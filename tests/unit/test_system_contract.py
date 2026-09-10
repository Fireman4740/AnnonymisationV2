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

def _micro() -> tuple[list[Document], dict[str, tuple[Annotation, ...]]]:
    documents = [
        d for d in read_jsonl(_MICRO / "documents.jsonl", Document) if d.split == "train"
    ]
    gold: dict[str, list[Annotation]] = {}
    for annotation in read_jsonl(_MICRO / "annotations.jsonl", Annotation):
        gold.setdefault(annotation.doc_id, []).append(annotation)
    return documents, {k: tuple(v) for k, v in gold.items()}


def _build(system_id: str):
    """Construit un système depuis SA PROPRE configuration de contrat.

    Chaque pipeline déclare ``contract_config()`` chez lui : ajouter une
    architecture ne demande aucune édition de ce fichier partagé. Un système
    dont la configuration déclarée ne suffit pas à le construire échoue ici,
    ce qui est voulu — un système inconstructible n'est pas évaluable.
    """
    cls = resolve_system(system_id)
    return cls(cls.contract_config())


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


def test_every_registered_system_is_constructible_from_its_own_contract() -> None:
    """Aucun système ne peut échapper au contrat : il déclare comment le bâtir."""
    for system_id, cls in sorted(SYSTEM_REGISTRY.items()):
        config = cls.contract_config()
        assert isinstance(config, SystemConfig), (
            f"{system_id} : contract_config() doit renvoyer un SystemConfig."
        )
        cls(config)  # doit se construire sans réseau ni paramètre externe
