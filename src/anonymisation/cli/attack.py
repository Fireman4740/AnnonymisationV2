"""Commande ``anonv2 attack`` : étapes figées optionnelles (C2).

Séparée de ``score`` par construction : l'attaque appelle un LLM et
CorrectMatch ; ``score`` ne fait que relire ``attacks.jsonl`` (C5).
"""

from __future__ import annotations

import sys
from pathlib import Path

from anonymisation.llm.config import LlmConfigError, load_backends_config

REPO_ROOT = Path(__file__).resolve().parents[3]
PROCESSED_ROOT = REPO_ROOT / "data" / "processed"


def cmd_attack(run: str, attacker: str, backend: str | None, workers: int | None) -> int:
    from anonymisation.attack.ratbench.risk import CorrectMatchUnavailable
    from anonymisation.attack.ratbench.runner import AttackError, run_attack
    from anonymisation.attack.spia.runner import SpiaAttackError, run_spia_attack
    from anonymisation.attack.spia.vendored import VendoredSpiaError
    from anonymisation.schema.integrity import DataIntegrityError

    if attacker not in ("ratbench", "spia"):  # argparse le garantit ; défense en profondeur
        print(f"Erreur d'usage : attaquant inconnu {attacker!r}", file=sys.stderr)
        return 2
    try:
        role = f"attacker_{attacker}"
        name = backend or load_backends_config().roles.get(role)
        if not name:
            raise LlmConfigError(f"aucun backend : passer --backend ou définir le rôle {role}")
        if attacker == "ratbench":
            lock = run_attack(Path(run), backend=name, processed_root=PROCESSED_ROOT, workers=workers)
        else:
            lock = run_spia_attack(Path(run), backend=name, workers=workers)
    except (AttackError, SpiaAttackError, VendoredSpiaError, DataIntegrityError,
            CorrectMatchUnavailable, LlmConfigError) as exc:
        print(f"Erreur d'usage : {exc}", file=sys.stderr)
        return 2
    print(
        f"attack {attacker} : {lock['documents']} document(s), {lock['documents_error']} en erreur "
        f"({lock['error_rate']:.1%}) — attaquant {lock['attacker']['model']}"
    )
    if not lock["publishable"]:
        print("AVERTISSEMENT BLOQUANT : plus de 5 % de documents en erreur (C4).")
        return 1
    return 0
