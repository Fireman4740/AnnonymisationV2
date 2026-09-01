"""Tests de l'adaptateur OpenPII 500k (EPIC B) — SPEC-09 §4.3 : aucun corpus réel, aucun réseau.

Le brut est factice : fichiers JSONL dans ``tmp_path`` au schéma exact de la
release HuggingFace (``source_text``, ``masked_text``, ``privacy_mask``,
``split``, ``uid``, ``language``, ``region``, ``script``, ``mbert_*``). Le
manifeste est le YAML réel du dépôt, adapté au corpus factice (sha256 agrégat
+ volumétrie) : la validation complète du modèle (20 labels, codes taxonomie,
contrôles) s'exécute donc sur le mapping réel.
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any

import pytest
import yaml

from anonymisation.datasets import openpii as openpii_module
from anonymisation.datasets.ingest import IngestionError, ingest
from anonymisation.datasets.manifest import DatasetManifest, load_manifest
from anonymisation.datasets.openpii import OpenpiiAdapter
from anonymisation.datasets.registry import UnmappedLabelError, resolve
from anonymisation.schema.models import Domain, ExpressionMode

REPO_ROOT = Path(__file__).resolve().parents[2]
OPENPII_YAML = REPO_ROOT / "configs" / "datasets" / "openpii.yaml"

#: Les 20 classes du labelset OpenPII (comparé au manifeste, G4 totalité).
ALL_20_LABELS = [
    "AGE",
    "BUILDINGNUM",
    "CITY",
    "CREDITCARDNUMBER",
    "DATE",
    "DRIVERLICENSENUM",
    "EMAIL",
    "GENDER",
    "GIVENNAME",
    "IDCARDNUM",
    "PASSPORTNUM",
    "SEX",
    "SOCIALNUM",
    "STREET",
    "SURNAME",
    "TAXNUM",
    "TELEPHONENUM",
    "TIME",
    "TITLE",
    "ZIPCODE",
]


# --------------------------------------------------------------------------- #
# Corpus factice au schéma réel
# --------------------------------------------------------------------------- #


def _mask_text(text: str, mask: list[tuple[str, int, int, str]]) -> str:
    """Construit ``masked_text`` comme la release : chaque span → ``[LABEL_i]``."""
    out: list[str] = []
    last = 0
    for i, (label, start, end, _value) in enumerate(mask, start=1):
        out.append(text[last:start])
        out.append(f"[{label}_{i}]")
        last = end
    out.append(text[last:])
    return "".join(out)


def _row(
    uid: int,
    text: str,
    mask: list[tuple[str, int, int, str]],
    *,
    split: str = "train",
    language: str = "fr",
    region: str | None = "FR",
    script: str | None = "Qxxx",
) -> dict[str, Any]:
    """Une ligne du JSONL openpii au schéma exact de la release."""
    return {
        "source_text": text,
        "masked_text": _mask_text(text, mask),
        "privacy_mask": [
            {"label": label, "start": start, "end": end, "value": value, "label_index": i}
            for i, (label, start, end, value) in enumerate(mask, start=1)
        ],
        "split": split,
        "uid": uid,
        "language": language,
        "region": region,
        "script": script,
        "mbert_tokens": ["x"],
        "mbert_token_classes": ["O"],
    }


def _write_raw(tmp_path: Path, lines_by_split: dict[str, list[str]]) -> Path:
    raw = tmp_path / "openpii"
    raw.mkdir(parents=True, exist_ok=True)
    for split, lines in lines_by_split.items():
        (raw / f"{split}.jsonl").write_text(
            "".join(line + "\n" for line in lines), encoding="utf-8"
        )
    return raw


def _manifest_for(raw: Path, expected_documents: int) -> DatasetManifest:
    """Le manifeste réel du dépôt, adapté au corpus factice (sha256 + volumétrie)."""
    h = hashlib.sha256()
    for name in ("train.jsonl", "validation.jsonl"):
        h.update((raw / name).read_bytes())
    data = yaml.safe_load(OPENPII_YAML.read_text(encoding="utf-8"))
    data["integrity"]["sha256"] = h.hexdigest()
    data["integrity"]["expected_documents"] = expected_documents
    return DatasetManifest(**data)


def _adapter(
    tmp_path: Path, rows_by_split: dict[str, list[dict[str, Any]]]
) -> tuple[OpenpiiAdapter, Path]:
    """Corpus factice → manifeste adapté → adaptateur prêt à itérer."""
    lines = {
        split: [json.dumps(r, ensure_ascii=False) for r in rows]
        for split, rows in rows_by_split.items()
    }
    raw = _write_raw(tmp_path, lines)
    manifest = _manifest_for(raw, sum(len(rows) for rows in rows_by_split.values()))
    return OpenpiiAdapter(manifest, raw), raw


# --------------------------------------------------------------------------- #
# Manifeste du dépôt (chargement réel du YAML)
# --------------------------------------------------------------------------- #


def test_repo_manifest_loads_with_full_declaration() -> None:
    """Le YAML complété se charge ; toutes les valeurs de la fiche y sont figées."""
    loaded = load_manifest(OPENPII_YAML)
    m = loaded.manifest
    assert m.key == "openpii"
    assert m.aliases == ["ai4privacy", "open-pii-500k"]
    assert m.source.kind == "huggingface"
    assert m.source.repo == "ai4privacy/open-pii-masking-500k-ai4privacy"
    assert m.source.revision == "506996d625ed970a0063432daf6007cf4a3a48e3"
    assert m.license.spdx == "UNKNOWN"
    assert m.license.redistribution is True
    assert m.license.restricted is False
    assert m.evaluation.official_eligible is False
    assert m.evaluation.default_metric_status == "DIAGNOSTIC"
    assert m.structure.domain == "generic"
    assert m.structure.synthetic is True
    assert m.structure.languages == ["de", "en", "es", "fr", "hi", "it", "nl", "te"]
    assert m.structure.splits == ["train", "validation"]
    assert m.integrity.expected_documents == 580227
    assert m.integrity.sha256 == "b2be30549173d572a9a879b6a44ded51f653b6e7a8cafed43653ae750df656f6"
    # Totalité du labelset (G4) : 20 classes, sans plus ni moins.
    assert set(m.label_map) == set(ALL_20_LABELS)
    # Volumétrie par langue : complète et cohérente avec le total.
    assert m.structure.per_language_counts is not None
    assert set(m.structure.per_language_counts) == set(m.structure.languages)
    assert sum(m.structure.per_language_counts.values()) == m.integrity.expected_documents
    # Source non locale : résolution nulle (acquisition = affaire de l'adaptateur).
    assert loaded.resolution is None


# --------------------------------------------------------------------------- #
# itération documents / annotations
# --------------------------------------------------------------------------- #


def test_iter_documents(tmp_path: Path) -> None:
    rows = {
        "train": [
            _row(
                1, "Bonjour Marie Dupont",
                [("GIVENNAME", 8, 13, "Marie"), ("SURNAME", 14, 20, "Dupont")],
            ),
            _row(2, "नमस्ते", [], language="hi", region="IN", script="Deva"),
        ],
        "validation": [
            _row(3, "Goodbye", [], split="validation", language="en", region="US", script="Latn"),
        ],
    }
    adapter, _ = _adapter(tmp_path, rows)
    docs = list(adapter.iter_documents("train"))
    assert [d.doc_id for d in docs] == ["openpii:1", "openpii:2"]
    d1, d2 = docs
    assert d1.dataset == "openpii"
    assert d1.split == "train"
    assert d1.domain is Domain.GENERIC
    assert d1.language == "fr"
    assert d1.text == "Bonjour Marie Dupont"
    assert d1.meta == {"uid": 1, "region": "FR", "script": "Qxxx"}
    assert d2.language == "hi"
    assert d2.meta == {"uid": 2, "region": "IN", "script": "Deva"}
    val = list(adapter.iter_documents("validation"))
    assert [d.doc_id for d in val] == ["openpii:3"]
    assert val[0].split == "validation"


def test_iter_annotations(tmp_path: Path) -> None:
    rows = {
        "train": [
            _row(10, "Hr John, 28 years", [("TITLE", 0, 2, "Hr"), ("AGE", 9, 11, "28")],
                language="en", region="US", script="Latn"),
        ],
        "validation": [_row(11, "x", [])],
    }
    adapter, _ = _adapter(tmp_path, rows)
    anns = list(adapter.iter_annotations("train"))
    assert [a.annotation_id for a in anns] == ["openpii:10:a1", "openpii:10:a2"]
    title, age = anns
    assert title.doc_id == "openpii:10"
    assert title.start == 0 and title.end == 2 and title.span_text == "Hr"
    assert title.identifier_type.value == "QUASI"
    assert title.qi_categories == ("GEN_OCCUPATION",)
    assert title.expression_mode is ExpressionMode.EXPLICIT
    assert title.granularity.value == "EXACT"
    assert title.stability.value == "STABLE"
    assert age.qi_categories == ("GEN_AGE",)
    assert age.span_text == "28"
    assert age.granularity.value == "EXACT"
    assert age.stability.value == "STABLE"


def test_all_twenty_labels_resolve(tmp_path: Path) -> None:
    rows = {
        "train": [
            _row(i, f"text {i}", [(label, 0, 1, "t")])
            for i, label in enumerate(ALL_20_LABELS, start=1)
        ],
        "validation": [_row(99, "x", [])],
    }
    adapter, _ = _adapter(tmp_path, rows)
    anns = list(adapter.iter_annotations("train"))
    assert len(anns) == 20
    # Chaque annotation porte au moins un code taxonomie valide (garanti par le
    # label_map validé au chargement du manifeste).
    assert all(len(a.qi_categories) >= 1 for a in anns)


# --------------------------------------------------------------------------- #
# Erreurs dures (malformations) — aucune correction silencieuse
# --------------------------------------------------------------------------- #


def test_unmapped_label_is_blocking(tmp_path: Path) -> None:
    rows = {
        "train": [_row(1, "abc", [("FOOBAR", 0, 3, "abc")])],
        "validation": [_row(2, "y", [])],
    }
    adapter, _ = _adapter(tmp_path, rows)
    with pytest.raises(UnmappedLabelError, match="classe 'FOOBAR'"):
        list(adapter.iter_annotations("train"))


def test_invalid_json_line_is_error(tmp_path: Path) -> None:
    lines = {
        "train": [json.dumps(_row(1, "ok", [])), "{cassé"],
        "validation": [json.dumps(_row(2, "y", []))],
    }
    raw = _write_raw(tmp_path, lines)
    adapter = OpenpiiAdapter(_manifest_for(raw, 2), raw)
    with pytest.raises(IngestionError, match=r"train\.jsonl:2 : JSON invalide"):
        list(adapter.iter_documents("train"))


def test_missing_required_field_is_error(tmp_path: Path) -> None:
    row = _row(1, "abc", [])
    del row["language"]
    lines = {
        "train": [json.dumps(row, ensure_ascii=False)],
        "validation": [json.dumps(_row(2, "y", []), ensure_ascii=False)],
    }
    raw = _write_raw(tmp_path, lines)
    adapter = OpenpiiAdapter(_manifest_for(raw, 2), raw)
    with pytest.raises(IngestionError, match="champ\\(s\\) manquant\\(s\\) : language"):
        list(adapter.iter_documents("train"))


def test_wrong_row_type_is_actionable(tmp_path: Path) -> None:
    row = _row(1, "abc", [])
    row["source_text"] = 42
    lines = {
        "train": [json.dumps(row)],
        "validation": [json.dumps(_row(2, "y", []))],
    }
    raw = _write_raw(tmp_path, lines)
    adapter = OpenpiiAdapter(_manifest_for(raw, 2), raw)
    with pytest.raises(IngestionError, match=r"train\.jsonl:1 .*source_text"):
        list(adapter.iter_documents("train"))


def test_malformed_entity_is_error(tmp_path: Path) -> None:
    row = _row(1, "abc", [])
    row["privacy_mask"] = [{"label": "AGE", "start": 0, "end": 1}]  # sans ``value``
    lines = {
        "train": [json.dumps(row, ensure_ascii=False)],
        "validation": [json.dumps(_row(2, "y", []), ensure_ascii=False)],
    }
    raw = _write_raw(tmp_path, lines)
    adapter = OpenpiiAdapter(_manifest_for(raw, 2), raw)
    with pytest.raises(IngestionError, match="entité 1 malformée"):
        list(adapter.iter_annotations("train"))


def test_blank_line_is_error(tmp_path: Path) -> None:
    lines = {
        "train": [json.dumps(_row(1, "ok", []), ensure_ascii=False), ""],
        "validation": [json.dumps(_row(2, "y", []), ensure_ascii=False)],
    }
    raw = _write_raw(tmp_path, lines)
    adapter = OpenpiiAdapter(_manifest_for(raw, 2), raw)
    with pytest.raises(IngestionError, match="train\\.jsonl:2 : ligne vide"):
        list(adapter.iter_documents("train"))


def test_unsupported_split_is_error(tmp_path: Path) -> None:
    rows = {
        "train": [_row(1, "abc", [])],
        "validation": [_row(2, "y", [])],
    }
    adapter, _ = _adapter(tmp_path, rows)
    with pytest.raises(IngestionError, match="split 'test' non supporté"):
        list(adapter.iter_documents("test"))
def test_row_split_mismatch_is_rejected(tmp_path: Path) -> None:
    rows = {
        "train": [_row(1, "abc", [], split="validation")],
        "validation": [_row(2, "y", [], split="validation")],
    }
    adapter, _ = _adapter(tmp_path, rows)
    with pytest.raises(IngestionError, match=r"train\.jsonl:1 .*split déclaré"):
        list(adapter.iter_documents("train"))



# --------------------------------------------------------------------------- #
# Contrat EPIC-B : donnée aberrante transmise telle quelle, refusée en VALIDATE
# --------------------------------------------------------------------------- #


def test_incoherent_span_rejected_by_validation(tmp_path: Path) -> None:
    """Offsets incohérents : l'adaptateur ne corrige pas ; le validateur refuse (E-VAL-101)."""
    rows = {
        "train": [_row(5, "Bonjour le monde", [("GIVENNAME", 0, 5, "xx")])],
        "validation": [_row(6, "y", [], split="validation")],
    }
    adapter, _ = _adapter(tmp_path, rows)
    with pytest.raises(IngestionError, match=r"E-VAL-101.*openpii:5"):
        ingest(adapter, adapter.manifest, output_root=tmp_path / "processed")
    assert not (tmp_path / "processed" / "openpii").exists()


