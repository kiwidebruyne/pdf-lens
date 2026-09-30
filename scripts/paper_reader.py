#!/usr/bin/env python3
"""Prepare, structurally validate, and build an offline annotated PDF reader.

Production dependencies: Python standard library and PyMuPDF (pymupdf).
Validation establishes structural integrity, not linguistic correctness.
"""
import argparse
import base64
import copy
import hashlib
import html
import json
import math
import os
from pathlib import Path
import re
import shutil
import sys
import tempfile
import unicodedata
import xml.etree.ElementTree as ET

ROOT = Path(__file__).resolve().parents[1]
ENGLISH = re.compile(r'[A-Za-z]')
REASONS = {'references', 'running_header', 'page_number', 'nonlinguistic'}
RUNTIME_ID = re.compile(r'\d+\.\d+\.\d+-[a-f0-9]{16}\Z')


def digest(path):
    h = hashlib.sha256()
    with Path(path).open('rb') as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b''):
            h.update(block)
    return h.hexdigest()


def read_json(path):
    def unique(pairs):
        result = {}
        for key, value in pairs:
            if key in result:
                raise ValueError('Duplicate JSON key: ' + key)
            result[key] = value
        return result
    return json.loads(Path(path).read_text(encoding='utf-8'), object_pairs_hook=unique,
                      parse_constant=lambda value: (_ for _ in ()).throw(ValueError('Non-finite JSON number: ' + value)))


