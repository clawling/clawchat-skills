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

    def test_preview_prints_both_scripts_without_writing_them(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            target = root / "target"
            analysis_path = root / "analysis.json"
            analysis = {**READY, "target_root": str(target)}
            analysis_path.write_text(json.dumps(analysis, ensure_ascii=False), encoding="utf-8")

            result = subprocess.run(
                [sys.executable, self.module.__file__, str(target), str(analysis_path)],
                capture_output=True,
                text=True,
                check=False,
            )

            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertEqual(
                json.loads(result.stdout),
                {
                    "setup.py": self.module.render_setup(analysis),
                    "start.sh": self.module.render_start(analysis),
                },
            )
            self.assertFalse((target / "liveware" / "scripts" / "setup.py").exists())
            self.assertFalse((target / "liveware" / "scripts" / "start.sh").exists())

    def test_apply_atomically_replaces_both_fixed_script_paths_with_mode_0755(self) -> None:
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
            analysis = {**READY, "target_root": str(target)}
            analysis_path.write_text(json.dumps(analysis, ensure_ascii=False), encoding="utf-8")

            result = subprocess.run(
                [sys.executable, self.module.__file__, str(target), str(analysis_path), "--apply"],
                capture_output=True,
                text=True,
                check=False,
            )

            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertEqual(result.stdout, "")
            start = scripts / "start.sh"
            self.assertEqual(setup.read_text(encoding="utf-8"), self.module.render_setup(analysis))
            self.assertEqual(start.read_text(encoding="utf-8"), self.module.render_start(analysis))
            self.assertEqual(stat.S_IMODE(setup.stat().st_mode), 0o755)
            self.assertEqual(stat.S_IMODE(start.stat().st_mode), 0o755)
            self.assertNotEqual(setup.stat().st_ino, stale_inode)
            self.assertEqual(sorted(path.name for path in scripts.iterdir()), ["setup.py", "start.sh"])

    def test_dynamic_start_preserves_command_and_waits_before_loopback_bind(self) -> None:
        text = self.module.render_start(READY)
        self.assertIn('PORT="${PORT:-5080}"', text)
        self.assertIn("SERVER_COMMAND=(python3 server.py --port \"${PORT}\")", text)
        self.assertIn("wait_for_http", text)
        self.assertIn('tunnel bind "$APP_ID" "http://127.0.0.1:${PORT}"', text)
        self.assertNotIn("npm install", text)
        self.assertNotIn("pip install", text)
        self.assertNotIn("kill ", text)

    def test_static_start_uses_bind_static_and_never_starts_a_server(self) -> None:
        analysis = dict(READY)
        analysis["adapter"] = {
            "kind": "static",
            "workdir": "liveware/static",
            "command": [],
            "required_commands": [],
            "default_port": None,
            "readiness": None,
            "log": {"owner": "target", "path": None},
        }
        analysis["static_dir"] = "liveware/static"
        text = self.module.render_start(analysis)
        self.assertIn('tunnel bind-static "$APP_ID" "$SKILL_ROOT/liveware/static"', text)
        self.assertNotIn("SERVER_COMMAND=", text)

    def test_repair_replaces_only_the_standard_binding_block(self) -> None:
        existing = """#!/usr/bin/env bash
# BEGIN TARGET SERVER ADAPTER
echo custom-server-adapter
# END TARGET SERVER ADAPTER
# BEGIN LIVEWARE BINDING
echo obsolete-binding
# END LIVEWARE BINDING
"""
        text = self.module.render_start(READY, existing=existing)
        self.assertIn("echo custom-server-adapter", text)
        self.assertNotIn("obsolete-binding", text)
        self.assertIn('tunnel bind "$APP_ID"', text)

    def test_existing_launcher_is_invoked_without_replacing_its_lifecycle(self) -> None:
        analysis = dict(READY)
        analysis["adapter"] = {
            "kind": "existing-launcher",
            "workdir": ".",
            "command": ["bash", "scripts/start-server.sh"],
            "required_commands": ["bash"],
            "default_port": 9000,
            "readiness": {"kind": "http", "url": "http://127.0.0.1:{port}/healthz"},
            "log": {"owner": "target", "path": None},
        }
        text = self.module.render_start(analysis)
        self.assertIn("SERVER_COMMAND=(bash scripts/start-server.sh)", text)
        self.assertIn('"${SERVER_COMMAND[@]}"', text)
        self.assertNotIn("SERVER_LOG=", text)

    def test_external_service_is_checked_but_never_started(self) -> None:
        analysis = dict(READY)
        analysis["adapter"] = {
            "kind": "external",
            "workdir": ".",
            "command": [],
            "required_commands": [],
            "default_port": 9000,
            "readiness": {"kind": "http", "url": "http://127.0.0.1:{port}/healthz"},
            "log": {"owner": "target", "path": None},
        }
        text = self.module.render_start(analysis)
        self.assertIn("Target service is externally managed", text)
        self.assertNotIn("SERVER_COMMAND=", text)
        self.assertIn("wait_for_http", text)

    def test_rendered_start_passes_bash_syntax_without_execution(self) -> None:
        import subprocess
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "start.sh"
            path.write_text(self.module.render_start(READY), encoding="utf-8")
            result = subprocess.run(["bash", "-n", str(path)], capture_output=True, text=True, check=False)
        self.assertEqual(result.returncode, 0, result.stderr)


if __name__ == "__main__":
    unittest.main()
