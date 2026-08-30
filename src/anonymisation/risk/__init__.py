"""Moteur de risque : k combinatoire et modèles de risque.

À implémenter en lot L3. Spécification :
documentation/specifications/SPEC-06-population-et-risque.md

Rappel des points structurants :
* quatre modèles (prosecutor, journalist, marketer, copula) ;
* le défaut pour les corpus FR est `copula` — l'approximation R = 1/k n'est
  valide que si la population est complète, ce qui n'est jamais le cas avec des
  données publiques agrégées ;
* le moteur produit un INTERVALLE [k_low, k_high], pas une valeur ponctuelle,
  et la décision se prend sur la borne haute du risque ;
* il accepte un état d'historique (author_history) : traiter chaque document
  indépendamment sous-estime systématiquement le risque sur les forums.
"""
