"""Prépare une grille humaine locale à partir d'un run figé.

Les notes `null` doivent être remplies manuellement avant l'étape evaluate.
L'option --review-out exporte le texte original et le texte anonymisé :
le fichier produit contient des données potentiellement personnelles.
"""
from __future__ import annotations

import argparse
import hashlib
from pathlib import Path

from anonymisation.cli import score
from anonymisation.metrics.text_quality import RUBRIC
from anonymisation.schema.io import write_json


def prepare(run: Path, output: Path, *, study_id: str, raters: list[str], review_out: Path | None = None, readability_out: Path | None = None) -> int:
    if not study_id.strip() or len(raters) < 2 or len(set(raters)) != len(raters) or any(not r.strip() for r in raters):
        raise ValueError("study-id et au moins deux pseudonymes d'évaluateurs distincts sont requis")
    lock = score._read_json(run / score.LOCK_NAME)
    dataset, split = lock["run"]["dataset"], lock["run"]["split"]
    score._verify_inputs(run, lock, dataset, split)
    predictions = score._read_predictions(run / score.PREDICTIONS_NAME)
    selected = [p for p in predictions if p.get("status") in {"ok", "partial"}]
    if not selected or len({p['doc_id'] for p in selected}) != len(selected):
        raise ValueError("prédictions absentes ou doc_id dupliqué")
    rows = []
    for p in selected:
        text = p.get("anonymized_text")
        if not isinstance(text, str):
            raise ValueError("texte anonymisé manquant")
        rows.append({"doc_id": p["doc_id"], "anonymized_sha256": hashlib.sha256(text.encode()).hexdigest(),
                     "ratings": [{"rater": r, "readability": None, "relevance": None, "faithfulness": None} for r in raters]})
    if readability_out is not None:
        write_json(readability_out, {"documents": [{"doc_id": p["doc_id"], "anonymized": p["anonymized_text"]} for p in selected]})
    if review_out is not None:
        docs, _ = score._load_gold(dataset, split)
        if any(p["doc_id"] not in docs for p in selected):
            raise ValueError("document absent du pivot")
        write_json(review_out, {"sensitive_original_texts": True, "documents": [
            {"doc_id": p["doc_id"], "original": docs[p["doc_id"]].text, "anonymized": p["anonymized_text"]}
            for p in selected]})
    write_json(output, {"rubric": RUBRIC, "evaluator": "human", "study_id": study_id, "rows": rows})
    return len(rows)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--run", type=Path, required=True)
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--study-id", required=True)
    parser.add_argument("--raters", nargs="+", required=True)
    parser.add_argument("--review-out", type=Path, help="Fichier local contenant les textes originaux et anonymisés.")
    parser.add_argument("--readability-out", type=Path, help="Fichier séparé pour juger la lisibilité à l'aveugle de l'original.")
    args = parser.parse_args()
    count = prepare(args.run, args.out, study_id=args.study_id, raters=args.raters,
                    review_out=args.review_out, readability_out=args.readability_out)
    print(f"{count} document(s) : compléter les notes avant evaluate.")


if __name__ == "__main__":
    main()
