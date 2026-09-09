"""Chargeur et calcul de k pondéré pour la population PUMS (SPEC-06 §4).

Lit le fichier parquet PUMS par lots via pyarrow.dataset, projette uniquement
les colonnes requises et somme `PWGTP` pour chaque combinaison de critères.
Ne matérialise jamais l'intégralité de la population en mémoire et ne compte
jamais le nombre de lignes (k_true = sum(PWGTP)).
"""

from __future__ import annotations

from collections.abc import Mapping
from pathlib import Path
from typing import Any


class PopulationError(ValueError):
    """Erreur liée à la population ou aux critères d'interrogation."""


class PopulationNoMatchError(PopulationError):
    """Aucun individu de la population ne satisfait les critères.

    Distinct des erreurs *structurelles* (colonne absente, PWGTP manquant,
    parquet illisible, pyarrow absent) qui restent des ``PopulationError``
    nues : un appelant peut légitimement tolérer une combinaison sans
    correspondance, jamais un schéma qui ne correspond pas au sien.
    """


class PumsPopulation:
    """Accès par lots à la population PUMS et calcul de k_true pondéré."""

    def __init__(self, path: Path | str, batch_size: int = 131_072) -> None:
        self.path = Path(path)
        if not self.path.exists():
            raise PopulationError(f"Fichier de population PUMS introuvable : {self.path}")
        self.batch_size = batch_size
        self._dataset: Any = None
        self._schema_names: set[str] | None = None

    def _get_dataset(self) -> Any:
        if self._dataset is None:
            try:
                import pyarrow.dataset as ds
            except ImportError as exc:
                raise PopulationError(
                    "PumsPopulation nécessite pyarrow pour lire le cache parquet."
                ) from exc
            try:
                self._dataset = ds.dataset(self.path, format="parquet")
                self._schema_names = set(self._dataset.schema.names)
            except Exception as exc:
                raise PopulationError(
                    f"Erreur d'ouverture du dataset PUMS {self.path} : {exc}"
                ) from exc
        return self._dataset

    def weighted_k(self, criteria: Mapping[str, Any]) -> int:
        """Calcule k_true = sum(PWGTP) pour les critères donnés.

        Lève PopulationError si :
        - criteria est vide
        - une colonne demandée n'existe pas dans le schéma PUMS
        - aucun enregistrement ne correspond (pas de k=0 silencieux)
        - la somme des poids calculée est <= 0
        """
        if not criteria:
            raise PopulationError(
                f"Critères vides fournis pour {self.path} : k_true ne peut pas être non contraint."
            )

        dataset = self._get_dataset()
        assert self._schema_names is not None

        if "PWGTP" not in self._schema_names:
            raise PopulationError(
                f"Fichier PUMS {self.path} invalide : colonne de pondération 'PWGTP' absente."
            )

        unknown_cols = [c for c in criteria if c not in self._schema_names]
        if unknown_cols:
            raise PopulationError(
                f"Colonnes de critères absentes du schéma PUMS ({self.path}) : {unknown_cols}"
            )

        try:
            import pyarrow.compute as pc
            import pyarrow.dataset as ds
        except ImportError as exc:
            raise PopulationError("pyarrow requis pour le calcul PUMS.") from exc

        # Construire l'expression de filtre pyarrow via ds.field et opérateurs
        filter_expr = None
        for col, val in criteria.items():
            cond = ds.field(col).is_null() if val is None else (ds.field(col) == val)
            filter_expr = cond if filter_expr is None else (filter_expr & cond)
        total_weight: int = 0
        matched_any: bool = False

        projection = ["PWGTP"] + [c for c in criteria if c != "PWGTP"]
        scanner = dataset.scanner(
            columns=projection,
            filter=filter_expr,
            batch_size=self.batch_size,
        )

        for batch in scanner.to_batches():
            if batch.num_rows > 0:
                matched_any = True
                weights = batch["PWGTP"]
                batch_sum = pc.sum(weights).as_py()
                if batch_sum is not None:
                    total_weight += int(batch_sum)

        if not matched_any or total_weight <= 0:
            raise PopulationNoMatchError(
                f"Aucune correspondance dans la population PUMS ({self.path}) pour les critères : {dict(criteria)}"
            )

        return total_weight
