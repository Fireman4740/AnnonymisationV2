"""Étapes AUDIT (AttackerA) et REWRITE : la boucle d'attaque bornée.

**AUDIT** — ``AttackerA`` = ``LlmClient.for_role("attacker_a")`` appelé sur
le **texte anonymisé seul** : ni original, ni gold, ni annotations, ni Q
latents ne figurent dans le prompt. La réponse stricte
``{inferred_qis, direct_ids_recovered}`` est comparée à Q(d) avec un seuil
de confiance 0.70 : la trace ne conserve que compteurs, catégories et
confidences — **aucune preuve ou sortie brute n'est journalisée** sur
corpus réel.

**REWRITE** — ``LlmClient.for_role("paraphrase")``, au plus
``max_rewrite_rounds`` passes (1–2) sur le texte anonymisé avec les
catégories à casser et les contraintes métier. Réponse stricte
``{text, changed_categories}``. Refus explicites : réponse vide (client,
C3), texte identique à l'entrée, longueur hors budget (±30 %), identifiant
direct réintroduit (détecteur natif), non-progression entre passes.
Après chaque passe, le système rejoue VALIDATE puis AUDIT ; une fuite
haute confiance subsistante après les deux passes produit une erreur
nommée, jamais un score partiel.

Règles communes : température 0 et cache **obligatoire** (jamais
``use_cache=False``), erreurs LLM remontées explicitement, aucune réponse
vide interprétée comme « aucun QI » (C3), prompts versionnés mentionnant
langue/domaine et les codes SPEC-01 offerts.
"""

from __future__ import annotations

import json
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import Any

from pydantic import BaseModel, ConfigDict, Field

from anonymisation.detect import DeterministicDetector
from anonymisation.llm.client import LlmClient
from anonymisation.schema.taxonomy import IdentifierType, validate_code

from .prompts import prompt_sha256

__all__ = [
    "ATTACK_PROMPT_VERSION",
    "REWRITE_LENGTH_TOLERANCE",
    "REWRITE_PROMPT_VERSION",
    "AttackerA",
    "AttackerAResponse",
    "AttackerAReport",
    "AttackInferredQi",
    "AttackRecoveredDirect",
    "AttackResponseError",
    "LEAK_CONFIDENCE_THRESHOLD",
    "RewriteResponse",
    "RewriteResponseError",
    "Rewriter",
    "RewriteResult",
    "build_attack_prompt",
    "build_rewrite_prompt",
]

ATTACK_PROMPT_VERSION: str = "1.0"
REWRITE_PROMPT_VERSION: str = "1.0"

#: Seuil de confiance au-dessus duquel une inférence de l'attaquant
#: compte comme fuite (plan AUDIT).
LEAK_CONFIDENCE_THRESHOLD: float = 0.70

#: Tolérance relative de longueur de la réécriture (plan REWRITE).
REWRITE_LENGTH_TOLERANCE: float = 0.30


# --------------------------------------------------------------------------- #
# Erreurs
# --------------------------------------------------------------------------- #
class AttackResponseError(RuntimeError):
    """Réponse AttackerA inutilisable : JSON invalide, champ manquant,
    code SPEC-01 inconnu, confiance hors [0,1]. Nomme le champ fautif,
    la valeur et le correctif.

    Une réponse **vide** lève déjà plus en amont (``LlmEmptyResponseError``
    du client) — elle n'est jamais interprétée comme « aucun QI » (C3).
    """


class RewriteResponseError(RuntimeError):
    """Réécriture refusée : JSON invalide, texte identique à l'entrée,
    longueur hors budget, identifiant direct réintroduit,
    non-progression entre passes. Nomme la cause et le correctif."""


# --------------------------------------------------------------------------- #
# Modèles stricts
# --------------------------------------------------------------------------- #
class AttackInferredQi(BaseModel):
    """QI que l'attaquant prétend inférer depuis le texte anonymisé."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    category: str
    value: str
    confidence: float = Field(ge=0.0, le=1.0)


class AttackRecoveredDirect(BaseModel):
    """Identifiant direct que l'attaquant prétend avoir rétabli."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    value: str
    confidence: float = Field(ge=0.0, le=1.0)


