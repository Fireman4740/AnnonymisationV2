#!/usr/bin/env python3
"""Refuse les données et secrets dans l'index Git (SPEC-09 §2.2, règle L1)."""

from __future__ import annotations

import re
import subprocess
import sys
from collections.abc import Iterable, Sequence
from pathlib import Path, PurePosixPath

MAX_JSONL_BYTES = 1_000_000
_ALLOWED_DATA_BASENAMES = frozenset({".gitkeep", "readme.md"})
_FORBIDDEN_PATH_PARTS = ("mimic", "meddocan")
_SECRET_PATTERNS = (
    re.compile(
        r"(?i)(?:api[_-]?key|secret[_-]?key|access[_-]?token|authorization|bearer|password)"
        r"\s*[:=]\s*[\"']?(?:sk-[A-Za-z0-9_-]{16,}|gh[pousr]_[A-Za-z0-9_]{20,}|"
        r"AKIA[0-9A-Z]{16}|[A-Za-z0-9_+/=-]{24,})"
    ),
    re.compile(r"-----BEGIN (?:RSA |EC |OPENSSH )?PRIVATE KEY-----"),
)


def _git_index_paths() -> list[Path]:
    """Retourne les chemins suivis ; l'absence de Git produit une erreur claire."""
    try:
        result = subprocess.run(
            ("git", "ls-files", "-z"),
            check=True,
            capture_output=True,
        )
    except (OSError, subprocess.CalledProcessError) as exc:
        raise RuntimeError(
            "impossible de lire l'index Git ; passez les chemins en arguments"
        ) from exc
    return [Path(raw) for raw in result.stdout.decode("utf-8").split("\0") if raw]


def _normalised(path: Path) -> str:
    return path.as_posix().replace("\\", "/").lower()


def _data_violation(path: Path, normalised: str) -> str | None:
    parts = PurePosixPath(normalised).parts
    if "data" not in parts:
        return None
    basename = parts[-1]
    if basename not in _ALLOWED_DATA_BASENAMES:
        return "fichier sous data/ interdit (seuls .gitkeep et README.md sont autorisés)"
    return None


def _path_violation(path: Path, normalised: str) -> str | None:
    # Les fiches documentaires peuvent citer des corpus non redistribuables ;
    # la garde vise les fichiers de données effectivement versionnés.
    is_documentation = normalised.startswith(("documentation/", "docs/"))
    if not is_documentation and any(part in normalised for part in _FORBIDDEN_PATH_PARTS):
        return "chemin contenant un corpus interdit (mimic ou meddocan)"
    if not is_documentation and (normalised.endswith(".dcm") or ".dcm/" in normalised):
        return "fichier DICOM interdit (.dcm)"
    basename = path.name.lower()
    if basename == ".env" or basename.startswith(".env."):
        return "fichier .env interdit"
    return _data_violation(path, normalised)


def _content_violation(path: Path) -> str | None:
    if not path.is_file():
        return None
    try:
        text = path.read_text(encoding="utf-8", errors="ignore")
    except OSError as exc:
        return f"fichier illisible : {exc}"
    if any(pattern.search(text) for pattern in _SECRET_PATTERNS):
        return "clé ou secret détecté dans le contenu"
    return None


def check_paths(paths: Iterable[Path]) -> list[str]:
    """Retourne les violations, triées et dédupliquées, pour les chemins donnés."""
    violations: set[str] = set()
    for path in sorted({Path(path) for path in paths}, key=lambda item: item.as_posix()):
        normalised = _normalised(path)
        reason = _path_violation(path, normalised)
        if reason:
            violations.add(f"{path}: {reason}")
        if path.suffix.lower() == ".jsonl" and path.is_file():
            try:
                size = path.stat().st_size
            except OSError as exc:
                violations.add(f"{path}: impossible de lire la taille ({exc})")
            else:
                if size > MAX_JSONL_BYTES:
                    violations.add(
                        f"{path}: JSONL de {size} octets, limite {MAX_JSONL_BYTES} octets dépassée"
                    )
        reason = _content_violation(path)
        if reason:
            violations.add(f"{path}: {reason}")
    return sorted(violations)


def main(argv: Sequence[str] | None = None) -> int:
    """Point d'entrée pre-commit/CI ; les arguments sont des chemins à contrôler."""
    raw_args = list(sys.argv[1:] if argv is None else argv)
    if raw_args and raw_args[0] == "--":
        raw_args = raw_args[1:]
    try:
        paths = [Path(value) for value in raw_args] if raw_args else _git_index_paths()
    except RuntimeError as exc:
        print(f"ERREUR conformité : {exc}", file=sys.stderr)
        return 1

    violations = check_paths(paths)
    if violations:
        print("Refus conformité données/secrets :", file=sys.stderr)
        for violation in violations:
            print(f"  - {violation}", file=sys.stderr)
        return 1
    print(f"Conformité données/secrets : OK ({len(paths)} chemin(s) contrôlé(s))")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
