"""Moteur de politique : risque -> décisions d'anonymisation (SPEC-06 §9).

**AVERTISSEMENT — estimateur de risque provisoire.**
Le vrai moteur de risque (populations de référence, modèle copule calibré,
SPEC-06) est un lot séparé (L3) qui n'existe pas encore au moment où ce code
est écrit. :class:`NaiveRiskEstimator` fournit un repli explicite et honnête :
il approxime $k$ par le produit de sélectivités déclarées par catégorie (une
table forfaitaire, non calibrée) et retourne ``1 / k`` comme risque.

Cette estimation **n'est pas calibrée** et ne doit **jamais** être publiée
comme un risque officiel (SPEC-07 §4 interdit de présenter un score PROXY à
côté d'un chiffre calibré, précisément pour éviter cette confusion). Toute
décision produite avec cet estimateur porte ``meta["risk_status"] = "PROXY"`,
et son ``risk_model`` associé est ``"naive_proxy"`` — jamais ``"copula"`` ni
un des modèles décrits par SPEC-06 §3.

## Algorithme (SPEC-06 §9)

```
tant que risk(Q) > seuil et actions_possibles non vide :
    choisir l'action qui maximise  Δrisque / Δutilité_perdue
    appliquer, recalculer Q et risk
si risk(Q) > seuil :
    SUPPRESS les QI restants
```

Ce module ne s'applique cet algorithme itératif qu'aux QI dont l'action de
politique par défaut est ``GENERALIZE`` : c'est le seul cas où une hiérarchie
de généralisation offre un choix à arbitrer. Quand la politique fixe
``KEEP`` (ex. P0) ou ``SUPPRESS`` (ex. P4) pour un type d'identifiant, cette
décision s'applique uniformément, sans recours au risque — c'est le sens de
« P0 ne touche pas les QI » et « P4 les supprime tous ».
"""

from __future__ import annotations

from collections.abc import Callable, Sequence
from dataclasses import dataclass, field
from typing import Any

from anonymisation.metrics.contracts import MetricStatus
from anonymisation.policy.models import Policy
from anonymisation.transform.decisions import (
    Action,
    AnnotationLike,
    AnonymizationDecision,
    check_action_allowed,
)
from anonymisation.transform.generalize import (
    MalformedValueNormalizedError,
    UnknownGeneralizationCategoryError,
    generalize,
    levels_available,
)

#: Coût d'utilité perdue par action, utilisé comme dénominateur du ratio
#: Δrisque / Δutilité. Valeurs de départ raisonnables (non calibrées), voir
#: en-tête de module. GENERALIZE est multiplié par le nombre de niveaux
#: parcourus.
DEFAULT_UTILITY_COST: dict[str, float] = {
    "KEEP": 0.0,
    "GENERALIZE_PER_LEVEL": 0.2,
    "PSEUDONYMIZE": 0.4,
    "MASK": 0.6,
    "SUPPRESS": 1.0,
}

