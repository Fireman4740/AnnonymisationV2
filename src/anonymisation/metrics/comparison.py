"""Comparaison inter-systèmes et validation de comparabilité (SPEC-07, SPEC-10).

Fournit :
- `assert_comparable_across_systems(scorecards)` : valide que tous les runs
  partagent le même dataset, le même split, le même protocole/version.
  Autorise la comparaison interne de valeurs PROXY/DIAGNOSTIC à condition que
  toutes les lignes partagent le même statut pour une métrique donnée ; les
  comparaisons externes/publicables relèvent de `assert_comparable()`, qui
  refuse tout chiffre PROXY ou DIAGNOSTIC.
- `render_comparison_markdown(scorecards)` : génère un tableau comparatif Markdown
  stable, avec colonnes normatives, trié par system_id, et une section de provenance.
"""

from __future__ import annotations

from collections.abc import Sequence
from typing import Any

from anonymisation.metrics.contracts import (
    MetricComparisonError,
    MetricStatus,
    MetricValue,
    assert_comparable,
)
from anonymisation.metrics.detailed_quality import METRICS as DETAILED_QUALITY_METRICS

__all__ = [
    "MetricComparisonError",
    "MetricStatus",
    "MetricValue",
    "assert_comparable",
    "assert_comparable_across_systems",
    "render_comparison_markdown",
]

#: Métriques dont la comparabilité est contrôlée ligne à ligne.
_CHECKED_METRICS: tuple[tuple[str, str], ...] = (
    *(("diagnostic", name) for name in sorted(DETAILED_QUALITY_METRICS)),
    ("primary", "cpr"),
    ("primary", "ipr"),
    ("primary", "reid_success_rate"),
    ("diagnostic", "span_precision"),
    ("diagnostic", "span_recall"),
    ("diagnostic", "span_f1"),
    ("diagnostic", "span_strict_f1"),
    ("diagnostic", "gold_leak_rate"),
    ("diagnostic", "direct_leak_rate"),
    ("diagnostic", "mask_coverage"),
    ("diagnostic", "tab_official"),
    ("diagnostic", "quasileak_group_mask_rate"),
    ("diagnostic", "utility_retention"),
    ("diagnostic", "task_f1_delta"),
    ("diagnostic", "local_readability"),
    ("diagnostic", "local_relevance"),
    ("diagnostic", "local_faithfulness"),
    ("diagnostic", "human_readability"),
    ("diagnostic", "human_relevance"),
    ("diagnostic", "human_faithfulness"),
    ("diagnostic", "qicr"),
    ("diagnostic", "male_k"),
    ("diagnostic", "brier"),
    ("diagnostic", "ece"),
)

#: Configuration d'un modèle évaluateur (attaquant, juge) qui conditionne la
#: valeur : deux anonymiseurs ne se comparent qu'à évaluateur identique (H-1).
_EVALUATOR_FIELDS: tuple[str, ...] = (
    "backend",
    "model",
    "temperature",
    "extra_body",
    "max_tokens",
    "default_max_output_tokens",
    "prompt_sha256",
    "module_sha256",
)


def _evaluator_signature(details: dict[str, Any]) -> tuple[Any, ...]:
    """Attaquant, juge et modèle de risque déclarés par la métrique, s'il y en a."""
    signature: list[Any] = []
    for role in ("attacker", "judge"):
        block = details.get(role)
        if isinstance(block, dict):
            signature.append((role, *(block.get(name) for name in _EVALUATOR_FIELDS)))
    risk = details.get("risk")
    if isinstance(risk, dict):
        signature.append(
            (
                "risk",
                *(
                    risk.get(name)
                    for name in ("population_n", "threshold", "repeats", "population_sha256")
                ),
            )
        )
    return tuple(signature)