class AttackerAResponse(BaseModel):
    """Contrat de sortie de l'attaque : JSON unique, strict."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    inferred_qis: list[AttackInferredQi]
    direct_ids_recovered: list[AttackRecoveredDirect] = Field(default_factory=list)


class RewriteResponse(BaseModel):
    """Contrat de sortie de la réécriture : JSON unique, strict."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    text: str
    changed_categories: list[str]


# --------------------------------------------------------------------------- #
# Prompts (versionnés — le SHA-256 est tracé dans l'audit)
# --------------------------------------------------------------------------- #
def build_attack_prompt(
    *,
    text: str,
    language: str,
    domain: str | None,
    qi_codes: Sequence[str],
) -> str:
    """Prompt AttackerA : texte anonymisé seul, codes SPEC-01 offerts,
    contrat JSON explicite. Ni original, ni gold, ni annotations."""
    codes = ", ".join(qi_codes)
    return (
        f"ATTACK-PROMPT v{ATTACK_PROMPT_VERSION}\n"
        f"Langue du document: {language}. Domaine: {domain or 'non spécifié'}.\n"
        "Tu es un attaquant qui examine le texte ANONYMISÉ ci-dessous.\n"
        "Ta tâche: retrouver, depuis ce texte seul, les quasi-identifiants "
        "et identifiants directs qui y subsisteraient.\n"
        f"Codes de quasi-identifiants à considérer (classification SPEC-01): {codes}.\n"
        "Contrat de sortie: un objet JSON unique, sans commentaire ni texte "
        "autour, de la forme:\n"
        '{"inferred_qis": [{"category": <code SPEC-01>, "value": '
        "<valeur reconstituée depuis le texte>, "
        '"confidence": <nombre 0..1>}], '
        '"direct_ids_recovered": [{"value": <identifiant direct retrouvé '
        "(email, téléphone, adresse, ...), "
        '"confidence": <nombre 0..1>}]}\n'
        "Règles: ne réinvente aucune valeur — `value` doit apparaître ou "
        "être déductible du texte fourni; `confidence` est ta confiance "
        "réelle; si rien ne peut être inféré, renvoie exactement "
        '{"inferred_qis": [], "direct_ids_recovered": []}.\n'
        "Réponds uniquement avec le JSON.\n"
        "----- TEXTE ANONYMISÉ -----\n"
        f"{text}\n"
        "----- FIN DU TEXTE -----"
    )


def build_rewrite_prompt(
    *,
    text: str,
    language: str,
    domain: str | None,
    target_categories: Sequence[str],
    business_constraints: Sequence[str],
) -> str:
    """Prompt de réécriture : texte anonymisé, catégories à casser,
    contraintes métier. Aucune information hors du texte anonymisé."""
    categories = ", ".join(target_categories)
    constraints = "\n".join(f"- {c}" for c in business_constraints) or (
        "- conserver le sens, la langue et la lisibilité du texte"
    )
    return (
        f"REWRITE-PROMPT v{REWRITE_PROMPT_VERSION}\n"
        f"Langue: {language}. Domaine: {domain or 'non spécifié'}.\n"
        "Le texte anonymisé ci-dessous contient encore des "
        f"quasi-identifiants résistants (codes SPEC-01): {categories}.\n"
        "Réécris le texte COMPLET pour casser ces informations, en respectant:\n"
        f"{constraints}\n"
        f"- longueur du texte d'origine ±{REWRITE_LENGTH_TOLERANCE:.0%} ;\n"
        "- n'introduire aucun identifiant direct (email, téléphone, adresse, "
        "IBAN, numéro de sécurité, ...).\n"
        "Contrat de sortie: un objet JSON unique, sans commentaire, de la "
        f'forme: {{"text": <nouveau texte complet>, "changed_categories": '
        "[<codes SPEC-01 effectivement cassés>]}}\n"
        "Réponds uniquement avec le JSON.\n"
        "----- TEXTE ANONYMISÉ -----\n"
        f"{text}\n"
        "----- FIN DU TEXTE -----"
    )


