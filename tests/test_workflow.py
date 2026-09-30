import copy
import hashlib
import json
import sys
import subprocess
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'scripts'))
import workflow


class WorkflowTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.work = self.root / 'chapter.work'
        self.work.mkdir()
        source_bytes = b'fixture source PDF bytes'
        (self.work / 'source.pdf').write_bytes(source_bytes)
        self.prepared = {
            'version': 2,
            'source': {'name': 'source.pdf', 'sha256': hashlib.sha256(source_bytes).hexdigest()},
            'scope': {'first_page': 1, 'last_page': 2},
            'source_pages': 2, 'backend': {'name': 'pymupdf', 'version': 'fixture'},
            'processor_version': 'fixture',
            'pages': [
                {'number': 1, 'width': 100, 'height': 100, 'svg': 'page-1.svg',
                 'tokens': [{'id': 'p1t0', 'text': 'Across', 'box': [1, 1, 20, 5], 'block': 0, 'line': 0, 'chars': [{}]}]},
                {'number': 2, 'width': 100, 'height': 100, 'svg': 'page-2.svg',
                 'tokens': [{'id': 'p2t0', 'text': 'pages.', 'box': [1, 1, 20, 5], 'block': 0, 'line': 0, 'chars': [{}]}]},
            ],
        }
        for name in ('page-1.svg', 'page-2.svg'):
            (self.work / name).write_text('<svg viewBox="0 0 100 100"/>')
        for page in self.prepared['pages']:
            page['svg_sha256'] = workflow.digest(self.work / page['svg'])
        for name in ('layout.xhtml', 'pdfinfo.txt', 'inspection.txt', 'anomalies.json', 'glyphs.json'):
            (self.work / name).write_text('[]' if name.endswith('.json') else 'fixture')
        self.write(self.work / 'prepared.json', self.prepared)
        machine_files = ['source.pdf', 'prepared.json', 'pdfinfo.txt',
                         'inspection.txt', 'anomalies.json', 'glyphs.json', 'page-1.svg', 'page-2.svg']
        self.write(self.work / 'manifest.json', {
            'version': 2, 'backend': {'name': 'pymupdf', 'version': 'fixture'},
            'processor_version': 'fixture',
            'files': {name: workflow.digest(self.work / name) for name in machine_files},
        })
        self.write(self.work / 'annotations.json', {
            'version': 2, 'source_sha256': self.prepared['source']['sha256'],
            'scope': self.prepared['scope'], 'title': 'Chapter', 'language': 'en',
            'lexicon': {}, 'sentences': [], 'excluded': [], 'unselectable_pages': [],
            'review': {'language': False, 'layout': False, 'coverage': False, 'notes': ''},
            'page_labels': {}, 'toc': [], 'math': {},
        })
        self.plan = {'chunks': [
            {'id': 'a', 'owned_tokens': ['p1t0'], 'context_tokens': ['p2t0']},
            {'id': 'b', 'owned_tokens': ['p2t0'], 'context_tokens': ['p1t0']},
        ]}
        self.worklist = workflow.make_worklist(self.work, self.plan)

    def tearDown(self):
        self.tmp.cleanup()

    @staticmethod
    def write(path, value):
        path.write_text(json.dumps(value, ensure_ascii=False), encoding='utf-8')

    def fragment(self, chunk_id, ids, sentence_id=None):
        chunk = next(item for item in self.worklist['chunks'] if item['id'] == chunk_id)
        return {
            'version': 2, 'source_sha256': self.prepared['source']['sha256'],
            'scope': copy.deepcopy(self.prepared['scope']), 'title': 'Chapter', 'language': 'en',
            'page_labels': {'1': 'i', '2': 'ii'}, 'toc': [], 'math': {},
            'lexicon': {'base': {'lemma': 'word', 'pos': '명사', 'gloss': '뜻'}},
            'sentences': ([{'id': sentence_id or chunk_id, 'tokens': ids,
                            'units': [{'id': 'u-' + (sentence_id or chunk_id), 'start': 0, 'end': len(ids),
                                      'literal': [{'start': 0, 'end': len(ids),
                                                   'parts': [{'type': 'text', 'text': '직역'}]}],
                                      'natural': [{'type': 'text', 'text': '자연스러운 번역'}]}],
                            'words': {key: {'entry': 'base', 'meaning': '문맥 뜻', 'role': '주어', 'expression': ''}
                                      for key in ids}, 'joins': []}]
                          if ids else []), 'excluded': [],
            '_chunk': {'worklist_sha256': workflow.worklist_hash(self.worklist),
                       'chunk_id': chunk_id, 'owned_tokens': chunk['owned_tokens'],
                       'context_tokens': chunk['context_tokens']},
        }

    def v3_fragment(self, chunk_id, ids, sentence_id=None, meaning='뜻'):
        fragment = self.fragment(chunk_id, ids, sentence_id)
        fragment['version'] = 3
        fragment.pop('lexicon')
        for sentence in fragment['sentences']:
            sentence.pop('units')
            sentence['natural'] = [{'type': 'text', 'text': '자연스러운 번역'}]
            sentence['words'] = {key: {'base': 'word', 'meaning': meaning} for key in ids}
        return fragment

    def test_plan_rejects_unowned_duplicate_and_out_of_order_tokens(self):
        for chunks in (
            [{'id': 'a', 'owned_tokens': ['p1t0'], 'context_tokens': []}],
            [{'id': 'a', 'owned_tokens': ['p1t0', 'p2t0'], 'context_tokens': []},
             {'id': 'b', 'owned_tokens': ['p2t0'], 'context_tokens': []}],
            [{'id': 'a', 'owned_tokens': ['invented'], 'context_tokens': []}],
            [{'id': 'b', 'owned_tokens': ['p2t0'], 'context_tokens': []},
             {'id': 'a', 'owned_tokens': ['p1t0'], 'context_tokens': []}],
        ):
            with self.assertRaises(ValueError):
                workflow.make_worklist(self.work, {'chunks': chunks})

    def test_corrected_within_page_chunk_order_is_preserved(self):
        one_page = copy.deepcopy(self.prepared)
        one_page['scope'] = {'first_page': 1, 'last_page': 1}
        one_page['source_pages'] = 1
        one_page['pages'] = [copy.deepcopy(one_page['pages'][0])]
        one_page['pages'][0]['tokens'].append({
            'id': 'p1t1', 'text': 'earlier in reading order', 'box': [25, 1, 20, 5], 'block': 0, 'line': 0, 'chars': [{}]})
        self.write(self.work / 'prepared.json', one_page)
        plan = {'chunks': [
            {'id': 'first-read', 'owned_tokens': ['p1t1'], 'context_tokens': []},
            {'id': 'second-read', 'owned_tokens': ['p1t0'], 'context_tokens': []},
        ]}
        self.assertEqual([chunk['id'] for chunk in workflow.make_worklist(self.work, plan)['chunks']],
                         ['first-read', 'second-read'])

    def test_missing_duplicate_foreign_and_context_only_assignments_rejected(self):
        with self.assertRaisesRegex(ValueError, 'missing owned'):
            workflow.validate_fragment(self.work, self.worklist, self.fragment('a', []), 'a')
        with self.assertRaisesRegex(ValueError, 'duplicate assignments'):
            workflow.validate_fragment(self.work, self.worklist, self.fragment('a', ['p1t0', 'p1t0']), 'a')
        with self.assertRaisesRegex(ValueError, 'outside ownership'):
            workflow.validate_fragment(self.work, self.worklist, self.fragment('a', ['p1t0', 'p2t0']), 'a')
        with self.assertRaisesRegex(ValueError, 'outside ownership'):
            workflow.validate_fragment(self.work, self.worklist, self.fragment('a', ['p2t0']), 'a')

    def test_cross_page_chunk_and_context_overlap_are_valid(self):
        plan = {'chunks': [{'id': 'cross', 'owned_tokens': ['p1t0', 'p2t0'],
                            'context_tokens': ['p1t0']}]}
        worklist = workflow.make_worklist(self.work, plan)
        chunk = worklist['chunks'][0]
        fragment = {
            'version': 2, 'source_sha256': self.prepared['source']['sha256'], 'scope': self.prepared['scope'],
            '_chunk': {'worklist_sha256': workflow.worklist_hash(worklist), 'chunk_id': 'cross',
                       'owned_tokens': chunk['owned_tokens'], 'context_tokens': chunk['context_tokens']},
            'sentences': [{'id': 'cross-page', 'tokens': ['p1t0', 'p2t0']}], 'excluded': [],
        }
        self.assertEqual(workflow.validate_fragment(self.work, worklist, fragment, 'cross')['id'], 'cross')

    def test_fragment_anomaly_filter_uses_owned_token_ids(self):
        fragment = self.fragment('a', ['p1t0'])
        for token_id, expected_error in (('p1t1', False), ('p1t0', True)):
            self.write(self.work / 'anomalies.json', [{'token': token_id, 'codepoints': ['U+0002']}])
            manifest = json.loads((self.work / 'manifest.json').read_text())
            manifest['files']['anomalies.json'] = workflow.digest(self.work / 'anomalies.json')
            self.write(self.work / 'manifest.json', manifest)
            if expected_error:
                with self.assertRaisesRegex(ValueError, 'unusual extracted glyph'):
                    workflow.validate_fragment_structure(
                        self.work, self.prepared, fragment, self.worklist['chunks'][0])
            else:
                workflow.validate_fragment_structure(
                    self.work, self.prepared, fragment, self.worklist['chunks'][0])

    def test_check_fragment_cli_ignores_same_page_other_chunk_anomaly(self):
        prepared = copy.deepcopy(self.prepared)
        prepared['pages'][0]['tokens'].append({
            'id': 'p1t1', 'text': 'context', 'box': [25, 1, 20, 5], 'block': 0, 'line': 0, 'chars': [{}]})
        self.write(self.work / 'prepared.json', prepared)
        self.prepared = prepared
        (self.work / 'anomalies.json').write_text(json.dumps([
            {'token': 'p1t1', 'codepoints': ['U+0002'], 'glyphs': ['p1c1']}]))
        manifest = json.loads((self.work / 'manifest.json').read_text())
        manifest['files']['prepared.json'] = workflow.digest(self.work / 'prepared.json')
        manifest['files']['anomalies.json'] = workflow.digest(self.work / 'anomalies.json')
        self.write(self.work / 'manifest.json', manifest)
        self.plan = {'chunks': [
            {'id': 'a', 'owned_tokens': ['p1t0'], 'context_tokens': ['p1t1']},
            {'id': 'b', 'owned_tokens': ['p1t1', 'p2t0'], 'context_tokens': ['p1t0']},
        ]}
        self.worklist = workflow.make_worklist(self.work, self.plan)
        worklist_path = self.root / 'worklist.json'
        fragment_path = self.root / 'fragment.json'
        self.write(worklist_path, self.worklist)
        self.write(fragment_path, self.fragment('a', ['p1t0']))
        script = Path(__file__).resolve().parents[1] / 'scripts' / 'check_fragment.py'
        result = subprocess.run([
            sys.executable, str(script), '--work', str(self.work), '--fragment', str(fragment_path),
            '--worklist', str(worklist_path), '--chunk', 'a'], capture_output=True, text=True)
        self.assertEqual(result.returncode, 0, result.stderr + result.stdout)
        self.assertIn('"structural_ok_excluding_other_fragments": true', result.stdout)

    def test_prepared_identity_prevents_resume_on_changed_preparation(self):
        changed = copy.deepcopy(self.prepared)
        changed['pages'][0]['tokens'][0]['text'] = 'Changed'
        self.write(self.work / 'prepared.json', changed)
        with self.assertRaisesRegex(ValueError, 'identity mismatch'):
            workflow.validate_worklist(self.work, self.worklist)

    def test_status_and_merge_follow_worklist_order_and_review_remains_pending(self):
        fragments = self.root / 'fragments'
        fragments.mkdir()
        self.write(fragments / 'z.json', self.fragment('b', ['p2t0'], 'second'))
        self.write(fragments / 'a.json', self.fragment('a', ['p1t0'], 'first'))
        report = workflow.status(self.work, self.worklist, fragments)
        self.assertEqual([row['status'] for row in report['chunks']], ['validated', 'validated'])
        merged = workflow.merge_fragments(self.work, self.worklist, fragments)
        self.assertEqual([s['id'] for s in merged['sentences']], ['first', 'second'])
        self.assertEqual(merged['review'], {
            'language': False, 'layout': False, 'coverage': False,
            'notes': 'Parallel fragments merged; full language, layout, and coverage review is pending.'})
        self.assertEqual(merged, workflow.merge_fragments(self.work, self.worklist, fragments))

    def test_merge_rejects_conflicting_duplicate_lexicon_keys(self):
        fragments = self.root / 'conflicts'
        fragments.mkdir()
        for chunk_id, ids, gloss in (('a', ['p1t0'], 'one'), ('b', ['p2t0'], 'two')):
            fragment = self.fragment(chunk_id, ids)
            fragment['lexicon']['base']['gloss'] = gloss
            self.write(fragments / f'{chunk_id}.json', fragment)
        with self.assertRaisesRegex(ValueError, 'Conflicting lexicon key'):
            workflow.merge_fragments(self.work, self.worklist, fragments)

    def test_v3_merges_local_meanings_without_shared_lexicon(self):
        fragments = self.root / 'v3-fragments'
        fragments.mkdir()
        self.write(fragments / 'a.json', self.v3_fragment('a', ['p1t0'], meaning='가로질러'))
        self.write(fragments / 'b.json', self.v3_fragment('b', ['p2t0'], meaning='쪽'))
        merged = workflow.merge_fragments(self.work, self.worklist, fragments)
        self.assertEqual(merged['version'], 3)
        self.assertNotIn('lexicon', merged)
        self.assertEqual(merged['sentences'][0]['words']['p1t0']['meaning'], '가로질러')
        self.assertEqual(merged['sentences'][1]['words']['p2t0']['meaning'], '쪽')

    def test_v3_rejects_missing_meaning_and_bad_math_before_merge(self):
        fragments = self.root / 'v3-invalid'
        fragments.mkdir()
        valid = self.v3_fragment('b', ['p2t0'])
        self.write(fragments / 'b.json', valid)
        missing = self.v3_fragment('a', ['p1t0'])
        missing['sentences'][0]['words']['p1t0']['meaning'] = ''
        self.write(fragments / 'a.json', missing)
        with self.assertRaisesRegex(ValueError, 'meaning'):
            workflow.merge_fragments(self.work, self.worklist, fragments)
        bad_math = self.v3_fragment('a', ['p1t0'])
        bad_math['sentences'][0]['natural'] = [{'type': 'math', 'ref': 'missing'}]
        self.write(fragments / 'a.json', bad_math)
        with self.assertRaisesRegex(ValueError, 'formula references'):
            workflow.merge_fragments(self.work, self.worklist, fragments)

    def test_check_fragment_cli_reports_v3_meaning_error(self):
        worklist_path = self.root / 'worklist.json'
        fragment_path = self.root / 'fragment.json'
        self.write(worklist_path, self.worklist)
        fragment = self.v3_fragment('a', ['p1t0'])
        fragment['sentences'][0]['words']['p1t0']['meaning'] = ''
        self.write(fragment_path, fragment)
        script = Path(__file__).resolve().parents[1] / 'scripts' / 'check_fragment.py'
        result = subprocess.run([
            sys.executable, str(script), '--work', str(self.work), '--fragment', str(fragment_path),
            '--worklist', str(worklist_path), '--chunk', 'a'], capture_output=True, text=True)
        self.assertNotEqual(result.returncode, 0)
        self.assertIn('meaning', result.stdout)

    def test_v3_starter_and_missing_starter_do_not_block_fragment_check_or_merge(self):
        starter_path = self.work / 'annotations.json'
        starter = json.loads(starter_path.read_text(encoding='utf-8'))
        starter['version'] = 3
        starter.pop('lexicon')
        self.write(starter_path, starter)
        worklist_path = self.root / 'worklist.json'
        fragment_path = self.root / 'fragment.json'
        self.write(worklist_path, self.worklist)
        self.write(fragment_path, self.v3_fragment('a', ['p1t0']))
        script = Path(__file__).resolve().parents[1] / 'scripts' / 'check_fragment.py'
        command = [sys.executable, str(script), '--work', str(self.work),
                   '--fragment', str(fragment_path), '--worklist', str(worklist_path), '--chunk', 'a']
        result = subprocess.run(command, capture_output=True, text=True)
        self.assertEqual(result.returncode, 0, result.stderr + result.stdout)
        starter_path.unlink()
        result = subprocess.run(command, capture_output=True, text=True)
        self.assertEqual(result.returncode, 0, result.stderr + result.stdout)
        fragments = self.root / 'v3-no-starter'
        fragments.mkdir()
        self.write(fragments / 'a.json', self.v3_fragment('a', ['p1t0']))
        self.write(fragments / 'b.json', self.v3_fragment('b', ['p2t0']))
        self.assertEqual(workflow.merge_fragments(self.work, self.worklist, fragments)['version'], 3)

    def test_v3_merge_preserves_complete_writer_review(self):
        fragments = self.root / 'reviewed-v3'
        fragments.mkdir()
        for chunk_id, token in (('a', 'p1t0'), ('b', 'p2t0')):
            fragment = self.v3_fragment(chunk_id, [token])
            fragment['review'] = {'language': True, 'layout': True, 'coverage': True,
                                  'notes': f'{chunk_id}: checked source tokens and page layout'}
            self.write(fragments / f'{chunk_id}.json', fragment)
        merged = workflow.merge_fragments(self.work, self.worklist, fragments)
        self.assertEqual(merged['review']['language'], True)
        self.assertEqual(merged['review']['layout'], True)
        self.assertEqual(merged['review']['coverage'], True)
        self.assertIn('a: checked source tokens', merged['review']['notes'])
        self.assertIn('b: checked source tokens', merged['review']['notes'])
        _, _, report = workflow.validate(self.work, self.write_and_return(self.root / 'merged.json', merged))
        self.assertFalse(report['errors'], report['errors'])

    def test_v3_merge_keeps_incomplete_writer_review_pending(self):
        fragments = self.root / 'pending-v3'
        fragments.mkdir()
        first = self.v3_fragment('a', ['p1t0'])
        first['review'] = {'language': True, 'layout': True, 'coverage': True,
                           'notes': 'a: checked source tokens'}
        second = self.v3_fragment('b', ['p2t0'])
        second['review'] = {'language': True, 'layout': True, 'coverage': True, 'notes': ''}
        self.write(fragments / 'a.json', first)
        self.write(fragments / 'b.json', second)
        merged = workflow.merge_fragments(self.work, self.worklist, fragments)
        self.assertFalse(merged['review']['language'])
        self.assertFalse(merged['review']['layout'])
        self.assertFalse(merged['review']['coverage'])
        self.assertIn('pending', merged['review']['notes'])

    def test_v3_merge_aggregates_each_review_flag(self):
        fragments = self.root / 'mixed-v3-review'
        fragments.mkdir()
        first = self.v3_fragment('a', ['p1t0'])
        first['review'] = {'language': True, 'layout': True, 'coverage': True,
                           'notes': 'Checked first source span'}
        second = self.v3_fragment('b', ['p2t0'])
        second['review'] = {'language': True, 'layout': False, 'coverage': True,
                            'notes': 'Checked second source span; layout pending'}
        self.write(fragments / 'a.json', first)
        self.write(fragments / 'b.json', second)
        merged = workflow.merge_fragments(self.work, self.worklist, fragments)
        self.assertTrue(merged['review']['language'])
        self.assertFalse(merged['review']['layout'])
        self.assertTrue(merged['review']['coverage'])

    @classmethod
    def write_and_return(cls, path, value):
        cls.write(path, value)
        return path

    def test_merge_runs_full_validation_across_chunk_boundaries(self):
        fragments = self.root / 'duplicate-sentences'
        fragments.mkdir()
        self.write(fragments / 'a.json', self.fragment('a', ['p1t0'], 'reused'))
        self.write(fragments / 'b.json', self.fragment('b', ['p2t0'], 'reused'))
        with self.assertRaisesRegex(ValueError, 'full structural validation'):
            workflow.merge_fragments(self.work, self.worklist, fragments)

    def test_merge_runs_full_validation_across_chunk_boundaries(self):
        fragments = self.root / 'duplicate-sentences'
        fragments.mkdir()
        self.write(fragments / 'a.json', self.fragment('a', ['p1t0'], 'reused'))
        self.write(fragments / 'b.json', self.fragment('b', ['p2t0'], 'reused'))
        with self.assertRaisesRegex(ValueError, 'full structural validation'):
            workflow.merge_fragments(self.work, self.worklist, fragments)


if __name__ == '__main__':
    unittest.main()
