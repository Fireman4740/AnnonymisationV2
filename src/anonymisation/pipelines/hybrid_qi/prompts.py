"""Prompt versionné et parseur STRICT de l'extraction QI (LLM) — contrainte C3.

Contrat (SPEC-10 C3) : une réponse LLM n'est valide que si elle est un objet
JSON contenant :

* ``qis`` — liste d'objets ``{category, expression_mode, explicit, span,
  span_text, value, prior, confidence, entity_ref, evidence}`` ;
* ``uniqueness_claims`` — liste de ``{evidence, confidence}`` ;
* ``direct_ids_missed`` — liste de codes ``DIR_*`` valides.

Tout le reste — contenu vide, JSON invalide, clé manquante, code inconnu ou
hors périmètre, mode d'expression inconnu, ``prior`` hors ``PRIOR_LEVELS``,
score hors ``[0, 1]``, ``explicit`` incohérent avec ``expression_mode``, span
hors limites ou incohérent avec le texte, ``span_text`` absent ou divergent
pour un QI explicite, ``evidence`` vide pour un QI implicite — lève
:class:`ExtractionResponseError`. **Une réponse invalide n'est jamais
interprétée comme « aucun QI »** : le seul cas vide valide est ``qis: []``
dans un JSON valide.

Le prompt contient le texte original, la langue, le domaine, la liste des
codes admissibles (QUASI hors périmètre v1) et l'instruction « JSON only » ;
il est versionné (``PROMPT_VERSION``) et son empreinte (``prompt_sha256``)
est portée par :class:`QiExtraction` pour la reproductibilité.

Les prompts d'attaque / réécriture de l'étape AUDIT sont dans ``attack.py``.
"""

from __future__ import annotations

import hashlib
import json
import re
from typing import Any, Final

from pydantic import BaseModel, ConfigDict, Field

from anonymisation.schema.taxonomy import (
    DIRECT_CODES,
    OUT_OF_SCOPE_V1,
    QUASI_CODES,
)

from .risk import EXPRESSION_MODES, PRIOR_LEVELS

#: Version du contrat de prompt ; changée à toute modification du template.
PROMPT_VERSION: Final[str] = "1.0"

#: Codes QUASI proposés à l'extracteur : tous les QUASI applicables en v1
#: (hors périmètre ``FOR_STYLE`` / ``FOR_RELATION``, SPEC-06 §10).
OFFERED_QI_CODES: Final[tuple[str, ...]] = tuple(sorted(QUASI_CODES - OUT_OF_SCOPE_V1))

#: Codes DIRECT proposés pour ``direct_ids_missed`` (audit de couverture).
OFFERED_DIRECT_CODES: Final[tuple[str, ...]] = tuple(sorted(DIRECT_CODES - OUT_OF_SCOPE_V1))

#: Clôture d'un bloc de code JSON optionnel (le parseur tolère une seule
#: paire « ```json ... ``` » — jamais plus).
_CODE_FENCE_RE: Final[re.Pattern[str]] = re.compile(
    r"^```(?:json)?\s*\n?|\n?\s*```$",
    re.MULTILINE,
)


class ExtractionResponseError(ValueError):
    """Réponse LLM d'extraction QI invalide (contrainte C3).

    Le message nomme le champ fautif, la valeur reçue et le correctif
    attendu — jamais un timeout opaque. Cette erreur est **toujours**
    propagée : elle ne doit ni être avalée ni convertie en « aucun QI ».
    """


#: Erreur de construction de prompt (texte vide, langue/domaine absents).
class ExtractionPromptError(ValueError):
    """Paramètres du prompt d'extraction invalides (jamais de défaut
    silencieux)."""


def prompt_sha256(prompt: str) -> str:
    """Empreinte du prompt versionné (métadonnée d'extraction)."""
    return hashlib.sha256(prompt.encode("utf-8")).hexdigest()


