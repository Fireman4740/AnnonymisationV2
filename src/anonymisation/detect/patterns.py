"""Chargement et exécution des motifs déclaratifs (``configs/detection/patterns.yaml``).

Principe : le YAML est la seule source de vérité pour les regex de détecteurs
« bas niveau » (email, IBAN, IP...). Le code ne fait que compiler, valider et
appliquer — aucune regex n'est en dur dans ce module.

Règle d'or reprise de l'audit v1 : **pas de dégradation silencieuse**. Un
validateur cité dans le YAML mais absent de ``validators.VALIDATORS`` fait
échouer le chargement, pas l'ignorance du champ ``validator``.
"""

from __future__ import annotations

import re
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Final

import yaml

from anonymisation.detect.base import Candidate
from anonymisation.detect.validators import VALIDATORS
from anonymisation.schema.taxonomy import (
    ExpressionMode,
    Granularity,
    IdentifierType,
    Stability,
    validate_code,
)

DEFAULT_PATTERNS_PATH: Path = (
    Path(__file__).resolve().parents[3] / "configs" / "detection" / "patterns.yaml"
)


#: Facteur appliqué à la confiance d'un candidat DIRECT dont le contexte
#: correspond à un `deny_context`. Dégrader plutôt qu'écarter : un faux
#: négatif de confidentialité est plus grave qu'un faux positif.
_DENY_CONFIDENCE_FACTOR: Final[float] = 0.5


class PatternConfigError(ValueError):
    """Erreur de configuration YAML — échec de chargement volontaire."""


@dataclass(frozen=True)
class CompiledPattern:
    """Un motif YAML compilé, prêt à être appliqué à un texte."""

    id: str
    qi_category: str
    identifier_type: IdentifierType
    granularity: Granularity
    stability: Stability
    languages: tuple[str, ...]
    regex: re.Pattern[str]
    validator: Callable[[str], Any] | None
    validator_name: str | None
    confidence: float
    context_boost: tuple[str, ...]
    deny_context: tuple[str, ...]
    context_window: int = 40
    #: Sensibilité à la casse. Certains identifiants sont **définis**
    #: en majuscules (BIC, IBAN) : les compiler en IGNORECASE faisait
    #: matcher n'importe quel mot de 8 ou 11 lettres — « transmis »,
    #: « derniere » — et produisait un sur-masquage massif du français.
    ignore_case: bool = True

    def matches_language(self, language: str) -> bool:
        return "*" in self.languages or language in self.languages


def _require(mapping: dict[str, Any], key: str, entry_id: str) -> Any:
    if key not in mapping:
        raise PatternConfigError(f"Motif {entry_id!r} : champ obligatoire manquant {key!r}")
    return mapping[key]


def load_patterns(config_path: Path | None = None) -> tuple[list[CompiledPattern], dict[str, list[str]]]:
    """Charge et compile ``patterns.yaml``.

    Retourne ``(patterns, lexicons)`` : les motifs regex compilés et les
    lexiques bruts (clé -> liste de termes) consommés par ``rules.py``.

    Lève ``PatternConfigError`` sur toute anomalie : regex invalide,
    validateur inconnu, code de catégorie hors taxonomie, champ manquant.
    Un YAML malformé n'est jamais ignoré en silence.
    """
    path = config_path or DEFAULT_PATTERNS_PATH
    if not path.exists():
        raise PatternConfigError(f"Fichier de configuration introuvable : {path}")

    try:
        raw = yaml.safe_load(path.read_text(encoding="utf-8"))
    except yaml.YAMLError as exc:
        raise PatternConfigError(f"YAML invalide dans {path} : {exc}") from exc

    if not isinstance(raw, dict):
        raise PatternConfigError(f"{path} doit contenir un mapping YAML au premier niveau")

    entries = raw.get("patterns")
    if not isinstance(entries, list) or not entries:
        raise PatternConfigError(f"{path} : clé 'patterns' absente ou vide")

    compiled: list[CompiledPattern] = []
    seen_ids: set[str] = set()
    for entry in entries:
        if not isinstance(entry, dict):
            raise PatternConfigError(f"Entrée de motif invalide (pas un mapping) : {entry!r}")

        entry_id = _require(entry, "id", "?")
        if entry_id in seen_ids:
            raise PatternConfigError(f"Identifiant de motif dupliqué : {entry_id!r}")
        seen_ids.add(entry_id)

        qi_category = validate_code(_require(entry, "qi_category", entry_id))

        try:
            identifier_type = IdentifierType(_require(entry, "identifier_type", entry_id))
        except ValueError as exc:
            raise PatternConfigError(
                f"Motif {entry_id!r} : identifier_type invalide : {exc}"
            ) from exc
        try:
            granularity = Granularity(_require(entry, "granularity", entry_id))
        except ValueError as exc:
            raise PatternConfigError(
                f"Motif {entry_id!r} : granularity invalide : {exc}"
            ) from exc
        try:
            stability = Stability(_require(entry, "stability", entry_id))
        except ValueError as exc:
            raise PatternConfigError(
                f"Motif {entry_id!r} : stability invalide : {exc}"
            ) from exc

        languages = tuple(entry.get("languages", ["*"]))

        regex_str = _require(entry, "regex", entry_id)
        try:
            ignore_case = bool(entry.get("ignore_case", True))
            flags = re.UNICODE | (re.IGNORECASE if ignore_case else 0)
            regex = re.compile(regex_str, flags)
        except re.error as exc:
            raise PatternConfigError(f"Motif {entry_id!r} : regex invalide : {exc}") from exc

        validator_name = entry.get("validator")
        validator_fn: Callable[[str], Any] | None = None
        if validator_name is not None:
            validator_key = str(validator_name)
            validator_fn = VALIDATORS.get(validator_key)
            if validator_fn is None:
                raise PatternConfigError(
                    f"Motif {entry_id!r} : validateur inconnu {validator_name!r}. "
                    f"Validateurs disponibles : {sorted(VALIDATORS)}"
                )

        confidence = float(entry.get("confidence", 0.9))
        if not 0.0 <= confidence <= 1.0:
            raise PatternConfigError(f"Motif {entry_id!r} : confidence hors [0,1]")

        compiled.append(
            CompiledPattern(
                id=entry_id,
                qi_category=qi_category,
                identifier_type=identifier_type,
                granularity=granularity,
                stability=stability,
                languages=languages,
                regex=regex,
                validator=validator_fn,
                validator_name=validator_name,
                confidence=confidence,
                context_boost=tuple(entry.get("context_boost", [])),
                deny_context=tuple(entry.get("deny_context", [])),
                ignore_case=ignore_case,
            )
        )

    lexicons_raw = raw.get("lexicons", {})
    if not isinstance(lexicons_raw, dict):
        raise PatternConfigError(f"{path} : clé 'lexicons' doit être un mapping")
    lexicons: dict[str, list[str]] = {}
    for key, values in lexicons_raw.items():
        if not isinstance(values, list):
            raise PatternConfigError(f"Lexique {key!r} doit être une liste")
        lexicons[key] = [str(v) for v in values]

    return compiled, lexicons