#: Sélectivité forfaitaire par catégorie (fraction de population supposée
#: partager une valeur exacte, niveau 0) et facteur d'élargissement par
#: niveau de généralisation franchi. PURE APPROXIMATION — voir avertissement
#: de module.
DEFAULT_SELECTIVITY: dict[str, float] = {
    "GEN_AGE": 0.02,
    "GEN_GEO": 0.005,
    "GEN_OCCUPATION": 0.05,
    "GEN_EDUCATION": 0.08,
    "GEN_AFFILIATION": 0.1,
    "GEN_FAMILY": 0.2,
    "GEN_HEALTH_STATE": 0.1,
    "GEN_SOCIOECON": 0.15,
    "GEN_ORIGIN_BELIEF": 0.1,
    "GEN_LIFESTYLE": 0.2,
    "GEN_PHYSICAL": 0.2,
    "GEN_GENDER": 0.5,
    "GEN_DATE_EVENT": 0.1,
    "HR_JOB_TITLE": 0.05,
    "HR_SENIORITY": 0.2,
    "HR_HIERARCHY": 0.2,
    "HR_DEPARTMENT": 0.1,
    "HR_CONTRACT": 0.3,
    "HR_EMPLOYER_SIZE": 0.1,
    "HR_WORKSITE": 0.05,
    "HR_SALARY_BAND": 0.15,
    "HR_CAREER_EVENT": 0.2,
    "HR_ADMIN_PROCEDURE": 0.1,
    "SUP_PRODUCT": 0.3,
    "SUP_VERSION": 0.1,
    "SUP_OS": 0.3,
    "SUP_DEVICE": 0.2,
    "SUP_ENVIRONMENT": 0.3,
    "SUP_ROLE": 0.2,
    "SUP_INCIDENT_TIME": 0.1,
    "SUP_TIMEZONE": 0.3,
    "SUP_ORG": 0.02,
    "SUP_SCALE": 0.2,
    "FOR_COMMUNITY": 0.1,
    "FOR_RELATION": 0.1,
    "FOR_ACTIVITY_PATTERN": 0.2,
}

#: Sélectivité par défaut pour une catégorie absente de la table ci-dessus.
_DEFAULT_UNKNOWN_SELECTIVITY = 0.2

#: Facteur multiplicatif de sélectivité appliqué par niveau de généralisation
#: franchi (une généralisation élargit la classe d'équivalence).
_LEVEL_WIDENING_FACTOR = 4.0


@dataclass(frozen=True)
class _QiState:
    """État courant d'un QI observé, pour le calcul de risque proxy."""

    annotation_id: str
    qi_category: str
    level: int


class _NaiveRiskValue(float):
    """Valeur numérique de risque qui transporte son statut de proxy.

    Le moteur de politique a besoin d'un ``float`` pour ses comparaisons et
    son classement des actions. Cette sous-classe conserve cette compatibilité
    tout en rendant le statut visible et non surchargeable sur chaque sortie.
    """

    __slots__ = ()

    @property
    def status(self) -> MetricStatus:
        return MetricStatus.PROXY


class NaiveRiskEstimator:
    r"""Estimateur de risque **provisoire, non calibré** (voir en-tête de module).

    Modèle : chaque catégorie de QI porte une *prévalence* ``p`` — la fraction
    de la population de référence qui partage cette valeur. Sous une hypothèse
    (fausse, mais assumée ici) d'indépendance des attributs, la taille attendue
    de la classe d'équivalence est

    .. math:: k = N \cdot \prod_j p_j

    et le risque *prosecutor* est :math:`R = 1/k`, borné à ``[0, 1]``.

    Deux propriétés de monotonie en découlent, et elles sont testées :

    * **ajouter un QI** réduit :math:`\prod p_j`, donc réduit ``k`` et
      **augmente** le risque — c'est tout le propos du risque combinatoire ;
    * **généraliser un QI** élargit sa prévalence d'un facteur
      :data:`_LEVEL_WIDENING_FACTOR` par niveau, donc augmente ``k`` et
      **réduit** le risque — c'est ce qui rend l'action ``GENERALIZE``
      effective.

    .. warning::
       Cette approximation n'est **pas** calibrée et ne remplace pas le moteur
       de SPEC-06 (lot L4). Ses sorties sont marquées ``PROXY`` et SPEC-07 §9
       interdit de les présenter à côté d'un chiffre officiel. En particulier,
       l'hypothèse d'indépendance sous-estime le risque : les attributs réels
       sont corrélés (profession et diplôme, ville et région).
    """

    #: Taille de la population de référence de repli, utilisée tant qu'aucune
    #: population réelle (SPEC-06 §4) n'est branchée. Valeur arbitraire et
    #: assumée comme telle : elle fixe l'échelle du risque, pas son classement.
    DEFAULT_POPULATION_SIZE: int = 10_000

    def __init__(
        self,
        selectivity: dict[str, float] | None = None,
        population_size: int | None = None,
    ) -> None:
        self._selectivity = dict(selectivity or DEFAULT_SELECTIVITY)
        self._population_size = int(population_size or self.DEFAULT_POPULATION_SIZE)
        if self._population_size < 1:
            raise ValueError("population_size doit être >= 1")
    @property
    def status(self) -> MetricStatus:
        """Statut contractuel de toutes les valeurs émises par cet estimateur."""
        return MetricStatus.PROXY


    def _prevalence_for(self, qi_category: str, level: int) -> float:
        """Prévalence de la catégorie, élargie d'un cran par niveau généralisé."""
        base = self._selectivity.get(qi_category, _DEFAULT_UNKNOWN_SELECTIVITY)
        return min(1.0, base * (_LEVEL_WIDENING_FACTOR**level))

    def estimate_k(self, states: Sequence[_QiState]) -> float:
        """Taille attendue de la classe d'équivalence."""
        if not states:
            return float(self._population_size)
        product = 1.0
        for state in states:
            product *= self._prevalence_for(state.qi_category, state.level)
        return self._population_size * product

    def __call__(self, states: Sequence[_QiState]) -> _NaiveRiskValue:
        if not states:
            # Aucun QI observé : rien ne restreint la population, risque nul.
            return _NaiveRiskValue(0.0)
        k = self.estimate_k(states)
        if k <= 1.0:
            # k < 1 signifie « personne ne correspond dans la population de
            # référence » : en pratique l'individu est unique -> risque maximal.
            return _NaiveRiskValue(1.0)
        return _NaiveRiskValue(min(1.0, 1.0 / k))


