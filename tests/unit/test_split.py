"""Tests du split déterministe (SPEC-04 §9).

Le test le plus important est ``test_adding_groups_does_not_reshuffle_existing``
qui vérifie la propriété que ``train_test_split`` ne garantit pas.
"""

from __future__ import annotations

import pytest

from anonymisation.datasets._split import assign_split, split_groups

RATIOS = {"train": 0.7, "dev": 0.1, "test": 0.2}


class TestAssignSplit:
    def test_returns_one_of_the_declared_splits(self) -> None:
        for i in range(200):
            split = assign_split(f"person:{i}", seed=42, ratios=RATIOS)
            assert split in RATIOS

    def test_is_deterministic_for_same_inputs(self) -> None:
        a = assign_split("person:42", seed=1, ratios=RATIOS)
        b = assign_split("person:42", seed=1, ratios=RATIOS)
        assert a == b

    def test_different_seed_can_change_assignment(self) -> None:
        # Pas garanti pour toute clé individuelle, mais sur un échantillon la
        # distribution doit changer pour au moins une clé.
        keys = [f"person:{i}" for i in range(500)]
        splits_seed_1 = [assign_split(k, seed=1, ratios=RATIOS) for k in keys]
        splits_seed_2 = [assign_split(k, seed=2, ratios=RATIOS) for k in keys]
        assert splits_seed_1 != splits_seed_2

    def test_ratio_order_in_dict_does_not_matter(self) -> None:
        """Le tri par nom de split garantit la stabilité quel que soit l'ordre
        du dict d'entrée."""
        ratios_a = {"train": 0.7, "dev": 0.1, "test": 0.2}
        ratios_b = {"test": 0.2, "train": 0.7, "dev": 0.1}
        for i in range(100):
            key = f"person:{i}"
            assert assign_split(key, seed=7, ratios=ratios_a) == assign_split(
                key, seed=7, ratios=ratios_b
            )

    def test_approximate_distribution_matches_ratios(self) -> None:
        n = 20_000
        counts = {name: 0 for name in RATIOS}
        for i in range(n):
            counts[assign_split(f"g{i}", seed=123, ratios=RATIOS)] += 1
        for name, ratio in RATIOS.items():
            observed = counts[name] / n
            assert abs(observed - ratio) < 0.02

    def test_empty_ratios_rejected(self) -> None:
        with pytest.raises(ValueError):
            assign_split("k", seed=1, ratios={})

    def test_ratios_not_summing_to_one_rejected(self) -> None:
        with pytest.raises(ValueError):
            assign_split("k", seed=1, ratios={"train": 0.5, "test": 0.2})

    def test_negative_ratio_rejected(self) -> None:
        with pytest.raises(ValueError):
            assign_split("k", seed=1, ratios={"train": 1.2, "test": -0.2})

    def test_single_split_always_assigns_it(self) -> None:
        assert assign_split("anything", seed=1, ratios={"all": 1.0}) == "all"


class TestSplitGroups:
    def test_partitions_all_keys(self) -> None:
        keys = [f"g{i}" for i in range(1000)]
        result = split_groups(keys, seed=42, ratios=RATIOS)
        total = sum(len(v) for v in result.values())
        assert total == len(keys)
        assert set(result) == set(RATIOS)

    def test_consistent_with_assign_split(self) -> None:
        keys = [f"g{i}" for i in range(300)]
        result = split_groups(keys, seed=5, ratios=RATIOS)
        for split_name, group_keys in result.items():
            for key in group_keys:
                assert assign_split(key, seed=5, ratios=RATIOS) == split_name

    def test_adding_groups_does_not_reshuffle_existing(self) -> None:
        """Propriété exigée par SPEC-04 §9 : ajouter un groupe ne redistribue
        pas les groupes déjà affectés — ce que train_test_split ne garantit
        pas."""
        base_keys = [f"person:{i}" for i in range(1000)]
        extra_keys = [f"person:{i}" for i in range(1000, 1200)]

        before = split_groups(base_keys, seed=42, ratios=RATIOS)
        before_assignment = {
            key: split for split, keys in before.items() for key in keys
        }

        after = split_groups(base_keys + extra_keys, seed=42, ratios=RATIOS)
        after_assignment = {
            key: split for split, keys in after.items() for key in keys
        }

        for key in base_keys:
            assert after_assignment[key] == before_assignment[key]

    def test_no_duplicate_keys_across_splits(self) -> None:
        keys = [f"g{i}" for i in range(500)]
        result = split_groups(keys, seed=1, ratios=RATIOS)
        seen: set[str] = set()
        for group_keys in result.values():
            for key in group_keys:
                assert key not in seen
                seen.add(key)
