"""Étape DETECT : détecteur natif du dépôt + adaptateur GLiNER optionnel.

Le détecteur natif (``detect/patterns.py`` + ``detect/rules.py`` +
``detect/validators.py``) reste la source unique des identifiants directs
(emails, téléphones, IBAN, NIR, cartes/Luhn, dates) et des QI par règles
contextuelles — **Presidio n'est pas ajouté** : pas de deuxième moteur de
regex concurrent. Ses candidats sont filtrés sur
``confidence >= qi_min_confidence`` (paramètre du système).

L'adaptateur GLiNER (``gliner`` + ``fastino/gliner2-privacy-filter-PII-multi``)
n'est importé et instancié **que si ``ner_enabled=true``** : module ou
poids locaux manquants → :class:`GlinerConfigError` nommée et actionnable —
**aucun repli silencieux** vers le détecteur natif (la couverture NER ne
doit jamais être présentée comme acquise sans exécution réelle).

Les offsets produits (natif ET GLiNER) réfèrent au texte original
``doc.text`` à toutes les étapes ; aucun chevauchement n'est résolu ici —
la fusion multi-label est l'étape FUSE.
"""

from __future__ import annotations

from collections.abc import Sequence

from anonymisation.detect import Candidate, DeterministicDetector
from anonymisation.schema.models import Document
from anonymisation.schema.taxonomy import (
    ExpressionMode,
    Granularity,
    IdentifierType,
    Sensitivity,
    Stability,
)

__all__ = [
    "GLINER_LABEL_MAP",
    "GLINER_MODEL",
    "GlinerConfigError",
    "GlinerDetector",
    "run_detection",
]

#: Modèle GLiNER exact utilisé par le pipeline (jamais remplacé
#: silencieusement par un autre poids).
GLINER_MODEL: str = "fastino/gliner2-privacy-filter-PII-multi"

#: Labels demandés au modèle → codes SPEC-01, **mapping strict** : une
#: étiquette retournée hors de ce dictionnaire est une erreur, pas une
#: valeur devinée. ``person``/``address`` sont des identifiants directs ;
#: ``date``/``organization``/``location`` des QI.
GLINER_LABEL_MAP: dict[str, str] = {
    "person": "DIR_NAME",
    "address": "DIR_ADDRESS",
    "date": "GEN_DATE_EVENT",
    "organization": "GEN_AFFILIATION",
    "location": "GEN_GEO",
}

#: Type d'identifiant porté par chaque code cible (déduit de la
#: taxonomie : ``DIR_*`` direct, ``GEN_*`` quasi).
GLINER_IDENTIFIER_TYPE: dict[str, IdentifierType] = {
    "DIR_NAME": IdentifierType.DIRECT,
    "DIR_ADDRESS": IdentifierType.DIRECT,
    "GEN_DATE_EVENT": IdentifierType.QUASI,
    "GEN_AFFILIATION": IdentifierType.QUASI,
    "GEN_GEO": IdentifierType.QUASI,
}


class GlinerConfigError(RuntimeError):
    """GLiNER demandé (``ner_enabled=true``) mais indisponible : module
    ``gliner``/``torch`` absent, téléchargement des poids échoué, étiquette
    inconnue retournée par le modèle, span hors bornes.

    Nomme le prérequis manquant et le correctif (extra ``models`` du
    projet, poids locaux) — l'exécution ne continue jamais sur le
    détecteur natif seul sous couvert d'une couverture NER fictive.
    """