def _assert_same_ground_truth(scorecards: Sequence[dict[str, Any]]) -> None:
    """Refuse des runs scorés contre des pivots gold différents.

    Même dataset et même split ne suffisent pas : une ré-ingestion ou une autre
    sélection de documents change la vérité terrain. Les empreintes du pivot
    effectivement lu par ``score`` (``inputs.pivot``) doivent coïncider ; une
    carte qui n'en porte pas (ancien scorer) n'est pas vérifiable ici.
    """
    pivots = [
        (idx, (sc.get("inputs") or {}).get("pivot")) for idx, sc in enumerate(scorecards, start=1)
    ]
    known = [(idx, pivot) for idx, pivot in pivots if isinstance(pivot, dict)]
    if not known:
        return
    ref_idx, reference = known[0]
    for idx, pivot in known[1:]:
        if pivot != reference:
            raise MetricComparisonError(
                f"Scorecard #{idx} scorée sur une autre vérité terrain que la #{ref_idx} "
                "(empreintes `inputs.pivot` différentes) : ré-ingestion ou sélection "
                "de documents divergente — rescorer contre le même pivot."
            )


def _assert_same_scored_documents(scorecards: Sequence[dict[str, Any]]) -> None:
    """Refuse des runs dont les documents effectivement scorés diffèrent.

    Un document en erreur est exclu du scoring ; deux systèmes aux erreurs
    différentes seraient sinon classés sur des sous-ensembles différents du
    même pivot. Rescorer sur l'intersection ou corriger les erreurs.
    """
    digests = [
        (idx, (sc.get("accounting") or {}).get("scored_doc_ids_sha256"))
        for idx, sc in enumerate(scorecards, start=1)
    ]
    known = [(idx, digest) for idx, digest in digests if digest is not None]
    for idx, digest in known[1:]:
        if digest != known[0][1]:
            raise MetricComparisonError(
                f"Scorecard #{idx} : documents scorés différents de la #{known[0][0]} "
                "(erreurs de prédiction différentes) — classement refusé ; corriger les "
                "erreurs ou rescorer sur l'intersection des documents."
            )


#: Statuts non publiables : la valeur existe, mais ne porte aucune garantie de
#: comparabilité externe (cf. ``assert_comparable``).
_NON_PUBLISHABLE = (MetricStatus.DIAGNOSTIC.value, MetricStatus.PROXY.value)

#: Statuts sans valeur affichée : la ligne rend « — », rien n'est comparé.
_NO_VALUE = (MetricStatus.UNAVAILABLE.value, MetricStatus.FAILED.value)


def _status_of(block: Any) -> str | None:
    if not isinstance(block, dict):
        return None
    status = block.get("status")
    return str(status) if status is not None else None


def _annotate(value: str, status: str | None) -> str:
    """Suffixe une valeur affichée par son statut quand il n'est pas publiable."""
    if value == "—" or status is None:
        return value
    if status in _NON_PUBLISHABLE:
        return f"{value} ({status[:4].upper()})"
    if status == MetricStatus.SAMPLED.value:
        return f"{value} (SAMP)"
    return value


