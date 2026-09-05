"""Garde hors réseau du profil déterministe (SPEC-10 §10, SPEC-08 E2)."""

from __future__ import annotations

import socket
from pathlib import Path

import pytest

from anonymisation.cli import predict
from anonymisation.cli.main import main
from anonymisation.pipeline.guards import LocalOnlyViolationError, assert_local_only
from anonymisation.pipeline.profiles import load_runtime_profile
from integration._micro import write_micro_pivot


def _remote_profile():
    profile = load_runtime_profile("deterministic").profile
    llm = profile.llm.model_copy(update={"allow_remote": True})
    return profile.model_copy(update={"llm": llm})


def _manifest(key: str, synthetic: bool) -> dict:
    return {"key": key, "structure": {"synthetic": synthetic}}


def test_deterministic_predict_succeeds_with_sockets_disabled(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Le chemin complet de predict ne doit ouvrir aucun socket."""
    processed = write_micro_pivot(tmp_path / "processed")
    monkeypatch.setattr(predict, "PROCESSED_ROOT", processed)

    def denied_socket(*args, **kwargs):
        raise AssertionError("le profil deterministic a tenté un accès réseau")

    monkeypatch.setattr(socket, "socket", denied_socket)
    assert main(
        [
            "predict",
            "--dataset",
            "micro",
            "--split",
            "train",
            "--policy",
            "P2",
            "--profile",
            "deterministic",
            "--out",
            str(tmp_path / "run"),
        ]
    ) in (0, 1)


@pytest.mark.parametrize("key", ["tab", "dbbio", "SupportTicketsReal", "CleanCoNLL"])
def test_remote_profile_is_rejected_for_real_corpus(key: str) -> None:
    """Les quatre corpus réels de la garde E2 sont refusés explicitement."""
    with pytest.raises(LocalOnlyViolationError, match=key):
        assert_local_only(_remote_profile(), _manifest(key, synthetic=False))


@pytest.mark.parametrize("key", ["personalreddit", "ratbench"])
def test_remote_profile_is_allowed_for_synthetic_corpus(key: str) -> None:
    """Un corpus déclaré synthétique peut utiliser un profil distant explicite."""
    assert_local_only(_remote_profile(), _manifest(key, synthetic=True))


def test_missing_synthetic_declaration_fails_closed() -> None:
    """L'absence du champ ne peut pas autoriser un envoi distant."""
    with pytest.raises(LocalOnlyViolationError, match="structure.synthetic"):
        assert_local_only(_remote_profile(), {"key": "unknown"})
