"""Tests de ``schema/io.py`` — lecture/écriture JSONL (SPEC-02 §2, SPEC-04 §6/§9).

Le test le plus important de ce fichier est ``test_write_is_bit_for_bit_deterministic`` :
c'est le test explicitement exigé par SPEC-04 §11 (« une réingestion complète
produit des fichiers identiques bit à bit »).
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from anonymisation.schema.io import JsonlError, read_jsonl, sha256_bytes, sha256_file, write_jsonl
from anonymisation.schema.models import Document, Domain

TEXT = "J'ai moins de 30 ans et je suis doctorant."


def _doc(doc_id: str = "fx:d1", **overrides: object) -> Document:
    base: dict[str, object] = {
        "doc_id": doc_id,
        "dataset": "fx",
        "split": "test",
        "domain": Domain.HR,
        "language": "fr",
        "text": TEXT,
        "author_id": None,
    }
    base.update(overrides)
    return Document(**base)  # type: ignore[arg-type]


class TestReadJsonl:
    def test_reads_valid_lines(self, tmp_path: Path) -> None:
        path = tmp_path / "documents.jsonl"
        write_jsonl(path, [_doc("fx:d1"), _doc("fx:d2")])

        docs = list(read_jsonl(path, Document))

        assert [d.doc_id for d in docs] == ["fx:d1", "fx:d2"]
        assert all(isinstance(d, Document) for d in docs)

    def test_is_lazy_generator(self, tmp_path: Path) -> None:
        path = tmp_path / "documents.jsonl"
        write_jsonl(path, [_doc("fx:d1")])

        gen = read_jsonl(path, Document)
        # Rien n'est consommé tant qu'on n'itère pas explicitement.
        assert hasattr(gen, "__next__")
        first = next(gen)
        assert first.doc_id == "fx:d1"

    def test_ignores_trailing_blank_line(self, tmp_path: Path) -> None:
        path = tmp_path / "documents.jsonl"
        payload = _doc("fx:d1").model_dump_json()
        path.write_text(payload + "\n\n", encoding="utf-8")

        docs = list(read_jsonl(path, Document))
        assert len(docs) == 1

    def test_invalid_json_raises_with_line_number_and_path(self, tmp_path: Path) -> None:
        path = tmp_path / "documents.jsonl"
        path.write_text('{"doc_id": "fx:d1"\n{not json at all\n', encoding="utf-8")

        with pytest.raises(JsonlError) as excinfo:
            list(read_jsonl(path, Document))

        message = str(excinfo.value)
        assert str(path) in message
        assert ":1" in message or ":2" in message

    def test_second_line_error_reports_line_2(self, tmp_path: Path) -> None:
        path = tmp_path / "documents.jsonl"
        good = _doc("fx:d1").model_dump_json()
        path.write_text(good + "\n" + "not json\n", encoding="utf-8")

        with pytest.raises(JsonlError, match=r":2 :"):
            list(read_jsonl(path, Document))

    def test_schema_violation_raises_jsonl_error(self, tmp_path: Path) -> None:
        """Une ligne JSON valide mais qui ne valide pas le modèle échoue aussi."""
        path = tmp_path / "documents.jsonl"
        bad = {"doc_id": "fx:d1", "dataset": "fx"}  # champs obligatoires manquants
        path.write_text(json.dumps(bad) + "\n", encoding="utf-8")

        with pytest.raises(JsonlError):
            list(read_jsonl(path, Document))

    def test_missing_file_raises(self, tmp_path: Path) -> None:
        with pytest.raises(FileNotFoundError):
            list(read_jsonl(tmp_path / "absent.jsonl", Document))


class TestWriteJsonl:
    def test_returns_record_count(self, tmp_path: Path) -> None:
        path = tmp_path / "documents.jsonl"
        n = write_jsonl(path, [_doc("fx:d1"), _doc("fx:d2"), _doc("fx:d3")])
        assert n == 3

    def test_writes_atomically_no_tmp_left_behind(self, tmp_path: Path) -> None:
        path = tmp_path / "documents.jsonl"
        write_jsonl(path, [_doc("fx:d1")])

        assert path.exists()
        assert not path.with_name(path.name + ".tmp").exists()

    def test_utf8_no_bom_lf_separator(self, tmp_path: Path) -> None:
        path = tmp_path / "documents.jsonl"
        write_jsonl(path, [_doc("fx:d1", text="café à Nantes")])

        raw = path.read_bytes()
        assert not raw.startswith(b"\xef\xbb\xbf")  # pas de BOM
        assert b"\r\n" not in raw
        assert raw.endswith(b"\n")
        # ensure_ascii=False : les caractères accentués restent en UTF-8, pas
        # échappés en \uXXXX.
        assert "café à Nantes".encode() in raw

    def test_sort_keys_for_reproducibility(self, tmp_path: Path) -> None:
        path = tmp_path / "documents.jsonl"
        write_jsonl(path, [_doc("fx:d1")])
        line = path.read_text(encoding="utf-8").splitlines()[0]
        obj = json.loads(line)
        keys = list(obj.keys())
        assert keys == sorted(keys)

    def test_write_is_bit_for_bit_deterministic(self, tmp_path: Path) -> None:
        """Exigence SPEC-04 §9 / §11 : deux écritures produisent des fichiers
        identiques bit à bit."""
        records = [_doc("fx:d1"), _doc("fx:d2", author_id="fx:P1"), _doc("fx:d3")]

        path_a = tmp_path / "run_a.jsonl"
        path_b = tmp_path / "run_b.jsonl"
        write_jsonl(path_a, records)
        write_jsonl(path_b, records)

        assert path_a.read_bytes() == path_b.read_bytes()
        assert sha256_file(path_a) == sha256_file(path_b)

    def test_rewrite_same_path_is_stable(self, tmp_path: Path) -> None:
        path = tmp_path / "documents.jsonl"
        records = [_doc("fx:d1"), _doc("fx:d2")]
        write_jsonl(path, records)
        first_hash = sha256_file(path)
        write_jsonl(path, records)
        second_hash = sha256_file(path)
        assert first_hash == second_hash

    def test_creates_parent_directories(self, tmp_path: Path) -> None:
        path = tmp_path / "nested" / "dir" / "documents.jsonl"
        write_jsonl(path, [_doc("fx:d1")])
        assert path.exists()

    def test_failure_mid_write_leaves_no_tmp_and_no_partial_target(
        self, tmp_path: Path
    ) -> None:
        path = tmp_path / "documents.jsonl"

        def _boom():
            yield _doc("fx:d1")
            raise RuntimeError("boom")

        with pytest.raises(RuntimeError):
            write_jsonl(path, _boom())

        assert not path.exists()
        assert not path.with_name(path.name + ".tmp").exists()

    def test_roundtrip_read_after_write(self, tmp_path: Path) -> None:
        path = tmp_path / "documents.jsonl"
        original = [_doc("fx:d1"), _doc("fx:d2", author_id="fx:P1")]
        write_jsonl(path, original)

        reloaded = list(read_jsonl(path, Document))
        assert reloaded == original


class TestHashing:
    def test_sha256_bytes_known_vector(self) -> None:
        # sha256("") — vecteur connu
        assert (
            sha256_bytes(b"")
            == "e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855"
        )

    def test_sha256_file_matches_bytes(self, tmp_path: Path) -> None:
        path = tmp_path / "data.bin"
        content = b"contenu de test avec accents \xc3\xa9"
        path.write_bytes(content)
        assert sha256_file(path) == sha256_bytes(content)

    def test_sha256_differs_on_change(self, tmp_path: Path) -> None:
        path = tmp_path / "documents.jsonl"
        write_jsonl(path, [_doc("fx:d1")])
        h1 = sha256_file(path)
        write_jsonl(path, [_doc("fx:d1"), _doc("fx:d2")])
        h2 = sha256_file(path)
        assert h1 != h2
