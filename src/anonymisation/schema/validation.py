"""Validation des invariants du format pivot.

Implémente SPEC-04 §5 (étape 4 — VALIDATE) : les contrôles ``E-VAL-*`` sur les
invariants ``I-DOC-*``, ``I-ANN-*``, ``I-PRO-*``, ``I-CMB-*`` de SPEC-02.

Règle d'or du projet : aucune valeur par défaut silencieuse. Une violation
bloquante produit une :class:`ValidationIssue` de sévérité ``"error"`` qui
nomme le ou les identifiants fautifs ; elle n'est jamais absorbée.

``E-VAL-108`` (fuite de split) est le contrôle le plus important en pratique :
c'est celui qui attrape la fuite par profil latent, laquelle produirait des
résultats de détection excellents et faux (un même auteur observé à la fois en
train et en test).
"""

from __future__ import annotations

import json
from collections import Counter, defaultdict
from collections.abc import Sequence
from dataclasses import dataclass, field
from typing import Any

from anonymisation.schema.models import (
    Annotation,
    Combination,
    Document,
    Organization,
    Profile,
    RiskModel,
    Scope,
    TaskLabel,
)
from anonymisation.schema.taxonomy import DIRECT_CODES, IdentifierType

#: Ordre de la hiérarchie de scope pour la monotonie I-CMB-1 (SPEC-02 §8).
_SCOPE_ORDER: tuple[str, ...] = (Scope.AUTHOR.value, Scope.THREAD.value, Scope.DOCUMENT.value)


@dataclass(frozen=True)
class ValidationIssue:
    """Une violation ou un avertissement, localisé autant que possible."""

    code: str
    severity: str  # "error" | "warning"
    message: str
    doc_id: str | None = None
    ref_id: str | None = None  # annotation_id, person_id, combination_id...

    def __post_init__(self) -> None:
        if self.severity not in ("error", "warning"):
            raise ValueError(f"severity invalide : {self.severity!r}")


@dataclass(frozen=True)
class ValidationReport:
    """Rapport de validation d'un dataset — alimente ``.validation.json``."""

    dataset: str
    status: str  # "PASS" | "WARN" | "FAIL"
    counts: dict[str, Any]
    issues: tuple[ValidationIssue, ...] = field(default_factory=tuple)

    def __post_init__(self) -> None:
        if self.status not in ("PASS", "WARN", "FAIL"):
            raise ValueError(f"status invalide : {self.status!r}")

    def errors(self) -> tuple[ValidationIssue, ...]:
        return tuple(i for i in self.issues if i.severity == "error")

    def warnings(self) -> tuple[ValidationIssue, ...]:
        return tuple(i for i in self.issues if i.severity == "warning")

    def to_dict(self) -> dict[str, Any]:
        return {
            "dataset": self.dataset,
            "status": self.status,
            "counts": self.counts,
            "errors": [
                {
                    "code": i.code,
                    "message": i.message,
                    "doc_id": i.doc_id,
                    "ref_id": i.ref_id,
                }
                for i in self.errors()
            ],
            "warnings": [
                {
                    "code": i.code,
                    "message": i.message,
                    "doc_id": i.doc_id,
                    "ref_id": i.ref_id,
                }
                for i in self.warnings()
            ],
        }


def _canonical_normalized(normalized: dict[str, Any]) -> str:
    """Représentation JSON triée d'un ``normalized`` pour comparaison stable."""
    return json.dumps(normalized, sort_keys=True, ensure_ascii=False)


def _qi_set_key(combination: Combination) -> frozenset[tuple[str, str]]:
    """Clé de regroupement I-CMB-1 : ``qi_set`` comme frozenset canonique."""
    return frozenset(
        (qi.qi_category, _canonical_normalized(qi.normalized)) for qi in combination.qi_set
    )


def _duplicates(values: Sequence[str]) -> list[str]:
    counts = Counter(values)
    return sorted(v for v, n in counts.items() if n > 1)


