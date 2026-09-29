"""PyMuPDF v2 extraction, validation, and safe-output tests."""
import hashlib
import json
import re
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

from reportlab.pdfgen.canvas import Canvas
from pypdf import PdfReader, PdfWriter

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / 'scripts/paper_reader.py'


class PipelineTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.base = Path(self.tmp.name)
        self.pdf = self.base / 'paper.pdf'
        self.work = self.base / 'work'
        self.make_pdf(1)

    def tearDown(self):
        self.tmp.cleanup()

    def make_pdf(self, pages):
        canvas = Canvas(str(self.pdf), pagesize=(400, 600))
        canvas.setFont('Helvetica', 9)
        for number in range(1, pages + 1):
            canvas.drawString(60, 450, f'Page {number} explains evidence with clear assumptions and useful predictions.')
            if number < pages:
                canvas.showPage()
        canvas.save()

    def cli(self, *args):
        return subprocess.run([sys.executable, str(SCRIPT), *map(str, args)], capture_output=True, text=True, encoding="utf-8")

    def prepare(self, *extra):
        result = self.cli('prepare', self.pdf, '--work', self.work, *extra)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        return json.loads((self.work / 'prepared.json').read_text(encoding="utf-8"))

    def complete(self, prepared):
        ids = [token['id'] for page in prepared['pages'] for token in page['tokens']]
        n = len(ids)
        sentence = {
            'id': 's1', 'tokens': ids,
            'units': [{'id': 'whole', 'start': 0, 'end': n,
                       'literal': [{'start': 0, 'end': n,
                                   'parts': [{'type': 'text', 'text': '문장 전체 직역'}]}],
                       'natural': [{'type': 'text', 'text': '문장 전체 의역'}]}],
            'words': {key: {'entry': 'word', 'meaning': '문맥 뜻', 'role': '문장 안 역할', 'expression': ''}
                      for key in ids},
            'joins': []}
        annotation = {
            'version': 2, 'source_sha256': prepared['source']['sha256'], 'scope': prepared['scope'],
            'title': 'A paper title', 'language': 'en',
            'lexicon': {'word': {'lemma': 'word', 'pos': '명사', 'gloss': '단어'}},
            'sentences': [sentence], 'excluded': [],
            'unselectable_pages': [],
            'page_labels': {str(page['number']): str(page['number']) for page in prepared['pages']},
            'toc': [], 'math': {},
            'review': {'language': True, 'layout': True, 'coverage': True, 'notes': 'Visually reviewed fixture.'}}
        path = self.base / 'annotations.json'
        path.write_text(json.dumps(annotation, ensure_ascii=False), encoding="utf-8")
        return annotation, path

    def test_prepare_defaults_to_full_v2_with_stable_ids_and_provenance(self):
        prepared = self.prepare()
        self.assertEqual(prepared['version'], 2)
        self.assertEqual(prepared['scope'], {'first_page': 1, 'last_page': 1})
        self.assertEqual(prepared['source']['sha256'], hashlib.sha256(self.pdf.read_bytes()).hexdigest())
        self.assertEqual(prepared['backend']['name'], 'pymupdf')
        self.assertTrue(prepared['processor_version'])
        token = prepared['pages'][0]['tokens'][0]
        self.assertEqual(token['id'], 'p1t0')
        self.assertEqual(token['text'], 'Page')
        self.assertTrue(token['chars'])
        self.assertTrue((self.work / 'glyphs.json').is_file())
        self.assertTrue((self.work / 'anomalies.json').is_file())
        self.assertTrue((self.work / 'page-1.svg').read_text(encoding="utf-8").find('<path') >= 0)
        self.assertNotEqual(self.cli('validate', '--work', self.work, '--annotations', self.work / 'annotations.json').returncode, 0)

    def test_selected_pages_preserve_physical_page_numbers(self):
        self.make_pdf(4)
        prepared = self.prepare('--pages', '2-3')
        self.assertEqual(prepared['scope'], {'first_page': 2, 'last_page': 3})
        self.assertEqual([p['number'] for p in prepared['pages']], [2, 3])
        self.assertEqual(prepared['pages'][0]['tokens'][0]['id'], 'p2t0')
        self.assertEqual(json.loads((self.work / 'annotations.json').read_text(encoding="utf-8"))['scope'], prepared['scope'])
        for value in ('0-2', '3-2', '2-9', '2', 'x-y'):
            bad = self.cli('prepare', self.pdf, '--work', self.base / f'bad-{value}', '--pages', value)
            self.assertNotEqual(bad.returncode, 0, bad.stdout)

    def test_resume_verifies_artifacts_and_keeps_annotations(self):
        self.prepare()
        annotations = self.work / 'annotations.json'
        annotations.write_text('keep', encoding="utf-8")
        result = self.cli('prepare', self.pdf, '--work', self.work)
        self.assertEqual(result.returncode, 0, result.stdout)
        self.assertIn('"resumed": true', result.stdout)
        self.assertEqual(annotations.read_text(encoding="utf-8"), 'keep')
        (self.work / 'page-1.svg').write_text('<svg/>', encoding="utf-8")
        rejected = self.cli('prepare', self.pdf, '--work', self.work)
        self.assertNotEqual(rejected.returncode, 0)
        self.assertIn('integrity mismatch', rejected.stdout)

    def test_resume_rejects_changed_source_and_range(self):
        self.make_pdf(3)
        self.prepare('--pages', '1-2')
        changed_range = self.cli('prepare', self.pdf, '--work', self.work, '--pages', '1-3')
        self.assertNotEqual(changed_range.returncode, 0)
        self.pdf.write_bytes(b'changed source')
        changed_source = self.cli('prepare', self.pdf, '--work', self.work, '--pages', '1-2')
        self.assertNotEqual(changed_source.returncode, 0)

    def test_cropbox_and_all_rotations_keep_tokens_in_svg_coordinates(self):
        original = self.pdf
        original_box = None
        for rotation in (0, 90, 180, 270):
            reader = PdfReader(original)
            page = reader.pages[0]
            page.cropbox.lower_left = (50, 100)
            page.cropbox.upper_right = (350, 500)
            page.rotate(rotation)
            writer = PdfWriter()
            writer.add_page(page)
            self.pdf = self.base / f'rot-{rotation}.pdf'
            writer.write(self.pdf)
            self.work = self.base / f'work-{rotation}'
            prepared = self.prepare()
            page_data = prepared['pages'][0]
            box = page_data['tokens'][0]['box']
            if rotation == 0:
                original_box = box
            x, y, w, h = original_box
            expected = {0: [x, y, w, h], 90: [400-y-h, x, h, w],
                        180: [300-x-w, 400-y-h, w, h], 270: [y, 300-x-w, h, w]}[rotation]
            for actual, target in zip(box, expected):
                self.assertAlmostEqual(actual, target, places=2)
            self.assertLessEqual(box[0] + box[2], page_data['width'] + 1)
            self.assertLessEqual(box[1] + box[3], page_data['height'] + 1)

    def test_anomaly_blocks_validation_until_reviewed_as_math_or_nonlinguistic(self):
        prepared = self.prepare()
        annotation, path = self.complete(prepared)
        token = prepared['pages'][0]['tokens'][0]
        anomaly = {'token': token['id'], 'codepoints': ['U+FFFD'], 'text': '\ufffd', 'box': token['box']}
        (self.work / 'anomalies.json').write_text(json.dumps([anomaly]), encoding="utf-8")
        manifest = json.loads((self.work / 'manifest.json').read_text(encoding="utf-8"))
        from importlib.util import spec_from_file_location, module_from_spec
        spec = spec_from_file_location('paper_reader', SCRIPT)
        module = module_from_spec(spec)
        spec.loader.exec_module(module)
        manifest['files']['anomalies.json'] = module.digest(self.work / 'anomalies.json')
        (self.work / 'manifest.json').write_text(json.dumps(manifest), encoding="utf-8")
        path.write_text(json.dumps(annotation, ensure_ascii=False), encoding="utf-8")
        blocked = self.cli('validate', '--work', self.work, '--annotations', path)
        self.assertNotEqual(blocked.returncode, 0)
        self.assertIn('unusual extracted glyph', blocked.stdout)
        annotation['excluded'] = [{'tokens': [token['id']], 'reason': 'nonlinguistic', 'note': 'Checked against page image; decorative glyph.'}]
        annotation['sentences'][0]['tokens'].remove(token['id'])
        annotation['sentences'][0]['words'].pop(token['id'])
        annotation['sentences'][0]['units'][0]['end'] -= 1
        annotation['sentences'][0]['units'][0]['literal'][0]['end'] -= 1
        path.write_text(json.dumps(annotation, ensure_ascii=False), encoding="utf-8")
        accepted = self.cli('validate', '--work', self.work, '--annotations', path)
        self.assertEqual(accepted.returncode, 0, accepted.stdout)

    def test_valid_build_is_atomic_and_embeds_paths(self):
        prepared = self.prepare()
        annotation, path = self.complete(prepared)
        output = self.base / 'reader.html'
        result = self.cli('build', '--work', self.work, '--annotations', path, '--output', output)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        html = output.read_text(encoding="utf-8")
        self.assertIn('data:image/svg+xml;base64,', html)
        self.assertNotIn('__READER_DATA__', html)
        match = re.search(r'<script id="reader-data" type="application/json">(.*?)</script>', html, re.S)
        payload = json.loads(match.group(1))
        self.assertEqual(payload['version'], 2)
        self.assertEqual(payload['scope'], prepared['scope'])
        self.assertEqual(len(payload['sentences'][0]['units']), 1)
        self.assertTrue(payload['pages'][0]['printed_label'])
        output.write_text('keep', encoding="utf-8")
        annotation['review']['layout'] = False
        path.write_text(json.dumps(annotation, ensure_ascii=False), encoding="utf-8")
        rejected = self.cli('build', '--work', self.work, '--annotations', path, '--output', output)
        self.assertNotEqual(rejected.returncode, 0)
        self.assertEqual(output.read_text(encoding="utf-8"), 'keep')

    def test_sentence_has_exactly_one_unit_and_math_requires_a_valid_crop(self):
        prepared = self.prepare()
        annotation, path = self.complete(prepared)
        sentence = annotation['sentences'][0]
        ids = sentence['tokens']
        token = prepared['pages'][0]['tokens'][0]
        ref = 'm1'
        annotation['math'] = {ref: {'tokens': [ids[0]], 'regions': [
            {'page': 1, 'box': token['box']} ]}}
        sentence['words'].pop(ids[0])
        unit = sentence['units'][0]
        unit['literal'][0]['parts'] = [{'type': 'math', 'ref': ref},
                                      {'type': 'text', 'text': '직역'}]
        unit['natural'] = [{'type': 'math', 'ref': ref},
                           {'type': 'text', 'text': '의역'}]
        path.write_text(json.dumps(annotation, ensure_ascii=False), encoding="utf-8")
        valid = self.cli('validate', '--work', self.work, '--annotations', path)
        self.assertEqual(valid.returncode, 0, valid.stdout)
        sentence['units'].append({'id': 'extra', 'start': 0, 'end': len(ids),
                                  'literal': unit['literal'], 'natural': unit['natural']})
        path.write_text(json.dumps(annotation, ensure_ascii=False), encoding="utf-8")
        extra = self.cli('validate', '--work', self.work, '--annotations', path)
        self.assertNotEqual(extra.returncode, 0)
        self.assertIn('exactly one whole-sentence unit', extra.stdout)
        sentence['units'].pop()
        annotation['math'][ref]['regions'][0]['box'] = [-1, 0, 3, 3]
        path.write_text(json.dumps(annotation, ensure_ascii=False), encoding="utf-8")
        bad_crop = self.cli('validate', '--work', self.work, '--annotations', path)
        self.assertNotEqual(bad_crop.returncode, 0)
        self.assertIn('outside page', bad_crop.stdout)

    def test_empty_or_unsafe_destinations_are_not_overwritten(self):
        self.work.mkdir()
        keep = self.work / 'keep.txt'
        keep.write_text('keep', encoding="utf-8")
        rejected = self.cli('prepare', self.pdf, '--work', self.work)
        self.assertNotEqual(rejected.returncode, 0)
        self.assertEqual(keep.read_text(encoding="utf-8"), 'keep')
        textless = self.base / 'image-only.pdf'
        c = Canvas(str(textless))
        c.rect(10, 10, 100, 100)
        c.showPage()
        c.save()
        failed = self.cli('prepare', textless, '--work', self.base / 'textless.work')
        self.assertNotEqual(failed.returncode, 0)
        self.assertFalse((self.base / 'textless.work' / 'prepared.json').exists())


if __name__ == '__main__':
    unittest.main()
