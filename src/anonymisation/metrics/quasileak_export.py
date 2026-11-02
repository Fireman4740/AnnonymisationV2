"""Export des décisions d'un anonymiseur au format groupé officiel QuasiLeak.

Le scorer officiel attend, par document, des groupes ``{attribute, spans}``.
Un anonymiseur du banc ne produit que des décisions isolées portant une
catégorie de la taxonomie. Cet export est la projection la plus directe et
non réglée de ces décisions :

- seules les décisions dont l'action n'est pas ``KEEP`` comptent : ce sont
  les indices que le système a effectivement retirés du texte ;
- l'attribut est l'inverse **strict** du ``label_map`` du manifeste
  (GEN_EDUCATION → education, …). Une catégorie absente de cette table
  (identifiants directs, HR_*, SUP_*, GEN_GEO…) n'est rattachée à aucun
  attribut et n'est pas exportée ; elle est comptée dans le verrou ;
- un groupe par (document, attribut), avec tous les spans de cet attribut.

Aucune information gold n'est lue : ni annotations, ni groupes, ni politique.
L'anonymiseur ne connaît pas la politique HIDE/KEEP : un groupe exporté sur un
attribut KEEP est donc pénalisé par le scorer, ce qui mesure fidèlement un
système qui masque sans tenir compte de la politique.

Limites : le regroupement par attribut fusionne deux groupes gold d'un même
attribut et ne sépare pas les indices non liés ; un attribut que le système
étiquette autrement (ex. HR_JOB_TITLE pour un métier) est perdu. Le P-GF1
obtenu mesure la détection groupée implicite des décisions, pas la
confidentialité résiduelle du texte anonymisé.
"""
from __future__ import annotations

import json
from collections import defaultdict
from collections.abc import Mapping
from pathlib import Path

from anonymisation.schema.io import atomic_write, sha256_file, write_json

EXPORT_PROTOCOL = 'quasileak-decision-groups-v1'


def category_to_attribute(label_map: Mapping[str, object]) -> dict[str, str]:
    """Inverse du label_map ; refuse une catégorie partagée par deux attributs."""
    inverse: dict[str, str] = {}
    for attribute, mapping in label_map.items():
        for code in mapping.qi_categories:
            if code in inverse:
                raise ValueError(f'label_map quasileak : {code!r} rattaché à {inverse[code]!r} et {attribute!r}')
            inverse[code] = attribute
    return inverse


def _groups(decisions: list[dict], mapping: Mapping[str, str]) -> tuple[list[dict], int]:
    spans: dict[str, set[tuple[int, int]]] = defaultdict(set)
    unmapped = 0
    for decision in decisions:
        if decision['action'] == 'KEEP':
            continue
        attribute = mapping.get(decision['qi_category'])
        if attribute is None:
            unmapped += 1
            continue
        spans[attribute].add((decision['start'], decision['end']))
    evidence = [{'attribute': a, 'spans': [{'start': s, 'end': e} for s, e in sorted(spans[a])]}
                for a in sorted(spans)]
    return evidence, unmapped


def export_run(run_dir: Path, selection: Path, out: Path, *, mapping: Mapping[str, str],
               dataset_sha256: str, split_sha256: str) -> dict:
    """Écrit le JSONL officiel et son verrou ; un document en erreur reste en erreur."""
    ids = json.loads(selection.read_text(encoding='utf-8'))
    rows = {}
    for line in (run_dir / 'predictions.jsonl').read_text(encoding='utf-8').splitlines():
        if line.strip():
            row = json.loads(line)
            if row['doc_id'] in rows:
                raise ValueError(f'{run_dir} : doc_id dupliqué {row["doc_id"]!r}')
            rows[row['doc_id']] = row
    if set(rows) != set(ids):
        raise ValueError(f'{run_dir} : documents du run ≠ sélection '
                         f'({len(set(ids) - set(rows))} absents, {len(set(rows) - set(ids))} en trop)')
    result, errors, unmapped, groups = [], 0, 0, 0
    for doc_id in ids:
        row = rows[doc_id]
        # « partial » = décisions complètes avec avertissements ; « error » = pas de décision fiable.
        if row['status'] not in {'ok', 'partial'}:
            errors += 1
            result.append({'sample_id': doc_id, 'status': 'error', 'error': row.get('error')})
            continue
        evidence, skipped = _groups(row['decisions'], mapping)
        unmapped += skipped
        groups += len(evidence)
        result.append({'sample_id': doc_id, 'evidence': evidence})
    out.parent.mkdir(parents=True, exist_ok=True)
    with atomic_write(out) as stream:
        for item in result:
            stream.write(json.dumps(item, ensure_ascii=False, sort_keys=True) + '\n')
    lock = {'protocol': EXPORT_PROTOCOL, 'run_predictions_sha256': sha256_file(run_dir / 'predictions.jsonl'),
            'dataset_sha256': dataset_sha256, 'split_manifest_sha256': split_sha256,
            'selection_sha256': sha256_file(selection), 'predictions_sha256': sha256_file(out),
            'category_to_attribute': dict(sorted(mapping.items())), 'documents': len(ids),
            'errors': errors, 'groups': groups, 'unmapped_decisions': unmapped}
    write_json(out.with_suffix(out.suffix + '.lock.json'), lock)
    return lock