# --------------------------------------------------------------------------- #
# Modèles stricts de la réponse
# --------------------------------------------------------------------------- #
class QiItem(BaseModel):
    """Un quasi-identifiant extrait (entrée de ``qis``).

    Invariants validés par :func:`parse_qi_extraction` (le modèle porte
    l'arborescence, le parseur porte la sémantique contre ``doc.text``) :

    * ``expression_mode ∈ EXPRESSION_MODES`` et ``explicit`` cohérent
      (``implicit ⇔ expression_mode == "IMPLICIT"``) ;
    * QI **explicite** (EXPLICIT / NON_STANDARD) : ``span`` fourni, dans
      ``[0, len(text)]`` avec ``start < end``, et ``text[start:end] ==
      span_text`` ;
    * QI **implicite** : ``span is null`` et ``evidence`` non vide ;
    * ``value`` : objet ou chaîne non vide ; ``confidence`` ∈ [0, 1] ;
      ``prior`` ∈ ``PRIOR_LEVELS`` (ou ``null``).
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    category: str
    expression_mode: str
    explicit: bool
    span: tuple[int, int] | None
    span_text: str | None
    value: dict[str, Any] | str
    prior: str | None = None
    confidence: float = Field(default=1.0, ge=0.0, le=1.0)
    entity_ref: str | None = None
    evidence: str | None = None


class UniquenessClaim(BaseModel):
    """Affirmation d'unicité portée par le texte (``uniqueness_claims``).

    ``confidence`` est la confiance de l'extracteur dans l'affirmation ;
    le seuil ``CLAIM_TRUST_THRESHOLD`` (``risk.py``) décide si l'estimateur
    la convertit en borne de risque, jamais l'inverse.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    evidence: str
    confidence: float = Field(default=0.0, ge=0.0, le=1.0)


class QiExtraction(BaseModel):
    """Extraction QI d'un document : la seule forme valide d'une réponse
    LLM d'extraction (``qis`` est toujours présent — vide inclus)."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    qis: tuple[QiItem, ...]
    uniqueness_claims: tuple[UniquenessClaim, ...] = ()
    direct_ids_missed: tuple[str, ...] = ()
    prompt_version: str = PROMPT_VERSION
    prompt_sha256: str = ""

    @property
    def has_qis(self) -> bool:
        return len(self.qis) > 0


# --------------------------------------------------------------------------- #
# Construction du prompt
# --------------------------------------------------------------------------- #
_QI_EXTRACTION_TEMPLATE: Final[str] = """Tu es un extracteur de quasi-identifiants (QI) multilingue (fr/en).

## Tâche
Extrais de l'ensemble le plus exhaustif de quasi-identifiants présents dans le texte, pour une évaluation du risque de ré-identification.

Règles strictes :
1. Réponds UNIQUEMENT avec un objet JSON valide, sans commentaire, sans texte avant ou après, sans markdown.
2. Schéma exact :
   {
     "qis": [
       {
         "category": <code>,
         "expression_mode": "EXPLICIT" | "NON_STANDARD" | "IMPLICIT",
         "explicit": <bool>,
         "span": [start, end] | null,
         "span_text": <string> | null,
         "value": <objet de valeur normalisée> | <string>,
         "prior": "rare" | "uncommon" | "common" | null,
         "confidence": <float 0..1>,
         "entity_ref": <string> | null,
         "evidence": <string> | null
       }
     ],
     "uniqueness_claims": [
       {"evidence": <string non vide>, "confidence": <float 0..1>}
     ],
     "direct_ids_missed": [<codes DIR_*>]
   }
