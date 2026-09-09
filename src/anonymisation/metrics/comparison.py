"""Comparaison inter-systèmes et validation de comparabilité (SPEC-07, SPEC-10).

Fournit :
- `assert_comparable_across_systems(scorecards)` : valide que tous les runs
  partagent le même dataset, le même split, le même protocole/version.
  Autorise la comparaison interne de valeurs PROXY/DIAGNOSTIC à condition que
  toutes les lignes partagent le même statut pour une métrique donnée ; les
  comparaisons externes/publicables relèvent de `assert_comparable()`, qui
  refuse tout chiffre PROXY ou DIAGNOSTIC.
- `render_comparison_markdown(scorecards)` : génère un tableau comparatif Markdown
  stable, avec colonnes normatives, trié par system_id, et une section de provenance.
"""

from __future__ import annotations

from collections.abc import Sequence
from typing import Any

from anonymisation.metrics.contracts import (
    MetricComparisonError,
    MetricStatus,
    MetricValue,
    assert_comparable,
)

__all__ = [
    "MetricComparisonError",
    "MetricStatus",
    "MetricValue",
    "assert_comparable",
    "assert_comparable_across_systems",
    "render_comparison_markdown",
]

#: Métriques dont la comparabilité est contrôlée ligne à ligne.
_CHECKED_METRICS: tuple[tuple[str, str], ...] = (
    ("primary", "cpr"),
    ("primary", "ipr"),
    ("primary", "trir"),
    ("primary", "utility_retention"),
    ("diagnostic", "mean_utility"),
    ("diagnostic", "ER_di"),
    ("diagnostic", "ER_qi"),
)

#: Statuts non publiables : la valeur existe, mais ne porte aucune garantie de
#: comparabilité externe (cf. ``assert_comparable``).
_NON_PUBLISHABLE = (MetricStatus.DIAGNOSTIC.value, MetricStatus.PROXY.value)

#: Statuts sans valeur affichée : la ligne rend « — », rien n'est comparé.
_NO_VALUE = (MetricStatus.UNAVAILABLE.value, MetricStatus.FAILED.value)


def _status_of(block: Any) -> str | None:
    if not isinstance(block, dict):
        return None
    status = block.get("status")
    return str(status) if status is not None else None


def _annotate(value: str, status: str | None) -> str:
    """Suffixe une valeur affichée par son statut quand il n'est pas publiable."""
    if value == "—" or status is None:
        return value
    if status in _NON_PUBLISHABLE:
        return f"{value} ({status[:4].upper()})"
    if status == MetricStatus.SAMPLED.value:
        return f"{value} (SAMP)"
    return value


def assert_comparable_across_systems(scorecards: Sequence[dict[str, Any]]) -> None:
    """Exige même dataset, split, protocole/version et cohérence de statut."""
    if not scorecards:
        raise MetricComparisonError("Aucune scorecard fournie pour la comparaison.")

    ref = scorecards[0]
    ref_ds = ref.get("dataset")
    ref_split = ref.get("split")
    ref_protocol = ref.get("protocol")
    ref_proto_ver = ref.get("protocol_version")

    for idx, sc in enumerate(scorecards[1:], start=2):
        ds = sc.get("dataset")
        split = sc.get("split")
        proto = sc.get("protocol")
        proto_ver = sc.get("protocol_version")

        if ds != ref_ds:
            raise MetricComparisonError(
                f"Scorecard #{idx} dataset incompatible : attendu {ref_ds!r}, obtenu {ds!r}"
            )
        if split != ref_split:
            raise MetricComparisonError(
                f"Scorecard #{idx} split incompatible : attendu {ref_split!r}, obtenu {split!r}"
            )
        if proto != ref_protocol or proto_ver != ref_proto_ver:
            raise MetricComparisonError(
                f"Scorecard #{idx} protocole incompatible : attendu {ref_protocol}/{ref_proto_ver}, obtenu {proto}/{proto_ver}"
            )

        # Le protocole global identique ne suffit pas : deux runs peuvent
        # publier la même métrique sous des statuts différents (PROXY vs
        # SAMPLED). Les aligner dans un tableau les ferait passer pour deux
        # chiffres du même ordre. Seules les lignes qui portent réellement une
        # valeur des deux côtés sont concernées.
        for section, metric in _CHECKED_METRICS:
            ref_status = _status_of((ref.get(section) or {}).get(metric))
            status = _status_of((sc.get(section) or {}).get(metric))
            if ref_status is None or status is None:
                continue
            # Une métrique qu'un système ne peut pas produire (capacité absente)
            # s'affiche « — » : elle ne se compare à rien et ne bloque donc
            # pas la comparaison des colonnes que les deux systèmes publient.
            if ref_status in _NO_VALUE or status in _NO_VALUE:
                continue
            if ref_status != status:
                raise MetricComparisonError(
                    f"Scorecard #{idx} statut incompatible pour {metric!r} : "
                    f"attendu {ref_status!r}, obtenu {status!r}"
                )


