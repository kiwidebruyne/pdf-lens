#!/usr/bin/env python3
"""Local original-page preview and atomic, sentence-complete publication."""
import argparse
import base64
import copy
from contextlib import contextmanager
from datetime import datetime, timezone
import hashlib
import html
from http.server import BaseHTTPRequestHandler, HTTPServer
import json
import os
from pathlib import Path
import re
import sys
import tempfile
import time
from urllib.parse import parse_qs, urlsplit
import uuid

import paper_reader as reader
import workflow


def atomic_json(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temporary = tempfile.mkstemp(prefix='.' + path.name + '-', dir=path.parent)
    try:
        with os.fdopen(descriptor, 'w', encoding='utf-8') as stream:
            json.dump(value, stream, ensure_ascii=False, indent=2, allow_nan=False)
            stream.write('\n')
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, path)
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)


def fragment_name(chunk_id):
    # Chunk IDs are data, never filesystem paths.
    return 'chunk-' + hashlib.sha256(chunk_id.encode('utf-8')).hexdigest()[:24] + '.json'


@contextmanager
def publication_lock(fragments):
    fragments.mkdir(parents=True, exist_ok=True)
    lock = fragments / '.publish-lock'
    deadline = time.monotonic() + 10
    while True:
        try:
            lock.mkdir()
            break
        except FileExistsError:
            if time.monotonic() >= deadline:
                raise ValueError('Publication is locked; inspect an interrupted publisher before retrying')
            time.sleep(0.05)
    try:
        yield
    finally:
        lock.rmdir()


def validate_partial(work, worklist, fragment, chunk_id):
    prepared = workflow.validate_worklist(work, worklist)
    chunks = {c['id']: c for c in worklist['chunks']}
    if chunk_id not in chunks:
        raise ValueError('Unknown chunk: ' + str(chunk_id))
    chunk = chunks[chunk_id]
    expected = {'chunk_id': chunk_id, 'worklist_sha256': workflow.worklist_hash(worklist),
                'owned_tokens': chunk['owned_tokens'], 'context_tokens': chunk['context_tokens']}
    if fragment.get('_chunk') != expected:
        raise ValueError('Fragment ownership metadata does not match worklist')
    if fragment.get('version') != 3:
        raise ValueError('Live publication requires v3 annotations')
    assigned = workflow.assignments(fragment)
    if len(set(assigned)) != len(assigned):
        raise ValueError('Duplicate token assignments')
    if not set(assigned) <= set(chunk['owned_tokens']):
        raise ValueError('Token outside chunk ownership')
    review = fragment.get('review', {})
    if not (review.get('language') is True and review.get('layout') is True and
            isinstance(review.get('notes'), str) and review['notes'].strip()):
        raise ValueError('Published sentences require actual author language/layout checks and notes')
    source = {key: copy.deepcopy(value) for key, value in fragment.items() if key != '_chunk'}
    source['page_labels'] = {str(p['number']): source.get('page_labels', {}).get(str(p['number']), str(p['number']))
                             for p in prepared['pages']}
    # Unlock the existing structural validator, without promoting the fragment's
    # actual whole-chunk coverage/review status.
    source['review'] = {'language': True, 'layout': True, 'coverage': True,
                        'notes': 'Structural partial-publication check only.'}
    with tempfile.TemporaryDirectory() as temporary:
        path = Path(temporary) / 'annotation.json'
        reader.write_json(path, source)
        _, _, report = reader.validate(work, path)
    errors = []
    for error in report['errors']:
        if 'source tokens unassigned:' in error or error.startswith('All zero-token pages need'):
            continue
        anomaly = re.match(r'^(p\d+t\d+): unusual extracted glyph', error)
        if anomaly and anomaly.group(1) not in assigned:
            continue
        errors.append(error)
    if errors:
        raise ValueError('Partial structural validation failed: ' + '; '.join(errors[:10]))
    return chunk


def combine(worklist, fragments):
    sentences, math, exclusions, labels, toc = [], {}, [], {}, []
    ids, tokens = set(), set()
    title = None
    for chunk in worklist['chunks']:
        part = fragments.get(chunk['id'])
        if part is None:
            continue
        for sentence in part['sentences']:
            if sentence['id'] in ids:
                raise ValueError('Duplicate sentence ID across chunks: ' + sentence['id'])
            ids.add(sentence['id'])
            sentences.append(sentence)
        assigned = set(workflow.assignments(part))
        if tokens & assigned:
            raise ValueError('Overlapping published token ownership')
        tokens.update(assigned)
        for ref, item in part.get('math', {}).items():
            if ref in math:
                raise ValueError('Duplicate math reference across chunks: ' + ref)
            math[ref] = item
        exclusions.extend(t for item in part.get('excluded', []) for t in item['tokens'])
        for number, label in part.get('page_labels', {}).items():
            if number in labels and labels[number] != label:
                raise ValueError('Conflicting page labels')
            labels[number] = label
        for item in part.get('toc', []):
            if item not in toc:
                toc.append(item)
        if title is not None and part['title'] != title:
            raise ValueError('Conflicting document titles')
        title = part['title']
    return {'sentences': sentences, 'math': math, 'excluded_tokens': exclusions,
            'page_labels': labels, 'toc': toc, 'title': title,
            'processed_tokens': len(tokens)}


