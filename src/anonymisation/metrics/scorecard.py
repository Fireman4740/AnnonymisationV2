"""Construction et validation de scorecards (SPEC-07 §10, EPIC-D D-4).

Ce module ne charge aucun détecteur ni modèle. Il agrège uniquement les
prédictions figées, les annotations gold et le lock de run.
"""

from __future__ import annotations

from collections import defaultdict
from collections.abc import Iterable, Mapping, Sequence
from math import ceil
from statistics import median
from typing import Any

from anonymisation.metrics.accounting import RunAccounting
from anonymisation.metrics.contracts import MetricDirection, MetricStatus, MetricValue
from anonymisation.metrics.entities import (
    entity_protection_counts,
    field_value,
    same_identifier_type,
)
from anonymisation.metrics.gating import gate
from anonymisation.metrics.leakage import aggregate_leak_counts, gold_leak_counts
from anonymisation.metrics.protection import (
    LITERAL_ADVERSARY,
    collective_protection_rate,
    individual_protection_rate,
    subject_outcomes_from_run,
)
from anonymisation.metrics.spans import span_metrics, weighted_token_precision
from anonymisation.metrics.tria import TRIARecord, evaluate_trir
from anonymisation.metrics.utility import rouge_l
from anonymisation.schema.taxonomy import IdentifierType

SCORECARD_SCHEMA_VERSION = "2.0"
_REQUIRED_REPRODUCIBILITY = (
    "data_version",
    "taxonomy_version",
    "code",
    "models",
    "seeds",
    "prompts",
    "policy",
)
_REQUIRED_TOP_LEVEL = (
    "run_id",
    "schema_version",
    "system",
    "dataset",
    "split",
    "primary",
    "diagnostic",
    "by_language",
    "by_domain",
    "by_expression",
    "efficiency",
    "accounting",
)


class ScorecardError(ValueError):
    """Scorecard absente, incohérente ou non publiable."""


def _label(value: Any) -> str:
    """Sérialise un enum ou une chaîne en libellé de ventilation."""
    return str(getattr(value, "value", value))


def _status_label(status: Any) -> str:
    """Retourne le statut d'une métrique, enum ou chaîne, en minuscule."""
    return str(getattr(status, "value", status)).lower()


def _has_proxy_risk(record: Mapping[str, Any]) -> bool:
    """Détecte une évaluation de risque proxy dans une prédiction sérialisée."""
    risk = record.get("risk")
    if not isinstance(risk, Mapping):
        return False
    return _status_label(risk.get("status")) == MetricStatus.PROXY.value


