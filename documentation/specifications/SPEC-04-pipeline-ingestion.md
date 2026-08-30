# SPEC-04 — Pipeline d'ingestion

| | |
|---|---|
| **Statut** | Stable |
| **Version** | 1.0 |
| **Date** | 2026-08-30 |
| **Dépend de** | SPEC-02, SPEC-03 |

---

## 1. Objet

Définir les **cinq étapes** entre une source distante et un dataset utilisable,
ainsi que les erreurs, les caches et les garanties de reproductibilité.

## 2. Les cinq étapes

```
  [1] ACQUIRE          [2] PARSE            [3] NORMALIZE        [4] VALIDATE        [5] PUBLISH
  source distante  →   objets bruts     →   objets SPEC-02   →   invariants     →   data/processed/
       │                    │                     │                   │                    │
   sha256              adaptateur            label_map          I-DOC/I-ANN/…        manifeste figé
   data/raw/          iter_documents()      normalisation        échec bruyant       + stats
                      iter_annotations()      des valeurs
```

Chaque étape a une sortie inspectable et peut être relancée seule.

---

## 3. Étape 1 — ACQUIRE

```bash
anonv2 datasets download <key> [--force]
```

| Aspect | Règle |
|--------|-------|
| Destination | `data/raw/<key>/` |
| Idempotence | Si le `sha256` correspond au manifeste, **ne retélécharge pas** |
| Épinglage | `source.revision` DOIT être utilisé (commit HF, tag Git, DOI Zenodo) |
| Sortie | `data/raw/<key>/.acquisition.json` : URL, révision, sha256, date, taille |
| Sources manuelles | `source.kind: manual` → la commande affiche les instructions et vérifie la présence des fichiers, sans télécharger |

`source.kind: manual` couvre MIMIC-III (accès PhysioNet) et JobStack (demande
aux auteurs). Ces datasets ne bloquent pas le pipeline : ils échouent
proprement avec un message expliquant la démarche à suivre.

### Premier calcul du checksum

À la première acquisition, `integrity.sha256` est `null`. La commande calcule le
checksum et **propose** de l'écrire dans le manifeste — elle ne l'écrit pas
seule, car figer un checksum est une décision (« cette version est la bonne »),
pas un effet de bord.

```bash
anonv2 datasets download openpii --pin    # calcule ET écrit le checksum
```

---

## 4. Étapes 2 et 3 — PARSE et NORMALIZE

```bash
anonv2 datasets ingest <key> [--split all] [--limit N]
```

L'adaptateur produit des objets bruts (étape 2) que le pipeline normalise
(étape 3). La séparation compte : l'adaptateur connaît le format source, le
pipeline connaît SPEC-01/SPEC-02.

### Ce que fait la normalisation

| Opération | Détail |
|-----------|--------|
| Application du `label_map` | Étiquette source → `identifier_type`, `qi_categories`, `granularity`, `stability` |
| Préfixage des identifiants | `<key>:<id local>` (SPEC-02 §11) |
| Normalisation Unicode | **NFC**, appliquée au texte **avant** tout calcul d'offset |
| Normalisation des valeurs | `value_normalized` selon les tables de `configs/populations/` |
| Renseignement des défauts explicites | `sensitivity=NONE`, `subject=SELF`, `confidence=1.0` — écrits, pas supposés |

> **Ordre critique** : normalisation Unicode → calcul/report des offsets. Dans
> l'autre sens, les offsets source ne correspondent plus au texte stocké, et
> l'invariant I-ANN-1 échoue sur l'ensemble du corpus. Si la source fournit des
> offsets sur du texte non-NFC, l'adaptateur DOIT soit conserver le texte
> original tel quel, soit recalculer les offsets par alignement.

### Erreurs de cette étape

| Code | Cause | Comportement |
|------|-------|--------------|
| `E-MAP-001` | Étiquette source absente du `label_map` | **Échec immédiat**, liste les étiquettes manquantes |
| `E-MAP-002` | Code QI inconnu de SPEC-01 | Échec immédiat |
| `E-NRM-001` | Valeur non normalisable (ex. profession hors nomenclature) | Avertissement + `value_normalized = null` + compteur |
| `E-NRM-002` | Plus de 5 % de valeurs non normalisables | **Échec** : la table de normalisation est inadaptée |

