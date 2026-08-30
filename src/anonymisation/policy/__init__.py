"""Moteur de politique : risque -> action.

À implémenter en lot L5. Les seuils vivent dans configs/policy/policies.yaml,
jamais en dur. L'algorithme choisit l'action qui maximise
Δrisque / Δutilité_perdue : c'est ce qui distingue une anonymisation pilotée par
le risque d'un masquage aveugle, et ce qui produit une frontière
privacy-utility plutôt qu'un point.
"""
