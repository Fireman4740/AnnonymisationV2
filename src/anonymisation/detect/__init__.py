"""Couche de détection déterministe des quasi-identifiants.

Point d'entrée public : ``DeterministicDetector``. Combine les motifs
déclaratifs (``detect/patterns.py``) et les règles contextuelles
(``detect/rules.py``), fusionne les candidats en conflit (``detect/fusion.py``)
et convertit vers le modèle SPEC-02 (``detect/base.py``).

Aucun LLM, aucun modèle lourd : cohérent avec la leçon de l'audit v1
(84-100 % d'erreurs dues à la dépendance aux LLM). Ce détecteur est
entièrement hors ligne et reproductible.
"""

from __future__ import annotations

from collections.abc import Sequence
from pathlib import Path

from anonymisation.detect.base import Candidate, Detector, candidates_to_annotations
from anonymisation.detect.fusion import FusionDecision, fuse
from anonymisation.detect.patterns import CompiledPattern, apply_patterns, load_patterns
from anonymisation.detect.rules import apply_rules
from anonymisation.schema.models import Annotation

__all__ = [
    "Candidate",
    "Detector",
    "candidates_to_annotations",
    "FusionDecision",
    "fuse",
    "CompiledPattern",
    "DeterministicDetector",
    "PatternDetector",
]


class DeterministicDetector:
    """Détecteur composite : motifs déclaratifs + règles contextuelles + fusion.

    ``config_path`` permet de pointer vers une variante de
    ``patterns.yaml`` (tests, jeux de motifs restreints). Par défaut, charge
    ``configs/detection/patterns.yaml`` à la racine du dépôt.
    """

    name: str = "deterministic_detector"

    def __init__(self, config_path: Path | None = None, strategy: str = "priority_longest") -> None:
        self._patterns, self._lexicons = load_patterns(config_path)
        self._strategy = strategy

    @property
    def patterns(self) -> Sequence[CompiledPattern]:
        return self._patterns

    @property
    def lexicons(self) -> dict[str, list[str]]:
        return self._lexicons

    def detect_raw(self, text: str, language: str = "fr") -> list[Candidate]:
        """Candidats bruts, AVANT fusion.

        Les appelants qui pilotent eux-mêmes la fusion (l'orchestrateur, dont
        le profil déclare ``stages.fuse.strategy``) doivent passer par ici :
        ``detect`` applique déjà la stratégie propre au détecteur.
        """
        raw = list(apply_patterns(text, language, self._patterns))
        raw.extend(apply_rules(text, language, self._lexicons))
        return raw

    def detect(self, text: str, language: str = "fr") -> list[Candidate]:
        """Détecte les candidats QI dans ``text``, fusionnés et triés par position.

        Les offsets retournés réfèrent toujours à ``text`` tel que passé en
        argument (invariant documenté dans ``detect/base.py``).
        """
        fused, _decisions = fuse(self.detect_raw(text, language), strategy=self._strategy)
        return fused

    def detect_with_trace(
        self, text: str, language: str = "fr"
    ) -> tuple[list[Candidate], list[FusionDecision]]:
        """Variante de ``detect`` qui expose aussi les décisions de fusion."""
        return fuse(self.detect_raw(text, language), strategy=self._strategy)

    def detect_annotations(
        self, text: str, doc_id: str, language: str = "fr"
    ) -> list[Annotation]:
        """Détecte puis convertit directement en ``Annotation`` SPEC-02."""
        candidates = self.detect(text, language)
        return candidates_to_annotations(candidates, doc_id, text)


class PatternDetector:
    """Détecteur par motifs déclaratifs seuls (regex sans règles contextuelles) + fusion."""

    name: str = "pattern_detector"

    def __init__(self, config_path: Path | None = None, strategy: str = "priority_longest") -> None:
        self._patterns, self._lexicons = load_patterns(config_path)
        self._strategy = strategy

    @property
    def patterns(self) -> Sequence[CompiledPattern]:
        return self._patterns

    @property
    def lexicons(self) -> dict[str, list[str]]:
        return self._lexicons

    def detect_raw(self, text: str, language: str = "fr") -> list[Candidate]:
        """Candidats bruts, AVANT fusion (cf. ``DeterministicDetector.detect_raw``)."""
        return list(apply_patterns(text, language, self._patterns))

    def detect(self, text: str, language: str = "fr") -> list[Candidate]:
        """Détecte les candidats en appliquant UNIQUEMENT les motifs déclaratifs."""
        fused, _decisions = fuse(self.detect_raw(text, language), strategy=self._strategy)
        return fused

    def detect_with_trace(
        self, text: str, language: str = "fr"
    ) -> tuple[list[Candidate], list[FusionDecision]]:
        """Variante de ``detect`` qui expose aussi les décisions de fusion."""
        return fuse(self.detect_raw(text, language), strategy=self._strategy)

    def detect_annotations(
        self, text: str, doc_id: str, language: str = "fr"
    ) -> list[Annotation]:
        """Détecte puis convertit directement en ``Annotation`` SPEC-02."""
        candidates = self.detect(text, language)
        return candidates_to_annotations(candidates, doc_id, text)