def candidates_from_disk(work, worklist, fragments):
    result = {}
    for path in sorted(fragments.glob('*.json')):
        try:
            part = reader.read_json(path)
            chunk_id = part.get('_chunk', {}).get('chunk_id')
            validate_partial(work, worklist, part, chunk_id)
        except (ValueError, KeyError, TypeError, AttributeError):
            saved = fragments / '.live-accepted' / path.name
            if not saved.is_file():
                raise
            part = reader.read_json(saved)
            chunk_id = part.get('_chunk', {}).get('chunk_id')
            validate_partial(work, worklist, part, chunk_id)
        if chunk_id in result:
            raise ValueError('Multiple fragment files for chunk ' + str(chunk_id))
        result[chunk_id] = part
    return result


def publish(work, worklist_path, fragments, chunk_id, input_path):
    work, fragments = work.resolve(), fragments.resolve()
    part = reader.read_json(input_path)
    worklist = reader.read_json(worklist_path)
    try:
        chunk = validate_partial(work, worklist, part, chunk_id)
    except (KeyError, TypeError, AttributeError) as error:
        raise ValueError('Malformed partial annotation: ' + str(error)) from error
    path = fragments / fragment_name(chunk_id)
    with publication_lock(fragments):
        existing = candidates_from_disk(work, worklist, fragments)
        previous = existing.get(chunk_id)
        if previous is not None and not set(workflow.assignments(previous)) <= set(workflow.assignments(part)):
            raise ValueError('Cumulative publication must retain previously assigned source tokens')
        existing[chunk_id] = part
        combine(worklist, existing)
        changed = previous is None or workflow.canonical_hash(previous) != workflow.canonical_hash(part)
        try:
            disk_matches = workflow.canonical_hash(reader.read_json(path)) == workflow.canonical_hash(part)
        except (OSError, ValueError):
            disk_matches = False
        if changed or not disk_matches:
            atomic_json(path, part)
    return {'ok': True, 'changed': changed, 'path': str(path),
            'ready_sentences': len(part['sentences']),
            'chunk_complete': set(workflow.assignments(part)) == set(chunk['owned_tokens'])}


