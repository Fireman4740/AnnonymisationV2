# Corpus QI français

| | |
|---|---|
| **Clé interne** | `quasifr` |
| **Priorité** | **P0** |
| **Benchmark** | B2 |
| **Statut de la fiche** | Stable · v1.1 · 2026-09-04 |

---

## 1. Identité

| Champ | Valeur |
|-------|--------|
| Nom complet | Corpus QI français — Annotations de quasi-identifiants en français |
| Type | **Annotées** — corpus gold d'évaluation |
| Langue | Français |
| Domaine | **Générique** (textes professionnels et personnels mixtes) |
| Source | Dépôt interne V1 |

## 2. Rôle et priorité

**L'unique source de quasi-identifiants annotés en français**, point de passage
obligatoire pour l'évaluation du pipeline sur la langue FR. C'est à la fois :

1. **Un corpus de mise au point** : petit, annoté manuellement, donc fiable, pour
   vérifier que le pipeline fonctionne sur du texte réel français.
2. **Une source de vérité terrain** : offsets réels, labels SPEC-01, coréférence,
   et **justification du risque** (`risk_note`) — ce qui manque à presque tous les
   autres corpus.
3. **Un benchmark FR étalon** : tout résultat sur le français DOIT être rapporté
   par rapport à ce corpus.

Sans ce corpus, aucune évaluation FR n'est possible.

## 3. Contenu et volumétrie

| Métrique | Valeur |
|----------|--------|
| `anonymization_dataset.json` | **31 exemples / 295 annotations** |
| `hard_quasi_id_dataset.json` | **40 exemples / 126 annotations** |
| `max_anonymization_dataset.json` | **1 exemple / 6 annotations** |
| Total | **72 exemples / 427 annotations** |
| Types source | **35** |
| Niveaux | L1 (1), L2 (11), L3 (29), L4 (25), L4-max-destructive (6) |
| `risk_score` observé | **10–100** |
| Langues observées | **en (22), es (13), fr (24), it (13)** |
| Annotations | Offsets caractères, `coref_id`, `risk_note`, `replacement` |

### Structure de chaque fichier JSON

Trois fichiers, même structure :
- `anonymization_dataset.json` : cas standard d'anonymisation
- `hard_quasi_id_dataset.json` : cas difficiles (implicite, coréférence complexe)
- `max_anonymization_dataset.json` : couvrage maximal, même coréférence distante

Chacun contient un objet JSON avec clé `examples` : liste d'exemples.

### Exemple réel annoté

```
Texte : "L'ancien CEO de la startup qui a inventé le distributeur de croquettes 
connecté en 2018 à Nantes, maintenant consultant en IA pour le secteur portuaire, 
a demandé un accès VPN."

Annotations :
  1. "ancien CEO de la startup qui a inventé le distributeur de croquettes connecté" 
     → type: QUASI_ID
     → replacement: [ROLE_FOUNDER_UNIQUE]
     → risk_note: "Description de poste unique via un produit spécifique"
     → coref_id: "person_1"
  
  2. "consultant en IA pour le secteur portuaire"
     → type: QUASI_ID
     → replacement: [ROLE_CONSULTANT_GENERIC]
     → risk_note: "Rôle actuel restreint + domaine spécialisé"
     → coref_id: "person_1" (même personne)
  
  3. "2018"
     → type: DATE
     → (pas replacé? ou [DATE_YEAR])
     → coref_id: "event_1"
```

### Structure formelle d'un exemple

```json
{
  "id": "<string>",
  "langue": "FR",
  "original_text": "<texte complet>",
  "annotations": [
    {
      "type": "QUASI_ID" | "DATE" | "<autre>",
      "start": <int>,
      "end": <int>,
      "text": "<span exact>",
      "replacement": "<token générique, ex. [ROLE_FOUNDER_UNIQUE]>",
      "coref_id": "<string ou null>",
      "risk_note": "<justification du risque>"
    }
  ]
}
```

## 4. Structure brute

- **Niveau document** : chaque exemple est un document textuel court à moyen
  (quelques phrases à un paragraphe).
