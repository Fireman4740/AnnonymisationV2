"""Pipeline `oracle_mask` — ancre oracle : supprime les mentions gold ancrées.

Dossier autonome : `system.py` (implémentation), `tests/` (ses tests),
`README.md` (sa notice).
L'import ci-dessous vaut enregistrement dans le registre des systèmes.
"""

from anonymisation.pipelines.oracle_mask.system import OracleMaskSystem

__all__ = ["OracleMaskSystem"]
