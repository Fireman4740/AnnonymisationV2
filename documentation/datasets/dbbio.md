# DB-bio

| | |
|---|---|
| **Clé interne** | `dbbio` |
| **Priorité** | **P1** |
| **Benchmark** | B1 (utilité aval), diagnostic pour QI |
| **Statut de la fiche** | Stable · v1.1 · 2026-09-04 |

---

## 1. Identité

| Champ | Valeur |
|-------|--------|
| Nom complet | DB-bio — biographies Wikipedia avec labels d'occupation hiérarchiques |
| Type | **Réel** — biographies Wikipedia authentiques |
| Langue | Anglais |
| Domaine | **Générique**, fortement ancré métier par l'occupation |
| Source | Dépôt interne V1, répertoire `DB-bio/` |

Le corpus canonique est constitué des trois fichiers `train.jsonl`, `val.jsonl`
et `test.jsonl`. Les variantes `train_sft.jsonl` et `train_dpo.jsonl` sont
présentes dans la source V1 mais ne sont pas comptées dans la volumétrie
canonique ci-dessous.

## 2. Rôle et priorité

**Corpus P1 pour la mesure d'utilité aval** et contrôle de la détection de noms
de personnes. Ce n'est pas un corpus d'annotations d'anonymisation à offsets.

1. **Tâche d'utilité aval réelle** : classification hiérarchique d'occupation
   (`l1`/`l2`/`l3`) à partir d'une biographie.
2. **Régression de la dégradation d'utilité** : la même tâche peut être mesurée
   après généralisation, aux trois niveaux de la hiérarchie.
3. **Contrôle de détection** : `wiki_name` et `people` fournissent des chaînes
   de noms candidates, sans vérité terrain de spans.

## 3. Contenu et volumétrie

| Métrique | Valeur |
|----------|--------|
| `train.jsonl` | **1 938 lignes** |
| `val.jsonl` | **243 lignes** |
| `test.jsonl` | **239 lignes** |
| Total canonique | **2 420 lignes** |
| Profils explicites | **0** |
| Langue | Anglais |
| Variantes auxiliaires | `train_sft.jsonl`, `train_dpo.jsonl` — rôle non établi |

### Structure de chaque ligne

| Colonne | Type réel | Contenu |
|---------|-----------|---------|
| `text` | `str` | Biographie Wikipedia |
| `wiki_name` | `str` | Nom/titre Wikipedia avec underscores éventuels |
| `people` | `str` | Une chaîne de nom, **pas une liste et pas des offsets** |
| `l1` | `str` | Niveau 1 de l'ontologie DBpedia ; observé : `Agent` |
| `l2` | `str` | Niveau 2 ; 7 valeurs observées |
| `l3` | `str` | Niveau 3 ; 24 valeurs observées |
| `label` | `str` | Libellé lisible correspondant au niveau 3, avec espaces |
| `word_count` | `int` | Nombre de mots déclaré pour `text` |

## 4. Structure brute et ontologie

- **Niveau document** : une ligne = une biographie.
- **Texte** : `text` est une chaîne complète ; il n'existe pas de liste de
  spans source ni de couple `(start, end)`.
- **Nom** : `people` est une chaîne. Une recherche exacte peut être tentée,
  mais son échec ne peut pas être corrigé par une supposition d'offset.
- **Hiérarchie** : les labels sont des classes **DBpedia**, pas des codes ESCO
  ou ISCO. La structure observée est de la forme `Agent > Artist > Photographer`
  ou `Agent > Athlete > ChessPlayer`.
- **Distribution de la hiérarchie** : `l1` vaut `Agent` dans les 2 420 lignes,
  `l2` comporte 7 valeurs et `l3` 24 valeurs.
- **`label`** : les 24 valeurs sont les libellés lisibles des 24 classes `l3`
  (par exemple `Chess Player` pour `ChessPlayer`).

