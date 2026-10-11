"""Évaluation TAB par l'évaluateur ORIGINAL (EPIC-H H-8).

Les métriques de TAB (Pilán et al., 2022) ne se réduisent pas à un rappel de
spans : couverture d'une mention modulo les tokens sans contenu (POS ignorés,
caractères de ponctuation), micro-moyenne entre annotateurs, rappel d'entité
qui exige toutes les mentions, précision par token. Les réimplémenter ferait
diverger les chiffres ; on appelle donc ``evaluation.py`` du dépôt officiel,
recopié tel quel dans :mod:`anonymisation.metrics.vendor.tab_evaluation`.

Cet adaptateur ne fait que deux choses :

* reconstruire le fichier gold attendu par ``GoldCorpus`` à partir des
  **enregistrements source** de TAB (fichier verrouillé à l'ingestion), limité
  aux documents scorés ;
* convertir les **décisions appliquées** du run (``KEEP`` exclu) en
  ``MaskedDocument`` — c'est ce que le système masque réellement.

La pondération BERT du contenu informationnel est une option de l'original,
désactivée par défaut (``--use_bert``) : on suit ce défaut et on le déclare.
"""

from __future__ import annotations

import json
import tempfile
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Any, Final

TAB_COMMIT: Final[str] = "558e09e26d6b36f5f78440074e6a233946d98bd9"
_KEEP = "KEEP"


class TabEvaluationError(ValueError):
    """Gold TAB introuvable ou masques incohérents."""


def masked_spans(decisions: Sequence[Mapping[str, Any]]) -> list[tuple[int, int]]:
    spans = []
    for decision in decisions:
        action = str(getattr(decision.get("action"), "value", decision.get("action")))
        if action.upper() == _KEEP:
            continue
        spans.append((int(decision["start"]), int(decision["end"])))
    return sorted(spans)


def evaluate_tab(
    source_records: Sequence[Mapping[str, Any]],
    masks: Mapping[str, Sequence[tuple[int, int]]],
) -> dict[str, Any]:
    """Mesures officielles de TAB sur les documents de ``masks`` (identifiants source)."""
    from anonymisation.metrics.vendor import tab_evaluation as official

    wanted = set(masks)
    gold = [dict(record) for record in source_records if record["doc_id"] in wanted]
    missing = wanted - {record["doc_id"] for record in gold}
    if missing:
        raise TabEvaluationError(
            f"documents TAB absents du gold source verrouillé : {sorted(missing)[:3]}"
        )
    with tempfile.TemporaryDirectory(prefix="tab-official-") as tmp:
        path = Path(tmp) / "gold.json"
        path.write_text(json.dumps(gold, ensure_ascii=False), encoding="utf-8")
        corpus = official.GoldCorpus(str(path))
    masked = [official.MaskedDocument(doc_id, list(spans)) for doc_id, spans in sorted(masks.items())]
    measures = official.evaluate(corpus, masked, use_bert=False)
    return {
        "measures": measures,
        "documents": len(masked),
        "evaluator": f"NorskRegnesentral/text-anonymization-benchmark@{TAB_COMMIT} evaluation.py",
        "use_bert": False,
    }


__all__ = ["TAB_COMMIT", "TabEvaluationError", "evaluate_tab", "masked_spans"]
