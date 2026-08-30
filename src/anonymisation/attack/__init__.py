"""Attaquants A / B / C (SPEC-08).

GARDES NORMATIVES à implémenter en code, pas seulement en documentation :
* E1 — l'attaquant C (recherche web) ne démarre que si le manifeste du dataset
  porte `structure.synthetic: true` ;
* E2 — il refuse TAB, IPI/MIMIC, JobStack, MEDDOCAN, MultiCoNER (personnes
  réelles) ;
* E3/E4 — aucune sortie identifiant une personne réelle n'est journalisée ;
  sur corpus réels, seuls des compteurs sont conservés.
"""