def _context_window(text: str, start: int, end: int, window: int) -> str:
    lo = max(0, start - window)
    hi = min(len(text), end + window)
    return text[lo:hi].lower()


def apply_patterns(
    text: str,
    language: str,
    patterns: Sequence[CompiledPattern],
) -> list[Candidate]:
    """Applique tous les motifs compilés à ``text`` et produit des ``Candidate``.

    Un candidat est rejeté seulement si :
    * un validateur est déclaré et échoue, ou
    * un mot de ``deny_context`` apparaît dans la fenêtre de contexte.

    ``context_boost`` augmente la confiance (plafonnée à 1.0) sans jamais la
    faire baisser — conformément à la règle "le rappel prime sur la
    précision" (SPEC-07 §2), on ne pénalise pas l'absence de contexte positif.
    """
    candidates: list[Candidate] = []
    for pattern in patterns:
        if not pattern.matches_language(language):
            continue
        for match in pattern.regex.finditer(text):
            start, end = match.start(), match.end()
            span_text = match.group(0)

            if pattern.validator is not None:
                result = pattern.validator(span_text)
                if not result:
                    continue
            else:
                result = None

            window = _context_window(text, start, end, pattern.context_window)
            confidence = pattern.confidence
            denied = any(word.lower() in window for word in pattern.deny_context)
            if denied:
                # Privacy-first (SPEC-07 §2) : un `deny_context` NE DOIT PAS
                # faire disparaître un identifiant DIRECT. Les domaines
                # réservés (RFC 2606 : example.com, exemple.fr) sont
                # précisément ceux qu'emploient les corpus synthétiques pour
                # des adresses **à protéger** : les écarter en silence
                # produisait une perte de rappel systématique et invisible.
                # On dégrade donc la confiance au lieu de jeter le candidat ;
                # la fusion et la politique restent libres de l'écarter, mais
                # de façon tracée.
                if pattern.identifier_type is IdentifierType.DIRECT:
                    confidence = round(confidence * _DENY_CONFIDENCE_FACTOR, 4)
                else:
                    continue
            if any(word.lower() in window for word in pattern.context_boost):
                confidence = min(1.0, confidence + 0.05)

            meta: dict[str, Any] = {}
            if denied:
                meta["deny_context_hit"] = True
            if isinstance(result, dict):
                meta["value_normalized"] = result

            candidates.append(
                Candidate(
                    start=start,
                    end=end,
                    text=span_text,
                    qi_category=pattern.qi_category,
                    identifier_type=pattern.identifier_type,
                    source=f"regex:{pattern.id}",
                    confidence=confidence,
                    granularity=pattern.granularity,
                    stability=pattern.stability,
                    expression_mode=ExpressionMode.EXPLICIT,
                    meta=meta,
                )
            )
    return candidates
