"""Partition complete saved transcripts without weakening the single-call contract."""
import copy

from analysis_contract import build_snapshot, _hash, _paragraphs

MAX_SEGMENTS = 8000
MAX_CHARACTERS = 240000
MAX_BATCHES = 16
PROMPT_VERSION = 'content-comments-full-partitioned-v1'
ASSEMBLY_VERSION = 'full-batch-context-v2'


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
    def context(index, batch):
        rows = [row for row in batch['snapshot']['paragraphs'] if row.get('source_ref', '').startswith('derived:')]
        if not rows:
            return '正文与评论批 0（已保存评论 %d 条；不含转写候选）' % len(batch['snapshot']['comments'])
        times = [row for row in rows if row.get('start') is not None]
        window = ('；候选时间 %s–%s 秒' % (min(row['start'] for row in times), max(row['end'] for row in times))) if times else ''
        return ('转写批 %d（%d 个所选候选%s；本批不含评论，不表示全文没有评论；'
                '自由文字引用使用本批局部编号）') % (index, len(rows), window)
    summaries = [context(0, batches[0]) + '：\n' + analysis['summary']]
    analysis['limitations'] = [context(0, batches[0]) + '：' + line for line in analysis['limitations']]
    for key in ('segments', 'claims', 'reusable_methods'):
        for row in analysis[key]:
            row['analysis_context'] = {'batch_index': 0, 'scope': 'base_content_and_comments',
                                      'local_paragraph': row['paragraph'], 'local_source_ref': row['source_ref'],
                                      'global_source_ref': row['source_ref']}
    covered = []
    for number, (batch, result) in enumerate(zip(batches[1:], results[1:]), 1):
        local = {row['paragraph']: row for row in batch['snapshot']['paragraphs']}
        def global_reference(source):
            prefix, job_id, index = source.split(':')
            return ':'.join((prefix, job_id, str(int(index) + batch['offsets'][job_id])))
        for paragraph in local.values():
            if paragraph.get('source_ref', '').startswith('derived:'):
                reference = global_reference(paragraph['source_ref'])
                expected = global_rows.get(reference)
                if expected is None or {k:v for k,v in paragraph.items() if k not in ('paragraph','source_ref')} != {k:v for k,v in expected.items() if k not in ('paragraph','source_ref')}:
                    raise ValueError('analysis_full_partition_changed')
                covered.append(reference)
        summaries.append(context(number, batch) + '：\n' + result['content_analysis']['summary'])
        for key in ('segments', 'claims', 'reusable_methods'):
            for row in result['content_analysis'][key]:
                projected = dict(row)
                source = local[row['paragraph']].get('source_ref', '')
                # Later prompts contain the base text for context; only batch 0
                # supplies base judgements in the assembled report.
                if not source.startswith('derived:'):
                    continue
                local_source = source
                source = global_reference(source)
                projected.update(paragraph=global_rows[source]['paragraph'], source_ref=source,
                    analysis_context={'batch_index': number, 'scope': 'selected_derived_window',
                                      'local_paragraph': row['paragraph'], 'local_source_ref': local_source,
                                      'global_source_ref': source, 'free_text_reference_basis': 'batch_local'})
                analysis[key].append(projected)
        analysis['limitations'].extend(context(number, batch) + '：' + line for line in result['content_analysis']['limitations'])
    if len(covered) != len(set(covered)) or set(covered) != set(global_rows):
        raise ValueError('analysis_full_coverage_incomplete')
    analysis['summary'] = '\n\n'.join(summaries)
    analysis['limitations'] = list(dict.fromkeys(analysis['limitations'] + [
        '全文分批分析全部已保存转写段；转写未经听音校对，不保证原音频每句话都被识别。']))
    analysis['assembly'] = {'version': ASSEMBLY_VERSION, 'base_judgements_batch': 0,
                            'free_text_reference_basis': 'batch_local', 'structured_reference_basis': 'global'}
    combined['full_analysis_coverage'] = {'state': 'all_selected_segments_analyzed',
        'batches_completed': len(results), 'batches_total': len(batches),
        'selected_segments': len(covered), 'selected_characters': sum(len(row['text']) for row in global_rows.values()),
        'source_refs': covered, 'semantic_review': 'not_reviewed', 'automatic_retry': False}
    return combined
