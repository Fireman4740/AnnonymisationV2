# SupportTicketsReal

| | |
|---|---|
| **Clé interne** | `supporttickets` |
| **Priorité** | **P0** |
| **Benchmark** | B2, B4 |
| **Statut de la fiche** | Stable · v1.0 · 2026-08-30 |

---

## 1. Identité

| Champ | Valeur |
|-------|--------|
| Nom complet | SupportTicketsReal — Corpus réel de tickets de support multilingues |
| Type | **Réel** — tickets d'assistance client authentiques |
| Langue | Multilingue (détecté via colonne `language`) |
| Domaine | **Support** (assistance technique client) |
| Source | Dépôt interne V1 |

## 2. Rôle et priorité

**L'unique corpus P0 du domaine support et la source exclusive de la tâche d'utilité
« routage »** ([SPEC-07 §6.B](../specifications/SPEC-07-metriques.md)).
C'est un corpus réel (non synthétique) avec une volumétrie opérationnelle (61 765
tickets) et une structure multi-domaine au sein d'un seul corpus (via la colonne
`queue`).

**Atout structurel** : la colonne `queue` fournit **la tâche d'utilité de
référence** — routage d'un ticket vers une équipe — directement mesurable et
opérationnellement significative. Cela permet de valider que l'anonymisation ne
dégradait pas une tâche réelle du pipeline support.

## 3. Contenu et volumétrie

| Métrique | Valeur |
|----------|--------|
| Tickets | **61 765** |
| Colonnes | 16 |
| Taille disque | 24 Mo (Parquet) |
| Langues | Multiple (voir `language`) |

### Structure des colonnes

