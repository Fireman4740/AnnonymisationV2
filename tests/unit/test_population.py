"""Tests unitaires ciblés pour PumsPopulation."""

from __future__ import annotations

from pathlib import Path

import pyarrow as pa
import pyarrow.parquet as pq
import pytest

from anonymisation.risk.population import PopulationError, PumsPopulation


def test_pums_weighted_k_sums_pwgtp_and_does_not_count_rows(tmp_path: Path):
    # Deux lignes, mais poids 100 et 7 -> la somme doit être 107, JAMAIS 2
    schema = pa.schema([
        ("SERIALNO", pa.string()),
        ("PWGTP", pa.int64()),
        ("sex", pa.string()),
        ("state of residence", pa.string()),
    ])
    table = pa.Table.from_arrays(
        [
            pa.array(["1", "2"]),
            pa.array([100, 7]),
            pa.array(["Male", "Male"]),
            pa.array(["Oregon/OR", "Oregon/OR"]),
        ],
        schema=schema,
    )
    parquet_path = tmp_path / "test_pums.parquet"
    pq.write_table(table, parquet_path)

    pums = PumsPopulation(parquet_path, batch_size=1)
    k = pums.weighted_k({"sex": "Male", "state of residence": "Oregon/OR"})
    assert k == 107, f"Attendu 107 (somme des poids), obtenu {k} (erreur si 2 = comptage de lignes)"


def test_pums_monotonicity(tmp_path: Path):
    # Ajouter un critère doit réduire ou laisser invariant k
    schema = pa.schema([
        ("SERIALNO", pa.string()),
        ("PWGTP", pa.int64()),
        ("sex", pa.string()),
        ("state of residence", pa.string()),
        ("citizenship status", pa.string()),
    ])
    table = pa.Table.from_arrays(
        [
            pa.array(["1", "2", "3"]),
            pa.array([50, 30, 20]),
            pa.array(["Male", "Male", "Female"]),
            pa.array(["Oregon/OR", "Oregon/OR", "Oregon/OR"]),
            pa.array(["Born in the US", "Not a citizen of the U.S.", "Born in the US"]),
        ],
        schema=schema,
    )
    parquet_path = tmp_path / "test_pums_mono.parquet"
    pq.write_table(table, parquet_path)

    pums = PumsPopulation(parquet_path)
    k1 = pums.weighted_k({"state of residence": "Oregon/OR"})
    assert k1 == 100

    k2 = pums.weighted_k({"state of residence": "Oregon/OR", "sex": "Male"})
    assert k2 == 80
    assert k2 < k1

    k3 = pums.weighted_k({"state of residence": "Oregon/OR", "sex": "Male", "citizenship status": "Born in the US"})
    assert k3 == 50
    assert k3 < k2


def test_pums_missing_or_no_match_raises_named_error(tmp_path: Path):
    schema = pa.schema([
        ("SERIALNO", pa.string()),
        ("PWGTP", pa.int64()),
        ("sex", pa.string()),
    ])
    table = pa.Table.from_arrays(
        [
            pa.array(["1"]),
            pa.array([10]),
            pa.array(["Male"]),
        ],
        schema=schema,
    )
    parquet_path = tmp_path / "test_pums_err.parquet"
    pq.write_table(table, parquet_path)

    pums = PumsPopulation(parquet_path)
    # Colonne inconnue
    with pytest.raises(PopulationError, match="absentes du schéma PUMS"):
        pums.weighted_k({"unknown_col": "val"})

    # Aucune correspondance
    with pytest.raises(PopulationError, match="Aucune correspondance dans la population PUMS"):
        pums.weighted_k({"sex": "Female"})
