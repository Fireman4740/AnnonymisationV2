# Corpus QI français

| | |
|---|---|
| **Clé interne** | `quasifr` |
| **Priorité** | **P0** |
| **Benchmark** | B2 |
| **Statut de la fiche** | Stable · v1.0 · 2026-08-30 |

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
| Fichiers | 3 JSON |
| Exemples totaux | à confirmer (≈ plusieurs centaines) |
| Taille disque | 212 Ko (JSON) |
| Annotations (spans) | Offsets caractères, coréférence complète |

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
- **Niveau annotation** : offsets caractères exacts (`start`, `end`), vérifiés
  `text[start:end] == span_text`.
- **Niveau coréférence** : les annotations portent un `coref_id` **global**, ce qui
  permet de **regrouper les mentions d'une même entité** across le document.
  C'est précieux pour évaluer la couverture de coréférence.
- **Niveau risque** : chaque annotation a une justification textuelle (`risk_note`)
  expliquant pourquoi ce QI est risqué — pas juste une étiquette.

Pas de profil latent explicite, mais les annotations suffisent à en reconstruire un
(ex. : si on annote « doctorant » + « Lille » + « moins de 30 ans » + « arrêt
maladie », on peut inférer un profil).

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
| Multilingue | ❌ (français) |
| Volumétrie d'entraînement | ❌ (corpus d'évaluation, trop petit) |

## 8. Apport pour le projet

1. **L'unique source de QI annotés en français**, donc indispensable pour l'évaluation
   FR.
2. **Offsets réels et coréférence**, ce qui permet de mesurer :
   - La précision de la détection (F1, MCC, etc.)
   - La couverture de la coréférence
   - L'impact sur l'anonymisation quand on doit considérer plusieurs mentions d'une
     même entité
3. **Justifications (`risk_note`)** qui articulent pourquoi chaque QI est risqué —
   resource inestimable pour concevoir une heuristique de détection et pour évaluer
   la plausibilité du risque détecté.
4. **Différenciation difficiles** (hard_quasi_id) qui expose les cas où l'inférence
   est requise (`IMPLICIT`), test d'une vraie robustesse.

## 9. Limites et pièges

| Limite | Conséquence |
|--------|-------------|
| Très petit volume | Pas d'entraînement possible. Corpus d'évaluation et de mise au point uniquement. |
| Document-level seulement | Pas de mesure d'agrégation (author-level). |
| Pas de profil latent explicite | La population de référence FR doit être construite séparément pour calculer $k$. |
| Langue FR uniquement | Aucune évaluation cross-lingue FR/EN sur ce corpus. |
| Pas de domaine d'application dédié | Mélange RH, forums, support, ce qui peut introduire du bruit. À documenter au manifeste. |

> **Piège** : ce corpus est petit et bien annoté — il peut sembler "facile". Or
> les cas difficiles (`hard_quasi_id`) sont intentionnellement implicites. Ne pas
> s'étonner d'une F1 basse sur ce sous-ensemble ; c'est le signal attendu.

## 10. Mapping vers le schéma interne

| Objet Corpus QI FR | Objet interne | Mapping |
|-------------------|---------------|---------|
| exemple | `Document` | `domain = "generic"`, `language = "fr"` |
| `original_text` | `Document.text` | Texte brut, **avant** anonymisation |
| annotation | `Annotation` | offsets, `qi_categories` mappé depuis `type`, etc. (voir tableau §10.1) |
| `coref_id` | `Annotation.entity_id` | cluster de coréférence |
| `risk_note` | `Annotation.meta` | key `risk_note` dans le dictionnaire JSON |
| `replacement` | référence de généralisation | stocké dans `Annotation.meta` sous key `replacement_suggestion` |

### Sous-tableau : mapping des labels

| Label source | Code SPEC-01 | expression_mode | granularity |
|--------------|--------------|-----------------|-------------|
| `QUASI_ID` (évidemment implicite dans le type) | À déterminer par le contenu (voir `risk_note`) | `EXPLICIT` ou `IMPLICIT` selon `risk_note` | À déterminer per-cas |
| `DATE` | `GEN_DATE_EVENT` | `EXPLICIT` | `EXACT` (si année complète) ou `COARSE` |

Cet exemple montre le point délicat : **le label source est générique, la classification
SPEC-01 requiert une analyse du contenu**. Le corpus ne fournit pas directement
`GEN_AGE`, `HR_JOB_TITLE`, etc. — il faut les inférer via `risk_note`.

## 11. Splits et protocole

**Pas de split fourni.** Proposition à fixer au manifeste :

- Utiliser les trois fichiers (anonymization, hard, max) comme trois sous-ensembles
  logiquement distincts.
- Ou bien split train/dev/test aléatoire 60/20/20 **avant** l'analyse (pour éviter
  du data leakage sur les cas difficiles).

**Granularité** : document-level.

## 12. Plan d'implémentation de l'adaptateur

| # | Étape | Sortie |
|---|-------|--------|
| 1 | Charger les 3 fichiers JSON, inspecter schéma réel | note §3, §4 |
| 2 | Vérifier offsets : `text[start:end] == span` pour chaque annotation | validation |
| 3 | Extraire et compter les labels uniques (`type`) | label_map planning |
| 4 | Mapper labels vers SPEC-01 (analyser `risk_note` pour infléchir le choix) | `label_map` |
| 5 | Fixer splits, checksum, volumétrie au manifeste | `configs/datasets/quasifr.yaml` |
| 6 | Implémenter `QuasFrAdapter` | `src/anonymisation/datasets/quasifr.py` |
| 7 | Émettre `documents.jsonl` + `annotations.jsonl` | `data/processed/quasifr/` |
| 8 | Construire ou pointer vers population FR pour calcul de $k$ | `configs/populations/fr-generic-*.yaml` |

## 13. Critères d'acceptation

- [ ] Tous les exemples chargés et structurés.
- [ ] Offsets validés (invariant I-ANN-1 de SPEC-02).
- [ ] `coref_id` mappé vers `Annotation.entity_id`.
- [ ] `risk_note` conservé dans `meta`.
- [ ] Labels source totalement mappés vers SPEC-01 (invariant I-ANN-4).
- [ ] Splits train/dev/test sans fuite.
- [ ] Population FR configurée et opérationnelle.

## 14. Questions ouvertes

- Combien d'exemples exactement dans chaque fichier ? (nécessaire pour planifier
  splits et dimensionner des benchmarks)
- Existe-t-il une version multi-langue (corpus QI EN, DE, etc.) ?
- Les trois fichiers (anonymization, hard, max) chevauchent-ils ou sont-ils
  disjoints ?
- Comment les labels source (`QUASI_ID`, `DATE`, etc.) ont-ils été générés ? Sont-ils
  exhaustifs dans le corpus ?
- Quelle est la distribution des `expression_mode` (EXPLICIT vs IMPLICIT) ? Les cas
  difficiles (hard_quasi_id) sont-ils majoritairement implicites ?
- Une population de référence française existe-t-elle déjà (ex. INSEE, données
  pseudo-anonymisées) pour le calcul de $k$ ?