def write_json(path, value):
    Path(path).write_text(json.dumps(value, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')


def local_path(work, relative):
    if not isinstance(relative, str) or Path(relative).is_absolute():
        raise ValueError('Artifact path must be relative')
    path = (work / relative).resolve()
    if not path.is_relative_to(work.resolve()):
        raise ValueError('Artifact path escapes work directory')
    return path


def svg_size(path):
    root = ET.parse(path).getroot()
    values = [float(v) for v in root.attrib['viewBox'].split()]
    if len(values) != 4 or values[:2] != [0, 0]:
        raise ValueError('Unsupported SVG viewBox')
    return values[2:]


def finite(value):
    return type(value) in (int, float) and math.isfinite(value)


def prepared_tokens(work, prepared):
    """Check retained sources before permitting annotation validation or reuse."""
    version = prepared.get('version')
    if version != 2 or not isinstance(prepared.get('pages'), list) or not prepared['pages']:
        raise ValueError('Invalid v2 prepared document/pages')
    scope = prepared.get('scope', {})
    first, last = scope.get('first_page'), scope.get('last_page')
    if type(first) is not int or type(last) is not int or first < 1 or first > last or last > prepared.get('source_pages', 0) or len(prepared['pages']) != last - first + 1:
        raise ValueError('Invalid selected page scope')
    if digest(work / 'source.pdf') != prepared['source']['sha256']:
        raise ValueError('Source PDF hash mismatch')
    tokens = {}
    start = prepared['scope']['first_page']
    for number, page in enumerate(prepared['pages'], start):
        if page['number'] != number:
            raise ValueError('Prepared page numbers must be sequential')
        svg = local_path(work, page['svg'])
        if digest(svg) != page['svg_sha256']:
            raise ValueError(f'Page {number}: SVG hash mismatch')
        width, height = page['width'], page['height']
        if not all(finite(v) and v > 0 for v in (width, height)) or svg_size(svg) != [width, height]:
            raise ValueError(f'Page {number}: invalid rendered dimensions')
        if not isinstance(page.get('tokens'), list):
            raise ValueError(f'Page {number}: tokens must be an array')
        for index, token in enumerate(page['tokens']):
            key = token['id']
            if key != f'p{number}t{index}' or key in tokens:
                raise ValueError('Invalid or duplicate source token ID')
            if not isinstance(token['text'], str) or (not token['text'].strip(' \t\r\n') and not token.get('chars')):
                raise ValueError(f'{key}: empty extracted text and glyph record')
            box = token['box']
            if not isinstance(box, list) or len(box) != 4 or not all(finite(v) for v in box):
                raise ValueError(f'{key}: invalid geometry')
            x, y, w, h = box
            if w <= 0 or h <= 0 or x < -1 or y < -1 or x + w > width + 1 or y + h > height + 1:
                raise ValueError(f'{key}: geometry outside visible page; inspect extraction')
            if any(type(token[v]) is not int or token[v] < 0 for v in ('block', 'line')):
                raise ValueError(f'{key}: invalid block/line')
            if not isinstance(token.get('chars'), list) or not token['chars']:
                raise ValueError(f'{key}: raw character records are required')
            tokens[key] = token
    if not tokens:
        raise ValueError('No extracted text in document; full-page scans are unsupported')
    return tokens


def verify_manifest(work, prepared):
    manifest = read_json(work / 'manifest.json')
    expected = {'source.pdf', 'prepared.json', 'pdfinfo.txt', 'inspection.txt'}
    expected.update(('anomalies.json', 'glyphs.json'))
    expected.update(page['svg'] for page in prepared['pages'])
    execution_path = work / 'execution.json'
    if execution_path.is_file():
        execution = read_json(execution_path)
        if (not isinstance(execution, dict) or set(execution) != {'runtime_id'} or
                not isinstance(execution.get('runtime_id'), str) or
                not RUNTIME_ID.fullmatch(execution['runtime_id'])):
            raise ValueError('Execution runtime pin is invalid')
        expected.add('execution.json')
    if manifest.get('version') != prepared['version'] or set(manifest.get('files', {})) != expected:
        raise ValueError('Machine artifact integrity manifest is invalid')
    backend = manifest.get('backend')
    if (not isinstance(backend, dict) or backend.get('name') != 'pymupdf' or
            not isinstance(backend.get('version'), str) or
            not isinstance(manifest.get('processor_version'), str) or
            not manifest['processor_version']):
        raise ValueError('v2 extraction provenance is missing or invalid')
    if (prepared.get('backend') != backend or
            prepared.get('processor_version') != manifest['processor_version']):
        raise ValueError('Prepared document and manifest extraction provenance differ')
    for name, expected_hash in manifest['files'].items():
        if digest(local_path(work, name)) != expected_hash:
            raise ValueError('Machine artifact integrity mismatch: ' + name)


def _anomalous_codepoints(value):
    points = []
    for char in value:
        code = ord(char)
        private_use = (0xE000 <= code <= 0xF8FF or 0xF0000 <= code <= 0xFFFFD or
                       0x100000 <= code <= 0x10FFFD)
        if (code < 32 and char not in '\t\n\r') or code == 0xFFFD or private_use or code == 0:
            points.append(f'U+{code:04X}')
    return points


def _rect_points(rect, matrix):
    import pymupdf
    transformed = pymupdf.Rect(rect) * matrix
    return [float(transformed.x0), float(transformed.y0),
            float(transformed.width), float(transformed.height)]


def _extract_v2(pdf_path, stage, first, last=None):
    try:
        import pymupdf
    except ImportError as error:
        raise ValueError('PyMuPDF is required for new v2 work (install pymupdf in this Python environment)') from error
    document = pymupdf.open(pdf_path)
    source_pages = len(document)
    if first < 1 or (last is not None and last > source_pages):
        raise ValueError('Selected page range exceeds source PDF')
    if last is None:
        last = source_pages
    pages, anomalies, glyphs = [], [], []
    inspection = ['Original extraction order only. Correct logical order in annotations.',
                  'Inspect SVGs and source before setting review flags. Image-only lettering is not extracted.', '']
    for number in range(first, last + 1):
        page = document[number - 1]
        matrix = page.rotation_matrix
        svg_name = f'page-{number}.svg'
        (stage / svg_name).write_text(page.get_svg_image(text_as_path=True), encoding='utf-8')
        width, height = svg_size(stage / svg_name)
        raw = page.get_text('rawdict', sort=False)
        tokens, line_index, block_index, glyph_index = [], 0, -1, 0
        inspection.append(f'PAGE {number} ({width} x {height} rendered points)')
        for block in raw.get('blocks', []):
            if 'lines' not in block:
                continue
            block_index += 1
            for line in block['lines']:
                chars = []
                for span in line.get('spans', []):
                    for char in span.get('chars', []):
                        mapped = char.get('c', '')
                        record = {'id': f'p{number}c{glyph_index}', 'text': mapped,
                                  'box': _rect_points(char.get('bbox'), matrix),
                                  'origin': [float(v) for v in (pymupdf.Point(char['origin']) * matrix)]}
                        glyph_index += 1
                        glyphs.append({'page': number, **record})
                        chars.append((char, record))
                groups, current = [], []
                for char, record in chars:
                    mapped = char.get('c', '')
                    if mapped.isspace() and not _anomalous_codepoints(mapped):
                        if current:
                            groups.append(current); current = []
                    else:
                        current.append((char, record))
                if current:
                    groups.append(current)
                for group in groups:
                    raw_text = ''.join(char.get('c', '') for char, _ in group)
                    char_records = [record for _, record in group]
                    boxes = [ch['box'] for ch in char_records]
                    x0, y0 = min(box[0] for box in boxes), min(box[1] for box in boxes)
                    x1, y1 = max(box[0]+box[2] for box in boxes), max(box[1]+box[3] for box in boxes)
                    token = {'id': f'p{number}t{len(tokens)}', 'text': raw_text,
                             'box': [x0, y0, x1-x0, y1-y0], 'block': block_index,
                             'line': line_index, 'chars': char_records}
                    tokens.append(token)
                    points = sorted(set(p for ch in raw_text for p in _anomalous_codepoints(ch)))
                    if points:
                        anomalies.append({'token': token['id'], 'codepoints': points,
                                          'glyphs': [char['id'] for char in char_records]})
                    inspection.append(f"[{token['id']}] {raw_text}")
                line_index += 1
            line_index += 1
        pages.append({'number': number, 'width': width, 'height': height, 'svg': svg_name,
                      'svg_sha256': digest(stage / svg_name), 'tokens': tokens})
        inspection.append('')
    document.close()
    return source_pages, pages, anomalies, glyphs, inspection


def prepare(pdf, work, page_range=None, runtime_id=None):
    pdf, work = pdf.resolve(), work.resolve()
    if runtime_id is not None and (not isinstance(runtime_id, str) or not RUNTIME_ID.fullmatch(runtime_id)):
        raise ValueError('Runtime ID must match x.y.z-16-lowercase-hex')
    source_hash = digest(pdf)
    if page_range is not None:
        selected = re.fullmatch(r'([1-9]\d*)-([1-9]\d*)', page_range)
        if not selected:
            raise ValueError('Selected pages must be START-END with positive PDF page numbers')
        first, last = map(int, selected.groups())
        if first > last:
            raise ValueError('Selected page start exceeds end')
        requested_scope = {'first_page': first, 'last_page': last}
    else:
        requested_scope = None
    if work.exists() and any(work.iterdir()):
        if not (work / 'prepared.json').is_file():
            raise ValueError('Work directory is nonempty without prepared.json; refusing to overwrite')
        previous = read_json(work / 'prepared.json')
        if previous['source']['sha256'] != source_hash:
            raise ValueError('Work directory belongs to a different input PDF')
        expected_scope = requested_scope or {'first_page': 1, 'last_page': previous.get('source_pages')}
        if previous.get('scope') != expected_scope:
            raise ValueError('Work directory belongs to a different selected page range')
        verify_manifest(work, previous)
        prepared_tokens(work, previous)
        existing_execution = work / 'execution.json'
        if runtime_id is not None:
            if not existing_execution.is_file():
                raise ValueError('Existing work has no execution runtime pin')
            if read_json(existing_execution).get('runtime_id') != runtime_id:
                raise ValueError('Work directory belongs to a different execution runtime')
        return {'ok': True, 'resumed': True, 'work': str(work)}
    work.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix='.paper-prepare-', dir=work.parent) as temporary:
        stage = Path(temporary)
        shutil.copyfile(pdf, stage / 'source.pdf')
        try:
            import pymupdf
        except ImportError as error:
            raise ValueError('PyMuPDF is required for new v2 work (install pymupdf in this Python environment)') from error
        first = requested_scope['first_page'] if requested_scope else 1
        source_pages, pages, anomalies, glyphs, inspection = _extract_v2(
            stage / 'source.pdf', stage, first, requested_scope['last_page'] if requested_scope else None)
        last = requested_scope['last_page'] if requested_scope else source_pages
        scope = {'first_page': first, 'last_page': last}
        if not pages:
            raise ValueError('Selected page range contains no pages')
        version = 2
        backend = {'name': 'pymupdf', 'version': pymupdf.VersionBind}
        prepared = {'version': version, 'backend': backend, 'processor_version': (ROOT / 'VERSION').read_text().strip(),
                    'source': {'name': pdf.name, 'sha256': source_hash}, 'pages': pages,
                    'scope': scope, 'source_pages': source_pages}
        write_json(stage / 'anomalies.json', anomalies)
        write_json(stage / 'glyphs.json', glyphs)
        (stage / 'pdfinfo.txt').write_text(f'Backend: PyMuPDF {pymupdf.VersionBind}\nPages: {source_pages}\n', encoding='utf-8')
        prepared_tokens(stage, prepared)
        write_json(stage / 'prepared.json', prepared)
        starter = {'version': 3, 'source_sha256': source_hash,
                   'title': pdf.stem, 'language': 'en', 'sentences': [], 'excluded': [],
                   'unselectable_pages': [{'page': p['number'], 'kind': '', 'note': ''} for p in pages if not p['tokens']],
                   'review': {'language': False, 'layout': False, 'coverage': False, 'notes': ''}}
        starter.update({'scope': scope, 'page_labels': {}, 'toc': [], 'math': {}})
        write_json(stage / 'annotations.json', starter)
        (stage / 'inspection.txt').write_text('\n'.join(inspection) + '\n', encoding='utf-8')
        if runtime_id is not None:
            write_json(stage / 'execution.json', {'runtime_id': runtime_id})
        machine_files = ['source.pdf', 'prepared.json', 'pdfinfo.txt', 'inspection.txt']
        machine_files.extend(('anomalies.json', 'glyphs.json'))
        if runtime_id is not None:
            machine_files.append('execution.json')
        machine_files.extend(page['svg'] for page in pages)
        write_json(stage / 'manifest.json', {'version': version, 'backend': backend,
                    'processor_version': prepared['processor_version'],
                    'files': {name: digest(stage / name) for name in machine_files}})
        if work.exists():
            work.rmdir()  # Only the previously verified empty directory; races fail closed.
        os.replace(stage, work)
    return {'ok': True, 'resumed': False, 'work': str(work), 'pages': len(pages),
            'tokens': sum(len(p['tokens']) for p in pages)}


def convert_annotations_v3(annotation):
    """Explicitly migrate a v2 authoring document without changing source IDs."""
    if annotation.get('version') != 2:
        raise ValueError('Only v2 annotations can be converted to v3')
    converted = copy.deepcopy(annotation)
    lexicon = converted.pop('lexicon', {})
    converted['version'] = 3
    for sentence in converted.get('sentences', []):
        units = sentence.pop('units', [])
        whole = [unit for unit in units if unit.get('start') == 0 and unit.get('end') == len(sentence.get('tokens', []))]
        if len(whole) != 1:
            raise ValueError(f"{sentence.get('id')}: exactly one whole-sentence unit required for conversion")
        sentence['natural'] = whole[0]['natural']
        words = sentence.get('words', {})
        for key, word in words.items():
            entry = lexicon.get(word.get('entry'))
            if not isinstance(entry, dict) or not isinstance(entry.get('gloss'), str):
                raise ValueError(f'{key}: missing v2 lexicon gloss')
            words[key] = {'base': entry['gloss'], 'meaning': word.get('meaning')}
    return converted


def validate(work, annotation_path):
    prepared = read_json(work / 'prepared.json')
    verify_manifest(work, prepared)
    tokens = prepared_tokens(work, prepared)
    annotation = read_json(annotation_path)
    errors = []
    def check(condition, message):
        if not condition:
            errors.append(message)
        return bool(condition)
    def text(value):
        return isinstance(value, str) and bool(value.strip())
    def span(item, total, label):
        a, b = item.get('start'), item.get('end')
        if not check(type(a) is int and type(b) is int and 0 <= a < b <= total, label + ': invalid span'):
            return None
        return a, b
    version = annotation.get('version')
    check(prepared['version'] == 2 and version in (2, 3), 'Annotation version must be v2 or v3 over v2 preparation')
    check(annotation.get('source_sha256') == prepared['source']['sha256'], 'Annotation source hash mismatch')
    check(annotation.get('scope') == prepared['scope'], 'Annotation selected page range mismatch')
    check(text(annotation.get('title')), 'Title is required')
    check(annotation.get('language') == 'en', 'Language must be en')
    review = annotation.get('review', {})
    for flag in ('language', 'layout', 'coverage'):
        check(review.get(flag) is True, f'review.{flag} must be true after actual inspection')
    check(text(review.get('notes')), 'Review notes are required')
    empty_pages = {page['number'] for page in prepared['pages'] if not page['tokens']}
    dispositions = annotation.get('unselectable_pages', [])
    if not isinstance(dispositions, list):
        raise ValueError('unselectable_pages must be an array')
    seen_pages = set()
    for disposition in dispositions:
        page = disposition.get('page')
        check(type(page) is int and page in empty_pages and page not in seen_pages, 'unselectable_pages must identify each zero-token page exactly once')
        seen_pages.add(page)
        check(disposition.get('kind') in ('blank', 'figure_only') and text(disposition.get('note')), 'Zero-token page needs blank/figure_only visual disposition and note; scanned prose is unsupported')
    check(seen_pages == empty_pages, 'All zero-token pages need unselectable_pages visual disposition; scanned prose is unsupported')
    lexicon = annotation.get('lexicon', {})
    if version == 2:
        if not isinstance(lexicon, dict):
            raise ValueError('lexicon must be an object')
        for key, entry in lexicon.items():
            check(text(key) and isinstance(entry, dict) and all(text(entry.get(f)) for f in ('lemma', 'pos', 'gloss')), f'Lexicon {key}: lemma/pos/gloss required')
    else:
        check('lexicon' not in annotation, 'v3 annotations must not contain lexicon')
    math = annotation.get('math', {})
    math_by_token = {}
    if version in (2, 3):
        check(isinstance(math, dict), 'math must be an object')
        labels = annotation.get('page_labels', {})
        check(isinstance(labels, dict) and set(labels) == {str(p['number']) for p in prepared['pages']} and all(text(v) for v in labels.values()), 'Every selected PDF page needs a printed page label')
        toc = annotation.get('toc', [])
        check(isinstance(toc, list), 'toc must be an array')
        selected_pages = {p['number']: p for p in prepared['pages']}
        for item in toc:
            check(isinstance(item, dict) and text(item.get('title')) and item.get('page') in selected_pages, 'TOC entry needs title and selected PDF page')
        for ref, item in math.items():
            check(text(ref) and isinstance(item, dict), f'Invalid math reference: {ref!r}')
            ids = item.get('tokens', [])
            check(isinstance(ids, list) and bool(ids), f'{ref}: math tokens required')
            for key in ids:
                check(key in tokens and key not in math_by_token, f'{ref}: unknown or overlapping math token {key}')
                if key in tokens:
                    math_by_token[key] = ref
            regions = item.get('regions', [])
            check(isinstance(regions, list) and bool(regions), f'{ref}: visual math region required')
            for region in regions:
                page = selected_pages.get(region.get('page')) if isinstance(region, dict) else None
                box = region.get('box') if isinstance(region, dict) else None
                if page is None or not isinstance(box, list) or len(box) != 4 or not all(finite(v) for v in box):
                    check(False, f'{ref}: invalid math region')
                    continue
                x, y, w, h = box
                check(w > 0 and h > 0 and x >= 0 and y >= 0 and x+w <= page['width'] and y+h <= page['height'], f'{ref}: math region outside page')
                check(any(key in tokens and key.startswith(f"p{page['number']}t") for key in ids), f'{ref}: math region page has no source token')

    def check_parts(parts, expected_refs, label):
        if not check(isinstance(parts, list) and bool(parts), label + ': translation parts required'):
            return
        observed = []
        for part in parts:
            if not check(isinstance(part, dict), label + ': invalid translation part'):
                continue
            kind = part.get('type')
            if kind == 'text':
                check(set(part) == {'type', 'text'}, label + ': text part may contain only type and text')
                check(text(part.get('text')), label + ': empty Korean text part')
            elif kind == 'math':
                check(set(part) == {'type', 'ref'}, label + ': math part may contain only type and ref')
                observed.append(part.get('ref'))
            else:
                check(False, label + ': unknown translation part type')
        check(observed == expected_refs, label + ': math formula references must match source order and coverage')
    owners = {}
    sentence_ids, unit_ids = set(), set()
    sentences = annotation.get('sentences', [])
    if not isinstance(sentences, list):
        raise ValueError('sentences must be an array')
    def assign(ids, label):
        if not isinstance(ids, list) or not ids:
            errors.append(label + ': nonempty tokens list required')
            return []
        valid = []
        for key in ids:
            if not isinstance(key, str) or key not in tokens:
                errors.append(f'{label}: unknown token {key!r}')
            elif key in owners:
                errors.append(f'{key}: assigned more than once ({owners[key]}, {label})')
            else:
                owners[key] = label
                valid.append(key)
        return valid
    previous_sentence_end_page = prepared['scope']['first_page']
    for sentence in sentences:
        sid = sentence.get('id')
        check(text(sid) and sid not in sentence_ids, f'Duplicate/empty sentence ID: {sid}')
        sentence_ids.add(sid)
        ids = sentence.get('tokens', [])
        valid = assign(ids, str(sid))
        if not isinstance(ids, list) or not ids:
            continue
        if version in (2, 3):
            sentence_pages = [int(key[1:key.index('t')]) for key in ids if key in tokens]
            if sentence_pages:
                check(sentence_pages == sorted(sentence_pages), f'{sid}: source tokens must follow PDF page order')
                check(sentence_pages[0] >= previous_sentence_end_page,
                      f'{sid}: sentence PDF page order goes backward')
                previous_sentence_end_page = sentence_pages[-1]
        n = len(ids)
        math_spans = []
        if version in (2, 3):
            for ref, item in math.items():
                positions = [i for i, key in enumerate(ids) if math_by_token.get(key) == ref]
                if not positions:
                    continue
                check(len(positions) == len(item['tokens']) and positions == list(range(positions[0], positions[-1]+1)) and ids[positions[0]:positions[-1]+1] == item['tokens'], f'{sid}: math {ref} must be contiguous in one sentence')
                math_spans.append((positions[0], positions[-1]+1, ref))
            math_spans.sort()
        def refs_for(a, b):
            refs = []
            for start, end, ref in math_spans:
                if start < b and end > a:
                    check(a <= start and end <= b, f'{sid}: unit splits math {ref}')
                    refs.append(ref)
            return refs
        units = sentence.get('units', []) if version == 2 else []
        if version == 3:
            check('units' not in sentence, f'{sid}: v3 sentence must not contain units')
            check_parts(sentence.get('natural'), refs_for(0, n), f'{sid} natural')
        intervals = []
        for unit in units:
            uid = unit.get('id')
            check(text(uid) and uid not in unit_ids, f'Duplicate/empty unit ID: {uid}')
            unit_ids.add(uid)
            bounds = span(unit, n, str(uid))
            if bounds is None:
                continue
            a, b = bounds
            check(bounds not in intervals, f'{sid}: duplicate unit range {bounds}')
            intervals.append(bounds)
            check_parts(unit.get('natural'), refs_for(a, b), f'{uid} natural')
            cursor = a
            chunks = unit.get('literal', [])
            for chunk in chunks:
                bounds_chunk = span(chunk, n, str(uid) + ' literal')
                if bounds_chunk:
                    ca, cb = bounds_chunk
                    check(ca == cursor and cb <= b, f'{uid}: literal chunks must partition unit in order')
                    cursor = cb
                    check_parts(chunk.get('parts'), refs_for(ca, cb), f'{uid} literal')
            check(cursor == b and bool(chunks), f'{uid}: literal chunks must cover entire unit')
        if version == 2:
            check(len(intervals) == 1 and intervals.count((0, n)) == 1,
                  f'{sid}: exactly one whole-sentence unit required')
        for i, (a, b) in enumerate(intervals):
            for c, d in intervals[i+1:]:
                check(not (a < c < b < d or c < a < d < b), f'{sid}: crossing translation units')
        words = sentence.get('words', {})
        if not isinstance(words, dict):
            raise ValueError(f'{sid}: words must be an object')
        for key in words:
            check(key in ids, f'{sid}: word entry outside sentence: {key}')
            if version == 3:
                word = words[key]
                check(isinstance(word, dict) and set(word) == {'base', 'meaning'} and text(word.get('base')) and text(word.get('meaning')),
                      f'{key}: base and context meaning required')
        for key in valid:
            if ENGLISH.search(tokens[key]['text']) and key not in math_by_token:
                word = words.get(key, {})
                if version == 2:
                    check(isinstance(word, dict) and word.get('entry') in lexicon and text(word.get('meaning')) and text(word.get('role')) and isinstance(word.get('expression'), str), f'{key}: lexical entry, context meaning, role and expression required')
                elif key not in words:
                    check(False, f'{key}: base and context meaning required')
        joined = set()
        for join in sentence.get('joins', []):
            bounds = span(join, n, str(sid) + ' join')
            if bounds is None:
                continue
            a, b = bounds
            check(b-a >= 2, f'{sid}: join needs multiple tokens')
            if version in (2, 3):
                check(not any(key in math_by_token for key in ids[a:b]), f'{sid}: join overlaps math source tokens')
            check(not joined.intersection(range(a, b)), f'{sid}: overlapping joins')
            joined.update(range(a, b))
            if any(key not in tokens for key in ids[a:b]):
                continue
            parts = [unicodedata.normalize('NFKC', tokens[key]['text']).replace('\u00ad', '') for key in ids[a:b]]
            candidates = {''.join(parts)}
            # Hyphen removal is allowed only across actual physical line/page boundaries.
            stripped = parts[:]
            for i in range(len(parts)-1):
                left, right = tokens[ids[a+i]], tokens[ids[a+i+1]]
                different_line = (ids[a+i].split('t')[0], left['line']) != (ids[a+i+1].split('t')[0], right['line'])
                if different_line and stripped[i].endswith('-'):
                    stripped[i] = stripped[i][:-1]
            candidates.add(''.join(stripped))
            check(join.get('text') in candidates, f'{sid}: join text is not normalized source concatenation')
            if version == 2:
                entries = [words.get(key, {}).get('entry') for key in ids[a:b] if ENGLISH.search(tokens[key]['text'])]
                check(bool(entries) and len(set(entries)) == 1 and entries[0] in lexicon, f'{sid}: joined lexical tokens must share a base entry')
    for excluded in annotation.get('excluded', []):
        check(excluded.get('reason') in REASONS, 'Unknown exclusion reason')
        check(text(excluded.get('note')), 'Concrete exclusion note required')
        assign(excluded.get('tokens'), 'excluded:' + str(excluded.get('reason')))
    missing = [key for key in tokens if key not in owners]
    check(not missing, f'{len(missing)} source tokens unassigned: ' + ', '.join(missing[:20]))
    if version in (2, 3):
        check(all(key in owners and not owners[key].startswith('excluded:') for key in math_by_token), 'Math tokens must belong to source sentences')
        for ref, item in math.items():
            check(any(item['tokens'] == sentence['tokens'][i:i+len(item['tokens'])] for sentence in sentences for i in range(len(sentence['tokens'])-len(item['tokens'])+1)), f'{ref}: math must belong to one contiguous sentence range')
        anomalies = read_json(work / 'anomalies.json')
        inspected_nonlinguistic = {key for item in annotation.get('excluded', [])
                                 if item.get('reason') == 'nonlinguistic' and text(item.get('note'))
                                 for key in item.get('tokens', [])}
        for item in anomalies:
            check(item['token'] in math_by_token or item['token'] in inspected_nonlinguistic,
                  f"{item['token']}: unusual extracted glyph needs an inspected math region or verified nonlinguistic disposition")
    return prepared, annotation, {'ok': not errors, 'coverage': {'total': len(tokens), 'assigned': len(owners), 'missing': len(missing)}, 'errors': errors,
                                  'limits': 'Structural checks only; translation quality, reading order and image-only lettering require inspection.'}


def build(work, annotations, output):
    output = output.resolve()
    if output.suffix.lower() != '.html':
        raise ValueError('Build output must have .html extension')
    prepared, annotation, report = validate(work, annotations)
    if not report['ok']:
        return report
    if annotation['version'] == 2:
        annotation = convert_annotations_v3(annotation)
    assets = ROOT / 'assets' / 'reader'
    template = (assets / 'index.html').read_text(encoding='utf-8')
    pages = []
    for page in prepared['pages']:
        page = dict(page)
        raw = local_path(work, page.pop('svg')).read_bytes()
        page.pop('svg_sha256')
        page['printed_label'] = annotation['page_labels'][str(page['number'])]
        page['image'] = 'data:image/svg+xml;base64,' + base64.b64encode(raw).decode('ascii')
        pages.append(page)
    payload = {'version': annotation['version'], 'template_version': 1, 'title': annotation['title'], 'source': prepared['source'],
               'pages': pages, 'sentences': annotation['sentences'],
               'unselectable_pages': annotation.get('unselectable_pages', [])}
    payload.update({'scope': prepared['scope'], 'toc': annotation['toc'], 'math': annotation['math']})
    data = json.dumps(payload, ensure_ascii=False, separators=(',', ':'))
    for char in '<>&\u2028\u2029':
        data = data.replace(char, '\\u%04x' % ord(char))
    replacements = {'__READER_CSS__': (assets / 'reader.css').read_text(encoding='utf-8'),
                    '__READER_JS__': (assets / 'reader.js').read_text(encoding='utf-8'),
                    '__READER_TITLE__': html.escape(annotation['title'], quote=True), '__READER_DATA__': data}
    for marker in replacements:
        if template.count(marker) != 1:
            raise ValueError('Template must contain exactly one ' + marker)
    # Single pass prevents annotation text resembling a marker from being substituted.
    result = re.sub('|'.join(map(re.escape, replacements)), lambda match: replacements[match.group()], template)
    output = output.resolve()
    protected = {annotations.resolve()}
    protected.update((work / name).resolve() for name in
                     ('source.pdf', 'prepared.json', 'pdfinfo.txt', 'inspection.txt', 'annotations.json', 'manifest.json', 'anomalies.json', 'glyphs.json', 'execution.json'))
    protected.update(local_path(work, page['svg']) for page in prepared['pages'])
    if output in protected:
        raise ValueError('Output must not replace input or prepared artifacts')
    output.parent.mkdir(parents=True, exist_ok=True)
    fd, temporary = tempfile.mkstemp(prefix='.reader-', suffix='.html', dir=output.parent)
    try:
        with os.fdopen(fd, 'w', encoding='utf-8') as stream:
            stream.write(result)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, output)
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)
    report['output'] = str(output)
    return report


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest='action', required=True)
    p = sub.add_parser('prepare'); p.add_argument('pdf', type=Path); p.add_argument('--work', required=True, type=Path); p.add_argument('--pages'); p.add_argument('--runtime-id')
    for name in ('validate', 'build'):
        p = sub.add_parser(name); p.add_argument('--work', required=True, type=Path); p.add_argument('--annotations', required=True, type=Path)
        if name == 'build':
            p.add_argument('--output', required=True, type=Path)
    args = parser.parse_args()
    try:
        if args.action == 'prepare':
            report = prepare(args.pdf, args.work, args.pages, args.runtime_id)
        elif args.action == 'validate':
            _, _, report = validate(args.work, args.annotations)
        else:
            report = build(args.work, args.annotations, args.output)
    except (OSError, ValueError, KeyError, TypeError, AttributeError, ET.ParseError) as error:
        report = {'ok': False, 'errors': [str(error)]}
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0 if report['ok'] else 1

if __name__ == '__main__':
    sys.exit(main())
