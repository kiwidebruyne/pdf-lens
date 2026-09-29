#!/usr/bin/env python3
"""Create an isolated, release-specific Python runtime for PDF Lens."""
from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys


PRODUCT = "pdf-lens"
PYTHON_VERSION = "3.13"


def digest(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            h.update(block)
    return h.hexdigest()


def uv_path(tool_dir: Path) -> Path:
    return tool_dir / "uv" / ("uv.exe" if os.name == "nt" else "uv")


def runtime_id(version: str, requirements: Path) -> str:
    return f"{version}-{digest(requirements)[:16]}"


def run(args: list[str], env: dict[str, str]) -> None:
    # Keep the helper's stdout machine-readable for its single JSON result.
    subprocess.run(args, check=True, env=env, stdout=sys.stderr)


def prepare(codex_home: Path, version: str, requirements: Path) -> dict:
    codex_home = codex_home.expanduser().resolve()
    requirements = requirements.resolve()
    tool_dir = codex_home / "tool-envs" / PRODUCT
    uv = uv_path(tool_dir)
    if not uv.is_file():
        raise RuntimeError(f"Private uv is missing: {uv}. Run the platform bootstrap first.")

    runtime_key = runtime_id(version, requirements)
    runtime_root = tool_dir / "runtimes" / runtime_key
    env_dir = runtime_root / "venv"
    browser_dir = runtime_root / "browsers"
    python_dir = tool_dir / "python"
    runtime_root.parent.mkdir(parents=True, exist_ok=True)
    browser_dir.mkdir(parents=True, exist_ok=True)

    env = os.environ.copy()
    env["UV_PYTHON_INSTALL_DIR"] = str(python_dir)
    env["UV_NO_MODIFY_PATH"] = "1"
    env["UV_CACHE_DIR"] = str(tool_dir / "cache")
    env["PLAYWRIGHT_BROWSERS_PATH"] = str(browser_dir)
    install_args = [str(uv), "python", "install", "--no-bin"]
    if os.name == "nt":
        install_args.append("--no-registry")
    run([*install_args, PYTHON_VERSION], env)
    managed_python = subprocess.run(
        [str(uv), "python", "find", "--managed-python", PYTHON_VERSION],
        check=True, env=env, capture_output=True, text=True,
    ).stdout.strip().splitlines()[-1]

    if not (env_dir / ("Scripts/python.exe" if os.name == "nt" else "bin/python")).is_file():
        run([str(uv), "venv", "--python", managed_python, str(env_dir)], env)
    python = env_dir / ("Scripts/python.exe" if os.name == "nt" else "bin/python")
    run([str(uv), "pip", "install", "--python", str(python), "--only-binary", ":all:", "-r", str(requirements)], env)
    run([str(python), "-m", "playwright", "install", "chromium"], env)

    metadata = {
        "product": PRODUCT,
        "release": version,
        "python": PYTHON_VERSION,
        "requirements_sha256": digest(requirements),
        "runtime_id": runtime_key,
        "runtime_root": str(runtime_root),
        "source_snapshot": str(runtime_root / "source_snapshot"),
        "python_executable": str(python),
        "browser_cache": str(browser_dir),
        "uv_executable": str(uv),
    }
    (runtime_root / "runtime.json").write_text(json.dumps(metadata, indent=2) + "\n", encoding="utf-8")
    return metadata


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--codex-home", type=Path, default=Path(os.environ.get("CODEX_HOME", Path.home() / ".codex")))
    parser.add_argument("--version", required=True)
    parser.add_argument("--requirements", type=Path, required=True)
    args = parser.parse_args()
    print(json.dumps(prepare(args.codex_home, args.version, args.requirements), indent=2))
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except subprocess.CalledProcessError as exc:
        if os.name == "nt" and exc.returncode in (126, 127, 0xC0000135, -1073741515):
            print("A required Microsoft Visual C++ runtime DLL is missing. Install the official Microsoft Visual C++ 2015–2022 Redistributable, then rerun setup.", file=sys.stderr)
        else:
            print(f"Runtime setup failed ({exc.returncode}): {exc}", file=sys.stderr)
        raise SystemExit(exc.returncode or 1)
    except Exception as exc:
        print(f"Runtime setup failed: {exc}", file=sys.stderr)
        raise SystemExit(1)