`E-NRM-002` évite le scénario où un dataset s'ingère « avec succès » mais dont
80 % des attributs sont inexploitables par le moteur de risque.

---

## 5. Étape 4 — VALIDATE

```bash
anonv2 datasets validate <key>
```

Vérifie tous les invariants de SPEC-02.

| Code | Invariant | Sévérité |
|------|-----------|:--------:|
| `E-VAL-101` | I-ANN-1 — `text[start:end] != span_text` | **Bloquant** |
| `E-VAL-102` | I-ANN-2 — annotation sans offset et `expression_mode != IMPLICIT` | **Bloquant** |
| `E-VAL-103` | I-ANN-3 — `DIRECT` avec un code `GEN_*` | **Bloquant** |
| `E-VAL-104` | I-DOC-3 — `author_id` orphelin | **Bloquant** |
| `E-VAL-105` | I-CMB-1 — monotonie du scope violée | **Bloquant** |
| `E-VAL-106` | I-CMB-2 — `risk_true != 1/k_true` en modèle prosecutor | **Bloquant** |
| `E-VAL-107` | I-PRO-2 — attribut sans `normalized` | Avertissement + compteur |
| `E-VAL-108` | Fuite de split : un `person_id`/`org_id` dans deux splits | **Bloquant** |
| `E-VAL-109` | Volumétrie ≠ `expected_*` | Dégrade le statut en `SAMPLED` |
| `E-VAL-110` | Taux d'`OTHER_QI` > 1 % | Avertissement fort (taxonomie incomplète) |
| `E-VAL-111` | Doublon d'identifiant | **Bloquant** |

`E-VAL-108` est le contrôle le plus important en pratique : c'est celui qui
attrape la fuite par profil latent, laquelle produirait des résultats
excellents et faux.

### Rapport de validation

Sortie : `data/processed/<key>/.validation.json`

```json
{
  "dataset": "synthpai",
  "schema_version": "2.0",
  "status": "PASS",
  "counts": {
    "documents": 7823, "annotations": 21044, "profiles": 300,
    "by_language": { "en": 7823 },
    "by_domain": { "forum": 7823 },
    "by_expression_mode": { "EXPLICIT": 9012, "NON_STANDARD": 5230, "IMPLICIT": 6802 },
    "by_qi_category": { "GEN_AGE": 2103, "GEN_GEO": 3277, "...": 0 }
  },
  "warnings": [ { "code": "E-VAL-107", "count": 12 } ],
  "errors": []
}
```

Ce fichier alimente directement les métriques déclinées par langue, domaine et
mode d'expression de [SPEC-07](SPEC-07-metriques.md). Il n'est pas un
sous-produit : il **est** la source des dénominateurs.

---

## 6. Étape 5 — PUBLISH

| Aspect | Règle |
|--------|-------|
| Destination | `data/processed/<key>/<split>/<table>.jsonl` |
| Écriture | **Atomique** : écriture dans `.tmp`, puis renommage |
| Manifeste figé | `data/processed/<key>/.manifest.lock.json` — copie du manifeste + sha256 des fichiers produits |
| Statut | `official` \| `sampled` \| `diagnostic`, déterminé par les garanties G3/G5 de SPEC-03 |

Le `.manifest.lock.json` est ce qui rend une expérience reproductible : il fige
la révision source, les checksums et la version de la taxonomie utilisée pour
l'ingestion.

> **Conséquence** : un changement de SPEC-01 (nouveau code QI) invalide les
> ingestions précédentes. Le lock contient `taxonomy_version` ; le pipeline
> refuse d'évaluer avec un lock dont la version de taxonomie diffère de la
> version courante, et demande une réingestion.

---

## 7. Caches

