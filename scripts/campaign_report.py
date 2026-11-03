"""Tableau consolidé des scores d'une campagne, depuis le résumé figé."""
from __future__ import annotations

from pathlib import Path
from typing import Any


def consolidated_scores(summary: dict[str, Any]) -> list[dict[str, Any]]:
    """Une ligne par (dataset, split, système) : toutes les métriques calculées.

    Les références qui reçoivent le profil (QuasiLeak) restent dans leur
    propre champ, jamais mêlées aux valeurs des systèmes.
    """
    rows = []
    for entry in summary["results"]:
        values = {}
        for section in ("primary", "diagnostic"):
            for name, metric in (entry.get(section) or {}).items():
                if isinstance(metric, dict) and metric.get("value") is not None:
                    values[f"{section}.{name}"] = metric["value"]
        grouped = (entry.get("reference_d8_llm_grouping") or {}).get("official") or {}
        rows.append({"dataset": entry["dataset"], "split": entry["split"], "system": entry["system"],
                     "gold_aware": entry.get("gold_aware"), "status": entry.get("status"),
                     "publishable": entry.get("publishable"), "error": entry.get("error"), "metrics": values,
                     "reference_d8_llm_grouping_pgf1": (grouped.get("scores_0_100") or {}).get("P-GF1")})
    return rows


def write_scores_markdown(summary: dict[str, Any], path: Path) -> None:
    lines = ["# Scores de la campagne", "",
             "Valeurs brutes des scorecards ; `diagnostic.*` n'est jamais un chiffre officiel (SPEC-07 §9).", ""]
    for dataset in dict.fromkeys(r["dataset"] for r in summary["scores"]):
        rows = [r for r in summary["scores"] if r["dataset"] == dataset]
        names = sorted({n for r in rows for n in r["metrics"]})
        lines += [f"## {dataset}", "", "| système | " + " | ".join(names) + " | publiable |",
                  "|" + "---|" * (len(names) + 2)]
        for r in rows:
            label = r["system"] + (" (ancre gold)" if r["gold_aware"] else "")
            cells = [f"{r['metrics'][n]:.4g}" if isinstance(r["metrics"].get(n), (int, float)) else "—" for n in names]
            lines.append(f"| {label} | " + " | ".join(cells) + f" | {r['publishable']} |")
        lines.append("")
    for ref in summary["reference_results"]:
        scores = (ref.get("official") or {}).get("scores_0_100") or {}
        lines += [f"## Référence {ref['dataset']} — {ref['reference']} (reçoit le profil, hors comparaison)", "",
                  f"P-GF1 {scores.get('P-GF1')} · P-GP {scores.get('P-GP')} · P-GR {scores.get('P-GR')}", ""]
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")
