"""Pipeline `redact_all` — Ancre S2 — supprime tout (borne haute de protection).

Dossier autonome : `system.py` (implémentation), `tests/` (ses tests),
`README.md` (sa notice).
L'import ci-dessous vaut enregistrement dans le registre des systèmes.
"""

from anonymisation.pipelines.redact_all.system import RedactAllSystem

__all__ = ["RedactAllSystem"]
