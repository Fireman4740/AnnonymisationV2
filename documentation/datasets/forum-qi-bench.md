# Forum-QI-Bench — corpus forums francophone à construire

| | |
|---|---|
| **Clé interne** | `forum_qi` |
| **Priorité** | **P0** |
| **Benchmark** | B2, B3, B4 |
| **Statut** | **À construire** · fiche v1.0 · 2026-08-30 |

---

## 1. Identité

| Champ | Valeur |
|-------|--------|
| Nom | Indirect-QI Re-identification Benchmark — volet forums |
| Origine | Production propre au projet |
| Type | Synthétique à profil latent |
| Langues | **FR** (primaire), EN (contrôle) |
| Domaine | Forums, communautés en ligne, espaces d'entraide |

## 2. Rôle et priorité

SynthPAI couvre déjà le domaine forums — **mais uniquement en anglais**, avec
des personnes synthétiques calibrées sur des distributions américaines et un
style Reddit.

Ce corpus a donc une raison d'être précise : **le pendant francophone**, avec
une population de référence française et des registres de forums européens
(entraide administrative, communautés professionnelles, forums techniques).

Il sert aussi de **contrôle expérimental** : en gardant le contenu constant
entre FR et EN, on isole l'effet de la langue sur la détection de QI et sur le
risque — un résultat difficilement obtenable autrement.

## 3. Contenu cible

| | Cible |
|---|---|
| Profils latents | **500** |
| Messages | **5 000** (≈ 10 par personne) |
| Threads | **~400** |
| Langue | 80 % FR, 20 % EN (sous-ensemble parallèle) |
| Population de référence | France (INSEE), partagée avec HR-QI-Bench |

### Types de messages

| Type | Part cible |
|------|-----------:|
| Demande d'aide / question | 40 % |
| Réponse / conseil | 30 % |
| Récit d'expérience personnelle | 20 % |
| Message court / réaction | 10 % |

Le troisième type est celui qui porte le plus de QI implicites : c'est le
registre où l'on dit « quand j'ai déménagé pour ma thèse » plutôt que « j'ai
28 ans, je suis doctorant à Lille ».

## 4. Spécificité : le risque cumulé par historique

C'est la caractéristique qui distingue le domaine forums des deux autres.

> Un message isolé est presque toujours anodin. **C'est l'historique complet
> d'un pseudonyme qui ré-identifie.**

Le corpus doit donc rendre mesurable l'effet d'agrégation :

| Granularité | Ce qu'on mesure |
|-------------|-----------------|
| message | QI détectables dans un message isolé |
| thread | QI détectables dans un fil |
| **auteur** | QI détectables dans l'union des messages d'un pseudonyme |

L'écart entre `message` et `auteur` est un **résultat publiable en soi**, et il
justifie une décision de conception : la politique d'anonymisation doit pouvoir
être appliquée **au niveau auteur**, avec un état persistant, et pas seulement
document par document.

> **Exigence à répercuter dans le pipeline** : le moteur de risque doit accepter
> un contexte d'historique (`author_history`), pas seulement un document isolé.
> Voir [SPEC-06 §7](../specifications/SPEC-06-population-et-risque.md).

## 5. Quasi-identifiants du domaine forums

Bloc générique de [SPEC-01](../specifications/SPEC-01-taxonomie-qi.md), enrichi :

âge / tranche d'âge · genre · localisation (ville, région, quartier) · niveau
d'étude · profession · situation familiale · revenu approximatif · santé ·
appartenance associative ou syndicale · pratique sportive ou culturelle rare ·
événements de vie datés (déménagement, soutenance, naissance) · pseudonyme et
style d'écriture · **combinaison localisation × profession × événement daté**.

Deux QI propres au domaine, absents de RH et support :

- **QI stylométriques** — le style d'écriture est lui-même un identifiant. Hors
  périmètre du moteur de risque v1, mais à documenter comme limite connue.
- **QI relationnels** — « mon collègue X qui poste ici aussi » : la structure du
  graphe de conversation est identifiante.

## 6. Voie de construction

**Voie A (synthétique) uniquement**, pour une raison décisive : la voie B
supposerait de collecter des messages de forums réels, donc des données
personnelles publiées par des personnes identifiables, sans base légale évidente
et avec un risque de ré-identification réel lors des expériences d'attaque.

> **Décision** : pas de collecte de forums réels. Si un besoin de réalisme
> apparaît, passer par un corpus déjà publié et licencié pour la recherche,
> jamais par du scraping.

