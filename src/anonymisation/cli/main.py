"""CLI ``anonv2``.

Commandes de datasets spécifiées en SPEC-03 §9 et en EPIC-A (ticket A-3).
Implémentation en ``argparse`` (stdlib) uniquement : le noyau ne dépend
d'aucune bibliothèque lourde (audit v1 §12.9) — la version précédente
importait ``typer``/``rich``, absents de l'environnement, et le module
était cassé à l'import.

Codes de sortie : ``0`` succès, ``1`` échec (validation, ingestion,
audit de licences), ``2`` erreur d'usage (clé inconnue, arguments
conflictuels — ``argparse`` renvoie 2 nativement).
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from collections.abc import Sequence
from datetime import date
from pathlib import Path

from anonymisation import __version__
from anonymisation.datasets.ingest import (
    LOCK_NAME,
    TABLE_MODELS,
    TABLES,
    VALIDATION_NAME,
    IngestionError,
    LocalSourceError,
    ingest,
    validate_streaming_output,
)
from anonymisation.datasets.manifest import (
    DatasetManifest,
    ManifestError,
    load_all_manifests,
    load_manifest,
)
from anonymisation.datasets.registry import (
    ALIASES,
    REGISTRY,
    UnknownDatasetError,
    UnmappedLabelError,
    list_keys,
)
from anonymisation.schema.io import JsonlError, atomic_write, read_jsonl, sha256_file, write_json
from anonymisation.schema.validation import validate_dataset

# Ancrage du dépôt : ``src/anonymisation/cli/main.py`` → racine 3 niveaux plus haut.
REPO_ROOT: Path = Path(__file__).resolve().parents[3]
CONFIG_DIR: Path = REPO_ROOT / "configs" / "datasets"
PROCESSED_ROOT: Path = REPO_ROOT / "data" / "processed"
RAW_ROOT: Path = REPO_ROOT / "data" / "raw"

# Identifiant SPDX officiel (SPEC-09 §2.3) : lettre/chiffre, puis ``. + - /``.
# Tout ce qui ne matche pas (« à decidir », « on-request », etc.) est traité
# comme licence incomplète.
_SPDX_RE = re.compile(r"[A-Za-z0-9][A-Za-z0-9.+\-/]*\Z")


def _print_table(headers: Sequence[str], rows: Sequence[Sequence[str]]) -> None:
    """Tableau texte brut, largeurs calculées à la main (jamais ``rich``).

    Tolère des lignes plus longues que l'en-tête (ex. marqueur « ← bloquant »
    du tableau SPEC-09 §2.3).
    """
    cols = max([len(headers)] + [len(r) for r in rows])
    data = [[str(h) for h in headers] + [""] * (cols - len(headers))]
    data += [[str(c) for c in row] + [""] * (cols - len(row)) for row in rows]
    widths = [max(len(row[i]) for row in data) for i in range(cols)]
    for i, row in enumerate(data):
        line = "  ".join(cell.ljust(widths[i]) for i, cell in enumerate(row)).rstrip()
        if i == 1:
            print("  ".join("-" * w for w in widths))
        print(line)


def _dataset_dir(key: str) -> Path:
    """Répertoire publié par l'ingestion pour ``key`` (SPEC-04 §6)."""
    return PROCESSED_ROOT / key


def _lock_path(key: str) -> Path:
    return _dataset_dir(key) / LOCK_NAME


def _read_lock(key: str) -> dict | None:
    path = _lock_path(key)
    if not path.is_file():
        return None
    return json.loads(path.read_text(encoding="utf-8"))


def _manifest_path(key: str) -> Path:
    return CONFIG_DIR / f"{key}.yaml"


_SHA256_LINE = re.compile(
    r"(?m)^([ \t]+sha256:[ \t]*)(?:null|['\"][^'\"]*['\"])([ \t]*(?:#.*)?)$"
)


def _pin_manifest_checksum(path: Path, digest: str) -> None:
    """Remplace uniquement ``integrity.sha256`` sans réécrire le YAML."""

    text = path.read_text(encoding="utf-8")
    updated, count = _SHA256_LINE.subn(r'\1"' + digest + r'"\2', text, count=1)
    if count != 1:
        raise ManifestError(f"{path} : impossible de localiser `integrity.sha256` pour le pin")
    with atomic_write(path) as handle:
        handle.write(updated)


