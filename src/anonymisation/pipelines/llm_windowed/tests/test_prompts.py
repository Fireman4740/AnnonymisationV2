"""Tests du prompt et du parseur ``llm_windowed`` — aucun réseau."""

from __future__ import annotations

import json

import pytest

from anonymisation.pipelines.llm_windowed.prompts import (
    LlmMalformedResponseError,
    build_window_prompt,
    parse_llm_entities,
)
from anonymisation.schema.taxonomy import DIRECT_CODES, OUT_OF_SCOPE_V1


def test_prompt_contains_text_index_total_and_direct_codes():
    prompt = build_window_prompt("Jean Dupont a 28 ans.", index=2, total=5)
    assert "Jean Dupont a 28 ans." in prompt
    assert "EXTRAIT 2/5" in prompt
    for code in DIRECT_CODES:
        assert code in prompt


def test_prompt_excludes_out_of_scope_codes():
    prompt = build_window_prompt("texte", index=1, total=1)
    for code in OUT_OF_SCOPE_V1:
        assert code not in prompt


@pytest.mark.parametrize("index,total", [(0, 1), (2, 1), (1, 0), (-1, 2)])
def test_prompt_rejects_invalid_window_bounds(index: int, total: int):
    with pytest.raises(ValueError):
        build_window_prompt("texte", index=index, total=total)


def test_parse_happy_path_and_code_fence():
    payload = {
        "entities": [
            {"span": "Jean Dupont", "category": "DIR_NAME", "action": "SUPPRESS", "replacement": ""},
            {
                "span": "28 ans",
                "category": "GEN_AGE",
                "action": "GENERALIZE",
                "replacement": "25-30 ans",
            },
        ]
    }
    entities = parse_llm_entities("```json\n" + json.dumps(payload) + "\n```")
    assert [entity.span for entity in entities] == ["Jean Dupont", "28 ans"]
    assert entities[1].action == "GENERALIZE"


def test_parse_defaults_missing_action_to_suppress():
    entities = parse_llm_entities('{"entities": [{"span": "x", "category": "DIR_NAME"}]}')
    assert entities[0].action == "SUPPRESS"
    assert entities[0].replacement == ""


@pytest.mark.parametrize(
    "content",
    [
        "",
        "not json at all",
        "{}",
        '{"entities": "not-a-list"}',
        '{"entities": [123]}',
        '{"entities": [{"category": "DIR_NAME"}]}',
        '{"entities": [{"span": "x"}]}',
        '{"entities": [{"span": "", "category": "DIR_NAME"}]}',
    ],
)
def test_parse_malformed_responses_raise(content: str):
    with pytest.raises(LlmMalformedResponseError):
        parse_llm_entities(content)
