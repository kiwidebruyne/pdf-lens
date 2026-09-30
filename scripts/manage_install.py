#!/usr/bin/env python3
"""Install, update, inspect, or remove only PDF Lens-owned files."""
from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import sys
import tempfile
import urllib.error
import urllib.request
import zipfile


REPOSITORY = "kiwidebruyne/pdf-lens"
PRODUCT = "pdf-lens"
API = f"https://api.github.com/repos/{REPOSITORY}/releases/latest"


def codex_home(value: str | None) -> Path:
    return Path(value or os.environ.get("CODEX_HOME", Path.home() / ".codex")).expanduser().resolve()


def paths(home: Path) -> tuple[Path, Path, Path]:
    owned = home / "skills" / PRODUCT
    runtime = home / "tool-envs" / PRODUCT
    state = runtime / "state.json"
    return owned, runtime, state


def sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def request(url: str, accept: str = "application/vnd.github+json") -> bytes:
    req = urllib.request.Request(url, headers={"Accept": accept, "User-Agent": "pdf-lens-installer"})
    with urllib.request.urlopen(req, timeout=60) as response:
        return response.read()


def release_info() -> tuple[str, bytes]:
    release = json.loads(request(API))
    if release.get("draft") or release.get("prerelease"):
        raise RuntimeError("GitHub did not return a stable, published latest release")
    tag = release.get("tag_name", "")
    version = tag.removeprefix("v")
    if not re.fullmatch(r"\d+\.\d+\.\d+(?:\.\d+)?", version):
        raise RuntimeError(f"Unsupported release tag: {tag!r}")
    expected_zip = f"{PRODUCT}-{version}.zip"
    assets = {item["name"]: item["browser_download_url"] for item in release.get("assets", [])}
    if expected_zip not in assets or expected_zip + ".sha256" not in assets:
        raise RuntimeError(f"Release {tag} must include {expected_zip} and {expected_zip}.sha256")
    archive = request(assets[expected_zip], "application/octet-stream")
    checksum = request(assets[expected_zip + ".sha256"], "text/plain").decode("ascii").strip().split()[0].lower()
    if not re.fullmatch(r"[0-9a-f]{64}", checksum) or sha256_bytes(archive) != checksum:
        raise RuntimeError(f"Release archive checksum verification failed for {expected_zip}")
    return version, archive


def extract_release(archive: bytes, destination: Path) -> Path:
    destination.mkdir(parents=True, exist_ok=True)
    archive_path = destination / "release.zip"
    archive_path.write_bytes(archive)
    with zipfile.ZipFile(archive_path) as zf:
        for item in zf.infolist():
            name = Path(item.filename)
            if name.is_absolute() or ".." in name.parts:
                raise RuntimeError("Release archive contains an unsafe path")
            target = (destination / name).resolve()
            if not target.is_relative_to(destination.resolve()):
                raise RuntimeError("Release archive escapes its staging folder")
        zf.extractall(destination)
    archive_path.unlink()
    candidates = [p for p in destination.iterdir() if p.is_dir() and (p / "VERSION").is_file()]
    if (destination / "VERSION").is_file():
        return destination
    if len(candidates) != 1:
        raise RuntimeError("Release ZIP must contain the PDF Lens source at its root or in one top-level folder")
    return candidates[0]


def version_of(source: Path) -> str:
    version = (source / "VERSION").read_text(encoding="utf-8").strip()
    if not re.fullmatch(r"\d+\.\d+\.\d+(?:\.\d+)?", version):
        raise RuntimeError(f"Invalid source VERSION: {version!r}")
    return version


def run_runtime(source: Path, home: Path, version: str) -> dict:
    helper = source / "scripts" / "setup_runtime.py"
    requirements = source / "requirements-runtime.txt"
    if not helper.is_file() or not requirements.is_file():
        raise RuntimeError("Source is missing setup_runtime.py or requirements-runtime.txt")
    command = [sys.executable, str(helper), "--codex-home", str(home), "--version", version, "--requirements", str(requirements)]
    try:
        result = subprocess.run(command, check=True, capture_output=True, text=True)
    except subprocess.CalledProcessError as exc:
        details = (exc.stderr or exc.stdout or "").strip()
        raise RuntimeError(f"Runtime setup command failed ({exc.returncode}). {details}") from exc
    if result.stderr:
        sys.stderr.write(result.stderr)
    return json.loads(result.stdout)


def smoke(source: Path, runtime: dict) -> None:
    env = os.environ.copy()
    env["PLAYWRIGHT_BROWSERS_PATH"] = runtime["browser_cache"]
    subprocess.run([runtime["python_executable"], str(source / "scripts" / "setup_smoke.py")], check=True, env=env)


def copy_skill(source: Path, destination: Path) -> None:
    shutil.copytree(source, destination, ignore=shutil.ignore_patterns(".git", ".harness", "__pycache__", ".DS_Store", "tests", "dist", "output"))


def ensure_source_snapshot(source: Path, runtime: dict, version: str) -> Path:
    snapshot = Path(runtime["runtime_root"]) / "source_snapshot"
    if snapshot.is_dir():
        if version_of(snapshot) != version:
            raise RuntimeError(f"Runtime source snapshot version does not match {version}")
        return snapshot
    stage = snapshot.with_name(f".source-snapshot-{os.getpid()}")
    if stage.exists():
        shutil.rmtree(stage)
    copy_skill(source, stage)
    try:
        stage.rename(snapshot)
    except Exception:
        shutil.rmtree(stage, ignore_errors=True)
        raise
    return snapshot


