#!/usr/bin/env python3
"""Evaluate an unchanged local transcript against explicit known reference text."""
import argparse
import ctypes
import json
from pathlib import Path
import sys
import unicodedata


def simplify_macos(text):
    if sys.platform != 'darwin':
        raise ValueError('macos_normalization_unavailable')
    cf = ctypes.CDLL('/System/Library/Frameworks/CoreFoundation.framework/CoreFoundation')
    cf.CFStringCreateWithCString.argtypes = [ctypes.c_void_p, ctypes.c_char_p, ctypes.c_uint32]
    cf.CFStringCreateWithCString.restype = ctypes.c_void_p
    cf.CFStringCreateMutableCopy.argtypes = [ctypes.c_void_p, ctypes.c_long, ctypes.c_void_p]
    cf.CFStringCreateMutableCopy.restype = ctypes.c_void_p
    cf.CFStringTransform.argtypes = [ctypes.c_void_p, ctypes.c_void_p, ctypes.c_void_p, ctypes.c_bool]
    cf.CFStringTransform.restype = ctypes.c_bool
    cf.CFStringGetCString.argtypes = [ctypes.c_void_p, ctypes.c_void_p, ctypes.c_long, ctypes.c_uint32]
    cf.CFStringGetCString.restype = ctypes.c_bool
    cf.CFRelease.argtypes = [ctypes.c_void_p]
    original = cf.CFStringCreateWithCString(None, text.encode('utf8'), 0x08000100)
    transform = cf.CFStringCreateWithCString(None, b'Traditional-Simplified', 0x08000100)
    mutable = cf.CFStringCreateMutableCopy(None, 0, original)
    try:
        buffer = ctypes.create_string_buffer(max(64, len(text.encode('utf8')) * 4 + 1))
        if (not cf.CFStringTransform(mutable, None, transform, False)
                or not cf.CFStringGetCString(mutable, buffer, len(buffer), 0x08000100)):
            raise ValueError('macos_normalization_failed')
        return buffer.value.decode('utf8')
    finally:
        for item in (mutable, transform, original):
            cf.CFRelease(item)


def normalize(text, simplified=False):
    text = unicodedata.normalize('NFKC', text).lower()
    if simplified:
        text = simplify_macos(text)
    return ''.join(char for char in text if not char.isspace() and not unicodedata.category(char).startswith('P'))


def character_error_rate(reference, hypothesis, simplified=False):
    reference, hypothesis = normalize(reference, simplified), normalize(hypothesis, simplified)
    if not reference:
        raise ValueError('reference_empty')
    if len(reference) * len(hypothesis) > 25_000_000:
        raise ValueError('evaluation_comparison_too_large')
    previous = list(range(len(hypothesis) + 1))
    for index, char in enumerate(reference, 1):
        current = [index]
        for column, other in enumerate(hypothesis, 1):
            current.append(min(previous[column] + 1, current[-1] + 1,
                               previous[column - 1] + (char != other)))
        previous = current
    errors = previous[-1]
    return {'reference_characters': len(reference), 'hypothesis_characters': len(hypothesis),
            'edit_distance': errors, 'cer': errors / len(reference),
            'normalization': 'NFKC, lowercase, remove Unicode punctuation/whitespace' +
            (', macOS ICU Traditional-Simplified' if simplified else ', preserve simplified/traditional differences'),
            'normalized_reference': reference, 'normalized_hypothesis': hypothesis}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--reference', required=True, type=Path)
    parser.add_argument('--transcript', required=True, type=Path, help='JSON containing segments[].text')
    parser.add_argument('--simplify-macos', action='store_true')
    args = parser.parse_args()
    for path in (args.reference, args.transcript):
        if not path.is_file() or path.stat().st_size > 2_000_000:
            raise ValueError('evaluation_input_missing_or_too_large')
    result = json.loads(args.transcript.read_text())
    if isinstance(result, list) and len(result) == 1:
        result = result[0]
    if isinstance(result, dict) and isinstance(result.get('evidence'), dict):
        result = result['evidence']
    hypothesis = ''.join(row['text'] for row in result['segments'])
    print(json.dumps(character_error_rate(args.reference.read_text(), hypothesis, args.simplify_macos), ensure_ascii=False))


if __name__ == '__main__':
    main()
