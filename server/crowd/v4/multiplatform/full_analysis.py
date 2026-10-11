"""Partition complete saved transcripts without weakening the single-call contract."""
import copy

from analysis_contract import build_snapshot, _hash, _paragraphs

MAX_SEGMENTS = 8000
MAX_CHARACTERS = 240000
MAX_BATCHES = 16
PROMPT_VERSION = 'content-comments-full-partitioned-v1'


def build_analysis_snapshot(imported, platform, content_id, entity_ref=None, derived_inputs=None):
    if derived_inputs is not None and not isinstance(derived_inputs, list):
        raise ValueError('invalid_analysis_derived_inputs')
    items = derived_inputs or []
    if not items:
        return build_snapshot(imported, platform, content_id, entity_ref=entity_ref)
    base = build_snapshot(imported, platform, content_id, entity_ref=entity_ref)
    if not isinstance(items, list) or len(items) > 5:
        raise ValueError('invalid_analysis_derived_inputs')
    if any(not isinstance(item, dict) or not isinstance(item.get('segments'), list)
           or any(not isinstance(row, dict) or not isinstance(row.get('text'), str) for row in item['segments'])
           for item in items):
        raise ValueError('invalid_analysis_derived_inputs')
    count = sum(len(item.get('segments', [])) for item in items)
    characters = sum(len(row.get('text', '')) for item in items for row in item.get('segments', []))
    if count > MAX_SEGMENTS or characters > MAX_CHARACTERS:
        raise ValueError('analysis_full_input_limit')
    try:
        return build_snapshot(imported, platform, content_id, entity_ref=entity_ref, derived_inputs=items)
    except ValueError as error:
        if str(error) not in ('invalid_analysis_derived_inputs', 'analysis_text_limit_exceeded'):
            raise
    # Validate every bounded piece through the unchanged original validator.
    text_only = {**imported, 'records': [({} if isinstance(row, dict) and row.get('kind') == 'comment' else row)
                                         for row in imported['records']]}
    batches = [{'snapshot': base, 'offsets': {}}]
    validated = []
    for item in items:
        if not isinstance(item, dict) or not isinstance(item.get('segments'), list) or not item['segments']:
            raise ValueError('invalid_analysis_derived_inputs')
        offset = 0
        while offset < len(item['segments']):
            rows = []; size = 0
            for row in item['segments'][offset:offset + 1000]:
                if not isinstance(row, dict) or not isinstance(row.get('text'), str):
                    raise ValueError('invalid_analysis_derived_inputs')
                if size + len(row['text']) > 24000:
                    break
                rows.append(row); size += len(row['text'])
            if not rows:
                raise ValueError('invalid_analysis_derived_inputs')
            piece = {**item, 'segments': rows}
            checked = build_snapshot(text_only, platform, content_id, entity_ref=entity_ref, derived_inputs=[piece])
            batches.append({'snapshot': checked, 'offsets': {item['job_id']: offset}})
            offset += len(rows)
            if len(batches) > MAX_BATCHES:
                raise ValueError('analysis_full_batch_limit')
        validated.append(copy.deepcopy(item))
    if len({item['job_id'] for item in validated}) != len(validated):
        raise ValueError('invalid_analysis_derived_inputs')
    full = {**base, 'derived_inputs': validated, 'analysis_batches': batches}
    full['paragraphs'] = _paragraphs(full)
    full.pop('snapshot_hash')
    full['snapshot_hash'] = _hash(full)
    return full


def combine_results(snapshot, results):
    batches = snapshot['analysis_batches']
    if len(results) != len(batches):
        raise ValueError('analysis_full_coverage_incomplete')
    global_rows = {row.get('source_ref', ''): row for row in snapshot['paragraphs'] if row.get('source_ref')}
    combined = copy.deepcopy(results[0])
    analysis = combined['content_analysis']
    summaries = [analysis['summary']]
    covered = []
    for number, (batch, result) in enumerate(zip(batches[1:], results[1:]), 1):
        local = {row['paragraph']: row for row in batch['snapshot']['paragraphs']}
        def global_reference(source):
            prefix, job_id, index = source.split(':')
            return ':'.join((prefix, job_id, str(int(index) + batch['offsets'][job_id])))
        for paragraph in local.values():
            if paragraph.get('source_ref', '').startswith('derived:'):
                covered.append(global_reference(paragraph['source_ref']))
        summaries.append('转写分批 ' + str(number) + '：' + result['content_analysis']['summary'])
        for key in ('segments', 'claims', 'reusable_methods'):
            for row in result['content_analysis'][key]:
                projected = dict(row)
                source = local[row['paragraph']].get('source_ref', '')
                if source.startswith('derived:'):
                    source = global_reference(source)
                    projected.update(paragraph=global_rows[source]['paragraph'], source_ref=source)
                analysis[key].append(projected)
        analysis['limitations'].extend(result['content_analysis']['limitations'])
    if len(covered) != len(set(covered)) or set(covered) != set(global_rows):
        raise ValueError('analysis_full_coverage_incomplete')
    analysis['summary'] = '\n\n'.join(summaries)
    analysis['limitations'] = list(dict.fromkeys(analysis['limitations'] + [
        '全文分批分析全部已保存转写段；转写未经听音校对，不保证原音频每句话都被识别。']))
    combined['full_analysis_coverage'] = {'state': 'all_selected_segments_analyzed',
        'batches_completed': len(results), 'batches_total': len(batches),
        'selected_segments': len(covered), 'selected_characters': sum(len(row['text']) for row in global_rows.values()),
        'source_refs': covered, 'semantic_review': 'not_reviewed', 'automatic_retry': False}
    return combined