Protocole de génération : [SPEC-05](../specifications/SPEC-05-generation-corpus-synthetiques.md).
Modèle méthodologique : SynthPAI [@yukhymenko2024synthpai].

## 7. Tâches d'utilité associées

| Tâche | Étiquette |
|-------|-----------|
| Classification de thème | catégorie de forum |
| Analyse de sentiment | polarité |
| Modération | contenu problématique oui/non + type |
| Détection de sujet | sujet fin |
| Clustering | groupe de référence |

La modération est la tâche la plus intéressante : elle dépend fortement du
contexte personnel (un message de détresse se reconnaît en partie à des indices
personnels), donc l'anonymisation la dégrade fortement. C'est un bon cas de
**tension privacy-utility irréductible**, honnête à publier.

## 8. Couverture visée

| Besoin | Couvert |
|--------|:-------:|
| QI indirects | ✅ |
| **QI implicites** | ✅ (le domaine où ils dominent) |
| Combinaisons annotées | ✅ |
| Profil latent | ✅ |
| **Agrégation par auteur** | ✅ |
| Population de référence FR | ✅ |
| **Français** | ✅ |
| Sous-ensemble parallèle FR/EN | ✅ |
| Tâches d'utilité | ✅ |
| Texte réel | ❌ (décision assumée) |

## 9. Mapping vers le schéma interne

Produit directement au format SPEC-02 :

- `profiles.jsonl` — `person_id`, attributs, `pseudonym` ;
- `documents.jsonl` — `domain = "forum"`, `author_id`, `thread_id`,
  `position_in_thread`, `timestamp` ;
- `annotations.jsonl` — spans + `expression_mode` (majorité d'`IMPLICIT`) ;
- `combinations.jsonl` — avec `scope` ∈ {`document`, `thread`, `author`} ;
- `tasks.jsonl` — étiquettes d'utilité.

Le champ `Combination.scope` est une extension requise par ce corpus : la même
combinaison n'a pas le même k selon qu'elle est observée dans un message ou
reconstruite depuis un historique.

## 10. Splits et protocole

- Split **par `person_id`**.
- Veiller à ce qu'un thread ne soit pas coupé entre deux splits (sinon le
  contexte conversationnel est amputé) → contrainte de split conjointe
  auteur × thread, à résoudre par affectation gloutonne des threads.
- Trois évaluations obligatoires : message-level, thread-level, author-level.

## 11. Plan de construction

| # | Étape | Sortie |
|---|-------|--------|
| 1 | Réutiliser la population FR de HR-QI-Bench, l'étendre aux attributs de vie | `configs/populations/fr-general.yaml` |
| 2 | Échantillonner 500 profils + pseudonymes | `profiles.jsonl` |
| 3 | Construire ~400 threads, affecter les auteurs | structure de conversation |
| 4 | Générer les messages, avec un ratio élevé de mode `IMPLICIT` | `documents.jsonl` |
| 5 | Dériver les annotations du plan de génération | `annotations.jsonl` |
| 6 | Calculer `k_true` aux trois `scope` | `combinations.jsonl` |
| 7 | Produire le sous-ensemble parallèle EN (même contenu, autre langue) | split `parallel_en` |
| 8 | Étiquettes d'utilité + contrôle humain 5 % | `tasks.jsonl`, rapport |

## 12. Critères d'acceptation

- [ ] 500 profils, ~5 000 messages, ~400 threads.
- [ ] Aucun thread coupé entre splits ; aucun auteur dans deux splits.
- [ ] ≥ 50 % des annotations sont en mode `IMPLICIT` (c'est le point du
      domaine ; un corpus majoritairement explicite raterait sa cible).
- [ ] `k_true` calculé aux trois `scope`, avec
      $k_{author} \leq k_{thread} \leq k_{document}$ vérifié sur 100 % des cas
      (test de cohérence de l'agrégation).
- [ ] Le sous-ensemble parallèle FR/EN a un contenu strictement aligné.
- [ ] Le contrôle humain valide la plausibilité conversationnelle des threads.

## 13. Questions ouvertes

- Faut-il modéliser la stylométrie comme un QI explicite, ou la documenter
  comme limite hors périmètre ? (recommandation : hors périmètre v1, documentée)
- Les QI relationnels (graphe de conversation) doivent-ils entrer dans le calcul
  de k ? Techniquement oui, mais cela ouvre un chantier entier.
- Le sous-ensemble parallèle FR/EN doit-il être traduit automatiquement (risque
  d'artefacts) ou co-généré depuis le même plan (recommandé) ?
