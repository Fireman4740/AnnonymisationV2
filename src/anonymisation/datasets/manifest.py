"""Manifestes de datasets (SPEC-03 §4) — modèles Pydantic et chargeurs.

Un manifeste est la **fiche d'identité** d'un dataset : sa source, sa
licence, sa structure, le mapping de ses étiquettes vers la taxonomie
SPEC-01, et son protocole d'évaluation. Il précède toujours le code de
l'adaptateur (procédure SPEC-03 §10) : un manifeste que l'on ne peut pas
écrire signale un dataset mal compris.

Règle d'or du projet : aucune valeur par défaut silencieuse. Tous les
modèles sont ``frozen`` et ``extra="forbid"`` ; seules **deux** valeurs par
défaut sont sanctionnées par le ticket A-1 :

- ``structure.synthetic`` (défaut ``False``) — garde E1 de SPEC-08 ;
- ``license.restricted`` (défaut ``False``) — règle L3 de SPEC-09.

Tous les autres champs sont requis dans le YAML ; un champ absent est une
erreur de manifeste, pas une hypothèse.

Contrôles normatifs appliqués par :func:`load_manifest` (EPIC A-1,
SPEC-03 §5) :

1. ``label_map`` citant un code hors SPEC-01 → **erreur** nommant le code
   (``E-MAP-002``) ;
2. ``has_profiles: true`` **et** ``split_by: document`` → **erreur** — la
   fuite par profil latent, qui produirait des résultats excellents et faux
   (SPEC-03 §4) ;
3. ``license.spdx: UNKNOWN`` → ``official_eligible`` forcé à ``False`` et
   événement journalisé (G3, L2 de SPEC-09) ;
4. ``kind: local`` → la source est résolue et les fichiers déclarés sont
   vérifiés ; source ou fichier absent → ``LocalSourceError`` actionnable ;
5. tout le reste est vérifié par le schéma Pydantic → ``ManifestError``.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Final

import yaml
from pydantic import BaseModel, ConfigDict, model_validator

from anonymisation.datasets._local import SourceResolution, resolve_local_source
from anonymisation.datasets.registry import ManifestError
from anonymisation.schema.taxonomy import (
    Granularity,
    IdentifierType,
    Stability,
    UnknownQiCodeError,
    validate_code,
)

logger = logging.getLogger("anonymisation.datasets.manifest")

_BASE = ConfigDict(frozen=True, extra="forbid")

#: Espèces de sources reconnues (SPEC-03 §4 + ``local`` ajouté par l'EPIC A).
KNOWN_SOURCE_KINDS: Final[frozenset[str]] = frozenset(
    {"local", "huggingface", "manual", "generated"}
)


class SourceSpec(BaseModel):
    """D'où vient le dataset, et comment l'acquérir.

    ``kind`` détermine quels champs sont porteurs ; les autres restent
    optionnels pour ne pas imposer une structure identique à 11 datasets
    hétérogènes (HF, manuelle, générée, locale).

    Pour ``kind: local`` (EPIC A) : ``path`` est le chemin du répertoire
    (absolu, ou relatif si la racine est donnée par ``path_env``) ;
    ``path_env`` est la variable d'environnement qui surcharge la racine —
    c'est elle qui rend le dépôt portable d'une machine à l'autre.
    ``files`` liste les fichiers attendus dans le répertoire ; vide signifie
    « le répertoire entier est la source ».
    """

    model_config = _BASE

    kind: str
    path: str | None = None
    path_env: str | None = None
    repo: str | None = None
    revision: str | None = None
    files: list[str] = []
    mirror: str | None = None
    paper: str | None = None
    v1_cache: str | None = None
    instructions: str | None = None
    generator: str | None = None
    seed: int | None = None

    @model_validator(mode="after")
    def _check_kind(self) -> SourceSpec:
        if self.kind not in KNOWN_SOURCE_KINDS:
            raise ManifestError(
                f"kind de source inconnu : {self.kind!r} "
                f"(attendus : {', '.join(sorted(KNOWN_SOURCE_KINDS))})"
            )
        if self.kind == "local" and self.path is None and self.path_env is None:
            raise ManifestError(
                "source `kind: local` : il faut déclarer `path` et/ou `path_env`"
            )
        return self


class LicenseSpec(BaseModel):
    """Licence du dataset (règles L1-L5 de SPEC-09).

    ``spdx`` est **requis** (L2) : la valeur ``UNKNOWN`` est autorisée mais
    interdit le statut ``OFFICIAL`` (forcé à ``False`` au chargement, G3).
    ``restricted`` est le seul booléen de ce modèle ayant un défaut
    sanctionné : ``False`` (L3 — un corpus restreint est l'exception qui
    doit se déclarer).
    """

    model_config = _BASE

    spdx: str
    redistribution: bool | None = None
    restricted: bool = False
    citation: str | None = None
    notes: str | None = None


class IntegritySpec(BaseModel):
    """Empreinte et volumétrie attendues — base du contrôle G5 (SPEC-03 §5).

    ``sha256`` et ``expected_*`` sont ``null`` tant que la source n'est pas
    épinglée ; le statut ``official`` reste refusé tant que la volumétrie
    n'est pas figée (G5). ``expected_threads`` est spécifique aux corpus à
    threads (SynthPAI) et sans défaut.
    """

    model_config = _BASE

    sha256: str | None
    expected_documents: int | None
    expected_profiles: int | None
    expected_threads: int | None = None


class StructureSpec(BaseModel):
    """Structure du corpus : domaines, langues, splits, tables présentes.

    ``synthetic`` est le second défaut sanctionné du ticket (défaut
    ``False``) : c'est la garde E1 de SPEC-08, l'attaquant C refuse de
    démarrer sur un corpus non déclaré.

    Le contrôle normatif le plus important est ici : ``has_profiles: true``
    avec ``split_by: document`` est une **fuite massive** — les messages d'un
    même auteur partagent le profil latent, donc les QI, et finissent à la
    fois en train et en test. Refusée au chargement (SPEC-03 §4).

    ``per_language_counts`` est optionnelle : quand l'acquisition a compté les
    exemples par langue, la figer dans le manifeste permet de contrôler la
    volumétrie linguistique sans re-taper le brut (ex. openpii, EPIC B).
    """

    model_config = _BASE

    domain: str
    languages: list[str]
    synthetic: bool = False
    has_profiles: bool
    has_combinations: bool
    has_organizations: bool
    has_tasks: bool
    split_by: str
    splits: list[str]
    per_language_counts: dict[str, int] | None = None

    @model_validator(mode="after")
    def _check_split_by(self) -> StructureSpec:
        if self.has_profiles and self.split_by == "document":
            raise ManifestError(
                "structure : `has_profiles: true` est incompatible avec "
                "`split_by: document` — fuite par profil latent (SPEC-03 §4) ; "
                "utiliser `person_id` ou `org_id`"
            )
        return self


class LabelMapEntry(BaseModel):
    """Mapping d'une étiquette source vers la taxonomie SPEC-01.

    Chaque ``qi_categories`` doit être un code connu de la taxonomie
    (``validate_code``) : un code inconnu est une erreur de manifeste
    (``E-MAP-002``), jamais un mapping approximé — dégrader silencieusement
    fausserait les métriques sans que personne ne s'en aperçoive (G4).
    """

    model_config = _BASE

    identifier_type: IdentifierType
    qi_categories: list[str]
    granularity: Granularity
    stability: Stability

    @model_validator(mode="after")
    def _check_codes(self) -> LabelMapEntry:
        for code in self.qi_categories:
            validate_code(code)  # inconnu → UnknownQiCodeError (E-MAP-002)
        return self


class EvaluationSpec(BaseModel):
    """Protocole d'évaluation du dataset.

    ``official_eligible`` est la déclaration humaine « ce dataset est apte
    au statut officiel » ; elle est forcée à ``False`` par le chargement si
    ``license.spdx`` est ``UNKNOWN`` (G3). ``default_metric_status`` est le
    statut affiché par défaut (``OFFICIAL``/``SAMPLED``/``DIAGNOSTIC``/
    ``PROXY``) ; ``reweighting`` signale une obligation de repondération des
    résultats (corpus stratifiés, SPEC-05).
    """

    model_config = _BASE

    protocol: str
    protocol_version: str
    official_eligible: bool
    default_metric_status: str
    granularities: list[str]
    report_by: list[str]
    sanity_checks: list[dict[str, str]] = []
    reweighting: str | None = None


class PopulationSpec(BaseModel):
    """Population de référence sur laquelle k et le risque sont calculés.

    ``risk_model`` (``prosecutor``/``copula``/``naive``) est la déclaration
    de quel modèle de risque la population supporte — un k « copula » ne
    transfère pas aux corpus d'une autre origine (voir notes de ratbench).
    """

    model_config = _BASE

    population_id: str | None
    k_computable: bool
    notes: str | None = None
    risk_model: str | None = None


class DatasetManifest(BaseModel):
    """Manifeste complet d'un dataset — SPEC-03 §4, schéma Pydantic.

    ``extra="forbid"`` : un champ inattendu (coquille, périmètre inconnu)
    est une erreur, pas du bruit ignoré. Les sections optionnelles hors
    ticket (``annotation``, ``generation``, ``tasks``) sont des champs
    simples pour rester dans le décompte exact des 8 modèles du ticket A-1.
    """

    model_config = _BASE

    key: str
    name: str
    description: str
    doc: str
    aliases: list[str] = []
    source: SourceSpec
    license: LicenseSpec
    integrity: IntegritySpec
    structure: StructureSpec
    label_map: dict[str, LabelMapEntry] = {}
    evaluation: EvaluationSpec
    population: PopulationSpec
    annotation: dict[str, Any] | None = None
    generation: dict[str, Any] | None = None
    tasks: list[dict[str, str]] = []


@dataclass(frozen=True)
class LoadedManifest:
    """Un manifeste chargé, avec la résolution de sa source locale.

    ``resolution`` est ``None`` pour les sources non locales (huggingface,
    manual, generated) : leur acquisition est l'affaire de l'adaptateur.
    """

    path: Path
    manifest: DatasetManifest
    resolution: SourceResolution | None = None


def load_manifest(path: Path) -> LoadedManifest:
    """Charge et contrôle le manifeste YAML ``path`` (EPIC A-1).

    Ordre des contrôles : YAML → mapping ``label_map`` → ``spdx: UNKNOWN``
    (force ``official_eligible = False`` et journalise) → schéma Pydantic
    (dont ``has_profiles``/``split_by``) → résolution de la source locale.

    Lève :class:`ManifestError` (schéma, ``label_map``), ``LocalSourceError``
    (source locale absente) — tous deux actionnables : fichier, champ,
    valeur, et variable à définir le cas échéant.
    """
    path = Path(path)
    try:
        raw_text = path.read_text(encoding="utf-8")
    except OSError as exc:
        raise ManifestError(f"manifeste illisible : {path} ({exc})") from exc

    try:
        raw = yaml.safe_load(raw_text)
    except yaml.YAMLError as exc:
        raise ManifestError(f"{path} : YAML invalide ({exc})") from exc
    if not isinstance(raw, dict):
        raise ManifestError(f"{path} : le manifeste doit être un mapping au sommet")

    # --- Contrôle 1 : label_map total sur les codes SPEC-01 (E-MAP-002) ---
    label_map = raw.get("label_map") or {}
    if not isinstance(label_map, dict):
        raise ManifestError(f"{path} : `label_map` doit être un mapping")
    for label, entry in label_map.items():
        if not isinstance(entry, dict):
            raise ManifestError(
                f"{path} : l'entrée `label_map[{label!r}]` doit être un mapping"
            )
        for code in entry.get("qi_categories") or []:
            try:
                validate_code(str(code))
            except UnknownQiCodeError as exc:
                raise ManifestError(
                    f"{path} : label_map[{label!r}] cite le code {code!r} inconnu "
                    f"de la taxonomie SPEC-01 (E-MAP-002) : {exc}"
                ) from exc

    # --- Contrôle 3 : spdx UNKNOWN → official_eligible = False (G3, L2) ---
    license_block = raw.get("license")
    spdx = license_block.get("spdx") if isinstance(license_block, dict) else None
    if spdx is not None and str(spdx).strip().upper() == "UNKNOWN":
        evaluation = raw.setdefault("evaluation", {})
        if evaluation.get("official_eligible") is True:
            logger.warning(
                "%s : license.spdx=UNKNOWN — official_eligible forcé à False "
                "(G3, SPEC-03 ; L2, SPEC-09)",
                path,
            )
        evaluation["official_eligible"] = False

    # --- Schéma Pydantic (dont le contrôle has_profiles/split_by) ---
    try:
        manifest = DatasetManifest.model_validate(raw)
    except ManifestError:
        raise
    except Exception as exc:  # ValidationError, TypeError, ValueError…
        raise ManifestError(f"{path} : manifeste invalide :\n{exc}") from exc

    # --- Contrôle 4 : source locale résolue et vérifiée ---
    resolution: SourceResolution | None = resolve_local_source(manifest.source)

    return LoadedManifest(path=path, manifest=manifest, resolution=resolution)


def load_all_manifests(directory: Path) -> dict[str, LoadedManifest]:
    """Charge tous les ``*.yaml`` de ``directory``, clé → :class:`LoadedManifest`.

    L'ordre de chargement est trié (déterministe). Une même clé dans deux
    fichiers est une erreur : elle rendrait le registre ambigu.
    """
    directory = Path(directory)
    if not directory.is_dir():
        raise ManifestError(f"répertoire de manifestes absent : {directory}")

    loaded: dict[str, LoadedManifest] = {}
    for yaml_path in sorted(directory.glob("*.yaml")):
        item = load_manifest(yaml_path)
        key = item.manifest.key
        if key in loaded:
            raise ManifestError(
                f"clé de manifeste dupliquée {key!r} : {yaml_path} et {loaded[key].path}"
            )
        loaded[key] = item
    return loaded