def validate_dataset(
    dataset: str,
    documents: Sequence[Document],
    annotations: Sequence[Annotation],
    profiles: Sequence[Profile] = (),
    organizations: Sequence[Organization] = (),
    combinations: Sequence[Combination] = (),
    tasks: Sequence[TaskLabel] = (),
    *,
    expected_documents: int | None = None,
) -> ValidationReport:
    """Valide un dataset chargé en mémoire contre les invariants de SPEC-02.

    Implémente SPEC-04 §5. Ne fait aucune E/S : les tables sont déjà chargées
    (typiquement via :func:`anonymisation.schema.io.read_jsonl`).
    """
    issues: list[ValidationIssue] = []

    documents_by_id: dict[str, Document] = {}
    for doc in documents:
        documents_by_id[doc.doc_id] = doc  # dernier gagne ; E-VAL-111 signale le doublon

    profile_ids = {p.person_id for p in profiles}
    org_ids = {o.org_id for o in organizations}

    # ---------------------------------------------------------------- #
    # E-VAL-111 — doublons d'identifiants (bloquant)
    # ---------------------------------------------------------------- #
    for label, values in (
        ("doc_id", [d.doc_id for d in documents]),
        ("annotation_id", [a.annotation_id for a in annotations]),
        ("person_id", [p.person_id for p in profiles]),
        ("org_id", [o.org_id for o in organizations]),
        ("combination_id", [c.combination_id for c in combinations]),
    ):
        for dup in _duplicates(values):
            issues.append(
                ValidationIssue(
                    code="E-VAL-111",
                    severity="error",
                    message=f"Identifiant {label} dupliqué : {dup!r}",
                    ref_id=dup,
                )
            )

    # ---------------------------------------------------------------- #
    # E-VAL-104 — I-DOC-3 : author_id / org_id / doc_id orphelins (bloquant)
    # ---------------------------------------------------------------- #
    for doc in documents:
        if doc.author_id is not None and doc.author_id not in profile_ids:
            issues.append(
                ValidationIssue(
                    code="E-VAL-104",
                    severity="error",
                    message=f"author_id orphelin : {doc.author_id!r} absent de profiles.jsonl",
                    doc_id=doc.doc_id,
                    ref_id=doc.author_id,
                )
            )
        if doc.org_id is not None and doc.org_id not in org_ids:
            issues.append(
                ValidationIssue(
                    code="E-VAL-104",
                    severity="error",
                    message=f"org_id orphelin : {doc.org_id!r} absent de organizations.jsonl",
                    doc_id=doc.doc_id,
                    ref_id=doc.org_id,
                )
            )

    for ann in annotations:
        if ann.doc_id not in documents_by_id:
            issues.append(
                ValidationIssue(
                    code="E-VAL-104",
                    severity="error",
                    message=f"annotation.doc_id orphelin : {ann.doc_id!r} absent de documents.jsonl",
                    doc_id=ann.doc_id,
                    ref_id=ann.annotation_id,
                )
            )
    # E-VAL-104 — référence de sujet explicite (SPEC-02 v2.1).
    for ann in annotations:
        document = documents_by_id.get(ann.doc_id)
        if document is None or not document.subject_ids:
            continue
        if ann.subject_id is None:
            issues.append(
                ValidationIssue(
                    code="E-VAL-104",
                    severity="error",
                    message=(
                        "annotation.subject_id absent pour un document multi-sujets : "
                        f"{document.doc_id!r}"
                    ),
                    doc_id=ann.doc_id,
                    ref_id=ann.annotation_id,
                )
            )
        elif ann.subject_id not in document.subject_ids:
            issues.append(
                ValidationIssue(
                    code="E-VAL-104",
                    severity="error",
                    message=(
                        f"subject_id orphelin : {ann.subject_id!r} absent de "
                        f"documents[{document.doc_id!r}].subject_ids"
                    ),
                    doc_id=ann.doc_id,
                    ref_id=ann.annotation_id,
                )
            )

    # ---------------------------------------------------------------- #
    # E-VAL-101 — I-ANN-1 : offsets valides (bloquant)
    for ann in annotations:
        annotation_doc = documents_by_id.get(ann.doc_id)
        if annotation_doc is None:
            continue  # déjà signalé par E-VAL-104
        try:
            ann.check_against_text(annotation_doc.text)
        except ValueError as exc:
            issues.append(
                ValidationIssue(
                    code="E-VAL-101",
                    severity="error",
                    message=str(exc),
                    doc_id=ann.doc_id,
                    ref_id=ann.annotation_id,
                )
            )

    # ---------------------------------------------------------------- #
    # E-VAL-102 — I-ANN-2 : annotation sans offset hors IMPLICIT (bloquant)
    #
    # Déjà bloqué à la construction du modèle Annotation ; revérifié ici pour
    # des données chargées sans passer par le constructeur validant (ex.
    # ``model_construct``, désérialisation partielle).
    # ---------------------------------------------------------------- #
    for ann in annotations:
        has_offsets = ann.start is not None and ann.end is not None
        if not has_offsets and ann.expression_mode.value != "IMPLICIT":
            issues.append(
                ValidationIssue(
                    code="E-VAL-102",
                    severity="error",
                    message=(
                        "I-ANN-2 violé : annotation sans offsets alors que "
                        f"expression_mode={ann.expression_mode.value}"
                    ),
                    doc_id=ann.doc_id,
                    ref_id=ann.annotation_id,
                )
            )

    # ---------------------------------------------------------------- #
    # E-VAL-103 — I-ANN-3 : exclusivité DIRECT (bloquant)
    # ---------------------------------------------------------------- #
    for ann in annotations:
        if ann.identifier_type is IdentifierType.DIRECT:
            offenders = [c for c in ann.qi_categories if c not in DIRECT_CODES]
            if offenders:
                issues.append(
                    ValidationIssue(
                        code="E-VAL-103",
                        severity="error",
                        message=(
                            "I-ANN-3 violé : identifier_type=DIRECT avec des codes "
                            f"non-DIR_* : {offenders}"
                        ),
                        doc_id=ann.doc_id,
                        ref_id=ann.annotation_id,
                    )
                )

    # ---------------------------------------------------------------- #
    # E-VAL-105 — I-CMB-1 : monotonie du scope (bloquant)
    # ---------------------------------------------------------------- #
    groups: dict[tuple[str, frozenset[tuple[str, str]]], dict[str, list[tuple[int, str]]]] = (
        defaultdict(lambda: defaultdict(list))
    )
    for comb in combinations:
        if comb.k_true is None:
            continue
        key = (comb.target_id, _qi_set_key(comb))
        groups[key][comb.scope.value].append((comb.k_true, comb.combination_id))

    for (target_id, _qi_key), by_scope in groups.items():
        for i, scope_low in enumerate(_SCOPE_ORDER):
            for scope_high in _SCOPE_ORDER[i + 1 :]:
                for k_low, id_low in by_scope.get(scope_low, ()):
                    for k_high, id_high in by_scope.get(scope_high, ()):
                        if k_low > k_high:
                            issues.append(
                                ValidationIssue(
                                    code="E-VAL-105",
                                    severity="error",
                                    message=(
                                        "I-CMB-1 violé : monotonie du scope pour "
                                        f"target_id={target_id!r} : k_{scope_low}={k_low} > "
                                        f"k_{scope_high}={k_high} "
                                        f"({id_low!r} vs {id_high!r})"
                                    ),
                                    ref_id=target_id,
                                )
                            )

    # ---------------------------------------------------------------- #
    # E-VAL-106 — I-CMB-2 : cohérence risque / k en modèle prosecutor
    # (bloquant). Déjà bloqué au constructeur ; revérifié pour la même raison
    # que E-VAL-102.
    # ---------------------------------------------------------------- #
    for comb in combinations:
        if (
            comb.risk_model is RiskModel.PROSECUTOR
            and comb.k_true is not None
            and comb.risk_true is not None
        ):
            expected = 1.0 / comb.k_true
            if abs(comb.risk_true - expected) > 1e-6:
                issues.append(
                    ValidationIssue(
                        code="E-VAL-106",
                        severity="error",
                        message=(
                            f"I-CMB-2 violé : risk_true={comb.risk_true} != "
                            f"1/k_true={expected}"
                        ),
                        ref_id=comb.combination_id,
                    )
                )

    # ---------------------------------------------------------------- #
    # E-VAL-107 — I-PRO-2 : attribut de profil sans normalized (avertissement)
    # ---------------------------------------------------------------- #
    pro107_count = 0
    for profile in profiles:
        for code, attr in profile.attributes.items():
            if attr.normalized is None:
                pro107_count += 1
                issues.append(
                    ValidationIssue(
                        code="E-VAL-107",
                        severity="warning",
                        message=(
                            f"I-PRO-2 : attribut {code!r} sans normalized — ignoré par le "
                            "moteur de risque"
                        ),
                        ref_id=profile.person_id,
                    )
                )

    # ---------------------------------------------------------------- #
    # E-VAL-108 — fuite de split (bloquant, LE contrôle le plus important)
    # ---------------------------------------------------------------- #
    splits_by_person: dict[str, set[str]] = defaultdict(set)
    splits_by_org: dict[str, set[str]] = defaultdict(set)
    for doc in documents:
        if doc.author_id is not None:
            splits_by_person[doc.author_id].add(doc.split)
        if doc.org_id is not None:
            splits_by_org[doc.org_id].add(doc.split)

    for person_id, splits in splits_by_person.items():
        if len(splits) > 1:
            issues.append(
                ValidationIssue(
                    code="E-VAL-108",
                    severity="error",
                    message=(
                        f"Fuite de split : person_id={person_id!r} apparaît dans les "
                        f"splits {sorted(splits)}"
                    ),
                    ref_id=person_id,
                )
            )
    for org_id, splits in splits_by_org.items():
        if len(splits) > 1:
            issues.append(
                ValidationIssue(
                    code="E-VAL-108",
                    severity="error",
                    message=(
                        f"Fuite de split : org_id={org_id!r} apparaît dans les "
                        f"splits {sorted(splits)}"
                    ),
                    ref_id=org_id,
                )
            )

    # ---------------------------------------------------------------- #
    # E-VAL-109 — volumétrie observée != expected_documents (avertissement)
    # ---------------------------------------------------------------- #
    if expected_documents is not None and len(documents) != expected_documents:
        issues.append(
            ValidationIssue(
                code="E-VAL-109",
                severity="warning",
                message=(
                    f"Volumétrie observée ({len(documents)}) != expected_documents "
                    f"({expected_documents})"
                ),
            )
        )

    # ---------------------------------------------------------------- #
    # E-VAL-110 — taux d'OTHER_QI > 1 % des annotations (avertissement)
    # ---------------------------------------------------------------- #
    other_qi_count = sum(1 for a in annotations if "OTHER_QI" in a.qi_categories)
    if annotations and other_qi_count / len(annotations) > 0.01:
        issues.append(
            ValidationIssue(
                code="E-VAL-110",
                severity="warning",
                message=(
                    f"Taux d'OTHER_QI={other_qi_count}/{len(annotations)} "
                    f"({other_qi_count / len(annotations):.2%}) > 1 % — taxonomie incomplète"
                ),
            )
        )

    # ---------------------------------------------------------------- #
    # Comptes — dénominateurs des métriques déclinées de SPEC-07
    # ---------------------------------------------------------------- #
    by_language: Counter[str] = Counter(d.language for d in documents)
    by_domain: Counter[str] = Counter(d.domain.value for d in documents)
    by_expression_mode: Counter[str] = Counter(a.expression_mode.value for a in annotations)
    by_identifier_type: Counter[str] = Counter(a.identifier_type.value for a in annotations)
    by_qi_category: Counter[str] = Counter()
    for a in annotations:
        by_qi_category.update(a.qi_categories)

    counts: dict[str, Any] = {
        "documents": len(documents),
        "annotations": len(annotations),
        "profiles": len(profiles),
        "organizations": len(organizations),
        "combinations": len(combinations),
        "tasks": len(tasks),
        "by_language": dict(sorted(by_language.items())),
        "by_domain": dict(sorted(by_domain.items())),
        "by_expression_mode": dict(sorted(by_expression_mode.items())),
        "by_identifier_type": dict(sorted(by_identifier_type.items())),
        "by_qi_category": dict(sorted(by_qi_category.items())),
        "warnings": {"E-VAL-107": pro107_count, "E-VAL-110": other_qi_count},
    }

    if any(i.severity == "error" for i in issues):
        status = "FAIL"
    elif any(i.severity == "warning" for i in issues):
        status = "WARN"
    else:
        status = "PASS"

    return ValidationReport(
        dataset=dataset,
        status=status,
        counts=counts,
        issues=tuple(issues),
    )
