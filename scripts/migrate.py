#!/usr/bin/env python3
"""Copy a retained v2 work folder and convert its annotations to v3."""
import argparse
from pathlib import Path
import os
import shutil
import sys
import tempfile

sys.path.insert(0, str(Path(__file__).resolve().parent))
import paper_reader


def migrate(work, output, runtime_id=None, check=True):
    work, output = Path(work).resolve(), Path(output).resolve()
    if output.exists() or output.is_relative_to(work):
        raise ValueError('Migration requires a new output folder outside the original work')
    prepared = paper_reader.read_json(work/'prepared.json')
    if check:
        paper_reader.verify_manifest(work, prepared)
        paper_reader.prepared_tokens(work, prepared)
    annotations = paper_reader.convert_annotations_v3(paper_reader.read_json(work/'annotations.json'))
    original_execution = paper_reader.read_json(work/'execution.json') if (work/'execution.json').is_file() else {}
    original_migration = paper_reader.read_json(work/'migration.json') if (work/'migration.json').is_file() else {}
    record = {'version':1, 'annotation_version':3,
              'extraction_runtime_id':original_migration.get('extraction_runtime_id', original_execution.get('runtime_id')),
              'extraction_processor_version':prepared['processor_version'],
              'processor_runtime_id':runtime_id,
              'processor_version':(paper_reader.ROOT/'VERSION').read_text().strip(),
              'processor_source':str(paper_reader.ROOT), 'original_work':str(work)}
    output.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix='.pdf-lens-migrate-', dir=output.parent) as temp:
        stage=Path(temp)/'work'
        shutil.copytree(work,stage)
        paper_reader.write_json(stage/'annotations.json',annotations)
        paper_reader.write_json(stage/'migration.json',record)
        if check:
            _, _, result=paper_reader.validate(stage,stage/'annotations.json')
            if not result['ok']:
                raise ValueError('Converted annotations failed validation: '+str(result))
        os.rename(stage,output)
    return {'ok':True,'work':str(output),'migration':record}


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--work',type=Path,required=True)
    parser.add_argument('--output',type=Path,required=True)
    parser.add_argument('--runtime-id')
    args=parser.parse_args()
    print(migrate(args.work,args.output,args.runtime_id))

if __name__=='__main__':
    try:main()
    except (OSError,ValueError,KeyError) as error:
        print(f'PDF Lens migration: {error}',file=sys.stderr)
        raise SystemExit(1)
