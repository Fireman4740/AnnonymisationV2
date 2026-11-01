"""Diagnostic de couverture des groupes annotés, distinct du scorer officiel."""
from __future__ import annotations

from collections import defaultdict

from anonymisation.metrics.entities import field_value
from anonymisation.metrics.masking import decisions_of, document_coverage
from anonymisation.metrics.uncertainty import bootstrap_interval


def group_mask_rate(records, gold_by_doc, documents_by_doc):
    """Part des groupes HIDE dont au moins un indice est intégralement masqué.

    Ce proxy ne mesure ni P-GF1, ni l'inférence résiduelle : il s'appuie sur
    les seules décisions d'édition appliquées, une fois les prédictions figées.
    """
    per_doc = []
    for record in records:
        doc_id = str(record['doc_id'])
        groups = defaultdict(list)
        for span in gold_by_doc.get(doc_id, ()):
            meta = field_value(span, 'meta', {}) or {}
            if meta.get('policy') != 'HIDE' or not meta.get('group_id'):
                raise ValueError('quasileak : annotation de groupe HIDE invalide')
            groups[meta['group_id']].append(span)
        text = str(field_value(documents_by_doc[doc_id], 'text', ''))
        broken = 0
        for spans in groups.values():
            sizes = {field_value(span, 'meta', {}).get('group_size') for span in spans}
            if sizes != {len(spans)} or not 2 <= len(spans) <= 4:
                raise ValueError('quasileak : groupe de gold incomplet')
            broken += any(document_coverage([span], decisions_of(record), text).covered_mentions == 1
                          for span in spans)
        per_doc.append((broken, len(groups)))
    def ratio(sample):
        denominator = sum(n for _, n in sample)
        return sum(n for n, _ in sample) / denominator if denominator else None
    value = ratio(per_doc)
    return {'name': 'quasileak_group_mask_rate', 'value': value,
            'protocol': 'quasileak-mask-proxy-v1', 'protocol_version': '1',
            'status': 'diagnostic' if value is not None else 'unavailable', 'direction': 'maximize', 'unit': 'ratio',
            'details': {'groups_total': sum(n for _, n in per_doc), 'groups_with_full_cue_masked': sum(n for n, _ in per_doc),
                'documents': len(per_doc), 'definition_id': 'hide-group-any-cue-fully-masked-v1',
                'denominator': 'groupes HIDE annotés des documents scorés',
                'reason': None if value is not None else 'aucun groupe HIDE annoté',
                'limitation': 'proxy de masquage, pas P-GF1 ni mesure de confidentialité résiduelle'},
            'interval': None if value is None else bootstrap_interval(per_doc, ratio, unit='document')}