# --------------------------------------------------------------------------- #
# AttackerA
# --------------------------------------------------------------------------- #
@dataclass(frozen=True)
class AttackerAReport:
    """Bilan d'audit — agrégats seuls : compteurs, catégories, confiances.
    Aucune preuve brute n'est conservée (corpus réel)."""

    inferred_qi_count: int
    direct_leak_count: int
    leaked_categories: tuple[str, ...]
    value_level_leaks: tuple[str, ...]
    max_confidence: float
    prompt_sha256: str
    model: str
    cached: bool

    @property
    def has_leak(self) -> bool:
        """Fuite = un QI de Q(d) inféré au-dessus du seuil OU un identifiant
        direct rétabli au-dessus du seuil."""
        return bool(self.leaked_categories) or self.direct_leak_count > 0

    def to_dict(self) -> dict[str, Any]:
        return {
            "inferred_qi_count": self.inferred_qi_count,
            "direct_leak_count": self.direct_leak_count,
            "leaked_categories": list(self.leaked_categories),
            "value_level_leaks": list(self.value_level_leaks),
            "max_confidence": self.max_confidence,
            "prompt_sha256": self.prompt_sha256,
            "model": self.model,
            "cached": self.cached,
            "has_leak": self.has_leak,
            "threshold": LEAK_CONFIDENCE_THRESHOLD,
        }


class AttackerA:
    """Attaquant A : ``LlmClient.for_role("attacker_a")``, température 0,
    cache obligatoire. Le prompt ne contient que le texte anonymisé."""

    def __init__(self, client: LlmClient) -> None:
        self._client = client

    def attack(
        self,
        *,
        text: str,
        language: str,
        domain: str | None,
        qi_codes: Sequence[str],
        qd_values: Mapping[str, frozenset[str]],
        threshold: float = LEAK_CONFIDENCE_THRESHOLD,
    ) -> AttackerAReport:
        """Attaque le texte anonymisé et compare à Q(d).

        ``qd_values`` : par code de QI présent dans Q(d), la frozenset des
        valeurs (normalisées) — sert au raffinement « fuite au niveau
        valeur » (valeur inférée égale à une valeur de Q(d)).

        Les erreurs LLM (backend injoignable, réponse vide — C3) remontent
        telles quelles ; une réponse malformée lève
        :class:`AttackResponseError`.
        """
        prompt = build_attack_prompt(
            text=text, language=language, domain=domain, qi_codes=qi_codes
        )
        completion = self._client.complete(prompt, temperature=0)  # cache: default
        payload = _load_strict_json(
            completion.content, error_class=AttackResponseError, label="attaque"
        )
        try:
            response = AttackerAResponse.model_validate(payload)
        except Exception as exc:
            raise AttackResponseError(
                f"réponse d'attaque invalide ({exc}) — le contrat exige un "
                "objet JSON {inferred_qis, direct_ids_recovered} avec des "
                "codes SPEC-01 valides et des confiances dans [0,1]."
            ) from exc

        for qi in response.inferred_qis:
            _validate_spec_code(qi.category, error_class=AttackResponseError)
        max_confidence = max(
            (qi.confidence for qi in response.inferred_qis),
            (d.confidence for d in response.direct_ids_recovered),
            default=0.0,
        )

        qd_categories = set(qd_values)
        leaked: list[AttackInferredQi] = [
            qi
            for qi in response.inferred_qis
            if qi.confidence >= threshold and qi.category in qd_categories
        ]
        value_level: list[str] = [
            qi.category
            for qi in leaked
            if _norm_value(qi.value) in qd_values.get(qi.category, frozenset())
        ]
        direct_leaks = [
            d for d in response.direct_ids_recovered if d.confidence >= threshold
        ]

        return AttackerAReport(
            inferred_qi_count=len(response.inferred_qis),
            direct_leak_count=len(direct_leaks),
            leaked_categories=tuple(sorted({qi.category for qi in leaked})),
            value_level_leaks=tuple(sorted(set(value_level))),
            max_confidence=max_confidence,
            prompt_sha256=prompt_sha256(prompt),
            model=completion.model,
            cached=completion.cached,
        )


# --------------------------------------------------------------------------- #
# Rewriter
# --------------------------------------------------------------------------- #
@dataclass(frozen=True)
class RewriteResult:
    """Sortie d'une passe de réécriture : nouveau texte + catégories
    cassées (aucune valeur — agrégats seuls)."""

    text: str
    changed_categories: tuple[str, ...]
    model: str
    cached: bool
    prompt_sha256: str