def assert_comparable_across_systems(scorecards: Sequence[dict[str, Any]]) -> None:
    """Exige même dataset, split, protocole/version et cohérence de statut."""
    if not scorecards:
        raise MetricComparisonError("Aucune scorecard fournie pour la comparaison.")

    ref = scorecards[0]
    ref_ds = ref.get("dataset")
    ref_split = ref.get("split")
    ref_protocol = ref.get("protocol")
    ref_proto_ver = ref.get("protocol_version")

    for idx, sc in enumerate(scorecards[1:], start=2):
        ds = sc.get("dataset")
        split = sc.get("split")
        proto = sc.get("protocol")
        proto_ver = sc.get("protocol_version")

        if ds != ref_ds:
            raise MetricComparisonError(
                f"Scorecard #{idx} dataset incompatible : attendu {ref_ds!r}, obtenu {ds!r}"
            )
        if split != ref_split:
            raise MetricComparisonError(
                f"Scorecard #{idx} split incompatible : attendu {ref_split!r}, obtenu {split!r}"
            )
        if proto != ref_protocol or proto_ver != ref_proto_ver:
            raise MetricComparisonError(
                f"Scorecard #{idx} protocole incompatible : attendu {ref_protocol}/{ref_proto_ver}, obtenu {proto}/{proto_ver}"
            )

    versions = {sc.get("schema_version") for sc in scorecards}
    if len(versions) > 1:
        raise MetricComparisonError(
            "Schémas de scorecards différents : rescorer avec le même noyau"
        )
    scoring = [sc.get("scoring") for sc in scorecards]
    if any(s is not None for s in scoring) and any(s != scoring[0] for s in scoring[1:]):
        raise MetricComparisonError("Code de scoring différent : rescorer avec le même noyau")
    _assert_same_ground_truth(scorecards)
    _assert_same_scored_documents(scorecards)

    # Chaque métrique prend pour référence sa première valeur disponible,
    # même si la première scorecard ne peut pas la produire.
    for section, metric in _CHECKED_METRICS:
        reference: tuple[str, tuple[Any, ...]] | None = None
        values = 0
        for idx, sc in enumerate(scorecards, start=1):
            if sc.get("publishable") is False:
                continue
            block = (sc.get(section) or {}).get(metric)
            status = _status_of(block)
            if status is None or status in _NO_VALUE or block.get("value") is None:
                continue
            details = block.get("details") or {}
            values += 1
            context = details.get("evaluation_context")
            if (metric in {"utility_retention", "task_f1_delta", "human_readability", "human_relevance", "human_faithfulness", "local_readability", "local_relevance", "local_faithfulness"} or metric in DETAILED_QUALITY_METRICS) and isinstance(context, dict):
                # Le fichier de notes dépend du système ; il est vérifié par score,
                # mais son empreinte ne doit pas rendre les notes incomparables.
                context = {key: context.get(key) for key in ("pivot", "successful_doc_ids")}
            signature = (
                block.get("protocol", sc.get("protocol")),
                block.get("protocol_version", sc.get("protocol_version")),
                details.get("definition_id"),
                details.get("denominator"),
                _evaluator_signature(details),
                context,
                details.get("study_id"),
                details.get("fact_study_id"),
                details.get("fact_reference_sha256"),
                details.get("quality_applicability_sha256"),
                details.get("reviewers_by_doc_sha256"),
                details.get("event_contract"),
                details.get("evaluator"),
                details.get("model_sha256"),
                details.get("task"),
                details.get("labels"),
                details.get("k_threshold"),
            )
            if reference is None:
                reference = status, signature
                continue
            ref_status, ref_signature = reference
            if ref_status != status:
                raise MetricComparisonError(
                    f"Scorecard #{idx} statut incompatible pour {metric!r} : "
                    f"attendu {ref_status!r}, obtenu {status!r}"
                )
            if ref_signature != signature:
                raise MetricComparisonError(
                    f"Scorecard #{idx} définition incompatible pour {metric!r} : "
                    f"attendu {ref_signature!r}, obtenu {signature!r}. "
                    "Recalculer les anciennes scorecards avec le même scorer."
                )
        if (
            metric in ("gold_leak_rate", "direct_leak_rate")
            and values > 1
            and reference is not None
            and reference[1][2] is None
        ):
            raise MetricComparisonError(
                f"Définition non versionnée pour {metric!r} : comparaison invérifiable. "
                "Recalculer les anciennes scorecards avec le même scorer."
            )


def _fmt_metric(val: Any) -> str:
    if val is None or val == "—":
        return "—"
    if isinstance(val, dict):
        if val.get("status") in ("unavailable", "failed") or val.get("value") is None:
            return "—"
        v = val.get("value")
        if v is None:
            return "—"
        return f"{float(v):.4f}"
    if isinstance(val, (int, float)):
        return f"{float(val):.4f}"
    return str(val)


def _cell(block: Any) -> str:
    """Valeur formatée, suffixée de son statut quand il n'est pas publiable."""
    return _annotate(_fmt_metric(block), _status_of(block))


