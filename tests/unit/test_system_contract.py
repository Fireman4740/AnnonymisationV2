"""Conformité au contrat de système — paramétré sur TOUT le registre.

C'est le test qui porte l'architecture multi-pipelines : enregistrer un
système le soumet automatiquement à ces assertions, sans qu'aucun test n'ait
à le mentionner. Un système qui ne les passe pas n'est pas évaluable.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from anonymisation.capabilities import (
    CAP_DECISIONS,
    CAP_RISK,
    CAP_SPANS,
    CAP_TRACES,
    CAPABILITIES,
)
from anonymisation.pipeline.traces import serialize_pipeline_result
from anonymisation.schema.io import read_jsonl
from anonymisation.schema.models import Annotation, Document
from anonymisation.systems import (
    SYSTEM_REGISTRY,
    SystemConfig,
    list_systems,
    resolve_system,
)

REPO_ROOT = Path(__file__).resolve().parents[2]
_MICRO = REPO_ROOT / "tests" / "fixtures" / "micro"

#: Paramètres minimaux pour construire chaque système. Un système dont la
#: construction exige des paramètres doit figurer ici — sinon le test de
#: conformité échoue, ce qui est le comportement voulu : un système
#: inconstructible n'est pas évaluable.
_CONFIGS: dict[str, SystemConfig] = {
    "passthrough-v1": SystemConfig(),
    "redact-all-v1": SystemConfig(params={"replacement": ""}),
    "deterministic-v1": SystemConfig(policy_id="P2"),
}


def _micro() -> tuple[list[Document], dict[str, tuple[Annotation, ...]]]:
    documents = [
        d for d in read_jsonl(_MICRO / "documents.jsonl", Document) if d.split == "train"
    ]
    gold: dict[str, list[Annotation]] = {}
    for annotation in read_jsonl(_MICRO / "annotations.jsonl", Annotation):
        gold.setdefault(annotation.doc_id, []).append(annotation)
    return documents, {k: tuple(v) for k, v in gold.items()}


def _build(system_id: str):
    config = _CONFIGS.get(system_id)
    assert config is not None, (
        f"Système {system_id!r} enregistré mais absent de _CONFIGS : ajoutez-y "
        f"ses paramètres de construction pour qu'il soit soumis au contrat."
    )
    return resolve_system(system_id)(config)


@pytest.mark.parametrize("system_id", list_systems())
def test_system_runs_and_stamps_its_identity(system_id: str) -> None:
    """``run`` ne lève jamais et estampille toujours l'identité déclarée."""
    documents, gold = _micro()
    system = _build(system_id)

    for document in documents:
        result = system.run(document, gold.get(document.doc_id, ()))
        assert result.status in ("ok", "partial", "error"), result.status
        assert result.identity is not None, "résultat non estampillé"
        assert result.identity.system_id == system_id
        assert isinstance(result.identity.capabilities, frozenset)
        assert result.identity.capabilities <= CAPABILITIES


@pytest.mark.parametrize("system_id", list_systems())
def test_system_declares_everything_it_produces(system_id: str) -> None:
    """Produire une sortie sans déclarer la capacité correspondante est refusé.

    Sans cette garantie, un système émettrait des annotations sans déclarer
    ``spans`` : le scorer les ignorerait et publierait un ``UNAVAILABLE``
    mensonger.
    """
    documents, gold = _micro()
    system = _build(system_id)
    capabilities = system.capabilities

    for document in documents:
        result = system.run(document, gold.get(document.doc_id, ()))
        if result.annotations:
            assert CAP_SPANS in capabilities
        if result.decisions:
            assert CAP_DECISIONS in capabilities
        if result.traces:
            assert CAP_TRACES in capabilities
            assert len(result.traces) == 8, "les 8 étapes, jamais un compte partiel"
        if result.risk is not None:
            assert CAP_RISK in capabilities


@pytest.mark.parametrize("system_id", list_systems())
def test_span_offsets_refer_to_the_original_text(system_id: str) -> None:
    """Invariant transverse de SPEC-10 §4, vérifié pour tout producteur de spans."""
    documents, gold = _micro()
    system = _build(system_id)
    if CAP_SPANS not in system.capabilities:
        pytest.skip(f"{system_id} ne produit pas de spans")

    for document in documents:
        result = system.run(document, gold.get(document.doc_id, ()))
        for annotation in result.annotations:
            if annotation.start is None or annotation.span_text is None:
                continue
            assert document.text[annotation.start : annotation.end] == annotation.span_text


@pytest.mark.parametrize("system_id", list_systems())
def test_system_output_is_serializable_and_deterministic(system_id: str) -> None:
    """Deux exécutions produisent une sérialisation stricte identique."""
    documents, gold = _micro()
    system = _build(system_id)

    def render() -> list[str]:
        return [
            json.dumps(
                serialize_pipeline_result(
                    system.run(d, gold.get(d.doc_id, ())), strict=True
                ),
                ensure_ascii=False,
                sort_keys=True,
            )
            for d in documents
        ]

    assert render() == render()


@pytest.mark.parametrize("system_id", list_systems())
def test_system_describes_itself(system_id: str) -> None:
    descriptor = _build(system_id).describe()
    assert descriptor.summary.strip(), "un système doit se résumer en une phrase"
    payload = descriptor.to_dict()
    # Les capacités sont triées : un frozenset n'a pas d'ordre stable et
    # casserait la reproductibilité bit-à-bit du lock.
    assert payload["capabilities"] == sorted(payload["capabilities"])
    assert json.dumps(payload, sort_keys=True)


def test_every_registered_system_is_covered_by_the_contract() -> None:
    """Aucun système ne peut échapper au contrat en oubliant sa configuration."""
    assert set(SYSTEM_REGISTRY) <= set(_CONFIGS), (
        f"Systèmes enregistrés sans configuration de test : "
        f"{sorted(set(SYSTEM_REGISTRY) - set(_CONFIGS))}"
    )
