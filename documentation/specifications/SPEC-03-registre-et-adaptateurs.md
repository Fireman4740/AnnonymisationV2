# SPEC-03 — Registre de datasets et contrat d'adaptateur

| | |
|---|---|
| **Statut** | Stable |
| **Version** | 1.0 |
| **Date** | 2026-08-30 |
| **Dépend de** | SPEC-02 |
| **Utilisée par** | SPEC-04, SPEC-07 |

---

## 1. Objet

Définir **comment un dataset entre dans le système** : son manifeste, son
adaptateur, son enregistrement au registre, et les garanties que le registre
fait respecter.

Objectif de conception : **ajouter un dataset = écrire un fichier YAML + une
classe d'adaptateur**. Aucune modification du moteur, des métriques ou du CLI.

## 2. Vue d'ensemble

```
configs/datasets/<key>.yaml        ← manifeste : quoi, d'où, sous quelle licence
        │
        ▼
src/anonymisation/datasets/<key>.py ← adaptateur : comment lire le format source
        │
        ▼
    REGISTRY (src/anonymisation/datasets/registry.py)
        │
        ├─→ anonv2 datasets list
        ├─→ anonv2 datasets download <key>
        ├─→ anonv2 datasets ingest <key>
        └─→ anonv2 datasets validate <key>
```

## 3. Clés de dataset

| Dataset | Clé | Alias acceptés |
|---------|-----|----------------|
| RAT-Bench | `ratbench` | `rat-bench`, `rat_bench` |
| TAB | `tab` | `text-anonymization-benchmark` |
| IPI | `ipi` | `ipi-mimic` |
| SynthPAI | `synthpai` | — |
| OpenPII 500k | `openpii` | `ai4privacy`, `open-pii-500k` |
| JobStack | `jobstack` | — |
| MultiCoNER II | `multiconer2` | `multiconer` |
| MEDDOCAN | `meddocan` | — |
| HR-QI-Bench | `hr_qi` | `hr-qi-bench` |
| Support-QI-Bench | `support_qi` | `support-qi-bench` |
| Forum-QI-Bench | `forum_qi` | `forum-qi-bench` |

La clé est **immuable** : elle préfixe tous les identifiants (SPEC-02 §11), donc
la changer invaliderait toutes les données déjà ingérées.

## 4. Le manifeste

Un fichier `configs/datasets/<key>.yaml` par dataset. Il étend le
`DatasetManifest` de la V1.

```yaml
# configs/datasets/synthpai.yaml
key: synthpai
name: "SynthPAI"
description: "Commentaires de forum synthétiques avec profils latents et attributs personnels"
doc: "documentation/datasets/synthpai.md"

source:
  kind: huggingface              # huggingface | url | zenodo | manual | generated
  repo: "RobinSta/SynthPAI"
  revision: "<commit-sha>"       # OBLIGATOIRE : épingle la version
  files: []

license:
  spdx: "UNKNOWN"                # à renseigner ; UNKNOWN bloque le mode official
  redistribution: false
  restricted: false              # true => tests marqués restricted_license
  citation: "yukhymenko2024synthpai"
  notes: "Vérifier la licence exacte sur la carte HF"

integrity:
  sha256: null                   # renseigné à la première acquisition
  expected_documents: 7823
  expected_profiles: 300
  expected_threads: 103

structure:
  domain: forum
  languages: ["en"]
  has_profiles: true
  has_combinations: false
  has_organizations: false
  has_tasks: false
  split_by: person_id            # CRITIQUE : jamais par document ici
  splits: ["train", "dev", "test"]

label_map:
  # étiquette source -> {identifier_type, qi_categories, granularity, stability}
  age:            { identifier_type: QUASI, qi_categories: [GEN_AGE],        granularity: EXACT,  stability: STABLE }
  sex:            { identifier_type: QUASI, qi_categories: [GEN_GENDER],     granularity: COARSE, stability: STABLE }
  income:         { identifier_type: QUASI, qi_categories: [GEN_SOCIOECON],  granularity: RANGE,  stability: VOLATILE }
  city_country:   { identifier_type: QUASI, qi_categories: [GEN_GEO],        granularity: COARSE, stability: VOLATILE }
  birth_city_country: { identifier_type: QUASI, qi_categories: [GEN_GEO],    granularity: COARSE, stability: STABLE }
  education:      { identifier_type: QUASI, qi_categories: [GEN_EDUCATION],  granularity: COARSE, stability: STABLE }
  occupation:     { identifier_type: QUASI, qi_categories: [GEN_OCCUPATION], granularity: COARSE, stability: VOLATILE }
  relationship_status: { identifier_type: QUASI, qi_categories: [GEN_FAMILY], granularity: COARSE, stability: VOLATILE }

evaluation:
  protocol: "synthpai-v1"
  protocol_version: "1"
  official_eligible: false       # passe à true quand licence + checksum sont fixés
  default_metric_status: "DIAGNOSTIC"
  granularities: ["document", "author"]

population:
  population_id: null            # SynthPAI n'a pas de population de référence
  k_computable: false
```

