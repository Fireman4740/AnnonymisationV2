"""Hiérarchies de généralisation (SPEC-06 §5).

La généralisation est l'action la plus intéressante du projet : elle réduit
le risque de ré-identification sans détruire l'information (contrairement à
SUPPRESS). Chaque catégorie de QI généralisable porte une hiérarchie de
niveaux, décrite dans ``configs/generalization/hierarchies.yaml``.

Convention adoptée pour ``value_normalized`` : chaque dict porte une clé
``"level"`` (entier, 0 = valeur exacte observée) en plus des champs propres à
la catégorie. :func:`generalize` avance ce niveau de ``steps`` crans et
recalcule la représentation normalisée ; :func:`levels_available` indique
combien de crans il reste avant épuisement de la hiérarchie (0 = plus rien à
généraliser, l'action suivante doit être SUPPRESS — SPEC-01 §8).

Exemples (voir tests) :

* ``{"range": [28, 28], "level": 0}`` (GEN_AGE) -> generalize(steps=1) ->
  ``("25-29 ans", {"range": [25, 29], "level": 1})``
* ``{"geo": "FR-59350", "level": 0}`` (GEN_GEO) -> "Nord" -> "Hauts-de-France"
  -> "France"
* ``{"semver": "4.2.1", "level": 0}`` (SUP_VERSION) -> "4.2" -> "4"
"""

from __future__ import annotations

from functools import lru_cache
from pathlib import Path
from typing import Any, Callable

import yaml


class UnknownGeneralizationCategoryError(ValueError):
    """La catégorie n'a pas de hiérarchie de généralisation définie."""


class MalformedValueNormalizedError(ValueError):
    """``value_normalized`` ne correspond pas au format attendu par la catégorie."""


def _find_repo_root(start: Path) -> Path:
    """Remonte l'arborescence à la recherche de ``pyproject.toml``.

    Permet de localiser ``configs/`` indépendamment du répertoire de travail
    courant, sans dépendre d'une installation du paquet.
    """
    current = start.resolve()
    for candidate in (current, *current.parents):
        if (candidate / "pyproject.toml").exists():
            return candidate
    raise FileNotFoundError(
        "Impossible de localiser la racine du dépôt (pyproject.toml introuvable) "
        f"en remontant depuis {start}"
    )


def default_hierarchies_path() -> Path:
    return _find_repo_root(Path(__file__)) / "configs" / "generalization" / "hierarchies.yaml"


@lru_cache(maxsize=4)
def _load_hierarchies(path_str: str) -> dict[str, Any]:
    path = Path(path_str)
    with path.open("r", encoding="utf-8") as fh:
        data = yaml.safe_load(fh)
    if not isinstance(data, dict):
        raise MalformedValueNormalizedError(
            f"Fichier de hiérarchies malformé : {path} (attendu un mapping YAML)"
        )
    return data


def _get_level(value_normalized: dict[str, Any]) -> int:
    level = value_normalized.get("level", 0)
    if not isinstance(level, int) or level < 0:
        raise MalformedValueNormalizedError(f"'level' doit être un entier >= 0, reçu : {level!r}")
    return level


# --------------------------------------------------------------------------- #
# GEN_AGE
# --------------------------------------------------------------------------- #
def _max_level_age(config: dict[str, Any]) -> int:
    bucket_sizes = config.get("bucket_sizes", [])
    return len(bucket_sizes) + 1  # + niveau "tranche large"


