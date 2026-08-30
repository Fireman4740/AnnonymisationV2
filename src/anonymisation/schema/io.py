"""Lecture/écriture des tables JSONL du format pivot.

Implémente SPEC-02 §2 (format physique) et SPEC-04 §6/§9 (écriture atomique,
déterminisme bit à bit).

Règle d'or : aucune valeur par défaut silencieuse. Une ligne invalide fait
échouer la lecture avec le chemin du fichier ET le numéro de ligne fautifs.
"""

from __future__ import annotations

import hashlib
import json
import os
from collections.abc import Iterable, Iterator
from pathlib import Path
from typing import TypeVar

from pydantic import BaseModel, ValidationError

T = TypeVar("T", bound=BaseModel)


class JsonlError(ValueError):
    """Ligne JSONL invalide — porte le chemin et le numéro de ligne fautifs."""


def read_jsonl(path: Path, model: type[T]) -> Iterator[T]:
    """Lit ``path`` ligne à ligne et valide chaque ligne via ``model``.

    Générateur paresseux (SPEC-03 §6 règle 1) : rien n'est chargé en mémoire
    tant que l'appelant n'itère pas. Les lignes vides sont ignorées (tolérance
    minimale pour une fin de fichier avec retour à la ligne final).

    Lève :
        JsonlError : ligne non-JSON ou ne validant pas le modèle. Le message
        nomme le fichier et le numéro de ligne (1-indexé), jamais un défaut
        silencieux.
    """
    path = Path(path)
    with path.open("r", encoding="utf-8", newline="") as fh:
        for lineno, raw_line in enumerate(fh, start=1):
            line = raw_line.rstrip("\n").rstrip("\r")
            if not line.strip():
                continue
            try:
                payload = json.loads(line)
            except json.JSONDecodeError as exc:
                raise JsonlError(
                    f"{path}:{lineno} : JSON invalide ({exc})"
                ) from exc
            try:
                yield model.model_validate(payload)
            except ValidationError as exc:
                raise JsonlError(
                    f"{path}:{lineno} : ne valide pas {model.__name__} ({exc})"
                ) from exc


def _default(value: object) -> object:
    raise JsonlError(f"Type non sérialisable en JSON : {type(value)!r} ({value!r})")


def write_jsonl(path: Path, records: Iterable[BaseModel]) -> int:
    """Écrit ``records`` dans ``path`` de façon atomique et reproductible.

    Garanties (SPEC-04 §6 et §9) :

    - Écriture dans ``<path>.tmp`` puis ``os.replace()`` vers ``path`` : un
      lecteur concurrent ne voit jamais un fichier à moitié écrit.
    - UTF-8, séparateur ``\\n``, pas de BOM, ``ensure_ascii=False``.
    - ``sort_keys=True`` : deux écritures des mêmes enregistrements produisent
      des fichiers identiques bit à bit, condition nécessaire au test de
      déterminisme de SPEC-04 §11.

    Retourne le nombre d'enregistrements écrits.
    """
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp_path = path.with_name(path.name + ".tmp")

    count = 0
    try:
        with tmp_path.open("w", encoding="utf-8", newline="\n") as fh:
            for record in records:
                data = record.model_dump(mode="json")
                line = json.dumps(
                    data,
                    ensure_ascii=False,
                    sort_keys=True,
                    separators=(",", ":"),
                    default=_default,
                )
                fh.write(line)
                fh.write("\n")
                count += 1
    except BaseException:
        # Nettoyage du fichier temporaire en cas d'échec en cours d'écriture :
        # ne jamais laisser de résidu qui pourrait être confondu avec une
        # sortie valide.
        if tmp_path.exists():
            tmp_path.unlink()
        raise

    os.replace(tmp_path, path)
    return count


def sha256_bytes(data: bytes) -> str:
    """Empreinte SHA-256 hexadécimale d'un bloc d'octets."""
    return hashlib.sha256(data).hexdigest()


def sha256_file(path: Path) -> str:
    """Empreinte SHA-256 hexadécimale du contenu d'un fichier.

    Lecture par blocs pour rester utilisable sur les fichiers volumineux
    (OpenPII, MultiCoNER — SPEC-03 §6).
    """
    path = Path(path)
    h = hashlib.sha256()
    with path.open("rb") as fh:
        for chunk in iter(lambda: fh.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()
