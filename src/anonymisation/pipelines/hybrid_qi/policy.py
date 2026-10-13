"""Planificateur P0–P4 local : le planificateur partagé adapté au risque
copule calibré.

Le planificateur partagé (``anonymisation/policy/engine.py``) est construit
sur l'estimateur naïf (``naive_proxy``). Ce module en **réutilise la
mécanique** — ``check_action_allowed``, les hiérarchies SPEC-03
``generalize``/``levels_available``, le modèle ``AnonymizationDecision``, le
coût d'utilité ``DEFAULT_UTILITY_COST`` — mais évalue le risque avec
:class:`~.risk.HybridRiskEstimator` (copule gaussienne, calibration
synthétique seed 42).

Règles de décision (SPEC-06 §9, ``policy.yaml`` du paquet) :

- la décision est prise sur la **borne haute calibrée** du risque
  (``use_upper_bound``) ;
- ``DIRECT`` : toujours ``SUPPRESS`` (P0–P4) ; ``SENSITIVE_ONLY`` : action
  de la politique (défaut ``KEEP``, ``SUPPRESS`` en P4) ;
- ``QUASI`` :
  * action par défaut ``KEEP`` (P0) → QI non traités, sans généralisation ;
  * action par défaut ``SUPPRESS`` (P4) → tous les QI supprimés ;
  * action par défaut ``GENERALIZE`` (P1–P3) : si le risque est sous
    ``keep_below`` → ``KEEP`` ; si le risque atteint ``suppress_above`` →
    ``SUPPRESS`` direct ; sinon boucle — tant que le risque dépasse
    ``keep_below``, choisir l'étape (généraliser une catégorie d'un niveau
    quand une hiérarchie existe, ou supprimer une classe de QI) au meilleur
    ratio ``Δrisque / perte d'utilité`` et réévaluer le risque sur l'état
    courant ;
- si le seuil reste dépassé après épuisement des étapes, les QI restants
  sont supprimés **explicitement** (raison française + métadonnée de repli
  ``fallback``) — **jamais un KEEP silencieux**.

Honnêteté du risque résiduel : seul ce que les décisions **éditent
effectivement** dans le texte sort du risque — les QI implicites sans span
(extraction LLM non positionnée) ne sont jamais anonymisables ; ils restent
actifs dans le risque résiduel même quand tout le reste est supprimé.
Toutes les décisions portent ``risk_status = DIAGNOSTIC`` (jamais
``OFFICIAL``) : le risque est calibré sur une population synthétique.
"""

from __future__ import annotations

from collections.abc import Sequence
from typing import Any

from anonymisation.policy.engine import (
    DEFAULT_UTILITY_COST,
    PolicyEngineError,
)
from anonymisation.policy.models import Policy
from anonymisation.schema.models import Annotation, Document
from anonymisation.schema.taxonomy import IdentifierType
from anonymisation.transform.decisions import (
    Action,
    AnonymizationDecision,
    check_action_allowed,
)
from anonymisation.transform.generalize import (
    MalformedValueNormalizedError,
    UnknownGeneralizationCategoryError,
    generalize,
    levels_available,
)

from .risk import (
    HybridRiskEstimate,
    HybridRiskEstimator,
    QiAttribute,
    UniquenessClaim,
    attribute_keys_for_annotation,
)

#: Coûts d'utilité perdus par action (dénominateur du ratio Δrisque /
#: Δutilité) — réutilisés à l'identique du planificateur partagé pour la
#: comparabilité des courbes.
UTILITY_COST: dict[str, float] = dict(DEFAULT_UTILITY_COST)

#: Marge de sécurité sur le nombre d'itérations de la boucle (borne
#: théorique : n_catégories × max_niveaux + n_classes).
_GUARD_MARGIN: int = 4


class HybridPlanningError(PolicyEngineError):
    """Erreur de planification hybride : action illégale, politique
    incohérente, valeur malformée — nomme la catégorie, la valeur et le
    correctif attendu.

    Erreur **d'exécution** (contrat violé), pas un repli : elle sature la
    campagne, elle ne devient jamais une décision silencieuse.
    """