def _generalize_age(value_normalized: dict[str, Any], level: int, config: dict[str, Any]) -> tuple[str, dict[str, Any]]:
    rng = value_normalized.get("range")
    if not (isinstance(rng, (list, tuple)) and len(rng) == 2):
        raise MalformedValueNormalizedError(f"GEN_AGE attend 'range': [low, high], reçu {value_normalized!r}")
    low, high = int(rng[0]), int(rng[1])

    bucket_sizes: list[int] = list(config.get("bucket_sizes", []))
    max_level = _max_level_age(config)

    if level < len(bucket_sizes):
        size = bucket_sizes[level]
        new_low = (low // size) * size
        new_high = new_low + size - 1
        label = f"{new_low}-{new_high} ans"
        return label, {"range": [new_low, new_high], "level": level + 1}

    if level == max_level - 1:
        bands = config.get("large_bands", [])
        reference_age = low
        for band in bands:
            max_age = band.get("max_age")
            if max_age is None or reference_age <= max_age:
                return band["label"], {"range": [low, high], "level": level + 1, "band": band["label"]}
        raise MalformedValueNormalizedError("Aucune tranche large ne couvre cet âge : vérifier hierarchies.yaml")

    raise MalformedValueNormalizedError("Niveau de généralisation GEN_AGE hors bornes")


# --------------------------------------------------------------------------- #
# GEN_GEO
# --------------------------------------------------------------------------- #
def _parse_commune(geo: str) -> str:
    # Format attendu : "FR-59350" (préfixe pays + code commune/postal).
    if "-" not in geo:
        raise MalformedValueNormalizedError(f"GEN_GEO attend un code du type 'FR-59350', reçu {geo!r}")
    _, commune = geo.split("-", 1)
    return commune


def _generalize_geo(value_normalized: dict[str, Any], level: int, config: dict[str, Any]) -> tuple[str, dict[str, Any]]:
    geo = value_normalized.get("geo")
    if not isinstance(geo, str):
        raise MalformedValueNormalizedError(f"GEN_GEO attend 'geo': str, reçu {value_normalized!r}")

    commune_to_dept: dict[str, str] = config.get("commune_to_departement", {})
    dept_labels: dict[str, str] = config.get("departement_label", {})
    dept_to_region: dict[str, str] = config.get("departement_to_region", {})
    country_label: str = config.get("country_label", "France")

    if level == 0:
        commune = _parse_commune(geo)
        dept = commune_to_dept.get(commune)
        if dept is None:
            raise MalformedValueNormalizedError(
                f"Commune {commune!r} absente de la table 'commune_to_departement' "
                f"(hierarchies.yaml) : ajouter une entrée pour la généraliser."
            )
        label = dept_labels.get(dept, dept)
        return label, {"geo": geo, "departement": dept, "level": 1}

    if level == 1:
        dept = value_normalized.get("departement")
        if dept is None:
            raise MalformedValueNormalizedError("Niveau 1 GEN_GEO requiert 'departement' dans value_normalized")
        region = dept_to_region.get(dept)
        if region is None:
            raise MalformedValueNormalizedError(
                f"Département {dept!r} absent de 'departement_to_region' (hierarchies.yaml)"
            )
        return region, {"geo": geo, "departement": dept, "region": region, "level": 2}

    if level == 2:
        return country_label, {"geo": geo, "level": 3, "country": country_label}

    raise MalformedValueNormalizedError("Niveau de généralisation GEN_GEO hors bornes")


def _max_level_geo(_config: dict[str, Any]) -> int:
    return 3  # commune(0) -> departement(1) -> region(2) -> pays(3, dernier)


# --------------------------------------------------------------------------- #
# GEN_OCCUPATION
# --------------------------------------------------------------------------- #
def _max_level_occupation(config: dict[str, Any]) -> int:
    return int(config.get("code_levels", 4)) - 1


def _generalize_occupation(value_normalized: dict[str, Any], level: int, config: dict[str, Any]) -> tuple[str, dict[str, Any]]:
    code = value_normalized.get("code")
    if not isinstance(code, str) or not code:
        raise MalformedValueNormalizedError(f"GEN_OCCUPATION attend 'code': str non vide, reçu {value_normalized!r}")
    if level >= _max_level_occupation({"code_levels": len(code)}):
        raise MalformedValueNormalizedError("Niveau de généralisation GEN_OCCUPATION hors bornes")
    # Simplification : chaque niveau retire un chiffre depuis la droite.
    new_code = code[: max(1, len(code) - (level + 1))]
    return new_code, {"code": code, "level": level + 1, "code_generalise": new_code}


# --------------------------------------------------------------------------- #
# GEN_EDUCATION
# --------------------------------------------------------------------------- #
def _max_level_education(_config: dict[str, Any]) -> int:
    return 2  # discipline(0) -> domaine(1) -> niveau seul(2, dernier)


def _generalize_education(value_normalized: dict[str, Any], level: int, config: dict[str, Any]) -> tuple[str, dict[str, Any]]:
    discipline_to_domain: dict[str, str] = config.get("discipline_to_domain", {})

    if level == 0:
        discipline = value_normalized.get("discipline")
        if not discipline:
            raise MalformedValueNormalizedError("GEN_EDUCATION niveau 0 requiert 'discipline'")
        domain = discipline_to_domain.get(str(discipline).lower())
        if domain is None:
            raise MalformedValueNormalizedError(
                f"Discipline {discipline!r} absente de 'discipline_to_domain' (hierarchies.yaml)"
            )
        new_value = dict(value_normalized)
        new_value.update({"domain": domain, "level": 1})
        return domain, new_value

    if level == 1:
        education_level = value_normalized.get("level_edu")
        if not education_level:
            raise MalformedValueNormalizedError("GEN_EDUCATION niveau 1 requiert 'level_edu'")
        new_value = dict(value_normalized)
        new_value["level"] = 2
        return str(education_level), new_value

    raise MalformedValueNormalizedError("Niveau de généralisation GEN_EDUCATION hors bornes")


# --------------------------------------------------------------------------- #
# HR_EMPLOYER_SIZE
# --------------------------------------------------------------------------- #
def _max_level_employer_size(_config: dict[str, Any]) -> int:
    return 1  # fine(0) -> large(1, dernier)


def _generalize_employer_size(value_normalized: dict[str, Any], level: int, config: dict[str, Any]) -> tuple[str, dict[str, Any]]:
    fine_to_large: dict[str, str] = config.get("fine_to_large", {})
    band = value_normalized.get("band")
    if not isinstance(band, str):
        raise MalformedValueNormalizedError(f"HR_EMPLOYER_SIZE attend 'band': str, reçu {value_normalized!r}")
    if level != 0:
        raise MalformedValueNormalizedError("Niveau de généralisation HR_EMPLOYER_SIZE hors bornes")
    large = fine_to_large.get(band)
    if large is None:
        raise MalformedValueNormalizedError(f"Tranche {band!r} absente de 'fine_to_large' (hierarchies.yaml)")
    return large, {"band": band, "level": 1, "band_large": large}


# --------------------------------------------------------------------------- #
# SUP_VERSION
# --------------------------------------------------------------------------- #
def _max_level_version(_config: dict[str, Any]) -> int:
    return 2  # patch(0) -> mineure(1) -> majeure(2, dernier)


def _generalize_version(value_normalized: dict[str, Any], level: int, _config: dict[str, Any]) -> tuple[str, dict[str, Any]]:
    semver = value_normalized.get("semver")
    if not isinstance(semver, str):
        raise MalformedValueNormalizedError(f"SUP_VERSION attend 'semver': str, reçu {value_normalized!r}")
    parts = semver.split(".")
    if level == 0:
        if len(parts) < 2:
            raise MalformedValueNormalizedError(f"semver {semver!r} n'a pas de composante mineure")
        new_surface = ".".join(parts[:2])
        return new_surface, {"semver": semver, "level": 1}
    if level == 1:
        new_surface = parts[0]
        return new_surface, {"semver": semver, "level": 2}
    raise MalformedValueNormalizedError("Niveau de généralisation SUP_VERSION hors bornes")


# --------------------------------------------------------------------------- #
# SUP_INCIDENT_TIME
# --------------------------------------------------------------------------- #
def _max_level_incident_time(_config: dict[str, Any]) -> int:
    return 2  # heure(0) -> demi-journée(1) -> jour(2, dernier)


def _generalize_incident_time(value_normalized: dict[str, Any], level: int, config: dict[str, Any]) -> tuple[str, dict[str, Any]]:
    time_str = value_normalized.get("time")
    date_str = value_normalized.get("date")
    if level == 0:
        if not isinstance(time_str, str) or ":" not in time_str:
            raise MalformedValueNormalizedError(f"SUP_INCIDENT_TIME attend 'time': 'HH:MM', reçu {value_normalized!r}")
        hour = int(time_str.split(":")[0])
        midday = int(config.get("midday_hour", 12))
        half = "matin" if hour < midday else "après-midi"
        return half, {"time": time_str, "date": date_str, "level": 1, "half": half}
    if level == 1:
        if not date_str:
            raise MalformedValueNormalizedError("SUP_INCIDENT_TIME niveau 1 requiert 'date'")
        return str(date_str), {"time": time_str, "date": date_str, "level": 2}
    raise MalformedValueNormalizedError("Niveau de généralisation SUP_INCIDENT_TIME hors bornes")


# --------------------------------------------------------------------------- #
# Table de dispatch
# --------------------------------------------------------------------------- #
_GENERALIZERS: dict[str, Callable[[dict[str, Any], int, dict[str, Any]], tuple[str, dict[str, Any]]]] = {
    "GEN_AGE": _generalize_age,
    "GEN_GEO": _generalize_geo,
    "GEN_OCCUPATION": _generalize_occupation,
    "GEN_EDUCATION": _generalize_education,
    "HR_EMPLOYER_SIZE": _generalize_employer_size,
    "SUP_VERSION": _generalize_version,
    "SUP_INCIDENT_TIME": _generalize_incident_time,
}

_MAX_LEVELS: dict[str, Callable[[dict[str, Any]], int]] = {
    "GEN_AGE": _max_level_age,
    "GEN_GEO": _max_level_geo,
    "GEN_OCCUPATION": _max_level_occupation,
    "GEN_EDUCATION": _max_level_education,
    "HR_EMPLOYER_SIZE": _max_level_employer_size,
    "SUP_VERSION": _max_level_version,
    "SUP_INCIDENT_TIME": _max_level_incident_time,
}


def _config_for(qi_category: str, hierarchies_path: Path | None) -> dict[str, Any]:
    if qi_category not in _GENERALIZERS:
        raise UnknownGeneralizationCategoryError(
            f"Aucune hiérarchie de généralisation pour {qi_category!r}. "
            f"Catégories disponibles : {sorted(_GENERALIZERS)}."
        )
    path = hierarchies_path or default_hierarchies_path()
    data = _load_hierarchies(str(path))
    return data.get(qi_category, {}) or {}


def levels_available(value_normalized: dict[str, Any], qi_category: str, *, hierarchies_path: Path | None = None) -> int:
    """Nombre de niveaux de généralisation encore disponibles pour cette valeur.

    0 signifie que la hiérarchie est épuisée : SUPPRESS est la seule action
    restante (SPEC-01 §8, granularity=COARSE).
    """
    config = _config_for(qi_category, hierarchies_path)
    max_level = _MAX_LEVELS[qi_category](config)
    current_level = _get_level(value_normalized)
    return max(0, max_level - current_level)


def generalize(
    value_normalized: dict[str, Any],
    qi_category: str,
    steps: int = 1,
    *,
    hierarchies_path: Path | None = None,
) -> tuple[str, dict[str, Any]] | None:
    """Généralise ``value_normalized`` de ``steps`` niveaux.

    Retourne ``(surface_generalisee, nouvelle_value_normalized)``, ou
    ``None`` si la hiérarchie est déjà épuisée ou si ``steps`` dépasse ce qui
    reste disponible (plutôt que de tronquer silencieusement).
    """
    if steps < 1:
        raise ValueError("steps doit être >= 1")

    available = levels_available(value_normalized, qi_category, hierarchies_path=hierarchies_path)
    if available <= 0 or steps > available:
        return None

    config = _config_for(qi_category, hierarchies_path)
    generalizer = _GENERALIZERS[qi_category]

    current = dict(value_normalized)
    surface = ""
    for _ in range(steps):
        level = _get_level(current)
        surface, current = generalizer(current, level, config)
    return surface, current
