import importlib.util
import json
from pathlib import Path
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location('migration', ROOT/'scripts/migrate.py')
migration = importlib.util.module_from_spec(spec)
spec.loader.exec_module(migration)

class MigrationTests(unittest.TestCase):
    def test_default_migration_validates_real_work_and_builds(self):
        import sys
        sys.path.insert(0, str(ROOT/'tests'))
        from test_v3 import V3Tests
        fixture=V3Tests(); fixture.setUp()
        try:
            data=fixture.annotation();data['version']=2
            data['lexicon']={'word':{'lemma':'word','pos':'명사','gloss':'단어'}}
            sentence=data['sentences'][0]
            natural=sentence.pop('natural')
            sentence['units']=[{'id':'s1-whole','start':0,'end':len(sentence['tokens']),
                               'literal':[{'start':0,'end':len(sentence['tokens']),'parts':natural}], 'natural':natural}]
            sentence['words']={key:{'entry':'word','meaning':'이 단어','role':'명사','expression':''} for key in sentence['tokens']}
            migration.paper_reader.write_json(fixture.work/'annotations.json',data)
            before={str(p.relative_to(fixture.work)):p.read_bytes() for p in fixture.work.rglob('*') if p.is_file()}
            new=fixture.base/'converted'
            migration.migrate(fixture.work,new)
            self.assertEqual(before,{str(p.relative_to(fixture.work)):p.read_bytes() for p in fixture.work.rglob('*') if p.is_file()})
            result=migration.paper_reader.build(new,new/'annotations.json',fixture.base/'converted.html')
            self.assertTrue(result['ok'],result)
        finally:fixture.doCleanups()

    def test_copy_preserves_original_artifacts_and_records_two_runtimes(self):
        with tempfile.TemporaryDirectory() as temp:
            base=Path(temp); old=base/'old';old.mkdir()
            a={'version':2,'lexicon':{'w':{'lemma':'word','pos':'명사','gloss':'단어'}},'sentences':[{'id':'s','tokens':['p1t0'],'units':[{'id':'s-whole','start':0,'end':1,'literal':[{'start':0,'end':1,'parts':[{'type':'text','text':'단어'}]}],'natural':[{'type':'text','text':'단어'}]}],'words':{'p1t0':{'entry':'w','meaning':'이 단어','role':'명사','expression':''}},'joins':[]} ]}
            for name,data in [('prepared.json',{'processor_version':'0.1.0'}),('execution.json',{'runtime_id':'0.1.0-aaaaaaaaaaaaaaaa'}),('annotations.json',a)]:
                (old/name).write_text(json.dumps(data))
            before={p.name:p.read_bytes() for p in old.iterdir()}
            new=base/'new'
            migration.migrate(old,new,'0.2.0-bbbbbbbbbbbbbbbb',check=False)
            self.assertEqual(before,{p.name:p.read_bytes() for p in old.iterdir()})
            self.assertEqual((new/'prepared.json').read_bytes(),before['prepared.json'])
            self.assertEqual((new/'execution.json').read_bytes(),before['execution.json'])
            out=json.loads((new/'annotations.json').read_text())
            self.assertEqual(out['version'],3)
            self.assertEqual(out['sentences'][0]['words']['p1t0'],{'base':'단어','meaning':'이 단어'})
            record=json.loads((new/'migration.json').read_text())
            self.assertEqual(record['extraction_runtime_id'],'0.1.0-aaaaaaaaaaaaaaaa')
            self.assertEqual(record['processor_runtime_id'],'0.2.0-bbbbbbbbbbbbbbbb')
            with self.assertRaises(ValueError):migration.migrate(old,new,'0.2.0-bbbbbbbbbbbbbbbb',check=False)

if __name__=='__main__':unittest.main()
