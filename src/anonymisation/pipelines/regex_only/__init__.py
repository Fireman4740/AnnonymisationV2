"""Pipeline `regex_only` — Baseline regex pure : motifs déclaratifs, décisions SUPPRESS.

Dossier autonome : `system.py` (implémentation), `tests/` (ses tests),
`README.md` (sa notice).
L'import ci-dessous vaut enregistrement dans le registre des systèmes.
"""

from anonymisation.pipelines.regex_only.system import RegexOnlySystem

__all__ = ["RegexOnlySystem"]
