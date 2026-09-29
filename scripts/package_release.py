#!/usr/bin/env python3
"""Package only maintained source files; never include PDFs, user outputs or runtimes."""
import argparse
import hashlib
from pathlib import Path
import re
import zipfile

ROOT = Path(__file__).resolve().parents[1]
TOP_FILES = {'SKILL.md', 'VERSION', 'README.md', 'LICENSE', 'THIRD_PARTY_NOTICES.md',
             'requirements-runtime.txt', 'requirements-dev.txt'}
TOP_DIRS = {'scripts', 'references', 'assets', 'agents', 'docs', 'tests'}


def package(source, destination):
    source, destination = Path(source).resolve(), Path(destination).resolve()
    version = (source/'VERSION').read_text().strip()
    if not re.fullmatch(r'\d+\.\d+\.\d+', version):
        raise ValueError('Release VERSION must be a stable x.y.z number')
    destination.mkdir(parents=True, exist_ok=True)
    archive = destination/f'pdf-lens-{version}.zip'
    with zipfile.ZipFile(archive, 'w', zipfile.ZIP_DEFLATED) as bundle:
        for path in sorted(source.rglob('*')):
            if not path.is_file() or path.is_symlink():
                continue
            relative = path.relative_to(source)
            if relative.parts[0] not in TOP_DIRS and str(relative) not in TOP_FILES:
                continue
            if any(part.startswith('.') or part == '__pycache__' for part in relative.parts):
                continue
            if path.suffix.lower() in {'.pdf', '.pyc', '.pyo'}:
                continue
            bundle.write(path, str(relative))
    checksum = hashlib.sha256(archive.read_bytes()).hexdigest()
    archive.with_suffix('.zip.sha256').write_text(f'{checksum}  {archive.name}\n', encoding='utf-8')
    return archive


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--source', type=Path, default=ROOT)
    parser.add_argument('--output', type=Path, default=ROOT/'dist')
    args = parser.parse_args()
    print(package(args.source,args.output))
