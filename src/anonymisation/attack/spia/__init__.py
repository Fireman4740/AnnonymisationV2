"""Protocole d'inférence adversariale SPIA (Oh et al., 2026), code original.

``original/`` contient le code de ``maisonOP/spia@3fa78a1`` (licence MIT)
recopié tel quel — empreintes dans ``original/ORIGINAL.json``, vérifiées au
chargement — à l'exception du transport LLM (``src/llm/client.py``).
:mod:`anonymisation.attack.spia.runner` enchaîne ses étapes et fige leurs
sorties ; le scoring recalcule CPR/IPR avec ``calculate_ipr_cpr`` original sans
relancer aucun modèle (C5).
"""

OFFICIAL_REPO = "maisonOP/spia"
OFFICIAL_COMMIT = "3fa78a1b3c75788c6294f40024fc79e1ef42923f"
