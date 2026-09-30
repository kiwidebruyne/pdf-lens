"""Behavioral checks for the simplified annotation format."""
import importlib.util
import json
import tempfile
import unittest
from pathlib import Path

import pymupdf

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location('paper_reader', ROOT / 'scripts/paper_reader.py')
reader = importlib.util.module_from_spec(spec)
spec.loader.exec_module(reader)


class V3Tests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.base = Path(self.tmp.name)
        self.pdf = self.base / 'paper.pdf'
        document = pymupdf.open()
        page = document.new_page(width=400, height=600)
        page.insert_text((60, 150), 'Clear evidence supports this model.')
        document.save(self.pdf)
        document.close()
        self.work = self.base / 'work'
        reader.prepare(self.pdf, self.work)
        self.prepared = reader.read_json(self.work / 'prepared.json')
        self.ids = [t['id'] for p in self.prepared['pages'] for t in p['tokens']]

    def annotation(self):
        result = reader.read_json(self.work / 'annotations.json')
        result['page_labels'] = {'1': '1'}
        result['sentences'] = [{'id': 's1', 'tokens': self.ids,
                                'natural': [{'type': 'text', 'text': '분명한 증거가 이 모형을 뒷받침한다.'}],
                                'words': {key: {'base': '기본 뜻', 'meaning': '문맥 뜻'} for key in self.ids},
                                'joins': []}]
        result['review'] = {'language': True, 'layout': True, 'coverage': True, 'notes': 'Checked the page.'}
        return result

    def validate(self, data):
        path = self.base / 'annotations.json'
        reader.write_json(path, data)
        return reader.validate(self.work, path)[2]

    def test_prepare_starts_v3_annotations_over_v2_source(self):
        starter = reader.read_json(self.work / 'annotations.json')
        self.assertEqual(self.prepared['version'], 2)
        self.assertEqual(starter['version'], 3)
        self.assertNotIn('lexicon', starter)

    def test_smallest_complete_v3_build_and_required_meanings(self):
        annotation = self.annotation()
        report = self.validate(annotation)
        self.assertTrue(report['ok'], report['errors'])
        output = self.base / 'reader.html'
        report = reader.build(self.work, self.base / 'annotations.json', output)
        self.assertTrue(report['ok'], report['errors'])
        import re
        payload = json.loads(re.search(r'<script id="reader-data" type="application/json">(.*?)</script>', output.read_text(), re.S).group(1))
        self.assertEqual(payload['version'], 3)
        self.assertEqual(payload['sentences'][0]['natural'], annotation['sentences'][0]['natural'])
        self.assertNotIn('lexicon', payload)
        annotation['sentences'][0]['words'][self.ids[0]]['meaning'] = ''
        self.assertFalse(self.validate(annotation)['ok'])

    def test_explicit_v2_conversion_preserves_content(self):
        legacy = self.annotation()
        legacy['version'] = 2
        legacy['lexicon'] = {'x': {'lemma': 'evidence', 'pos': 'noun', 'gloss': '증거'}}
        sentence = legacy['sentences'][0]
        sentence['words'] = {key: {'entry': 'x', 'meaning': '근거', 'role': '역할', 'expression': ''} for key in self.ids}
        sentence['units'] = [{'id': 'u1', 'start': 0, 'end': len(self.ids), 'natural': sentence.pop('natural'),
                              'literal': [{'start': 0, 'end': len(self.ids), 'parts': [{'type': 'text', 'text': '직역'}]}]}]
        converted = reader.convert_annotations_v3(legacy)
        self.assertEqual(converted['version'], 3)
        self.assertEqual(converted['sentences'][0]['natural'], sentence['units'][0]['natural'])
        self.assertEqual(converted['sentences'][0]['words'][self.ids[0]], {'base': '증거', 'meaning': '근거'})
        self.assertNotIn('units', converted['sentences'][0])
        self.assertNotIn('lexicon', converted)
        self.assertTrue(self.validate(converted)['ok'])

    def test_legacy_v2_build_emits_reader_v3_payload(self):
        legacy = self.annotation()
        legacy['version'] = 2
        legacy['lexicon'] = {'e': {'lemma': 'evidence', 'pos': 'noun', 'gloss': '증거'}}
        sentence = legacy['sentences'][0]
        natural = sentence.pop('natural')
        sentence['units'] = [{'id': 'whole', 'start': 0, 'end': len(self.ids),
                              'natural': natural,
                              'literal': [{'start': 0, 'end': len(self.ids),
                                           'parts': [{'type': 'text', 'text': '직역'}]}]}]
        sentence['words'] = {key: {'entry': 'e', 'meaning': '근거', 'role': '역할', 'expression': ''}
                             for key in self.ids}
        path = self.base / 'legacy.json'
        reader.write_json(path, legacy)
        output = self.base / 'legacy.html'
        report = reader.build(self.work, path, output)
        self.assertTrue(report['ok'], report['errors'])
        import re
        payload = json.loads(re.search(r'<script id="reader-data" type="application/json">(.*?)</script>', output.read_text(), re.S).group(1))
        self.assertEqual(payload['version'], 3)
        self.assertEqual(payload['sentences'][0]['natural'], natural)
        self.assertEqual(payload['sentences'][0]['words'][self.ids[0]], {'base': '증거', 'meaning': '근거'})
        self.assertNotIn('units', payload['sentences'][0])
        self.assertNotIn('lexicon', payload)

    def test_math_reference_and_crop_are_checked_in_v3(self):
        annotation = self.annotation()
        key = self.ids[0]
        token = self.prepared['pages'][0]['tokens'][0]
        annotation['math'] = {'m1': {'tokens': [key], 'regions': [{'page': 1, 'box': token['box']}]}}
        annotation['sentences'][0]['words'].pop(key)
        annotation['sentences'][0]['natural'] = [{'type': 'math', 'ref': 'm1'},
                                                 {'type': 'text', 'text': '이 모형을 뒷받침한다.'}]
        self.assertTrue(self.validate(annotation)['ok'])
        annotation['sentences'][0]['natural'].pop(0)
        self.assertIn('math', ' '.join(self.validate(annotation)['errors']))
        annotation['sentences'][0]['natural'].insert(0, {'type': 'math', 'ref': 'm1'})
        annotation['math']['m1']['regions'][0]['box'] = [-1, 0, 1, 1]
        self.assertIn('outside page', ' '.join(self.validate(annotation)['errors']))


if __name__ == '__main__':
    unittest.main()
