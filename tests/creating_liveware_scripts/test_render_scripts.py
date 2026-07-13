from __future__ import annotations

import json
import py_compile
import stat
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

from tests.creating_liveware_scripts.helpers import load_skill_script


READY = {
    "schema_version": 1,
    "status": "ready",
    "target_root": "/tmp/sample-skill",
    "skill_name": "sample-skill",
    "display_name": "示例应用",
    "adapter": {
        "kind": "managed-command",
        "workdir": "liveware",
        "command": ["python3", "server.py", "--port", "{port}"],
        "required_commands": ["python3"],
        "default_port": 5080,
        "readiness": {"kind": "http", "url": "http://127.0.0.1:{port}/"},
        "log": {"owner": "generated-start", "path": "$HOME/.clawling/apps/sample-skill.server.log"},
    },
    "static_dir": "liveware/static",
    "evidence": [],
    "issues": [],
}


class RenderSetupTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.module = load_skill_script("render_scripts")

    def test_setup_embeds_identity_without_translating_display_name(self) -> None:
        text = self.module.render_setup(READY)
        self.assertIn('SKILL_NAME = "sample-skill"', text)
        self.assertIn('CLAWCHAT_APP_NAME = "示例应用"', text)
        self.assertEqual(text.count('"app_name": SKILL_NAME'), 2)
        self.assertNotIn('"app_name": CLAWCHAT_APP_NAME', text)
        self.assertIn('STATE_ROOT = Path.home() / ".clawling" / "apps"', text)

    def test_setup_falls_back_to_skill_name_when_display_name_is_missing(self) -> None:
        analysis = {key: value for key, value in READY.items() if key != "display_name"}
        try:
            text = self.module.render_setup(analysis)
        except KeyError as exc:
            self.fail(f"render_setup did not apply the display-name fallback: {exc}")
        self.assertIn('CLAWCHAT_APP_NAME = "sample-skill"', text)

    def test_setup_guards_non_object_state_before_field_access(self) -> None:
        text = self.module.render_setup(READY)
        load_state = text.index("def load_state()")
        guard_marker = "if not isinstance(state, dict):"
        self.assertIn(guard_marker, text[load_state:])
        guard = text.index(guard_marker, load_state)
        field_access = text.index("state.get(", load_state)
        self.assertLess(guard, field_access)
        self.assertIn(
            'raise fail(f"State file is invalid: {STATE_FILE}")',
            text[guard:field_access],
        )

    def test_setup_uses_plugin_login_exact_recovery_and_atomic_state(self) -> None:
        text = self.module.render_setup(READY)
        self.assertIn("await tools.liveware_login()", text)
        self.assertIn('run_liveware(binary, "app", "inspect", app_id)', text)
        self.assertIn('run_liveware(binary, "app", "list", "--json")', text)
        self.assertIn('"--agent-type", "hermes"', text)
        self.assertIn("os.replace(temp_name, STATE_FILE)", text)
        self.assertNotIn("shell=True", text)
        self.assertNotIn("token", text.lower())

    def test_rendered_setup_compiles_without_execution(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "setup.py"
            path.write_text(self.module.render_setup(READY), encoding="utf-8")
            py_compile.compile(str(path), doraise=True)

    def test_setup_rendering_is_deterministic(self) -> None:
        reordered = dict(reversed(list(READY.items())))
        self.assertEqual(self.module.render_setup(READY), self.module.render_setup(reordered))

    def test_setup_rejects_non_ready_or_unresolved_analysis(self) -> None:
        cases = (
            ({**READY, "status": "blocked"}, "status ready"),
            ({**READY, "issues": [{"code": "unresolved"}]}, "unresolved issues"),
        )
        for analysis, message in cases:
            with self.subTest(message=message):
                with self.assertRaisesRegex(ValueError, message):
                    self.module.render_setup(analysis)

    def test_preview_prints_setup_without_writing_scripts(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            target = root / "target"
            analysis_path = root / "analysis.json"
            analysis_path.write_text(json.dumps(READY, ensure_ascii=False), encoding="utf-8")

            result = subprocess.run(
                [sys.executable, self.module.__file__, str(target), str(analysis_path)],
                capture_output=True,
                text=True,
                check=False,
            )

            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertEqual(result.stdout, self.module.render_setup(READY) + "\n")
            self.assertFalse((target / "liveware" / "scripts" / "setup.py").exists())
            self.assertFalse((target / "liveware" / "scripts" / "start.sh").exists())

    def test_apply_atomically_replaces_fixed_setup_path_with_mode_0755(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            target = root / "target"
            scripts = target / "liveware" / "scripts"
            scripts.mkdir(parents=True)
            setup = scripts / "setup.py"
            setup.write_text("stale\n", encoding="utf-8")
            setup.chmod(0o600)
            stale_inode = setup.stat().st_ino
            analysis_path = root / "analysis.json"
            analysis_path.write_text(json.dumps(READY, ensure_ascii=False), encoding="utf-8")

            result = subprocess.run(
                [sys.executable, self.module.__file__, str(target), str(analysis_path), "--apply"],
                capture_output=True,
                text=True,
                check=False,
            )

            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertEqual(result.stdout, "")
            self.assertEqual(setup.read_text(encoding="utf-8"), self.module.render_setup(READY))
            self.assertEqual(stat.S_IMODE(setup.stat().st_mode), 0o755)
            self.assertNotEqual(setup.stat().st_ino, stale_inode)
            self.assertEqual([path.name for path in scripts.iterdir()], ["setup.py"])
            self.assertFalse((scripts / "start.sh").exists())


if __name__ == "__main__":
    unittest.main()