class Rewriter:
    """Réécriture du texte anonymisé : ``LlmClient.for_role("paraphrase")``,
    température 0, cache obligatoire.

    Chaque passe est validée avant acceptation : JSON strict, texte
    différent de l'entrée, longueur dans ±30 %, aucun identifiant direct
    réintroduit (détecteur natif réutilisé — jamais un deuxième moteur).
    """

    def __init__(
        self,
        client: LlmClient,
        *,
        detector: DeterministicDetector,
        qi_min_confidence: float = 0.30,
        length_tolerance: float = REWRITE_LENGTH_TOLERANCE,
    ) -> None:
        self._client = client
        self._detector = detector
        self._qi_min_confidence = qi_min_confidence
        self._length_tolerance = length_tolerance

    def rewrite(
        self,
        *,
        text: str,
        language: str,
        domain: str | None,
        target_categories: Sequence[str],
        business_constraints: Sequence[str] = (),
    ) -> RewriteResult:
        prompt = build_rewrite_prompt(
            text=text,
            language=language,
            domain=domain,
            target_categories=target_categories,
            business_constraints=business_constraints,
        )
        completion = self._client.complete(prompt, temperature=0)  # cache: default
        payload = _load_strict_json(
            completion.content, error_class=RewriteResponseError, label="réécriture"
        )
        try:
            response = RewriteResponse.model_validate(payload)
        except Exception as exc:
            raise RewriteResponseError(
                f"réponse de réécriture invalide ({exc}) — le contrat exige "
                "un objet JSON {text, changed_categories}."
            ) from exc

        for code in response.changed_categories:
            _validate_spec_code(code, error_class=RewriteResponseError)
        if not response.text.strip():
            raise RewriteResponseError(
                "réécriture refusée : texte renvoyé vide — la réécriture "
                "doit produire un texte complet."
            )
        if response.text == text:
            raise RewriteResponseError(
                "réécriture refusée : texte identique à l'entrée — "
                "non-progression (le modèle n'a rien cassé)."
            )
        old_len = len(text)
        new_len = len(response.text)
        if old_len > 0:
            deviation = abs(new_len - old_len) / old_len
            if deviation > self._length_tolerance:
                raise RewriteResponseError(
                    f"réécriture refusée : longueur {new_len} hors budget "
                    f"(origine {old_len}, tolérance ±{self._length_tolerance:.0%}) — "
                    "contrainte métier non respectée."
                )
        reintroduced = [
            c
            for c in self._detector.detect_raw(response.text, language=language)
            if c.identifier_type is IdentifierType.DIRECT
            and c.confidence >= self._qi_min_confidence
        ]
        if reintroduced:
            first = reintroduced[0]
            raise RewriteResponseError(
                f"réécriture refusée : identifiant direct réintroduit "
                f"({first.qi_category} en position {first.start} — "
                f"{len(reintroduced)} au total) — la réécriture ne doit "
                "jamais rajouter d'identifiants directs."
            )
        return RewriteResult(
            text=response.text,
            changed_categories=tuple(response.changed_categories),
            model=completion.model,
            cached=completion.cached,
            prompt_sha256=prompt_sha256(prompt),
        )


# --------------------------------------------------------------------------- #
# Aides
# --------------------------------------------------------------------------- #
def _load_strict_json(
    content: str, *, error_class: type[RuntimeError], label: str
) -> Any:
    """JSON unique, strict : jamais de balisage autour, jamais de texte
    partiel (règle d'or — l'ambiguïté est une erreur, pas un best-effort)."""
    try:
        return json.loads(content)
    except json.JSONDecodeError as exc:
        raise error_class(
            f"réponse {label} : JSON invalide ({exc.msg} ligne {exc.lineno} "
            f"colonne {exc.colno}) — le contrat exige un objet JSON unique "
            "sans commentaire."
        ) from exc


def _validate_spec_code(code: str, *, error_class: type[RuntimeError]) -> None:
    try:
        validate_code(code)
    except Exception as exc:
        raise error_class(
            f"code SPEC-01 inconnu {code!r} dans la réponse ({exc}) — "
            "corriger le prompt ou le mapping ; jamais deviné."
        ) from exc


def _norm_value(value: str) -> str:
    return " ".join(value.split()).casefold()