def _known_keys() -> tuple[str, ...]:
    return tuple(sorted(set(list_keys()) | {p.stem for p in CONFIG_DIR.glob("*.yaml")}))


def _resolve_key(key: str) -> str:
    """Résout clé ou alias vers la clé canonique ; lève ``UnknownDatasetError``."""
    if key in ALIASES:
        return ALIASES[key]
    if key in REGISTRY or _manifest_path(key).is_file():
        return key
    known = ", ".join(_known_keys()) or "aucun"
    raise UnknownDatasetError(f"Dataset inconnu : {key!r}. Clés connues : {known}")


# --- version ----------------------------------------------------------------- #


def cmd_version() -> int:
    print(f"anonymisation-v2 {__version__}")
    return 0


# --- datasets list ----------------------------------------------------------- #


def cmd_datasets_list() -> int:
    """Liste les manifestes trouvés, que ou non un adaptateur est enregistré."""
    if not CONFIG_DIR.is_dir():
        print(f"Répertoire de manifestes introuvable : {CONFIG_DIR}", file=sys.stderr)
        return 1
    loaded = load_all_manifests(CONFIG_DIR)
    if not loaded:
        print(f"Aucun manifeste trouvé dans {CONFIG_DIR}.")
        return 0

    rows: list[list[str]] = []
    for key in sorted(loaded):
        m = loaded[key].manifest
        lock = _read_lock(key)
        status = lock["status"] if lock else "non ingéré"
        expected = m.integrity.expected_documents
        rows.append(
            [
                key,
                m.license.spdx if m.license.spdx else "<absent>",
                m.source.kind,
                status,
                str(expected) if expected is not None else "—",
                "implémenté" if key in REGISTRY else "non implémenté",
            ]
        )
    _print_table(
        ("CLÉ", "LICENCE", "SOURCE", "STATUT", "DOCUMENTS", "ADAPTATEUR"),
        rows,
    )
    return 0


# --- datasets describe ------------------------------------------------------- #


def cmd_datasets_describe(key: str) -> int:
    """Manifeste résolu + couverture d'ingestion si un lock existe."""
    canonical = _resolve_key(key)
    path = _manifest_path(canonical)
    if not path.is_file():
        print(f"Manifeste introuvable : {path}", file=sys.stderr)
        return 1
    loaded = load_manifest(path)
    print(f"# {canonical}")
    print(
        json.dumps(
            loaded.manifest.model_dump(mode="json"), ensure_ascii=False, indent=2,
            sort_keys=True,
        )
    )
    lock = _read_lock(canonical)
    if lock:
        print(
            "# Couverture : "
            f"statut={lock['status']} date={lock['date']} "
            f"fichiers={len(lock['files'])} fingerprint={lock['source']['fingerprint']}"
        )
    else:
        print("# Couverture : non ingéré")
    return 0


def cmd_datasets_download(key: str, force: bool, pin: bool = False) -> int:
    """Acquiert une source et écrit son rapport reproductible."""

    canonical = _resolve_key(key)
    if canonical not in REGISTRY:
        print(
            f"Adaptateur non implémenté pour {canonical!r} : "
            f"classe d'adaptateur absente du registre ({list_keys() or 'vide'}).",
            file=sys.stderr,
        )
        return 2
    path = _manifest_path(canonical)
    if not path.is_file():
        print(f"Manifeste introuvable : {path}", file=sys.stderr)
        return 1
    try:
        loaded = load_manifest(path)
        adapter = REGISTRY[canonical](loaded.manifest, RAW_ROOT / canonical)
        report = adapter.download(force=force)
        acquisition_path = report.path / ".acquisition.json"
        if not acquisition_path.is_file():
            write_json(
                acquisition_path,
                {
                    "dataset": canonical,
                    "source": loaded.manifest.source.model_dump(mode="json"),
                    "sha256": report.sha256,
                    "bytes_downloaded": report.bytes_downloaded,
                    "from_cache": report.from_cache,
                    "revision": report.revision,
                    "date": date.today().isoformat(),
                },
            )
        if pin:
            expected_digest = loaded.manifest.integrity.sha256
            if expected_digest is not None and expected_digest != report.sha256:
                raise IngestionError(
                    f"{canonical} : checksum téléchargé {report.sha256} "
                    f"différent du checksum manifeste {expected_digest}"
                )
            if expected_digest is None:
                _pin_manifest_checksum(path, report.sha256)
    except (IngestionError, LocalSourceError, ManifestError, UnmappedLabelError, OSError) as exc:
        print(f"Échec de l'acquisition de {canonical} : {exc}", file=sys.stderr)
        return 1

    print(
        f"Acquisition de {canonical} terminée : sha256={report.sha256} "
        f"octets={report.bytes_downloaded} "
        f"cache={'oui' if report.from_cache else 'non'} "
        f"révision={report.revision or 'n/a'} rapport={report.path / '.acquisition.json'}"
    )
    return 0