Audit de localisation, réalisé par recherche insensible à la casse :
`people` apparaît comme sous-chaîne de `text` dans 1 654 lignes sur 2 420 ;
`wiki_name` (underscores remplacés par des espaces) apparaît dans 1 487 lignes.
Ces nombres ne constituent pas des offsets de référence et ne doivent pas être
transformés silencieusement en annotations valides.

## 5. Accès et acquisition

| | |
|---|---|
| Source | Dépôt V1 local : `F:\IA\Anonymisation\eval\datasets\DB-bio\` |
| Fichiers canoniques | `train.jsonl`, `val.jsonl`, `test.jsonl` |
| Variantes | `train_sft.jsonl`, `train_dpo.jsonl` |
| Méthode | Lecture JSONL, une ligne par biographie |
| Prérequis | Aucun accès réseau ; source locale requise |
| Cache local V2 | `data/raw/dbbio/` ou lecture directe depuis V1 |

## 6. Licence et conformité

- Les textes sont des biographies Wikipedia de personnes réelles et
  identifiables.
- La source Wikipedia est sous **CC BY-SA 3.0** ; l'attribution et le partage
  à l'identique doivent être conservés lors d'une redistribution.
- La garde E2 de SPEC-08 s'applique : l'attaquant avec recherche web est
  interdit sur ce corpus. Aucune sortie d'attaquant ne doit exposer une
  identification en clair.

## 7. Couverture

| Besoin | Couvert |
|--------|:-------:|
| Identifiants directs candidats | ✅ (`wiki_name`, `people`) |
| Offsets d'annotation source | ❌ |
| QI indirects liés à l'occupation | ✅ |
| Tâche d'utilité aval | ✅ |
| Hiérarchie d'utilité | ✅ (`l1`/`l2`/`l3`) |
| Multi-documents par auteur | ❌ |
| Population de référence pour $k$ | ❌ |
| Multilingue | ❌ (anglais uniquement) |
| Texte réel | ✅ |
| Variantes SFT/DPO documentées | ◐ (présentes, rôle à établir) |

## 8. Apport pour le projet

1. Mesurer la conservation de la classification d'occupation après
   anonymisation, sans confondre cette utilité avec une métrique de détection.
2. Tester trois grains de généralisation sur une hiérarchie réelle DBpedia.
3. Fournir un corpus réaliste de noms de personnes, tout en imposant la garde
   E2 et l'interdiction de recherche web pour l'attaquant.
4. Exposer la limite importante des listes de noms non localisées : une
   recherche dans `text` est une procédure de génération de candidats, pas une
   vérité terrain d'offsets.

## 9. Limites et pièges

| Limite | Conséquence |
|--------|-------------|
| `people` est une chaîne, non une liste d'offsets | Toute localisation doit être une étape explicite et auditée ; aucun span source n'est garanti. |
| Personnes réelles identifiées | Garde E2 stricte ; attaquant web interdit. |
| Une biographie par ligne | Pas d'agrégation multi-documents par auteur. |
| Ontologie DBpedia | Les labels ne doivent pas être interprétés comme ESCO/ISCO sans table de correspondance externe. |
| Anglais uniquement | Aucune mesure FR. |
| Une occurrence `wiki_name` recouvre `train` et `test` (`Artie_Lange`) | La séparation n'est pas démontrée sans fuite ; ce recouvrement doit être traité ou explicitement exclu des scores concernés. |
| Petite hiérarchie (`l1 = Agent`, 7 `l2`, 24 `l3`) | Les résultats ne représentent pas toute la distribution des métiers. |

> **Piège méthodologique** : DB-bio est d'abord un benchmark de **régression
> d'utilité**. Il ne faut pas présenter une recherche de noms dans `text` comme
> une vérité terrain d'anonymisation.

## 10. Mapping vers le schéma interne

| Objet DB-bio | Objet interne | Mapping |
|--------------|---------------|---------|
| ligne | `Document` | `domain = "generic"`, `language = "en"`, `meta.source_split` |
| `text` | `Document.text` | Biographie brute |
| `wiki_name` | `Document.meta.wiki_name` | Chaîne candidate, sans offset garanti |
| `people` | `Document.meta.people` | Chaîne candidate, sans offset garanti |
| `l1` / `l2` / `l3` | `TaskLabel` ou cible d'utilité | Hiérarchie DBpedia conservée telle quelle |
| `label` | cible d'utilité lisible | Libellé associé au niveau `l3` |

Aucune `Annotation` `DIR_NAME` ne doit être fabriquée à partir d'une simple
chaîne absente du texte. Une future localisation pourra produire des annotations
avec offsets seulement lorsque la recherche et la règle de résolution auront été
spécifiées et validées ; les échecs doivent rester visibles.

### Hiérarchie d'utilité

Le contrat de tâche recommandé conserve les trois niveaux dans un même enregistrement :

```json
{
  "doc_id": "dbbio:train:000001",
  "task": "occupation",
  "label": {"l1": "Agent", "l2": "Athlete", "l3": "ChessPlayer"},
  "label_display": "Chess Player",
  "label_type": "dbpedia_hierarchy"
}
```

La conversion vers ESCO/ISCO n'est pas autorisée sans source externe et table
de correspondance versionnée.

## 11. Splits et protocole

Les splits officiels de la source sont conservés :

| Split | Documents |
|-------|-----------:|
| `train` | 1 938 |
| `val` | 243 |
| `test` | 239 |

Total : **2 420** documents. La granularité est document-level. Un audit de
`wiki_name` trouve un recouvrement `train`/`test` pour `Artie_Lange`; le protocole
ne doit donc pas déclarer une absence de fuite avant décision sur ce doublon.
Les variantes SFT/DPO restent hors du protocole canonique tant que leur rôle et
leur éventuel recouvrement ne sont pas établis.

## 12. Plan d'implémentation de l'adaptateur

| # | Étape | Sortie |
|---|-------|--------|
| 1 | Charger `train`/`val`/`test` et valider les 8 champs réels | 2 420 documents |
| 2 | Conserver `wiki_name` et `people` comme chaînes candidates | métadonnées sans offsets inventés |
| 3 | Définir une politique de localisation exacte/fuzzy, avec gestion des échecs | contrat d'annotation |
| 4 | Extraire les vocabulaires `l1`/`l2`/`l3` et la table d'affichage `label` | hiérarchie DBpedia |
| 5 | Décider le contrat de tâche hiérarchique | `tasks.jsonl` ou cible équivalente |
| 6 | Fixer checksum, volumétrie et splits au manifeste | `configs/datasets/dbbio.yaml` |
| 7 | Implémenter et enregistrer `DBBioAdapter` | adaptateur B-6 |
| 8 | Valider l'absence d'offsets fabriqués et la garde E2 | validation + rapport |

## 13. Critères d'acceptation de la fiche

- [x] `train`/`val`/`test` reportés avec les volumes **1 938 / 243 / 239**.
- [x] Le total canonique **2 420** est explicite.
- [x] Les champs réels (`text`, `wiki_name`, `people`, `l1`, `l2`, `l3`,
      `label`, `word_count`) sont documentés.
- [x] `people` est documenté comme chaîne sans offsets.
- [x] `l1`/`l2`/`l3` sont documentés comme ontologie DBpedia, pas ESCO/ISCO.
- [x] Le recouvrement `Artie_Lange` train/test est signalé.
- [ ] L'adaptateur B-6 et la localisation des noms restent à implémenter.

## 14. Questions ouvertes

- Quel est le rôle exact de `train_sft.jsonl` et `train_dpo.jsonl`, et quels
  recouvrements ont-ils avec `train.jsonl` ?
- Le recouvrement `Artie_Lange` entre train et test est-il un doublon source
  intentionnel ou une fuite à exclure du protocole ?
- Quelle population de référence des occupations permettrait de calculer $k$ ?
- Quelle politique validée doit localiser `wiki_name`/`people` lorsque la chaîne
  n'est pas une sous-chaîne exacte de `text` ?