def test_ingest_deterministic_and_diagnostic(tmp_path: Path) -> None:
    """Réingestion = fichiers bit-à-bit identiques ; statut ``diagnostic`` (spdx UNKNOWN)."""
    rows = {
        "train": [
            _row(
                1, "Bonjour Marie Dupont",
                [("GIVENNAME", 8, 13, "Marie"), ("SURNAME", 14, 20, "Dupont")],
            ),
            _row(2, "Hr John, 28 years", [("TITLE", 0, 2, "Hr"), ("AGE", 9, 11, "28")],
                language="en", region="US", script="Latn"),
        ],
        "validation": [
            _row(3, "Rue de la Paix 42", [("STREET", 0, 14, "Rue de la Paix"),
                                          ("BUILDINGNUM", 15, 17, "42")],
                 split="validation", region="FR"),
        ],
    }
    adapter1, _ = _adapter(tmp_path, rows)
    res1 = ingest(adapter1, adapter1.manifest, output_root=tmp_path / "p1")
    assert res1.status == "diagnostic"
    assert res1.counts["documents"] == 3

    base1 = tmp_path / "p1" / "openpii"
    lock1 = json.loads((base1 / ".manifest.lock.json").read_text(encoding="utf-8"))
    assert set(lock1) == {
        "manifest", "schema_version", "taxonomy_version",
        "source", "files", "date", "status",
    }
    # Source non locale : empreinte nulle, kind figé.
    assert lock1["source"] == {"kind": "huggingface", "fingerprint": None}
    assert lock1["status"] == "diagnostic"
    assert set(lock1["files"]) == {
        "train/documents.jsonl", "train/annotations.jsonl",
        "validation/documents.jsonl", "validation/annotations.jsonl",
    }
    # ``masked_text`` n'est pas dupliqué dans le pivot (reconstructible).
    doc_lines = (base1 / "train" / "documents.jsonl").read_text(encoding="utf-8").splitlines()
    records = [json.loads(line) for line in doc_lines]
    assert all("masked_text" not in r for r in records)
    keys = {
        "doc_id", "dataset", "split", "domain", "language", "text", "meta",
        "author_id", "org_id", "thread_id", "position_in_thread", "timestamp",
    }
    assert all(set(r) == keys for r in records)

    # Réingestion dans un répertoire neuf : bit-à-bit identique (le lock diffère
    # uniquement par sa date).
    adapter2 = OpenpiiAdapter(adapter1.manifest, adapter1.raw_dir)
    res2 = ingest(adapter2, adapter2.manifest, output_root=tmp_path / "p2")
    base2 = tmp_path / "p2" / "openpii"
    for name in lock1["files"]:
        assert (base1 / name).read_bytes() == (base2 / name).read_bytes()
    assert (base1 / ".validation.json").read_bytes() == (base2 / ".validation.json").read_bytes()
    lock2 = json.loads((base2 / ".manifest.lock.json").read_text(encoding="utf-8"))
    stripped = {k: v for k, v in lock1.items() if k != "date"}
    assert stripped == {k: v for k, v in lock2.items() if k != "date"}
    assert res2.status == "diagnostic"


