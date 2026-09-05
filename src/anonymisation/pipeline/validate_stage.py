"""Étape 6 — VALIDATE : contrôle hors-ligne de l'anonymisation (SPEC-10 §3).

Trois contrôles complémentaires, tous calculés **hors-ligne** — aucun modèle
n'est ré-exécuté (SPEC-10, contrainte C5) :

1. **Placeholders bien formés** — chaque remplacement produit par une
   décision non-KEEP est présent dans le texte anonymisé, à la forme attendue
   (placeholder pseudonyme ``[CAT_X…]`` ou masque ``[CAT]``) ; une
   transformation ultérieure ne doit pas avoir tronqué ou corrompu un
   placeholder ;
2. **Motifs interdits résiduels** — le texte anonymisé ne contient plus
   aucun motif détectable par la couche ``detect/`` en catégorie **DIRECT**
   (e-mail, IBAN, IP, téléphone…) ;
3. **Fuite de valeurs gold** — aucune valeur gold d'identifiant direct du
   pivot ne subsiste dans le texte anonymisé. Ce contrôle est une
   **recherche exacte dans le texte**, donc **indépendant du détecteur** :
   c'est lui qui attrape ce que le détecteur a raté (ex. une adresse e-mail
   rejetée par un ``deny_context``) — l'acceptation SPEC-10 §9 (« 0 fuite
   détectable ») exige cette indépendance.

Sémantique des résultats :

* ``ok=True`` → document non touché ;
* sinon, l'orchestrateur marque le document ``partial`` (constat journalisé)
  ou l'interrompt en ``error`` **uniquement** si ``fail_on_leak`` est vrai et
  qu'une fuite gold a été constatée — l'interrupteur est un interrupteur de
  document, pas du run.

Les surfaces gold éventuellement exposées par :class:`ValidationOutcome` ne
doivent être journalisées qu'au travers du nombre de fuites (la valeur elle-
même reste dans le pivot, jamais dans les logs).
"""

from __future__ import annotations

import re
from collections.abc import Sequence
from dataclasses import dataclass
from typing import Final

from anonymisation.detect.patterns import CompiledPattern, apply_patterns
from anonymisation.detect.rules import apply_rules
from anonymisation.pipeline.profiles import ValidateSpec
from anonymisation.schema.models import Annotation
from anonymisation.schema.taxonomy import IdentifierType
from anonymisation.transform.decisions import Action, AnonymizationDecision

#: Forme d'un placeholder pseudonyme produit par ``PseudoMapper`` :
#: ``[<CATEGORIE>_<base32 de 4 à 32 caractères>]``.
_PSEUDO_RE: Final = re.compile(r"^\[[A-Z0-9_]+_[A-Z0-9]{4,32}\]$")


@dataclass(frozen=True)
class ValidationOutcome:
    """Résultat de l'étape VALIDATE pour un document.

    Les trois tuples sont vides si le contrôle correspondant n'a rien
    trouvé ; ``ok`` est vrai seulement si les trois sont vides.
    """

    ok: bool
    leaked_direct: tuple[str, ...]
    malformed_placeholders: tuple[str, ...]
    residual_patterns: tuple[str, ...]

    def summary(self) -> str:
        """Résumé sans valeur sensible (journalisable)."""
        return (
            f"{len(self.leaked_direct)} fuite(s) gold, "
            f"{len(self.residual_patterns)} motif(s) DIRECT résiduel(s), "
            f"{len(self.malformed_placeholders)} placeholder(s) malformé(s)"
        )


def _dedupe(items: list[str]) -> tuple[str, ...]:
    seen: set[str] = set()
    out: list[str] = []
    for item in items:
        if item not in seen:
            seen.add(item)
            out.append(item)
    return tuple(out)


def validate_anonymization(
    *,
    anonymized_text: str,
    decisions: Sequence[AnonymizationDecision],
    gold_annotations: Sequence[Annotation] = (),
    patterns: Sequence[CompiledPattern] = (),
    lexicons: dict[str, list[str]] | None = None,
    language: str = "fr",
    checks: ValidateSpec,
) -> ValidationOutcome:
    """Exécute les trois contrôles hors-ligne de l'étape VALIDATE.

    Args:
        anonymized_text: texte produit par TRANSFORM.
        decisions: décisions complètes du document (KEEP incluses, qui sont
            ignorées par le contrôle de placeholders).
        gold_annotations: annotations du pivot ; seules les surfaces
            ``DIRECT`` non vides sont testées par recherche exacte.
        patterns: patterns compilés du profil (contrôle de résidus).
        lexicons: lexiques des règles (mêmes motifs que DETECT).
        language: langue du document (ISO 639-1), pour la réexécution des
            patterns/règles sur le texte anonymisé.
        checks: bloc ``stages.validate`` du profil (interrupteurs de
            contrôle).
    """
    malformed: list[str] = []
    residual: list[str] = []
    leaked: list[str] = []

    # -- 1. Placeholders bien formés, non corrompus.
    if checks.check_placeholders:
        for d in decisions:
            if d.action is Action.KEEP or d.replacement == "":
                continue
            if d.replacement not in anonymized_text:
                malformed.append(
                    f"remplacement {d.action.value} absent du texte anonymisé "
                    f"({d.qi_category}@{d.start}-{d.end})"
                )
                continue
            if d.action is Action.PSEUDONYMIZE and not _PSEUDO_RE.match(d.replacement):
                malformed.append(
                    f"placeholder pseudonyme malformé pour {d.qi_category}@{d.start}-{d.end}"
                )

    if checks.check_forbidden_patterns:
        matches = apply_patterns(anonymized_text, language, patterns)
        if lexicons is not None:
            matches = [*matches, *apply_rules(anonymized_text, language, lexicons)]
        replacements = {d.replacement for d in decisions if d.replacement}
        for m in matches:
            if m.identifier_type is not IdentifierType.DIRECT:
                continue
            # Un motif qui n'est qu'un sous-texte d'un placeholder déjà
            # introduit est un faux positif (ex. un fragment de base32) —
            # un véritable résidu n'est jamais sous-texte d'un
            # remplacement.
            if any(m.text in replacement for replacement in replacements):
                continue
            residual.append(f"{m.qi_category}@{m.start}-{m.end}")

    # -- 3. Fuite de valeurs gold (recherche exacte, indépendante du
    # détecteur).
    if checks.check_gold_leakage:
        for g in gold_annotations:
            if g.identifier_type is not IdentifierType.DIRECT or not g.span_text:
                continue
            if g.span_text in anonymized_text:
                leaked.append(g.span_text)

    return ValidationOutcome(
        ok=not (leaked or residual or malformed),
        leaked_direct=_dedupe(leaked),
        malformed_placeholders=_dedupe(malformed),
        residual_patterns=_dedupe(residual),
    )
