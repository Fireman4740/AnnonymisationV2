"""Adaptateur OpenPII 500k (AI4Privacy) — fiche ``documentation/datasets/openpii-500k.md``.

Format source (révision épinglée dans le manifeste) : JSONL HuggingFace
``ai4privacy/open-pii-masking-500k-ai4privacy``, une ligne = un exemple :

- ``source_text`` / ``masked_text`` (str) ;
- ``privacy_mask`` : ``[{label, start, end, value, label_index}]`` — offsets
  **caractères de ``source_text``** (vérifiés sur 100 % des 580 227 lignes de
  la release : ``source_text[start:end] == value``, aucune superposition) ;
- ``split`` (str) : « train » ou « validation » — source de vérité du split ;
- ``uid`` (int) : unique sur tout le corpus → ``doc_id = "openpii:{uid}"`` ;
- ``language`` / ``region`` / ``script`` : métadonnées conservées en ``meta`` ;
- ``mbert_tokens`` / ``mbert_token_classes`` : artefacts de tokenisation,
  ignorés (les offsets caractères sont déjà porteurs).

``masked_text`` est le texte source où chaque span est remplacé par
``[LABEL_index]`` (non aligné caractère à caractère) : il est **reconstructible**
à partir de ``source_text`` + ``privacy_mask`` (vérifié, 0 divergence sur la
release) et n'est donc pas dupliqué dans le pivot.

L'adaptateur ne filtre ni ne corrige silencieusement (contrat EPIC-B) :

- une ligne **malformée** (JSON invalide, champ requis manquant, ``uid``
  non-entier, entité incomplète) est une **erreur dure** nommant fichier et
  ligne ;
- une donnée source **aberrante mais analysable** (offsets incohérents, label
  inconnu…) remonte telle quelle : le label inconnu est refusé dès ici
  (``UnmappedLabelError``, G4/E-MAP-001), le span incohérent est transmis au
  validateur qui le rejette avec son ``doc_id`` (E-VAL-101).
"""

from __future__ import annotations

import hashlib
import json
import os
import urllib.request
from collections.abc import Iterator
from datetime import date
from pathlib import Path
from typing import Any, ClassVar
from urllib.parse import quote

from anonymisation.datasets.base import AcquisitionReport, DatasetAdapter
from anonymisation.datasets.ingest import IngestionError
from anonymisation.datasets.registry import UnmappedLabelError, register
from anonymisation.schema.io import write_json
from anonymisation.schema.models import Annotation, Document, Domain
from anonymisation.schema.taxonomy import ExpressionMode

ACQUISITION_NAME = ".acquisition.json"


# Champs d'une ligne de JSONL indispensables à la construction d'un document.
_REQUIRED_FIELDS: tuple[str, ...] = (
    "source_text",
    "masked_text",
    "privacy_mask",
    "split",
    "uid",
    "language",
    "region",
    "script",
)


# Champs d'une entité ``privacy_mask`` indispensables à la construction d'une
# annotation.
_REQUIRED_ENTITY_FIELDS: tuple[str, ...] = (
    "label",
    "start",
    "end",
    "value",
    "label_index",
)


def _fetch(url: str, dest: Path) -> int:
    """Télécharge ``url`` vers ``dest`` avec un renommage atomique."""

    tmp = dest.with_suffix(dest.suffix + ".tmp")
    size = 0
    try:
        with urllib.request.urlopen(url) as resp, tmp.open("wb") as out:  # noqa: S310
            for chunk in iter(lambda: resp.read(1 << 20), b""):
                out.write(chunk)
                size += len(chunk)
        os.replace(tmp, dest)
    except BaseException:
        if tmp.exists():
            tmp.unlink()
        raise
    return size


