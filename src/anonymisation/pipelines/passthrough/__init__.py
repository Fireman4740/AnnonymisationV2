"""Pipeline `passthrough` — Ancre S1 — ne modifie rien (borne basse de protection).

Dossier autonome : `system.py` (implémentation), `tests/` (ses tests),
`README.md` (sa notice).
L'import ci-dessous vaut enregistrement dans le registre des systèmes.
"""

from anonymisation.pipelines.passthrough.system import PassthroughSystem

__all__ = ["PassthroughSystem"]
