"""Chargement du code SPIA original recopié, sans toucher à ``sys.path`` global.

Le code original importe en absolu ``src.*`` et ``config.*``. Ces noms sont
servis TEMPORAIREMENT depuis ``original/`` : les entrées homonymes de
``sys.modules`` sont mises de côté puis restaurées, et ``original/`` n'est en
tête de ``sys.path`` que le temps du contexte. Toute fonction originale doit
être appelée DANS le contexte : certaines importent à l'exécution
(``parse_subject_profiling`` → ``fix_json_with_llm``).
"""

from __future__ import annotations

import hashlib
import importlib
import json
import sys
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path
from types import ModuleType, SimpleNamespace

ROOT = Path(__file__).with_name("original")
_PREFIXES = ("src", "config")


class VendoredSpiaError(RuntimeError):
    """Copie du code original altérée."""


def verify() -> dict[str, str]:
    """Vérifie chaque fichier recopié contre ``ORIGINAL.json`` ; renvoie le manifeste."""
    manifest = json.loads((ROOT / "ORIGINAL.json").read_text(encoding="utf-8"))
    for relative, digest in manifest["verbatim_files"].items():
        actual = hashlib.sha256((ROOT / relative).read_bytes()).hexdigest()
        if actual != digest:
            raise VendoredSpiaError(
                f"SPIA original altéré : {relative} ({actual} ≠ {digest}) — restaurer la copie "
                f"de {manifest['repo']}@{manifest['commit']}"
            )
    return manifest


def tree_sha256() -> str:
    """Empreinte de l'arbre recopié + cale, pour le lock d'attaque."""
    digest = hashlib.sha256()
    for path in sorted(p for p in ROOT.rglob("*") if p.is_file() and "__pycache__" not in p.parts):
        digest.update(str(path.relative_to(ROOT)).encode())
        digest.update(hashlib.sha256(path.read_bytes()).digest())
    return digest.hexdigest()


def _owned(name: str) -> bool:
    return any(name == prefix or name.startswith(prefix + ".") for prefix in _PREFIXES)


_ATTACK_MODULES = {
    "infer": "src.inference.infer_spia",
    "align": "src.evaluate.gt_vs_llms.align_subject_based_ground_truth",
    "check": "src.evaluate.gt_vs_llms.check_human_labels_gt",
    "ppr": "src.evaluate.privacy.calculate_ipr_cpr",
    "client": "src.llm.client",
}
#: Le scoring ne charge que le calcul CPR/IPR (bibliothèque standard seule).
SCORING_MODULES = {"ppr": "src.evaluate.privacy.calculate_ipr_cpr"}


@contextmanager
def original_spia(modules: dict[str, str] | None = None) -> Iterator[SimpleNamespace]:
    """Modules originaux utiles, chargés depuis la copie vérifiée."""
    verify()
    saved = {name: module for name, module in sys.modules.items() if _owned(name)}
    for name in saved:
        del sys.modules[name]
    sys.path.insert(0, str(ROOT))
    try:
        loaded: dict[str, ModuleType] = {
            alias: importlib.import_module(name)
            for alias, name in (modules or _ATTACK_MODULES).items()
        }
        if "infer" in loaded:
            from anonymisation.attack.spia.parsing import strict_first

            # Liaison locale au module d'inférence : les modules originaux
            # sortent de sys.modules à la fin du contexte, la cale avec eux.
            infer = loaded["infer"]
            infer.parse_subject_profiling = strict_first(infer.parse_subject_profiling)
        yield SimpleNamespace(**loaded)
    finally:
        sys.path.remove(str(ROOT))
        for name in [n for n in sys.modules if _owned(n)]:
            del sys.modules[name]
        sys.modules.update(saved)


__all__ = ["ROOT", "SCORING_MODULES", "VendoredSpiaError", "original_spia", "tree_sha256", "verify"]
