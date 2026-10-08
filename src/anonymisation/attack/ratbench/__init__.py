"""Attaque de ré-identification RAT-Bench (Krčo et al., 2026, arXiv:2602.12806).

Portage du protocole officiel ``imperial-aisp/rat-bench`` au commit
``8e9f03d00cb0559508d8ee86bc743875aa6bcf95`` :

1. un attaquant LLM devine les attributs listés dans ``features`` à partir du
   texte anonymisé (prompt de Staab et al., ``prompts.py``) ;
2. chaque devinette est jugée par règles (``correctness.py``) ;
3. les attributs indirects correctement devinés sont encodés dans les codes
   PUMS 2010 (``encoding.py``) et CorrectMatch (Rocher et al., 2019) estime la
   probabilité de ré-identification correcte dans la population US
   (``risk.py``) ;
4. un profil est ré-identifié si un identifiant direct est juste OU si la
   correctness CorrectMatch atteint 0,2.

Étape **optionnelle et hors ligne interdite** (C1/C2) : elle exige un LLM et
CorrectMatch (Julia). Ses sorties sont figées dans ``attacks.jsonl`` ; le
scoring les relit sans relancer aucun modèle (C5).
"""

OFFICIAL_REPO = "imperial-aisp/rat-bench"
OFFICIAL_COMMIT = "8e9f03d00cb0559508d8ee86bc743875aa6bcf95"
#: Population utilisée par ``compute_reid_risk`` dans le code officiel. La
#: constante ``N = 309 349 689`` du même module n'est PAS celle du chemin de
#: calcul effectif ; on reprend celle qui produit les chiffres publiés.
POPULATION_N = 306_169_200
REID_CORRECTNESS_THRESHOLD = 0.2
#: Nombre de tirages CorrectMatch moyennés par profil (code officiel).
CORRECTMATCH_REPEATS = 10