class LiveDocument:
    def __init__(self, work, worklist_path, fragments):
        self.work, self.worklist_path, self.fragments = work.resolve(), worklist_path.resolve(), fragments.resolve()
        self.prepared = reader.read_json(self.work / 'prepared.json')
        reader.verify_manifest(self.work, self.prepared)
        self.total = len(reader.prepared_tokens(self.work, self.prepared))
        self.accepted_dir = self.fragments / '.live-accepted'
        self.epoch = uuid.uuid4().hex
        self.revision = 0
        self.accepted = {}
        self.signatures = {}
        self.path_chunks = {}
        self.rejected = {}
        self.worklist = None
        self.worklist_identity = None
        self.payload = {'sentences': [], 'math': {}, 'excluded_tokens': [], 'page_labels': {},
                        'toc': [], 'title': None, 'processed_tokens': 0}
        self.history = {}
        self.last_update = None
        self.errors = []
        self.final_path = None
        self.final_attempt = None
        self.final_error = None

    def _accept(self, part):
        chunk_id = part.get('_chunk', {}).get('chunk_id')
        validate_partial(self.work, self.worklist, part, chunk_id)
        previous = self.accepted.get(chunk_id)
        if previous and not set(workflow.assignments(previous)) <= set(workflow.assignments(part)):
            raise ValueError('Cumulative fragment lost previously published tokens')
        proposed = dict(self.accepted)
        proposed[chunk_id] = part
        combine(self.worklist, proposed)
        self.accepted = proposed
        return chunk_id

    def refresh(self):
        errors = []
        if self.worklist_path.exists():
            try:
                worklist = reader.read_json(self.worklist_path)
                identity = workflow.worklist_hash(worklist)
                if self.worklist is None:
                    workflow.validate_worklist(self.work, worklist)
                    self.worklist, self.worklist_identity = worklist, identity
                    for path in sorted(self.accepted_dir.glob('*.json')):
                        try:
                            self._accept(reader.read_json(path))
                        except (OSError, ValueError, KeyError, TypeError, AttributeError) as error:
                            errors.append('Saved publication: ' + str(error))
                elif identity != self.worklist_identity:
                    raise ValueError('Live worklist changed; keep the original or start a separate job')
            except (OSError, ValueError, KeyError, TypeError, AttributeError) as error:
                self.errors = [str(error)]
                return
        if self.worklist is None:
            self.errors = []
            return
        seen_chunks = set()
        for path in sorted(self.fragments.glob('*.json')):
            signature = None
            try:
                stat = path.stat()
                signature = (stat.st_mtime_ns, stat.st_size)
                if self.signatures.get(path) == signature:
                    continue
                if self.rejected.get(path, (None, None))[0] == signature:
                    errors.append(self.rejected[path][1])
                    continue
                part = reader.read_json(path)
                chunk_id = part.get('_chunk', {}).get('chunk_id')
                if chunk_id in seen_chunks or any(other != path and other.exists() and owner == chunk_id
                                                   for other, owner in self.path_chunks.items()):
                    raise ValueError('Multiple files for the same chunk')
                seen_chunks.add(chunk_id)
                self._accept(part)
                atomic_json(self.accepted_dir / fragment_name(chunk_id), part)
                self.signatures[path] = signature
                self.path_chunks[path] = chunk_id
                self.rejected.pop(path, None)
            except (OSError, ValueError, KeyError, TypeError, AttributeError) as error:
                message = str(path.name) + ': ' + str(error)
                errors.append(message)
                if signature is not None:
                    self.rejected[path] = (signature, message)
        new_payload = combine(self.worklist, self.accepted)
        if workflow.canonical_hash(new_payload) != workflow.canonical_hash(self.payload):
            before = {s['id']: s for s in self.payload['sentences']}
            after = {s['id']: s for s in new_payload['sentences']}
            self.revision += 1
            self.history[self.revision] = {
                'sentences': [s for key, s in after.items() if before.get(key) != s],
                'removed_sentence_ids': [key for key in before if key not in after]}
            if len(self.history) > 200:
                del self.history[min(self.history)]
            self.last_update = datetime.now(timezone.utc).isoformat()
            self.payload = new_payload
        self.errors = errors
        identity = workflow.canonical_hash(self.accepted)
        if identity != self.final_attempt:
            self.final_path = None
            self.final_error = None
        complete = (self.payload['processed_tokens'] == self.total and
                    len(self.accepted) == len(self.worklist['chunks']) and
                    all(part.get('review', {}).get(flag) is True for part in self.accepted.values()
                        for flag in ('language', 'layout', 'coverage')))
        if complete and identity != self.final_attempt:
            self.final_attempt = identity
            try:
                merged = workflow.merge_fragments(self.work, self.worklist, self.accepted_dir)
                annotation_path = self.work / 'annotations.json'
                atomic_json(annotation_path, merged)
                output = self.work / 'reader.html'
                report = reader.build(self.work, annotation_path, output)
                if not report['ok']:
                    raise ValueError('; '.join(report['errors']))
                self.final_path = output
            except (OSError, ValueError, KeyError, TypeError, AttributeError) as error:
                self.final_error = 'Final build: ' + str(error)
        if self.final_error:
            self.errors.append(self.final_error)

    def updates(self, since=0, epoch=None):
        self.refresh()
        reset = epoch != self.epoch or since > self.revision or since < self.revision - len(self.history)
        changed = reset or since != self.revision
        if reset:
            sentences = self.payload['sentences']
            removed = []
        else:
            new, removed_ids = {}, set()
            for revision in range(since + 1, self.revision + 1):
                entry = self.history[revision]
                for key in entry['removed_sentence_ids']:
                    new.pop(key, None)
                    removed_ids.add(key)
                for sentence in entry['sentences']:
                    new[sentence['id']] = sentence
                    removed_ids.discard(sentence['id'])
            sentences, removed = list(new.values()), list(removed_ids)
        status = {'ready_sentences': len(self.payload['sentences']),
                  'processed_tokens': self.payload['processed_tokens'], 'total_tokens': self.total,
                  'last_update': self.last_update,
                  'phase': 'complete' if self.final_path else 'waiting',
                  'errors': self.errors, 'final_url': '/reader.html' if self.final_path else None,
                  'final_path': str(self.final_path) if self.final_path else None}
        result = {'epoch': self.epoch, 'revision': self.revision, 'reset': reset,
                  'sentences': sentences, 'removed_sentence_ids': removed, 'status': status}
        if changed:
            result.update({key: self.payload[key] for key in ('math', 'excluded_tokens', 'page_labels', 'toc', 'title')})
            result['order'] = [s['id'] for s in self.payload['sentences']]
        return result

    def html(self):
        update = self.updates(0)
        pages = []
        for page in self.prepared['pages']:
            page = dict(page)
            raw = reader.local_path(self.work, page.pop('svg')).read_bytes()
            page.pop('svg_sha256')
            page['printed_label'] = self.payload['page_labels'].get(str(page['number']))
            page['image'] = 'data:image/svg+xml;base64,' + base64.b64encode(raw).decode('ascii')
            pages.append(page)
        payload = {'version': 3, 'template_version': 1, 'source': self.prepared['source'],
                   'scope': self.prepared['scope'], 'title': self.payload['title'] or self.work.name,
                   'pages': pages, 'sentences': self.payload['sentences'], 'math': self.payload['math'],
                   'toc': self.payload['toc'], 'excluded_tokens': self.payload['excluded_tokens'],
                   'live': {'updates_url': '/api/updates', 'epoch': self.epoch, 'revision': self.revision,
                            'status': update['status']}}
        data = json.dumps(payload, ensure_ascii=False, separators=(',', ':'))
        for char in '<>&\u2028\u2029':
            data = data.replace(char, '\\u%04x' % ord(char))
        assets = reader.ROOT / 'assets/reader'
        template = (assets / 'index.html').read_text(encoding='utf-8')
        template = template.replace("connect-src 'none'", "connect-src 'self'")
        values = {'__READER_DATA__': data, '__READER_TITLE__': html.escape(payload['title'], quote=True),
                  '__READER_JS__': (assets / 'reader.js').read_text(encoding='utf-8'),
                  '__READER_CSS__': (assets / 'reader.css').read_text(encoding='utf-8')}
        return re.sub('|'.join(map(re.escape, values)), lambda match: values[match.group()], template)


