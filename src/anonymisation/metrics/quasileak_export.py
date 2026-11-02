"""Adaptateur QuasiLeak de l'annexe D.8 pour les anonymiseurs du banc.

L'article (Zhu et al., arXiv:2610.21333, §5.3 et annexe D.8) évalue les
détecteurs qui ne produisent que des spans par un protocole commun, repris ici
sans changement de principe :

1. seuls les spans que le système a lui-même retenus deviennent des indices
   (ici : ses décisions de transformation, **avant** toute politique de
   divulgation — une décision remise en clair par la politique garde son
   action initiale dans ``meta.disclosure``) ;
2. une table **fixe** traduit les étiquettes natives vers les huit attributs ;
   le reste vaut ``OTHER`` et n'est jamais rapporté ;
3. les spans d'un même attribut forment un groupe ;
4. la politique fournie par le document décide si le groupe est rapporté :
   seuls les groupes d'un attribut ``HIDE`` le sont ;
5. ``E_R`` pré-politique : rappel des indices HIDE sur **tout** l'inventaire
   de spans, avant traduction, regroupement et filtrage.

Conséquence : le P-GF1 D.8 ne dépend pas de l'étape de divulgation du banc
(qui ne retire que des décisions KEEP/NEUTRAL, filtrées ici de toute façon) ;
cette étape agit sur le texte produit, donc sur l'utilité.

La table d'attributs vient de ``configs/policy/disclosure.yaml`` (source
unique partagée avec l'étape de divulgation). Les offsets sont ceux du système,
sans relocalisation textuelle : pas d'ambiguïté d'occurrence à arbitrer.

Limites : un groupe par attribut fusionne deux groupes gold d'un même attribut
(l'article l'accepte : aucun document n'a deux groupes gold d'un même
attribut) ; la catégorie choisie par le système détermine l'attribut.
"""
from __future__ import annotations

import json
from collections import defaultdict
from collections.abc import Iterable, Mapping
from pathlib import Path

from anonymisation.metrics.vendor import quasileak_score as official_scorer
from anonymisation.schema.io import atomic_write, sha256_file, write_json

EXPORT_PROTOCOL = 'quasileak-d8-span-adapter-v1'
ER_PROTOCOL = 'quasileak-d8-pre-policy-evidence-recall-v1'


def category_to_attribute(label_map: Mapping[str, object]) -> dict[str, str]:
    """Inverse d'un label_map de manifeste ; refuse une catégorie partagée."""
    inverse: dict[str, str] = {}
    for attribute, mapping in label_map.items():
        for code in mapping.qi_categories:
            if code in inverse:
                raise ValueError(f'label_map quasileak : {code!r} rattaché à {inverse[code]!r} et {attribute!r}')
            inverse[code] = attribute
    return inverse


def pre_policy_inventory(decisions: Iterable[Mapping]) -> list[dict]:
    """Décisions retenues par le système avant toute politique de divulgation."""
    kept = []
    for decision in decisions:
        if decision['action'] != 'KEEP':
            kept.append(decision)
        elif (decision.get('meta') or {}).get('disclosure'):
            kept.append({**decision, 'action': decision['meta']['disclosure']['initial_action']})
    return kept


def _groups(decisions: list[dict], mapping: Mapping[str, str], hide: set[str] | None) -> tuple[list[dict], int, int]:
    spans: dict[str, set[tuple[int, int]]] = defaultdict(set)
    unmapped = filtered = 0
    for decision in decisions:
        attribute = mapping.get(decision['qi_category'])
        if attribute is None:
            unmapped += 1
            continue
        spans[attribute].add((decision['start'], decision['end']))
    evidence = []
    for attribute in sorted(spans):
        if hide is not None and attribute not in hide:
            filtered += 1
            continue
        evidence.append({'attribute': attribute,
                         'spans': [{'start': s, 'end': e} for s, e in sorted(spans[attribute])]})
    return evidence, unmapped, filtered


def _run_rows(run_dir: Path, ids: list[str]) -> dict[str, dict]:
    rows: dict[str, dict] = {}
    for line in (run_dir / 'predictions.jsonl').read_text(encoding='utf-8').splitlines():
        if line.strip():
            row = json.loads(line)
            if row['doc_id'] in rows:
                raise ValueError(f'{run_dir} : doc_id dupliqué {row["doc_id"]!r}')
            rows[row['doc_id']] = row
    if set(rows) != set(ids):
        raise ValueError(f'{run_dir} : documents du run ≠ sélection '
                         f'({len(set(ids) - set(rows))} absents, {len(set(rows) - set(ids))} en trop)')
    return rows


