# ÉPIC A — Infrastructure d'ingestion

**Objectif** : pouvoir charger, normaliser et valider n'importe quel corpus
local vers le format pivot SPEC-02, de façon déterministe et portable.

**Effort** : ~3 jours · **Bloquant pour** : tout l'épic B.

---

## A-1 — Manifestes Pydantic et source `kind: local`

| | |
|---|---|
| **Priorité** | **P0 — goulot d'étranglement du backlog** |
| **Dépend de** | — |
| **Spécs** | SPEC-03 §4 et §5 |
| **Effort** | 0,5 j |

### Contexte

Aucun adaptateur ne peut être chargé sans manifeste. C'est le premier ticket à
faire, et il doit être fait seul : tout le reste en dépend.

Les corpus étant déjà sur disque
([`inventaire-local.md`](../datasets/inventaire-local.md)), il faut un `kind`
de source nouveau, absent de SPEC-03 : `local`. 

### Périmètre

- `src/anonymisation/datasets/manifest.py`
- `src/anonymisation/datasets/_local.py`
- `tests/unit/test_manifest.py`, `tests/unit/test_local_source.py`

### Travail

1. Modèles : `DatasetManifest`, `SourceSpec`, `LicenseSpec`, `IntegritySpec`,
   `StructureSpec`, `LabelMapEntry`, `EvaluationSpec`, `PopulationSpec`.
   Tous en `extra="forbid"`.
2. `SourceSpec` accepte :
   ```yaml
   source:
     kind: local
     path: "F:/IA/Anonymisation/eval/datasets/TAB/official"
     path_env: "ANONV2_V1_DATASETS"     # racine surchargeable, prioritaire
     files: ["echr_train.json", "echr_dev.json", "echr_test.json"]
   ```
3. `_local.py` : `resolve_source_dir(source)`, `check_files(dir, files)`,
   `fingerprint(paths)` (sha256 combiné, ordre trié → déterministe).
4. `load_manifest(path)` et `load_all_manifests(dir)`.

### Contrôles normatifs à implémenter

| Contrôle | Comportement |
|----------|--------------|
| `label_map` citant un code hors SPEC-01 | **Erreur au chargement** (`validate_code`) |
| `has_profiles: true` **et** `split_by: document` | **Erreur** — c'est la fuite par profil latent, elle produirait des résultats excellents et faux |
| `license.spdx: UNKNOWN` | Autorisé, mais force `official_eligible = False` et le journalise |
| `structure.synthetic` | Champ obligatoire (défaut `false`) — utilisé par la garde E1 de SPEC-08 |
| Source ou fichier absent | `LocalSourceError` **actionnable** : dire quoi définir et où |

### Critères d'acceptation