# --- datasets ingest --------------------------------------------------------- #


def cmd_datasets_ingest(key: str, split: str, limit: int | None, all_splits: bool) -> int:
    """Normalise vers le format pivot (SPEC-04) et publie dans ``data/processed``."""
    canonical = _resolve_key(key)
    if canonical not in REGISTRY:
        print(
            f"Adaptateur non implémenté pour {canonical!r} : "
            f"classe d'adaptateur absente du registre ({list_keys() or 'vide'}). "
            "Implémentez-la (SPEC-03 §10) puis réessayez.",
            file=sys.stderr,
        )
        return 2
    path = _manifest_path(canonical)
    if not path.is_file():
        print(f"Manifeste introuvable : {path}", file=sys.stderr)
        return 1
    try:
        loaded = load_manifest(path)
        adapter = REGISTRY[canonical](loaded.manifest, RAW_ROOT / canonical)
        result = ingest(
            adapter,
            loaded.manifest,
            split=split,
            limit=limit,
            output_root=PROCESSED_ROOT,
            resolution=loaded.resolution,
        )
    except (IngestionError, LocalSourceError, ManifestError, UnmappedLabelError) as exc:
        print(f"Échec de l'ingestion de {canonical} : {exc}", file=sys.stderr)
        return 1
    counts = result.counts
    print(
        f"Ingestion de {canonical} terminée : statut={result.status} "
        f"documents={counts.get('documents', 0)} "
        f"annotations={counts.get('annotations', 0)} lock={result.lock_path}"
    )
    return 0


# --- datasets validate ------------------------------------------------------- #


def cmd_datasets_validate(key: str) -> int:
    """Vérifie tous les invariants SPEC-02 sur les tables ingérées."""
    canonical = _resolve_key(key)
    lock = _read_lock(canonical)
    if lock is None:
        print(
            f"{canonical} non ingéré — exécutez : anonv2 datasets ingest {canonical}",
            file=sys.stderr,
        )
        return 1
    base = _dataset_dir(canonical)
    if canonical in REGISTRY and REGISTRY[canonical].streaming:
        try:
            manifest = load_manifest(_manifest_path(canonical)).manifest
            for relative, expected_digest in lock["files"].items():
                path = base / relative
                if not path.is_file():
                    raise IngestionError(f"{canonical} : fichier publié manquant : {path}")
                actual_digest = sha256_file(path)
                if actual_digest != expected_digest:
                    raise IngestionError(
                        f"{canonical} : checksum publié invalide pour {relative!r} : "
                        f"{actual_digest} != {expected_digest}"
                    )
            report = validate_streaming_output(
                canonical,
                base,
                lock["files"],
                expected_documents=manifest.integrity.expected_documents,
                expected_profiles=manifest.integrity.expected_profiles,
                expected_threads=manifest.integrity.expected_threads,
            )
        except (IngestionError, JsonlError, ManifestError, OSError) as exc:
            print(f"Échec de la validation de {canonical} : {exc}", file=sys.stderr)
            return 1
    else:
        loaded: dict[str, list] = {}
        for rel in lock["files"]:
            table = rel.split("/")[-1].rsplit(".", 1)[0]
            model = TABLE_MODELS.get(table)
            if model is None:
                continue
            loaded[table] = list(read_jsonl(base / rel, model))
        report = validate_dataset(
            canonical,
            loaded.get("documents", []),
            loaded.get("annotations", []),
            loaded.get("profiles", []),
            loaded.get("organizations", []),
            loaded.get("combinations", []),
            loaded.get("tasks", []),
        )
    print(f"Validation de {canonical} : {report.status}")
    for issue in report.issues:
        print(f"  [{issue.severity.upper()}] {issue.code} — {issue.message}")
    if not report.issues:
        print("  aucun problème détecté")
    return 1 if report.errors() else 0