def activate(source: Path, home: Path, version: str, runtime: dict, current: Path) -> None:
    skill, runtime_root, _ = paths(home)
    skill.parent.mkdir(parents=True, exist_ok=True)
    stage = Path(tempfile.mkdtemp(prefix=".pdf-lens-stage-", dir=skill.parent))
    backup = skill.parent / f".pdf-lens-backup-{os.getpid()}"
    try:
        staged_skill = stage / PRODUCT
        copy_skill(source, staged_skill)
        source_snapshot = ensure_source_snapshot(source, runtime, version)
        state = {
            "product": PRODUCT,
            "version": version,
            "skill_path": str(skill),
            "runtime_path": runtime["python_executable"],
            "runtime_id": runtime["runtime_id"],
            "browser_cache": runtime["browser_cache"],
            "source_snapshot": str(source_snapshot),
            "source": current,
        }
        runtime_root.mkdir(parents=True, exist_ok=True)
        (staged_skill / "install-state.json").write_text(json.dumps(state, indent=2) + "\n", encoding="utf-8")
        old_cwd = Path.cwd()
        os.chdir(stage)
        try:
            if skill.exists():
                skill.rename(backup)
            try:
                staged_skill.rename(skill)
            except Exception:
                if backup.exists() and not skill.exists():
                    backup.rename(skill)
                raise
        finally:
            os.chdir(old_cwd if old_cwd.exists() else Path(tempfile.gettempdir()))
        if backup.exists():
            shutil.rmtree(backup)
    finally:
        shutil.rmtree(stage, ignore_errors=True)


def install(args: argparse.Namespace, home: Path) -> None:
    if args.source:
        source = Path(args.source).expanduser().resolve()
        version = version_of(source)
        origin = "source"
    else:
        raise RuntimeError("Initial installation requires --source PATH. Run `update` later to install the latest stable release.")
    runtime = run_runtime(source, home, version)
    smoke(source, runtime)
    activate(source, home, version, runtime, origin)
    print(f"Installed PDF Lens {version} at {paths(home)[0]}")


def update(home: Path) -> None:
    skill, _, _ = paths(home)
    if not (skill / "install-state.json").is_file():
        raise RuntimeError("PDF Lens is not installed; use `install --source PATH` first")
    version, archive = release_info()
    old_state = json.loads((skill / "install-state.json").read_text(encoding="utf-8"))
    if tuple(map(int, old_state["version"].split("."))) >= tuple(map(int, version.split("."))):
        print(f"PDF Lens {old_state['version']} is installed; release {version} will not replace it.")
        return
    with tempfile.TemporaryDirectory(prefix="pdf-lens-update-") as temp:
        source = extract_release(archive, Path(temp) / "archive")
        if version_of(source) != version:
            raise RuntimeError(f"Release tag version {version} does not match archive VERSION {version_of(source)}")
        runtime = run_runtime(source, home, version)
        smoke(source, runtime)
        activate(source, home, version, runtime, "github-release")
    print(f"Updated PDF Lens to {version} at {skill}")


def state(home: Path) -> None:
    skill, runtime, _ = paths(home)
    output = {"installed": (skill / "install-state.json").is_file(), "skill_path": str(skill), "runtime_root": str(runtime)}
    state_path = skill / "install-state.json"
    if state_path.is_file():
        output["active"] = json.loads(state_path.read_text(encoding="utf-8"))
    print(json.dumps(output, indent=2))


def uninstall(home: Path) -> None:
    skill, runtime, _ = paths(home)
    # These paths are intentionally narrow and fixed to the product's ownership boundary.
    if skill.exists():
        shutil.rmtree(skill)
    if runtime.exists() and os.name != "nt":
        shutil.rmtree(runtime)
    runtime_message = "runtime" if os.name != "nt" else "skill (the native Windows wrapper removes the runtime after this process exits)"
    print(f"Removed PDF Lens {runtime_message} from {home}; PDF Lens work and output folders were not touched.")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--codex-home", help="Override CODEX_HOME (mainly for testing)")
    subparsers = parser.add_subparsers(dest="command", required=True)
    p_install = subparsers.add_parser("install", help="Install a local source checkout")
    p_install.add_argument("--source", required=True, help="Path to a PDF Lens source checkout or release folder")
    subparsers.add_parser("update", help="Install the latest stable GitHub release")
    subparsers.add_parser("state", help="Print machine-readable installation state")
    subparsers.add_parser("uninstall", help="Remove only PDF Lens-owned skill and runtime files")
    args = parser.parse_args()
    home = codex_home(args.codex_home)
    {"install": lambda: install(args, home), "update": lambda: update(home), "state": lambda: state(home), "uninstall": lambda: uninstall(home)}[args.command]()
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except (OSError, urllib.error.URLError, zipfile.BadZipFile, subprocess.CalledProcessError, RuntimeError, ValueError) as exc:
        print(f"PDF Lens setup failed; the current installation is unchanged: {exc}", file=sys.stderr)
        raise SystemExit(1)
