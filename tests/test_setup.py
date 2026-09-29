import importlib.util
import io
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
import zipfile


ROOT = Path(__file__).resolve().parents[1]


def load(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


installer = load("manage_install", ROOT / "scripts" / "manage_install.py")
runtime = load("setup_runtime", ROOT / "scripts" / "setup_runtime.py")


class SetupTests(unittest.TestCase):
    def test_pinned_runtime_fingerprint_changes_with_requirements(self):
        with tempfile.TemporaryDirectory() as temp:
            req = Path(temp) / "requirements.txt"
            req.write_text("PyMuPDF==1.28.2\n", encoding="utf-8")
            first = runtime.runtime_id("1.2.3", req)
            req.write_text("PyMuPDF==1.28.3\n", encoding="utf-8")
            self.assertNotEqual(first, runtime.runtime_id("1.2.3", req))

    def test_powershell_bootstrap_captures_native_stderr_and_retries_same_action(self):
        wrapper = (ROOT / "scripts" / "bootstrap.ps1").read_text(encoding="utf-8")
        self.assertIn("-RedirectStandardOutput $stdoutFile", wrapper)
        self.assertIn("-RedirectStandardError $stderrFile", wrapper)
        self.assertLess(wrapper.index("function Invoke-NativeCapture"), wrapper.index("$pythonInstall = Invoke-NativeCapture"))
        self.assertIn("$exitCode = Invoke-PdfLensInstall $python $Action", wrapper)

    def test_release_extraction_rejects_path_traversal(self):
        archive = io.BytesIO()
        with zipfile.ZipFile(archive, "w") as zf:
            zf.writestr("../outside.txt", "unsafe")
        with tempfile.TemporaryDirectory() as temp:
            with self.assertRaisesRegex(RuntimeError, "unsafe path"):
                installer.extract_release(archive.getvalue(), Path(temp) / "stage")
            self.assertFalse((Path(temp) / "outside.txt").exists())

    def test_latest_release_rejects_prerelease_and_bad_checksum(self):
        prerelease = json.dumps({"draft": False, "prerelease": True, "tag_name": "v1.2.3-rc1"}).encode()
        with patch.object(installer, "request", return_value=prerelease) as request:
            with self.assertRaisesRegex(RuntimeError, "stable"):
                installer.release_info()
            self.assertEqual(request.call_count, 1)

        archive = b"published release archive"
        metadata = {
            "draft": False,
            "prerelease": False,
            "tag_name": "v1.2.3",
            "assets": [
                {"name": "pdf-lens-1.2.3.zip", "browser_download_url": "archive"},
                {"name": "pdf-lens-1.2.3.zip.sha256", "browser_download_url": "checksum"},
            ],
        }
        with patch.object(installer, "request", side_effect=[json.dumps(metadata).encode(), archive, b"0" * 64]):
            with self.assertRaisesRegex(RuntimeError, "checksum"):
                installer.release_info()

    def test_source_install_swap_restores_old_skill_if_activation_fails(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            home = root / "codex"
            source = root / "source"
            source.mkdir()
            (source / "VERSION").write_text("1.2.3\n", encoding="utf-8")
            (source / "SKILL.md").write_text("new skill", encoding="utf-8")
            skill, _, _ = installer.paths(home)
            skill.mkdir(parents=True)
            (skill / "SKILL.md").write_text("working skill", encoding="utf-8")
            real_rename = Path.rename
            failed = False

            def rename_once(path, target):
                nonlocal failed
                if not failed and path.parent.name.startswith(".pdf-lens-stage-") and path.name == "pdf-lens":
                    failed = True
                    raise OSError("simulated directory activation failure")
                return real_rename(path, target)

            runtime_data = {
                "runtime_root": str(root / "codex" / "tool-envs" / "pdf-lens" / "runtimes" / "1.2.3-test"),
                "python_executable": "/private/python",
                "runtime_id": "1.2.3-test",
                "browser_cache": "/private/browsers",
            }
            with patch.object(Path, "rename", rename_once):
                with self.assertRaisesRegex(OSError, "simulated"):
                    installer.activate(source, home, "1.2.3", runtime_data, "source")
            self.assertEqual((skill / "SKILL.md").read_text(encoding="utf-8"), "working skill")

    def test_uninstall_is_scoped_to_pdf_lens_owned_paths(self):
        with tempfile.TemporaryDirectory() as temp:
            home = Path(temp) / "codex"
            skill, runtime_dir, _ = installer.paths(home)
            keep = home / "skills" / "paper-korean-reader"
            keep.mkdir(parents=True)
            (keep / "SKILL.md").write_text("keep", encoding="utf-8")
            skill.mkdir(parents=True)
            runtime_dir.mkdir(parents=True)
            installer.uninstall(home)
            self.assertFalse(skill.exists())
            if installer.os.name == "nt":
                self.assertTrue(runtime_dir.is_dir(), "Windows wrapper deletes the runtime after its Python child exits")
                wrapper = (ROOT / "scripts" / "bootstrap.ps1").read_text(encoding="utf-8")
                self.assertIn('if ($Action -eq "uninstall") { Remove-Item $toolDir -Recurse -Force }', wrapper)
            else:
                self.assertFalse(runtime_dir.exists())
            self.assertTrue((keep / "SKILL.md").is_file())

    def test_update_failure_keeps_old_install_and_retry_activates_snapshot(self):
        archive = io.BytesIO()
        with zipfile.ZipFile(archive, "w") as zf:
            zf.writestr("VERSION", "2.0.0\n")
            zf.writestr("SKILL.md", "new skill")
        with tempfile.TemporaryDirectory() as temp:
            home = Path(temp) / "codex"
            skill, runtime_base, _ = installer.paths(home)
            skill.mkdir(parents=True)
            (skill / "VERSION").write_text("1.0.0\n", encoding="utf-8")
            (skill / "SKILL.md").write_text("working skill", encoding="utf-8")
            (skill / "install-state.json").write_text(json.dumps({"version": "1.0.0"}), encoding="utf-8")
            runtime_root = runtime_base / "runtimes" / "2.0.0-test"
            runtime_data = {
                "runtime_root": str(runtime_root),
                "python_executable": str(runtime_root / "venv" / "bin" / "python"),
                "runtime_id": "2.0.0-test",
                "browser_cache": str(runtime_root / "browsers"),
            }
            with patch.object(installer, "release_info", return_value=("2.0.0", archive.getvalue())), \
                 patch.object(installer, "run_runtime", return_value=runtime_data), \
                 patch.object(installer, "smoke", side_effect=[RuntimeError("simulated browser failure"), None]):
                with self.assertRaisesRegex(RuntimeError, "simulated browser failure"):
                    installer.update(home)
                self.assertEqual((skill / "SKILL.md").read_text(encoding="utf-8"), "working skill")
                self.assertEqual(json.loads((skill / "install-state.json").read_text(encoding="utf-8"))["version"], "1.0.0")

                installer.update(home)

            self.assertEqual((skill / "SKILL.md").read_text(encoding="utf-8"), "new skill")
            active = json.loads((skill / "install-state.json").read_text(encoding="utf-8"))
            self.assertEqual(active["version"], "2.0.0")
            self.assertEqual((Path(active["source_snapshot"]) / "VERSION").read_text(encoding="utf-8").strip(), "2.0.0")


if __name__ == "__main__":
    unittest.main()
