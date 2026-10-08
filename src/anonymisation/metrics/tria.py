"""TRIA/TRIR sans LLM (SPEC-07 v2.0 §5, ticket G-3, correctif EPIC-H H-2).

Protocole (version 2)
---------------------
TRIA [@manzanares2024tria] modélise un attaquant qui dispose de **connaissances
auxiliaires** — d'autres textes reliés à des individus connus — et tente de
rattacher chaque document anonymisé publié à l'un d'eux. L'attaquant ne voit
**jamais** le texte original du document qu'il attaque.

La version 1 de ce module violait cette hypothèse : le classifieur était
entraîné sur le texte original de *tous* les documents évalués, puis
interrogé sur leurs versions anonymisées. TRIR mesurait alors le recouvrement
lexical résiduel avec l'original — pas un risque de ré-identification — et
valait 1 par construction sur un texte non anonymisé.

La version 2 sépare connaissances auxiliaires et cibles par **validation
croisée à K blocs, groupée par sujet** :

* les documents de chaque sujet sont répartis de façon déterministe sur les
  K blocs (tourniquet décalé par une empreinte SHA-256 du sujet) ;
* pour le bloc ``f``, l'attaquant est entraîné sur les textes **originaux** de
  tous les documents hors de ``f`` (IDF compris), puis interrogé sur les textes
  **anonymisés** des documents de ``f`` ;
* un document dont le sujet n'a aucun autre document n'est pas une cible
  évaluable (aucune connaissance auxiliaire possible) : il est compté dans
  ``excluded_no_background`` et sert de distracteur dans les autres blocs.

L'intersection apprentissage/cible est vérifiée par assertion à chaque bloc :
une régression qui réintroduirait la fuite échoue bruyamment.

Égalités et niveaux de référence
--------------------------------
Les égalités de score sont résolues en **espérance** : si ``g`` candidats ont
un score strictement supérieur au vrai sujet et ``e`` un score égal (vrai sujet
compris), la probabilité d'un succès top-k est ``clip((k - g) / e, 0, 1)``. Un
texte vide donne donc exactement le hasard, sans dépendre de l'ordre
lexicographique des identifiants.

Deux niveaux de référence sont publiés : le hasard uniforme ``1/N`` (moyenne
par cible du nombre de candidats de son bloc) et la **classe majoritaire**
(attaquant qui désigne toujours le sujet le plus documenté). Sur un corpus
déséquilibré, le second peut dépasser nettement le premier : comparer TRIR au
seul ``1/N`` serait optimiste.

Limite assumée : classifieur TF-IDF par centroïde, déterministe et sans
dépendance. TRIA utilise un encodeur neuronal fin-tuné ; le résultat est donc
publié en ``PROXY`` (un attaquant plus fort ne ferait qu'augmenter TRIR).
"""

from __future__ import annotations

import hashlib
import math
import re
from collections import Counter, defaultdict
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass, field
from typing import Any, TypeAlias

_TOKEN_RE = re.compile(r"(?u)\b\w+\b")
RecordLike: TypeAlias = Any

#: Nombre de blocs par défaut. 5 garde 80 % des documents comme connaissance
#: auxiliaire à chaque bloc, tout en bornant le coût à 5 apprentissages.
DEFAULT_FOLDS = 5
TOP_K = (1, 5)
PROTOCOL = "tria-tfidf-centroid-heldout"
PROTOCOL_VERSION = "2"


class TRIRUnavailable(ValueError):
    """TRIR non calculable sur ce corpus — raison explicite, jamais un zéro."""


def _field(record: RecordLike, name: str, default: Any = None) -> Any:
    if isinstance(record, Mapping):
        return record.get(name, default)
    return getattr(record, name, default)


def _record_id(record: RecordLike, index: int) -> str:
    value = _field(record, "doc_id", _field(record, "id", None))
    return str(value) if value is not None else f"record:{index}"


def _subject_id(record: RecordLike) -> str:
    value = _field(record, "subject_id", None)
    if value is None:
        value = _field(record, "author_id", None)
    if value is None or not str(value).strip():
        raise ValueError("chaque document TRIA doit porter subject_id ou author_id")
    return str(value)


