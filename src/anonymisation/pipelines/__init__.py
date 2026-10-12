"""Pipelines d'anonymisation — un dossier autonome par architecture.

Séparation nette entre **le contrat** et **les implémentations** :

* ``anonymisation.systems`` définit le contrat (``SystemBase``, capacités,
  registre). Il ne connaît aucune implémentation concrète.
* ``anonymisation.pipelines.<nom>/`` contient **tout** ce qui appartient à une
  architecture : son code (``system.py``), son profil d'exécution
  (``profile.yaml``), ses tests (``tests/``), sa notice (``README.md``), et le
  cas échéant ses ressources propres (prompts, lexiques, gabarits).

Conséquence : ajouter, remplacer ou supprimer une architecture se fait dans un
seul dossier. Le seul point de contact partagé est la ligne d'import
ci-dessous.

**Découverte par import explicite, jamais par scan de répertoire** : le
comportement du registre ne doit pas dépendre de l'ordre de parcours du
système de fichiers. Ajouter un pipeline = ajouter une ligne ici.
"""

from anonymisation.pipelines import deterministic as _deterministic  # noqa: F401
from anonymisation.pipelines import hybrid_qi as _hybrid_qi  # noqa: F401
from anonymisation.pipelines import llm_full as _llm_full  # noqa: F401
from anonymisation.pipelines import oracle_mask as _oracle_mask  # noqa: F401
from anonymisation.pipelines import passthrough as _passthrough  # noqa: F401
from anonymisation.pipelines import redact_all as _redact_all  # noqa: F401
from anonymisation.pipelines import regex_only as _regex_only  # noqa: F401

#: Noms des paquets de pipelines livrés, dans l'ordre d'enregistrement.
PIPELINE_PACKAGES: tuple[str, ...] = (
    "passthrough",
    "redact_all",
    "regex_only",
    "deterministic",
    "hybrid_qi",
    "llm_full",
    "oracle_mask",
)

__all__ = ["PIPELINE_PACKAGES"]
