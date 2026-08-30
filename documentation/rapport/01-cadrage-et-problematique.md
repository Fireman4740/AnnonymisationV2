# 01 — Cadrage et problématique

| | |
|---|---|
| **Statut** | Stable |
| **Version** | 1.0 |
| **Date** | 2026-08-30 |

---

## 1. Périmètre fixé

| Dimension | Choix |
|-----------|-------|
| Domaines | **RH**, **forums**, **tickets support** |
| Langues | **Multilingue**, priorité FR + EN, extension DE/ES |
| Modèles | **Locaux, < 30 B paramètres** (contrainte de souveraineté et de coût) |
| Traitement | **Anonymisation automatique** (pas de validation humaine dans la boucle nominale) |
| Sortie | **Score de risque explicite** et **politique d'anonymisation configurable** |

Ces cinq choix contraignent fortement les décisions qui suivent : ils excluent
les approches purement API-based, imposent une évaluation coût / latence, et
imposent que le score de risque soit **interprétable et calibré**, pas seulement
discriminant.

## 2. Ce que le problème n'est pas

Le problème n'est **pas** de la détection de PII. Un système de PII fait :

```
texte → PERSON / EMAIL / PHONE / ADDRESS → masquage
```

Ce pipeline est mature et largement résolu (voir
[02-etat-de-l-art §6](02-etat-de-l-art.md#6-openpii--ai4privacy)). Il échoue
totalement sur :

> « je suis le seul doctorant de mon équipe à travailler sur ce sujet »

Aucun span de PII n'y est détectable, et pourtant l'énoncé est potentiellement
identifiant à lui seul.

## 3. Formulation du problème

### 3.1 Chaîne de traitement visée

```
texte
  → informations personnelles explicites et implicites
  → quasi-identifiants individuels (QI)
  → combinaisons de QI
  → estimation de la population compatible
  → probabilité de ré-identification
  → décision d'anonymisation
  → validation par attaque
```

### 3.2 Formalisation

Soit un document $d$ produit par un individu $i$ appartenant à une population de
référence $P$. Le système extrait un ensemble de contraintes attributaires :

$$
Q(d) = \{q_1, q_2, \dots, q_m\}
$$

Exemple, pour « j'ai moins de 30 ans et je suis doctorant et je cherche comment
mettre un arrêt maladie » :

$$
Q = \{\text{âge} < 30,\ \text{doctorant},\ \text{démarche administrative RH}\}
$$

La **classe d'équivalence** de $Q$ dans $P$ est :

$$
\mathrm{EC}_P(Q) = \{p \in P : Q(p) = Q\}
$$

et sa cardinalité :

$$
k(Q) = |\mathrm{EC}_P(Q)|
$$

Dans le modèle de risque *prosecutor* (l'attaquant sait que la cible est dans le
jeu de données), le risque de ré-identification est approché par :

$$
R(Q) \approx \frac{1}{k(Q)}
$$

Le danger ne vient donc pas de l'identifiabilité de chaque $q_j$ pris isolément,
mais de la **taille de l'intersection**. C'est un problème de **linkage risk** et
d'**inference risk**, pas de reconnaissance d'entités nommées.

> ⚠️ Cette approximation $R \approx 1/k$ est un **point de départ**, pas le modèle
> final. Elle suppose une population de référence complète et une indépendance
> des attributs — deux hypothèses fausses en pratique. Voir
> [SPEC-06](../specifications/SPEC-06-population-et-risque.md) pour le modèle
> retenu (k-map, risque populationnel, estimation par copule pour les populations
> incomplètes).

### 3.3 Conséquence méthodologique

TAB [@pilan2022tab] a établi que le rappel classique de spans **ne suffit pas** à
mesurer la protection : tous les identifiants n'ont pas le même poids, et une
même personne peut être mentionnée plusieurs fois dans un document. La métrique
d'évaluation doit donc opérer au niveau **entité** et **combinaison**, pas au
niveau token.

## 4. Modèle de menace

Trois adversaires sont considérés, de force croissante
(détail : [SPEC-08](../specifications/SPEC-08-attaquants.md)) :

| Niveau | Adversaire | Capacités | Usage |
|--------|-----------|-----------|-------|
| **A** | LLM local 7–14 B | Inférence sur le seul texte anonymisé, pas d'accès externe | Benchmark quotidien, mesure du risque résiduel hors ligne |
| **B** | LLM plus puissant | Meilleure inférence d'attributs implicites | Vérifie que la protection n'est pas seulement valable contre un petit attaquant |
| **C** | Agent avec recherche web | Chaînage d'indices faibles avec des sources publiques auxiliaires | Stress-test final ; AURA [@li2026aura] et InferLink [@ko2026inferlink] montrent que ce niveau change la nature de la menace |

Hypothèse retenue par défaut pour les mesures publiées : **attaquant A** pour le
suivi continu, **attaquant C** pour les résultats de robustesse.

## 5. Contraintes de conception

| Contrainte | Implication |
|------------|-------------|
| Modèles < 30 B, exécution locale | Budget latence et VRAM à mesurer et publier (voir SPEC-07 §5) |
| Anonymisation automatique | Aucun humain pour rattraper un faux négatif → **le rappel QI prime sur la précision QI** |
| Score de risque explicite | Le score doit être **calibré** (ECE, Brier), pas seulement ordonnant |
| Politique configurable | Les seuils risque → action sont des paramètres, pas des constantes codées en dur |
| Multilingue | Toute métrique doit être déclinable **par langue** |
| Multi-domaines | Toute métrique doit être déclinable **par domaine** (RH / forum / support) |

## 6. Critère de succès du projet

Le système n'est **pas** évalué par un F1. Il est évalué par un **point de
fonctionnement** sur le plan privacy × utility :

| Politique | Re-ID Risk ↓ | Utility Retention ↑ | Latence |
|-----------|-------------:|--------------------:|--------:|
| P0 (permissive) | … | … | … |
| P1 | … | … | … |
| P2 | … | … | … |
| P3 | … | … | … |
| P4 (agressive) | … | … | … |

Publier une courbe, pas un point. Voir
[SPEC-07 §6](../specifications/SPEC-07-metriques.md#6-le-privacy-utility-operating-point).

## 7. Questions de recherche

Le projet sépare nettement **quatre questions** que la littérature confond souvent :

1. **Détection** — le système repère-t-il les informations qui peuvent contribuer
   à l'identification ? → *Contribution A*, métriques de niveau 1.
2. **Combinaison** — comprend-il que plusieurs QI forment un ensemble dangereux ?
   → *Contribution A*, métrique **QICR**, niveau 2.
3. **Résistance** — le texte anonymisé résiste-t-il réellement à une attaque de
   ré-identification ? → *Contribution C*, métrique **R_succ**, niveau 4.
4. **Utilité** — que reste-t-il d'exploitable après anonymisation ?
   → *Contribution C*, **Utility Retention**, niveau 5.

Entre 2 et 3 s'intercale la question de l'**estimation du risque** lui-même
(*Contribution B*, niveau 3) : transformer une collection d'indices textuels en
une probabilité calibrée.

## 8. Vocabulaire

Voir [`../annexes/glossaire.md`](../annexes/glossaire.md).

Trois distinctions à ne jamais confondre dans ce projet :

- **Identifiant direct** vs **quasi-identifiant** : le premier identifie seul, le
  second seulement en combinaison.
- **QI explicite** vs **QI implicite** : « j'ai 28 ans » vs « j'ai soutenu ma
  thèse l'an dernier ». Le second est le cas difficile
  ([@krco2026ratbench] montre qu'il reste très mal traité).
- **Divulgation d'identité** (linkage) vs **divulgation d'attribut** (inference) :
  retrouver *qui* vs retrouver *quoi* sur une personne déjà localisée.
