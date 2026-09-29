#!/usr/bin/env python3
"""Run source and real-browser checks with a freshly bootstrapped installation."""
import argparse
import json
import os
from pathlib import Path
import subprocess


def main():
    parser=argparse.ArgumentParser()
    parser.add_argument('--codex-home',type=Path,required=True)
    parser.add_argument('--output',type=Path,required=True)
    args=parser.parse_args()
    root=Path(__file__).resolve().parents[1]
    state=json.loads((args.codex_home/'skills/pdf-lens/install-state.json').read_text())
    python=state['runtime_path']
    uv=args.codex_home/'tool-envs/pdf-lens/uv'/('uv.exe' if os.name=='nt' else 'uv')
    env=os.environ.copy()
    env['PLAYWRIGHT_BROWSERS_PATH']=state['browser_cache']
    env['UV_CACHE_DIR']=str(args.codex_home/'tool-envs/pdf-lens/cache')
    def run(*command):
        subprocess.run([str(x) for x in command],cwd=root,env=env,check=True)
    run(uv,'pip','install','--python',python,'--only-binary',':all:','-r',root/'requirements-dev.txt')
    run(python,'-m','unittest','discover','-s','tests','-p','test_*.py','-v')
    run(python,'tests/make_sample.py',args.output/'새 문서')
    run(python,'scripts/verify_reader.py',args.output/'새 문서/sample.html',
        '--report',args.output/'browser.json')
    run(python,'scripts/package_release.py','--output',args.output/'release')


if __name__=='__main__':
    main()
