from __future__ import annotations

import copy
import json
import py_compile
import shlex
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
        self.assertLess(
            text.index('if ! wait_for_http "http://127.0.0.1:${PORT}/"'),
            text.index('"$LIVEWARE_BIN" tunnel bind "$APP_ID"'),
        )
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
        existing = self.module.render_start(READY)
        existing = "# preserve-prefix\r\n" + existing + "# preserve-suffix\n"
        existing = existing.replace(
            self.module.BEGIN_BINDING,
            "echo preserve-before-binding\n" + self.module.BEGIN_BINDING,
        )
        existing = existing.replace(
            '"$LIVEWARE_BIN" tunnel bind "$APP_ID" "http://127.0.0.1:${PORT}"',
            "echo obsolete-binding",
        )
        text = self.module.render_start(READY, existing=existing)
        expected = existing.replace(
            "echo obsolete-binding",
            '"$LIVEWARE_BIN" tunnel bind "$APP_ID" "http://127.0.0.1:${PORT}"',
        )
        self.assertEqual(text, expected)

    def test_repair_rejects_an_adapter_that_differs_from_current_analysis(self) -> None:
        existing = self.module.render_start(READY).replace(
            "SERVER_COMMAND=(python3 server.py --port \"${PORT}\")",
            "SERVER_COMMAND=(node stale-server.js)",
        )
        with self.assertRaisesRegex(ValueError, "does not match current analysis"):
            self.module.render_start(READY, existing=existing)

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

    def test_repair_rejects_missing_duplicate_fake_reordered_or_nested_markers(self) -> None:
        base = self.module.render_start(READY)
        cases = {
            "missing": base.replace(self.module.END_BINDING, "", 1),
            "duplicate": base.replace(
                self.module.BEGIN_BINDING,
                self.module.BEGIN_BINDING + "\n" + self.module.BEGIN_BINDING,
                1,
            ),
            "fake": base.replace(
                self.module.BEGIN_BINDING,
                "echo " + self.module.BEGIN_BINDING,
                1,
            ),
            "reordered": "\n".join(
                (
                    self.module.BEGIN_BINDING,
                    "echo binding",
                    self.module.END_BINDING,
                    self.module.BEGIN_ADAPTER,
                    "echo adapter",
                    self.module.END_ADAPTER,
                    "",
                )
            ),
            "nested": "\n".join(
                (
                    self.module.BEGIN_ADAPTER,
                    self.module.BEGIN_BINDING,
                    self.module.END_ADAPTER,
                    self.module.END_BINDING,
                    "",
                )
            ),
            "indented": base.replace(
                self.module.BEGIN_BINDING,
                "  " + self.module.BEGIN_BINDING,
                1,
            ),
        }
        for name, existing in cases.items():
            with self.subTest(name=name):
                with self.assertRaisesRegex(ValueError, "marker"):
                    self.module.render_start(READY, existing=existing)

    def test_analysis_shell_values_are_encoded_as_data(self) -> None:
        analysis = copy.deepcopy(READY)
        analysis["adapter"]["command"] = [
            "python3",
            "server; echo injected",
            "--label",
            '$(touch "/tmp/not-created")',
            "--port",
            "{port}",
        ]
        analysis["adapter"]["required_commands"] = ["python3", "tool; echo injected"]
        analysis["adapter"]["workdir"] = "liveware/a dir;$(touch pwn)"
        analysis["adapter"]["readiness"] = {
            "kind": "http",
            "url": 'http://127.0.0.1:{port}/health?probe=$(touch+pwn)&label="x"',
        }
        analysis["adapter"]["log"] = {
            "owner": "generated-start",
            "path": "${HOME}/.clawling/apps/log $(pwn).txt",
        }

        text = self.module.render_start(analysis)

        for value in analysis["adapter"]["command"][:-1]:
            self.assertIn(shlex.quote(value), text)
        self.assertIn(shlex.quote("tool; echo injected"), text)
        self.assertIn('cd "$SKILL_ROOT/liveware/a dir;\\$(touch pwn)"', text)
        self.assertIn(
            'http://127.0.0.1:${PORT}/health?probe=\\$(touch+pwn)&label=\\"x\\"',
            text,
        )
        self.assertIn('SERVER_LOG="${HOME}/.clawling/apps/log \\$(pwn).txt"', text)
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "start.sh"
            path.write_text(text, encoding="utf-8")
            result = subprocess.run(["bash", "-n", str(path)], capture_output=True, text=True, check=False)
        self.assertEqual(result.returncode, 0, result.stderr)

    def test_control_characters_are_rejected_in_every_shell_derived_field(self) -> None:
        cases: list[tuple[str, dict[str, object]]] = []

        skill_name = copy.deepcopy(READY)
        skill_name["skill_name"] = "sample\nskill"
        cases.append(("skill_name", skill_name))

        command = copy.deepcopy(READY)
        command["adapter"]["command"][1] = "server\n.py"
        cases.append(("command", command))

        required = copy.deepcopy(READY)
        required["adapter"]["required_commands"] = ["python3\n"]
        cases.append(("required_command", required))

        workdir = copy.deepcopy(READY)
        workdir["adapter"]["workdir"] = "liveware\nelsewhere"
        cases.append(("workdir", workdir))

        readiness = copy.deepcopy(READY)
        readiness["adapter"]["readiness"]["url"] += "\nextra"
        cases.append(("readiness", readiness))

        log_path = copy.deepcopy(READY)
        log_path["adapter"]["log"]["path"] += "\nextra"
        cases.append(("log_path", log_path))

        static_dir = copy.deepcopy(READY)
        static_dir["adapter"] = {
            "kind": "static",
            "workdir": "liveware/static",
            "command": [],
            "required_commands": [],
            "default_port": None,
            "readiness": None,
            "log": {"owner": "target", "path": None},
        }
        static_dir["static_dir"] = "liveware/static\nelsewhere"
        cases.append(("static_dir", static_dir))

        for name, analysis in cases:
            with self.subTest(name=name):
                with self.assertRaisesRegex(ValueError, "control character"):
                    self.module.render_start(analysis)

    def test_malformed_adapter_mappings_raise_value_error(self) -> None:
        missing = copy.deepcopy(READY)
        del missing["adapter"]

        unknown = copy.deepcopy(READY)
        unknown["adapter"]["kind"] = "invented"

        bool_port = copy.deepcopy(READY)
        bool_port["adapter"]["default_port"] = True

        tuple_command = copy.deepcopy(READY)
        tuple_command["adapter"]["command"] = ("python3", "server.py")

        missing_readiness = copy.deepcopy(READY)
        missing_readiness["adapter"]["readiness"] = None

        external_command = copy.deepcopy(READY)
        external_command["adapter"] = {
            "kind": "external",
            "workdir": ".",
            "command": ["python3", "server.py"],
            "required_commands": [],
            "default_port": 9000,
            "readiness": {"kind": "http", "url": "http://127.0.0.1:{port}/healthz"},
            "log": {"owner": "target", "path": None},
        }

        launcher_log_owner = copy.deepcopy(READY)
        launcher_log_owner["adapter"] = {
            "kind": "existing-launcher",
            "workdir": ".",
            "command": ["bash", "scripts/start-server.sh"],
            "required_commands": ["bash"],
            "default_port": 9000,
            "readiness": {"kind": "http", "url": "http://127.0.0.1:{port}/healthz"},
            "log": {"owner": "generated-start", "path": "${HOME}/launcher.log"},
        }

        static_command = copy.deepcopy(READY)
        static_command["adapter"] = {
            "kind": "static",
            "workdir": "liveware/static",
            "command": ["python3", "server.py"],
            "required_commands": [],
            "default_port": None,
            "readiness": None,
            "log": {"owner": "target", "path": None},
        }

        cases = {
            "missing": missing,
            "not_mapping": {**READY, "adapter": "managed-command"},
            "unknown_kind": unknown,
            "bool_port": bool_port,
            "tuple_command": tuple_command,
            "missing_readiness": missing_readiness,
            "external_command": external_command,
            "launcher_log_owner": launcher_log_owner,
            "static_command": static_command,
        }
        for name, analysis in cases.items():
            with self.subTest(name=name):
                with self.assertRaises(ValueError):
                    self.module.render_start(analysis)

    def test_dynamic_readiness_requires_exact_loopback_placeholder_structure(self) -> None:
        urls = (
            "https://127.0.0.1:{port}/healthz",
            "http://localhost:{port}/healthz",
            "http://127.0.0.1:9000/healthz",
            "http://127.0.0.1:{port}",
            "http://127.0.0.1:{port}/healthz/{port}",
        )
        for url in urls:
            with self.subTest(url=url):
                analysis = copy.deepcopy(READY)
                analysis["adapter"]["readiness"]["url"] = url
                with self.assertRaisesRegex(ValueError, "readiness|loopback"):
                    self.module.render_start(analysis)

    def test_cli_requires_non_empty_string_target_root_even_for_cwd(self) -> None:
        cases = {"missing": object(), "empty": "", "null": None, "integer": 7}
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            for name, value in cases.items():
                with self.subTest(name=name):
                    analysis = copy.deepcopy(READY)
                    if name == "missing":
                        del analysis["target_root"]
                    else:
                        analysis["target_root"] = value
                    analysis_path = root / f"{name}.json"
                    analysis_path.write_text(json.dumps(analysis, ensure_ascii=False), encoding="utf-8")
                    result = subprocess.run(
                        [sys.executable, self.module.__file__, str(Path.cwd()), str(analysis_path)],
                        capture_output=True,
                        text=True,
                        check=False,
                    )
                    self.assertNotEqual(result.returncode, 0)
                    self.assertIn("target_root must be a non-empty string", result.stderr)

    def test_cli_rejects_symlinked_or_escaping_script_paths_before_io(self) -> None:
        for kind in ("liveware_parent", "scripts_parent", "start_file", "setup_file"):
            with self.subTest(kind=kind), tempfile.TemporaryDirectory() as tmp:
                root = Path(tmp)
                target = root / "target"
                outside = root / "outside"
                target.mkdir()
                outside.mkdir()
                if kind == "liveware_parent":
                    (target / "liveware").symlink_to(outside, target_is_directory=True)
                elif kind == "scripts_parent":
                    (target / "liveware").mkdir()
                    (target / "liveware" / "scripts").symlink_to(outside, target_is_directory=True)
                else:
                    scripts = target / "liveware" / "scripts"
                    scripts.mkdir(parents=True)
                    outside_file = outside / f"{kind}.txt"
                    if kind == "start_file":
                        outside_file.write_text(self.module.render_start(READY), encoding="utf-8")
                        (scripts / "start.sh").symlink_to(outside_file)
                    else:
                        outside_file.write_text("outside setup\n", encoding="utf-8")
                        (scripts / "setup.py").symlink_to(outside_file)
                before_paths = sorted(str(path.relative_to(outside)) for path in outside.rglob("*"))
                before_files = {
                    str(path.relative_to(outside)): path.read_bytes()
                    for path in outside.rglob("*")
                    if path.is_file()
                }
                analysis = {**copy.deepcopy(READY), "target_root": str(target)}
                analysis_path = root / "analysis.json"
                analysis_path.write_text(json.dumps(analysis, ensure_ascii=False), encoding="utf-8")

                result = subprocess.run(
                    [sys.executable, self.module.__file__, str(target), str(analysis_path), "--apply"],
                    capture_output=True,
                    text=True,
                    check=False,
                )

                self.assertNotEqual(result.returncode, 0)
                self.assertRegex(result.stderr, "symlink|escape")
                self.assertEqual(
                    sorted(str(path.relative_to(outside)) for path in outside.rglob("*")),
                    before_paths,
                )
                self.assertEqual(
                    {
                        str(path.relative_to(outside)): path.read_bytes()
                        for path in outside.rglob("*")
                        if path.is_file()
                    },
                    before_files,
                )

    def test_all_adapter_variants_pass_bash_syntax_without_execution(self) -> None:
        managed = copy.deepcopy(READY)
        existing = copy.deepcopy(READY)
        existing["adapter"] = {
            "kind": "existing-launcher",
            "workdir": ".",
            "command": ["bash", "scripts/start-server.sh"],
            "required_commands": ["bash"],
            "default_port": 9000,
            "readiness": {"kind": "http", "url": "http://127.0.0.1:{port}/healthz"},
            "log": {"owner": "target", "path": None},
        }
        external = copy.deepcopy(READY)
        external["adapter"] = {
            "kind": "external",
            "workdir": ".",
            "command": [],
            "required_commands": [],
            "default_port": 9000,
            "readiness": {"kind": "http", "url": "http://127.0.0.1:{port}/healthz"},
            "log": {"owner": "target", "path": None},
        }
        static = copy.deepcopy(READY)
        static["adapter"] = {
            "kind": "static",
            "workdir": "liveware/static",
            "command": [],
            "required_commands": [],
            "default_port": None,
            "readiness": None,
            "log": {"owner": "target", "path": None},
        }
        static["static_dir"] = "liveware/static"

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            for name, analysis in {
                "managed-command": managed,
                "existing-launcher": existing,
                "external": external,
                "static": static,
            }.items():
                with self.subTest(kind=name):
                    path = root / f"{name}.sh"
                    path.write_text(self.module.render_start(analysis), encoding="utf-8")
                    result = subprocess.run(
                        ["bash", "-n", str(path)],
                        capture_output=True,
                        text=True,
                        check=False,
                    )
                    self.assertEqual(result.returncode, 0, result.stderr)


if __name__ == "__main__":
    unittest.main()