| Cache | Emplacement | Invalidé par |
|-------|-------------|--------------|
| Sources brutes | `data/raw/<key>/` | `--force` ou changement de `source.revision` |
| Données normalisées | `data/processed/<key>/` | changement de `label_map`, de `taxonomy_version`, ou du checksum source |
| Populations résolues | `data/interim/populations/<pid>/` | changement du fichier de population |

Aucun de ces répertoires n'est versionné. La reproductibilité passe par les
manifestes et les checksums, pas par le stockage des données dans Git.

---

## 8. Traitement par lots

```bash
anonv2 datasets ingest --all --skip-missing
```

Traite tous les datasets enregistrés dont la source est disponible localement,
et saute proprement ceux dont l'acquisition est manuelle et non satisfaite
(MIMIC-III, JobStack), en les listant en fin de rapport.

C'est la commande de la CI (voir [SPEC-09](SPEC-09-qualite-licences-ci.md)).

---

## 9. Déterminisme

Trois exigences, sans lesquelles aucune comparaison entre deux runs n'a de sens :

1. **Ordre stable** — les `iter_*` produisent toujours le même ordre pour une
   même source. Si la source est un ensemble non ordonné, l'adaptateur trie par
   identifiant.
2. **Splits déterministes** — hachage de la clé de groupe (`person_id`,
   `org_id`) avec une graine fixe, jamais `random.shuffle` sur une liste dont
   l'ordre dépend du système de fichiers.
3. **Pas d'horodatage dans les données** — les dates de traitement vont dans le
   lock, pas dans les enregistrements.

```python
def assign_split(group_key: str, seed: int, ratios: dict[str, float]) -> str:
    h = hashlib.blake2b(f"{seed}:{group_key}".encode(), digest_size=8).digest()
    x = int.from_bytes(h, "big") / 2**64
    # affectation par seuils cumulés sur ratios triés
```

Cette fonction garantit qu'ajouter un nouveau profil ne redistribue pas les
profils existants entre splits — propriété que `train_test_split` n'a pas.

---

## 10. Ordre d'implémentation

Rappel de [`datasets/README §6`](../datasets/README.md) :

| # | Dataset | Ce que l'étape valide |
|---|---------|----------------------|
| 1 | **OpenPII** | La chaîne complète sur un cas facile : HF, label_map, offsets, splits, stats par langue |
| 2 | **SynthPAI** | Profils latents, split par auteur, annotations sans offset (I-ANN-2), agrégation |
| 3 | **TAB** | Coréférences, multi-annotateurs, texte réel, métriques entity-level |
| 4 | **RAT-Bench** | Population de référence, combinaisons, `k_true`, attaquant |
| 5 | **HR / Support / Forum-QI** | Génération (SPEC-05) plutôt qu'ingestion |
| 6 | JobStack, MultiCoNER II, MEDDOCAN | Utilitaires BIO et BRAT |

Chaque étape ajoute **une** difficulté nouvelle. C'est délibéré : commencer par
TAB ou RAT-Bench ferait affronter simultanément le format, la taxonomie, la
coréférence et le risque.

---

## 11. Critères de sortie du lot d'ingestion

- [ ] `anonv2 datasets list` affiche les 11 datasets avec leur statut réel.
- [ ] Les 5 datasets P0 accessibles sans démarche administrative sont ingérés et
      valides.
- [ ] Chaque dataset ingéré a un `.manifest.lock.json` et un
      `.validation.json`.
- [ ] Aucun avertissement `E-VAL-108` (fuite de split) sur aucun dataset.
- [ ] Le taux global d'`OTHER_QI` est < 1 % sur chaque dataset.
- [ ] Une réingestion complète produit des fichiers **identiques bit à bit**
      (test de déterminisme).

Le dernier point est le test qui attrape les non-déterminismes cachés (ordre de
dictionnaire, parcours de répertoire, seed non fixée).

## 12. Journal des modifications

| Version | Date | Changement |
|---------|------|-----------|
| 1.0 | 2026-08-30 | Création. Cinq étapes, codes d'erreur E-MAP/E-NRM/E-VAL, déterminisme, ordre d'implémentation. |