### Champs bloquants

| Champ | Si absent ou invalide |
|-------|----------------------|
| `license.spdx` | Chargement autorisé en mode `dev`, **refusé** en mode `official` |
| `source.revision` | Avertissement bloquant : sans épinglage, aucune reproductibilité |
| `label_map` | Toute étiquette source absente du map → **échec d'ingestion** |
| `structure.split_by` | Défaut `document` ; DOIT être `person_id` ou `org_id` quand des profils existent |

> `structure.split_by` mérite une insistance : un split par document sur un
> corpus à profils latents produit une **fuite massive** (les messages d'un même
> auteur partagent le profil, donc les QI). C'est l'erreur qui invaliderait
> silencieusement tous les résultats. Le registre DOIT la refuser.

## 5. Garanties du registre

Le registre applique cinq contrôles avant tout chargement :

| # | Contrôle | Action si échec |
|---|----------|-----------------|
| G1 | La clé est enregistrée et unique | `UnknownDatasetError` |
| G2 | Le manifeste est valide (schéma Pydantic) | `ManifestError` |
| G3 | La licence est déclarée | Refus en mode `official`, avertissement en `dev` |
| G4 | Le `label_map` est total sur les étiquettes rencontrées | `UnmappedLabelError` (bloquant) |
| G5 | La volumétrie observée == `integrity.expected_*` | Refus du statut `official`, bascule en `SAMPLED` |

Ces contrôles matérialisent la règle d'or de
[SPEC-README §5](README.md) : aucune valeur par défaut silencieuse.

## 6. Le contrat `DatasetAdapter`

```python
# src/anonymisation/datasets/base.py

class DatasetAdapter(ABC):
    """Contrat que tout dataset doit implémenter.

    L'adaptateur ne connaît que son format source et le schéma SPEC-02.
    Il ne connaît ni les métriques, ni le moteur de risque, ni la politique.
    """

    key: ClassVar[str]

    def __init__(self, manifest: DatasetManifest, raw_dir: Path) -> None: ...

    # --- Acquisition -------------------------------------------------------
    @abstractmethod
    def download(self, *, force: bool = False) -> AcquisitionReport:
        """Télécharge la source dans raw_dir. Idempotent. Calcule le sha256."""

    # --- Normalisation -----------------------------------------------------
    @abstractmethod
    def iter_documents(self, split: str) -> Iterator[Document]: ...

    @abstractmethod
    def iter_annotations(self, split: str) -> Iterator[Annotation]: ...

    def iter_profiles(self, split: str) -> Iterator[Profile]:
        return iter(())          # défaut : pas de profils

    def iter_organizations(self, split: str) -> Iterator[Organization]:
        return iter(())

    def iter_combinations(self, split: str) -> Iterator[Combination]:
        return iter(())

    def iter_tasks(self, split: str) -> Iterator[TaskLabel]:
        return iter(())

    # --- Découpage ---------------------------------------------------------
    def splits(self) -> tuple[str, ...]:
        return tuple(self.manifest.structure.splits)

    def make_splits(self, seed: int = 42) -> dict[str, tuple[str, ...]]:
        """Split déterministe quand la source n'en fournit pas.

        DOIT respecter manifest.structure.split_by.
        """

    # --- Introspection -----------------------------------------------------
    def describe(self) -> dict[str, Any]: ...
```

### Règles d'implémentation

1. Les méthodes `iter_*` DOIVENT être des **générateurs paresseux** — certains
   datasets (OpenPII, MultiCoNER) ne tiennent pas confortablement en mémoire.
2. `download()` DOIT être **idempotent** : relancé, il ne retélécharge pas si le
   checksum correspond.
3. Un adaptateur NE DOIT PAS écrire dans `data/processed/` : c'est le rôle du
   pipeline d'ingestion (SPEC-04). L'adaptateur produit des objets, pas des
   fichiers.
4. Un adaptateur NE DOIT PAS filtrer ni corriger silencieusement. Une donnée
   source aberrante remonte telle quelle et est rejetée par la validation, avec
   son `doc_id`.

### Utilitaires partagés

