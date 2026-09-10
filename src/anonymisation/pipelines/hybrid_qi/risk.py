"""Risque de ré-identification hybride : QICR + copule gaussienne (SPEC-06 §6-§7).

Contrastes avec l'estimateur naïf du noyau v1 :

- **QICR** : les attributs sont normalisés (JSON canonique), dédupliqués sur
  ``(catégorie, valeur, coréférence)`` et fusionnés par coréférence — deux
  mentions du même âge n'entrent qu'une fois dans le produit ;
- **copule gaussienne** : la masse conjointe du tuple d'attributs est
  ``N · Π p_j · c_Σ`` avec ``c_Σ = det(Σ)^(-1/2) · exp(-½ zᵀ(Σ⁻¹−I)z)`` et
  ``z_j = Φ⁻¹(p_j)`` — une approximation déterministe en bibliothèque
  standard, jamais le produit indépendant de l'estimateur naïf ;
- **calibration** : un monde de référence synthétique reproductible (seed 42)
  où la vraie masse de chaque combinaison est **connue par construction**
  (attributs indépendants, valeurs géométriques) ; le résidu ``k_true /
  k_brut`` étalonne l'intervalle (quantiles par strate de taille) et le point
  (régression isotone). Audit **DIAGNOSTIC** de généralisation : le scope est
  ``synthetic`` et aucun chiffre produit ici ne devient OFFICIAL sur un
  dataset DIAGNOSTIC.

Règle d'or : une valeur sans probabilité configurée **et** sans prior
ordinal lève :class:`RiskInputError` (catégorie, valeur, fichier) — jamais
la valeur inconnue de l'estimateur naïf.
"""

from __future__ import annotations

import itertools
import json
import math
import random
from collections.abc import Mapping
from pathlib import Path
from typing import Any, Final

import yaml
from pydantic import BaseModel, ConfigDict, Field, field_validator

from anonymisation.schema.taxonomy import OUT_OF_SCOPE_V1, QUASI_CODES, validate_code


# --------------------------------------------------------------------------- #
# Erreurs
# --------------------------------------------------------------------------- #
class RiskConfigError(RuntimeError):
    """Population non utilisable : matrice invalide, probabilité hors bornes,
    code inconnu — nomme le fichier fautif."""


class RiskInputError(RuntimeError):
    """Valeur QI sans probabilité ni prior ordinal (jamais de défaut silencieux)."""

    def __init__(self, *, category: str, value: Any, file: Path | str) -> None:
        self.category = category
        self.value = value
        self.file = str(file)
        super().__init__(
            f"risque : aucune probabilité pour la catégorie {category!r} "
            f"(valeur {value!r}) : ajoutez-la à ``category_selectivity`` ou "
            f"fournissez un prior ordinal dans {self.file}"
        )


# --------------------------------------------------------------------------- #
# Constantes
# --------------------------------------------------------------------------- #
#: Modes d'expression acceptés (SPEC-01).
EXPRESSION_MODES: Final[tuple[str, ...]] = ("EXPLICIT", "NON_STANDARD", "IMPLICIT")

#: Niveaux ordinaux de rareté (SPEC-06 §6).
PRIOR_LEVELS: Final[tuple[str, ...]] = ("rare", "uncommon", "common")

#: Seuil de crédibilité d'une claim d'unicité « vraie » (même seuil que
#: l'audit attaque).
CLAIM_TRUST_THRESHOLD: Final[float] = 0.70

#: Taille de la population de calibration synthétique (seed 42) ; la vraie
#: masse y est connue par construction, aucun record n'est matérialisé.
_CAL_POPULATION_SIZE: Final[int] = 100_000
_CAL_VALUES_PER_ATTR: Final[int] = 8
_CAL_SAMPLES_PER_SUBSET: Final[int] = 20
_CAL_MAX_SUBSET: Final[int] = 3
#: Facteur de décroissance de la fréquence des valeurs synthétiques.
_CAL_VALUE_DECAY: Final[float] = 0.55