def render_comparison_markdown(scorecards: Sequence[dict[str, Any]]) -> str:
    """Affiche seulement le catalogue actif et les colonnes effectivement mesurées."""
    assert_comparable_across_systems(scorecards)
    cards = sorted(
        scorecards,
        key=lambda s: (
            str(s.get("system", {}).get("system_id", "")),
            str(s.get("system", {}).get("system_version", "")),
        ),
    )
    first = cards[0]
    labels = {
        "cpr": "CPR",
        "ipr": "IPR",
        "reid_success_rate": "R_succ",
        "span_precision": "Précision spans",
        "span_recall": "Rappel spans",
        "span_f1": "F1 spans",
        "span_strict_f1": "F1 strict",
        "gold_leak_rate": "Fuite gold",
        "direct_leak_rate": "Fuite directe",
        "mask_coverage": "Couverture gold",
        "tab_official": "Rappel TAB officiel",
        "quasileak_group_mask_rate": "Groupes avec un indice masqué (proxy)",
        "utility_retention": "Rétention tâche",
        "task_f1_delta": "Δ F1 tâche",
        "local_readability": "Lisibilité (juge local)",
        "local_relevance": "Pertinence (juge local)",
        "local_faithfulness": "Fidélité (juge local)",
        "quality_understandable": "Compréhension (juge local)",
        "quality_grammar": "Grammaire (juge local)",
        "quality_references": "Références (juge local)",
        "quality_main_information": "Information principale (juge local)",
        "quality_no_contradiction": "Absence de contradiction (juge local)",
        "quality_no_invention": "Absence d'invention (juge local)",
        "quality_errors_per_document": "Erreurs détectées/document (juge local)",
        "quality_fact_retention": "Faits conservés (juge local)",
        "quality_fact_omission": "Faits omis (juge local)",
        "quality_fact_contradiction": "Faits contredits (juge local)",
        "human_readability": "Lisibilité humaine",
        "human_relevance": "Pertinence humaine",
        "human_faithfulness": "Fidélité humaine",
        "qicr": "QICR (détection)",
        "male_k": "MALE-k",
        "brier": "Brier (événement)",
        "ece": "ECE (événement)",
    }
    columns = [
        (section, name)
        for section, name in _CHECKED_METRICS
        if any(
            sc.get(section, {}).get(name, {}).get("value") is not None
            for sc in cards
            if sc.get("publishable") is not False
        )
    ]
    lines = [
        f"# Comparaison des systèmes — {first.get('dataset')} ({first.get('split')})",
        "",
        f"**Protocole :** `{first.get('protocol')}` (version `{first.get('protocol_version')}`)",
        f"**Nombre de systèmes comparés :** {len(cards)}",
        "",
        "> DIAG, SAMP et PROX désignent des statuts diagnostiques, échantillonnés ou historiques approchés. "
        "Les scores des runs bloqués ne sont pas utilisés pour classer les systèmes.",
        "",
        "| Système | Version | "
        + " | ".join([labels[n] for _, n in columns] + ["Latence p50 (ms)", "Erreur"])
        + " |",
        "|" + "---|" * (len(columns) + 4),
    ]
    reasons = []
    for card in cards:
        identity = card.get("system") or {}
        name = identity.get("system_id", "unknown")
        blocked = card.get("publishable") is False
        values = [
            "—" if blocked else _cell(card.get(section, {}).get(key)) for section, key in columns
        ]
        latency = card.get("efficiency", {}).get("latency_p50_ms")
        lines.append(
            "| "
            + " | ".join(
                [
                    f"`{name}`",
                    f"`{identity.get('system_version', '1')}`",
                    *values,
                    f"{latency:.2f}" if latency is not None else "—",
                    f"{card.get('error_rate', 0.0):.1%}",
                ]
            )
            + " |"
        )
        if blocked:
            reasons.extend(
                f"- **{name}** : {reason}"
                for reason in card.get("publication_blockers", ["run bloqué"])
            )
        for section, key in columns:
            metric = card.get(section, {}).get(key)
            if isinstance(metric, dict) and metric.get("value") is None:
                reasons.append(
                    f"- **{name}** `{key}` : {metric.get('details', {}).get('reason', metric.get('status'))}"
                )
    if reasons:
        lines.extend(["", "## Provenance et statut des métriques indisponibles", "", *reasons])
    return "\n".join(lines) + "\n"