- **Niveau annotation** : offsets caractères ; six offsets étaient incohérents
  dans `max_anonymization_dataset.json`/`ticket_001`. Les six ont une occurrence
  unique et sont ré-ancrés de façon déterministe ; aucun offset ambigu ou sans
  occurrence n'a été rencontré.
- **Niveau coréférence** : les annotations portent un `coref_id` global, mappé
  vers `Annotation.entity_id`.
- **Niveau risque** : chaque annotation porte une justification `risk_note` et
  un `replacement` source.

Les trois fichiers ont un recouvrement d'identifiants : `ticket_001` existe dans
`anonymization_dataset.json` et `max_anonymization_dataset.json`. Le pivot
qualifie donc chaque `doc_id` par le nom du fichier. Les types techniques et
`COREF` sont conservés sous le code explicite `IGNORED` ; aucune annotation
source n'est filtrée silencieusement.

Les annotations ne constituent pas un profil latent explicite, mais elles
permettent d'en reconstruire un pour une analyse ultérieure.

## 5. Accès et acquisition

| | |
|---|---|
| Source | Dépôt V1 local : `F:\IA\Anonymisation\eval\datasets\data\` |
| Fichiers | `anonymization_dataset.json`, `hard_quasi_id_dataset.json`, `max_anonymization_dataset.json` |
| Méthode | Chargement via `json.load()` |
| Prérequis | Aucun (accès local immédiat) |
| Cache local | `data/raw/quasifr/` ou lecture directe depuis V1 |

## 6. Licence et conformité

- **Textes synthétisés ou remaniés** → pas de personnes réelles, aucune
  contrainte RGPD.
- Licence source : à confirmer (consulter le manifeste V1)

## 7. Couverture

| Besoin | Couvert |
|--------|:-------:|
| Identifiants directs (noms) | ◐ (peut être masqué dans les textes) |
| QI génériques | ✅ |
| QI implicites | ✅ |
| Coréférence | ✅ |
| Justification du risque | ✅ |
| Offsets réels | ✅ |
| Multi-documents par personne | ❌ (document-level seulement) |
| Population de référence | ❌ |
| Multilingue | ◐ — `en`, `es`, `fr`, `it` observés |
| Volumétrie d'entraînement | ❌ (corpus d'évaluation, trop petit) |

## 8. Apport pour le projet

1. **La source de QI annotés en français**, indispensable pour l'évaluation FR,
   contient aussi des exemples en anglais, espagnol et italien.
2. **Offsets réels et coréférence**, ce qui permet de mesurer la précision de la
   détection et la couverture entity-level.
3. **Justifications (`risk_note`)**, utiles pour distinguer attribut et simple
   mécanisme de déduction (voir l'annexe de couverture taxonomique).
4. **Cas difficiles (`hard_quasi_id`)**, qui exposent l'inférence implicite.

## 9. Limites et pièges

| Limite | Conséquence |
|--------|-------------|
| Très petit volume | Pas d'entraînement possible. Corpus d'évaluation et de mise au point uniquement. |
| Document-level seulement | Pas de mesure d'agrégation (author-level). |
| Pas de profil latent explicite | La population de référence FR doit être construite séparément pour calculer $k$. |
| Langues multiples dans les fichiers | Les comparaisons FR/EN doivent être rapportées séparément. |

> **Piège** : ce corpus est petit et bien annoté — il peut sembler "facile". Or
> les cas difficiles (`hard_quasi_id`) sont intentionnellement implicites. Ne pas
> s'étonner d'une F1 basse sur ce sous-ensemble ; c'est le signal attendu.

## 10. Mapping vers le schéma interne

| Objet Corpus QI FR | Objet interne | Mapping |
|-------------------|---------------|---------|
| exemple | `Document` | `domain = "generic"`, `language` normalisée (`en`/`es`/`fr`/`it`) |
| `original_text` | `Document.text` | Texte brut, **avant** anonymisation |
| annotation | `Annotation` | offsets, `qi_categories` mappé depuis `type`, axes et audit de normalisation |
| `coref_id` | `Annotation.entity_id` | cluster de coréférence qualifié par le fichier source |
| `risk_note` | `Annotation.meta` | clé `risk_note` |
| `replacement` | référence de généralisation | `Annotation.meta.replacement_suggestion` |

### Sous-tableau : mapping des labels

| Label source | Code SPEC-01 | expression_mode | granularity |
|--------------|--------------|-----------------|-------------|
| `QUASI_ID` | `OTHER_QI` par défaut ; classification manuelle des `risk_note` (annexe F-3) | `IMPLICIT` pour rareté/déduction, sinon `EXPLICIT` | `COARSE` par défaut |
| `MONTANT`, `AMOUNT` | `GEN_SOCIOECON` | `EXPLICIT` | `EXACT` |
| `HOST` | `SUP_ENVIRONMENT` | `EXPLICIT` | `EXACT` |
| `DATE`, `DATE_REL`, `EVENT` | `GEN_DATE_EVENT` | `EXPLICIT` ou `NON_STANDARD` pour `DATE_REL` | `EXACT` |
| Types techniques / `COREF` | `IGNORED` | `EXPLICIT` | selon la source |

Les 35 types source sont déclarés au manifeste. Les six offsets réparés sont
indiqués dans `Document.meta.repaired_offsets`; une annotation ambiguë aurait
été enregistrée dans `dropped_annotations` plutôt que devinée.

La classification fine est déterministe et auditée dans l'annexe F-3 ; les
notes vides ou purement déductives restent `OTHER_QI` au lieu d'être devinées.

## 11. Splits et protocole

Les trois fichiers sont conservés comme splits logiques du manifeste :
`anonymization` (31), `hard_quasi_id` (40) et `max_anonymization` (1). Il n'y a
pas de split train/dev/test officiel et aucun re-split aléatoire n'est appliqué.
Les identifiants bruts peuvent se recouvrir entre variantes ; les `doc_id` du
pivot sont qualifiés par le fichier source.

**Granularité** : document-level.

## 12. Plan d'implémentation de l'adaptateur

| # | Étape | Sortie |
|---|-------|--------|
| 1 | Charger les 3 fichiers JSON, inspecter le schéma | ✅ 72 exemples, 35 types |
| 2 | Vérifier offsets et ré-ancrer les occurrences uniques | ✅ 427/427 valides, 6 ré-ancrages tracés |
| 3 | Extraire et compter les labels uniques | ✅ 35 types |
| 4 | Mapper labels et `risk_note` vers SPEC-01 | ✅ manifeste + annexe F-3 |
| 5 | Fixer splits, volumétrie et statut au manifeste | ✅ 72 documents |
| 6 | Implémenter `QuasifrAdapter` | ✅ adaptateur publié |
| 7 | Émettre `documents.jsonl` + `annotations.jsonl` | ✅ ingestion officielle publiée |
| 8 | Construire ou pointer vers une population FR pour $k$ | ☐ population FR toujours absente |

## 13. Critères d'acceptation

- [x] Tous les exemples chargés et structurés : 72.
- [x] Offsets validés ; six ré-ancrages uniques tracés.
- [x] `coref_id` mappé vers `Annotation.entity_id`.
- [x] `risk_note` conservé dans `meta`.
- [x] Les 35 types source sont déclarés et mappés ; `OTHER_QI` reste explicite
      pour les cas non classables (annexe F-3).
- [x] Les trois variantes sont isolées comme splits logiques ; aucun split
      train/dev/test officiel n'est fourni.
- [ ] Population FR configurée et opérationnelle.

## 14. Questions ouvertes

- Quelle licence exacte couvre les trois fichiers ?
- Le recouvrement de `ticket_001` entre les variantes est-il intentionnel, et
  faut-il le dédupliquer pour un futur split expérimental ?
- Quelle population de référence française (INSEE ou autre) permettrait de calculer $k$ ?
- Le sens des `risk_note` vides et des six notes de déduction restant `OTHER_QI`
  peut-il être récupéré auprès des auteurs ?