class GlinerDetector:
    """Adaptateur GLiNER paresseux : construit uniquement si l'option est
    activée ; toute indisponibilité lève :class:`GlinerConfigError`."""

    name = "gliner"

    def __init__(
        self,
        *,
        threshold: float = 0.35,
        person_threshold: float = 0.55,
    ) -> None:
        self._threshold = threshold
        self._person_threshold = person_threshold
        try:
            import gliner
        except ImportError as exc:
            raise GlinerConfigError(
                "ner_enabled=true mais le module 'gliner' est absent — "
                "installer l'extra 'models' du projet (uv sync --extra llm "
                "--extra models) ou mettre ner_enabled=false. Aucun repli "
                "silencieux vers le détecteur natif."
            ) from exc
        try:
            self._model = gliner.Gliner.from_pretrained(GLINER_MODEL)
        except Exception as exc:
            raise GlinerConfigError(
                f"modèle GLiNER {GLINER_MODEL!r} indisponible "
                f"({exc.__class__.__name__}: {exc}) — vérifier les poids "
                "locaux (extra 'models') ou mettre ner_enabled=false. "
                "Aucun repli silencieux vers le détecteur natif."
            ) from exc

    def _predict(
        self, sentence: str, labels: Sequence[str], threshold: float
    ) -> list[tuple[str, int, int, float | None]]:
        """Prédiction ``gliner`` : ``(label, start, end, score|None)``.

        ``return_scores`` est demandé quand l'API le permet ; sinon le
        score est ``None`` (le seuil appliqué reste la borne honnête,
        tracée en ``meta``).
        """
        try:
            raw = self._model.predict(
                sentence,
                label_set=list(labels),
                threshold=threshold,
                return_scores=True,
            )
        except TypeError:
            raw = self._model.predict(
                sentence, label_set=list(labels), threshold=threshold
            )
            return [(str(label), int(start), int(end), None) for label, start, end in raw]
        out: list[tuple[str, int, int, float | None]] = []
        for item in raw:
            if len(item) != 4:
                raise GlinerConfigError(
                    f"modèle {GLINER_MODEL!r} : forme de sortie inattendue "
                    f"{item!r} (attendu (label, start, end, score)) — "
                    "vérifier la version du module gliner."
                )
            label, start, end, score = item
            out.append((str(label), int(start), int(end), float(score)))
        return out

    def detect(self, doc: Document) -> list[Candidate]:
        """Entités GLiNER du document mappées en ``Candidate`` SPEC-02.

        Seuils : ``person_threshold`` pour ``person``, ``threshold`` pour
        les autres labels (appels séparés — le seuil s'applique à
        l'intérieur de ``predict``). Chaque span est **vérifié** contre le
        texte original : bornes dans ``doc.text`` et ``doc.text[start:end]``
        = surface produite ; un span entièrement blanc est réduit à sa
        partie non blanche (offsets recalés, jamais inventés).
        """
        text = doc.text
        raw_person = self._predict(text, ["person"], self._person_threshold)
        raw_other = self._predict(
            text, ["address", "date", "organization", "location"], self._threshold
        )
        candidates: list[Candidate] = []
        for label, start, end, score in [*raw_person, *raw_other]:
            code = GLINER_LABEL_MAP.get(label)
            if code is None:
                raise GlinerConfigError(
                    f"modèle {GLINER_MODEL!r} : étiquette {label!r} hors du "
                    "mapping strict "
                    f"({', '.join(sorted(GLINER_LABEL_MAP))}) — corriger le "
                    "mapping ou les labels demandés ; jamais deviné."
                )
            if not (0 <= start < end <= len(text)):
                raise GlinerConfigError(
                    f"modèle {GLINER_MODEL!r} : span hors bornes "
                    f"({start}, {end}) pour un texte de longueur {len(text)} "
                    f"(label {label!r}) — offsets non fiables, document rejeté."
                )
            # Réduction aux caractères non blancs du span (offsets recalés
            # sur le texte original — l'invariant doc.text[start:end] doit
            # rester vrai).
            first = start
            last = end
            while first < last and text[first] in " \t\n\r":
                first += 1
            while last > first and text[last - 1] in " \t\n\r":
                last -= 1
            if first >= last:
                continue  # span entièrement blanc : entité dégénérée
            surface = text[first:last]
            if not surface:
                continue
            if score is not None:
                confidence = score
            else:
                # Score indisponible dans cette version de l'API : le seuil
                # que l'entité a franchi est la borne honnête de confiance.
                confidence = (
                    self._person_threshold if label == "person" else self._threshold
                )
            confidence = max(0.0, min(1.0, confidence))
            candidates.append(
                Candidate(
                    start=first,
                    end=last,
                    text=surface,
                    qi_category=code,
                    identifier_type=GLINER_IDENTIFIER_TYPE[code],
                    source=f"gliner:{label}",
                    confidence=confidence,
                    granularity=Granularity.EXACT,
                    stability=Stability.STABLE,
                    expression_mode=ExpressionMode.EXPLICIT,
                    meta={
                        "sensitivity": Sensitivity.NONE.value,
                        "value_normalized": {},
                    },
                )
            )
        return candidates


def run_detection(
    *,
    doc: Document,
    detector: DeterministicDetector,
    qi_min_confidence: float,
    gliner: GlinerDetector | None,
) -> list[Candidate]:
    """Candidats de l'étape DETECT (avant fusion) :

    - **natif** (toujours) : ``DeterministicDetector.detect_raw`` filtrés
      sur ``confidence >= qi_min_confidence`` ;
    - **GLiNER** (optionnel) : uniquement si instancié
      (``ner_enabled=true``) — ses seuils propres gouvernent déjà.

    ``gliner=None`` (option désactivée) : aucun import, aucun modèle.
    """
    candidates: list[Candidate] = [
        c
        for c in detector.detect_raw(doc.text, language=doc.language)
        if c.confidence >= qi_min_confidence
    ]
    if gliner is not None:
        candidates.extend(gliner.detect(doc))
    return candidates
