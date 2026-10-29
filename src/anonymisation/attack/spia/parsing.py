"""Cale de parsing devant ``parse_subject_profiling`` du code SPIA original.

``clean_json_response`` (original) applique ses réparations AVANT d'essayer
le JSON tel quel : ``replace('\\"', '"')`` et ``replace('\\\\', '')`` cassent
un JSON pourtant valide dès qu'une description contient des guillemets
échappés (``\\"I\\"``, ``\\"Seller\\"``). Observé sur le banc 200 :
9 à 13,5 % des documents PANORAMA rejetés en ``SPC/SPNC_PARSING_ERROR``.

La cale ne fait qu'exécuter d'abord l'étape « Try parsing as-is (already
valid JSON) » déclarée par l'original, avec la même extraction de crochets et
la même normalisation (id entier, description, PIIs en liste). Tout ce qui
n'est pas du JSON valide repart vers le parseur original inchangé (réparations
et retry LLM compris).
"""

from __future__ import annotations

import json
from collections.abc import Callable
from typing import Any

Parser = Callable[..., tuple[str, Any]]


def _bracketed(response: str) -> str:
    """Même extraction que l'original : premier ``[``/``{`` au dernier fermant."""
    b1, b2 = response.find("["), response.find("{")
    if b1 != -1 and b2 != -1:
        return response[b1:response.rfind("]") + 1] if b1 < b2 else response[b2:response.rfind("}") + 1]
    return response


def _subject_id(value: Any) -> int:
    if isinstance(value, str):
        return int(value) if value.isdigit() else 0
    return value if isinstance(value, int) and not isinstance(value, bool) else 0


def _normalize(subject: dict[str, Any]) -> dict[str, Any]:
    piis = subject.get("PIIs", [])
    return {"id": _subject_id(subject.get("id", 0)),
            "description": subject.get("description", ""),
            "PIIs": piis if isinstance(piis, list) else []}


def strict_first(original: Parser) -> Parser:
    """Enveloppe ``parse_subject_profiling`` : JSON valide d'abord, original sinon."""

    def parse(response: str, retry_with_llm: bool = True) -> tuple[str, Any]:
        try:
            parsed = json.loads(_bracketed(response))
        except (json.JSONDecodeError, ValueError):
            return original(response, retry_with_llm=retry_with_llm)
        if isinstance(parsed, dict):
            return "success", [_normalize(parsed)]
        if isinstance(parsed, list) and all(isinstance(s, dict) for s in parsed):
            return "success", [_normalize(s) for s in parsed]
        return original(response, retry_with_llm=retry_with_llm)

    return parse


__all__ = ["strict_first"]