# --------------------------------------------------------------------------- #
# Modèles immuables
# --------------------------------------------------------------------------- #
class UniquenessClaim(BaseModel):
    """Claim d'unicité détectée dans le document (partie de Q(d), jamais une
    « catégorie » à part entière)."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    evidence: str
    confidence: float = Field(ge=0.0, le=1.0)


class QiAttribute(BaseModel):
    """Un quasi-identifiant du document : catégorie, valeur normalisée et
    provenance — l'entrée du risque (QICR)."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    category: str
    value: dict[str, Any]
    expression_mode: str
    explicit: bool
    start: int | None = None
    end: int | None = None
    confidence: float = Field(default=1.0, ge=0.0, le=1.0)
    prior: str | None = None
    entity_ref: str | None = None
    source: str = "native"

    @field_validator("category")
    @classmethod
    def _check_category(cls, v: str) -> str:
        validate_code(v)
        return v

    @field_validator("expression_mode")
    @classmethod
    def _check_mode(cls, v: str) -> str:
        if v not in EXPRESSION_MODES:
            raise ValueError(f"mode d'expression {v!r} hors {EXPRESSION_MODES}")
        return v

    @field_validator("prior")
    @classmethod
    def _check_prior(cls, v: str | None) -> str | None:
        if v is not None and v not in PRIOR_LEVELS:
            raise ValueError(f"prior {v!r} hors {PRIOR_LEVELS}")
        return v

    @property
    def key(self) -> tuple[str, str, str | None]:
        """Clé QICR : ``(catégorie, valeur JSON canonique, coréférence)``."""
        return (self.category, _canonical_json(self.value), self.entity_ref)


class CalibrationStats(BaseModel):
    """Résultats de la calibration synthétique (seed 42, DIAGNOSTIC).

    Trois strates, une par taille de combinaison d'audit (1, 2, 3) : le
    comportement du modèle (sélectivité forfaitaire + approximation copule)
    diffère selon la profondeur du produit.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    scope: str = "synthetic"
    seed: int = 42
    n_combinations: int
    #: Quantile 0.05 du résidu ``k_true / k_brut`` par strate (1, 2, 3).
    q_low_residual: tuple[float, float, float]
    #: Quantile 0.95 du résidu par strate.
    q_high_residual: tuple[float, float, float]
    #: Régression isotone par strate : segments ``(x_borne, y)`` en croissant.
    isotone: dict[int, tuple[tuple[float, float], ...]]
    ece: float
    brier: float
    male_k: float


class HybridRiskEstimate(BaseModel):
    """Estimation de risque copule d'un document (jamais OFFICIAL)."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    population_id: str
    k_hat: float
    k_interval: tuple[float, float]
    #: Risque de décision (borne haute : ``1 / k_low`` si ``use_upper_bound``).
    risk: float
    #: Risque point après calibration isotone.
    risk_point: float
    risk_model: str = "copula"
    contributing_qi: tuple[str, ...] = ()
    uniqueness_claim: UniquenessClaim | None = None
    status: str = "DIAGNOSTIC"
    calibration_scope: str = "synthetic"
    combination_truncated: bool = False
    total_qi_count: int = 0
    explanation: str = ""

    @field_validator("k_interval")
    @classmethod
    def _check_interval(cls, v: tuple[float, float]) -> tuple[float, float]:
        if v[0] > v[1]:
            raise ValueError("k_interval : la borne basse dépasse la haute")
        return v


