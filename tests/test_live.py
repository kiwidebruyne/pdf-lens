"""Observable partial publication and live-reader recovery behavior."""
import copy
import importlib.util
import json
from pathlib import Path
import sys
import tempfile
import unittest
from concurrent.futures import ThreadPoolExecutor
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'scripts'))
sys.path.insert(0, str(ROOT / 'tests'))
import paper_reader
import workflow
from make_sample import make_sample

if (ROOT / 'scripts/live_reader.py').exists():
    import live_reader
else:
    live_reader = None


class LiveTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.base = Path(self.tmp.name)
        make_sample(self.base)
        self.work = self.base / 'sample.work'
        self.annotations = paper_reader.read_json(self.work / 'annotations.json')
        self.fragments = self.work / 'fragments'
        self.worklist_path = self.work / 'worklist.json'
        chunks = []
        for name, sentences in [('first', self.annotations['sentences'][:3]),
                                ('second', self.annotations['sentences'][3:])]:
            chunks.append({'id': name, 'owned_tokens': [t for s in sentences for t in s['tokens']],
                           'context_tokens': []})
        self.worklist = workflow.make_worklist(self.work, {'chunks': chunks})
        paper_reader.write_json(self.worklist_path, self.worklist)
        self.assertIsNotNone(live_reader, 'Live publication must be implemented')

    def fragment(self, chunk, ids):
        result = copy.deepcopy(self.annotations)
        result['sentences'] = [s for s in result['sentences'] if s['id'] in ids]
        refs = {p['ref'] for s in result['sentences'] for p in s['natural'] if p['type'] == 'math'}
        result['math'] = {ref: value for ref, value in result['math'].items() if ref in refs}
        owned = next(c for c in self.worklist['chunks'] if c['id'] == chunk)
        result['_chunk'] = {'chunk_id': chunk, 'worklist_sha256': workflow.worklist_hash(self.worklist),
                            'owned_tokens': owned['owned_tokens'], 'context_tokens': []}
        return result

    def publish(self, chunk, data):
        path = self.base / (chunk + '-input.json')
        paper_reader.write_json(path, data)
        return live_reader.publish(self.work, self.worklist_path, self.fragments, chunk, path)

    def doc(self):
        return live_reader.LiveDocument(self.work, self.worklist_path, self.fragments)

    def test_one_complete_sentence_is_published_before_chunk_completion(self):
        result = self.publish('first', self.fragment('first', ['s0']))
        self.assertTrue(result['changed'])
        doc = self.doc()
        update = doc.updates(0)
        self.assertEqual([s['id'] for s in update['sentences']], ['s0'])
        self.assertEqual(update['status']['ready_sentences'], 1)
        self.assertEqual(update['status']['processed_tokens'], 3)
        self.assertIsNone(update['status']['final_path'])
        # The ordinary complete build gate must still reject partial fragments.
        with self.assertRaises(ValueError):
            workflow.merge_fragments(self.work, self.worklist, self.fragments)

    def test_same_publication_is_idempotent_and_correction_is_a_delta(self):
        part = self.fragment('first', ['s0'])
        self.publish('first', part)
        doc = self.doc()
        before = doc.updates(0)
        again = self.publish('first', part)
        self.assertFalse(again['changed'])
        unchanged = doc.updates(before['revision'], before['epoch'])
        self.assertEqual(unchanged['revision'], before['revision'])
        self.assertEqual(unchanged['sentences'], [])
        part['sentences'][0]['natural'][0]['text'] = '모형은 시스템을 설명한다.'
        self.publish('first', part)
        changed = doc.updates(before['revision'], before['epoch'])
        self.assertFalse(changed['reset'])
        self.assertEqual(len(changed['sentences']), 1)
        self.assertIn('설명한다', changed['sentences'][0]['natural'][0]['text'])
        self.assertNotIn('pages', changed)

    def test_rejected_input_preserves_last_good_result_including_restart(self):
        part = self.fragment('first', ['s0'])
        result = self.publish('first', part)
        doc = self.doc()
        doc.updates(0)
        destination = Path(result['path'])
        good = destination.read_bytes()
        for kind in ('missing-card', 'foreign-token', 'duplicate-token', 'bad-math'):
            bad = copy.deepcopy(part)
            sentence = bad['sentences'][0]
            if kind == 'missing-card':
                sentence['words'].pop(sentence['tokens'][0])
            elif kind == 'foreign-token':
                sentence['tokens'].append(self.annotations['sentences'][-1]['tokens'][0])
            elif kind == 'duplicate-token':
                sentence['tokens'].append(sentence['tokens'][0])
            else:
                sentence['natural'] = [{'type': 'math', 'ref': 'absent'}]
            with self.assertRaises(ValueError, msg=kind):
                self.publish('first', bad)
            self.assertEqual(destination.read_bytes(), good)
        destination.write_text('{ unfinished', encoding='utf-8')
        self.assertEqual(doc.updates(0)['status']['ready_sentences'], 1)
        self.assertEqual(self.doc().updates(0)['status']['ready_sentences'], 1)

    def test_preview_precedes_worklist_and_can_later_accept_publication(self):
        self.worklist_path.unlink()
        doc = self.doc()
        html = doc.html()
        self.assertIn('data:image/svg+xml;base64,', html)
        self.assertIn("connect-src 'self'", html)
        self.assertEqual(doc.updates(0)['status']['ready_sentences'], 0)
        paper_reader.write_json(self.worklist_path, self.worklist)
        self.publish('second', self.fragment('second', ['s3']))
        self.assertEqual(doc.updates(0)['status']['ready_sentences'], 1)

    def test_complete_chunks_auto_build_offline_final_with_full_coverage(self):
        self.publish('second', self.fragment('second', ['s3', 's4']))
        self.publish('first', self.fragment('first', ['s0', 's1', 's2']))
        update = self.doc().updates(0)
        self.assertEqual(update['status']['phase'], 'complete')
        final = Path(update['status']['final_path'])
        self.assertTrue(final.exists())
        html = final.read_text(encoding='utf-8')
        self.assertIn("connect-src 'none'", html)
        self.assertNotIn('"live":', html)
        report = paper_reader.validate(self.work, self.work / 'annotations.json')[2]
        self.assertTrue(report['ok'], report['errors'])

    def test_parallel_owners_and_full_but_unreviewed_coverage_do_not_finalize(self):
        first = self.fragment('first', ['s0', 's1', 's2'])
        second = self.fragment('second', ['s3', 's4'])
        second['review']['coverage'] = False
        with ThreadPoolExecutor(max_workers=2) as pool:
            results = list(pool.map(lambda item: self.publish(*item), [('first', first), ('second', second)]))
        self.assertEqual(len({result['path'] for result in results}), 2)
        doc = self.doc()
        pending = doc.updates(0)
        self.assertEqual(pending['status']['ready_sentences'], 5)
        self.assertIsNone(pending['status']['final_path'])
        second['review']['coverage'] = True
        self.publish('second', second)
        finished = doc.updates(pending['revision'], pending['epoch'])
        self.assertEqual(finished['status']['phase'], 'complete')

    def test_later_unreviewed_correction_does_not_offer_a_stale_final_html(self):
        first = self.fragment('first', ['s0', 's1', 's2'])
        second = self.fragment('second', ['s3', 's4'])
        self.publish('first', first)
        self.publish('second', second)
        doc = self.doc()
        self.assertEqual(doc.updates(0)['status']['phase'], 'complete')
        second['sentences'][-1]['natural'][0]['text'] = '결과를 살펴보자.'
        second['review']['coverage'] = False
        self.publish('second', second)
        update = doc.updates(0)
        self.assertIsNone(update['status']['final_path'])
        self.assertIsNone(update['status']['final_url'])

    def test_repair_of_malformed_owner_file_uses_the_last_accepted_snapshot(self):
        part = self.fragment('first', ['s0'])
        result = self.publish('first', part)
        self.doc().updates(0)
        Path(result['path']).write_text('{ incomplete', encoding='utf-8')
        part['sentences'][0]['natural'][0]['text'] = '모형은 시스템을 설명한다.'
        repaired = self.publish('first', part)
        self.assertTrue(repaired['changed'])
        update = self.doc().updates(0)
        self.assertIn('설명한다', update['sentences'][0]['natural'][0]['text'])

    def test_identical_last_good_publication_repairs_a_malformed_file_without_new_revision(self):
        part = self.fragment('first', ['s0'])
        result = self.publish('first', part)
        doc = self.doc()
        before = doc.updates(0)
        Path(result['path']).write_text('{ broken', encoding='utf-8')
        self.publish('first', part)
        self.assertEqual(paper_reader.read_json(Path(result['path'])), part)
        after = doc.updates(before['revision'], before['epoch'])
        self.assertEqual(after['revision'], before['revision'])
        self.assertEqual(after['status']['errors'], [])

    def test_unchanged_rejected_file_is_not_revalidated_every_poll(self):
        part = self.fragment('first', ['s0'])
        result = self.publish('first', part)
        doc = self.doc()
        doc.updates(0)
        part['sentences'][0]['words'][part['sentences'][0]['tokens'][0]]['meaning'] = ''
        paper_reader.write_json(Path(result['path']), part)
        with patch.object(live_reader, 'validate_partial', wraps=live_reader.validate_partial) as check:
            for _ in range(3):
                self.assertTrue(doc.updates(0)['status']['errors'])
            self.assertEqual(check.call_count, 1)

    def test_final_merge_is_not_attempted_while_any_chunk_is_partial(self):
        self.publish('first', self.fragment('first', ['s0']))
        self.publish('second', self.fragment('second', ['s3']))
        with patch.object(workflow, 'merge_fragments', wraps=workflow.merge_fragments) as merge:
            self.doc().updates(0)
            self.assertEqual(merge.call_count, 0)


if __name__ == '__main__':
    unittest.main()
