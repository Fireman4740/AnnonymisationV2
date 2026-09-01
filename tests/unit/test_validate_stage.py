"""Tests de l'étape VALIDATE (ticket C-2, SPEC-10 §3, §9).

Les trois contrôles hors-ligne de ``validate_anonymization`` :

* **fuite de valeurs gold** — recherche exacte dans le texte anonymisé,
  **indépendante du détecteur** : la couche de détection doit pouvoir être
  entièrement absente (aucun pattern, aucun lexique) pour que la fuite soit
  tout de même constatée — c'est elle qui attrape ce que le détecteur a
  rejeté (ex. un e-mail tombé sur un ``deny_context``, jeu micro d5) ;
* **motifs DIRECT résiduels** — le texte anonymisé ne doit plus porter de
  motif d'identifiant direct reconnaissable (réexécution hors-ligne des
  patterns du profil, contrainte C5 : aucun modèle) ;
* **placeholders bien formés** — chaque remplacement d'une décision
  non-KEEP doit être présent intact dans le texte ; un placeholder
  pseudonyme doit porter la forme ``[CAT_X…]``.

Plus : les interrupteurs de contrôle (``ValidateSpec``) et le résumé
journalisable (jamais de valeur sensible). Le comportement ``fail_on_leak``
(interruption du document seul) est couvert au niveau orchestrateur dans
``test_orchestrator.py``.
"""

from __future__ import annotations

from anonymisation.detect.patterns import load_patterns
from anonymisation.pipeline.profiles import ValidateSpec
from anonymisation.pipeline.validate_stage import validate_anonymization
from anonymisation.schema.models import Annotation
from anonymisation.transform.decisions import Action, AnonymizationDecision

#: Modèle de la ligne gold d5 du jeu micro (schéma exact du pivot).
_GOLD_FIELDS: dict[str, object] = {
    "annotator_id": None,
    "confidence": 1.0,
    "entity_id": None,
    "expression_mode": "EXPLICIT",
    "granularity": "EXACT",
    "identifier_type": "DIRECT",
    "meta": {},
    "qi_categories": ["DIR_EMAIL"],
    "sensitivity": "NONE",
    "stability": "STABLE",
    "value_normalized": None,
}


def _gold_direct(annotation_id: str, doc_id: str, text: str, span: str) -> Annotation:
    start = text.index(span)
    data = dict(_GOLD_FIELDS)
    data.update(
        {
            "annotation_id": annotation_id,
            "doc_id": doc_id,
            "start": start,
            "end": start + len(span),
            "span_text": span,
        }
    )
    return Annotation.model_validate(data)


def _suppress_decision(text: str, span: str, category: str = "DIR_EMAIL") -> AnonymizationDecision:
    start = text.index(span)
    return AnonymizationDecision(
        start=start,
        end=start + len(span),
        original=span,
        action=Action.SUPPRESS,
        replacement=f"[{category}_SUPPRIME]",
        qi_category=category,
        reason="test",
    )


# --------------------------------------------------------------------------- #
# 3. Fuite de valeurs gold — recherche exacte, indépendante du détecteur
# --------------------------------------------------------------------------- #
def test_gold_leak_is_independent_of_the_detector() -> None:
    """L'e-mail est présent dans le texte anonymisé et la couche de détection
    est absente (aucun pattern, aucun lexique) : la fuite est quand même
    constatée par recherche exacte (SPEC-10 §9 « 0 fuite détectable »)."""
    text = "Contactez-moi à jean.dupont@example.com pour le contrat."
    gold = _gold_direct("v:1", "v:doc", text, "jean.dupont@example.com")
    outcome = validate_anonymization(
        anonymized_text=text,
        decisions=(),
        gold_annotations=(gold,),
        patterns=(),
        lexicons=None,
        language="fr",
        checks=ValidateSpec(),
    )
    assert outcome.ok is False
    assert outcome.leaked_direct == ("jean.dupont@example.com",)
    assert outcome.residual_patterns == ()
    assert outcome.malformed_placeholders == ()


