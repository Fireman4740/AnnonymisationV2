"""Vérification d'intégrité des fichiers pivot et des artefacts de run.

Pourquoi ce module : sans lui, ``score`` relisait le pivot gold **courant** du
disque, quel que soit celui sur lequel ``predict`` avait tourné. Une
ré-ingestion (nouvelle version d'adaptateur, correction d'annotations) entre
les deux commandes produisait une scorecard calculée contre une vérité terrain
différente de celle du run — sans le moindre avertissement. C'est exactement
la classe d'erreur « chiffre faux mais plausible » que la règle d'or interdit.

La chaîne est donc fermée par empreintes SHA-256 :

* ``ingest`` écrit ``files`` (``"<split>/<table>.jsonl" -> sha256``) dans le
  lock d'ingestion ;
* ``predict`` vérifie le pivot contre ce lock **avant** de traiter un document,
  puis recopie le lock dans ``data_version`` et ajoute l'empreinte de ses
  propres sorties (``outputs``) ;
* ``score`` revérifie le pivot **et** les prédictions contre le lock de run.

Ce module ne dépend que de la bibliothèque standard et de ``schema.io`` :
``score`` peut l'importer sans charger aucun détecteur (C5).
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from pathlib import Path

from anonymisation.schema.io import sha256_file


class DataIntegrityError(ValueError):
    """Fichier absent, non verrouillé ou dont l'empreinte a changé."""


def locked_files(data_version: object, *, context: str) -> Mapping[str, str]:
    """Extrait la table ``files`` d'un lock d'ingestion, ou lève.

    ``context`` nomme l'artefact fautif dans le message (lock de run, lock
    d'ingestion) pour que le correctif soit évident.
    """
    if not isinstance(data_version, Mapping):
        raise DataIntegrityError(
            f"{context} : `data_version` absent ou invalide — le pivot n'a pas "
            "été produit par `anonv2 datasets ingest`. Réingérer le corpus puis "
            "relancer `anonv2 predict`."
        )
    files = data_version.get("files")
    if not isinstance(files, Mapping) or not files:
        raise DataIntegrityError(
            f"{context} : `data_version.files` absent ou vide — aucune empreinte "
            "de données à vérifier. Réingérer le corpus puis relancer "
            "`anonv2 predict`."
        )
    return {str(key): str(value) for key, value in files.items()}


def verify_pivot_files(
    dataset_root: Path,
    split: str,
    names: Sequence[str],
    files: Mapping[str, str],
    *,
    context: str,
    required: Sequence[str] = (),
) -> dict[str, str]:
    """Vérifie ``dataset_root/<split>/<name>`` contre les empreintes ``files``.

    Un fichier présent sur disque mais absent du lock est une erreur : il a été
    ajouté hors ingestion et rien ne garantit son contenu. Un fichier listé dans
    ``required`` doit exister. Retourne les empreintes vérifiées, triées.
    """
    verified: dict[str, str] = {}
    for name in names:
        key = f"{split}/{name}"
        path = Path(dataset_root) / split / name
        expected = files.get(key)
        if not path.is_file():
            if name in required or expected is not None:
                raise DataIntegrityError(
                    f"{context} : fichier pivot attendu absent : {path} "
                    f"(clé de lock `{key}`). Réingérer le corpus."
                )
            continue
        if expected is None:
            raise DataIntegrityError(
                f"{context} : {path} existe mais n'est pas verrouillé (clé `{key}` "
                "absente de `files`). Il a été modifié ou ajouté hors ingestion : "
                "réingérer le corpus."
            )
        actual = sha256_file(path)
        if actual != expected:
            raise DataIntegrityError(
                f"{context} : empreinte divergente pour {path} — attendu "
                f"{expected[:12]}…, trouvé {actual[:12]}…. Le pivot a changé "
                "depuis le lock : restaurer la version verrouillée ou relancer "
                "`anonv2 predict` sur le pivot courant."
            )
        verified[key] = actual
    return dict(sorted(verified.items()))


def verify_run_outputs(
    run_dir: Path, outputs: object, names: Sequence[str], *, context: str
) -> dict[str, str]:
    """Vérifie les artefacts d'un run (``predictions.jsonl``…) contre ``outputs``."""
    if not isinstance(outputs, Mapping):
        raise DataIntegrityError(
            f"{context} : `outputs` absent du lock — run produit avant le "
            "verrouillage des sorties. Relancer `anonv2 predict`."
        )
    verified: dict[str, str] = {}
    for name in names:
        path = Path(run_dir) / name
        expected = outputs.get(name)
        if expected is None:
            raise DataIntegrityError(
                f"{context} : empreinte de `{name}` absente de `outputs`. "
                "Relancer `anonv2 predict`."
            )
        if not path.is_file():
            raise DataIntegrityError(f"{context} : artefact de run absent : {path}")
        actual = sha256_file(path)
        if actual != str(expected):
            raise DataIntegrityError(
                f"{context} : {path} a été modifié après `predict` (attendu "
                f"{str(expected)[:12]}…, trouvé {actual[:12]}…). Relancer "
                "`anonv2 predict` plutôt que d'éditer un run."
            )
        verified[name] = actual
    return verified


__all__ = [
    "DataIntegrityError",
    "locked_files",
    "verify_pivot_files",
    "verify_run_outputs",
]
