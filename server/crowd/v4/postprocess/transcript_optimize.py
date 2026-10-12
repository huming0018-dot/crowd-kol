"""Bounded evidence-based revision proposals; no model, network, or global rewrites."""
import hashlib
import json
import math
import re
import unicodedata
from difflib import SequenceMatcher


def canonical(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(',', ':'), allow_nan=False)


def digest(value):
    return hashlib.sha256(canonical(value).encode()).hexdigest()


def normalized(text):
    return ''.join(char for char in unicodedata.normalize('NFKC', text).casefold()
                   if not char.isspace() and not unicodedata.category(char).startswith('P'))


def overlap_removal(rows, chunks, index, retained):
    """Only remove a whole fragment witnessed twice inside real extraction overlap."""
    if type(index) is not int or type(retained) is not int or index == retained:
        return None
    if not 0 <= index < len(rows) or not 0 <= retained < len(rows):
        return None
    short, longer = rows[index], rows[retained]
    a, b = short.get('chunk_index'), longer.get('chunk_index')
    windows = {chunk['index']: chunk for chunk in chunks}
    if type(a) is not int or type(b) is not int or a == b or a not in windows or b not in windows:
        return None
    if any(not {'start', 'end'} <= set(windows[index]) for index in (a, b)):
        return None
    left, right = max(windows[a]['start'], windows[b]['start']), min(windows[a]['end'], windows[b]['end'])
    if (left >= right or not left <= short['start'] <= short['end'] <= right
            or max(short['start'], longer['start']) >= min(short['end'], longer['end'])):
        return None
    text, other = normalized(short['text']), normalized(longer['text'])
    exact = len(text) >= 6 and text == other
    prefix = (4 <= len(text) < len(other) and other.startswith(text)
              and abs(short['start'] - longer['start']) <= .2
              and longer['end'] >= short['end'])
    if not exact and not prefix:
        return None
    return {'rule': 'exact_overlap' if exact else 'aligned_overlap_prefix',
            'removed_segment_index': index, 'retained_segment_index': retained,
            'overlap_start': left, 'overlap_end': right,
            'removed_text_sha256': hashlib.sha256(short['text'].encode()).hexdigest(),
            'retained_text_sha256': hashlib.sha256(longer['text'].encode()).hexdigest()}


def extract_terms(source_context, references):
    """Conservative lexical candidates, explicitly not named-entity ground truth."""
    terms = {}
    def add(term, basis, source_hash):
        if 2 <= len(term) <= 40 and len(terms) < 100:
            terms.setdefault(term, []).append({'basis': basis, 'source_sha256': source_hash})
    for field in ('title', 'body'):
        text = source_context.get(field, '')
        if not isinstance(text, str) or len(text) > 64000:
            raise ValueError('invalid_transcript_optimization_context')
        for match in re.finditer(r'《([^《》\n]{2,40})》', text):
            add(match[1], 'source_' + field + '_quoted_title', source_context.get('source_sha256'))
        for match in re.finditer(r'(?:作者|作家|名叫|名为|大学生)[：:\s]*([\u4e00-\u9fff]{2,6})(?=的|[，。；\s]|$)', text):
            add(match[1], 'source_' + field + '_named_context', source_context.get('source_sha256'))
        for match in re.finditer(r'》\s*([\u4e00-\u9fff]{2,6})(?=$|[，。；\s])', text):
            add(match[1], 'source_' + field + '_author_attribution_candidate', source_context.get('source_sha256'))
    for reference in references:
        text = reference['visible_hard_subtitle']
        name = None
        if re.fullmatch(r'[\u4e00-\u9fff]{2,6}', text):
            name = text
        else:
            match = re.search(r'(?:大学生|名叫|名为|正是)([\u4e00-\u9fff]{2,6})(?=自己|[，。]|$)', text)
            if match:
                name = match[1]
        if name:
            add(name, 'saved_hard_subtitle_named_candidate', reference['frame_sha256'])
    return [{'term': term, 'evidence': proofs, 'status': 'lexical_candidate_not_spoken_groundtruth'}
            for term, proofs in terms.items()]


