"""CLI ``anonv2``.

Commandes de datasets spécifiées en SPEC-03 §9. Squelette : les commandes
lèvent ``NotImplementedError`` tant que le lot L2 n'est pas fait, plutôt que de
retourner un résultat vide qui donnerait l'illusion de fonctionner.
"""

from __future__ import annotations

import typer
from rich.console import Console
from rich.table import Table

from anonymisation import __version__
from anonymisation.datasets import list_keys, resolve

app = typer.Typer(add_completion=False, help="Anonymisation pilotée par le risque de ré-identification")
datasets_app = typer.Typer(help="Acquisition, ingestion et validation des jeux de données")
app.add_typer(datasets_app, name="datasets")

console = Console()


@app.command()
def version() -> None:
    """Affiche la version."""
    console.print(f"anonymisation-v2 {__version__}")


@datasets_app.command("list")
def datasets_list() -> None:
    """Liste les datasets enregistrés, avec leur statut."""
    table = Table(title="Datasets enregistrés")
    table.add_column("clé")
    table.add_column("licence")
    table.add_column("documents")
    table.add_column("statut")

    keys = list_keys()
    if not keys:
        console.print(
            "[yellow]Aucun adaptateur enregistré.[/yellow] "
            "Décommenter les imports dans src/anonymisation/datasets/__init__.py "
            "au fur et à mesure du lot L2 (voir documentation/roadmap.md)."
        )
        return

    for key in keys:
        adapter = resolve(key)
        table.add_row(key, "?", "?", "non ingéré")
    console.print(table)


@datasets_app.command("download")
def datasets_download(key: str, force: bool = False, pin: bool = False) -> None:
    """Acquiert la source (SPEC-04 §3).

    ``--pin`` calcule ET écrit le checksum dans le manifeste. Sans lui, le
    checksum est seulement affiché : figer une version est une décision, pas un
    effet de bord.
    """
    raise NotImplementedError("Lot L2 — voir SPEC-04 §3")


@datasets_app.command("ingest")
def datasets_ingest(key: str, split: str = "all", limit: int | None = None) -> None:
    """Normalise vers le format pivot (SPEC-04 §4)."""
    raise NotImplementedError("Lot L2 — voir SPEC-04 §4")


@datasets_app.command("validate")
def datasets_validate(key: str) -> None:
    """Vérifie tous les invariants de SPEC-02 (SPEC-04 §5)."""
    raise NotImplementedError("Lot L2 — voir SPEC-04 §5")


@datasets_app.command("stats")
def datasets_stats(key: str) -> None:
    """Comptes par langue, domaine, catégorie et mode d'expression.

    Ce n'est pas un confort : ces comptes sont les dénominateurs des métriques
    déclinées de SPEC-07.
    """
    raise NotImplementedError("Lot L2 — voir SPEC-04 §5")


@datasets_app.command("audit-licenses")
def datasets_audit_licenses() -> None:
    """Vérifie la conformité des licences (SPEC-09 §2). Échoue si incomplet."""
    raise NotImplementedError("Lot L2 — voir SPEC-09 §2")


if __name__ == "__main__":
    app()