def _risk_meta(estimate: HybridRiskEstimate) -> dict[str, Any]:
    """Métadonnées de statut de risque portées par chaque décision."""
    return {
        "risk_status": estimate.status,
        "risk_model": estimate.risk_model,
        "calibration_scope": estimate.calibration_scope,
        "population_id": estimate.population_id,
    }


def _category_of(annotation: Annotation) -> str:
    if not annotation.qi_categories:
        raise HybridPlanningError(
            f"annotation {annotation.annotation_id} : qi_categories vide — "
            "impossible de choisir une action (règle d'or : jamais de code deviné)."
        )
    return annotation.qi_categories[0]


def _require_offsets(annotation: Annotation) -> tuple[int, int]:
    if annotation.start is None or annotation.end is None:
        raise HybridPlanningError(
            f"annotation {annotation.annotation_id} : décision positionnelle "
            "impossible sans offsets (QI implicite — évalué au niveau document "
            "dans ASSESS, pas planifié ici)."
        )
    return annotation.start, annotation.end


def _hierarchy_available(attribute: QiAttribute) -> int:
    """Niveaux de généralisation disponibles pour la valeur de l'attribut ;
    ``0`` si la hiérarchie est absente ou la valeur malformée (repli
    documenté, pas une erreur d'exécution)."""
    try:
        return levels_available(attribute.value, attribute.category)
    except (MalformedValueNormalizedError, UnknownGeneralizationCategoryError):
        return 0


def _granularity_is_coarse(annotation: Annotation | None) -> bool:
    """Une annotation COARSE n'est jamais généralisée (granularité trop
    grossière pour une hiérarchie de valeurs) — même règle que le
    planificateur partagé."""
    if annotation is None:
        return False
    granularity = annotation.granularity
    return str(getattr(granularity, "value", granularity)) == "COARSE"


