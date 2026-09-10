"""Tests de ``anonymisation.pipelines.llm_full.prompts`` — construction et parsing, sans réseau."""

from __future__ import annotations

import json

import pytest

from anonymisation.pipelines.llm_full.prompts import (
    LlmMalformedResponseError,
    build_anonymization_prompt,
    parse_llm_entities,
)
from anonymisation.schema.taxonomy import DIRECT_CODES, OUT_OF_SCOPE_V1


def test_prompt_contains_the_text_and_direct_codes():
    prompt = build_anonymization_prompt("Jean Dupont a 28 ans.")
    assert "Jean Dupont a 28 ans." in prompt
    for code in DIRECT_CODES:
        assert code in prompt


def test_prompt_excludes_out_of_scope_codes():
    prompt = build_anonymization_prompt("texte")
    for code in OUT_OF_SCOPE_V1:
        assert code not in prompt


def test_parse_happy_path():
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
    entities = parse_llm_entities(json.dumps(payload))
    assert len(entities) == 2
    assert entities[0].span == "Jean Dupont"
    assert entities[0].category == "DIR_NAME"
    assert entities[1].action == "GENERALIZE"
    assert entities[1].replacement == "25-30 ans"


def test_parse_strips_markdown_code_fence():
    payload = '```json\n{"entities": []}\n```'
    assert parse_llm_entities(payload) == ()


def test_parse_empty_entities_list_is_valid():
    assert parse_llm_entities('{"entities": []}') == ()


def test_parse_defaults_missing_action_to_suppress():
    payload = json.dumps({"entities": [{"span": "x", "category": "DIR_NAME"}]})
    entities = parse_llm_entities(payload)
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