RiskFn = Callable[[Sequence[Any]], float]


class PolicyEngineError(ValueError):
    """Erreur d'exécution du moteur de politique (annotation malformée, etc.)."""


@dataclass
class _PlanContext:
    """État mutable interne à :meth:`PolicyEngine._plan_quasi`."""

    values: dict[str, dict[str, Any]] = field(default_factory=dict)
    active: set[str] = field(default_factory=set)


class PolicyEngine:
    """Applique une :class:`Policy` à un ensemble d'annotations pour produire
    des :class:`AnonymizationDecision` explicables.
    """

    def __init__(
        self,
        policy: Policy,
        risk_fn: RiskFn | None = None,
        *,
        utility_cost: dict[str, float] | None = None,
    ) -> None:
        self.policy = policy
        self._risk_fn_is_custom = risk_fn is not None
        self._risk_fn: RiskFn = risk_fn or NaiveRiskEstimator()
        self._utility_cost = dict(utility_cost or DEFAULT_UTILITY_COST)

    def _risk_status_meta(self) -> dict[str, Any]:
        if self._risk_fn_is_custom:
            return {}
        status = getattr(self._risk_fn, "status", MetricStatus.PROXY)
        status_name = getattr(status, "name", str(status).upper())
        return {"risk_status": status_name, "risk_model": "naive_proxy"}

    # ------------------------------------------------------------------ #
    # Point d'entrée
    # ------------------------------------------------------------------ #
    def plan(self, annotations: Sequence[AnnotationLike], *, text: str) -> list[AnonymizationDecision]:
        decisions: list[AnonymizationDecision] = []
        quasi: list[AnnotationLike] = []

        for annotation in annotations:
            id_type = self._identifier_type_key(annotation)

            if id_type == "IGNORED":
                decisions.append(self._keep_decision(annotation, text, "type IGNORED : toujours conservé (SPEC-01 §8)"))
                continue

            if id_type == "DIRECT":
                action_name = self.policy.actions.get("DIRECT", "SUPPRESS")
                decisions.append(self._build_fixed_decision(annotation, text, action_name, "DIRECT"))
                continue

            if id_type == "SENSITIVE_ONLY":
                action_name = self.policy.actions.get("SENSITIVE_ONLY", "KEEP")
                decisions.append(self._build_fixed_decision(annotation, text, action_name, "SENSITIVE_ONLY"))
                continue

            if id_type == "QUASI":
                quasi.append(annotation)
                continue

            raise PolicyEngineError(f"identifier_type inconnu ou non géré : {id_type!r}")

        decisions.extend(self._plan_quasi(quasi, text))
        return decisions

    # ------------------------------------------------------------------ #
    # Types non pilotés par le risque : DIRECT, SENSITIVE_ONLY, IGNORED
    # ------------------------------------------------------------------ #
    @staticmethod
    def _identifier_type_key(annotation: AnnotationLike) -> str:
        return str(getattr(annotation.identifier_type, "value", annotation.identifier_type))

    @staticmethod
    def _granularity_of(annotation: AnnotationLike) -> Any:
        return getattr(annotation, "granularity", None)

    @staticmethod
    def _category_of(annotation: AnnotationLike) -> str:
        categories = getattr(annotation, "qi_categories", None)
        if not categories:
            raise PolicyEngineError("Annotation sans qi_categories : impossible de choisir une action")
        return categories[0]

    def _keep_decision(self, annotation: AnnotationLike, text: str, reason: str) -> AnonymizationDecision:
        start, end = self._require_offsets(annotation)
        original = text[start:end]
        return AnonymizationDecision(
            start=start,
            end=end,
            original=original,
            action=Action.KEEP,
            replacement=original,
            qi_category=self._category_of(annotation),
            reason=reason,
        )

    @staticmethod
    def _require_offsets(annotation: AnnotationLike) -> tuple[int, int]:
        start, end = annotation.start, annotation.end
        if start is None or end is None:
            raise PolicyEngineError(
                "Le moteur de politique ne peut pas produire de décision positionnelle "
                "pour une annotation sans offsets (IMPLICIT sans span)."
            )
        return start, end

    def _build_fixed_decision(
        self, annotation: AnnotationLike, text: str, action_name: str, id_type: str
    ) -> AnonymizationDecision:
        start, end = self._require_offsets(annotation)
        original = text[start:end]
        category = self._category_of(annotation)
        action = Action(action_name)
        granularity = self._granularity_of(annotation) if id_type != "DIRECT" else None
        check_action_allowed(id_type, granularity, action)

        replacement = self._render_replacement(action, category, original)
        reason = (
            f"Politique {self.policy.label} : {id_type} -> {action.value} "
            f"(action fixe, indépendante du risque estimé)."
        )
        return AnonymizationDecision(
            start=start,
            end=end,
            original=original,
            action=action,
            replacement=replacement,
            qi_category=category,
            reason=reason,
            meta=self._risk_status_meta(),
        )

    def _render_replacement(self, action: Action, category: str, original: str) -> str:
        if action is Action.KEEP:
            return original
        if action is Action.SUPPRESS:
            return f"[{category}_SUPPRIME]"
        if action is Action.PSEUDONYMIZE:
            # Le moteur de politique ne détient pas de secret HMAC : produire
            # un placeholder stable est la responsabilité de l'appelant, qui
            # peut post-traiter les décisions PSEUDONYMIZE avec un
            # `PseudoMapper` partagé. Ici, un jeton explicite et traçable.
            return f"[{category}_A_PSEUDONYMISER]"
        raise PolicyEngineError(f"Action {action} non attendue pour une décision fixe")

    # ------------------------------------------------------------------ #
    # QUASI : pilotage par le risque (SPEC-06 §9)
    # ------------------------------------------------------------------ #
    def _plan_quasi(self, annotations: list[AnnotationLike], text: str) -> list[AnonymizationDecision]:
        if not annotations:
            return []

        default_action = self.policy.actions.get("QUASI", "KEEP")

        if default_action == "KEEP":
            return [
                self._keep_decision(
                    ann, text, f"Politique {self.policy.label} : QUASI -> KEEP (QI non traités par cette politique)."
                )
                for ann in annotations
            ]

        if default_action == "SUPPRESS":
            return [
                self._suppress_decision(
                    ann,
                    text,
                    f"Politique {self.policy.label} : QUASI -> SUPPRESS (protection maximale, "
                    f"indépendante du risque estimé).",
                    risk_before=None,
                    risk_after=None,
                )
                for ann in annotations
            ]

        if default_action != "GENERALIZE":
            raise PolicyEngineError(f"Action QUASI non gérée par le moteur de risque : {default_action!r}")

        return self._plan_quasi_generalize(annotations, text)

    def _suppress_decision(
        self,
        annotation: AnnotationLike,
        text: str,
        reason: str,
        *,
        risk_before: float | None,
        risk_after: float | None,
    ) -> AnonymizationDecision:
        start, end = self._require_offsets(annotation)
        original = text[start:end]
        category = self._category_of(annotation)
        granularity = self._granularity_of(annotation)
        check_action_allowed("QUASI", granularity, Action.SUPPRESS)
        return AnonymizationDecision(
            start=start,
            end=end,
            original=original,
            action=Action.SUPPRESS,
            replacement=f"[{category}_SUPPRIME]",
            qi_category=category,
            reason=reason,
            risk_before=risk_before,
            risk_after=risk_after,
            meta=self._risk_status_meta(),
        )

    def _plan_quasi_generalize(self, annotations: list[AnnotationLike], text: str) -> list[AnonymizationDecision]:
        by_id: dict[str, AnnotationLike] = {}
        state: dict[str, dict[str, Any]] = {}
        active: list[str] = []

        for index, ann in enumerate(annotations):
            aid = getattr(ann, "annotation_id", None) or f"anon-{index}"
            by_id[aid] = ann
            value = getattr(ann, "value_normalized", None) or {}
            state[aid] = dict(value)
            state[aid].setdefault("level", 0)
            active.append(aid)

        threshold = self.policy.thresholds.keep_below
        max_steps = self.policy.max_generalization_steps

        def compute_risk(active_ids: list[str]) -> float:
            qi_states = [
                _QiState(aid, self._category_of(by_id[aid]), state[aid].get("level", 0)) for aid in active_ids
            ]
            return self._risk_fn(qi_states)

        risk = compute_risk(active)
        risk_initial = risk
        suppressed: set[str] = set()

        while risk > threshold and active:
            best_choice: tuple[float, str, str, dict[str, Any] | None, float] | None = None
            # (ratio, aid, action_name, new_value_or_None, new_risk)

            for aid in list(active):
                ann = by_id[aid]
                category = self._category_of(ann)
                current_level = state[aid].get("level", 0)
                try:
                    available = levels_available(state[aid], category)
                except (MalformedValueNormalizedError, UnknownGeneralizationCategoryError):
                    # Pas de hiérarchie de généralisation pour cette catégorie
                    # (table non exhaustive : HR_*, GEN_GENDER, GEN_DATE_EVENT…)
                    # ou état non utilisable : le QI est réputé épuisé au niveau
                    # 0 — le repli prévu par l'algorithme SPEC-06 §9 (SUPPRESS)
                    # s'applique au lieu d'une erreur d'exécution.
                    available = 0
                under_cap = max_steps is None or current_level < max_steps
                granularity_key = str(getattr(self._granularity_of(ann), "value", self._granularity_of(ann)))
                is_coarse = granularity_key == "COARSE"

                if available > 0 and under_cap and not is_coarse:
                    try:
                        result = generalize(state[aid], category, steps=1)
                    except (MalformedValueNormalizedError, UnknownGeneralizationCategoryError):
                        # ``value_normalized`` ne porte pas la forme attendue
                        # par la hiérarchie : seule la voie de suppression reste
                        # jouable pour ce QI.
                        result = None
                    if result is not None:
                        _, new_value = result
                        trial_active = active
                        saved = state[aid]
                        state[aid] = new_value
                        new_risk = compute_risk(trial_active)
                        state[aid] = saved
                        delta_risk = max(0.0, risk - new_risk)
                        delta_utility = self._utility_cost["GENERALIZE_PER_LEVEL"]
                        ratio = delta_risk / delta_utility if delta_utility > 0 else float("inf")
                        if best_choice is None or ratio > best_choice[0]:
                            best_choice = (ratio, aid, "GENERALIZE", new_value, new_risk)

                trial_active_wo = [a for a in active if a != aid]
                new_risk_sup = compute_risk(trial_active_wo)
                delta_risk_sup = max(0.0, risk - new_risk_sup)
                delta_utility_sup = self._utility_cost["SUPPRESS"]
                ratio_sup = delta_risk_sup / delta_utility_sup if delta_utility_sup > 0 else float("inf")
                if best_choice is None or ratio_sup > best_choice[0]:
                    best_choice = (ratio_sup, aid, "SUPPRESS", None, new_risk_sup)

            if best_choice is None:
                break

            _, aid, action_name, new_value, new_risk = best_choice
            if action_name == "GENERALIZE" and new_value is not None:
                state[aid] = new_value
            else:
                active.remove(aid)
                suppressed.add(aid)
            risk = new_risk

        # Seuil non atteint malgré l'épuisement des actions possibles :
        # SUPPRESS les QI restants (dernière étape de l'algorithme SPEC-06 §9).
        if risk > threshold and active:
            for aid in list(active):
                active.remove(aid)
                suppressed.add(aid)
            risk = compute_risk(active)  # = 0.0, plus aucun QI actif

        decisions: list[AnonymizationDecision] = []
        for aid, ann in by_id.items():
            category = self._category_of(ann)
            if aid in suppressed:
                decisions.append(
                    self._suppress_decision(
                        ann,
                        text,
                        (
                            f"Politique {self.policy.label} : risque estimé initial "
                            f"{risk_initial:.3f} > seuil {threshold:.3f} ; suppression de {category} "
                            f"(hiérarchie de généralisation épuisée ou insuffisante à elle seule)."
                        ),
                        risk_before=risk_initial,
                        risk_after=risk,
                    )
                )
                continue

            level = state[aid].get("level", 0)
            start, end = self._require_offsets(ann)
            original = text[start:end]
            granularity = self._granularity_of(ann)

            if level == 0:
                decisions.append(
                    AnonymizationDecision(
                        start=start,
                        end=end,
                        original=original,
                        action=Action.KEEP,
                        replacement=original,
                        qi_category=category,
                        reason=(
                            f"Politique {self.policy.label} : risque estimé {risk:.3f} <= seuil "
                            f"{threshold:.3f} dès la valeur exacte, aucune généralisation nécessaire."
                        ),
                        risk_before=risk_initial,
                        risk_after=risk,
                        meta=self._risk_status_meta(),
                    )
                )
                continue

            check_action_allowed("QUASI", granularity, Action.GENERALIZE)
            surface, _ = generalize({**(getattr(ann, "value_normalized", None) or {}), "level": 0}, category, steps=level)  # type: ignore[arg-type]
            decisions.append(
                AnonymizationDecision(
                    start=start,
                    end=end,
                    original=original,
                    action=Action.GENERALIZE,
                    replacement=surface,
                    qi_category=category,
                    reason=(
                        f"Politique {self.policy.label} : risque ramené à {risk:.3f} "
                        f"(seuil {threshold:.3f}) en généralisant {category} de {level} niveau(x)."
                    ),
                    risk_before=risk_initial,
                    risk_after=risk,
                    meta=self._risk_status_meta(),
                )
            )

        return decisions
