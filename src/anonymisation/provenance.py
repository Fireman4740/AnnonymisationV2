"""Vérification du contenu d'une archive Git contre son arbre source exporté."""

from __future__ import annotations

import os
import re
import subprocess
import tempfile
from pathlib import Path

ARCHIVAL_TEMPLATE = b"commit: $Format:%H$\ntree: $Format:%T$\n"


def archive_identity(root: Path) -> tuple[str, str] | None:
    try:
        text = (root / ".git_archival.txt").read_text(encoding="utf-8")
    except OSError:
        return None
    match = re.fullmatch(r"commit: ([0-9a-f]{40})\ntree: ([0-9a-f]{40})\n", text)
    return (match[1], match[2]) if match else None


def archive_dirty(root: Path) -> bool | None:
    """Reconstitue l'arbre dans un index temporaire ; aucun fichier source modifié.

    Git contrôle les contenus, chemins, modes et liens symboliques. Les sorties
    ignorées par le .gitignore exporté restent hors de l'arbre. Le marqueur
    export-subst est remis à sa forme source dans l'index uniquement.
    Une identité absente ou une vérification impossible reste inconnue.
    """
    identity = archive_identity(root)
    if identity is None:
        return None
    try:
        with tempfile.TemporaryDirectory(prefix="anonv2-source-index-") as directory:
            env = dict(os.environ)
            env.update(GIT_DIR=str(Path(directory) / ".git"), GIT_WORK_TREE=str(root.resolve()),
                       GIT_INDEX_FILE=str(Path(directory) / "index"))

            def git(*args: str, data: bytes | None = None) -> bytes:
                return subprocess.run(
                    ("git", "-c", "core.excludesFile=/dev/null", "-c", "core.autocrlf=false",
                     "-c", "core.attributesFile=/dev/null", *args),
                    cwd=root, env=env, input=data, capture_output=True, check=True, timeout=60,
                ).stdout.strip()

            git("init", "--quiet")
            git("add", "--", ".")
            blob = git("hash-object", "-w", "--stdin", data=ARCHIVAL_TEMPLATE).decode()
            git("update-index", "--add", "--cacheinfo", "100644", blob, ".git_archival.txt")
            actual_tree = git("write-tree").decode()
            return actual_tree != identity[1]
    except (OSError, subprocess.SubprocessError):
        return None
