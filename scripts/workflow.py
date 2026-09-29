#!/usr/bin/env python3
"""Deterministic worklists and merging for parallel version-2 annotations."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import re
import tempfile
import sys

from paper_reader import read_json, digest, validate


def canonical_hash(value):
    data = json.dumps(value, ensure_ascii=False, sort_keys=True,
                       separators=(',', ':')).encode('utf-8')
    return hashlib.sha256(data).hexdigest()


def token_ids(prepared):
    return [token['id'] for page in prepared['pages'] for token in page['tokens']]


def make_worklist(work, plan):
    prepared = read_json(work / 'prepared.json')
    if prepared.get('version') != 2:
        raise ValueError('Parallel worklists require scoped version-2 preparation')
    if not isinstance(plan, dict) or set(plan) != {'chunks'} or not isinstance(plan['chunks'], list) or not plan['chunks']:
        raise ValueError('Plan must contain a nonempty chunks array')
    token_pages = {token['id']: page['number'] for page in prepared['pages']
                   for token in page['tokens']}
    seen_owned = set()
    chunks = []
    prior_last_page = 0
    chunk_ids = set()
    for raw in plan['chunks']:
        if not isinstance(raw, dict) or set(raw) != {'id', 'owned_tokens', 'context_tokens'}:
            raise ValueError('Each chunk needs exactly id, owned_tokens, and context_tokens')
        chunk_id, owned, context = raw['id'], raw['owned_tokens'], raw['context_tokens']
        if not isinstance(chunk_id, str) or not chunk_id.strip() or chunk_id in chunk_ids:
            raise ValueError(f'Duplicate or invalid chunk id: {chunk_id!r}')
        chunk_ids.add(chunk_id)
        if not isinstance(owned, list) or not owned or not isinstance(context, list):
            raise ValueError(f'{chunk_id}: owned_tokens must be nonempty and context_tokens an array')
        if len(owned) != len(set(owned)) or len(context) != len(set(context)):
            raise ValueError(f'{chunk_id}: duplicate token in owned/context list')
        unknown = [key for key in owned + context if key not in token_pages]
        if unknown:
            raise ValueError(f'{chunk_id}: unknown token IDs: {unknown[:10]}')
        duplicate = seen_owned.intersection(owned)
        if duplicate:
            raise ValueError(f'{chunk_id}: tokens owned more than once: {sorted(duplicate)[:10]}')
        first_page = min(token_pages[key] for key in owned)
        last_page = max(token_pages[key] for key in owned)
        if first_page < prior_last_page:
            raise ValueError('Chunks reverse prepared PDF page order')
        prior_last_page = last_page
        seen_owned.update(owned)
        chunks.append({'id': chunk_id, 'owned_tokens': list(owned),
                       'context_tokens': list(context)})
    missing = set(token_pages) - seen_owned
    if missing:
        ordered = token_ids(prepared)
        raise ValueError('Plan leaves source tokens unowned: ' + ', '.join(key for key in ordered if key in missing)[:20])
    return {'version': 1,
            'identity': {'source_sha256': prepared['source']['sha256'],
                         'scope': prepared['scope'],
                         'prepared_sha256': digest(work / 'prepared.json')},
            'chunks': chunks}


def validate_worklist(work, worklist):
    prepared = read_json(work / 'prepared.json')
    if not isinstance(worklist, dict) or worklist.get('version') != 1:
        raise ValueError('Unsupported worklist version')
    identity = worklist.get('identity')
    expected = {'source_sha256': prepared['source']['sha256'],
                'scope': prepared.get('scope'),
                'prepared_sha256': digest(work / 'prepared.json')}
    if identity != expected:
        raise ValueError('Worklist identity mismatch (source, scope, or prepared.json changed)')
    rebuilt = make_worklist(work, {'chunks': worklist.get('chunks')})
    if rebuilt != worklist:
        raise ValueError('Worklist is not canonical or contains unsupported fields')
    return prepared


def worklist_hash(worklist):
    return canonical_hash(worklist)


def assignments(fragment):
    result = []
    for sentence in fragment.get('sentences', []):
        result.extend(sentence.get('tokens', []))
    for item in fragment.get('excluded', []):
        result.extend(item.get('tokens', []))
    return result


def validate_fragment(work, worklist, fragment, chunk_id):
    prepared = validate_worklist(work, worklist)
    chunks = {chunk['id']: chunk for chunk in worklist['chunks']}
    if chunk_id not in chunks:
        raise ValueError(f'Unknown chunk: {chunk_id}')
    expected = chunks[chunk_id]
    metadata = fragment.get('_chunk')
    if not isinstance(metadata, dict):
        raise ValueError('Fragment is missing _chunk ownership metadata')
    wanted = {'worklist_sha256': worklist_hash(worklist), 'chunk_id': chunk_id,
              'owned_tokens': expected['owned_tokens'],
              'context_tokens': expected['context_tokens']}
    if metadata != wanted:
        raise ValueError(f'{chunk_id}: fragment ownership metadata does not match worklist')
    if fragment.get('version') != 2 or fragment.get('source_sha256') != prepared['source']['sha256'] or fragment.get('scope') != prepared['scope']:
        raise ValueError(f'{chunk_id}: fragment source/scope mismatch')
    owned = set(expected['owned_tokens'])
    seen = set()
    repeated = set()
    unknown = set()
    outside = set()
    available = set(token_ids(prepared))
    for key in assignments(fragment):
        if key in seen:
            repeated.add(key)
        seen.add(key)
        if key not in available:
            unknown.add(key)
        elif key not in owned:
            outside.add(key)
    missing = owned - seen
    if repeated or unknown or outside or missing:
        details = []
        if missing: details.append('missing owned tokens ' + ', '.join(sorted(missing)))
        if repeated: details.append('duplicate assignments ' + ', '.join(sorted(repeated)))
        if outside: details.append('outside ownership ' + ', '.join(sorted(outside)))
        if unknown: details.append('unknown tokens ' + ', '.join(sorted(unknown)))
        raise ValueError(f'{chunk_id}: ' + '; '.join(details))
    return expected


def validate_fragment_structure(work, prepared, fragment, chunk):
    """Run the production validator while allowing tokens owned by other chunks to remain absent."""
    source = read_json(work / 'annotations.json')
    for key in ('lexicon', 'sentences', 'math', 'excluded', 'toc'):
        source[key] = fragment.get(key, source.get(key, [] if key in ('sentences', 'excluded', 'toc') else {}))
    owned_tokens = set(chunk['owned_tokens'])
    local_labels = fragment.get('page_labels', {})
    source['page_labels'] = {
        str(page['number']): local_labels.get(str(page['number']), str(page['number']))
        for page in prepared['pages']}
    # These temporary flags only unlock structural checks; nothing is written back as reviewed.
    source['review'] = {'language': True, 'layout': True, 'coverage': True,
                        'notes': 'Temporary structural fragment check; author review remains pending.'}
    with tempfile.TemporaryDirectory() as directory:
        path = Path(directory) / 'fragment.json'
        path.write_text(json.dumps(source, ensure_ascii=False), encoding='utf-8')
        _, _, report = validate(work, path)
    errors = []
    for error in report['errors']:
        if 'source tokens unassigned:' in error:
            continue
        match = re.match(r'^(p\d+t\d+): unusual extracted glyph', error)
        if match and match.group(1) not in owned_tokens:
            continue
        errors.append(error)
    if errors:
        raise ValueError('structural validation failed: ' + '; '.join(errors[:8]))


def fragment_paths(path):
    path = Path(path)
    return sorted(path.glob('*.json')) if path.is_dir() else [path]


def load_fragments(work, worklist, path):
    fragments = {}
    errors = []
    by_hash = worklist_hash(worklist)
    chunks = {chunk['id']: chunk for chunk in worklist['chunks']}
    for file in fragment_paths(path):
        try:
            fragment = read_json(file)
            meta = fragment.get('_chunk', {})
            chunk_id = meta.get('chunk_id')
            if chunk_id not in chunks:
                raise ValueError('unknown chunk id')
            validate_fragment(work, worklist, fragment, chunk_id)
            prepared = read_json(work / 'prepared.json')
            validate_fragment_structure(work, prepared, fragment, chunks[chunk_id])
            if meta['worklist_sha256'] != by_hash:
                raise ValueError('worklist hash mismatch')
            if chunk_id in fragments:
                raise ValueError(f'duplicate fragment for {chunk_id}')
            fragments[chunk_id] = fragment
        except (ValueError, KeyError, TypeError, AttributeError) as error:
            errors.append(f'{file}: {error}')
    return fragments, errors


def status(work, worklist, fragments_path):
    validate_worklist(work, worklist)
    fragments, errors = load_fragments(work, worklist, fragments_path)
    return {'ok': not errors,
            'chunks': [{'id': item['id'],
                        'status': 'validated' if item['id'] in fragments else 'pending'}
                       for item in worklist['chunks']],
            'errors': errors}


def merge_fragments(work, worklist, fragments_path):
    prepared = validate_worklist(work, worklist)
    fragments, errors = load_fragments(work, worklist, fragments_path)
    if errors:
        raise ValueError('Invalid fragments: ' + ' | '.join(errors))
    missing = [chunk['id'] for chunk in worklist['chunks'] if chunk['id'] not in fragments]
    if missing:
        raise ValueError('Missing validated fragments: ' + ', '.join(missing))
    starter = read_json(work / 'annotations.json')
    result = {key: value for key, value in starter.items() if key in (
        'version', 'source_sha256', 'title', 'language', 'lexicon', 'sentences',
        'excluded', 'unselectable_pages', 'review', 'scope', 'page_labels', 'toc', 'math')}
    result['version'] = 2
    result['source_sha256'] = prepared['source']['sha256']
    result['scope'] = prepared['scope']
    result['sentences'] = []
    result['excluded'] = []
    result['lexicon'] = {}
    result['math'] = {}
    result['toc'] = []
    labels = {}
    empty_page_dispositions = {}
    chosen_title = None
    chosen_language = None
    for chunk in worklist['chunks']:
        part = fragments[chunk['id']]
        for key, value in part.get('lexicon', {}).items():
            if key in result['lexicon'] and result['lexicon'][key] != value:
                raise ValueError(f'Conflicting lexicon key {key!r}')
            result['lexicon'][key] = value
        for key, value in part.get('math', {}).items():
            if key in result['math'] and result['math'][key] != value:
                raise ValueError(f'Conflicting math key {key!r}')
            result['math'][key] = value
        result['sentences'].extend(part.get('sentences', []))
        result['excluded'].extend(part.get('excluded', []))
        for item in part.get('unselectable_pages', []):
            page = item.get('page')
            if page in empty_page_dispositions and empty_page_dispositions[page] != item:
                raise ValueError(f'Conflicting unselectable page disposition for page {page}')
            empty_page_dispositions[page] = item
        for label_page, value in part.get('page_labels', {}).items():
            if label_page in labels and labels[label_page] != value:
                raise ValueError(f'Conflicting page label for page {label_page}')
            labels[label_page] = value
        for item in part.get('toc', []):
            if item not in result['toc']:
                result['toc'].append(item)
        for field in ('title', 'language'):
            current = chosen_title if field == 'title' else chosen_language
            if part.get(field) and current and part[field] != current:
                raise ValueError(f'Conflicting annotation {field}')
            if part.get(field):
                if field == 'title':
                    chosen_title = part[field]
                else:
                    chosen_language = part[field]
    if chosen_title:
        result['title'] = chosen_title
    if chosen_language:
        result['language'] = chosen_language
    result['unselectable_pages'] = [empty_page_dispositions[number]
                                    for number in sorted(empty_page_dispositions)]
    page_numbers = [str(page['number']) for page in prepared['pages']]
    if set(labels) != set(page_numbers):
        raise ValueError('Fragments must provide one printed page label per selected page')
    result['page_labels'] = {page: labels[page] for page in page_numbers}
    result['review'] = {'language': False, 'layout': False, 'coverage': False,
                        'notes': 'Parallel fragments merged; full language, layout, and coverage review is pending.'}
    complete = copy_json(result)
    complete['review'] = {'language': True, 'layout': True, 'coverage': True,
                          'notes': 'Temporary structural validation only; review remains pending.'}
    with tempfile.TemporaryDirectory() as directory:
        path = Path(directory) / 'merged.json'
        path.write_text(json.dumps(complete, ensure_ascii=False), encoding='utf-8')
        _, _, report = validate(work, path)
    if report['errors']:
        raise ValueError('Merged annotation failed full structural validation: ' + '; '.join(report['errors'][:12]))
    return result


def copy_json(value):
    return json.loads(json.dumps(value, ensure_ascii=False))


def write_json_atomic(path, value):
    path = Path(path).resolve()
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, temporary = tempfile.mkstemp(prefix='.workflow-', suffix='.json', dir=path.parent)
    try:
        with os.fdopen(fd, 'w', encoding='utf-8') as stream:
            json.dump(value, stream, ensure_ascii=False, indent=2)
            stream.write('\n')
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, path)
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest='command', required=True)
    p = sub.add_parser('create-worklist')
    p.add_argument('--work', required=True, type=Path); p.add_argument('--plan', required=True, type=Path); p.add_argument('--output', required=True, type=Path)
    p = sub.add_parser('validate-plan')
    p.add_argument('--work', required=True, type=Path); p.add_argument('--worklist', required=True, type=Path)
    p = sub.add_parser('status')
    p.add_argument('--work', required=True, type=Path); p.add_argument('--worklist', required=True, type=Path); p.add_argument('--fragments', required=True, type=Path)
    p = sub.add_parser('merge')
    p.add_argument('--work', required=True, type=Path); p.add_argument('--worklist', required=True, type=Path); p.add_argument('--fragments', required=True, type=Path); p.add_argument('--output', required=True, type=Path)
    args = parser.parse_args(argv)
    try:
        if args.command == 'create-worklist':
            value = make_worklist(args.work, read_json(args.plan))
            protected = {(args.work / name).resolve()
                         for name in ('source.pdf', 'prepared.json', 'manifest.json')}
            protected.add(args.plan.resolve())
            if args.output.resolve() in protected:
                raise ValueError('Worklist output must not replace its plan or prepared source artifacts')
            write_json_atomic(args.output, value)
            report = {'ok': True, 'worklist_sha256': worklist_hash(value), 'chunks': len(value['chunks'])}
        elif args.command == 'validate-plan':
            value = read_json(args.worklist); validate_worklist(args.work, value)
            report = {'ok': True, 'worklist_sha256': worklist_hash(value), 'chunks': len(value['chunks'])}
        elif args.command == 'status':
            report = status(args.work, read_json(args.worklist), args.fragments)
        else:
            value = merge_fragments(args.work, read_json(args.worklist), args.fragments)
            protected = {(args.work / name).resolve() for name in ('source.pdf', 'prepared.json', 'manifest.json', 'anomalies.json', 'glyphs.json')}
            protected.add(args.worklist.resolve())
            protected.update((args.work / page['svg']).resolve() for page in read_json(args.work / 'prepared.json')['pages'])
            if args.output.resolve() in protected:
                raise ValueError('Output must not replace source, prepared, manifest, worklist, or page artifacts')
            write_json_atomic(args.output, value)
            report = {'ok': True, 'output': str(args.output), 'sentences': len(value['sentences'])}
    except (OSError, ValueError, KeyError, TypeError, AttributeError) as error:
        report = {'ok': False, 'errors': [str(error)]}
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0 if report['ok'] else 1


if __name__ == '__main__':
    sys.exit(main())