def plan_hybrid_policy(
    *,
    doc: Document,
    annotations: Sequence[Annotation],
    attributes: Sequence[QiAttribute],
    claims: Sequence[UniquenessClaim],
    estimator: HybridRiskEstimator,
    policy: Policy,
    risk_base: HybridRiskEstimate,
) -> tuple[list[AnonymizationDecision], dict[str, Any]]:
    """Planifie l'anonymisation d'un document selon la politique P0–P4.

    ``attributes`` est l'ensemble Q(d) de l'étape ASSESS (dedup_q terminé :
    dédupliqué, coréférence fusionnée) ; ``risk_base`` est l'estimation du
    risque de l'état initial (niveaux 0) déjà calculée en ASSESS — elle est
    réutilisée telle quelle, jamais recalculée différemment (un document a
    UN risque de base par run).

    Retourne ``(decisions, meta)`` : chaque décision est un
    ``AnonymizationDecision`` sérialisable (offsets sur le texte original),
    raison en français, statut ``DIAGNOSTIC`` ; ``meta`` porte les étapes
    franchies (audit de la boucle) et les risques de base/final.
    """
    decisions: list[AnonymizationDecision] = []
    meta: dict[str, Any] = {
        "policy_label": policy.label,
        "risk_base": risk_base.risk,
        "risk_final": risk_base.risk,
        "steps": [],
    }
    base_meta = _risk_meta(risk_base)
    domain = doc.domain.value if doc.domain is not None else None
    language = doc.language

    def evaluate(
        *,
        levels: dict[str, int],
        suppressed_keys: set[tuple[str, str, str | None]],
    ) -> HybridRiskEstimate:
        """Risque de l'état courant (niveaux + suppressions) — borne haute
        calibrée, déterministe."""
        active = [a for a in attributes if a.key not in suppressed_keys]
        return estimator.assess(
            active,
            domain=domain,
            language=language,
            claims=tuple(claims),
            levels=levels,
        )

    # -- 1. Types non pilotés par le risque : DIRECT / SENSITIVE_ONLY ----- #
    for annotation in annotations:
        if annotation.identifier_type is not IdentifierType.QUASI:
            if annotation.identifier_type is IdentifierType.DIRECT:
                action_name = policy.actions.get("DIRECT", "SUPPRESS")
                type_label = "identifiant direct"
            elif annotation.identifier_type is IdentifierType.SENSITIVE_ONLY:
                action_name = policy.actions.get("SENSITIVE_ONLY", "KEEP")
                type_label = "donnée sensible"
            else:
                action_name = "KEEP"
                type_label = "type IGNORED"
            start, end = _require_offsets(annotation)
            original = doc.text[start:end]
            category = _category_of(annotation)
            action = Action(action_name)
            # La table normative est indexée par code, pas par libellé.
            # La granularité ne pilote que les transformations de QUASI.
            check_action_allowed(annotation.identifier_type.value, None, action)
            replacement = (
                original if action is Action.KEEP else f"[{category}_SUPPRIME]"
            )
            decisions.append(
                AnonymizationDecision(
                    start=start,
                    end=end,
                    original=original,
                    action=action,
                    replacement=replacement,
                    qi_category=category,
                    reason=(
                        f"Politique {policy.label} : {type_label} -> "
                        f"{action.value} (action fixe, indépendante du "
                        "risque)."
                    ),
                    risk_before=risk_base.risk,
                    risk_after=None,
                    meta=base_meta,
                )
            )

    quasi = [a for a in annotations if a.identifier_type is IdentifierType.QUASI]
    if not quasi:
        return decisions, meta

    # Clés éditables : ce que les décisions anonymisent réellement dans le
    # texte. Les attributs hors de cet ensemble (QI implicites sans span)
    # restent actifs dans le risque résiduel — on ne peut pas « supprimer »
    # ce qu'on ne peut pas éditer.
    editable_keys: set[tuple[str, str, str | None]] = set()
    for annotation in annotations:
        editable_keys |= attribute_keys_for_annotation(annotation)
    quasi_keys: set[tuple[str, str, str | None]] = set()
    for annotation in quasi:
        quasi_keys |= attribute_keys_for_annotation(annotation)
    loopable = [
        a for a in attributes if a.key in quasi_keys and a.key not in editable_keys - quasi_keys
    ]

    default_action = policy.actions.get("QUASI", "KEEP")

    # -- 2. P0 : QUASI -> KEEP (aucune anonymisation de QI) --------------- #
    if default_action == "KEEP":
        for annotation in quasi:
            start, end = _require_offsets(annotation)
            original = doc.text[start:end]
            category = _category_of(annotation)
            # Comme PolicyEngine._keep_decision : KEEP constate une absence
            # de transformation décidée par la politique. La table SPEC-01 §8
            # contrôle les transformations, pas cette conservation explicite.
            decisions.append(
                AnonymizationDecision(
                    start=start,
                    end=end,
                    original=original,
                    action=Action.KEEP,
                    replacement=original,
                    qi_category=category,
                    reason=(
                        f"Politique {policy.label} : QUASI -> KEEP — les QI "
                        f"sont conservés (point de référence ; risque "
                        f"estimé {risk_base.risk:.3f} pour information)."
                    ),
                    risk_before=risk_base.risk,
                    risk_after=risk_base.risk,
                    meta=base_meta,
                )
            )
        meta["risk_final"] = risk_base.risk
        return decisions, meta

    # -- 3. P4 : QUASI -> SUPPRESS (protection maximale) ------------------ #
    if default_action == "SUPPRESS":
        # On supprime du risque exactement ce que les décisions éditent
        # (QUASI + SENSITIVE_ONLY quand la politique le demande + DIRECT).
        suppressed_keys = {
            a.key
            for a in attributes
            if a.key in quasi_keys
            or (
                a.key in editable_keys
                and policy.actions.get("SENSITIVE_ONLY", "KEEP") != "KEEP"
            )
            or policy.actions.get("DIRECT", "SUPPRESS") != "KEEP"
        }
        risk_final = evaluate(levels={}, suppressed_keys=suppressed_keys)
        for annotation in quasi:
            start, end = _require_offsets(annotation)
            original = doc.text[start:end]
            category = _category_of(annotation)
            check_action_allowed("QUASI", annotation.granularity, Action.SUPPRESS)
            decisions.append(
                AnonymizationDecision(
                    start=start,
                    end=end,
                    original=original,
                    action=Action.SUPPRESS,
                    replacement=f"[{category}_SUPPRIME]",
                    qi_category=category,
                    reason=(
                        f"Politique {policy.label} : QUASI -> SUPPRESS "
                        f"(protection maximale, indépendante du risque "
                        f"estimé {risk_base.risk:.3f})."
                    ),
                    risk_before=risk_base.risk,
                    risk_after=risk_final.risk,
                    meta=base_meta,
                )
            )
        meta["risk_final"] = risk_final.risk
        return decisions, meta

    if default_action != "GENERALIZE":
        raise HybridPlanningError(
            f"action QUASI non gérée par le planificateur hybride : "
            f"{default_action!r} (politique {policy.label}) — corriger "
            "policy.yaml (KEEP | GENERALIZE | SUPPRESS)."
        )

    # -- 4. P1–P3 : GENERALIZE piloté par le risque copule calibré -------- #
    threshold = policy.thresholds.keep_below
    suppress_above = policy.thresholds.suppress_above
    max_steps = policy.max_generalization_steps

    if risk_base.risk < threshold:
        for annotation in quasi:
            start, end = _require_offsets(annotation)
            original = doc.text[start:end]
            category = _category_of(annotation)
            decisions.append(
                AnonymizationDecision(
                    start=start,
                    end=end,
                    original=original,
                    action=Action.KEEP,
                    replacement=original,
                    qi_category=category,
                    reason=(
                        f"Politique {policy.label} : risque {risk_base.risk:.3f} "
                        f"<= seuil {threshold:.3f} dès la valeur exacte — "
                        "aucune généralisation nécessaire."
                    ),
                    risk_before=risk_base.risk,
                    risk_after=risk_base.risk,
                    meta=base_meta,
                )
            )
        meta["risk_final"] = risk_base.risk
        return decisions, meta

    if suppress_above is not None and risk_base.risk >= suppress_above:
        suppressed_keys = set(quasi_keys)
        risk_final = evaluate(levels={}, suppressed_keys=suppressed_keys)
        for annotation in quasi:
            start, end = _require_offsets(annotation)
            original = doc.text[start:end]
            category = _category_of(annotation)
            check_action_allowed("QUASI", annotation.granularity, Action.SUPPRESS)
            decisions.append(
                AnonymizationDecision(
                    start=start,
                    end=end,
                    original=original,
                    action=Action.SUPPRESS,
                    replacement=f"[{category}_SUPPRIME]",
                    qi_category=category,
                    reason=(
                        f"Politique {policy.label} : risque {risk_base.risk:.3f} "
                        f">= borne haute {suppress_above:.3f} — suppression "
                        "directe des QI (la généralisation ne pourrait pas "
                        "ramener le risque sous le seuil)."
                    ),
                    risk_before=risk_base.risk,
                    risk_after=risk_final.risk,
                    meta=base_meta,
                )
            )
        meta["risk_final"] = risk_final.risk
        return decisions, meta

    # Boucle SPEC-06 §9 : état courant (niveaux + suppressions), meilleure
    # étape au ratio Δrisque / perte d'utilité, réévaluation après chaque
    # étape. Seuls les QI éditables (portés par une annotation QUASI)
    # entrent en jeu ; les QI implicites restent actifs.
    levels: dict[str, int] = {}
    suppressed_keys: set[tuple[str, str, str | None]] = set()
    risk = risk_base.risk
    n_categories = len({a.category for a in loopable})
    max_iterations = (
        n_categories * (max_steps or 0) + len(loopable) + _GUARD_MARGIN
    )
    iterations = 0

    # Attribut -> annotations (une classe peut porter plusieurs mentions :
    # la coréférence a fusionné la valeur de risque, chaque mention garde
    # sa propre position).
    annotations_by_key: dict[tuple[str, str, str | None], list[Annotation]] = {}
    for annotation in quasi:
        for key in attribute_keys_for_annotation(annotation):
            annotations_by_key.setdefault(key, []).append(annotation)

    while risk > threshold and iterations < max_iterations:
        iterations += 1
        best: tuple[float, QiAttribute, str, dict[str, int], float] | None = (
            None
        )  # (ratio, attribut, "GENERALIZE"|"SUPPRESS", niveaux, risque)

        for attr in loopable:
            if attr.key in suppressed_keys:
                continue
            current_level = levels.get(attr.category, 0)
            available = _hierarchy_available(attr)
            under_cap = (max_steps is None) or current_level < max_steps
            is_coarse = any(
                _granularity_is_coarse(a)
                for a in annotations_by_key.get(attr.key, ())
            )

            if available > current_level and under_cap and not is_coarse:
                trial_levels = {**levels, attr.category: current_level + 1}
                trial = evaluate(levels=trial_levels, suppressed_keys=suppressed_keys)
                delta_risk = max(0.0, risk - trial.risk)
                cost = UTILITY_COST["GENERALIZE_PER_LEVEL"]
                ratio = delta_risk / cost if cost > 0 else float("inf")
                if best is None or ratio > best[0]:
                    best = (ratio, attr, "GENERALIZE", trial_levels, trial.risk)

            trial_sup = evaluate(
                levels=levels,
                suppressed_keys=suppressed_keys | {attr.key},
            )
            delta_risk_sup = max(0.0, risk - trial_sup.risk)
            cost_sup = UTILITY_COST["SUPPRESS"]
            ratio_sup = delta_risk_sup / cost_sup if cost_sup > 0 else float("inf")
            if best is None or ratio_sup > best[0]:
                best = (ratio_sup, attr, "SUPPRESS", levels, trial_sup.risk)

        if best is None or best[0] <= 0.0:
            break
        _, chosen, kind, new_levels, new_risk = best
        levels = new_levels
        if kind == "SUPPRESS":
            suppressed_keys.add(chosen.key)
        meta["steps"].append(
            {
                "kind": kind,
                "category": chosen.category,
                "level": levels.get(chosen.category, 0),
                "risk_after": new_risk,
            }
        )
        risk = new_risk

    # Seuil non atteint malgré l'épuisement des étapes : SUPPRESS explicite
    # des QI restants (dernière étape de l'algorithme SPEC-06 §9) — métadonnée
    # de repli, jamais un KEEP silencieux.
    if risk > threshold:
        for attr in loopable:
            if attr.key in suppressed_keys:
                continue
            suppressed_keys.add(attr.key)
            meta["steps"].append(
                {
                    "kind": "SUPPRESS_FALLBACK",
                    "category": attr.category,
                    "level": levels.get(attr.category, 0),
                    "risk_after": risk,
                }
            )
        risk = evaluate(levels=levels, suppressed_keys=suppressed_keys).risk
        meta["risk_final"] = risk
        meta["seuil_non_atteint"] = risk > threshold
    else:
        meta["risk_final"] = risk

    # -- 5. Décisions par annotation -------------------------------------- #
    for attr in attributes:
        key = attr.key
        anns = annotations_by_key.get(key, [])
        if not anns:
            continue  # QI implicite sans span : pas de décision positionnelle
        level = levels.get(attr.category, 0)
        is_suppressed = key in suppressed_keys

        for annotation in anns:
            start, end = _require_offsets(annotation)
            original = doc.text[start:end]
            category = _category_of(annotation)

            if is_suppressed:
                check_action_allowed("QUASI", annotation.granularity, Action.SUPPRESS)
                fallback = any(
                    s["kind"] == "SUPPRESS_FALLBACK"
                    for s in meta["steps"]
                    if s["category"] == category
                )
                decisions.append(
                    AnonymizationDecision(
                        start=start,
                        end=end,
                        original=original,
                        action=Action.SUPPRESS,
                        replacement=f"[{category}_SUPPRIME]",
                        qi_category=category,
                        reason=(
                            f"Politique {policy.label} : {category} supprimé — "
                            "la généralisation ne ramène pas le risque sous le "
                            f"seuil {threshold:.3f} (risque final {risk:.3f})."
                        ),
                        risk_before=risk_base.risk,
                        risk_after=risk,
                        meta={
                            **base_meta,
                            **({"fallback": "seuil_non_atteint"} if fallback else {}),
                        },
                    )
                )
                continue

            if level > 0:
                value = annotation.value_normalized or {}
                try:
                    generalized = generalize(value, category, steps=level)
                except (MalformedValueNormalizedError, UnknownGeneralizationCategoryError) as exc:
                    # Le niveau est porté par la catégorie : une autre mention
                    # de la catégorie a été généralisée, celle-ci n'a pas de
                    # valeur normalisée exploitable. Repli explicite en
                    # suppression (plus protecteur que le niveau visé) —
                    # jamais un KEEP silencieux ni un document en erreur.
                    check_action_allowed(
                        "QUASI", annotation.granularity, Action.SUPPRESS
                    )
                    decisions.append(
                        AnonymizationDecision(
                            start=start,
                            end=end,
                            original=original,
                            action=Action.SUPPRESS,
                            replacement=f"[{category}_SUPPRIME]",
                            qi_category=category,
                            reason=(
                                f"Politique {policy.label} : {category} "
                                f"généralisé au niveau {level} mais cette "
                                f"mention n'est pas généralisable ({exc}) — "
                                "repli en suppression explicite."
                            ),
                            risk_before=risk_base.risk,
                            risk_after=risk,
                            meta={**base_meta, "fallback": "valeur_non_generalisable"},
                        )
                    )
                    continue
                if generalized is None:
                    # Hiérarchie épuisée pour cette mention (niveaux
                    # incohérents entre valeur et hiérarchie) : repli
                    # explicite en suppression — jamais un KEEP silencieux.
                    check_action_allowed(
                        "QUASI", annotation.granularity, Action.SUPPRESS
                    )
                    decisions.append(
                        AnonymizationDecision(
                            start=start,
                            end=end,
                            original=original,
                            action=Action.SUPPRESS,
                            replacement=f"[{category}_SUPPRIME]",
                            qi_category=category,
                            reason=(
                                f"Politique {policy.label} : hiérarchie de "
                                f"généralisation incohérente pour {category} "
                                f"au niveau {level} — repli en suppression "
                                f"explicite (risque final {risk:.3f})."
                            ),
                            risk_before=risk_base.risk,
                            risk_after=risk,
                            meta={**base_meta, "fallback": "hierarchie_epuisee"},
                        )
                    )
                    continue
                surface, _ = generalized
                check_action_allowed(
                    "QUASI", annotation.granularity, Action.GENERALIZE
                )
                decisions.append(
                    AnonymizationDecision(
                        start=start,
                        end=end,
                        original=original,
                        action=Action.GENERALIZE,
                        replacement=surface,
                        qi_category=category,
                        reason=(
                            f"Politique {policy.label} : {category} généralisé "
                            f"de {level} niveau(x) — risque ramené à "
                            f"{risk:.3f} (seuil {threshold:.3f})."
                        ),
                        risk_before=risk_base.risk,
                        risk_after=risk,
                        meta=base_meta,
                    )
                )
                continue

            decisions.append(
                AnonymizationDecision(
                    start=start,
                    end=end,
                    original=original,
                    action=Action.KEEP,
                    replacement=original,
                    qi_category=category,
                    reason=(
                        f"Politique {policy.label} : {category} conservé — le "
                        f"risque final {risk:.3f} est sous le seuil "
                        f"{threshold:.3f} et aucun niveau de généralisation "
                        "n'était nécessaire."
                    ),
                    risk_before=risk_base.risk,
                    risk_after=risk,
                    meta=base_meta,
                )
            )

    # Tri par position (offsets sur le texte original) pour la
    # reproductibilité de la sortie.
    decisions.sort(key=lambda d: (d.start, d.end, d.qi_category))
    return decisions, meta