def plan(evidence, chunks, source_context=None, references=None):
    if (not isinstance(evidence, dict) or not isinstance(chunks, list)
            or source_context is not None and not isinstance(source_context, dict)
            or references is not None and not isinstance(references, dict)):
        raise ValueError('invalid_transcript_optimization_input')
    rows = evidence['segments']
    if not isinstance(rows, list) or not 1 <= len(rows) <= 8000 or len(chunks) > 512:
        raise ValueError('invalid_transcript_optimization_input')
    source_context = source_context or {}
    references = references or {}
    samples = references.get('samples', [])
    bridge = (source_context.get('asset_sha256') == evidence.get('asset_sha256')
              and source_context.get('reference_source_asset_sha256') == references.get('source_asset_sha256')
              and isinstance(source_context.get('source_sha256'), str)
              and re.fullmatch('[a-f0-9]{64}', source_context['source_sha256']))
    if (not isinstance(samples, list) or len(samples) > 100
            or samples and references.get('source_asset_sha256') != evidence.get('asset_sha256') and not bridge):
        raise ValueError('transcript_optimization_reference_identity_mismatch')
    for sample in samples:
        if (not isinstance(sample, dict) or sample.get('reference_basis') not in
                ('human_visual_read_of_saved_source_frame', 'apple_vision_ocr_saved_source_frame')
                or sample.get('spoken_audio_reference') is not False
                or not isinstance(sample.get('visible_hard_subtitle'), str)
                or not 1 <= len(sample['visible_hard_subtitle']) <= 200
                or type(sample.get('absolute_seconds')) not in (int, float)
                or not math.isfinite(sample['absolute_seconds'])
                or not 0 <= sample['absolute_seconds'] <= evidence['duration_seconds']
                or not isinstance(sample.get('frame_sha256'), str)
                or not re.fullmatch('[a-f0-9]{64}', sample['frame_sha256'])):
            raise ValueError('invalid_transcript_optimization_reference')
        if sample['reference_basis'] == 'apple_vision_ocr_saved_source_frame' and (
                not isinstance(sample.get('ocr_result_sha256'), str)
                or not re.fullmatch('[a-f0-9]{64}', sample['ocr_result_sha256'])):
            raise ValueError('invalid_transcript_optimization_reference')
    if source_context and (source_context.get('asset_sha256') != evidence.get('asset_sha256')
            or not isinstance(source_context.get('source_sha256'), str)
            or not re.fullmatch('[a-f0-9]{64}', source_context['source_sha256'])):
        raise ValueError('transcript_optimization_context_identity_mismatch')
    terms = extract_terms(source_context, samples)
    proposed, concerns, removed = {}, [], set()
    for sample in samples:
        time = sample['absolute_seconds']
        active = [index for index, row in enumerate(rows) if row['start'] <= time <= row['end']]
        if len(active) != 1:
            continue
        index = active[0]; row = rows[index]
        target = normalized(sample['visible_hard_subtitle']); text = row['text']
        if target in normalized(text):
            continue
        # Retain source spelling and unrelated words: replace only one short anchored span.
        choices = []
        for start in range(len(text) - len(target) + 1):
            span = text[start:start + len(target)]
            if len(normalized(span)) != len(target):
                continue
            errors = sum(a != b for a, b in zip(normalized(span), target))
            if 1 <= errors <= (2 if len(target) >= 4 else 1) and errors <= max(1, len(target) // 2):
                choices.append((errors, start, span))
        if not choices:
            continue
        minimum = min(choice[0] for choice in choices)
        best = [choice for choice in choices if choice[0] == minimum]
        if len(best) != 1 or index in proposed:
            continue
        _, start, span = best[0]
        new_text = text[:start] + sample['visible_hard_subtitle'] + text[start + len(target):]
        proposed[index] = {'segment_index': index, 'expected_text_sha256': hashlib.sha256(text.encode()).hexdigest(),
            'text': new_text, 'basis': {'rule': 'unique_time_anchored_hard_subtitle_span',
                'absolute_seconds': time, 'original_span': span, 'reference_span': sample['visible_hard_subtitle'],
                'frame_sha256': sample['frame_sha256'], 'reference_basis': sample['reference_basis'],
                'ocr_result_sha256': sample.get('ocr_result_sha256'), 'spoken_audio_reference': False}}
    # A source-attributed name needs a unique local spelling and a repeated role anchor.
    names = [item for item in terms if 4 <= len(item['term']) <= 6
             and re.fullmatch(r'[\u4e00-\u9fff]+', item['term'])
             and any(proof['basis'].endswith(('author_attribution_candidate', 'named_context'))
                     for proof in item['evidence'])]
    variants = {}
    canonical_name_set = {item['term'] for item in names}
    for item in names:
        term = item['term']
        for index, row in enumerate(rows):
            for start in range(len(row['text']) - len(term) + 1):
                span = row['text'][start:start + len(term)]
                if span in canonical_name_set:
                    continue
                errors = sum(a != b for a, b in zip(span, term))
                if (1 <= errors <= 2 and errors <= len(term) * .4
                        and span[0] == term[0] and span[-2:] == term[-2:]):
                    variants.setdefault(span, []).append((item, index, start))
    for span, hits in variants.items():
        canonical_names = {item['term'] for item, _, _ in hits}
        if len(canonical_names) != 1 or len({index for _, index, _ in hits}) < 2:
            continue
        anchors = []
        for item, index, start in hits:
            text = rows[index]['text']
            before, after = text[max(0, start - 8):start], text[start + len(span):start + len(span) + 12]
            if re.search(r'(?:作家|作者|名叫|名为|叫)$', before) or re.search(r'(?:出道|创作|发表|这个名字)', after):
                anchors.append(index)
        if not anchors:
            concerns.append({'rule': 'source_name_variant_without_local_role_anchor',
                             'source_term': next(iter(canonical_names)), 'variant': span,
                             'segment_indices': sorted({index for _, index, _ in hits}), 'automatic_replacement': False})
            continue
        for item, index, start in hits:
            if index in proposed or rows[index]['text'].count(span) != 1:
                continue
            text = rows[index]['text']
            proposed[index] = {'segment_index': index, 'expected_text_sha256': hashlib.sha256(text.encode()).hexdigest(),
                'text': text[:start] + item['term'] + text[start + len(span):],
                'basis': {'rule': 'unique_source_name_repeated_local_role_anchor', 'source_term': item['term'],
                    'original_span': span, 'role_anchor_segment_indices': sorted(set(anchors)),
                    'source_evidence': item['evidence'], 'spoken_audio_groundtruth': False}}
    for index, row in enumerate(rows):
        for other in range(max(0, index - 8), min(len(rows), index + 9)):
            if other == index or other in removed or index in removed:
                continue
            proof = overlap_removal(rows, chunks, index, other)
            if proof and index not in proposed:
                proposed[index] = {'segment_index': index,
                    'expected_text_sha256': hashlib.sha256(row['text'].encode()).hexdigest(),
                    'remove_overlap_with': other, 'basis': proof}
                removed.add(index)
                break
            windows = {chunk['index']: chunk for chunk in chunks}
            window_a, window_b = windows.get(row.get('chunk_index'), {}), windows.get(rows[other].get('chunk_index'), {})
            real_overlap = (all('start' in window and 'end' in window for window in (window_a, window_b))
                            and max(window_a['start'], window_b['start']) < min(window_a['end'], window_b['end']))
            if (other > index and real_overlap and row.get('chunk_index') != rows[other].get('chunk_index')
                    and max(row['start'], rows[other]['start']) < min(row['end'], rows[other]['end'])
                    and len(normalized(row['text'])) >= 6
                    and SequenceMatcher(None, normalized(row['text']), normalized(rows[other]['text'])).ratio() >= .75):
                concerns.append({'segment_index': index, 'other_segment_index': other,
                                 'rule': 'near_overlap_requires_review', 'automatic_removal': False})
        if re.search(r'(字幕.*(?:志愿者|提供|制作)|Amara\.org)', row['text'], re.I):
            concerns.append({'segment_index': index, 'rule': 'possible_subtitle_credit_hallucination',
                             'basis': 'known_transcription_tail_pattern_not_proof_of_silence', 'automatic_removal': False})
    for diagnostic in evidence.get('quality_diagnostics', {}).get('segments', []):
        if diagnostic.get('flags'):
            concerns.append({'rule': 'native_metric_review_hint', 'original_diagnostic': diagnostic,
                             'automatic_removal': False})
    # No deleting a target retained by another deletion and no unbounded revision batch.
    deletions = {index for index, edit in proposed.items() if 'remove_overlap_with' in edit}
    proposed = {index: edit for index, edit in proposed.items()
                if edit.get('remove_overlap_with') not in deletions}
    edits = [proposed[index] for index in sorted(proposed)][:50]
    output = {'schema_version': 1, 'policy': 'time_anchored_local_revision_v1', 'edits': edits,
        'eligible_edits_total': len(proposed), 'proposal_limit': 50, 'truncated_proposals': len(proposed) > 50,
        'lexical_candidates': terms, 'review_concerns': concerns[:500], 'semantic_status': 'not_reviewed',
        'human_groundtruth': False, 'cer': None, 'model_calls': 0, 'source_requests': 0,
        'input_sha256': digest({'evidence': evidence, 'chunks': chunks, 'context': source_context, 'references': references})}
    output['reference_binding'] = {'audio_asset_sha256': evidence.get('asset_sha256'),
        'reference_source_asset_sha256': references.get('source_asset_sha256'),
        'source_record_sha256': source_context.get('source_sha256'),
        'binding': 'same_asset' if references.get('source_asset_sha256') == evidence.get('asset_sha256')
        else 'server_verified_derived_audio_bridge' if bridge else 'no_references'}
    output['plan_sha256'] = digest(output)
    return output
