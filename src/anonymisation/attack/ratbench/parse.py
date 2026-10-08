"""Lecture de la réponse de l'attaquant.

Le code officiel (``parse_output_gpt``) lit la réponse ligne à ligne et, en cas
d'échec, **imprime l'erreur et renvoie un dictionnaire partiel** : une réponse
illisible devient silencieusement « aucune devinette », donc une protection
apparente. Ici :

1. on tente d'abord un vrai JSON (balises ```json retirées, virgules
   pendantes tolérées) — c'est le format que le prompt exige ;
2. sinon le lecteur ligne à ligne officiel ;
3. si rien n'est lu, :class:`AttackParseError` — compté en erreur (C3/C4),
   jamais en « rien deviné ».
"""

from __future__ import annotations

import json
import re
from typing import Any

from anonymisation.attack.ratbench.maps import LABEL_TO_COLUMN

_FENCE = re.compile(r"```(?:json)?\s*(.*?)```", re.DOTALL)


class AttackParseError(ValueError):
    """Réponse de l'attaquant illisible."""


def _column(label: str) -> str:
    cleaned = label.strip(' ",\'')
    return LABEL_TO_COLUMN.get(cleaned, "DOB" if cleaned == "DOB" else cleaned)


def _normalise(payload: dict[str, Any]) -> dict[str, dict[str, Any]]:
    out: dict[str, dict[str, Any]] = {}
    for label, value in payload.items():
        if not isinstance(value, dict):
            continue
        entry = {str(k).strip().capitalize(): v for k, v in value.items()}
        out[_column(str(label))] = entry
    return out


def _try_json(text: str) -> dict[str, Any] | None:
    candidates = [m.group(1) for m in _FENCE.finditer(text)] or [text]
    for candidate in candidates:
        start, end = candidate.find("{"), candidate.rfind("}")
        if start == -1 or end <= start:
            continue
        body = re.sub(r",\s*([}\]])", r"\1", candidate[start : end + 1])
        try:
            parsed = json.loads(body)
        except json.JSONDecodeError:
            continue
        if isinstance(parsed, dict):
            return parsed
    return None


def _line_parser(text: str) -> dict[str, dict[str, Any]]:
    """``parse_output_gpt`` officiel : clé connue puis 3 lignes Inference/Guess/Certainty."""
    lines = text.splitlines()
    known = set(LABEL_TO_COLUMN) | {"DOB"}
    out: dict[str, dict[str, Any]] = {}
    i = 0
    while i < len(lines):
        key = lines[i].split(":")[0].strip(' ",\'')
        if key not in known:
            i += 1
            continue
        entry: dict[str, Any] = {}
        for j in range(i + 1, min(i + 4, len(lines))):
            field, _, value = lines[j].partition(":")
            name = field.strip(' ",\'').lower()
            if name in ("inference", "guess", "certainty"):
                entry[name.capitalize()] = value.strip(' ",\'')
        out[_column(key)] = entry
        i += 4
    return out


def parse_guesses(response: str) -> dict[str, dict[str, Any]]:
    parsed = _try_json(response)
    guesses = _normalise(parsed) if parsed is not None else _line_parser(response)
    if not guesses:
        raise AttackParseError(
            "réponse de l'attaquant sans aucune devinette lisible (ni JSON ni format "
            f"ligne à ligne) — début : {response[:160]!r}"
        )
    return guesses


__all__ = ["AttackParseError", "parse_guesses"]