class PopulationConfig(BaseModel):
    """Population versionnée (``population.yaml`` du paquet)."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    population_id: str
    kind: str = "synthetic"
    size: int = Field(ge=1)
    prior_probabilities: dict[str, float]
    category_selectivity: dict[str, float]
    correlated_attributes: tuple[str, ...]
    correlation_off_diagonal: float

    @field_validator("prior_probabilities")
    @classmethod
    def _check_priors(cls, v: dict[str, float]) -> dict[str, float]:
        if set(v) != set(PRIOR_LEVELS):
            raise ValueError(
                f"prior_probabilities doit couvrir exactement {PRIOR_LEVELS} "
                f"(trouvé : {sorted(v)})"
            )
        for k, p in v.items():
            if not 0.0 < p < 1.0:
                raise ValueError(f"prior {k}={p} hors ]0,1[")
        return v

    @field_validator("category_selectivity")
    @classmethod
    def _check_selectivity(cls, v: dict[str, float]) -> dict[str, float]:
        for code, p in v.items():
            if code != "OTHER_QI":
                validate_code(code)
            if code in OUT_OF_SCOPE_V1 and code in QUASI_CODES:
                raise ValueError(f"catégorie hors périmètre v1 : {code}")
            if not 0.0 < p < 1.0:
                raise ValueError(f"sélectivité {code}={p} hors ]0,1[")
        return v

    @field_validator("correlated_attributes")
    @classmethod
    def _check_correlated(cls, v: tuple[str, ...]) -> tuple[str, ...]:
        if len(v) != len(set(v)):
            raise ValueError("correlated_attributes contient des doublons")
        for code in v:
            validate_code(code)
            if code in OUT_OF_SCOPE_V1 and code in QUASI_CODES:
                raise ValueError(f"catégorie corrélée hors périmètre v1 : {code}")
        if len(v) < 1:
            raise ValueError("correlated_attributes est vide")
        return v

    @field_validator("correlation_off_diagonal")
    @classmethod
    def _check_offdiagonal(cls, v: float) -> float:
        if not -1.0 < v < 1.0:
            raise ValueError(f"correlation_off_diagonal={v} hors ]-1,1[")
        return v

    def correlation_matrix(self) -> list[list[float]]:
        """Matrice de corrélation ``m×m`` : diagonale 1, hors-diagonale
        constante (validée définie-positives au chargement)."""
        m = len(self.correlated_attributes)
        return [
            [1.0 if i == j else self.correlation_off_diagonal for j in range(m)]
            for i in range(m)
        ]

    def probability_of(
        self, attribute: QiAttribute, level: int = 0
    ) -> float | None:
        """Probabilité de l'attribut : valeur configurée → prior ordinal →
        sélectivité de catégorie. ``None`` si aucune source n'existe (le
        risque échoue alors — jamais de défaut)."""
        value = attribute.value or {}
        if isinstance(value, dict) and "selectivity" in value:
            p = float(value["selectivity"])
        elif attribute.prior in self.prior_probabilities:
            p = self.prior_probabilities[attribute.prior]
        elif attribute.category in self.category_selectivity:
            p = self.category_selectivity[attribute.category]
        else:
            return None
        # Une généralisation élargit la classe d'équivalence (même facteur
        # que l'estimateur naïf, SPEC-06 §8).
        if level > 0:
            p = p * (4.0 ** level)
        return min(max(p, 1e-6), 1.0 - 1e-6)


# --------------------------------------------------------------------------- #
# Algèbre linéaire déterministe (bibliothèque standard)
# --------------------------------------------------------------------------- #
def _det(m: list[list[float]]) -> float:
    """Déterminant par élimination de Gauss avec pivot partiel."""
    n = len(m)
    a = [row[:] for row in m]
    sign = 1.0
    for col in range(n):
        pivot = max(range(col, n), key=lambda r: abs(a[r][col]))
        if abs(a[pivot][col]) < 1e-12:
            return 0.0
        if pivot != col:
            a[col], a[pivot] = a[pivot], a[col]
            sign = -sign
        for r in range(col + 1, n):
            factor = a[r][col] / a[col][col]
            if factor:
                for c in range(col, n):
                    a[r][c] -= factor * a[col][c]
    return sign * math.prod(a[i][i] for i in range(n))


def _inverse(m: list[list[float]]) -> list[list[float]]:
    """Inverse par Gauss-Jordan avec pivot partiel."""
    n = len(m)
    a = [row[:] for row in m]
    inv = [[1.0 if i == j else 0.0 for j in range(n)] for i in range(n)]
    for col in range(n):
        pivot = max(range(col, n), key=lambda r: abs(a[r][col]))
        if abs(a[pivot][col]) < 1e-12:
            raise ValueError("matrice non inversible")
        if pivot != col:
            a[col], a[pivot] = a[pivot], a[col]
            inv[col], inv[pivot] = inv[pivot], inv[col]
        pivot_val = a[col][col]
        a[col] = [v / pivot_val for v in a[col]]
        inv[col] = [v / pivot_val for v in inv[col]]
        for r in range(n):
            if r != col and a[r][col]:
                factor = a[r][col]
                a[r] = [a[r][c] - factor * a[col][c] for c in range(n)]
                inv[r] = [inv[r][c] - factor * inv[col][c] for c in range(n)]
    return inv


def is_positive_definite(m: list[list[float]]) -> bool:
    """Déterminisme : Cholesky sans pivot — un pivot ≤ 0 invalide la matrice."""
    n = len(m)
    a = [row[:] for row in m]
    for i in range(n):
        for j in range(i):
            a[i][j] -= sum(a[i][k] * a[j][k] for k in range(j))
        if a[i][i] <= 1e-12:
            return False
        pivot = a[i][i]
        for j in range(i + 1, n):
            a[j][i] = a[j][i] / pivot
            for k in range(i + 1, n):
                a[j][k] -= a[j][i] * a[i][k]
    return True


_SQRT2: Final[float] = math.sqrt(2.0)
_SQRT_2PI: Final[float] = math.sqrt(2.0 * math.pi)


def _cdf(z: float) -> float:
    """Cumulée de la normale centrée réduite, en double via ``erfc``."""
    return 0.5 * math.erfc(-z / _SQRT2)


def _inv_cdf(p: float) -> float:
    """Quantile de la normale centrée réduite.

    Bissection bornée + pas de Newton (évalué contre la cumulée ``erfc``)
    : déterministe, pur bibliothèque standard, précision ~1e-15 sur
    ``p ∈ ]0,1[`` — aucune table de coefficients à maintenir.
    """
    if not 0.0 < p < 1.0:
        raise ValueError(f"p={p} hors ]0,1[")
    if p == 0.5:
        return 0.0
    if p > 0.5:
        lo, hi = 0.0, 10.0
        z = min(hi, max(lo, math.sqrt(-2.0 * math.log(1.0 - p))))
    else:
        lo, hi = -10.0, 0.0
        z = min(hi, max(lo, -math.sqrt(-2.0 * math.log(p))))
    for _ in range(128):
        fz = _cdf(z) - p
        if abs(fz) < 1e-15:
            break
        if fz < 0.0:
            lo = z
        else:
            hi = z
        # Pas de Newton borné : au-delà d'une unité de déplacement,
        # repli sur la bissection (convergence garantie du bracket).
        phi = math.exp(-0.5 * z * z) / _SQRT_2PI
        step = fz / phi
        z_new = z - step if lo < z - step < hi and abs(step) <= 1.0 else 0.5 * (lo + hi)
        if z_new == z:
            break
        z = z_new
    return z


def copula_factor(z: list[float], sigma: list[list[float]]) -> float:
    """Rapport masse conjointe / produit des marginales :
    ``det(Σ)^(-1/2) · exp(-½ zᵀ(Σ⁻¹ − I)z)``.

    Égal à 1 quand Σ = I (indépendance) ; > 1 pour des corrélations positives
    concentrant la masse autour des moyennes.
    """
    n = len(z)
    det = _det(sigma)
    if det <= 0.0:
        raise RiskConfigError("matrice de corrélation au déterminant non strictement positif")
    inv = _inverse(sigma)
    quad = 0.0
    for i in range(n):
        for j in range(n):
            term = inv[i][j] - (1.0 if i == j else 0.0)
            quad += z[i] * term * z[j]
    return det ** -0.5 * math.exp(-0.5 * quad)


# --------------------------------------------------------------------------- #
# Calibration synthétique (seed 42 — DIAGNOSTIC, jamais OFFICIAL)
# --------------------------------------------------------------------------- #
#: Les six attributs corrélés de la population de référence.
_CAL_ATTRS: Final[tuple[str, ...]] = (
    "GEN_AGE",
    "GEN_GEO",
    "GEN_EDUCATION",
    "GEN_OCCUPATION",
    "HR_SENIORITY",
    "HR_EMPLOYER_SIZE",
)
_CAL_SELECTIVITY: Final[dict[str, float]] = {
    "GEN_AGE": 0.02,
    "GEN_GEO": 0.005,
    "GEN_EDUCATION": 0.08,
    "GEN_OCCUPATION": 0.05,
    "HR_SENIORITY": 0.20,
    "HR_EMPLOYER_SIZE": 0.10,
}


def _canonical_json(value: dict[str, Any]) -> str:
    """Forme canonique JSON d'une valeur normalisée (tri des clés)."""
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=True)


