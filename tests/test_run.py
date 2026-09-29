import importlib.util
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch


ROOT = Path(__file__).resolve().parents[1]


def load(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


runner = load("pdf_lens_run", ROOT / "scripts" / "run.py")


class RunTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.base = Path(self.temp.name)
        self.home = self.base / "codex"
        self.skill = self.home / "skills" / "pdf-lens"
        self.skill.mkdir(parents=True)
        self.tool_dir = self.home / "tool-envs" / "pdf-lens"
        self.work = self.base / "chapter.work"
        self.work.mkdir()
        self.pdf = self.base / "paper.pdf"
        self.pdf.write_bytes(b"fixture PDF")
        self.old_id = "0.1.0-aaaaaaaaaaaaaaaa"
        self.new_id = "0.2.0-bbbbbbbbbbbbbbbb"
        self.write_runtime(self.old_id, "0.1.0")
        self.write_runtime(self.new_id, "0.2.0")
        self.write_install_state(self.old_id)

    def tearDown(self):
        self.temp.cleanup()

    def write_json(self, path, value):
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(value), encoding="utf-8")

    def write_runtime(self, runtime_id, release):
        runtime_root = self.tool_dir / "runtimes" / runtime_id
        snapshot = runtime_root / "source_snapshot"
        (snapshot / "scripts").mkdir(parents=True, exist_ok=True)
        (snapshot / "scripts" / "paper_reader.py").write_text("# fixture processor\n", encoding="utf-8")
        self.write_json(runtime_root / "runtime.json", {
            "runtime_id": runtime_id,
            "release": release,
            "source_snapshot": str(snapshot),
            "python_executable": str(runtime_root / "venv" / "bin" / "python"),
            "browser_cache": str(runtime_root / "browsers"),
        })

    def write_install_state(self, runtime_id):
        self.write_json(self.skill / "install-state.json", {
            "skill_path": str(self.skill),
            "runtime_id": runtime_id,
        })

    def write_prepared(self, processor_version):
        self.write_json(self.work / "prepared.json", {"processor_version": processor_version})

    def write_execution(self, runtime_id):
        self.write_json(self.work / "execution.json", {"runtime_id": runtime_id})

    def invoke(self, argv, update_result=0):
        commands = []

        def fake_run(command, **kwargs):
            commands.append((command, kwargs))
            if command[-1:] == ["update"]:
                return subprocess.CompletedProcess(command, update_result)
            return subprocess.CompletedProcess(command, 0)

        with patch.object(runner, "ROOT", self.skill), patch.object(runner.subprocess, "run", fake_run):
            result = runner.main(argv)
        return result, commands

    def test_only_new_prepare_requests_automatic_update(self):
        result, commands = self.invoke(["prepare", str(self.pdf), "--work", str(self.work)])
        self.assertEqual(result, 0)
        self.assertEqual(len(commands), 2)
        self.assertEqual(commands[0][0][-1], "update")
        self.assertEqual(commands[1][0][1], str(self.tool_dir / "runtimes" / self.old_id / "source_snapshot" / "scripts" / "paper_reader.py"))
        command = commands[1][0]
        self.assertEqual(command[command.index("--runtime-id") + 1], self.old_id)
        self.assertFalse((self.work / "execution.json").exists(), "The child must commit the pin with its work transaction")

        self.write_prepared("0.1.0")
        self.write_execution(self.old_id)
        _, resumed_commands = self.invoke(["validate", "--work", str(self.work), "--annotations", str(self.base / "annotations.json")])
        self.assertEqual(len(resumed_commands), 1)
        self.assertEqual(resumed_commands[0][0][1], str(self.tool_dir / "runtimes" / self.old_id / "source_snapshot" / "scripts" / "paper_reader.py"))
        self.assertFalse(any(command[-1:] == ["update"] for command, _ in resumed_commands))

    def test_failed_update_continues_with_active_runtime(self):
        active_before = (self.skill / "install-state.json").read_bytes()
        result, commands = self.invoke(["prepare", str(self.pdf), "--work", str(self.work)], update_result=1)

        self.assertEqual(result, 0)
        self.assertEqual((self.skill / "install-state.json").read_bytes(), active_before)
        self.assertEqual(commands[0][0][-1], "update")
        processor_command = commands[1][0]
        self.assertEqual(processor_command[0], str(self.tool_dir / "runtimes" / self.old_id / "venv" / "bin" / "python"))
        self.assertEqual(processor_command[1], str(self.tool_dir / "runtimes" / self.old_id / "source_snapshot" / "scripts" / "paper_reader.py"))

    def test_resume_uses_retained_runtime_snapshot_after_newer_install(self):
        self.write_install_state(self.new_id)
        self.write_prepared("0.1.0")
        self.write_execution(self.old_id)

        result, commands = self.invoke(["prepare", str(self.pdf), "--work", str(self.work)])

        self.assertEqual(result, 0)
        self.assertEqual(len(commands), 1)
        self.assertNotEqual(commands[0][0][-1:], ["update"])
        self.assertEqual(commands[0][0][0], str(self.tool_dir / "runtimes" / self.old_id / "venv" / "bin" / "python"))
        self.assertEqual(commands[0][0][1], str(self.tool_dir / "runtimes" / self.old_id / "source_snapshot" / "scripts" / "paper_reader.py"))

    def test_resume_rejects_processor_version_mismatch_before_execution(self):
        self.write_prepared("0.2.0")
        self.write_execution(self.old_id)

        with patch.object(runner, "ROOT", self.skill), patch.object(runner.subprocess, "run") as run:
            with self.assertRaisesRegex(ValueError, "버전"):
                runner.main(["validate", "--work", str(self.work), "--annotations", str(self.base / "annotations.json")])

        run.assert_not_called()

    def test_source_checkout_uses_its_development_processor_without_update(self):
        source = self.base / "source-checkout"
        (source / "scripts").mkdir(parents=True)
        processor = source / "scripts" / "paper_reader.py"
        processor.write_text("# source fixture\n", encoding="utf-8")

        result, commands = self.invoke_source(source)

        self.assertEqual(result, 0)
        self.assertEqual(len(commands), 1)
        self.assertEqual(commands[0][0][0], sys.executable)
        self.assertEqual(commands[0][0][1], str(processor))
        self.assertFalse(any(command[-1:] == ["update"] for command, _ in commands))

    def invoke_source(self, source):
        commands = []

        def fake_run(command, **kwargs):
            commands.append((command, kwargs))
            return subprocess.CompletedProcess(command, 0)

        with patch.object(runner, "ROOT", source), patch.object(runner.subprocess, "run", fake_run):
            result = runner.main(["prepare", str(self.pdf), "--work", str(self.work)])
        return result, commands


if __name__ == "__main__":
    unittest.main()