def test_suppressed_gold_is_clean() -> None:
    """Même e-mail, bien supprimé : aucun des trois contrôles ne conclut."""
    original = "Contactez-moi à jean.dupont@example.com pour le contrat."
    anonymized = original.replace("jean.dupont@example.com", "[DIR_EMAIL_SUPPRIME]")
    gold = _gold_direct("v:1", "v:doc", original, "jean.dupont@example.com")
    decision = _suppress_decision(original, "jean.dupont@example.com")
    patterns, lexicons = load_patterns()
    outcome = validate_anonymization(
        anonymized_text=anonymized,
        decisions=(decision,),
        gold_annotations=(gold,),
        patterns=patterns,
        lexicons=lexicons,
        language="fr",
        checks=ValidateSpec(),
    )
    assert outcome.ok is True
    assert outcome.leaked_direct == ()
    assert outcome.residual_patterns == ()
    assert outcome.malformed_placeholders == ()


def test_gold_quasi_annotations_are_ignored_by_the_leak_check() -> None:
    """Seules les surfaces DIRECT non vides sont testées (contrat du module) :
    un quasi-identifiant gold subsistant n'est pas une « fuite gold »."""
    text = "J'ai 45 ans, c'est une information quasi."
    quasi = Annotation.model_validate(
        {
            **_GOLD_FIELDS,
            "annotation_id": "v:2",
            "doc_id": "v:doc",
            "start": text.index("45 ans"),
            "end": text.index("45 ans") + len("45 ans"),
            "span_text": "45 ans",
            "identifier_type": "QUASI",
            "qi_categories": ["GEN_AGE"],
        }
    )
    outcome = validate_anonymization(
        anonymized_text=text,
        decisions=(),
        gold_annotations=(quasi,),
        patterns=(),
        lexicons=None,
        language="fr",
        checks=ValidateSpec(),
    )
    assert outcome.ok is True


# --------------------------------------------------------------------------- #
# 2. Motifs DIRECT résiduels
# --------------------------------------------------------------------------- #
def test_residual_direct_pattern_is_detected() -> None:
    """Un e-mail subsiste dans le texte anonymisé (hors liste de refus) :
    la réexécution hors-ligne des patterns du profil le signale."""
    text = "Pour l'incident, joindre support@acme-corp.fr directement."
    patterns, lexicons = load_patterns()
    outcome = validate_anonymization(
        anonymized_text=text,
        decisions=(),
        gold_annotations=(),
        patterns=patterns,
        lexicons=lexicons,
        language="fr",
        checks=ValidateSpec(),
    )
    assert outcome.ok is False
    assert len(outcome.residual_patterns) >= 1
    assert any(item.startswith("DIR_EMAIL@") for item in outcome.residual_patterns)
    assert outcome.leaked_direct == ()


def test_residual_check_ignores_quasi_patterns() -> None:
    """Seuls les motifs DIRECT comptent comme résidus (contrat du module) :
    un texte sans aucun motif DIRECT est propre, quels que soient les
    motifs QUASI éventuellement reconnaisables."""
    text = "La réunion a eu lieu dans l'après-midi, tout s'est bien passé."
    patterns, lexicons = load_patterns()
    outcome = validate_anonymization(
        anonymized_text=text,
        decisions=(),
        gold_annotations=(),
        patterns=patterns,
        lexicons=lexicons,
        language="fr",
        checks=ValidateSpec(),
    )
    assert outcome.ok is True
    assert outcome.residual_patterns == ()


# --------------------------------------------------------------------------- #
# 1. Placeholders bien formés, non corrompus
# --------------------------------------------------------------------------- #
def test_placeholder_missing_from_text_is_malformed() -> None:
    """Le remplacement déclaré par la décision n'est pas présent dans le
    texte : une transformation ultérieure l'a tronqué ou corrompu."""
    text = "M. [DIR_NAME_SUPPRIMÉ] a appelé."
    decision = AnonymizationDecision(
        start=3,
        end=9,
        original="Pierre",
        action=Action.SUPPRESS,
        replacement="[DIR_NAME_SUPPRIME]",
        qi_category="DIR_NAME",
        reason="test",
    )
    outcome = validate_anonymization(
        anonymized_text=text,
        decisions=(decision,),
        checks=ValidateSpec(),
    )
    assert outcome.ok is False
    assert len(outcome.malformed_placeholders) == 1
    assert "absent du texte anonymisé" in outcome.malformed_placeholders[0]