def _quantile(sorted_values: list[float], q: float) -> float:
    """Quantile par interpolation linéaire sur une liste triée."""
    if not sorted_values:
        raise ValueError("quantile d'une liste vide")
    if len(sorted_values) == 1:
        return sorted_values[0]
    idx = (len(sorted_values) - 1) * q
    lo = int(idx)
    hi = min(lo + 1, len(sorted_values) - 1)
    return sorted_values[lo] + (sorted_values[hi] - sorted_values[lo]) * (idx - lo)


def _isotone_fit(points: list[tuple[float, float]]) -> list[tuple[float, float]]:
    """Régression isotone (pool-adjacent-violators, pur) de ``y`` sur ``x``.

    Retourne un escalier ``(x_borne, y)`` en croissant : la valeur au point
    ``x`` est la ``y`` du dernier segment de borne ≤ ``x``.
    """
    order = sorted(
        enumerate(points), key=lambda t: (t[1][0], t[1][1], t[0])
    )
    blocks: list[list[float]] = []  # [somme_y, count, x_borne, x_fin]
    for _, (x, y) in order:
        block = [y, 1.0, x, x]
        while blocks and blocks[-1][0] / blocks[-1][1] > block[0] / block[1]:
            prev = blocks.pop()
            block[0] += prev[0]
            block[1] += prev[1]
            block[2] = prev[2]
        blocks.append(block)
    return [(blk[2], blk[0] / blk[1]) for blk in blocks]


def _apply_isotone(segments: list[tuple[float, float]], x: float) -> float:
    """Applique l'escalier isotone (dernier segment de borne ≤ x)."""
    if not segments:
        raise ValueError("isotone vide")
    out = segments[0][1]
    for x_lo, y in segments:
        if x_lo <= x:
            out = y
        else:
            break
    return out


