"""Vocabulaire des capacités d'un système d'anonymisation.

Ce module **n'importe rien** du paquet, et c'est délibéré : il est le seul
point de contact entre les producteurs (``anonymisation.systems``) et les
consommateurs (``anonymisation.metrics``).

Pourquoi la racine du paquet et non ``systems/capabilities.py`` : importer
``anonymisation.systems.capabilities`` exécuterait ``systems/__init__.py``,
qui importe tous les systèmes enregistrés, donc ``detect/``. Or ``anonv2
score`` ne doit **jamais** charger un détecteur — c'est une garantie testée
(``tests/integration/test_score.py``) et la condition pour que le scoring
puisse être rejoué des dizaines de fois sans relancer le moindre modèle
(SPEC-10 §5, audit v1 §12.6).

À quoi servent les capacités : un ``PipelineResult`` sans annotations est
**ambigu** — boîte noire qui ne prétend pas détecter, ou pipeline riche qui
n'a rien trouvé ? Le scorer ne doit pas deviner. Il lit les capacités
déclarées et dégrade en ``UNAVAILABLE`` les métriques inapplicables, **jamais
en 0.0** : un zéro ferait passer une boîte noire parfaite pour un détecteur
catastrophique.
"""

from __future__ import annotations

from typing import Final

#: Le système produit des annotations localisées (offsets sur le texte
#: original). Condition de l'axe A : F1 de spans, macro-F1, ER_di / ER_qi.
CAP_SPANS: Final[str] = "spans"

#: Le système produit des décisions d'anonymisation explicables.
CAP_DECISIONS: Final[str] = "decisions"

#: Le système produit les traces d'étape de SPEC-10 §4.
CAP_TRACES: Final[str] = "traces"

#: Le système produit une estimation de risque à l'étape ASSESS.
CAP_RISK: Final[str] = "risk"

#: Le système consomme une politique d'anonymisation (P0..P4).
CAP_POLICY: Final[str] = "policy"

#: Le système lit la vérité terrain. Réservé aux oracles et au contrôle de
#: fuite ; un système qui la lit n'est pas un concurrent publiable.
CAP_GOLD_AWARE: Final[str] = "gold_aware"

#: Le système distingue plusieurs sujets par document (CPR / IPR par sujet).
CAP_SUBJECTS: Final[str] = "subjects"

CAPABILITIES: Final[frozenset[str]] = frozenset(
    {
        CAP_SPANS,
        CAP_DECISIONS,
        CAP_TRACES,
        CAP_RISK,
        CAP_POLICY,
        CAP_GOLD_AWARE,
        CAP_SUBJECTS,
    }
)


class UnknownCapabilityError(ValueError):
    """Capacité absente du vocabulaire — refusée à l'enregistrement."""


def assert_known(capabilities: frozenset[str], *, owner: str) -> None:
    """Refuse une capacité inconnue, en nommant le système fautif.

    Aucune valeur par défaut silencieuse : une capacité mal orthographiée
    ferait taire des métriques entières sans que personne ne s'en aperçoive.
    """
    unknown = sorted(set(capabilities) - CAPABILITIES)
    if unknown:
        raise UnknownCapabilityError(
            f"Système {owner!r} : capacité(s) inconnue(s) {unknown}. "
            f"Vocabulaire admis : {sorted(CAPABILITIES)}."
        )


def sorted_capabilities(capabilities: frozenset[str]) -> tuple[str, ...]:
    """Forme sérialisable et **déterministe** d'un ensemble de capacités.

    Un ``frozenset`` n'a pas d'ordre stable entre exécutions : le sérialiser
    tel quel casserait la reproductibilité bit-à-bit des prédictions
    (SPEC-10 §10).
    """
    return tuple(sorted(capabilities))