def _text(record: RecordLike) -> str:
    value = _field(record, "text", _field(record, "original_text", None))
    if not isinstance(value, str):
        raise ValueError("chaque document TRIA doit porter un texte str")
    return value


def _tokens(text: str) -> tuple[str, ...]:
    return tuple(token.casefold() for token in _TOKEN_RE.findall(text))


@dataclass(frozen=True)
class TRIARecord:
    """Document candidat : texte **original** et sujet auquel il se rattache."""

    doc_id: str
    subject_id: str
    text: str


@dataclass(frozen=True)
class TargetOutcome:
    """Résultat d'une cible : probabilités espérées de succès top-1 / top-5."""

    doc_id: str
    subject_id: str
    fold: int
    top1: float
    top5: float
    chance: float
    majority: float


@dataclass(frozen=True)
class TRIRResult:
    """Résultat TRIR, avec niveaux de référence et comptes d'exclusion."""

    accuracy: float | None
    top5: float | None
    candidate_count: int
    candidate_subjects: tuple[str, ...]
    correct: float
    total: int
    chance_level: float | None
    majority_level: float | None
    folds: int
    excluded_no_background: int
    outcomes: tuple[TargetOutcome, ...] = field(default=(), repr=False)
    protocol: str = PROTOCOL
    protocol_version: str = PROTOCOL_VERSION

    @property
    def trir(self) -> float | None:
        """Alias explicite pour les scorecards qui nomment la métrique TRIR."""
        return self.accuracy

    def to_dict(self) -> dict[str, Any]:
        # La liste des sujets candidats n'est pas sérialisée : sur un grand
        # corpus elle gonflerait la scorecard sans rien apprendre au lecteur.
        return {
            "name": "trir",
            "value": self.accuracy,
            "accuracy": self.accuracy,
            "top5_accuracy": self.top5,
            "candidate_count": self.candidate_count,
            "correct": self.correct,
            "total": self.total,
            "chance_level": self.chance_level,
            "majority_level": self.majority_level,
            "folds": self.folds,
            "excluded_no_background": self.excluded_no_background,
            "tie_policy": "espérance (crédit fractionnaire entre ex-aequo)",
            "attacker_training": "textes originaux hors bloc (connaissance auxiliaire)",
            "attacker_targets": "textes anonymisés du bloc, jamais vus en apprentissage",
            "protocol": self.protocol,
            "protocol_version": self.protocol_version,
        }