À écrire une fois, réutilisés par plusieurs adaptateurs :

| Utilitaire | Fichier | Utilisé par |
|------------|---------|-------------|
| Conversion BIO → spans caractères | `datasets/_bio.py` | JobStack, MultiCoNER II |
| Parseur BRAT (`.txt` + `.ann`) | `datasets/_brat.py` | MEDDOCAN, futures campagnes d'annotation |
| Chargeur Hugging Face avec épinglage de révision | `datasets/_hf.py` | OpenPII, SynthPAI, MultiCoNER II |
| Agrégation document → thread → auteur | `datasets/aggregation.py` | SynthPAI, forum_qi, support_qi |
| Split déterministe par clé de groupe | `datasets/_split.py` | tous |

`_bio.py` mérite un soin particulier : la conversion token → caractères est la
source d'erreur d'offsets la plus fréquente, et l'invariant I-ANN-1 la rendra
visible bruyamment — ce qui est le comportement voulu, mais autant l'écrire
correctement une fois.

## 7. Reprise des adaptateurs V1

Le dépôt V1 contient `eval/core/dataset_adapters/` avec `tab.py`,
`ratbench.py`, `personalreddit.py`, `conll2003.py`, `dbbio.py`, et
`eval/core/loaders/`.

| Élément V1 | Décision |
|------------|----------|
| `tab_official.py`, `ratbench.py` (logique de format) | **À lire avant toute réimplémentation** — ils documentent le format réel des sources |
| `DatasetAdapter` V1 (dataclass avec `loader` optionnel) | **Non repris tel quel** : trop couplé à `argparse` et au runner. La v2 utilise une ABC. |
| Caches `eval/datasets/TAB`, `eval/datasets/RAT-Bench` | **Réutilisables** : copier plutôt que retélécharger, après vérification de checksum |
| `conll2003.py` (logique BIO) | **Repris** comme base de `_bio.py` |

> Recommandation pratique : commencer chaque nouvel adaptateur par une lecture
> de son homologue V1. Le temps gagné sur la découverte du format source dépasse
> largement le coût de la lecture.

## 8. Enregistrement

```python
# src/anonymisation/datasets/registry.py

REGISTRY: Final[dict[str, type[DatasetAdapter]]] = {}

def register(cls: type[DatasetAdapter]) -> type[DatasetAdapter]:
    if cls.key in REGISTRY:
        raise ValueError(f"Clé de dataset déjà enregistrée : {cls.key!r}")
    REGISTRY[cls.key] = cls
    return cls
```

L'enregistrement se fait par décorateur, la découverte par import explicite dans
`datasets/__init__.py` — **pas** par scan dynamique du système de fichiers, qui
rendrait le comportement dépendant de l'ordre d'import.

## 9. Interface en ligne de commande

```bash
anonv2 datasets list                      # clés, statut, licence, volumétrie
anonv2 datasets describe openpii          # manifeste résolu + couverture
anonv2 datasets download openpii          # acquisition + checksum
anonv2 datasets ingest openpii            # normalisation vers data/processed/
anonv2 datasets validate openpii          # tous les invariants SPEC-02
anonv2 datasets stats openpii             # comptes par langue, catégorie, mode
```

`stats` n'est pas un confort : c'est lui qui produit les comptes par langue et
par catégorie exigés pour les métriques déclinées de
[SPEC-07](SPEC-07-metriques.md).

## 10. Ajouter un dataset — procédure

1. Écrire la fiche `documentation/datasets/<nom>.md` (gabarit en 14 sections).
2. Écrire `configs/datasets/<key>.yaml`, `license.spdx` inclus.
3. Écrire `src/anonymisation/datasets/<key>.py` héritant de `DatasetAdapter`.
4. L'enregistrer via `@register` et l'importer dans `datasets/__init__.py`.
5. `anonv2 datasets download <key> && anonv2 datasets ingest <key>`.
6. `anonv2 datasets validate <key>` — DOIT passer sans avertissement.
7. Compléter `integrity.sha256` et `expected_*` dans le manifeste.
8. Ajouter un test dans `tests/integration/test_<key>.py`, marqué
   `requires_data`.

**L'étape 1 précède le code.** Une fiche qui ne peut pas être écrite signale un
dataset mal compris, et un adaptateur écrit sur un dataset mal compris coûtera
plus cher à corriger.

## 11. Journal des modifications

| Version | Date | Changement |
|---------|------|-----------|
| 1.0 | 2026-08-30 | Création. Manifeste YAML, ABC `DatasetAdapter`, cinq garanties du registre, décisions de reprise V1. |