def export_run(run_dir: Path, selection: Path, out: Path, *, mapping: Mapping[str, str],
               dataset_sha256: str, split_sha256: str, policies: Mapping[str, Mapping] | None = None,
               table: str | None = None) -> dict:
    """Écrit le JSONL officiel et son verrou ; un document en erreur reste en erreur.

    ``policies`` (sample_id → politique fournie) active le filtrage D.8 ; sans
    elle, tous les groupes d'attributs sont rapportés (diagnostic non D.8).
    """
    ids = json.loads(selection.read_text(encoding='utf-8'))
    rows = _run_rows(run_dir, ids)
    result, errors, unmapped, groups, filtered = [], 0, 0, 0, 0
    for doc_id in ids:
        row = rows[doc_id]
        # « partial » = décisions complètes avec avertissements ; « error » = pas de décision fiable.
        if row['status'] not in {'ok', 'partial'}:
            errors += 1
            result.append({'sample_id': doc_id, 'status': 'error', 'error': row.get('error')})
            continue
        hide = None if policies is None else set(policies[doc_id]['hide'])
        evidence, skipped, dropped = _groups(pre_policy_inventory(row['decisions']), mapping, hide)
        unmapped, filtered, groups = unmapped + skipped, filtered + dropped, groups + len(evidence)
        result.append({'sample_id': doc_id, 'evidence': evidence})
    out.parent.mkdir(parents=True, exist_ok=True)
    with atomic_write(out) as stream:
        for item in result:
            stream.write(json.dumps(item, ensure_ascii=False, sort_keys=True) + '\n')
    lock = {'protocol': EXPORT_PROTOCOL if policies is not None else EXPORT_PROTOCOL + '-unfiltered',
            'attribute_table': table, 'policy_filter': policies is not None,
            'run_predictions_sha256': sha256_file(run_dir / 'predictions.jsonl'),
            'dataset_sha256': dataset_sha256, 'split_manifest_sha256': split_sha256,
            'selection_sha256': sha256_file(selection), 'predictions_sha256': sha256_file(out),
            'category_to_attribute': dict(sorted(mapping.items())), 'documents': len(ids),
            'errors': errors, 'groups': groups, 'groups_filtered_by_policy': filtered,
            'unmapped_decisions': unmapped}
    write_json(out.with_suffix(out.suffix + '.lock.json'), lock)
    return lock


def pre_policy_evidence_recall(run_dir: Path, gold_rows: Iterable[Mapping]) -> dict:
    """E_R pré-politique de l'annexe D.8, avec les fonctions du scorer officiel.

    Inventaire = toutes les décisions retenues avant politique, dédupliquées
    par offsets ; appariement un-à-un avec les indices des groupes HIDE à
    l'IoU de tokens θ du scorer. Les documents en erreur sont refusés.
    """
    gold_rows = list(gold_rows)
    rows = _run_rows(run_dir, [r['sample_id'] for r in gold_rows])
    found = total = inventory = 0
    for gold in gold_rows:
        row = rows[gold['sample_id']]
        if row['status'] not in {'ok', 'partial'}:
            raise ValueError(f"{gold['sample_id']} : document en erreur, E_R pré-politique non calculable")
        doc = gold['document']
        offsets = [(m.start(), m.end()) for m in official_scorer.TOKEN.finditer(doc)]
        intervals = sorted({(d['start'], d['end']) for d in pre_policy_inventory(row['decisions'])})
        inventory += len(intervals)
        spans = {s['span_id']: s for s in gold['gold']['spans']}
        hide = set(gold['policy']['hide'])
        cues = [official_scorer.token_set((spans[c]['start'], spans[c]['end']), offsets)
                for g in gold['gold']['groups'] if g['attribute'] in hide for c in g['cue_ids']]
        total += len(cues)
        if cues:
            predicted = [official_scorer.token_set(x, offsets) for x in intervals]
            found += len(official_scorer.match(predicted, cues, official_scorer.THETA))
    return {'protocol': ER_PROTOCOL, 'value': found / total if total else None, 'cues_found': found,
            'cues_hide': total, 'inventory_spans': inventory, 'theta': official_scorer.THETA}
