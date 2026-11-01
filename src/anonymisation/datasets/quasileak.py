"""Adaptateur QuasiLeak-Bench : splits officiels et seuls groupes HIDE au gold.

Les profils et les groupes gold ne sont jamais placés dans Document.meta. La
politique est une entrée fournie par l'utilisateur dans le protocole officiel.
"""
from __future__ import annotations

import json
from collections.abc import Iterator
from pathlib import Path
from typing import Any

from anonymisation.datasets._local import check_files, fingerprint, resolve_source_dir
from anonymisation.datasets.base import AcquisitionReport, DatasetAdapter
from anonymisation.datasets.ingest import IngestionError
from anonymisation.datasets.registry import register
from anonymisation.schema.models import Annotation, Document, Domain, Profile
from anonymisation.schema.taxonomy import ExpressionMode, Sensitivity

SPLITS = ('train', 'validation', 'test')
ATTRIBUTES = frozenset({'age', 'gender', 'nationality', 'education', 'occupation', 'income', 'relationship', 'health'})


@register
class QuasiLeakAdapter(DatasetAdapter):
    key = 'quasileak'
    aliases = ('quasileak-bench', 'quasileak_bench')
    requires_complete_annotations = True

    def __init__(self, manifest: Any, raw_dir: Path) -> None:
        super().__init__(manifest, raw_dir)
        self._cache = None

    def _files(self):
        return check_files(resolve_source_dir(self.manifest.source), self.manifest.source.files)

    def download(self, *, force: bool = False) -> AcquisitionReport:
        del force
        paths = self._files()
        digest = fingerprint(paths)
        if self.manifest.integrity.sha256 is not None and digest != self.manifest.integrity.sha256:
            raise IngestionError('quasileak : empreinte des sources différente de la release épinglée')
        self.raw_dir.mkdir(parents=True, exist_ok=True)
        return AcquisitionReport(dataset=self.key, path=self.raw_dir, sha256=digest,
                                 bytes_downloaded=0, from_cache=True, revision=self.manifest.source.revision)

    def _load(self):
        if self._cache is not None:
            return self._cache
        paths = {p.name: p for p in self._files()}
        if self.manifest.integrity.sha256 is not None and fingerprint(tuple(paths.values())) != self.manifest.integrity.sha256:
            raise IngestionError('quasileak : empreinte des sources différente de la release épinglée')
        try:
            manifest = json.loads(paths['split_manifest.json'].read_text(encoding='utf-8'))
            memberships = {s: set(manifest['membership'][s]) for s in SPLITS}
            if any(len(memberships[s]) != len(manifest['membership'][s]) for s in SPLITS):
                raise IngestionError('quasileak : identifiants de split dupliqués')
            if any(memberships[a] & memberships[b] for i, a in enumerate(SPLITS) for b in SPLITS[i + 1:]):
                raise IngestionError('quasileak : splits non disjoints')
            all_ids = set().union(*memberships.values())
            rows = {s: [] for s in SPLITS}
            seen, profiles = set(), {}
            with paths['quasileak_bench_data_full.jsonl'].open(encoding='utf-8') as stream:
                for line in stream:
                    if not line.strip():
                        continue
                    row = json.loads(line)
                    sid, text = row['sample_id'], row['document']
                    if not isinstance(sid, str) or not sid or sid in seen or sid not in all_ids or not isinstance(text, str) or not text:
                        raise IngestionError('quasileak : document invalide ou hors partition')
                    seen.add(sid)
                    split = next(s for s in SPLITS if sid in memberships[s])
                    profile = row['profile']
                    pid = profile['profile_id']
                    if not isinstance(pid, str) or not pid:
                        raise IngestionError('quasileak : profil manquant')
                    if pid in profiles and profiles[pid] != (split, profile):
                        raise IngestionError('quasileak : profil incohérent ou réparti entre splits')
                    profiles[pid] = (split, profile)
                    policy = row['policy']
                    parts = [set(policy[x]) for x in ('hide', 'keep', 'neutral')]
                    if (set().union(*parts) != ATTRIBUTES or sum(map(len, parts)) != len(ATTRIBUTES)
                            or any(len(policy[k]) != len(set(policy[k])) for k in ('hide', 'keep', 'neutral'))):
                        raise IngestionError('quasileak : politique non partitionnée')
                    gold = row['gold']
                    spans = {x['span_id']: x for x in gold['spans']}
                    if len(spans) != len(gold['spans']):
                        raise IngestionError('quasileak : indices dupliqués')
                    for item in spans.values():
                        a, b = item['start'], item['end']
                        if type(a) is not int or type(b) is not int or not 0 <= a < b <= len(text) or text[a:b] != item['text']:
                            raise IngestionError('quasileak : offsets source incohérents')
                    group_ids = set()
                    for group in gold['groups']:
                        gid, attr, cues = group['group_id'], group['attribute'], group['cue_ids']
                        if (gid in group_ids or attr not in ATTRIBUTES or not 2 <= len(cues) <= 4
                                or len(set(cues)) != len(cues) or any(c not in spans or spans[c]['group_id'] != gid for c in cues)):
                            raise IngestionError('quasileak : groupe ou indices incohérents')
                        group_ids.add(gid)
                    if any(s['group_id'] not in group_ids for s in spans.values()):
                        raise IngestionError('quasileak : indice sans groupe')
                    rows[split].append(row)
            if seen != all_ids:
                raise IngestionError('quasileak : documents de split absents')
        except (OSError, KeyError, TypeError, json.JSONDecodeError) as exc:
            raise IngestionError('quasileak : source invalide') from exc
        self._cache = rows
        return rows

    def _rows(self, split):
        if split not in SPLITS:
            raise IngestionError(f'quasileak : split inconnu {split!r}')
        return self._load()[split]

    def iter_documents(self, split: str) -> Iterator[Document]:
        for row in self._rows(split):
            context = row['context']
            yield Document(doc_id=row['sample_id'], dataset=self.key, split=split,
                domain=Domain.GENERIC, language='en', text=row['document'],
                author_id=row['profile']['profile_id'],
                meta={'context_id': context['context_id'], 'recipient': context['recipient'],
                      'purpose': context['purpose'], 'policy': row['policy']})

    def iter_annotations(self, split: str) -> Iterator[Annotation]:
        for row in self._rows(split):
            source_spans = {s['span_id']: s for s in row['gold']['spans']}
            for group in row['gold']['groups']:
                attr = group['attribute']
                if attr not in row['policy']['hide']:
                    continue
                mapping = self.manifest.label_map[attr]
                for cue in group['cue_ids']:
                    span = source_spans[cue]
                    yield Annotation(annotation_id=f"{row['sample_id']}:{group['group_id']}:{cue}",
                        doc_id=row['sample_id'], start=span['start'], end=span['end'], span_text=span['text'],
                        identifier_type=mapping.identifier_type, qi_categories=tuple(mapping.qi_categories),
                        granularity=mapping.granularity, stability=mapping.stability,
                        expression_mode=ExpressionMode.IMPLICIT,
                        sensitivity=Sensitivity.HEALTH if attr == 'health' else Sensitivity.NONE,
                        meta={'group_id': group['group_id'], 'attribute': attr, 'cue_id': cue,
                              'group_size': len(group['cue_ids']), 'distance': group['distance'], 'policy': 'HIDE'})

    def iter_profiles(self, split: str) -> Iterator[Profile]:
        seen = set()
        for row in self._rows(split):
            pid = row['profile']['profile_id']
            if pid not in seen:
                seen.add(pid)
                yield Profile(person_id=pid, dataset=self.key, population_id='quasileak-synthetic',
                              attributes={}, meta={'source_profile': row['profile']})