class TfidfReidentifier:
    """Classifieur document -> sujet par centroïde TF-IDF.

    Le produit scalaire passe par un index inversé (jeton -> sujets) : la
    prédiction coûte la taille du vocabulaire partagé, pas le nombre de sujets.
    """

    def __init__(self) -> None:
        self._idf: dict[str, float] = {}
        self._postings: dict[str, list[tuple[str, float]]] = {}
        self._norms: dict[str, float] = {}
        self._subjects: tuple[str, ...] = ()
        self._doc_counts: dict[str, int] = {}

    @property
    def candidate_subjects(self) -> tuple[str, ...]:
        return self._subjects

    @property
    def subject_document_counts(self) -> Mapping[str, int]:
        return self._doc_counts

    def fit(self, records: Iterable[RecordLike]) -> TfidfReidentifier:
        rows = list(records)
        if not rows:
            raise ValueError("TRIA requiert au moins un document candidat")
        subject_documents: dict[str, list[tuple[str, ...]]] = defaultdict(list)
        document_frequency: Counter[str] = Counter()
        for record in rows:
            tokens = _tokens(_text(record))
            subject_documents[_subject_id(record)].append(tokens)
            document_frequency.update(set(tokens))
        self._subjects = tuple(sorted(subject_documents))
        self._doc_counts = {s: len(subject_documents[s]) for s in self._subjects}
        document_count = len(rows)
        self._idf = {
            token: math.log((1.0 + document_count) / (1.0 + frequency)) + 1.0
            for token, frequency in document_frequency.items()
        }
        postings: dict[str, list[tuple[str, float]]] = defaultdict(list)
        for subject in self._subjects:
            vectors = [self._vector(tokens) for tokens in subject_documents[subject]]
            centroid: dict[str, float] = defaultdict(float)
            for vector in vectors:
                for token, value in vector.items():
                    centroid[token] += value / len(vectors)
            self._norms[subject] = math.sqrt(sum(v * v for v in centroid.values()))
            for token in sorted(centroid):
                postings[token].append((subject, centroid[token]))
        self._postings = dict(postings)
        return self

    def _vector(self, tokens: Sequence[str]) -> dict[str, float]:
        if not tokens:
            return {}
        counts = Counter(tokens)
        length = float(len(tokens))
        return {
            token: (count / length) * self._idf[token]
            for token, count in counts.items()
            if token in self._idf
        }

    def scores(self, text: str) -> dict[str, float]:
        """Similarité cosinus du texte avec chaque sujet candidat (0 par défaut)."""
        if not self._subjects:
            raise ValueError("le classifieur TRIA doit être entraîné avant scores")
        vector = self._vector(_tokens(text))
        norm = math.sqrt(sum(v * v for v in vector.values()))
        result = dict.fromkeys(self._subjects, 0.0)
        if not norm:
            return result
        for token, value in vector.items():
            for subject, weight in self._postings.get(token, ()):
                result[subject] += value * weight
        return {
            subject: (dot / (norm * self._norms[subject]) if self._norms[subject] else 0.0)
            for subject, dot in result.items()
        }

    def predict(self, text: str) -> str:
        """Sujet de score maximal ; égalité départagée par ordre alphabétique.

        Réservé à l'inspection manuelle : la métrique utilise
        :func:`expected_hit`, qui ne dépend pas de cet ordre arbitraire.
        """
        scores = self.scores(text)
        return min(self._subjects, key=lambda subject: (-scores[subject], subject))


def expected_hit(scores: Mapping[str, float], truth: str, k: int) -> float:
    """Probabilité de succès top-k quand les ex-aequo sont départagés au hasard."""
    if truth not in scores:
        raise ValueError(f"sujet {truth!r} absent des candidats de l'attaquant")
    reference = scores[truth]
    greater = sum(1 for value in scores.values() if value > reference)
    equal = sum(1 for value in scores.values() if value == reference)
    return min(1.0, max(0.0, (k - greater) / equal))


def _majority_credit(counts: Mapping[str, int], truth: str) -> float:
    best = max(counts.values())
    leaders = [subject for subject, count in counts.items() if count == best]
    return 1.0 / len(leaders) if truth in leaders else 0.0


def assign_folds(records: Sequence[RecordLike], folds: int) -> dict[str, int]:
    """Bloc de chaque document : tourniquet par sujet, décalé par empreinte.

    Déterministe (aucun aléa de processus : ``hash()`` varie entre exécutions
    Python, SHA-256 non) et équilibré : les documents d'un sujet se répartissent
    sur des blocs distincts, donc tout sujet à ≥ 2 documents a une connaissance
    auxiliaire dans chaque bloc où il a une cible.
    """
    by_subject: dict[str, list[str]] = defaultdict(list)
    for index, record in enumerate(records):
        by_subject[_subject_id(record)].append(_record_id(record, index))
    assignment: dict[str, int] = {}
    for subject, doc_ids in by_subject.items():
        offset = int(hashlib.sha256(subject.encode("utf-8")).hexdigest()[:8], 16) % folds
        for position, doc_id in enumerate(sorted(doc_ids)):
            if doc_id in assignment:
                raise ValueError(f"doc_id dupliqué dans les candidats TRIA : {doc_id!r}")
            assignment[doc_id] = (position + offset) % folds
    return assignment