# --- datasets stats ---------------------------------------------------------- #


def cmd_datasets_stats(key: str) -> int:
    """Comptes par langue, domaine, QI et mode d'expression (SPEC-07)."""
    canonical = _resolve_key(key)
    path = _dataset_dir(canonical) / VALIDATION_NAME
    if not path.is_file():
        print(
            f"{canonical} non ingéré — exécutez : anonv2 datasets ingest {canonical}",
            file=sys.stderr,
        )
        return 1
    payload = json.loads(path.read_text(encoding="utf-8"))
    counts = payload["counts"]
    print(f"Stats de {canonical} (statut validation : {payload['status']})")
    for name in TABLES:
        if name in counts:
            print(f"  {name} : {counts[name]}")
    for name in ("by_language", "by_domain", "by_qi_category", "by_expression_mode"):
        if name in counts:
            print(f"  {name} : {json.dumps(counts[name], ensure_ascii=False, sort_keys=True)}")
    return 0


# --- datasets audit-licenses ------------------------------------------------- #


def _license_row(m: DatasetManifest) -> tuple[list[str], bool]:
    """Ligne du tableau SPEC-09 §2.3 ; la 2ᵉ composante est la complétude."""
    spdx = m.license.spdx
    complete = bool(spdx) and spdx.upper() != "UNKNOWN" and bool(_SPDX_RE.match(spdx))
    redist = m.license.redistribution
    return (
        [
            m.key,
            spdx or "<absent>",
            "?" if redist is None else ("oui" if redist else "non"),
            "OUI" if m.license.restricted else "non",
            "oui" if m.evaluation.official_eligible else "NON",
        ],
        complete,
    )


def cmd_datasets_audit_licenses() -> int:
    """Tableau de conformité SPEC-09 §2.3 ; échoue si un manifeste est incomplet."""
    if not CONFIG_DIR.is_dir():
        print(f"Répertoire de manifestes introuvable : {CONFIG_DIR}", file=sys.stderr)
        return 1
    loaded = load_all_manifests(CONFIG_DIR)
    if not loaded:
        print(f"Aucun manifeste trouvé dans {CONFIG_DIR}.")
        return 0
    rows: list[list[str]] = []
    incomplete: list[str] = []
    for key in sorted(loaded):
        row, complete = _license_row(loaded[key].manifest)
        if not complete:
            incomplete.append(key)
            row.append("← bloquant")
        rows.append(row)
    _print_table(
        ("DATASET", "LICENCE", "REDISTRIB", "RESTREINT", "OFFICIAL-ELIGIBLE"),
        rows,
    )
    if incomplete:
        print(
            f"Licences incomplètes : {', '.join(incomplete)} — "
            "déclarez un identifiant SPDX officiel dans `license.spdx`.",
            file=sys.stderr,
        )
        return 1
    return 0


