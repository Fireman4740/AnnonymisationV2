"""Adaptation d'I/O autour du scorer officiel QuasiLeak-Bench, non modifié."""
from __future__ import annotations

import hashlib
import json
import tempfile
from pathlib import Path

from anonymisation.metrics.vendor import quasileak_score as official
from anonymisation.schema.io import sha256_file

SCORER_SHA256 = '2d4dd8f48595634af450810accfe5d492d32f63f54788023a702ef999f00b707'
DATA_SHA256 = '9af4c3e4fc59f664d124448e81e514012b8608bfa3ee6ba0faba9c6b9b27a965'
SPLIT_SHA256 = '34bbb26ebde1096f8c71f457caa7e81b78080a6f11c3494df67a6ffda4e6fc4a'
SOURCE_COMMIT = '75987cdf029fac5fecce160bea218b458ed46dbb'


def score_official(dataset: Path, manifest: Path, predictions: Path, *, split: str,
                   selection: Path | None = None) -> dict:
    """Score des groupes réellement prédits ; une sélection doit être explicite.

    Les erreurs ou absences ne sont jamais converties en groupes vides. Les
    prédictions contiennent une ligne par document sélectionné, et l'évaluation
    s'effectue dans le scorer d'origine avec ses paramètres par défaut.
    """
    if split not in {'train', 'validation', 'test'}:
        raise ValueError('quasileak : split officiel train, validation ou test requis')
    if sha256_file(Path(official.__file__)) != SCORER_SHA256:
        raise ValueError('quasileak : scorer officiel modifié')
    if sha256_file(dataset) != DATA_SHA256 or sha256_file(manifest) != SPLIT_SHA256:
        raise ValueError('quasileak : dataset ou partitions hors release épinglée')
    prediction_lock = predictions.with_suffix(predictions.suffix + '.lock.json')
    if prediction_lock.exists():
        lock = json.loads(prediction_lock.read_text(encoding='utf-8'))
        if (lock.get('predictions_sha256') != sha256_file(predictions)
                or lock.get('dataset_sha256') != DATA_SHA256 or lock.get('split_manifest_sha256') != SPLIT_SHA256
                or lock.get('errors') != 0):
            raise ValueError('quasileak : prédictions locales modifiées ou en erreur')
        if selection is None or lock.get('selection_sha256') != sha256_file(selection):
            raise ValueError('quasileak : sélection de prédiction divergente')
    splits = json.loads(manifest.read_text(encoding='utf-8'))['membership']
    members = splits[split]
    if len(set(members)) != len(members):
        raise ValueError('quasileak : split dupliqué')
    if selection is None:
        selected = set(members)
    else:
        selected_list = json.loads(selection.read_text(encoding='utf-8'))
        if (not isinstance(selected_list, list) or not selected_list
                or not all(isinstance(x, str) and x for x in selected_list)
                or len(set(selected_list)) != len(selected_list) or set(selected_list) - set(members)):
            raise ValueError('quasileak : sélection vide, dupliquée ou hors split')
        selected = set(selected_list)
    rows = [row for row in official.read_jsonl(dataset) if row['sample_id'] in selected]
    if len(rows) != len(selected) or len({row['sample_id'] for row in rows}) != len(selected):
        raise ValueError('quasileak : documents sélectionnés absents ou dupliqués')
    # Avant appel au scorer : pas de ligne en erreur convertie en aucune fuite.
    for item in official.read_jsonl(predictions):
        if item.get('status') not in {None, 'ok'}:
            raise ValueError('quasileak : prédiction échouée ou partielle non évaluable')
    with tempfile.TemporaryDirectory(prefix='quasileak-gold-') as temp:
        path = Path(temp) / 'selected.jsonl'
        with path.open('w', encoding='utf-8') as stream:
            for row in rows:
                stream.write(json.dumps(row, ensure_ascii=False) + '\n')
        measures = official.score(str(predictions), str(path))
    return {'protocol': 'quasileak-official-v1.0.1', 'split': split,
            'status': 'sampled' if len(selected) != len(members) else 'diagnostic',
            'source_commit': SOURCE_COMMIT, 'scorer_sha256': SCORER_SHA256,
            'dataset_sha256': DATA_SHA256, 'split_manifest_sha256': SPLIT_SHA256,
            'predictions_sha256': sha256_file(predictions),
            'prediction_lock_sha256': sha256_file(prediction_lock) if prediction_lock.exists() else None,
            'prediction_provenance': 'locked-local' if prediction_lock.exists() else 'external-unverified',
            'selection_sha256': hashlib.sha256('\n'.join(sorted(selected)).encode()).hexdigest(),
            'parameters': {'gamma': official.GAMMA, 'theta': official.THETA,
                           'rho_sec': official.RHO_SEC, 'lambda_k': official.LAMBDA_K},
            'scores_0_100': measures,
            'limitation': 'détection de groupes sous politique ; pas une mesure directe du texte anonymisé'}