@register
class OpenpiiAdapter(DatasetAdapter):
    """OpenPII 500k — JSONL HuggingFace épinglé, offsets caractères, 20 classes.

    Acquisition : téléchargement de la **révision épinglée** du dépôt HuggingFace
    (``source.revision`` du manifeste) vers ``data/raw/openpii/``. Le cache local
    est vérifié par son sha256 agrégé (``integrity.sha256``) à chaque itération :
    un corpus altéré ou incomplet fait échouer l'ingestion, sans approximation.
    """

    key = "openpii"
    aliases = ("ai4privacy", "open-pii-500k")
    streaming: ClassVar[bool] = True

    # Layout du cache local (data/raw/openpii/) ↔ fichiers du dépôt HF.
    _SPLIT_FILES: ClassVar[dict[str, str]] = {
        "train": "train.jsonl",
        "validation": "validation.jsonl",
    }
    _HF_PATHS: ClassVar[dict[str, str]] = {
        "train.jsonl": "data/train/train.jsonl",
        "validation.jsonl": "data/validation/test.jsonl",
    }
    _HF_BASE_URL = "https://huggingface.co/datasets"

    def __init__(self, manifest: Any, raw_dir: Path) -> None:
        super().__init__(manifest, raw_dir)
        self._raw_digest: str | None = None

    # --- Acquisition ------------------------------------------------------ #

    def download(self, *, force: bool = False) -> AcquisitionReport:
        """Télécharge (ou réutilise le cache de) la révision épinglée."""

        src = self.manifest.source
        if src.kind != "huggingface" or not src.revision or not src.repo:
            raise IngestionError(
                f"openpii : source de manifeste inattendue (kind={src.kind!r}, "
                f"repo={src.repo!r}, revision={src.revision!r}) — l'acquisition "
                "requiert un dépôt et un commit HuggingFace déclarés"
            )
        self.raw_dir.mkdir(parents=True, exist_ok=True)
        if force:
            self._raw_digest = None
        from_cache = True
        bytes_downloaded = 0
        urls: dict[str, str] = {}
        repo = quote(src.repo.strip("/"), safe="/")
        revision = quote(src.revision, safe="")
        for name in self._SPLIT_FILES.values():
            dest = self.raw_dir / name
            url = f"{self._HF_BASE_URL}/{repo}/resolve/{revision}/{self._HF_PATHS[name]}"
            urls[name] = url
            if not force and dest.is_file():
                continue
            from_cache = False
            try:
                bytes_downloaded += _fetch(url, dest)
            except OSError as exc:
                raise IngestionError(
                    f"openpii : téléchargement impossible pour {name!r} depuis {url!r} ({exc})"
                ) from exc
        digest = self._verify_raw()
        write_json(
            self.raw_dir / ACQUISITION_NAME,
            {
                "dataset": self.key,
                "source": {"kind": src.kind, "repo": src.repo, "revision": src.revision},
                "files": [
                    {
                        "name": name,
                        "path": name,
                        "url": urls[name],
                        "bytes": (self.raw_dir / name).stat().st_size,
                    }
                    for name in self._SPLIT_FILES.values()
                ],
                "sha256": digest,
                "bytes_downloaded": bytes_downloaded,
                "from_cache": from_cache,
                "date": date.today().isoformat(),
            },
        )
        return AcquisitionReport(
            dataset=self.key,
            path=self.raw_dir,
            sha256=digest,
            bytes_downloaded=bytes_downloaded,
            from_cache=from_cache,
            revision=src.revision,
        )

    def _verify_raw(self) -> str:
        """Vérifie le cache local (présence + sha256 agrégé vs manifeste).

        Agrégat = sha256 de ``train.jsonl`` puis ``validation.jsonl``
        concaténés, dans cet ordre (convention du manifeste). Mémoïsé par
        instance d'adaptateur pour éviter de re-taper 675 Mo par split.
        """
        if self._raw_digest is not None:
            return self._raw_digest
        expected = self.manifest.integrity.sha256
        h = hashlib.sha256()
        for name in self._SPLIT_FILES.values():
            path = self.raw_dir / name
            if not path.is_file():
                raise IngestionError(
                    f"openpii : {path} manquant — corpus non acquis ou incomplet ; "
                    "exécutez l'acquisition du dataset"
                )
            with path.open("rb") as f:
                for chunk in iter(lambda: f.read(1 << 20), b""):
                    h.update(chunk)
        digest = h.hexdigest()
        if expected is not None and digest != expected:
            raise IngestionError(
                f"openpii : empreinte du cache local {digest} ≠ manifeste {expected} — "
                "corpus altéré, incomplet ou de mauvaise révision ; réacquérir avec force"
            )
        self._raw_digest = digest
        return digest

    # --- Parcours --------------------------------------------------------- #

    def _check_split(self, split: str) -> None:
        if split not in self._SPLIT_FILES:
            raise IngestionError(
                f"openpii : split {split!r} non supporté — splits du dataset : "
                f"{', '.join(sorted(self._SPLIT_FILES))}"
            )

    def _iter_rows(self, split: str) -> Iterator[tuple[Path, int, dict[str, Any]]]:
        """Itère les lignes validées du split : ``(fichier, ligne, ligne)``."""

        self._check_split(split)
        path = self.raw_dir / self._SPLIT_FILES[split]
        self._verify_raw()
        with path.open(encoding="utf-8") as f:
            for line_no, line in enumerate(f, start=1):
                if not line.strip():
                    raise IngestionError(f"openpii : {path}:{line_no} : ligne vide")
                row = self._parse_row(path, line_no, line)
                if row["split"] != split:
                    raise IngestionError(
                        f"openpii : {path}:{line_no} : doc_id=openpii:{row['uid']} : "
                        f"split déclaré {row['split']!r} incompatible avec le fichier {split!r}"
                    )
                yield path, line_no, row

    @staticmethod
    def _parse_row(path: Path, line_no: int, line: str) -> dict[str, Any]:
        """Valide l'enveloppe d'une ligne ; toute malformation est une erreur dure."""

        try:
            row = json.loads(line)
        except json.JSONDecodeError as exc:
            raise IngestionError(f"openpii : {path}:{line_no} : JSON invalide ({exc.msg})") from exc
        if not isinstance(row, dict):
            raise IngestionError(f"openpii : {path}:{line_no} : ligne non-objet JSON")
        missing = [k for k in _REQUIRED_FIELDS if k not in row or row[k] is None]
        if missing:
            raise IngestionError(
                f"openpii : {path}:{line_no} : champ(s) manquant(s) : {', '.join(missing)}"
            )
        for field in ("source_text", "masked_text", "split", "language", "region", "script"):
            if not isinstance(row[field], str):
                raise IngestionError(
                    f"openpii : {path}:{line_no} : champ {field!r} non-chaîne : "
                    f"{row[field]!r}"
                )
        if not isinstance(row["uid"], int) or isinstance(row["uid"], bool):
            raise IngestionError(f"openpii : {path}:{line_no} : uid non-entier : {row['uid']!r}")
        if not isinstance(row["privacy_mask"], list):
            raise IngestionError(f"openpii : {path}:{line_no} : privacy_mask non-liste")
        return row

    def iter_documents(self, split: str) -> Iterator[Document]:
        """Extrait les documents du split (1 ligne source = 1 document)."""

        for path, line_no, row in self._iter_rows(split):
            doc_id = f"openpii:{row['uid']}"
            try:
                document = Document(
                    doc_id=doc_id,
                    dataset=self.key,
                    split=row["split"],
                    domain=Domain.GENERIC,
                    language=row["language"],
                    text=row["source_text"],
                    meta={"uid": row["uid"], "region": row["region"], "script": row["script"]},
                )
            except ValueError as exc:
                raise IngestionError(
                    f"openpii : {path}:{line_no} : doc_id={doc_id} : document invalide ({exc})"
                ) from exc
            yield document

    def iter_annotations(self, split: str) -> Iterator[Annotation]:
        """Extrait les annotations du split (1 entité = 1 annotation)."""

        for path, line_no, row in self._iter_rows(split):
            doc_id = f"openpii:{row['uid']}"
            for i, ent in enumerate(row["privacy_mask"], start=1):
                if not isinstance(ent, dict) or any(
                    k not in ent or ent[k] is None for k in _REQUIRED_ENTITY_FIELDS
                ):
                    raise IngestionError(
                        f"openpii : {path}:{line_no} : doc_id={doc_id} : entité {i} malformée"
                    )
                if (
                    not isinstance(ent["label"], str)
                    or not isinstance(ent["start"], int)
                    or isinstance(ent["start"], bool)
                    or not isinstance(ent["end"], int)
                    or isinstance(ent["end"], bool)
                    or not isinstance(ent["value"], str)
                    or not isinstance(ent["label_index"], int)
                    or isinstance(ent["label_index"], bool)
                ):
                    raise IngestionError(
                        f"openpii : {path}:{line_no} : doc_id={doc_id} : "
                        f"entité {i} contient un type invalide"
                    )
                entry = self.manifest.label_map.get(ent["label"])
                if entry is None:
                    raise UnmappedLabelError(
                        f"openpii : {path}:{line_no} : doc_id={doc_id} : classe "
                        f"{ent['label']!r} absente du label_map — erreur E-MAP-001, "
                        "compléter le manifeste, ne pas approximer"
                    )
                try:
                    annotation = Annotation(
                        annotation_id=f"openpii:{row['uid']}:a{i}",
                        doc_id=doc_id,
                        start=ent["start"],
                        end=ent["end"],
                        span_text=ent["value"],
                        identifier_type=entry.identifier_type,
                        qi_categories=tuple(entry.qi_categories),
                        expression_mode=ExpressionMode.EXPLICIT,
                        granularity=entry.granularity,
                        stability=entry.stability,
                    )
                except ValueError as exc:
                    raise IngestionError(
                        f"openpii : {path}:{line_no} : doc_id={doc_id} : "
                        f"annotation {i} invalide ({exc})"
                    ) from exc
                yield annotation
