"""Pipeline `llm_full` — Anonymisation intégrale par LLM, un appel par document.

Dossier autonome : `system.py` (implémentation), `tests/` (ses tests),
`README.md` (sa notice), `profile.yaml` (son profil d'exécution).
L'import ci-dessous vaut enregistrement dans le registre des systèmes.
"""

from anonymisation.pipelines.llm_full.system import LlmFullSystem

__all__ = ["LlmFullSystem"]