def _metric_dict(
    name: str,
    value: float | None,
    *,
    protocol: str,
    protocol_version: str,
    status: MetricStatus,
    direction: MetricDirection,
    unit: str = "ratio",
    details: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    if value is None and status not in (MetricStatus.UNAVAILABLE, MetricStatus.FAILED):
        status = MetricStatus.UNAVAILABLE
    return MetricValue(
        name=name,
        value=value,
        protocol=protocol,
        protocol_version=protocol_version,
        status=status,
        direction=direction,
        unit=unit,
        details=dict(details or {}),
    ).to_dict()


def _aggregate_counts(
    records: Iterable[tuple[Sequence[Any], Sequence[Any]]], *, match: str = "partial"
) -> dict[str, Any]:
    totals = {"tp": 0, "fp": 0, "fn": 0, "gold": 0, "pred": 0}
    for gold, pred in records:
        result = span_metrics(gold, pred, match=match)
        for key in totals:
            totals[key] += result[key] or 0
    tp, fp, fn = totals["tp"], totals["fp"], totals["fn"]
    precision = tp / (tp + fp) if tp + fp else None
    recall = tp / (tp + fn) if tp + fn else None
    f1 = None if precision is None or recall is None else (
        0.0 if precision + recall == 0 else 2 * precision * recall / (precision + recall)
    )
    f2 = None if precision is None or recall is None else (
        0.0
        if 4 * precision + recall == 0
        else 5 * precision * recall / (4 * precision + recall)
    )
    return {
        "match": match,
        "tp": tp,
        "fp": fp,
        "fn": fn,
        "gold": totals["gold"],
        "pred": totals["pred"],
        "precision": precision,
        "recall": recall,
        "f1": f1,
        "f2": f2,
    }


def _percentile(values: Sequence[float], percentile: float) -> float | None:
    if not values:
        return None
    ordered = sorted(values)
    index = max(0, min(len(ordered) - 1, ceil(len(ordered) * percentile) - 1))
    return ordered[index]


def _group_metric(
    rows: Sequence[tuple[Sequence[Any], Sequence[Any], str]],
    *,
    match: str,
) -> dict[str, dict[str, Any]]:
    grouped: dict[str, list[tuple[Sequence[Any], Sequence[Any]]]] = defaultdict(list)
    for gold, pred, group in rows:
        grouped[group].append((gold, pred))
    output: dict[str, dict[str, Any]] = {}
    for group, pairs in sorted(grouped.items()):
        values = _aggregate_counts(pairs, match=match)
        values["documents"] = len(pairs)
        output[group] = values
    return output


def _entity_recall_over_rows(
    rows: Sequence[tuple[Sequence[Any], Sequence[Any], Any]],
    identifier_type: IdentifierType,
) -> tuple[float | None, int]:
    """Rappel entité agrégé sur le corpus, **calculé document par document**.

    Les offsets ne sont comparables qu'au sein d'un document : mettre en
    commun les spans de tout le corpus ferait « protéger » une mention du
    document A par une prédiction du document B située aux mêmes offsets, et
    fusionnerait en une entité unique deux homonymes de documents distincts.
    Retourne ``(rappel, nombre d'entités gold)`` ; le rappel vaut ``None`` si
    le corpus ne contient aucune entité gold de ce type.
    """
    protected = 0
    total = 0
    for gold, pred, _ in rows:
        gold_spans = [span for span in gold if same_identifier_type(span, identifier_type)]
        if not gold_spans:
            continue
        pred_spans = [span for span in pred if same_identifier_type(span, identifier_type)]
        doc_protected, doc_total = entity_protection_counts(
            gold_spans, pred_spans, identifier_type=identifier_type
        )
        protected += doc_protected
        total += doc_total
    return (protected / total if total else None), total


def _expression_rows(
    rows: Sequence[tuple[Sequence[Any], Sequence[Any], Any]],
) -> list[tuple[Sequence[Any], Sequence[Any], str]]:
    """Ventile gold **et** prédictions par mode d'expression.

    Sans ce filtrage, un document portant deux modes verserait l'intégralité
    de son gold et de ses prédictions dans chacun des deux seaux : les
    effectifs par mode dépasseraient ceux du corpus et chaque mode afficherait
    les erreurs de l'autre.
    """
    output: list[tuple[Sequence[Any], Sequence[Any], str]] = []
    for gold, pred, _ in rows:
        by_mode: dict[str, tuple[list[Any], list[Any]]] = {}
        for span in gold:
            mode = _label(field_value(span, "expression_mode", "unknown"))
            by_mode.setdefault(mode, ([], []))[0].append(span)
        for span in pred:
            mode = _label(field_value(span, "expression_mode", "unknown"))
            by_mode.setdefault(mode, ([], []))[1].append(span)
        for mode in sorted(by_mode):
            gold_spans, pred_spans = by_mode[mode]
            output.append((tuple(gold_spans), tuple(pred_spans), mode))
    return output


def _subject_of(
    record: Mapping[str, Any],
    gold_by_doc: Mapping[str, Sequence[Any]],
    documents_by_doc: Mapping[str, Any],
    strategy: str,
) -> str:
    """Clé sujet d'un document, selon la stratégie retenue pour le corpus."""
    doc_id = str(record.get("doc_id"))
    if strategy == "subject_id":
        for annotation in gold_by_doc.get(doc_id, ()):
            value = field_value(annotation, "subject_id", None)
            if value:
                return str(value)
    if strategy == "author_id":
        value = field_value(documents_by_doc.get(doc_id), "author_id", None)
        if value:
            return str(value)
    return doc_id


def build_scorecard(
    *,
    run_id: str,
    dataset: str,
    split: str,
    protocol: str,
    protocol_version: str,
    predictions: Sequence[Mapping[str, Any]],
    gold_by_doc: Mapping[str, Sequence[Any]],
    documents_by_doc: Mapping[str, Any],
    reproducibility: Mapping[str, Any],
    system: Mapping[str, Any],
    requested_status: MetricStatus | str = MetricStatus.DIAGNOSTIC,
    match: str = "partial",
) -> dict[str, Any]:
    """Agrège un run figé en scorecard SPEC-07 §10.

    Les lignes ``ok`` et ``partial`` alimentent les TP/FP/FN ; seules les
    lignes ``error`` en sont exclues. Toutes les
    lignes sont toutefois comptées par :class:`RunAccounting` et leur taux
    d'erreur est exposé au premier niveau.
    """
    validate_reproducibility(reproducibility)
    rows: list[tuple[Sequence[Any], Sequence[Any], Any]] = []
    runtimes: list[float] = []
    scored_predictions: list[Mapping[str, Any]] = []
    for record in predictions:
        # `partial` est scoré : le pipeline est allé au bout, il porte des
        # prédictions valides. Seul `error` est exclu (SPEC-10 C4).
        if str(record.get("status", "error")).lower() not in ("ok", "partial"):
            continue
        doc_id = str(record.get("doc_id", ""))
        document = documents_by_doc.get(doc_id)
        if document is None:
            raise ScorecardError(f"document absent du pivot gold : {doc_id!r}")
        pred = tuple(record.get("annotations") or ())
        gold = tuple(gold_by_doc.get(doc_id, ()))
        rows.append((gold, pred, document))
        scored_predictions.append(record)
        try:
            runtimes.append(float(record.get("runtime_ms", 0.0)))
        except (TypeError, ValueError) as exc:
            raise ScorecardError(f"runtime_ms invalide pour {doc_id!r}") from exc

    accounting = RunAccounting.from_predictions(predictions)
    status = (
        requested_status
        if isinstance(requested_status, MetricStatus)
        else MetricStatus(str(requested_status).lower())
    )
    status = accounting.status_for(status)
    if status is MetricStatus.OFFICIAL and any(_has_proxy_risk(record) for record in predictions):
        raise ScorecardError(
            "Scorecard OFFICIAL interdite : les prédictions portent un risque PROXY "
            "(estimateur naïf)."
        )


    overall = _aggregate_counts(
        [(gold, pred) for gold, pred, _ in rows],
        match=match,
    )
    direct_recall, direct_total = _entity_recall_over_rows(rows, IdentifierType.DIRECT)
    quasi_recall, quasi_total = _entity_recall_over_rows(rows, IdentifierType.QUASI)

    # ``None`` = document sans token prédit : la précision n'y est pas définie
    # et l'inclure à 0.0 pénaliserait un système qui ne prédit rien à raison.
    token_scores = [
        score
        for gold, pred, document in rows
        if (
            score := weighted_token_precision(
                gold, pred, str(field_value(document, "text", ""))
            )
        )
        is not None
    ]
    token_precision = sum(token_scores) / len(token_scores) if token_scores else None
    # ------------------------------------------------------------------ #
    # Axes B/C/D — mesurés sur le TEXTE : applicables à tout système,
    # boîte noire comprise (aucune capacité requise).
    # ------------------------------------------------------------------ #
    scored = [
        record for record in predictions
        if str(record.get("status", "error")).lower() in ("ok", "partial")
    ]

    leak_counts = aggregate_leak_counts(
        [
            gold_leak_counts(
                str(record.get("anonymized_text") or ""),
                gold_by_doc.get(str(record.get("doc_id")), ()),
            )
            for record in scored
        ]
    )

    outcomes, subject_key = subject_outcomes_from_run(
        predictions, gold_by_doc, documents_by_doc
    )
    cpr = collective_protection_rate(outcomes)
    ipr = individual_protection_rate(outcomes)
    protection_details = {
        "adversary": LITERAL_ADVERSARY,
        "subject_key": subject_key,
        "subjects": len(outcomes),
        # Écrit dans la métrique, pas seulement dans la documentation : un
        # adversaire littéral ne fait AUCUNE inférence, il constate une
        # présence verbatim. Il surestime donc la protection.
        "limitation": (
            "borne inférieure de l'inférabilité : ne capture ni la paraphrase "
            "ni l'inférence — un adversaire LLM retrouverait davantage"
        ),
    }

    rouge_scores = [
        rouge_l(
            str(field_value(documents_by_doc.get(str(record.get("doc_id"))), "text", "")),
            str(record.get("anonymized_text") or ""),
        )
        for record in scored
    ]
    rouge_mean = sum(rouge_scores) / len(rouge_scores) if rouge_scores else None

    trir_result = None
    trir_details: dict[str, Any] = {}
    try:
        trir_records = [
            TRIARecord(
                doc_id=str(record.get("doc_id")),
                subject_id=_subject_of(record, gold_by_doc, documents_by_doc, subject_key),
                text=str(field_value(documents_by_doc.get(str(record.get("doc_id"))), "text", "")),
            )
            for record in scored
        ]
        anonymized = {
            str(record.get("doc_id")): str(record.get("anonymized_text") or "")
            for record in scored
        }
        trir_result = evaluate_trir(trir_records, anonymized_texts=anonymized)
        trir_details = trir_result.to_dict()
    except Exception as exc:  # noqa: BLE001 — TRIR reste facultatif
        trir_details = {"reason": f"TRIR non calculable : {exc}"}

    diagnostic_status = MetricStatus.DIAGNOSTIC
    capabilities = frozenset(str(c) for c in (system.get("capabilities") or ()))

    def _gate(name: str, value: float | None, **kwargs: Any) -> dict[str, Any]:
        """Publie une métrique sous portillon de capacité."""
        return gate(
            name, value, capabilities=capabilities, protocol=protocol,
            protocol_version=protocol_version, **kwargs,
        )

    diagnostic = {
        "span_precision": _gate(
            "span_precision", overall["precision"], status=diagnostic_status,
            direction=MetricDirection.MAXIMIZE, details={"match": match},
        ),
        "span_recall": _gate(
            "span_recall", overall["recall"], status=diagnostic_status,
            direction=MetricDirection.MAXIMIZE, details={"match": match},
        ),
        "span_f1": _gate(
            "span_f1", overall["f1"], status=diagnostic_status,
            direction=MetricDirection.MAXIMIZE, details={"match": match},
        ),
        "weighted_token_precision": _gate(
            "weighted_token_precision", token_precision, status=diagnostic_status,
            direction=MetricDirection.MAXIMIZE, details={"weight": "token_length_proxy"},
        ),
        # Noms normatifs de SPEC-07 §2, avec les anciennes clés en alias.
        "ER_di": _gate(
            "ER_di", direct_recall,
            status=diagnostic_status if direct_total else MetricStatus.UNAVAILABLE,
            direction=MetricDirection.MAXIMIZE,
            details={"entities": direct_total, "level": "entity"},
        ),
        "entity_recall_direct": _gate(
            "entity_recall_direct", direct_recall,
            status=diagnostic_status if direct_total else MetricStatus.UNAVAILABLE,
            direction=MetricDirection.MAXIMIZE,
            details={"entities": direct_total, "alias_of": "ER_di"},
        ),
        "ER_qi": _gate(
            "ER_qi", quasi_recall,
            status=diagnostic_status if quasi_total else MetricStatus.UNAVAILABLE,
            direction=MetricDirection.MAXIMIZE,
            details={"entities": quasi_total, "level": "entity"},
        ),
        "entity_recall_quasi": _gate(
            "entity_recall_quasi", quasi_recall,
            status=diagnostic_status if quasi_total else MetricStatus.UNAVAILABLE,
            direction=MetricDirection.MAXIMIZE,
            details={"entities": quasi_total},
        ),
        # Axe C — utilité textuelle, universelle (aucune capacité requise).
        # ROUGE-L PÉNALISE les reformulations légitimes : généraliser
        # « 28 ans » en « fin de vingtaine » la dégrade alors que c'est une
        # bonne anonymisation. C'est un proxy, jamais la référence d'utilité.
        "rouge_l": _gate(
            "rouge_l", rouge_mean, status=diagnostic_status,
            direction=MetricDirection.MAXIMIZE,
            details={
                "documents": len(rouge_scores),
                "limitation": "métrique de surface : pénalise la généralisation",
            },
        ),
        # Fuite gold : recherche exacte, indépendante du détecteur.
        "gold_leak_rate": _gate(
            "gold_leak_rate", leak_counts.direct_rate, status=diagnostic_status,
            direction=MetricDirection.MINIMIZE, details=leak_counts.to_dict(),
        ),
        "counts": overall,
    }

    def grouped(group_getter: Any) -> dict[str, dict[str, Any]]:
        return _group_metric(
            [
                (gold, pred, _label(group_getter(document)))
                for gold, pred, document in rows
            ],
            match=match,
        )

    by_language = grouped(lambda document: field_value(document, "language", "unknown"))
    by_domain = grouped(lambda document: field_value(document, "domain", "unknown"))
    by_expression = _group_metric(_expression_rows(rows), match=match)
    by_difficulty = grouped(
        lambda document: (field_value(document, "meta", {}) or {}).get("difficulty", "unknown")
    )
    by_category: dict[str, dict[str, Any]] = {}
    categories = sorted(
        {
            category
            for gold, pred, _ in rows
            for span in (*gold, *pred)
            for category in (field_value(span, "qi_categories", ()) or ())
        }
    )
    for category in categories:
        values = _aggregate_counts(
            [
                (
                    tuple(
                        span
                        for span in gold
                        if category
                        in (field_value(span, "qi_categories", ()) or ())
                    ),
                    tuple(
                        span
                        for span in pred
                        if category
                        in (field_value(span, "qi_categories", ()) or ())
                    ),
                )
                for gold, pred, _ in rows
            ],
            match=match,
        )
        values["category"] = category
        values["documents"] = sum(
            category in {
                item
                for span in gold
                for item in (field_value(span, "qi_categories", ()) or ())
            }
            for gold, _, _ in rows
        )
        by_category[category] = values

    # Macro-F1 : moyenne non pondérée des F1 par catégorie, en ignorant les
    # catégories sans gold (dont le F1 est ``None``) — les compter à 0.0 ferait
    # chuter artificiellement la moyenne (D-1).
    category_f1 = [
        values["f1"] for values in by_category.values() if values["f1"] is not None
    ]
    macro_f1 = sum(category_f1) / len(category_f1) if category_f1 else None

    run_info = reproducibility.get("run") or {}
    requested_run_status = str(run_info.get("status", "complete")).lower()
    run_status = (
        "sampled"
        if requested_run_status == "sampled" or status is MetricStatus.SAMPLED
        else status.value
    )
    scorecard = {
        "run_id": run_id,
        "schema_version": SCORECARD_SCHEMA_VERSION,
        # Identité RÉELLE du système, lue dans le lock : sans elle, deux
        # systèmes différents produiraient la même valeur et la comparaison
        # serait impossible.
        "system": {
            **{k: v for k, v in system.items() if k != "prompts"},
            "policy": run_info.get("policy"),
            "profile": run_info.get("profile"),
        },
        "dataset": dataset,
        "split": split,
        "protocol": protocol,
        "protocol_version": protocol_version,
        "status": run_status,
        # C-5 règle 5 : la publiabilité dépend du seuil de 5 % d'erreur. Le
        # statut des métriques (dégradé en SAMPLED dès la première erreur, C-5
        # règle 4) est une information distincte, portée par ``status``.
        "publishable": accounting.publishable,
        "error_rate": accounting.error_rate,
        "accounting": accounting.to_dict(),
        # SPEC-07 v2.0 : CPR et IPR sont les métriques principales, devant
        # R_succ. Elles sortent en PROXY tant que l'adversaire est littéral.
        "primary": {
            "cpr": _gate(
                "cpr", cpr, status=MetricStatus.PROXY,
                direction=MetricDirection.MAXIMIZE, details=protection_details,
            ),
            "ipr": _gate(
                "ipr", ipr, status=MetricStatus.PROXY,
                direction=MetricDirection.MAXIMIZE, details=protection_details,
            ),
            "trir": _gate(
                "trir",
                trir_result.trir if trir_result is not None else None,
                status=MetricStatus.PROXY if trir_result is not None
                else MetricStatus.UNAVAILABLE,
                direction=MetricDirection.MINIMIZE, details=trir_details,
            ),
            "reid_success_rate": _metric_dict(
                "reid_success_rate", None, protocol=protocol,
                protocol_version=protocol_version, status=MetricStatus.UNAVAILABLE,
                direction=MetricDirection.MINIMIZE,
                details={"reason": "aucun attaquant exécuté par score"},
            ),
            "utility_retention": _metric_dict(
                "utility_retention", None, protocol=protocol,
                protocol_version=protocol_version, status=MetricStatus.UNAVAILABLE,
                direction=MetricDirection.MAXIMIZE,
                details={
                    "reason": "aucune tâche downstream déclarée ; "
                    "voir `rouge_l` pour un proxy d'utilité textuelle"
                },
            ),
        },
        "diagnostic": diagnostic,
        "macro_f1": _metric_dict(
            "macro_f1", macro_f1, protocol=protocol,
            protocol_version=protocol_version, status=diagnostic_status,
            direction=MetricDirection.MAXIMIZE,
            details={"match": match, "categories": len(category_f1)},
        ),
        "by_qi_category": by_category,
        "by_language": by_language,
        "by_domain": by_domain,
        "by_expression": by_expression,
        "by_expression_mode": by_expression,
        "by_difficulty": by_difficulty,
        "efficiency": {
            "documents_scored": len(scored_predictions),
            "latency_p50_ms": median(runtimes) if runtimes else None,
            "latency_p95_ms": _percentile(runtimes, 0.95),
        },
        "data_version": reproducibility.get("data_version"),
        "taxonomy_version": reproducibility.get("taxonomy_version"),
        "code": reproducibility.get("code"),
        "models": reproducibility.get("models"),
        "seeds": reproducibility.get("seeds"),
        "prompts": reproducibility.get("prompts"),
        "policy": reproducibility.get("policy"),
        "reproducibility": dict(reproducibility),
    }
    validate_scorecard(scorecard)
    return scorecard


def validate_reproducibility(lock: Mapping[str, Any]) -> None:
    """Refuse un lock auquel manque ou auquel est invalide un élément requis."""
    missing = [key for key in _REQUIRED_REPRODUCIBILITY if key not in lock]
    if missing:
        raise ScorecardError(
            "Lock de reproductibilité incomplet : éléments manquants : "
            + ", ".join(missing)
        )
    if lock.get("data_version") is None:
        raise ScorecardError("Lock de reproductibilité sans version des données")
    if not str(lock.get("taxonomy_version", "")).strip():
        raise ScorecardError("Lock de reproductibilité sans taxonomy_version")
    code = lock.get("code")
    if not isinstance(code, Mapping) or not code.get("git_commit"):
        raise ScorecardError("Lock de reproductibilité sans commit git")
    for key in ("models", "seeds", "prompts"):
        if lock.get(key) is None:
            raise ScorecardError(f"Lock de reproductibilité sans élément `{key}`")
    policy = lock.get("policy")
    if not isinstance(policy, Mapping):
        raise ScorecardError("Lock de reproductibilité sans politique")
    if not policy.get("id"):
        # Un système sans politique (boîte noire, passe-plat) est légitime,
        # mais l'absence doit être **déclarée**, jamais déduite du silence :
        # sans `reason`, on ne distingue pas « aucune politique » d'un lock
        # tronqué.
        if not str(policy.get("reason", "")).strip():
            raise ScorecardError(
                "Lock sans politique : un `policy.id` vide exige un "
                "`policy.reason` explicite (ex. « système sans politique »)."
            )


def validate_scorecard(scorecard: Mapping[str, Any]) -> None:
    """Valide les invariants structurels de SPEC-07 §10 et D-4."""
    missing = [key for key in _REQUIRED_TOP_LEVEL if key not in scorecard]
    if missing:
        raise ScorecardError("Scorecard incomplète : champs manquants : " + ", ".join(missing))
    if "error_rate" not in scorecard or "error_rate" not in scorecard["accounting"]:
        raise ScorecardError("Scorecard sans error_rate au premier niveau")
    # Un PROXY dans `primary` n'est interdit que si la scorecard se présente
    # comme OFFICIAL : c'est le mélange d'un chiffre approché et d'un chiffre
    # officiel que SPEC-07 §9 proscrit, pas l'usage d'un proxy correctement
    # étiqueté. CPR/IPR/TRIR sont nécessairement PROXY tant que l'adversaire
    # est littéral ; les interdire viderait `primary` de toute substance et
    # ramènerait le F1 de spans au premier plan — exactement ce que SPEC-07
    # v2.0 cherche à éviter.
    card_status = _status_label(scorecard.get("status"))
    if card_status == MetricStatus.OFFICIAL.value:
        for name, metric in scorecard["primary"].items():
            if (
                isinstance(metric, Mapping)
                and _status_label(metric.get("status")) == MetricStatus.PROXY.value
            ):
                raise ScorecardError(
                    f"Scorecard OFFICIAL : métrique PROXY interdite dans primary "
                    f"({name}). Dégradez le statut du run, ou remplacez "
                    f"l'estimation approchée par une mesure officielle."
                )
    reproducibility = dict(scorecard.get("reproducibility") or {})
    for key in _REQUIRED_REPRODUCIBILITY:
        if key not in reproducibility and key in scorecard:
            reproducibility[key] = scorecard[key]
    validate_reproducibility(reproducibility)
