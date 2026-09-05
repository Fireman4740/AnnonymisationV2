"""TRIA/TRIR sans LLM (SPEC-07 v2.0 §5, ticket G-3).

Cette première implémentation utilise un profil TF-IDF léger et une
classification par centroïde cosinus. Elle reste entièrement déterministe et
ne dépend ni d'un fournisseur distant ni de scikit-learn.
"""

from __future__ import annotations

import math
import re
from collections import Counter, defaultdict
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass
from typing import Any, TypeAlias

_TOKEN_RE = re.compile(r"(?u)\b\w+\b")
RecordLike: TypeAlias = Any


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
    if value is None:
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
    """Exemple minimal du candidat TRIA."""

    doc_id: str
    subject_id: str
    text: str


@dataclass(frozen=True)
class TRIRResult:
    """Résultat TRIR avec la taille de l'ensemble candidat déclarée."""

    accuracy: float | None
    candidate_count: int
    candidate_subjects: tuple[str, ...]
    correct: int
    total: int
    protocol: str = "tria-tfidf-centroid"
    protocol_version: str = "1"

    @property
    def trir(self) -> float | None:
        """Alias explicite pour les scorecards qui nomment la métrique TRIR."""
        return self.accuracy

    def to_dict(self) -> dict[str, Any]:
        return {
            "name": "trir",
            "value": self.accuracy,
            "accuracy": self.accuracy,
            "candidate_count": self.candidate_count,
            "candidate_subjects": list(self.candidate_subjects),
            "correct": self.correct,
            "total": self.total,
            "protocol": self.protocol,
            "protocol_version": self.protocol_version,
            "chance_level": 1.0 / self.candidate_count if self.candidate_count else None,
        }


class TfidfReidentifier:
    """Classifieur document -> sujet par centroïde TF-IDF."""

    def __init__(self) -> None:
        self._idf: dict[str, float] = {}
        self._centroids: dict[str, dict[str, float]] = {}
        self._subjects: tuple[str, ...] = ()

    @property
    def candidate_subjects(self) -> tuple[str, ...]:
        return self._subjects

    def fit(self, records: Iterable[RecordLike]) -> TfidfReidentifier:
        rows = list(records)
        if not rows:
            raise ValueError("TRIA requiert au moins un document candidat")
        subject_documents: dict[str, list[tuple[str, ...]]] = defaultdict(list)
        document_frequency: Counter[str] = Counter()
        for record in rows:
            subject = _subject_id(record)
            tokens = _tokens(_text(record))
            subject_documents[subject].append(tokens)
            document_frequency.update(set(tokens))
        self._subjects = tuple(sorted(subject_documents))
        document_count = len(rows)
        self._idf = {
            token: math.log((1.0 + document_count) / (1.0 + frequency)) + 1.0
            for token, frequency in document_frequency.items()
        }
        centroids: dict[str, dict[str, float]] = {}
        for subject in self._subjects:
            vectors = [self._vector(tokens) for tokens in subject_documents[subject]]
            centroids[subject] = {
                token: sum(vector.get(token, 0.0) for vector in vectors) / len(vectors)
                for token in sorted({token for vector in vectors for token in vector})
            }
        self._centroids = centroids
        return self

    def _vector(self, tokens: Sequence[str]) -> dict[str, float]:
        if not tokens:
            return {}
        counts = Counter(tokens)
        length = float(len(tokens))
        return {
            token: (count / length) * self._idf.get(token, 0.0)
            for token, count in counts.items()
            if token in self._idf
        }

    @staticmethod
    def _cosine(left: Mapping[str, float], right: Mapping[str, float]) -> float:
        if not left or not right:
            return 0.0
        dot = sum(value * right.get(token, 0.0) for token, value in left.items())
        norm_left = math.sqrt(sum(value * value for value in left.values()))
        norm_right = math.sqrt(sum(value * value for value in right.values()))
        return dot / (norm_left * norm_right) if norm_left and norm_right else 0.0

    def predict(self, text: str) -> str:
        if not self._subjects:
            raise ValueError("le classifieur TRIA doit être entraîné avant predict")
        vector = self._vector(_tokens(text))
        # max() conserve le premier sujet en cas d'égalité ; les sujets sont
        # triés, donc le comportement sur texte vide est déterministe.
        return max(
            self._subjects,
            key=lambda subject: (self._cosine(vector, self._centroids[subject]), subject),
        )


def _anonymized_texts(
    records: Sequence[RecordLike], anonymized: Mapping[str, str] | Sequence[str] | None
) -> tuple[str, ...]:
    if anonymized is None:
        return tuple(_text(record) for record in records)
    if isinstance(anonymized, Mapping):
        return tuple(anonymized.get(_record_id(record, index), "") for index, record in enumerate(records))
    if len(anonymized) != len(records):
        raise ValueError("anonymized_texts doit avoir la même longueur que records")
    return tuple(anonymized)


def evaluate_trir(
    records: Sequence[RecordLike],
    anonymized_texts: Mapping[str, str] | Sequence[str] | None = None,
) -> TRIRResult:
    """Entraîne TRIA sur les textes originaux et mesure TRIR sur les textes fournis."""
    if not records:
        return TRIRResult(None, 0, (), 0, 0)
    classifier = TfidfReidentifier().fit(records)
    texts = _anonymized_texts(records, anonymized_texts)
    correct = sum(
        classifier.predict(text) == _subject_id(record)
        for record, text in zip(records, texts, strict=True)
    )
    return TRIRResult(
        accuracy=correct / len(records),
        candidate_count=len(classifier.candidate_subjects),
        candidate_subjects=classifier.candidate_subjects,
        correct=correct,
        total=len(records),
    )


def trir(
    records: Sequence[RecordLike],
    anonymized_texts: Mapping[str, str] | Sequence[str] | None = None,
) -> TRIRResult:
    """Alias court de :func:`evaluate_trir`."""
    return evaluate_trir(records, anonymized_texts)


TRIAClassifier = TfidfReidentifier

__all__ = [
    "TRIAClassifier",
    "TRIARecord",
    "TRIRResult",
    "TfidfReidentifier",
    "evaluate_trir",
    "trir",
]