def _fmt_metric(val: Any) -> str:
    if val is None or val == "—":
        return "—"
    if isinstance(val, dict):
        if val.get("status") in ("unavailable", "failed") or val.get("value") is None:
            return "—"
        v = val.get("value")
        if v is None:
            return "—"
        return f"{float(v):.4f}"
    if isinstance(val, (int, float)):
        return f"{float(val):.4f}"
    return str(val)


def _cell(block: Any) -> str:
    """Valeur formatée, suffixée de son statut quand il n'est pas publiable."""
    return _annotate(_fmt_metric(block), _status_of(block))


def render_comparison_markdown(scorecards: Sequence[dict[str, Any]]) -> str:
    """Rend un rapport Markdown stable de comparaison inter-systèmes."""
    assert_comparable_across_systems(scorecards)

    # Trier par system_id puis version
    sorted_scs = sorted(
        scorecards,
        key=lambda s: (
            str((s.get("system") or {}).get("system_id", "")),
            str((s.get("system") or {}).get("system_version", "")),
        ),
    )

    first = sorted_scs[0]
    dataset = first.get("dataset", "unknown")
    split = first.get("split", "unknown")
    protocol = first.get("protocol", "unknown")
    proto_ver = first.get("protocol_version", "unknown")

    lines = [
        f"# Comparaison des systèmes — {dataset} ({split})",
        "",
        f"**Protocole :** `{protocol}` (version `{proto_ver}`)  ",
        f"**Nombre de systèmes comparés :** {len(sorted_scs)}",
        "",
        "> Les valeurs suffixées `PROX`, `DIAG` ou `SAMP` ne sont pas des "
        "chiffres publiables : elles ne portent aucune garantie de "
        "comparabilité externe (SPEC-07). Elles ne se lisent qu'entre runs de "
        "même statut, tel que vérifié ci-dessus.",
        "",
        "| Système | Version | CPR | IPR | TRIR | Utility Ret. | Mean Utility | ROUGE-L | ER_di | ER_qi | Gold Leak | Latence p50 (ms) | Erreur |",
        "|---|---|---|---|---|---|---|---|---|---|---|---|---|",
    ]

    unavailable_provenance: list[str] = []

    for sc in sorted_scs:
        sys_block = sc.get("system") or {}
        sys_id = sys_block.get("system_id", "unknown")
        sys_ver = sys_block.get("system_version", "1")

        primary = sc.get("primary") or {}
        diag = sc.get("diagnostic") or {}
        eff = sc.get("efficiency") or {}

        cpr = _cell(primary.get("cpr"))
        ipr = _cell(primary.get("ipr"))
        trir = _cell(primary.get("trir"))
        util_ret = _cell(primary.get("utility_retention"))
        mean_util = _cell(diag.get("mean_utility"))
        rouge = _cell(diag.get("rouge_l"))
        er_di = _cell(diag.get("ER_di"))
        er_qi = _cell(diag.get("ER_qi"))
        leak = _cell(diag.get("gold_leak_rate"))

        lat = eff.get("latency_p50_ms")
        lat_str = f"{float(lat):.2f}" if lat is not None else "—"

        err = sc.get("error_rate", 0.0)
        err_str = f"{float(err):.1%}"

        lines.append(
            f"| `{sys_id}` | `{sys_ver}` | {cpr} | {ipr} | {trir} | {util_ret} | {mean_util} | {rouge} | {er_di} | {er_qi} | {leak} | {lat_str} | {err_str} |"
        )

        # Collecter les raisons des indisponibilités
        for name, blk in [
            ("CPR", primary.get("cpr")),
            ("IPR", primary.get("ipr")),
            ("TRIR", primary.get("trir")),
            ("Utility Retention", primary.get("utility_retention")),
            ("Mean Utility", diag.get("mean_utility")),
            ("ER_di", diag.get("ER_di")),
            ("ER_qi", diag.get("ER_qi")),
        ]:
            if isinstance(blk, dict) and (blk.get("status") in ("unavailable", "failed") or blk.get("value") is None):
                reason = (blk.get("details") or {}).get("reason") or blk.get("status")
                unavailable_provenance.append(f"- **{sys_id}** `{name}` : {reason}")

    if unavailable_provenance:
        lines.extend([
            "",
            "## Provenance et statut des métriques indisponibles",
            "",
        ])
        lines.extend(unavailable_provenance)

    lines.append("")
    return "\n".join(lines)
