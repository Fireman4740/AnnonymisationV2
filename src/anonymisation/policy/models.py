"""Modèles Pydantic pour ``configs/policy/policies.yaml`` (SPEC-06 §9).

Un YAML de politique incohérent DOIT échouer au chargement (règle d'or du
projet : pas de dégradation silencieuse). Deux invariants sont vérifiés ici,
en plus de la validation Pydantic standard :

* les seuils d'une politique sont **monotones**
  (``keep_below <= generalize_below <= suppress_above``) ;
* toute action mentionnée dans la section ``actions`` d'une politique est un
  membre connu de :class:`anonymisation.transform.decisions.Action`.
"""

from __future__ import annotations

from itertools import pairwise
from pathlib import Path
from typing import Any, Final

import yaml
from pydantic import BaseModel, ConfigDict, model_validator

from anonymisation.transform.decisions import Action

_BASE = ConfigDict(frozen=True, extra="forbid")

#: Types d'identifiants configurables dans la section ``actions`` d'une
#: politique. ``IGNORED`` n'y figure pas : il est toujours ``KEEP`` (SPEC-01 §8).
_POLICY_ACTION_KEYS: Final[frozenset[str]] = frozenset({"DIRECT", "QUASI", "SENSITIVE_ONLY"})


class PolicyConfigError(ValueError):
    """Le fichier de politique est structurellement invalide."""


class Thresholds(BaseModel):
    """Seuils de risque d'une politique (SPEC-06 §9).

    Sémantique : en dessous de ``keep_below``, aucune action n'est requise ;
    en dessous de ``generalize_below``, la généralisation suffit ; à partir de
    ``suppress_above``, la suppression est requise. Les trois seuils doivent
    être monotones non décroissants.
    """

    model_config = _BASE

    keep_below: float
    generalize_below: float | None = None
    suppress_above: float | None = None

    @model_validator(mode="after")
    def _check_monotone(self) -> Thresholds:
        for value, name in (
            (self.keep_below, "keep_below"),
            (self.generalize_below, "generalize_below"),
            (self.suppress_above, "suppress_above"),
        ):
            if value is not None and not (0.0 <= value <= 1.0):
                raise PolicyConfigError(f"{name}={value!r} doit être dans [0, 1]")

        ordered = [self.keep_below]
        if self.generalize_below is not None:
            ordered.append(self.generalize_below)
        if self.suppress_above is not None:
            ordered.append(self.suppress_above)

        for lower, upper in pairwise(ordered):
            if lower > upper:
                raise PolicyConfigError(
                    f"Seuils non monotones : {ordered} "
                    "(attendu keep_below <= generalize_below <= suppress_above)"
                )
        return self


class Policy(BaseModel):
    """Une politique nommée (P0..P4)."""

    model_config = _BASE

    label: str
    description: str | None = None
    thresholds: Thresholds
    actions: dict[str, str]
    max_generalization_steps: int | None = None
    scope: str | None = None

    @model_validator(mode="after")
    def _check_actions(self) -> Policy:
        unknown_keys = set(self.actions) - _POLICY_ACTION_KEYS
        if unknown_keys:
            raise PolicyConfigError(
                f"Clés d'actions inconnues dans la politique {self.label!r} : {sorted(unknown_keys)}. "
                f"Clés valides : {sorted(_POLICY_ACTION_KEYS)}."
            )
        known_actions = {a.value for a in Action}
        for id_type, action in self.actions.items():
            if action not in known_actions:
                raise PolicyConfigError(
                    f"Action inconnue {action!r} pour {id_type!r} dans la politique {self.label!r}. "
                    f"Actions valides : {sorted(known_actions)}."
                )
        if self.max_generalization_steps is not None and self.max_generalization_steps < 1:
            raise PolicyConfigError("max_generalization_steps doit être >= 1 si défini")
        return self


class Defaults(BaseModel):
    """Bloc ``defaults`` du fichier de politique."""

    model_config = _BASE

    risk_model: str
    scope: str
    use_upper_bound: bool
    k_seuil_at_risk: int
    sensitive_hardening: bool
    action_selection: str


class PolicySet(BaseModel):
    """L'ensemble du fichier ``policies.yaml`` chargé et validé."""

    model_config = _BASE

    defaults: Defaults
    policies: dict[str, Policy]

    @model_validator(mode="after")
    def _check_non_empty(self) -> PolicySet:
        if not self.policies:
            raise PolicyConfigError("Aucune politique définie : 'policies' est vide")
        return self

    def get(self, name: str) -> Policy:
        """Retourne la politique ``name`` (ex. ``"P2"``), échoue sinon."""
        try:
            return self.policies[name]
        except KeyError as exc:
            raise PolicyConfigError(
                f"Politique inconnue : {name!r}. Disponibles : {sorted(self.policies)}."
            ) from exc


def load_policy_set(path: str | Path) -> PolicySet:
    """Charge et valide un fichier de politiques YAML.

    Toute incohérence (seuils non monotones, action inconnue, YAML malformé)
    échoue ici, avant que le moteur ne puisse produire une décision fondée sur
    une politique invalide.
    """
    path = Path(path)
    with path.open("r", encoding="utf-8") as fh:
        raw: Any = yaml.safe_load(fh)
    if not isinstance(raw, dict):
        raise PolicyConfigError(f"Fichier de politique malformé : {path} (attendu un mapping YAML)")
    try:
        return PolicySet.model_validate(raw)
    except Exception as exc:  # pydantic.ValidationError ou PolicyConfigError levée dans un validator
        raise PolicyConfigError(f"Échec du chargement de {path} : {exc}") from exc