# --- arborescence argparse --------------------------------------------------- #


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="anonv2",
        description="Anonymisation pilotée par le risque de ré-identification.",
    )
    sub = parser.add_subparsers(dest="command")

    sub.add_parser("version", help="Affiche la version.")

    predict_p = sub.add_parser(
        "predict",
        help="Anonymise un corpus ingéré et fige le lock de reproductibilité.",
    )
    predict_p.add_argument(
        "--dataset", required=True, help="Clé ou alias du dataset ingéré."
    )
    predict_p.add_argument(
        "--split", required=True, help="Split du pivot (ex. train, validation)."
    )
    predict_p.add_argument(
        "--policy", required=True, help="Identifiant de politique (P0-P4)."
    )
    predict_p.add_argument(
        "--profile",
        default="deterministic",
        help="Profil runtime (défaut : deterministic).",
    )
    predict_p.add_argument(
        "--out",
        default=None,
        help="Répertoire de sortie (défaut : runs/predict-<...>).",
    )
    predict_p.add_argument(
        "--limit",
        type=int,
        default=None,
        help="Nombre de documents (le lock passe au statut « sampled »).",
    )

    score_p = sub.add_parser(
        "score",
        help="Calcule une scorecard depuis un run figé, sans relancer de modèle.",
    )
    score_p.add_argument("--run", required=True, help="Répertoire produit par predict.")
    score_p.add_argument("--protocol", required=True, help="Protocole d'évaluation.")

    datasets_p = sub.add_parser(
        "datasets",
        help="Acquisition, ingestion et validation des jeux de données.",
    )
    dsub = datasets_p.add_subparsers(dest="datasets_command")

    dsub.add_parser("list", help="Clés, licences, statuts, volumétrie, source.")

    describe_p = dsub.add_parser("describe", help="Manifeste résolu + couverture.")
    describe_p.add_argument("key")

    download_p = dsub.add_parser(
        "download", help="Acquiert la source et vérifie son checksum."
    )
    download_p.add_argument("key")
    download_p.add_argument("--force", action="store_true", help="Ignore le cache existant.")
    download_p.add_argument(
        "--pin", action="store_true", help="Fige le checksum s'il est absent du manifeste."
    )

    ingest_p = dsub.add_parser("ingest", help="Normalise vers le format pivot (SPEC-04).")
    ingest_p.add_argument("key")
    ingest_p.add_argument("--split", default="all", help="Split cible (défaut : tous).")
    ingest_p.add_argument(
        "--limit", type=int, default=None, help="Troncature par table."
    )
    ingest_p.add_argument(
        "--all",
        dest="all_splits",
        action="store_true",
        help="Ingeste tous les splits (défaut).",
    )

    validate_p = dsub.add_parser("validate", help="Tous les invariants SPEC-02.")
    validate_p.add_argument("key")

    stats_p = dsub.add_parser("stats", help="Comptes par langue, domaine, QI, mode.")
    stats_p.add_argument("key")

    dsub.add_parser("audit-licenses", help="Conformité des licences (SPEC-09 §2).")
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    if args.command == "version":
        return cmd_version()
    if args.command == "predict":
        from anonymisation.cli.predict import PredictError, cmd_predict
        from anonymisation.pipeline.orchestrator import PipelineCapabilityError
        from anonymisation.pipeline.profiles import ProfileError
        from anonymisation.policy.models import PolicyConfigError

        try:
            return cmd_predict(
                args.dataset,
                args.split,
                args.policy,
                args.profile,
                args.out,
                args.limit,
            )
        except (
            PredictError,
            UnknownDatasetError,
            ProfileError,
            PolicyConfigError,
            PipelineCapabilityError,
            JsonlError,
        ) as exc:
            print(f"Erreur d'usage : {exc}", file=sys.stderr)
            return 2
    if args.command == "score":
        from anonymisation.cli.score import ScoreError, cmd_score

        try:
            return cmd_score(args.run, args.protocol)
        except ScoreError as exc:
            print(f"Erreur d'usage : {exc}", file=sys.stderr)
            return 2
    if args.command != "datasets":
        parser.print_help()
        return 2
    try:
        if args.datasets_command == "list":
            return cmd_datasets_list()
        if args.datasets_command == "describe":
            return cmd_datasets_describe(args.key)
        if args.datasets_command == "download":
            return cmd_datasets_download(args.key, args.force, args.pin)
        if args.datasets_command == "ingest":
            if args.all_splits and args.split != "all":
                parser.error("--all est conflictuel avec --split distinct de 'all'")
            return cmd_datasets_ingest(args.key, args.split, args.limit, args.all_splits)
        if args.datasets_command == "validate":
            return cmd_datasets_validate(args.key)
        if args.datasets_command == "stats":
            return cmd_datasets_stats(args.key)
        if args.datasets_command == "audit-licenses":
            return cmd_datasets_audit_licenses()
    except UnknownDatasetError as exc:
        print(f"Erreur d'usage : {exc}", file=sys.stderr)
        return 2
    parser.print_help()
    return 2


def app() -> None:
    """Point d'entrée ``anonymisation.cli.main:app`` (console script)."""
    sys.exit(main())


if __name__ == "__main__":
    app()