# --------------------------------------------------------------------------- #
# Acquisition (révision épinglée) — réseau simulé
# --------------------------------------------------------------------------- #


def test_download_cache_and_force(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    rows = {
        "train": [_row(1, "abc", [])],
        "validation": [_row(2, "y", [])],
    }
    adapter, raw = _adapter(tmp_path, rows)
    original = {name: (raw / name).read_bytes() for name in ("train.jsonl", "validation.jsonl")}
    calls: list[str] = []

    def fake_fetch(url: str, dest: Path) -> int:
        calls.append(url)
        dest.write_bytes(original[dest.name])
        return len(original[dest.name])

    monkeypatch.setattr(openpii_module, "_fetch", fake_fetch)

    # Cache présent et valide : rien n'est re-téléchargé.
    report = adapter.download()
    assert report.from_cache is True
    assert report.bytes_downloaded == 0
    assert report.sha256 == adapter.manifest.integrity.sha256
    assert report.revision == "506996d625ed970a0063432daf6007cf4a3a48e3"
    assert calls == []
    acquisition = json.loads((raw / ".acquisition.json").read_text(encoding="utf-8"))
    assert acquisition["source"]["revision"] == adapter.manifest.source.revision
    assert acquisition["sha256"] == adapter.manifest.integrity.sha256
    assert {item["name"] for item in acquisition["files"]} == {
        "train.jsonl",
        "validation.jsonl",
    }

    # ``force`` : re-téléchargement de la révision épinglée, pas de HEAD.
    report2 = adapter.download(force=True)
    assert report2.from_cache is False
    assert report2.bytes_downloaded == sum(len(b) for b in original.values())
    expected_prefix = (
        "https://huggingface.co/datasets/ai4privacy/open-pii-masking-500k-ai4privacy/"
        "resolve/506996d625ed970a0063432daf6007cf4a3a48e3/"
    )
    assert all(url.startswith(expected_prefix) for url in calls)


def test_force_revalidates_downloaded_cache(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    rows = {
        "train": [_row(1, "abc", [])],
        "validation": [_row(2, "y", [])],
    }
    adapter, raw = _adapter(tmp_path, rows)
    adapter.download()
    original_validation = (raw / "validation.jsonl").read_bytes()

    def fake_corrupt_fetch(url: str, dest: Path) -> int:
        payload = b"corrompu" if dest.name == "train.jsonl" else original_validation
        dest.write_bytes(payload)
        return len(payload)

    monkeypatch.setattr(openpii_module, "_fetch", fake_corrupt_fetch)
    with pytest.raises(IngestionError, match=r"empreinte du cache local .* ≠ manifeste"):
        adapter.download(force=True)


def test_download_corrupt_cache_is_error(tmp_path: Path) -> None:
    rows = {
        "train": [_row(1, "abc", [])],
        "validation": [_row(2, "y", [])],
    }
    adapter, raw = _adapter(tmp_path, rows)
    (raw / "train.jsonl").write_bytes(b"corrompu")
    with pytest.raises(IngestionError, match=r"empreinte du cache local .* ≠ manifeste"):
        adapter.download()


def test_download_requires_pinned_revision(tmp_path: Path) -> None:
    data = yaml.safe_load(OPENPII_YAML.read_text(encoding="utf-8"))
    data["source"]["revision"] = None
    manifest = DatasetManifest(**data)
    raw = tmp_path / "openpii"
    raw.mkdir()
    adapter = OpenpiiAdapter(manifest, raw)
    with pytest.raises(IngestionError, match="revision"):
        adapter.download()


# --------------------------------------------------------------------------- #
# Registre
# --------------------------------------------------------------------------- #


def test_registry_and_aliases() -> None:
    assert resolve("openpii") is OpenpiiAdapter
    assert resolve("ai4privacy") is OpenpiiAdapter
    assert resolve("open-pii-500k") is OpenpiiAdapter