def _anonymized_texts(
    records: Sequence[RecordLike], anonymized: Mapping[str, str] | Sequence[str] | None
) -> dict[str, str]:
    ids = [_record_id(record, index) for index, record in enumerate(records)]
    if anonymized is None:
        return {doc_id: _text(record) for doc_id, record in zip(ids, records, strict=True)}
    if isinstance(anonymized, Mapping):
        missing = [doc_id for doc_id in ids if doc_id not in anonymized]
        if missing:
            # Un texte manquant remplacé par "" passerait pour une suppression
            # totale et ferait baisser TRIR sans raison.
            raise ValueError(
                f"texte anonymisé absent pour {len(missing)} document(s), "
                f"ex. {missing[0]!r}"
            )
        return {doc_id: str(anonymized[doc_id]) for doc_id in ids}
    if len(anonymized) != len(records):
        raise ValueError("anonymized_texts doit avoir la même longueur que records")
    return dict(zip(ids, (str(text) for text in anonymized), strict=True))


def evaluate_trir(
    records: Sequence[RecordLike],
    anonymized_texts: Mapping[str, str] | Sequence[str] | None = None,
    *,
    folds: int = DEFAULT_FOLDS,
) -> TRIRResult:
    """TRIR par validation croisée groupée : l'attaquant ne voit jamais sa cible.

    ``records`` portent le texte **original** ; ``anonymized_texts`` le texte
    publié (``None`` = texte non anonymisé, contrôle de sanité S1). Lève
    :class:`TRIRUnavailable` si aucun document n'a de connaissance auxiliaire.
    """
    if folds < 2:
        raise ValueError("TRIR exige au moins 2 blocs : sinon l'attaquant verrait ses cibles")
    if not records:
        raise TRIRUnavailable("aucun document candidat")
    published = _anonymized_texts(records, anonymized_texts)
    ids = [_record_id(record, index) for index, record in enumerate(records)]
    subject_sizes = Counter(_subject_id(record) for record in records)
    if all(size < 2 for size in subject_sizes.values()):
        raise TRIRUnavailable(
            "aucun sujet n'a plus d'un document : sans connaissance auxiliaire "
            "disjointe de la cible, TRIA n'est pas définie (identité "
            "inter-documents absente ou corpus mono-document par sujet)"
        )
    if len(subject_sizes) < 2:
        # Un seul candidat : l'attaquant « ré-identifie » à coup sûr, TRIR = 1
        # = hasard. Publier ce 1.0 ferait croire à un risque maximal.
        raise TRIRUnavailable(
            "un seul sujet candidat : ré-identification triviale (hasard = 1), "
            "TRIR non informatif — élargir l'échantillon"
        )
    effective_folds = folds
    assignment = assign_folds(records, effective_folds)

    outcomes: list[TargetOutcome] = []
    excluded = 0
    for fold in range(effective_folds):
        training = [
            (doc_id, record) for doc_id, record in zip(ids, records, strict=True)
            if assignment[doc_id] != fold
        ]
        targets = [
            (doc_id, record) for doc_id, record in zip(ids, records, strict=True)
            if assignment[doc_id] == fold
        ]
        if not targets or not training:
            continue
        leaked = {doc_id for doc_id, _ in training} & {doc_id for doc_id, _ in targets}
        if leaked:  # garde structurelle : ne doit jamais arriver
            raise AssertionError(f"fuite TRIR : cibles vues en apprentissage {sorted(leaked)[:3]}")
        attacker = TfidfReidentifier().fit(record for _, record in training)
        counts = attacker.subject_document_counts
        for doc_id, record in targets:
            truth = _subject_id(record)
            if truth not in counts:
                excluded += 1
                continue
            scores = attacker.scores(published[doc_id])
            outcomes.append(
                TargetOutcome(
                    doc_id=doc_id,
                    subject_id=truth,
                    fold=fold,
                    top1=expected_hit(scores, truth, 1),
                    top5=expected_hit(scores, truth, 5),
                    chance=1.0 / len(counts),
                    majority=_majority_credit(counts, truth),
                )
            )
    if not outcomes:
        raise TRIRUnavailable("aucune cible n'a de connaissance auxiliaire dans son bloc")
    total = len(outcomes)
    correct = sum(outcome.top1 for outcome in outcomes)
    return TRIRResult(
        accuracy=correct / total,
        top5=sum(outcome.top5 for outcome in outcomes) / total,
        candidate_count=len(subject_sizes),
        candidate_subjects=tuple(sorted(subject_sizes)),
        correct=correct,
        total=total,
        chance_level=sum(outcome.chance for outcome in outcomes) / total,
        majority_level=sum(outcome.majority for outcome in outcomes) / total,
        folds=effective_folds,
        excluded_no_background=excluded,
        outcomes=tuple(sorted(outcomes, key=lambda o: o.doc_id)),
    )


