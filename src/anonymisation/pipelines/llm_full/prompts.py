"""Prompt et parseur de la tâche « anonymisation complète par LLM ».

Le système ``llm-full-v1`` (``anonymisation.systems.llm_full``) délègue au LLM
la détection ET la décision d'action en un seul appel : ce module construit ce
prompt et parse la réponse JSON attendue. La localisation des offsets sur le
texte original, elle, reste du code déterministe (``llm_full._locate``) — on
ne fait jamais confiance à un LLM pour compter des caractères.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from typing import Any, Final

from anonymisation.schema.taxonomy import DIRECT_CODES, OUT_OF_SCOPE_V1, QUASI_CODES

#: Catégories offertes au LLM : DIRECT + QUASI, moins celles hors périmètre
#: v1 du moteur de risque (SPEC-01 §4.5/§10). OTHER_QI et IGNORED ne sont
#: jamais proposés : un LLM invité à choisir « autre » le fait trop souvent,
#: ce qui viderait la taxonomie de son sens (SPEC-01 §4.6).
_OFFERED_CODES: Final[tuple[str, ...]] = tuple(
    sorted((DIRECT_CODES | QUASI_CODES) - OUT_OF_SCOPE_V1)
)

_DIRECT_LIST = ", ".join(sorted(DIRECT_CODES))
_QUASI_LIST = ", ".join(sorted(QUASI_CODES - OUT_OF_SCOPE_V1))

_CODE_FENCE_RE = re.compile(r"^```(?:json)?\s*|\s*```$", re.MULTILINE)

_PROMPT_TEMPLATE: Final[str] = """Tu es un système d'anonymisation de texte. Analyse le TEXTE ci-dessous \
et identifie CHAQUE identifiant direct et quasi-identifiant (QI) qu'il contient — y compris ceux qui ne \
sont pas des noms ou des coordonnées (âge, métier, lieu, diplôme, état de santé, ancienneté, produit, \
version logicielle, horaire d'incident, etc.).

Un identifiant DIRECT identifie la personne à lui seul. Codes autorisés :
{direct_list}

Un QUASI-identifiant n'identifie qu'en combinaison avec d'autres informations. Codes autorisés :
{quasi_list}

Pour chaque entité trouvée, choisis une action :
- pour un identifiant DIRECT : SUPPRESS (supprimer) ou PSEUDONYMIZE (remplacer par un substitut qui ne \
révèle RIEN de l'original — pas de fragment du nom réel, pas de vraie ville, pas de vrai domaine d'email) ;
- pour un QUASI-identifiant : GENERALIZE (remplacer par une version moins précise, ex. « 28 ans » -> \
« 25-30 ans », « Lille » -> « Nord de la France ») ou SUPPRESS.

Règles strictes :
1. "span" est la sous-chaîne EXACTE copiée depuis le TEXTE (mêmes caractères, accents, casse, ponctuation). \
Ne reformule jamais le span.
2. Si la même information identifiante est répétée plusieurs fois dans le TEXTE, liste UNE entité par \
occurrence.
3. "category" est un des codes ci-dessus, jamais un autre mot.
4. "replacement" est le texte de remplacement à insérer à la place du span (obligatoire si action != \
SUPPRESS, sinon laisse une chaîne vide).
5. N'invente aucune information qui ne serait pas dans le TEXTE.

Réponds STRICTEMENT avec un objet JSON de la forme {{"entities": [{{"span": "...", "category": "...", \
"action": "...", "replacement": "..."}}]}}. Aucun texte avant ou après. Aucun bloc de code markdown. Si le \
TEXTE ne contient aucune entité, réponds {{"entities": []}}.

TEXTE:
{text}
"""


def build_anonymization_prompt(text: str) -> str:
    """Construit le prompt d'anonymisation complète pour un document."""
    return _PROMPT_TEMPLATE.format(direct_list=_DIRECT_LIST, quasi_list=_QUASI_LIST, text=text)


@dataclass(frozen=True)
class ParsedEntity:
    span: str
    category: str
    action: str
    replacement: str


class LlmMalformedResponseError(ValueError):
    """La réponse du LLM ne respecte pas le contrat JSON attendu.

    Distincte de :class:`anonymisation.llm.client.LlmEmptyResponseError` :
    ici le LLM a répondu, mais avec un contenu inexploitable (JSON invalide,
    champ manquant). Traitée comme une erreur du document par le système
    appelant (SPEC-10 C3/C4 : jamais interprétée comme « aucune entité »).
    """


def _strip_code_fence(text: str) -> str:
    return _CODE_FENCE_RE.sub("", text.strip()).strip()


def parse_llm_entities(content: str) -> tuple[ParsedEntity, ...]:
    """Parse la réponse JSON du LLM en entités structurées.

    Tolère un encadrement par un bloc de code markdown (fréquent malgré
    l'instruction contraire), mais échoue bruyamment sur tout le reste : un
    JSON invalide ou un champ requis absent lève
    :class:`LlmMalformedResponseError`.
    """
    stripped = _strip_code_fence(content)
    if not stripped:
        raise LlmMalformedResponseError("réponse vide après nettoyage.")
    try:
        payload: Any = json.loads(stripped)
    except json.JSONDecodeError as exc:
        raise LlmMalformedResponseError(f"JSON invalide : {exc}") from exc

    if not isinstance(payload, dict) or "entities" not in payload:
        raise LlmMalformedResponseError("clé 'entities' absente de la réponse JSON.")
    raw_entities = payload["entities"]
    if not isinstance(raw_entities, list):
        raise LlmMalformedResponseError("'entities' doit être une liste.")

    entities: list[ParsedEntity] = []
    for index, item in enumerate(raw_entities):
        if not isinstance(item, dict):
            raise LlmMalformedResponseError(f"entities[{index}] n'est pas un objet JSON.")
        span = item.get("span")
        category = item.get("category")
        if not isinstance(span, str) or not span:
            raise LlmMalformedResponseError(f"entities[{index}].span manquant ou vide.")
        if not isinstance(category, str) or not category:
            raise LlmMalformedResponseError(f"entities[{index}].category manquant ou vide.")
        action = item.get("action")
        action = action if isinstance(action, str) and action else "SUPPRESS"
        replacement = item.get("replacement")
        replacement = replacement if isinstance(replacement, str) else ""
        entities.append(
            ParsedEntity(span=span, category=category, action=action, replacement=replacement)
        )
    return tuple(entities)


__all__ = [
    "LlmMalformedResponseError",
    "ParsedEntity",
    "build_anonymization_prompt",
    "parse_llm_entities",
]
