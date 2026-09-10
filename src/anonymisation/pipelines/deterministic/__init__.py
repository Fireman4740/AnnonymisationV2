"""Pipeline `deterministic` — Pipeline 8 étapes de SPEC-10 : motifs + règles QI, politique P0..P4.

Dossier autonome : `system.py` (implémentation), `tests/` (ses tests),
`README.md` (sa notice), `profile.yaml` (son profil d'exécution).
L'import ci-dessous vaut enregistrement dans le registre des systèmes.
"""

from anonymisation.pipelines.deterministic.system import DeterministicSystem

__all__ = ["DeterministicSystem"]