- [x] Manifeste avec `has_profiles: true` + `split_by: document` → erreur.
- [x] `label_map` avec un code inconnu → erreur nommant le code.
- [x] `license.spdx: UNKNOWN` → `official_eligible` forcé à `False`.
- [x] `ANONV2_V1_DATASETS` pointée vers un répertoire temporaire est bien prise
      en compte (**le dépôt ne doit pas dépendre d'une seule machine**).
- [x] Source absente → message indiquant la variable à définir.
- [x] `fingerprint` est stable quel que soit l'ordre des chemins fournis.

### Piège connu

La portabilité n'est pas un confort : sans `path_env`, le dépôt ne fonctionne
que sur cette machine et aucun résultat n'est reproductible par un tiers.

---

## A-2 — Pipeline d'ingestion en 5 étapes

| | |
|---|---|
| **Priorité** | **P0** |
| **Dépend de** | A-1 |
| **Spécs** | SPEC-04 (intégralité) |
| **Effort** | 1 j |

### Périmètre

- `src/anonymisation/datasets/ingest.py`
- `tests/integration/test_ingest.py`

### Travail

ACQUIRE → PARSE → NORMALIZE → VALIDATE → PUBLISH.

```python
def ingest(adapter, manifest, *, split="all", limit=None,
           output_root=Path("data/processed")) -> IngestionResult
```

1. Écrit `data/processed/<clé>/<split>/{documents,annotations,profiles,
   organizations,combinations,tasks}.jsonl` via `write_jsonl` (déjà livré,
   atomique). N'écrit pas les tables vides.
2. Applique `validate_dataset` (déjà livré) et **échoue** si le rapport contient
   une issue de sévérité `error`, avec un message listant les codes et leurs
   comptes.
3. Produit `.manifest.lock.json` : manifeste résolu, `schema_version`,
   **`taxonomy_version`**, empreinte de la source, sha256 de chaque fichier
   produit, date, statut.
4. Produit `.validation.json` = `report.to_dict()`.
5. Statut selon G3/G5 de SPEC-03 : `official` seulement si licence connue **et**
   volumétrie conforme ; sinon `sampled` ou `diagnostic`.
6. `check_lock_compatibility(lock_path)` : refuse un lock dont le
   `taxonomy_version` diffère de la version courante, en demandant une
   réingestion.

### Critères d'acceptation

- [x] Deux ingestions successives produisent des fichiers **identiques bit à
      bit** (test explicite).
- [x] Une violation d'invariant fait échouer l'ingestion, elle n'est jamais
      journalisée en avertissement.
- [x] Le lock contient les 7 éléments de reproductibilité de SPEC-09 §5.
- [x] `taxonomy_version` divergent → refus explicite.
- [x] Les tests utilisent un **adaptateur factice en mémoire** et ne dépendent
      d'aucun corpus réel.

### Piège connu

`.validation.json` n'est pas un sous-produit décoratif : ses `counts` sont les
**dénominateurs** des métriques ventilées de SPEC-07. Un compte faux fausse
toutes les métriques par langue et par domaine.

---

## A-3 — CLI argparse

| | |
|---|---|
| **Priorité** | **P0** |
| **Dépend de** | A-2 |
| **Spécs** | SPEC-03 §9 |
| **Effort** | 0,5 j |

### Contexte

`src/anonymisation/cli/main.py` est **actuellement cassé** : il importe `typer`
et `rich`, absents de l'environnement. Le fichier est à réécrire entièrement en
`argparse` (stdlib) — le noyau ne doit dépendre d'aucune bibliothèque lourde
(audit v1 §12.9).

### Périmètre

- `src/anonymisation/cli/main.py` (réécriture complète)
- `tests/unit/test_cli.py`

### Commandes

```
anonv2 datasets list                 # clé, licence, statut, volumétrie, source présente ou non
anonv2 datasets describe <clé>
anonv2 datasets ingest <clé> [--split S] [--limit N] [--all]
anonv2 datasets validate <clé>
anonv2 datasets stats <clé>
anonv2 datasets audit-licenses
anonv2 version
```

Codes de sortie : `0` succès, `1` échec de validation, `2` erreur d'usage.

### Critères d'acceptation

- [x] `import anonymisation.cli.main` fonctionne (il échoue aujourd'hui).
- [x] `datasets list` fonctionne **même si aucun adaptateur n'est enregistré** :
      liste les manifestes trouvés avec la mention « adaptateur non implémenté ».
- [x] `stats` sur un dataset non ingéré affiche un message clair sans planter.
- [x] `audit-licenses` sort en code ≠ 0 si un manifeste est incomplet.
- [x] Sortie tabulaire en texte simple, aucune dépendance à `rich`.

---

## A-4 — Utilitaire BIO → offsets caractères

| | |
|---|---|
| **Priorité** | P1 |
| **Dépend de** | — |
| **Spécs** | SPEC-03 §6 |
| **Effort** | 0,5 j |

### Contexte

CleanCoNLL est au format BIO au niveau token. La conversion vers des spans
caractères est **la source d'erreur d'offsets la plus fréquente**, et
l'invariant I-ANN-1 la rendra visible bruyamment — autant l'écrire correctement
une fois pour toutes.

La v1 contient déjà cette logique dans
`F:\IA\Anonymisation\eval\core\loaders\conll2003.py` (lecture seule) :
la lire avant de réimplémenter.

### Périmètre

- `src/anonymisation/datasets/_bio.py`
- `tests/unit/test_bio.py`

### Travail

```python
def bio_to_spans(tokens: Sequence[str], tags: Sequence[str],
                 *, joiner: str = " ") -> tuple[str, list[tuple[int, int, str]]]
    # reconstruit le texte ET les offsets, garantit text[start:end] == surface
```

Gère : `B-`/`I-`/`O`, les tags `I-` orphelins (sans `B-` précédent), les
entités en fin de séquence, la ponctuation collée.

### Critères d'acceptation

- [x] `text[start:end] == span_text` sur 100 % des spans produits, sur au moins
      5 cas dont un `I-` orphelin et une entité en fin de séquence.
- [x] Une séquence `tokens`/`tags` de longueurs différentes → erreur explicite.

---

## A-5 — Câblage du registre d'adaptateurs

| | |
|---|---|
| **Priorité** | **P0** |
| **Dépend de** | A-1 |
| **Effort** | 0,25 j |

### Contexte

`datasets/registry.py` et `base.py` sont livrés, mais aucun adaptateur n'est
enregistré. Les imports d'adaptateurs sont **commentés** dans
`datasets/__init__.py`.

Décision de conception à préserver : l'enregistrement se fait par décorateur
`@register` et la découverte par **import explicite**, jamais par scan
dynamique du système de fichiers — sinon le comportement dépendrait de l'ordre
d'import.

### Périmètre

- `src/anonymisation/datasets/__init__.py`

### Travail

Décommenter et compléter les imports au fur et à mesure que les adaptateurs de
l'épic B sont livrés. Chaque adaptateur s'auto-enregistre dans son propre
module ; **aucun adaptateur ne doit modifier `__init__.py` lui-même** (source
de conflits quand plusieurs personnes travaillent en parallèle).

### Critères d'acceptation

- [x] `from anonymisation.datasets import REGISTRY` expose tous les adaptateurs
      livrés.
- [x] Une clé enregistrée deux fois lève une erreur.
- [x] Un alias déjà utilisé lève une erreur.