def make_server(document, port=0):
    class Handler(BaseHTTPRequestHandler):
        def do_GET(self):
            if self.headers.get('Host') != f'127.0.0.1:{self.server.server_port}':
                self.send_error(403)
                return
            request = urlsplit(self.path)
            if request.path in ('/', '/index.html'):
                body, content_type = document.html().encode('utf-8'), 'text/html; charset=utf-8'
            elif request.path == '/api/updates':
                query = parse_qs(request.query)
                try:
                    since = int(query.get('since', ['0'])[0])
                    if since < 0:
                        raise ValueError('negative revision')
                    update = document.updates(since, query.get('epoch', [None])[0])
                    body, content_type = json.dumps(update, ensure_ascii=False).encode('utf-8'), 'application/json; charset=utf-8'
                except (ValueError, KeyError, TypeError):
                    self.send_error(400)
                    return
            elif request.path == '/reader.html' and document.final_path:
                body, content_type = document.final_path.read_bytes(), 'text/html; charset=utf-8'
            elif request.path == '/favicon.ico':
                self.send_response(204)
                self.end_headers()
                return
            else:
                self.send_error(404)
                return
            self.send_response(200)
            self.send_header('Content-Type', content_type)
            self.send_header('Content-Length', str(len(body)))
            self.send_header('Cache-Control', 'no-store')
            self.send_header('X-Content-Type-Options', 'nosniff')
            self.end_headers()
            self.wfile.write(body)

        def log_message(self, format, *args):
            pass
    return HTTPServer(('127.0.0.1', port), Handler)


def serve(work, worklist, fragments, port=0):
    document = LiveDocument(work, worklist, fragments)
    server = make_server(document, port)
    print(json.dumps({'url': f'http://127.0.0.1:{server.server_port}/', 'work': str(work)}, ensure_ascii=False), flush=True)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest='command', required=True)
    for name in ('serve', 'publish'):
        p = sub.add_parser(name)
        for option in ('work', 'worklist', 'fragments'):
            p.add_argument('--' + option, type=Path, required=True)
        if name == 'publish':
            p.add_argument('--chunk', required=True)
            p.add_argument('--input', type=Path, required=True)
    args = parser.parse_args(argv)
    if args.command == 'serve':
        serve(args.work, args.worklist, args.fragments)
    else:
        print(json.dumps(publish(args.work, args.worklist, args.fragments, args.chunk, args.input), ensure_ascii=False))
    return 0


if __name__ == '__main__':
    try:
        raise SystemExit(main())
    except (OSError, ValueError, KeyError, TypeError, AttributeError) as error:
        print('PDF Lens live: ' + str(error), file=sys.stderr)
        raise SystemExit(1)