3. Codes de catégorie autorisés (aucun autre) : {qi_codes}
4. ``span`` = [début, fin[ ] en **indices de caractères du texte original** (fin exclusive) ; obligatoire pour EXPLICIT et NON_STANDARD, ``null`` pour IMPLICIT.
5. ``span_text`` = la citation exacte du texte pour un QI explicite ; ``null`` sinon.
6. ``value`` = objet JSON de valeur normalisée (champs libres, ex. {{"age": 34}}) OU chaîne pour une valeur simple.
7. ``explicit`` = ``true`` si et seulement si ``expression_mode`` n'est pas "IMPLICIT" ; un QI implicite doit justifier son ``evidence`` (citations du texte qui l'impliquent).
8. ``entity_ref`` : identifiant commun (stable, opaque) des mentions de la **même entité réelle** (ex. « me » et « mon père » sont distincts du « père » d'un autre).
9. ``uniqueness_claims`` : affirmations explicites d'unicité dans le texte (« le seul », « unique », « un seul »…) ; liste vide sinon.
10. ``direct_ids_missed`` : codes DIR_* ({direct_codes}) que tu observes dans le texte mais qui ne sont pas couverts par les catégories ci-dessus ; liste vide sinon.
11. ``prior`` : rareté perçue de la valeur telle que déclinée dans le texte (rare / uncommon / common) ; ``null`` si incertain.
12. Si aucun QI n'est présent, réponds {{"qis": [], "uniqueness_claims": [], "direct_ids_missed": []}}.

Langue du texte : {language}
Domaine : {domain}

## Texte
{text}
"""


def build_qi_extraction_prompt(
    *,
    text: str,
    language: str,
    domain: str,
    qi_codes: tuple[str, ...] = OFFERED_QI_CODES,
) -> str:
    """Construit le prompt d'extraction QI versionné.

    Échoue (:class:`ExtractionPromptError`) sur un texte vide, une langue
    ou un domaine absents : le prompt est versionné et citable, il ne
    tolère aucun vide silencieux.
    """
    if not text.strip():
        raise ExtractionPromptError(
            "build_qi_extraction_prompt : texte vide — un prompt d'extraction "
            "sans texte n'est pas constructible (SPEC-10, règle d'or)."
        )
    if not language:
        raise ExtractionPromptError(
            "build_qi_extraction_prompt : langue absente — passe language="
            "'fr' ou 'en' (jamais de langue devinée)."
        )
    if not domain:
        raise ExtractionPromptError(
            "build_qi_extraction_prompt : domaine absent — passe domain="
            "(ex. 'rh', 'forum', 'support') : l'audit doit pouvoir tracer "
            "pourquoi le prompt a été construit."
        )
    return _QI_EXTRACTION_TEMPLATE.format(
        qi_codes=", ".join(qi_codes),
        direct_codes=", ".join(OFFERED_DIRECT_CODES),
        language=language,
        domain=domain,
        text=text,
    )


# --------------------------------------------------------------------------- #
# Parseur strict
# --------------------------------------------------------------------------- #
def _fail(
    detail: str,
    *,
    field: str,
    value: Any,
    fix: str,
) -> ExtractionResponseError:
    """Construit une ``ExtractionResponseError`` actionnable (nom + champ +
    valeur + correctif) — convention des messages d'erreur du projet."""
    return ExtractionResponseError(
        f"Extraction QI : réponse LLM invalide — champ {field!r} = {value!r} ; "
        f"{detail}. Correctif attendu : {fix}"
    )


def _required(item: dict[str, Any], key: str, index: int) -> Any:
    """Champ obligatoire d'un objet ``qis[i]`` : absent → erreur nommée."""
    if key not in item:
        raise _fail(
            "champ obligatoire manquant",
            field=f"qis[{index}].{key}",
            value="<absent>",
            fix=f"le champ {key!r} est obligatoire dans chaque QI",
        )
    return item[key]


def _strip_json_fence(content: str) -> str:
    """Retire une unique paire de clôtures markdown JSON.

    Au-delà d'une paire, le contenu n'est plus un objet JSON pur : c'est
    une erreur, pas une tolérance.
    """
    stripped = content.strip()
    if stripped.startswith("```"):
        stripped = _CODE_FENCE_RE.sub("", stripped).strip()
        if "```" in stripped:
            raise _fail(
                "plus d'une paire de clôtures de bloc de code dans la réponse",
                field="raw",
                value=content[:80],
                fix="le modèle doit répondre JSON nu, sans blocs de code",
            )
    return stripped


def parse_qi_extraction(
    content: str | None,
    *,
    text: str,
    max_entities: int = 64,
    prompt_sha256: str = "",
) -> QiExtraction:
    """Parse strict d'une réponse d'extraction QI (contrainte C3).

    ``content`` : le ``content`` brut de la complétion LLM. Toute anomalie
    lève :class:`ExtractionResponseError` — y compris une réponse **vide**,
    qui est une erreur de LLM, jamais « aucun QI ».

    ``max_entities`` : borne de ``len(qis) + len(uniqueness_claims)`` ; une
    réponse au-dessus est une erreur (défense du budget de contexte), pas un
    troncage silencieux.

    ``prompt_sha256`` : empreinte du prompt versionné utilisé (portée dans
    l'extraction pour la reproductibilité bit-à-bit).
    """
    if content is None:
        raise _fail(
            "réponse LLM nulle (le client n'a pas renvoyé de contenu)",
            field="content",
            value=None,
            fix="relancer le backend local ; une réponse vide est une erreur "
            "(C3), jamais « aucun QI »",
        )
    if not content.strip():
        raise _fail(
            "réponse LLM vide",
            field="content",
            value="",
            fix="relancer le backend local ; un contenu vide est une erreur "
            "(C3), jamais « aucun QI »",
        )

    payload = _strip_json_fence(content)
    try:
        raw = json.loads(payload)
    except json.JSONDecodeError as exc:
        raise _fail(
            f"JSON invalide ({exc.msg}, ligne {exc.lineno} colonne {exc.colno})",
            field="content",
            value=content[:200],
            fix="le modèle doit répondre strictement un objet JSON valide",
        ) from exc

    if not isinstance(raw, dict):
        raise _fail(
            "le JSON racine n'est pas un objet",
            field="<racine>",
            value=type(raw).__name__,
            fix="un objet {qis: [...], uniqueness_claims: [...], direct_ids_missed: [...]}",
        )

    if "qis" not in raw:
        raise _fail(
            "clé obligatoire manquante",
            field="qis",
            value="<absente>",
            fix="le JSON doit contenir la clé 'qis' (liste vide autorisée)",
        )

    raw_qis = raw["qis"]
    if not isinstance(raw_qis, list):
        raise _fail(
            "``qis`` n'est pas une liste",
            field="qis",
            value=type(raw_qis).__name__,
            fix="``qis`` doit être une liste d'objets QI",
        )

    raw_claims = raw.get("uniqueness_claims", [])
    if not isinstance(raw_claims, list):
        raise _fail(
            "``uniqueness_claims`` n'est pas une liste",
            field="uniqueness_claims",
            value=type(raw_claims).__name__,
            fix="``uniqueness_claims`` doit être une liste",
        )

    raw_direct = raw.get("direct_ids_missed", [])
    if not isinstance(raw_direct, list):
        raise _fail(
            "``direct_ids_missed`` n'est pas une liste",
            field="direct_ids_missed",
            value=type(raw_direct).__name__,
            fix="``direct_ids_missed`` doit être une liste de codes DIR_*",
        )

    if len(raw_qis) + len(raw_claims) > max_entities:
        raise _fail(
            f"{len(raw_qis) + len(raw_claims)} entités > borne {max_entities}",
            field="qis+uniqueness_claims",
            value=len(raw_qis) + len(raw_claims),
            fix=f"réduire la granularité de l'extraction (borne {max_entities})",
        )

    n = len(text)
    qis: list[QiItem] = []
    for i, item in enumerate(raw_qis):
        if not isinstance(item, dict):
            raise _fail(
                f"``qis[{i}]`` n'est pas un objet",
                field=f"qis[{i}]",
                value=type(item).__name__,
                fix="chaque QI est un objet au schéma du prompt",
            )

        category = _required(item, "category", i)
        if not isinstance(category, str) or category not in OFFERED_QI_CODES:
            raise _fail(
                "code de catégorie inconnu ou hors périmètre v1",
                field=f"qis[{i}].category",
                value=category,
                fix=f"choisir parmi {', '.join(OFFERED_QI_CODES)}",
            )

        mode = _required(item, "expression_mode", i)
        if not isinstance(mode, str) or mode not in EXPRESSION_MODES:
            raise _fail(
                "mode d'expression inconnu",
                field=f"qis[{i}].expression_mode",
                value=mode,
                fix=f"choisir parmi {', '.join(EXPRESSION_MODES)}",
            )

        explicit = _required(item, "explicit", i)
        if not isinstance(explicit, bool):
            raise _fail(
                "``explicit`` n'est pas un booléen",
                field=f"qis[{i}].explicit",
                value=explicit,
                fix="``explicit`` : true (EXPLICIT/NON_STANDARD) | false (IMPLICIT)",
            )
        if explicit != (mode != "IMPLICIT"):
            raise _fail(
                "``explicit`` incohérent avec ``expression_mode``",
                field=f"qis[{i}].explicit",
                value=explicit,
                fix=f"pour expression_mode={mode!r}, explicit doit être "
                f"{mode != 'IMPLICIT'}",
            )

        span = item.get("span")
        span_text = item.get("span_text")
        if span is not None:
            if (
                not isinstance(span, list)
                or len(span) != 2
                or not all(isinstance(x, int) and not isinstance(x, bool) for x in span)
            ):
                raise _fail(
                    "``span`` n'est pas un couple d'entiers",
                    field=f"qis[{i}].span",
                    value=span,
                    fix="``span`` : [start, end] entiers (end exclusive) ou null",
                )
            start, end = span
            if not (0 <= start < end <= n):
                raise _fail(
                    f"``span`` [{start}, {end}) hors limites du texte (longueur {n})",
                    field=f"qis[{i}].span",
                    value=span,
                    fix=f"0 <= start < end <= {n}",
                )
            if not isinstance(span_text, str) or text[start:end] != span_text:
                raise _fail(
                    "``span_text`` absent ou diverge de texte[start:end]",
                    field=f"qis[{i}].span_text",
                    value=span_text,
                    fix=f"``span_text`` doit être exactement texte[{start}:{end}]",
                )
            if mode == "IMPLICIT":
                raise _fail(
                    "``span`` fourni sur un QI implicite",
                    field=f"qis[{i}].span",
                    value=span,
                    fix="un QI IMPLICIT porte span=null et un evidence non vide",
                )
        else:
            if mode != "IMPLICIT":
                raise _fail(
                    f"``span`` absent sur un QI {mode}",
                    field=f"qis[{i}].span",
                    value=None,
                    fix=f"un QI {mode} doit porter un span valide",
                )
            if span_text is not None:
                raise _fail(
                    "``span_text`` doit être null sur un QI implicite",
                    field=f"qis[{i}].span_text",
                    value=span_text,
                    fix="``span_text`` : null (l'absence de citation est ce qui "
                    "rend le QI implicite)",
                )

        evidence = item.get("evidence")
        if mode == "IMPLICIT" and not (
            isinstance(evidence, str) and evidence.strip()
        ):
            raise _fail(
                "``evidence`` vide sur un QI implicite",
                field=f"qis[{i}].evidence",
                value=evidence,
                fix="un QI implicite doit justifier par une citation du texte",
            )

        value = _required(item, "value", i)
        if not isinstance(value, (dict, str)):
            raise _fail(
                "``value`` n'est ni un objet ni une chaîne",
                field=f"qis[{i}].value",
                value=type(value).__name__,
                fix="``value`` : objet de valeur normalisée ou chaîne non vide",
            )
        if isinstance(value, str) and not value.strip():
            raise _fail(
                "``value`` chaîne vide",
                field=f"qis[{i}].value",
                value="",
                fix="``value`` : objet ou chaîne non vide",
            )

        prior = item.get("prior")
        if prior is not None and prior not in PRIOR_LEVELS:
            raise _fail(
                "``prior`` hors des niveaux connus",
                field=f"qis[{i}].prior",
                value=prior,
                fix=f"``prior`` : {', '.join(PRIOR_LEVELS)} | null",
            )

        confidence = item.get("confidence", 1.0)
        if (
            not isinstance(confidence, (int, float))
            or isinstance(confidence, bool)
            or not (0.0 <= confidence <= 1.0)
        ):
            raise _fail(
                "``confidence`` hors [0, 1]",
                field=f"qis[{i}].confidence",
                value=confidence,
                fix="``confidence`` : flottant dans [0, 1]",
            )

        entity_ref = item.get("entity_ref")
        if entity_ref is not None and not isinstance(entity_ref, str):
            raise _fail(
                "``entity_ref`` non string",
                field=f"qis[{i}].entity_ref",
                value=entity_ref,
                fix="``entity_ref`` : chaîne opaque ou null",
            )

        qis.append(
            QiItem(
                category=category,
                expression_mode=mode,
                explicit=explicit,
                span=tuple(span) if span is not None else None,
                span_text=span_text if isinstance(span_text, str) else None,
                value=value,
                prior=prior,
                confidence=confidence,
                entity_ref=entity_ref,
                evidence=evidence if isinstance(evidence, str) else None,
            )
        )

    claims: list[UniquenessClaim] = []
    for j, claim in enumerate(raw_claims):
        if not isinstance(claim, dict):
            raise _fail(
                f"``uniqueness_claims[{j}]`` n'est pas un objet",
                field=f"uniqueness_claims[{j}]",
                value=type(claim).__name__,
                fix="chaque claim : {evidence, confidence}",
            )
        evidence = claim.get("evidence")
        if not (isinstance(evidence, str) and evidence.strip()):
            raise _fail(
                "``evidence`` d'un claim d'unicité vide",
                field=f"uniqueness_claims[{j}].evidence",
                value=evidence,
                fix="un claim cite la portion du texte qui affirme l'unicité",
            )
        confidence = claim.get("confidence", 0.0)
        if (
            not isinstance(confidence, (int, float))
            or isinstance(confidence, bool)
            or not (0.0 <= confidence <= 1.0)
        ):
            raise _fail(
                "``confidence`` d'un claim hors [0, 1]",
                field=f"uniqueness_claims[{j}].confidence",
                value=confidence,
                fix="``confidence`` : flottant dans [0, 1]",
            )
        claims.append(UniquenessClaim(evidence=evidence, confidence=confidence))

    direct: list[str] = []
    for k, code in enumerate(raw_direct):
        if not isinstance(code, str) or code not in OFFERED_DIRECT_CODES:
            raise _fail(
                "code DIRECT inconnu ou hors périmètre v1",
                field=f"direct_ids_missed[{k}]",
                value=code,
                fix=f"choisir parmi {', '.join(OFFERED_DIRECT_CODES)}",
            )
        direct.append(code)

    return QiExtraction(
        qis=tuple(qis),
        uniqueness_claims=tuple(claims),
        direct_ids_missed=tuple(direct),
        prompt_version=PROMPT_VERSION,
        prompt_sha256=prompt_sha256,
    )