def trir(
    records: Sequence[RecordLike],
    anonymized_texts: Mapping[str, str] | Sequence[str] | None = None,
    *,
    folds: int = DEFAULT_FOLDS,
) -> TRIRResult:
    """Alias court de :func:`evaluate_trir`."""
    return evaluate_trir(records, anonymized_texts, folds=folds)


def trir_inputs_from_run(
    scored: Sequence[Mapping[str, Any]],
    gold_by_doc: Mapping[str, Sequence[Any]],
    documents_by_doc: Mapping[str, Any],
) -> tuple[list[TRIARecord], dict[str, str], dict[str, Any]]:
    """Cibles TRIR et identité inter-documents retenue, sans repli silencieux.

    TRIA rattache un document à **une** personne connue par d'autres textes.
    Il faut donc une identité qui traverse les documents :

    * ``author_id`` si tous les documents le portent (forums, tickets) ;
    * sinon le sujet **unique** du document (``Document.subject_ids`` ou
      ``subject_id`` des annotations gold). Un document à plusieurs sujets n'a
      pas de cible TRIR unique : il est exclu et compté, jamais rattaché
      arbitrairement au premier sujet rencontré.

    Le repli v1 sur ``doc_id`` (chaque document = son propre sujet) est
    supprimé : il rendait TRIR(passthrough) = 1 par construction.
    """
    def _doc(record: Mapping[str, Any]) -> Any:
        return documents_by_doc.get(str(record.get("doc_id")))

    if scored and all(_field(_doc(r), "author_id", None) for r in scored):
        identity = "author_id"
        subjects = {
            str(r.get("doc_id")): str(_field(_doc(r), "author_id", None))
            for r in scored
        }
        excluded_multi = excluded_none = 0
    else:
        identity = "subject_id"
        subjects = {}
        excluded_multi = excluded_none = 0
        for record in scored:
            doc_id = str(record.get("doc_id"))
            found = {str(x) for x in (_field(_doc(record), "subject_ids", ()) or ())}
            found |= {
                str(value)
                for annotation in gold_by_doc.get(doc_id, ())
                if (value := _field(annotation, "subject_id", None))
            }
            if len(found) == 1:
                subjects[doc_id] = next(iter(found))
            elif found:
                excluded_multi += 1
            else:
                excluded_none += 1
        if not subjects:
            raise TRIRUnavailable(
                "aucune identité inter-documents : ni `author_id` sur tous les "
                "documents, ni sujet unique par document"
            )
    records = [
        TRIARecord(
            doc_id=doc_id,
            subject_id=subjects[doc_id],
            text=str(_field(documents_by_doc.get(doc_id), "text", "")),
        )
        for doc_id in sorted(subjects)
    ]
    anonymized = {
        str(r.get("doc_id")): str(r["anonymized_text"])
        for r in scored
        if str(r.get("doc_id")) in subjects
    }
    details = {
        "identity": identity,
        "excluded_multi_subject": excluded_multi,
        "excluded_no_subject": excluded_none,
    }
    return records, anonymized, details


TRIAClassifier = TfidfReidentifier

__all__ = [
    "DEFAULT_FOLDS",
    "TRIAClassifier",
    "TRIARecord",
    "TRIRResult",
    "TRIRUnavailable",
    "TargetOutcome",
    "TfidfReidentifier",
    "assign_folds",
    "evaluate_trir",
    "expected_hit",
    "trir",
    "trir_inputs_from_run",
]