def _run_calibration() -> CalibrationStats:
    """Étalonnage déterministe (seed 42).

    Le monde de référence est connu par construction : les six attributs y
    sont indépendants, chacun tiré d'une distribution géométrique de 8
    valeurs. La vraie masse d'une combinaison est donc
    ``k_true = N · Π w(v_j)`` — aucune échantillonnage, aucun bruit de
    comptage. ``k_brut`` est la masse que le modèle copule prétend ; le
    résidu ``k_true / k_brut`` mesure l'erreur du modèle (sélectivité
    forfaitaire + approximation copule), pas le bruit de sampling.

    Stratifié par taille de combinaison (1, 2, 3) : quantiles de résidu de
    l'intervalle et escalier isotone du point. Métriques globales : ECE (10
    bacs équipopulés), Brier, MALE-k.
    """
    rng = random.Random(42)
    raw_w = [_CAL_VALUE_DECAY**i for i in range(_CAL_VALUES_PER_ATTR)]
    total = sum(raw_w)
    weights = [w / total for w in raw_w]

    # 1) combinaisons d'audit : sous-ensembles d'attributs jusqu'à 3,
    #    échantillonnés puis dédupliqués.
    combos: list[tuple[tuple[int, int], ...]] = []
    seen: set[frozenset] = set()
    for size in range(1, _CAL_MAX_SUBSET + 1):
        for subset in itertools.combinations(range(len(_CAL_ATTRS)), size):
            for _ in range(_CAL_SAMPLES_PER_SUBSET):
                assignment = tuple(
                    (idx, rng.choices(range(_CAL_VALUES_PER_ATTR), weights=weights, k=1)[0])
                    for idx in subset
                )
                key = frozenset(assignment)
                if key not in seen:
                    seen.add(key)
                    combos.append(assignment)
    # Ordre déterministe du traitement (le contenu de ``seen`` dépend des
    # tirages : on trie pour figer la suite).
    combos.sort(key=lambda a: tuple(a))

    # 2) pour chaque combinaison : k_true exact (monde connu), k_brut modèle.
    sigma_full = _sigma_for(_CAL_ATTRS, _CAL_ATTRS, 0.20)
    points: list[tuple[int, float, float, float, float]] = []
    for assignment in combos:
        size = len(assignment)
        p = [
            _CAL_SELECTIVITY[_CAL_ATTRS[idx]]
            for idx, _ in assignment
        ]
        sigma = _sigma_for(
            tuple(_CAL_ATTRS[idx] for idx, _ in assignment), _CAL_ATTRS, 0.20, parent=sigma_full
        )
        z = [_inv_cdf(x) for x in p]
        k_raw = (
            _CAL_POPULATION_SIZE
            * math.prod(p)
            * copula_factor(z, sigma)
        )
        k_true = _CAL_POPULATION_SIZE * math.prod(
            weights[val] for _, val in assignment
        )
        points.append(
            (size, 1.0 / max(1.0, k_raw), 1.0 / max(1.0, k_true), k_raw, k_true)
        )

    # 3) stratification par taille : quantiles de résidu + isotone.
    q_lo: list[float] = []
    q_hi: list[float] = []
    isotone: dict[int, tuple[tuple[float, float], ...]] = {}
    for size in (1, 2, 3):
        strata = [pt for pt in points if pt[0] == size]
        res = sorted(
            k_true / max(1e-9, k_raw)
            for _, _, _, k_raw, k_true in strata
        )
        q_lo.append(_quantile(res, 0.05))
        q_hi.append(_quantile(res, 0.95))
        isotone[size] = tuple(_isotone_fit([(x, y) for _, x, y, _, _ in strata]))

    # 4) métriques globales.
    n = len(points)
    indexed = sorted(
        range(n), key=lambda i: (points[i][1], points[i][2], i)
    )
    ece = 0.0
    brier = 0.0
    male_k = 0.0
    bin_size = max(1, n // 10)
    for b in range(0, n, bin_size):
        chunk = indexed[b : b + bin_size]
        w = len(chunk) / n
        mean_pred = sum(
            _apply_isotone(list(isotone[points[i][0]]), points[i][1]) for i in chunk
        ) / len(chunk)
        mean_true = sum(points[i][2] for i in chunk) / len(chunk)
        ece += w * abs(mean_pred - mean_true)
    for i in range(n):
        pred = _apply_isotone(list(isotone[points[i][0]]), points[i][1])
        brier += (pred - points[i][2]) ** 2
        male_k += abs(
            math.log2(max(points[i][3], 1e-9)) - math.log2(max(points[i][4], 1.0))
        )
    brier /= n
    male_k /= n

    return CalibrationStats(
        n_combinations=n,
        q_low_residual=tuple(q_lo),
        q_high_residual=tuple(q_hi),
        isotone=isotone,
        ece=ece,
        brier=brier,
        male_k=male_k,
    )


def _sigma_for(
    present: tuple[str, ...],
    correlated_order: tuple[str, ...],
    off_diagonal: float,
    parent: list[list[float]] | None = None,
) -> list[list[float]]:
    """Sigma bloc-diagonale : sous-matrice corrélée (ordre canonique) ⊕
    identité pour les catégories indépendantes présentes."""
    corr_idx = [correlated_order.index(c) for c in present if c in correlated_order]
    n_corr = len(corr_idx)
    if parent is not None:
        block = [
            [parent[i][j] for j in corr_idx] for i in corr_idx
        ]
    else:
        block = [
            [1.0 if i == j else off_diagonal for j in range(n_corr)]
            for i in range(n_corr)
        ]
    n_ind = len(present) - n_corr
    if n_ind:
        ident = [[1.0 if i == j else 0.0 for j in range(n_ind)] for i in range(n_ind)]
        width = n_corr + n_ind
        full: list[list[float]] = [
            [0.0] * width for _ in range(width)
        ]
        for i in range(n_corr):
            for j in range(n_corr):
                full[i][j] = block[i][j]
        for i in range(n_ind):
            for j in range(n_ind):
                full[n_corr + i][n_corr + j] = ident[i][j]
        return full
    return block


_CALIBRATION: CalibrationStats | None = None


def get_calibration() -> CalibrationStats:
    """Calibration synthétique — calculée une fois par processus, identique
    quel que soit le run (seed 42)."""
    global _CALIBRATION
    if _CALIBRATION is None:
        _CALIBRATION = _run_calibration()
    return _CALIBRATION


# --------------------------------------------------------------------------- #
# Attributs Q(d)
# --------------------------------------------------------------------------- #

def annotation_attribute_key(annotation) -> tuple[str, str, str | None]:
    """Clé d'attribut de risque d'une annotation : même normalisation que
    ``build_qi_attributes`` (premier code, valeur normalisée canonique,
    coréférence) — permet d'associer annotations <-> attributs sans
    recalculer Q(d).

    ``annotation`` : ``Annotation`` (type ``Any`` pour éviter une
    dépendance circulaire).
    """
    if not annotation.qi_categories:
        raise ValueError(
            f"annotation {getattr(annotation, 'annotation_id', '?')!r} : "
            "qi_categories vide — impossible de l'associer à un attribut de "
            "risque (une annotation de QI porte au moins un code SPEC-01)."
        )
    value = annotation.value_normalized if annotation.value_normalized else {}
    return (
        annotation.qi_categories[0],
        _canonical_json(value),
        annotation.entity_id,
    )


def attribute_keys_for_annotation(annotation) -> frozenset[tuple[str, str, str | None]]:
    """Toutes les clés d'attribut de risque portées par une annotation —
    une par code de ``qi_categories`` (même valeur normalisée, même
    coréférence), même normalisation que ``build_qi_attributes``.

    Sert au planificateur à distinguer les attributs **éditables**
    (portés par une annotation positionnelle) des QI implicites sans span
    (jamais anonymisables, toujours actifs dans le risque résiduel).
    """
    if not annotation.qi_categories:
        return frozenset()
    value = annotation.value_normalized if annotation.value_normalized else {}
    canonical = _canonical_json(value)
    return frozenset(
        (code, canonical, annotation.entity_id) for code in annotation.qi_categories
    )


def build_qi_attributes(
    *,
    annotations: Any,
    extraction: Any | None = None,
) -> tuple[QiAttribute, ...]:
    """Q(d) : attributs issus des annotations détectées + QI implicites/
    explicites de l'extracteur (dédupliqués contre le natif sur
    ``(catégorie, start, end)``).

    ``annotations`` est une séquence d'``Annotation`` (type any pour éviter
    une dépendance circulaire) ; ``extraction`` un ``QiExtraction``
    (``prompts.py``) ou ``None``.
    """
    from anonymisation.schema.models import ExpressionMode, IdentifierType

    attributes: list[QiAttribute] = []
    seen: set[tuple[str, int, int]] = set()

    for ann in annotations:
        if ann.identifier_type is IdentifierType.DIRECT:
            continue  # un identifiant direct n'est pas un quasi-identifiant
        value = ann.value_normalized if ann.value_normalized else {}
        explicit = ann.expression_mode is not ExpressionMode.IMPLICIT
        source = str(ann.meta.get("source", "native"))
        for code in ann.qi_categories:
            seen.add((code, ann.start if ann.start is not None else -1, ann.end if ann.end is not None else -1))
            attributes.append(
                QiAttribute(
                    category=code,
                    value=dict(value),
                    expression_mode=ann.expression_mode.value,
                    explicit=explicit,
                    start=ann.start,
                    end=ann.end,
                    confidence=ann.confidence,
                    entity_ref=ann.entity_id,
                    source=source,
                )
            )

    if extraction is not None:
        for qi in extraction.qis:
            if qi.span is not None and (qi.category, qi.span[0], qi.span[1]) in seen:
                # Déduplication contre le natif : le même (code, span) déjà
                # détecté n'entre pas deux fois dans Q(d).
                continue
            attributes.append(
                QiAttribute(
                    category=qi.category,
                    value=dict(qi.value) if isinstance(qi.value, dict) else {"raw": qi.value},
                    expression_mode=qi.expression_mode,
                    explicit=qi.explicit,
                    start=qi.span[0] if qi.span is not None else None,
                    end=qi.span[1] if qi.span is not None else None,
                    confidence=qi.confidence,
                    prior=qi.prior,
                    entity_ref=qi.entity_ref,
                    source="llm:qi",
                )
            )

    return _dedup_attributes(attributes)


def _dedup_attributes(attributes: list[QiAttribute]) -> tuple[QiAttribute, ...]:
    """Dédup QICR : même ``(catégorie, valeur canonique, coréférence)`` →
    une seule entrée (la plus confiante) ; même coréférence et même
    catégorie → fusion des mentions."""
    best: dict[tuple[str, str, str | None], QiAttribute] = {}
    for attr in attributes:
        key = attr.key
        prev = best.get(key)
        if prev is None or attr.confidence > prev.confidence:
            best[key] = attr
    merged: dict[tuple[str, str | None], QiAttribute] = {}
    for attr in best.values():
        if attr.entity_ref is None:
            continue
        k = (attr.category, attr.entity_ref)
        prev = merged.get(k)
        if prev is None or attr.confidence > prev.confidence:
            merged[k] = attr
    out = [attr for attr in best.values() if attr.entity_ref is None]
    out.extend(merged.values())
    return tuple(out)


def build_qi_combinations(
    attributes: tuple[QiAttribute, ...] | list[QiAttribute],
    population: PopulationConfig,
) -> tuple[QiAttribute, ...]:
    """Combinaison d'audit : valeurs normalisées (JSON canonique),
    déduplication, fusion par coréférence, tri par rareté puis par
    catégorie. Retourne l'ordre dans lequel les attributs entrent dans le
    produit copule."""
    ordered = sorted(
        _dedup_attributes(list(attributes)),
        key=lambda a: (
            _probability_or_max(population, a),
            a.category,
            _canonical_json(a.value),
        ),
    )
    return tuple(ordered)


def _probability_or_max(population: PopulationConfig, attr: QiAttribute) -> float:
    """Probabilité de tri : la valeur inconnue est triée **dernière** (le
    risque échoue ensuite explicitement — jamais un défaut au milieu du
    tri)."""
    p = population.probability_of(attr)
    return p if p is not None else 2.0


# --------------------------------------------------------------------------- #
# Estimateur
# --------------------------------------------------------------------------- #
class HybridRiskEstimator:
    """Estimateur de risque copule (SPÉC-06 §7) calibré sur population
    synthétique.

    L'estimation d'un document est **déterministe** : mêmes attributs → même
    ``HybridRiskEstimate``, quel que soit le moment de l'appel (la
    calibration est un singleton de module figé).
    """

    def __init__(self, population: PopulationConfig) -> None:
        self._population = population
        self._sigma = population.correlation_matrix()
        if not is_positive_definite(self._sigma):
            raise RiskConfigError(
                f"population {population.population_id!r} : matrice de "
                "corrélation non définie-positive — corrigez "
                "``correlation_off_diagonal`` dans population.yaml"
            )
        self._calibration = get_calibration()

    @property
    def population(self) -> PopulationConfig:
        return self._population

    def _probability(self, attribute: QiAttribute, level: int = 0) -> float:
        p = self._population.probability_of(attribute, level=level)
        if p is None:
            raise RiskInputError(
                category=attribute.category,
                value=attribute.value,
                file=population_file(self._population),
            )
        return p

    def assess(
        self,
        attributes: tuple[QiAttribute, ...] | list[QiAttribute],
        domain: str | None = None,
        language: str | None = None,
        claims: tuple[UniquenessClaim, ...] = (),
        levels: Mapping[str, int] | None = None,
    ) -> HybridRiskEstimate:
        """Évalue le risque du document : QICR → produit copule → intervalle
        (résidus calibrés) → décision sur la borne haute.

        - claim d'unicité vraie (confiance ≥ 0.70) → k = 1, risque 1.0 ;
        - aucun QI → risque 0, k_hat = taille de population ;
        - plus de 6 attributs → tous entrent dans le produit et
          ``combination_truncated=true`` est tracé (jamais un QI ignoré) ;
        - ``levels`` : état courant du planificateur — niveau de
          généralisation appliqué par catégorie (0 = valeur brute) ; chaque
          pas de généralisation élargit la probabilité d'un facteur 4
          (SPEC-06 §8) et le risque est réévalué sur l'état courant.
        """
        pop = self._population
        attrs = build_qi_combinations(attributes, pop)

        trusted_claim = None
        for claim in claims:
            if claim.confidence >= CLAIM_TRUST_THRESHOLD and (
                trusted_claim is None or claim.confidence > trusted_claim.confidence
            ):
                trusted_claim = claim

        base = dict(
            population_id=pop.population_id,
            risk_model="copula",
            status="DIAGNOSTIC",
            calibration_scope=self._calibration.scope,
            uniqueness_claim=trusted_claim,
            total_qi_count=len(attrs),
        )

        if trusted_claim is not None:
            return HybridRiskEstimate(
                k_hat=1.0,
                k_interval=(1.0, 1.0),
                risk=1.0,
                risk_point=1.0,
                contributing_qi=tuple(a.category for a in attrs),
                explanation=(
                    "claim d'unicité de confiance "
                    f"{trusted_claim.confidence:.2f} : k forcé à 1, risque 1.0"
                ),
                **base,
            )

        if not attrs:
            return HybridRiskEstimate(
                k_hat=float(pop.size),
                k_interval=(float(pop.size), float(pop.size)),
                risk=0.0,
                risk_point=0.0,
                contributing_qi=(),
                explanation="aucun quasi-identifiant : risque 0",
                **base,
            )

        levels_map = levels or {}
        probabilities = [
            self._probability(a, level=int(levels_map.get(a.category, 0)))
            for a in attrs
        ]
        z = [_inv_cdf(p) for p in probabilities]

        # Sigma bloc-diagonale : attributs corrélés (ordre canonique de la
        # population) ⊕ indépendants. L'ordre de ``attrs`` trié par rareté
        # ne change PAS la matrice : seules les catégories présentes
        # comptent, dans l'ordre canonique.
        sigma = _sigma_for(tuple(a.category for a in attrs), pop.correlated_attributes, 0.0, parent=self._sigma)
        factor = copula_factor(z, sigma)
        k_raw = pop.size * math.prod(probabilities) * factor

        cal = self._calibration
        # Strate de calibration par taille de combinaison ; au-delà de 3
        # attributs (cas tronqué) on prend la strate 3, la plus conservatrice.
        stratum = min(len(attrs), _CAL_MAX_SUBSET)
        k_low = max(1.0, k_raw * cal.q_low_residual[stratum - 1])
        k_high = max(k_low, k_raw * cal.q_high_residual[stratum - 1])
        risk = 1.0 / k_low  # décision conservatrice (use_upper_bound)
        raw_risk = 1.0 / max(1.0, k_raw)
        risk_point = _apply_isotone(list(cal.isotone[stratum]), raw_risk)

        return HybridRiskEstimate(
            k_hat=k_raw,
            k_interval=(k_low, k_high),
            risk=risk,
            risk_point=risk_point,
            contributing_qi=tuple(a.category for a in attrs),
            combination_truncated=len(attrs) > 6,
            explanation=(
                f"{len(attrs)} quasi-identifiants "
                f"({', '.join(a.category for a in attrs)}) : k≈{k_raw:.1f} "
                f"[{k_low:.1f}–{k_high:.1f}] (population {pop.size}, "
                f"copule ×{factor:.3f}), risque {risk:.4f} / point "
                f"{risk_point:.4f} — DIAGNOSTIC (calibration {cal.scope})"
            ),
            **base,
        )


def load_population(path: Path) -> PopulationConfig:
    """Charge et valide une population versionnée ; les erreurs nomment le
    fichier fautif (règle d'or : jamais de silence)."""
    path = Path(path)
    if not path.is_file():
        raise RiskConfigError(f"population introuvable : {path}")
    raw = yaml.safe_load(path.read_text(encoding="utf-8"))
    if not isinstance(raw, dict):
        raise RiskConfigError(f"{path} : contenu YAML invalide (dictionnaire attendu)")
    try:
        return PopulationConfig.model_validate(raw)
    except Exception as exc:
        raise RiskConfigError(f"{path} : {exc}") from exc


def population_file(population: PopulationConfig) -> str:
    """Nom du fichier de population (pour les messages d'erreur
    actionnables)."""
    return f"population.yaml ({population.population_id})"
