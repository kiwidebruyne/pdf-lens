#!/usr/bin/env python3
"""Installed user entrypoint: update new jobs, pin resumed jobs to their runtime."""
import argparse
import json
import os
from pathlib import Path
import re
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[1]


def read(path):
    return json.loads(Path(path).read_text(encoding='utf-8'))


def select_runtime(root, work, new_job, active=False):
    state_path = root / 'install-state.json'
    if not state_path.is_file():
        # Source checkouts use their explicitly provisioned development environment.
        return {'python_executable': sys.executable, 'source_snapshot': str(root)}, None
    state = read(state_path)
    home = Path(state['skill_path']).parent.parent
    tool_dir = home / 'tool-envs/pdf-lens'
    if new_job:
        update_env = os.environ.copy()
        update_env['PYTHONUTF8'] = '1'
        result = subprocess.run([sys.executable, str(root/'scripts/manage_install.py'),
            '--codex-home', str(home), 'update'], cwd=home, stdout=sys.stderr, env=update_env)
        if result.returncode:
            print('PDF Lens: 업데이트를 적용하지 못해 검증된 기존 버전으로 계속합니다.', file=sys.stderr)
        state = read(home/'skills/pdf-lens/install-state.json')
    execution = work/'execution.json'
    migration = read(work/'migration.json') if (work/'migration.json').is_file() else None
    if migration and not active:
        if (migration.get('version') != 1 or migration.get('annotation_version') != 3 or
                migration.get('extraction_runtime_id') != (read(execution)['runtime_id'] if execution.is_file() else None) or
                migration.get('extraction_processor_version') != read(work/'prepared.json')['processor_version']):
            raise ValueError('Migration extraction provenance is invalid')
        runtime_id = migration['processor_runtime_id']
    elif not new_job and execution.is_file() and not active:
        runtime_id = read(execution)['runtime_id']
    else:
        runtime_id = state['runtime_id']
    if not isinstance(runtime_id,str) or not re.fullmatch(r'\d+\.\d+\.\d+-[0-9a-f]{16}',runtime_id):
        raise ValueError('Invalid work runtime identity')
    runtime = read(tool_dir/'runtimes'/runtime_id/'runtime.json')
    if not new_job and not active:
        prepared = read(work/'prepared.json')
        if not migration and prepared['processor_version'] != runtime['release']:
            raise ValueError('이 작업을 만든 버전의 실행 환경이 필요합니다. 자동으로 재추출하지 않습니다.')
    snapshot = Path(runtime['source_snapshot']).resolve()
    expected_root = (tool_dir/'runtimes'/runtime_id).resolve()
    if not snapshot.is_relative_to(expected_root) or not (snapshot/'scripts/paper_reader.py').is_file():
        raise ValueError('Retained processor snapshot is missing or outside its runtime')
    return runtime, runtime_id


def main(argv=None):
    parser=argparse.ArgumentParser(description=__doc__)
    sub=parser.add_subparsers(dest='command',required=True)
    p=sub.add_parser('prepare');p.add_argument('pdf',type=Path);p.add_argument('--work',type=Path,required=True);p.add_argument('--pages')
    for name in ('validate','build'):
        p=sub.add_parser(name);p.add_argument('--work',type=Path,required=True);p.add_argument('--annotations',type=Path,required=True)
        if name=='build':p.add_argument('--output',type=Path,required=True)
    p=sub.add_parser('migrate');p.add_argument('--work',type=Path,required=True);p.add_argument('--output',type=Path,required=True)
    for name in ('serve', 'publish'):
        p=sub.add_parser(name)
        for option in ('work', 'worklist', 'fragments'):
            p.add_argument('--'+option,type=Path,required=True)
        if name=='publish':
            p.add_argument('--chunk',required=True)
            p.add_argument('--input',type=Path,required=True)
    args=parser.parse_args(argv)
    work=args.work.resolve()
    new_job=args.command=='prepare' and not (work/'prepared.json').exists()
    runtime,runtime_id=select_runtime(ROOT,work,new_job,active=args.command=='migrate')
    if args.command in ('serve','publish'):
        script=Path(runtime['source_snapshot'])/'scripts/live_reader.py'
        if not script.is_file():
            raise ValueError('이 작업의 고정된 버전은 실시간 읽기를 지원하지 않습니다. 기존 작업은 보존하고 새 버전으로 새 작업을 시작하세요.')
        command=[runtime['python_executable'],str(script),args.command,
                 '--work',str(work),'--worklist',str(args.worklist.resolve()),
                 '--fragments',str(args.fragments.resolve())]
        if args.command=='publish':
            command.extend(['--chunk',args.chunk,'--input',str(args.input.resolve())])
        env=os.environ.copy();env['PYTHONUTF8']='1'
        return subprocess.run(command,env=env).returncode
    if args.command=='migrate':
        command=[runtime['python_executable'],str(Path(runtime['source_snapshot'])/'scripts/migrate.py'), '--work',str(work),'--output',str(args.output.resolve())]
        if runtime_id:command.extend(['--runtime-id',runtime_id])
        return subprocess.run(command).returncode
    command=[runtime['python_executable'],str(Path(runtime['source_snapshot'])/'scripts/paper_reader.py'),args.command]
    if args.command=='prepare':
        command.append(str(args.pdf.resolve()))
        preparation_id = (read(work/'migration.json').get('extraction_runtime_id')
                          if (work/'migration.json').is_file() else runtime_id)
        if preparation_id:command.extend(['--runtime-id',preparation_id])
    command.extend(['--work',str(work)])
    if getattr(args,'pages',None):command.extend(['--pages',args.pages])
    if getattr(args,'annotations',None):command.extend(['--annotations',str(args.annotations.resolve())])
    if getattr(args,'output',None):command.extend(['--output',str(args.output.resolve())])
    env=os.environ.copy()
    env['PYTHONUTF8']='1'
    if runtime.get('browser_cache'):env['PLAYWRIGHT_BROWSERS_PATH']=runtime['browser_cache']
    result=subprocess.run(command,env=env)
    return result.returncode


if __name__=='__main__':
    sys.stdout.reconfigure(encoding='utf-8')
    sys.stderr.reconfigure(encoding='utf-8')
    try:
        raise SystemExit(main())
    except (OSError,ValueError,KeyError) as error:
        print(f'PDF Lens: {error}',file=sys.stderr)
        raise SystemExit(1)
