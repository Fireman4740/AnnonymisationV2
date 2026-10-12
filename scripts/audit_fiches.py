"""Fiches d'audit par document d'un run figé (EPIC-H H-9).

Pour chaque document : texte original, gold, prédictions, décisions, texte
anonymisé, erreurs, devinettes et jugement de l'attaque RAT-Bench, jugement
d'utilité et contribution du document aux scores. Trois vérifications sont
**bloquantes** (code de sortie 1) — un écart inexpliqué entre texte et score
invalide le run :

1. offsets : ``text[start:end] == span_text`` pour tout gold et toute
   prédiction ancrés, et chaque décision retombe sur son ``original`` ;
2. reconstruction : appliquer les décisions figées (``KEEP`` exclu, fusion
   des chevauchements, ``apply_decisions``) redonne **exactement** le texte
   anonymisé figé — constater qu'un remplacement apparaît quelque part ne
   suffit pas ;
3. cohérence attaque : la décision de ré-identification figée suit la règle
   (identifiant direct OU correctness ≥ 0,2).

Aucun modèle n'est appelé. Usage ::

    uv run --locked python scripts/audit_fiches.py runs/campaign/ratbench/eval/llm-full \\
        --processed data/processed --out runs/campaign/audit/ratbench-llm-full
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

from anonymisation.metrics.leakage import surface_present
from anonymisation.metrics.masking import document_coverage
from anonymisation.pipeline.orchestrator import _merge_overlapping
from anonymisation.transform.apply import apply_decisions
from anonymisation.transform.decisions import Action, AnonymizationDecision

REID_THRESHOLD = 0.2


def _jsonl(path: Path) -> list[dict[str, Any]]:
    if not path.is_file():
        return []
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]


def _offset_gaps(kind: str, spans: list[dict[str, Any]], text: str) -> list[str]:
    gaps = []
    for span in spans:
        start, end = span.get("start"), span.get("end")
        if start is None or end is None:
            continue
        if text[start:end] != span.get("span_text"):
            gaps.append(f"{kind} {span.get('annotation_id')} : texte[{start}:{end}]="
                        f"{text[start:end]!r} ≠ span_text={span.get('span_text')!r}")
    return gaps


def _reconstruct(text: str, decisions: list[dict[str, Any]]) -> str:
    actionable = [
        AnonymizationDecision(
            start=d["start"], end=d["end"], original=d["original"], action=Action(d["action"]),
            replacement=d["replacement"], qi_category=d["qi_category"], reason=d["reason"],
            risk_before=d.get("risk_before"), risk_after=d.get("risk_after"),
            meta=dict(d.get("meta") or {}),
        )
        for d in decisions if d["action"] != Action.KEEP.value
    ]
    return apply_decisions(text, _merge_overlapping(actionable, text)).anonymized_text


def audit_document(document: dict[str, Any], gold: list[dict[str, Any]], record: dict[str, Any],
                   attack: dict[str, Any] | None, judgment: dict[str, Any] | None,
                   uses_decisions: bool) -> dict[str, Any]:
    text = document["text"]
    gaps: list[str] = []
    sheet: dict[str, Any] = {"doc_id": document["doc_id"], "status": record.get("status"),
                             "errors": record.get("error")}
    gaps += _offset_gaps("gold", gold, text)
    if record.get("status") not in ("ok", "partial"):
        return {**sheet, "gaps": gaps, "scored": False}
    predictions = record.get("annotations") or []
    decisions = record.get("decisions") or []
    gaps += _offset_gaps("prédiction", predictions, text)
    for decision in decisions:
        if text[decision["start"]:decision["end"]] != decision["original"]:
            gaps.append(f"décision {decision['action']} [{decision['start']}:{decision['end']}] "
                        f"hors texte : {decision['original']!r}")
    anonymized = record["anonymized_text"]
    reconstruction = None
    if uses_decisions:
        try:
            reconstruction = _reconstruct(text, decisions)
        except ValueError as exc:
            gaps.append(f"reconstruction impossible : {exc}")
        else:
            if reconstruction != anonymized:
                gaps.append("texte anonymisé figé ≠ reconstruction depuis les décisions")
    leaks = [{"surface": g["span_text"], "category": g["qi_categories"],
              "present": surface_present(g["span_text"], anonymized)}
             for g in gold if g.get("span_text")]
    coverage = document_coverage(gold, decisions, text).to_dict()
    sheet.update(
        scored=True, original_text=text, anonymized_text=anonymized,
        reconstruction_identical=None if reconstruction is None else reconstruction == anonymized,
        gold=[{k: g.get(k) for k in ("annotation_id", "start", "end", "span_text", "qi_categories",
                                       "identifier_type", "expression_mode")} for g in gold],
        predictions=[{k: p.get(k) for k in ("start", "end", "span_text", "qi_categories")}
                     for p in predictions],
        decisions=[{k: d.get(k) for k in ("start", "end", "original", "action", "replacement",
                                           "qi_category")} for d in decisions],
        contribution={"gold_surfaces": len(leaks), "leaked": sum(x["present"] for x in leaks),
                      "mask_coverage": coverage},
        leaks=leaks,
    )
    if attack is not None:
        sheet["attack"] = {k: attack.get(k) for k in (
            "status", "error", "guesses", "unanswered_attributes", "correctness",
            "correct_direct_ids", "encoded_record", "correctmatch_draws",
            "correctmatch_correctness", "reidentified")}
        if attack.get("status") == "ok":
            p = attack.get("correctmatch_correctness")
            expected = bool(attack["correct_direct_ids"]) or (p is not None and p >= REID_THRESHOLD)
            if expected != attack["reidentified"]:
                gaps.append("décision de ré-identification incohérente avec la règle officielle")
    if judgment is not None:
        sheet["utility_judgment"] = {k: judgment.get(k) for k in (
            "status", "error", "readability", "meaning", "hallucinations", "rougeL", "utility_comb")}
    return {**sheet, "gaps": gaps}


def _markdown(sheet: dict[str, Any]) -> str:
    lines = [f"# Fiche d'audit — `{sheet['doc_id']}`", "",
             f"- statut : `{sheet['status']}` ; écarts : **{len(sheet['gaps'])}**"]
    for gap in sheet["gaps"]:
        lines.append(f"  - ⚠️ {gap}")
    if not sheet.get("scored"):
        lines.append(f"- erreur : `{sheet.get('errors')}` (document exclu du scoring)")
        return "\n".join(lines) + "\n"
    c = sheet["contribution"]
    lines += [f"- reconstruction depuis les décisions : `{sheet['reconstruction_identical']}`",
              f"- surfaces gold encore présentes : {c['leaked']}/{c['gold_surfaces']}",
              f"- couverture des masques : {c['mask_coverage']}", "",
              "## Texte original", "", "```", sheet["original_text"], "```", "",
              "## Texte anonymisé", "", "```", sheet["anonymized_text"], "```", "",
              "## Gold", ""]
    lines += [f"- `{g['span_text']}` [{g['start']}:{g['end']}] {g['qi_categories']} "
              f"{g['identifier_type']} → {'FUIT' if any(x['surface'] == g['span_text'] and x['present'] for x in sheet['leaks']) else 'protégé'}"
              for g in sheet["gold"]]
    lines += ["", "## Décisions appliquées", ""]
    lines += [f"- {d['action']} [{d['start']}:{d['end']}] `{d['original']}` → `{d['replacement']}` "
              f"({d['qi_category']})" for d in sheet["decisions"]] or ["- aucune"]
    if "attack" in sheet:
        a = sheet["attack"]
        lines += ["", "## Attaque RAT-Bench", "", f"- statut : `{a['status']}` {a.get('error') or ''}",
                  f"- devinettes : `{a.get('guesses')}`", f"- non répondus : `{a.get('unanswered_attributes')}`",
                  f"- jugement : `{a.get('correctness')}`",
                  f"- identifiants directs justes : `{a.get('correct_direct_ids')}`",
                  f"- enregistrement PUMS : `{a.get('encoded_record')}`",
                  f"- CorrectMatch (10 tirages) : `{a.get('correctmatch_draws')}` → "
                  f"`{a.get('correctmatch_correctness')}`",
                  f"- **ré-identifié : `{a.get('reidentified')}`**"]
    if "utility_judgment" in sheet:
        lines += ["", "## Jugement d'utilité", "", f"- `{sheet['utility_judgment']}`"]
    return "\n".join(lines) + "\n"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("run", type=Path)
    parser.add_argument("--processed", type=Path, default=Path("data/processed"))
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args(argv)
    lock = json.loads((args.run / "manifest.lock.json").read_text(encoding="utf-8"))
    dataset, split = lock["run"]["dataset"], lock["run"]["split"]
    base = args.processed / dataset / split
    documents = {d["doc_id"]: d for d in _jsonl(base / "documents.jsonl")}
    gold: dict[str, list[dict[str, Any]]] = {}
    for annotation in _jsonl(base / "annotations.jsonl"):
        gold.setdefault(annotation["doc_id"], []).append(annotation)
    attacks = {r["doc_id"]: r for r in _jsonl(args.run / "attacks.jsonl")}
    judgments = {r["doc_id"]: r for r in _jsonl(args.run / "judgments.jsonl")}
    uses_decisions = "decisions" in (lock.get("system") or {}).get("capabilities", [])
    args.out.mkdir(parents=True, exist_ok=True)
    sheets = []
    for record in _jsonl(args.run / "predictions.jsonl"):
        doc_id = record["doc_id"]
        sheet = audit_document(documents[doc_id], gold.get(doc_id, []), record,
                               attacks.get(doc_id), judgments.get(doc_id), uses_decisions)
        sheets.append(sheet)
        safe = doc_id.replace(":", "_").replace("/", "_")
        (args.out / f"{safe}.md").write_text(_markdown(sheet), encoding="utf-8")
    summary = {"run": str(args.run), "dataset": dataset, "split": split,
               "system": (lock.get("system") or {}).get("system_id"),
               "documents": len(sheets), "scored": sum(s.get("scored", False) for s in sheets),
               "gaps": sum(len(s["gaps"]) for s in sheets),
               "documents_with_gaps": [s["doc_id"] for s in sheets if s["gaps"]]}
    (args.out / "audit.json").write_text(json.dumps({"summary": summary, "sheets": sheets},
                                                    ensure_ascii=False, indent=2, sort_keys=True) + "\n",
                                         encoding="utf-8")
    print("AUDIT_FICHES", json.dumps(summary, ensure_ascii=False), flush=True)
    return 1 if summary["gaps"] else 0


if __name__ == "__main__":
    sys.exit(main())
