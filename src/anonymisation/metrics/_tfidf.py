"""Implémentation vectorielle légère TF-IDF et classifieur par centroïdes sans scikit-learn.

Tokenizer regex stable, IDF lissé log((1+n)/(1+df)) + 1, vecteurs normalisés L2,
centroïdes de classes normalisés, prédiction par cosinus avec départage par libellé.
"""

from __future__ import annotations

import math
import re
from collections import Counter
from collections.abc import Iterable, Sequence

_WORD_RE = re.compile(r"\b\w+\b", re.UNICODE)


def tokenize(text: str) -> list[str]:
    """Tokenisation stable en minuscules sans ponctuation."""
    return [m.group(0).lower() for m in _WORD_RE.finditer(text)]


class TfidfVectorizer:
    """Vectoriseur TF-IDF déterministe avec IDF lissé et normalisation L2."""

    def __init__(self, min_df: int = 1, max_features: int | None = 5000) -> None:
        self.min_df = min_df
        self.max_features = max_features
        self.vocabulary: dict[str, int] = {}
        self.idf: list[float] = []

    def fit(self, documents: Sequence[str]) -> TfidfVectorizer:
        n_docs = len(documents)
        if n_docs == 0:
            return self

        doc_freq: Counter[str] = Counter()
        for doc in documents:
            tokens = set(tokenize(doc))
            for tok in tokens:
                doc_freq[tok] += 1

        # Filtrer par min_df
        candidates = [(tok, count) for tok, count in doc_freq.items() if count >= self.min_df]
        # Trier par fréquence décroissante puis alphabétique
        candidates.sort(key=lambda x: (-x[1], x[0]))

        if self.max_features is not None:
            candidates = candidates[: self.max_features]

        # Figer le vocabulaire trié alphabétiquement pour déterminisme
        vocab_words = sorted([tok for tok, _ in candidates])
        self.vocabulary = {word: idx for idx, word in enumerate(vocab_words)}

        # IDF lissé : log((1 + n) / (1 + df)) + 1
        self.idf = [0.0] * len(self.vocabulary)
        for word, idx in self.vocabulary.items():
            df = doc_freq[word]
            self.idf[idx] = math.log((1.0 + n_docs) / (1.0 + df)) + 1.0

        return self

    def transform_one(self, doc: str) -> dict[int, float]:
        """Retourne un vecteur creux sous forme {feature_idx: value} normalisé L2."""
        if not self.vocabulary:
            return {}

        counts = Counter(tokenize(doc))
        sparse: dict[int, float] = {}
        norm_sq = 0.0

        for word, cnt in counts.items():
            idx = self.vocabulary.get(word)
            if idx is not None:
                val = float(cnt) * self.idf[idx]
                sparse[idx] = val
                norm_sq += val * val

        if norm_sq > 0.0:
            norm = math.sqrt(norm_sq)
            for idx in sparse:
                sparse[idx] /= norm

        return sparse


class CentroidClassifier:
    """Classifieur de centroïdes normalisés avec prédiction par similarité cosinus."""

    def __init__(self) -> None:
        self.classes: list[str] = []
        self.centroids: list[dict[int, float]] = []

    def fit(self, vectors: Sequence[dict[int, float]], labels: Sequence[str]) -> CentroidClassifier:
        if len(vectors) != len(labels):
            raise ValueError("Nombre de vecteurs différent du nombre de labels.")

        by_class: dict[str, list[dict[int, float]]] = {}
        for vec, label in zip(vectors, labels, strict=True):
            by_class.setdefault(label, []).append(vec)

        self.classes = sorted(by_class.keys())
        self.centroids = []

        for c in self.classes:
            vecs = by_class[c]
            # Somme
            sum_vec: dict[int, float] = {}
            for v in vecs:
                for idx, val in v.items():
                    sum_vec[idx] = sum_vec.get(idx, 0.0) + val

            # Normaliser L2 le centroïde
            norm_sq = sum(val * val for val in sum_vec.values())
            if norm_sq > 0.0:
                norm = math.sqrt(norm_sq)
                centroid = {idx: val / norm for idx, val in sum_vec.items()}
            else:
                centroid = {}
            self.centroids.append(centroid)

        return self

    def predict_one(self, vector: dict[int, float]) -> str:
        """Prédit la classe dont le centroïde maximise le produit scalaire (cosinus)."""
        if not self.classes:
            return "UNKNOWN"
        if not vector:
            return self.classes[0]

        best_score = -1.0
        best_class = self.classes[0]

        for cls_name, centroid in zip(self.classes, self.centroids, strict=True):
            score = 0.0
            # Produit scalaire
            # Itérer sur le plus petit des deux dictionnaires creux
            if len(vector) < len(centroid):
                for idx, val in vector.items():
                    c_val = centroid.get(idx)
                    if c_val is not None:
                        score += val * c_val
            else:
                for idx, c_val in centroid.items():
                    val_opt = vector.get(idx)
                    if val_opt is not None:
                        score += val_opt * c_val

            if score > best_score:
                best_score = score
                best_class = cls_name
            elif score == best_score and cls_name < best_class:
                best_class = cls_name

        return best_class

    def predict(self, vectors: Iterable[dict[int, float]]) -> list[str]:
        return [self.predict_one(vec) for vec in vectors]