def test_pseudonym_placeholder_must_match_expected_shape() -> None:
    """Un placeholder pseudonyme présent mais hors forme ``[CAT_X…]``
    (base32, 4 à 32 caractères) est malformé."""
    text = "M. [DIR_NAME_!!] a appelé."
    decision = AnonymizationDecision(
        start=3,
        end=9,
        original="Pierre",
        action=Action.PSEUDONYMIZE,
        replacement="[DIR_NAME_!!]",
        qi_category="DIR_NAME",
        reason="test",
    )
    outcome = validate_anonymization(
        anonymized_text=text,
        decisions=(decision,),
        checks=ValidateSpec(),
    )
    assert outcome.ok is False
    assert "placeholder pseudonyme malformé" in outcome.malformed_placeholders[0]

    # La forme attendue est acceptée.
    good = "M. [DIR_NAME_ABCD1234] a appelé."
    good_decision = AnonymizationDecision(
        start=3,
        end=9,
        original="Pierre",
        action=Action.PSEUDONYMIZE,
        replacement="[DIR_NAME_ABCD1234]",
        qi_category="DIR_NAME",
        reason="test",
    )
    assert validate_anonymization(
        anonymized_text=good,
        decisions=(good_decision,),
        checks=ValidateSpec(),
    ).ok is True


def test_keep_decisions_are_ignored_by_the_placeholder_check() -> None:
    """Les décisions KEEP n'ont pas de remplacement à vérifier."""
    text = "Aucun identifiant ici."
    decision = AnonymizationDecision(
        start=0,
        end=5,
        original="Aucun",
        action=Action.KEEP,
        replacement="Aucun",
        qi_category="GEN_LIFESTYLE",
        reason="test",
    )
    assert validate_anonymization(
        anonymized_text=text,
        decisions=(decision,),
        checks=ValidateSpec(),
    ).ok is True


# --------------------------------------------------------------------------- #
# Interrupteurs de contrôle (ValidateSpec)
# --------------------------------------------------------------------------- #
def test_check_toggles_are_respected() -> None:
    text = "Contactez-moi à jean.dupont@example.com pour le contrat."
    gold = _gold_direct("v:1", "v:doc", text, "jean.dupont@example.com")

    # Contrôle gold actif (détecteur absent) → fuite constatée.
    leaked = validate_anonymization(
        anonymized_text=text,
        decisions=(),
        gold_annotations=(gold,),
        patterns=(),
        lexicons=None,
        checks=ValidateSpec(),
    )
    assert leaked.ok is False

    # Contrôle gold désactivé, détecteur absent → aucun contrôle ne conclut.
    gold_off = validate_anonymization(
        anonymized_text=text,
        decisions=(),
        gold_annotations=(gold,),
        patterns=(),
        lexicons=None,
        checks=ValidateSpec(check_gold_leakage=False),
    )
    assert gold_off.ok is True
    assert gold_off.leaked_direct == ()

    # Contrôle résidus désactivé → l'e-mail subsistant n'est plus signalé.
    patterns, lexicons = load_patterns()
    residual_off = validate_anonymization(
        anonymized_text="Joindre support@acme-corp.fr.",
        decisions=(),
        patterns=patterns,
        lexicons=lexicons,
        checks=ValidateSpec(check_forbidden_patterns=False),
    )
    assert residual_off.ok is True
    assert residual_off.residual_patterns == ()


# --------------------------------------------------------------------------- #
# Résumé journalisable : jamais de valeur sensible
# --------------------------------------------------------------------------- #
def test_summary_never_contains_sensitive_values() -> None:
    text = "Contactez-moi à jean.dupont@example.com pour le contrat."
    gold = _gold_direct("v:1", "v:doc", text, "jean.dupont@example.com")
    outcome = validate_anonymization(
        anonymized_text=text,
        decisions=(),
        gold_annotations=(gold,),
        patterns=(),
        lexicons=None,
        checks=ValidateSpec(),
    )
    assert outcome.summary() == (
        "1 fuite(s) gold, 0 motif(s) DIRECT résiduel(s), 0 placeholder(s) malformé(s)"
    )
    assert "jean.dupont@example.com" not in outcome.summary()