| Colonne | Type | Rôle |
|---------|------|------|
| `subject` | `str` | Sujet du ticket |
| `body` | `str` | Corps du message, texte complet |
| `answer` | `str` | Réponse du support |
| `type` | `str` | Catégorie de type (à documenter : valeurs possibles) |
| `queue` | `str` | **Équipe/file de routage cible** (tâche d'utilité) |
| `priority` | `str` | Niveau de priorité (tâche d'utilité secondaire) |
| `language` | `str` | Langue détectée du ticket |
| `version` | `str` | **Version du produit/logiciel** → QI technique |
| `tag_1` à `tag_8` | `str \| null` | Tags libres (à documenter) |

## 4. Structure brute

Un document par ligne du Parquet. Chaque ticket est une **entité atomique** — on ne
dispose pas de profil latent d'auteur ni d'historique multi-ticket consolidé.

Chaque colonne textuelle (`subject`, `body`, `answer`) peut contenir des QI :
- **Directs** (noms, emails, numéros)
- **Indirects** (version produit → `SUP_VERSION`, localisation implicite via fuseau…)
- **Implicites** (détection d'environnement technique, rôle via le contexte)

## 5. Accès et acquisition

| | |
|---|---|
| Source | Dépôt V1 local : `F:\IA\Anonymisation\eval\datasets\SupportTicketsReal\train.parquet` |
| Méthode | Chargement via `pandas.read_parquet()` ou `pyarrow` |
| Prérequis | Aucun (accès local immédiat) |
| Cache local | `data/raw/supporttickets/` ou lecture directe depuis V1 |

## 6. Licence et conformité

- **Personnes réelles** → corpus soumis au RGPD. Aucune sortie d'attaquant ne DOIT
  être journalisée.
- **Garde E2 obligatoire** ([SPEC-08](../specifications/SPEC-08-attaquants.md)) : l'attaquant avec
  recherche web est **interdit** sur ce dataset. Toute attaque doit rester intra-corpus.
- Licence source : à confirmer (consulter le manifeste V1)

## 7. Couverture

| Besoin | Couvert |
|--------|:-------:|
| Identifiants directs (noms, emails) | ✅ |
| QI techniques du support | ✅ |
| QI implicites (inférence) | ◐ |
| Tâche d'utilité « routage » | ✅ |
| Tâche d'utilité « priorité » | ✅ |
| Multi-documents par auteur | ❌ (pas de profil auteur) |
| Population de référence | ❌ |
| Multilingue | ✅ |
| Texte réel | ✅ |

## 8. Apport pour le projet

1. **L'unique source de la tâche d'utilité « routage »**, qui valide
   opérationnellement l'approche (SPEC-07 §6.B).
2. **Un corpus réel et opérationnel**, contrairement aux synthétiques. Les résultats
   ont une crédibilité immédiate.
3. **La multilingualité** naturelle permet de mesurer la dégradation d'utilité par
   langue.
4. **Un domaine absent des autres corpus** — domaine support, donc un tiers du
   périmètre du projet.
5. **Détection de QI techniques** (`version` explicite, mais aussi OS, device,
   timezone implicites) — cas d'usage réel du secteur.

## 9. Limites et pièges

| Limite | Conséquence |
|--------|-------------|
| Pas d'annotations de spans | Aucune vérité terrain d'offset. Détection non supervisée obligatoire ; aucune métrique F1 de détection. |
| Pas de profil latent d'auteur | Pas de mesure d'agrégation (author-level risk). Évaluation au niveau document seulement. |
| Personnes réelles | Garde E2 : aucune sortie d'attaquant en clair, aucune recherche web. Limite l'attaque à une inférence intra-corpus. |
| Structure plate (un ticket = un document) | Pas de thread conversationnel, pas de richesse relationnelle comme dans les forums. |
| Multilingue sans annotation de langue au niveau span | La langue est colonne-level, pas token-level. |

> **Piège majeur** : c'est une source de tâche d'utilité, pas une source de
> vérité terrain pour le QI. Ne pas confondre — un ticket bien routé n'est pas
> un ticket bien anonymisé.

## 10. Mapping vers le schéma interne

| Objet SupportTicketsReal | Objet interne | Mapping |
|---------------------------|---------------|---------|
| ligne (ticket) | `Document` | `domain = "support"`, `language` depuis colonne, `author_id = null` (pas de profil) |
| `subject` + `body` + `answer` | `Document.text` | Concaténé avec délimiteurs explicites ou stocké comme trois colonnes ? (à fixer) |
| `queue` | `tasks.jsonl` | `task = "ticket_routing"`, `label = queue_value`, `label_type = "single"` |
| `priority` | `tasks.jsonl` | `task = "ticket_priority"`, `label = priority_value` |
| `version` | `Annotation` ou détection | Code QI `SUP_VERSION` → à détecter automatiquement dans `body` |
| `language` | `Document.language` | ISO 639-1 depuis la colonne |
| `type` | `tasks.jsonl` (optionnel) | `task = "ticket_type"` si réutilisable. Valeurs à documenter. |

### Note critique

Le corpus ne fournit pas de vérité terrain d'annotation (spans). Toute annotation
de QI DOIT être générée par :
- Une détection automatique (NER, regex, heuristiques) ;
- Validation manuelle partielle ou complète (à fixer au manifeste) ;
- Population de référence (support-parc) pour le calcul de $k$.

## 11. Splits et protocole

**Pas de split officiel fourni.** Proposition :

- **Train** : 70 % des tickets (43 235)
- **Dev** : 15 % (9 265)
- **Test** : 15 % (9 265)
- Seed : 42
- **Stratification recommandée** : par `queue` (maintenir la distribution des files
  dans chaque split) et par `language` (éviter d'avoir une langue dans un seul split).

**Granularité** : document-level (un ticket = une unité d'évaluation indépendante).

## 12. Plan d'implémentation de l'adaptateur

| # | Étape | Sortie |
|---|-------|--------|
| 1 | Charger depuis Parquet V1, inspecter schéma et volumétrie réelle | note §4 et §3 |
| 2 | Vérifier les valeurs uniques de `language`, `queue`, `priority`, `type` | documentation valeurs |
| 3 | Concaténer/normaliser les colonnes textuelles, fixer les offsets | `text` normalisé |
| 4 | Fixer licence, checksum, volumétrie dans le manifeste | `configs/datasets/supporttickets.yaml` |
| 5 | Implémenter `SupportTicketsAdapter` | `src/anonymisation/datasets/supporttickets.py` |
| 6 | Émettre `documents.jsonl` + `tasks.jsonl` | `data/processed/supporttickets/` |
| 7 | Configurer la population de référence (`support-parc-*`) | `configs/populations/` |
| 8 | (Optionnel) Exécuter détection NER baseline sur `body` et annoter spans | `annotations.jsonl` |

## 13. Critères d'acceptation

- [ ] 61 765 documents chargés avec `domain = "support"`.
- [ ] Colonne `language` mappée vers ISO 639-1 valide ; pas de valeur null.
- [ ] `queue` non null pour tous les documents ; valeurs uniques documentées.
- [ ] Split train/dev/test sans fuite (aucun ticket dans deux splits).
- [ ] `tasks.jsonl` produit avec au moins `ticket_routing` et `ticket_priority`.
- [ ] Toute personne réelle identifiée en clair dans `subject` ou `body` est
      masquée (politesse préalable, avant toute anonymisation).
- [ ] Aucune sortie d'attaquant en clair n'apparaît dans les logs ou résultats
      (garde E2).

## 14. Questions ouvertes

- Quelle est la licence exacte du corpus ? Peut-il être redistribué sans accord
  tiers ?
- Comment sont structurées les trois colonnes textuelles (`subject`, `body`,
  `answer`) ? Sont-elles contiguës, ou à traiter séparément ?
- Existe-t-il une colonne d'identifiant de client/utilisateur qui pourrait
  servir à construire un profil latent ?
- Quelles sont les valeurs réelles et distributions de `type`, `queue` et
  `priority` ? Sont-elles équilibrées ou très skewed ?
- `answer` contient-il une signature ou un nom d'agent ? À masquer systématiquement ?
- Une population de référence « support-parc » (clients/organisations réels du
  domaine) est-elle disponible pour le calcul de $k$ ?
