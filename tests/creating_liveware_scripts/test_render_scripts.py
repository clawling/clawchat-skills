from __future__ import annotations

import base64
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

from tests.creating_liveware_scripts.helpers import load_skill_script, write_target


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
        cls.analyzer = load_skill_script("analyze_target")
        cls.validator = load_skill_script("validate_scripts")

    def assert_bash_syntax(self, text: str) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "start.sh"
            path.write_text(text, encoding="utf-8")
            result = subprocess.run(["bash", "-n", str(path)], capture_output=True, text=True, check=False)
        self.assertEqual(result.returncode, 0, result.stderr)

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

    def test_analysis_manifest_is_canonical_unicode_and_embedded_once(self) -> None:
        analysis = copy.deepcopy(READY)
        analysis["display_name"] = "星月 🌙"

        payload = self.module.encode_analysis_manifest(analysis)
        expected = json.dumps(
            analysis,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")
        self.assertEqual(base64.urlsafe_b64decode(payload), expected)
        self.assertEqual(self.module.decode_analysis_manifest(payload), analysis)

        marker = f"# LIVEWARE ANALYSIS V1: {payload}"
        setup = self.module.render_setup(analysis)
        start = self.module.render_start(analysis)
        self.assertEqual(setup.count(marker), 1)
        self.assertEqual(start.count(marker), 1)
        self.assertEqual(self.module.extract_analysis_manifest(setup), analysis)
        self.assertEqual(self.module.extract_analysis_manifest(start), analysis)

    def test_manifest_decoder_rejects_every_corrupt_contract_class(self) -> None:
        def encoded(value: object, *, canonical: bool = True) -> str:
            if canonical:
                raw = json.dumps(
                    value,
                    ensure_ascii=False,
                    sort_keys=True,
                    separators=(",", ":"),
                ).encode("utf-8")
            else:
                raw = json.dumps(value, ensure_ascii=False).encode("utf-8")
            return base64.urlsafe_b64encode(raw).decode("ascii")

        duplicate_key_json = json.dumps(
            READY,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        ).replace('"schema_version":1', '"schema_version":1,"schema_version":1')
        cases = {
            "malformed-base64": "%%%",
            "invalid-utf8": base64.urlsafe_b64encode(b"\xff").decode("ascii"),
            "non-object": encoded([READY]),
            "non-v1": encoded({**READY, "schema_version": 2}),
            "boolean-v1": encoded({**READY, "schema_version": True}),
            "float-v1": encoded({**READY, "schema_version": 1.0}),
            "non-ready": encoded({**READY, "status": "blocked"}),
            "issues": encoded({**READY, "issues": [{"code": "blocked"}]}),
            "noncanonical": encoded(READY, canonical=False),
            "non-json-number": encoded({**READY, "bad": float("nan")}),
            "duplicate-json-key": base64.urlsafe_b64encode(
                duplicate_key_json.encode("utf-8")
            ).decode("ascii"),
        }
        for name, payload in cases.items():
            with self.subTest(name=name):
                with self.assertRaises(ValueError):
                    self.module.decode_analysis_manifest(payload)

        marker = f"# LIVEWARE ANALYSIS V1: {encoded(READY)}"
        with self.assertRaisesRegex(ValueError, "exactly one"):
            self.module.extract_analysis_manifest("plain text\n")
        with self.assertRaisesRegex(ValueError, "exactly one"):
            self.module.extract_analysis_manifest(f"{marker}\n{marker}\n")

    def test_manifest_schema_rejects_every_unknown_top_level_property_uniformly(self) -> None:
        prior_credential_reports = (
            "token",
            "accessToken",
            "password",
            "passWord",
            "pass_word",
            "pass-word",
            "passwd",
            "passWd",
            "pass_wd",
            "passphrase",
            "passPhrase",
            "pass_phrase",
            "pass-phrase",
            "clientSecret",
            "clientsecret",
            "refreshToken",
            "refreshtoken",
            "authToken",
            "authtoken",
            "bearerToken",
            "bearertoken",
            "api_key",
            "access_key",
            "access-key",
            "accessKeyId",
            "accesskeyid",
            "private_key",
            "authorization",
            "auth_key",
            "authHeader",
            "credential",
            "token2",
            "tokens",
            "secrets",
            "passwords",
            "passphrases",
            "accessKeys",
            "apiKeys",
            "privateKeys",
            "secret2",
            "password2",
            "clientsecret2",
            "authcode",
            "auth_code",
            "authCode",
            "authorizationcode",
            "authorization_code",
            "authorizationCode",
            "credentials",
            "clientCredentials",
            "refreshTokens",
            "apiSecrets",
            "accessKeys2",
            "apikeys3",
            "privatekeys4",
        )
        benign_extensions = (
            "author",
            "authority",
            "tokenizer",
            "tokenization",
            "secretary",
            "secretariat",
            "privateKeyboard",
            "metadata",
        )
        for key in prior_credential_reports + benign_extensions:
            with self.subTest(key=key):
                with self.assertRaisesRegex(ValueError, "schema|additional|property"):
                    self.module.encode_analysis_manifest({**READY, key: "do-not-embed"})

    def test_manifest_schema_allows_sensitive_words_only_as_allowed_text_values(self) -> None:
        analysis = copy.deepcopy(READY)
        words = (
            "token password secret credential api_key accessToken author authority "
            "tokenizer secretary privateKeyboard"
        )
        analysis["display_name"] = words
        analysis["evidence"] = [{"path": "SKILL.md", "reason": words}]

        payload = self.module.encode_analysis_manifest(analysis)

        self.assertEqual(self.module.decode_analysis_manifest(payload), analysis)

    def test_manifest_schema_requires_every_analyzer_top_level_property(self) -> None:
        required = {
            "schema_version",
            "status",
            "target_root",
            "skill_name",
            "adapter",
            "static_dir",
            "evidence",
            "issues",
        }
        for key in required:
            with self.subTest(key=key):
                analysis = copy.deepcopy(READY)
                del analysis[key]
                with self.assertRaisesRegex(ValueError, "schema|required|property"):
                    self.module.encode_analysis_manifest(analysis)

        without_display_name = copy.deepcopy(READY)
        del without_display_name["display_name"]
        self.assertEqual(
            self.module.decode_analysis_manifest(
                self.module.encode_analysis_manifest(without_display_name)
            ),
            without_display_name,
        )

    def test_manifest_schema_requires_exact_adapter_readiness_and_log_properties(self) -> None:
        object_cases: list[tuple[str, tuple[str, ...], str]] = []
        for key in (
            "kind",
            "workdir",
            "command",
            "required_commands",
            "default_port",
            "readiness",
            "log",
        ):
            object_cases.append(("adapter-missing", ("adapter", key), "missing"))
        object_cases.append(("adapter-extra", ("adapter", "extension"), "extra"))
        for key in ("kind", "url"):
            object_cases.append(("readiness-missing", ("adapter", "readiness", key), "missing"))
        object_cases.append(("readiness-extra", ("adapter", "readiness", "extension"), "extra"))
        for key in ("owner", "path"):
            object_cases.append(("log-missing", ("adapter", "log", key), "missing"))
        object_cases.append(("log-extra", ("adapter", "log", "extension"), "extra"))

        for layer, path, mutation in object_cases:
            with self.subTest(layer=layer, path=path):
                analysis = copy.deepcopy(READY)
                parent: dict[str, object] = analysis
                for key in path[:-1]:
                    child = parent[key]
                    self.assertIsInstance(child, dict)
                    parent = child
                if mutation == "missing":
                    del parent[path[-1]]
                else:
                    parent[path[-1]] = "not allowed"
                with self.assertRaisesRegex(ValueError, "schema|required|additional|property"):
                    self.module.encode_analysis_manifest(analysis)

    def test_manifest_schema_requires_exact_evidence_objects(self) -> None:
        valid = copy.deepcopy(READY)
        valid["evidence"] = [{"path": "SKILL.md", "reason": "Stable skill identity"}]
        self.assertEqual(
            self.module.decode_analysis_manifest(self.module.encode_analysis_manifest(valid)),
            valid,
        )

        cases = {
            "not-list": {"path": "SKILL.md", "reason": "identity"},
            "not-object": ["SKILL.md"],
            "missing-path": [{"reason": "identity"}],
            "missing-reason": [{"path": "SKILL.md"}],
            "extra": [{"path": "SKILL.md", "reason": "identity", "source": "agent"}],
            "path-not-string": [{"path": 1, "reason": "identity"}],
            "reason-not-string": [{"path": "SKILL.md", "reason": True}],
        }
        for name, evidence in cases.items():
            with self.subTest(name=name):
                analysis = copy.deepcopy(READY)
                analysis["evidence"] = evidence
                with self.assertRaisesRegex(ValueError, "evidence|schema|required|additional|property"):
                    self.module.encode_analysis_manifest(analysis)

        for path in ("/etc/passwd", "../outside", "evidence/../../outside"):
            with self.subTest(path=path):
                analysis = copy.deepcopy(READY)
                analysis["evidence"] = [{"path": path, "reason": "Untrusted path"}]
                with self.assertRaisesRegex(ValueError, "evidence|target-relative"):
                    self.module.encode_analysis_manifest(analysis)

    def test_manifest_schema_enforces_exact_numeric_types_on_schema_fields(self) -> None:
        for field, value in (
            ("schema_version", True),
            ("schema_version", 1.0),
            ("default_port", True),
            ("default_port", 5080.0),
        ):
            with self.subTest(field=field, value=value):
                analysis = copy.deepcopy(READY)
                if field == "schema_version":
                    analysis[field] = value
                else:
                    analysis["adapter"][field] = value
                with self.assertRaises(ValueError):
                    self.module.encode_analysis_manifest(analysis)

    def test_every_analyzer_produced_ready_shape_is_manifest_renderable(self) -> None:
        for kind in ("python", "static"):
            with self.subTest(kind=kind), tempfile.TemporaryDirectory() as tmp:
                target = write_target(Path(tmp), display_name="Sensitive token words are text")
                liveware = target / "liveware"
                if kind == "python":
                    liveware.mkdir()
                    (liveware / "server.py").write_text(
                        'DEFAULT_PORT = 5080\nROUTES = ["/healthz"]\n',
                        encoding="utf-8",
                    )
                else:
                    static = liveware / "static"
                    static.mkdir(parents=True)
                    (static / "index.html").write_text("<!doctype html>", encoding="utf-8")

                analysis = self.analyzer.analyze_target(
                    target,
                    which=lambda command: f"/bin/{command}",
                )
                self.assertEqual(analysis["status"], "ready")
                payload = self.module.encode_analysis_manifest(analysis)
                self.assertEqual(self.module.decode_analysis_manifest(payload), analysis)
                self.module.render_setup(analysis)
                self.assert_bash_syntax(self.module.render_start(analysis))

    def test_analyzer_node_candidate_is_not_manifest_renderable_without_confirmation(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            target = write_target(Path(tmp))
            liveware = target / "liveware"
            liveware.mkdir()
            (liveware / "package.json").write_text(
                json.dumps({"scripts": {"liveware": "node server.js"}}),
                encoding="utf-8",
            )
            (liveware / "server.js").write_text(
                "const port = process.env.PORT || 4173;\nserver.listen(port);\n",
                encoding="utf-8",
            )
            analysis = self.analyzer.analyze_target(target)

        self.assertEqual(analysis["status"], "ambiguous")
        with self.assertRaises(ValueError):
            self.module.render_start(analysis)

    def test_static_adapter_workdir_must_equal_static_dir(self) -> None:
        analysis = copy.deepcopy(READY)
        analysis["adapter"] = {
            "kind": "static",
            "workdir": "unrelated",
            "command": [],
            "required_commands": [],
            "default_port": None,
            "readiness": None,
            "log": {"owner": "target", "path": None},
        }
        analysis["static_dir"] = "liveware/static"

        with self.assertRaisesRegex(ValueError, "workdir|static_dir|Static"):
            self.module.encode_analysis_manifest(analysis)

    def test_target_root_must_have_one_lexical_canonical_form(self) -> None:
        for target_root in (
            "/tmp//sample-skill/.",
            "//tmp/sample-skill",
            "///tmp/sample-skill",
        ):
            with self.subTest(target_root=target_root):
                analysis = copy.deepcopy(READY)
                analysis["target_root"] = target_root
                with self.assertRaisesRegex(ValueError, "normalized"):
                    self.module.encode_analysis_manifest(analysis)

        root = copy.deepcopy(READY)
        root["target_root"] = "/"
        self.assertEqual(self.module.decode_analysis_manifest(
            self.module.encode_analysis_manifest(root)
        ), root)

    def test_template_substitution_is_one_pass_and_rejects_bad_template_shapes(self) -> None:
        replacements = {
            "@@FIRST@@": "@@SECOND@@",
            "@@SECOND@@": "literal @@ data",
        }
        self.assertEqual(
            self.module.render_template(
                "@@FIRST@@|@@SECOND@@",
                replacements,
                "Test",
            ),
            "@@SECOND@@|literal @@ data",
        )

        bad_templates = {
            "missing": "@@FIRST@@",
            "duplicate": "@@FIRST@@|@@SECOND@@|@@SECOND@@",
            "unknown": "@@FIRST@@|@@SECOND@@|@@UNKNOWN@@",
            "malformed": "@@FIRST@@|@@SECOND@@|@@",
        }
        for name, template in bad_templates.items():
            with self.subTest(name=name):
                with self.assertRaisesRegex(ValueError, "template|placeholder"):
                    self.module.render_template(template, replacements, "Test")

    def test_placeholder_like_setup_and_dynamic_adapter_data_remain_literal(self) -> None:
        analysis = copy.deepcopy(READY)
        analysis["display_name"] = "Literal @@DISPLAY_NAME@@, @@LIVEWARE_BINDING@@, and @@"
        analysis["adapter"]["command"] = [
            "python3",
            "@@LIVEWARE_BINDING@@",
            "argument@@value",
            "{port}",
        ]
        analysis["adapter"]["required_commands"] = [
            "python3",
            "tool@@LIVEWARE_BINDING@@",
        ]
        analysis["adapter"]["workdir"] = "liveware/@@TARGET_SERVER_ADAPTER@@/dir@@"
        analysis["adapter"]["readiness"]["url"] = (
            "http://127.0.0.1:{port}/@@LIVEWARE_BINDING@@/ready@@"
        )
        analysis["adapter"]["log"] = {
            "owner": "generated-start",
            "path": "${HOME}/.clawling/apps/@@SKILL_NAME@@/server@@.log",
        }

        setup = self.module.render_setup(analysis)
        start = self.module.render_start(analysis)

        self.assertIn(
            "CLAWCHAT_APP_NAME = " + json.dumps(analysis["display_name"], ensure_ascii=False),
            setup,
        )
        self.assertIn("@@LIVEWARE_BINDING@@", start)
        self.assertIn("argument@@value", start)
        self.assertIn(
            'SERVER_COMMAND=(python3 @@LIVEWARE_BINDING@@ argument@@value "${PORT}")',
            start,
        )
        self.assertIn("command -v -- tool@@LIVEWARE_BINDING@@", start)
        self.assertIn('cd -- "$SKILL_ROOT/liveware/@@TARGET_SERVER_ADAPTER@@/dir@@"', start)
        self.assertIn("http://127.0.0.1:${PORT}/@@LIVEWARE_BINDING@@/ready@@", start)
        self.assertIn(
            'SERVER_LOG="${HOME}/.clawling/apps/@@SKILL_NAME@@/server@@.log"',
            start,
        )
        self.assertEqual(self.module.extract_analysis_manifest(setup), analysis)
        self.assertEqual(self.module.extract_analysis_manifest(start), analysis)
        self.assertEqual(self.validator.validate_texts(setup, start, analysis=analysis), [])
        self.assert_bash_syntax(start)

        invalid_name = copy.deepcopy(analysis)
        invalid_name["skill_name"] = "@@SKILL_NAME@@"
        with self.assertRaisesRegex(ValueError, "skill identifier"):
            self.module.render_start(invalid_name)

    def test_placeholder_like_static_directory_remains_literal(self) -> None:
        analysis = copy.deepcopy(READY)
        static_dir = "liveware/@@LIVEWARE_BINDING@@/assets@@"
        analysis["adapter"] = {
            "kind": "static",
            "workdir": static_dir,
            "command": [],
            "required_commands": [],
            "default_port": None,
            "readiness": None,
            "log": {"owner": "target", "path": None},
        }
        analysis["static_dir"] = static_dir

        setup = self.module.render_setup(analysis)
        start = self.module.render_start(analysis)

        self.assertIn(
            '"$LIVEWARE_BIN" tunnel bind-static "$APP_ID" '
            '"$SKILL_ROOT/liveware/@@LIVEWARE_BINDING@@/assets@@"',
            start,
        )
        self.assertEqual(self.module.extract_analysis_manifest(start), analysis)
        self.assertEqual(self.validator.validate_texts(setup, start, analysis=analysis), [])
        self.assert_bash_syntax(start)

    def test_analysis_json_loader_rejects_duplicate_keys(self) -> None:
        duplicate = json.dumps(READY, ensure_ascii=False).replace(
            '"schema_version": 1',
            '"schema_version": 2, "schema_version": 1',
            1,
        )
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "analysis.json"
            path.write_text(duplicate, encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "duplicate"):
                self.module.load_analysis(path)

    def test_setup_rejects_non_ready_or_unresolved_analysis(self) -> None:
        cases = (
            ({**READY, "status": "blocked"}, "status ready"),
            ({**READY, "issues": [{"code": "unresolved"}]}, "unresolved issues"),
        )
        for analysis, message in cases:
            with self.subTest(message=message):
                with self.assertRaisesRegex(ValueError, message):
                    self.module.render_setup(analysis)

    def test_manifest_rendering_rejects_unsafe_or_malformed_identity_fields(self) -> None:
        cases = {
            "empty-skill": {**READY, "skill_name": ""},
            "escaping-skill": {**READY, "skill_name": "../../outside"},
            "uppercase-skill": {**READY, "skill_name": "Sample"},
            "non-string-display": {**READY, "display_name": 17},
            "empty-target": {**READY, "target_root": ""},
            "non-string-target": {**READY, "target_root": 17},
            "relative-target": {**READY, "target_root": "relative/skill"},
            "parent-target": {**READY, "target_root": "/tmp/skill/../other"},
            "control-target": {**READY, "target_root": "/tmp/skill\nother"},
        }
        for name, analysis in cases.items():
            with self.subTest(name=name):
                with self.assertRaises(ValueError):
                    self.module.render_setup(analysis)
                with self.assertRaises(ValueError):
                    self.module.render_start(analysis)

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

    def test_cli_repair_requires_existing_setup_and_start_manifest_pair(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            target = root / "target"
            scripts = target / "liveware" / "scripts"
            scripts.mkdir(parents=True)
            analysis = {**copy.deepcopy(READY), "target_root": str(target.resolve())}
            analysis_path = root / "analysis.json"
            analysis_path.write_text(json.dumps(analysis, ensure_ascii=False), encoding="utf-8")
            (scripts / "start.sh").write_text(self.module.render_start(analysis), encoding="utf-8")

            missing_setup = subprocess.run(
                [sys.executable, self.module.__file__, str(target), str(analysis_path), "--apply"],
                capture_output=True,
                text=True,
                check=False,
            )
            self.assertNotEqual(missing_setup.returncode, 0)
            self.assertIn("setup/start manifest pair", missing_setup.stderr)

            other = copy.deepcopy(analysis)
            other["display_name"] = "Other"
            (scripts / "setup.py").write_text(self.module.render_setup(other), encoding="utf-8")
            mismatched_setup = subprocess.run(
                [sys.executable, self.module.__file__, str(target), str(analysis_path), "--apply"],
                capture_output=True,
                text=True,
                check=False,
            )
            self.assertNotEqual(mismatched_setup.returncode, 0)
            self.assertIn("setup/start manifest pair", mismatched_setup.stderr)

            canonical_setup = self.module.render_setup(analysis)
            (scripts / "setup.py").write_text(
                canonical_setup.replace('SKILL_NAME = "sample-skill"', 'SKILL_NAME = "tampered"', 1),
                encoding="utf-8",
            )
            rebuilt_setup = subprocess.run(
                [sys.executable, self.module.__file__, str(target), str(analysis_path), "--apply"],
                capture_output=True,
                text=True,
                check=False,
            )
            self.assertEqual(rebuilt_setup.returncode, 0, rebuilt_setup.stderr)
            self.assertEqual((scripts / "setup.py").read_text(encoding="utf-8"), canonical_setup)

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

    def test_repair_replaces_only_binding_content_and_returns_canonical_script(self) -> None:
        existing = self.module.render_start(READY)
        existing = existing.replace(
            '"$LIVEWARE_BIN" tunnel bind "$APP_ID" "http://127.0.0.1:${PORT}"',
            "echo obsolete-binding",
        )
        text = self.module.render_start(READY, existing=existing)
        self.assertEqual(text, self.module.render_start(READY))

    def test_repair_rejects_every_byte_changed_outside_binding_content(self) -> None:
        base = self.module.render_start(READY)
        cases = {
            "prefix-comment": "# injected\n" + base,
            "suffix-comment": base + "# injected\n",
            "pre-binding-command": base.replace(
                self.module.BEGIN_BINDING,
                "echo injected\n" + self.module.BEGIN_BINDING,
                1,
            ),
            "adapter-command": base.replace(
                "SERVER_COMMAND=(python3 server.py --port \"${PORT}\")",
                "SERVER_COMMAND=(python3 other.py --port \"${PORT}\")",
                1,
            ),
        }
        for name, existing in cases.items():
            with self.subTest(name=name):
                with self.assertRaisesRegex(ValueError, "canonical scaffold"):
                    self.module.render_start(READY, existing=existing)

    def test_repair_rejects_manifest_that_differs_from_current_analysis(self) -> None:
        other = copy.deepcopy(READY)
        other["display_name"] = "Other"
        existing = self.module.render_start(other)
        with self.assertRaisesRegex(ValueError, "manifest.*current analysis"):
            self.module.render_start(READY, existing=existing)

    def test_repair_rejects_an_adapter_that_differs_from_current_analysis(self) -> None:
        existing = self.module.render_start(READY).replace(
            "SERVER_COMMAND=(python3 server.py --port \"${PORT}\")",
            "SERVER_COMMAND=(node stale-server.js)",
        )
        with self.assertRaisesRegex(ValueError, "canonical scaffold"):
            self.module.render_start(READY, existing=existing)

    def test_repair_rejects_stale_missing_or_duplicate_scaffold_identity(self) -> None:
        base = self.module.render_start(READY)
        skill_line = "SKILL_NAME=sample-skill"
        state_line = 'STATE_FILE="${HOME}/.clawling/apps/${SKILL_NAME}.json"'
        cases = {
            "stale_skill": base.replace(skill_line, "SKILL_NAME=other-skill", 1),
            "missing_skill": base.replace(skill_line + "\n", "", 1),
            "duplicate_skill": base.replace(skill_line, skill_line + "\n" + skill_line, 1),
            "stale_state": base.replace(
                state_line,
                'STATE_FILE="${HOME}/.clawling/apps/other-skill.json"',
                1,
            ),
            "missing_state": base.replace(state_line + "\n", "", 1),
            "duplicate_state": base.replace(state_line, state_line + "\n" + state_line, 1),
        }
        for name, existing in cases.items():
            with self.subTest(name=name):
                with self.assertRaisesRegex(ValueError, "canonical scaffold"):
                    self.module.render_start(READY, existing=existing)

    def test_repair_rejects_static_and_external_scaffold_identity_changes(self) -> None:
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
        for kind, analysis in {"static": static, "external": external}.items():
            with self.subTest(kind=kind):
                existing = self.module.render_start(analysis).replace(
                    "SKILL_NAME=sample-skill",
                    "SKILL_NAME=other-skill",
                    1,
                )
                with self.assertRaisesRegex(ValueError, "canonical scaffold"):
                    self.module.render_start(analysis, existing=existing)

    def test_existing_launcher_is_invoked_without_replacing_its_lifecycle(self) -> None:
        analysis = dict(READY)
        analysis["evidence"] = [
            {
                "path": "scripts/start-server.sh",
                "reason": "Command consumes exported PORT environment variable",
            }
        ]
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
        analysis["adapter"]["required_commands"] = ["python3", "tool-helper"]
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
        self.assertIn("command -v -- tool-helper", text)
        self.assertIn('cd -- "$SKILL_ROOT/liveware/a dir;\\$(touch pwn)"', text)
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

    def test_required_command_field_rejects_option_and_shell_syntax_names(self) -> None:
        values = (
            "-p",
            "$(touch-not-allowed)",
            "`touch-not-allowed`",
            "tool;echo-not-allowed",
            "tool with spaces",
            'tool"quote',
        )
        for value in values:
            with self.subTest(value=value):
                analysis = copy.deepcopy(READY)
                analysis["adapter"]["required_commands"] = [value]
                with self.assertRaisesRegex(ValueError, "Required command"):
                    self.module.render_start(analysis)

    def test_required_command_field_uses_option_terminator_for_valid_name(self) -> None:
        text = self.module.render_start(READY)
        self.assertIn("command -v -- python3", text)
        self.assert_bash_syntax(text)

    def test_workdir_field_encodes_shell_syntax_and_option_like_data(self) -> None:
        analysis = copy.deepcopy(READY)
        analysis["adapter"]["workdir"] = '-p $(nope) `nope` "quoted";semi'

        text = self.module.render_start(analysis)

        self.assertIn('cd -- "$SKILL_ROOT/-p \\$(nope) \\`nope\\` \\"quoted\\";semi"', text)
        self.assert_bash_syntax(text)

    def test_readiness_suffix_field_encodes_shell_syntax_as_data(self) -> None:
        analysis = copy.deepcopy(READY)
        analysis["adapter"]["readiness"]["url"] = (
            'http://127.0.0.1:{port}/health/-p?cmd=$(nope)&tick=`nope`&quote="x";semi'
        )

        text = self.module.render_start(analysis)

        self.assertIn(
            'http://127.0.0.1:${PORT}/health/-p?cmd=\\$(nope)&tick=\\`nope\\`&quote=\\"x\\";semi',
            text,
        )
        self.assert_bash_syntax(text)

    def test_generated_log_path_requires_a_normalized_absolute_or_home_path(self) -> None:
        valid_paths = (
            "/var/tmp/sample-skill.server.log",
            "$HOME/.clawling/apps/sample-skill.server.log",
            "${HOME}/.clawling/apps/sample-skill.server.log",
        )
        for log_path in valid_paths:
            with self.subTest(valid=log_path):
                analysis = copy.deepcopy(READY)
                analysis["adapter"]["log"] = {
                    "owner": "generated-start",
                    "path": log_path,
                }
                text = self.module.render_start(analysis)
                self.assertIn("SERVER_LOG=", text)
                self.assertIn('mkdir -p -- "$(dirname -- "$SERVER_LOG")"', text)
                self.assert_bash_syntax(text)

        invalid_paths = (
            "server.log",
            "logs/server.log",
            "$HOME/../server.log",
            "${HOME}/logs/../server.log",
            "/var/tmp/../server.log",
            "/var//tmp/server.log",
        )
        for log_path in invalid_paths:
            with self.subTest(invalid=log_path):
                analysis = copy.deepcopy(READY)
                analysis["adapter"]["log"] = {
                    "owner": "generated-start",
                    "path": log_path,
                }
                with self.assertRaisesRegex(ValueError, "log path|normalized|absolute"):
                    self.module.render_start(analysis)

    def test_command_port_placeholder_is_standalone_and_unique(self) -> None:
        for kind in ("managed-command", "existing-launcher"):
            for command in (
                ["python3", "server.py", "--port={port}"],
                ["python3", "server.py", "{port}", "{port}"],
            ):
                with self.subTest(kind=kind, command=command):
                    analysis = copy.deepcopy(READY)
                    analysis["adapter"]["kind"] = kind
                    analysis["adapter"]["command"] = command
                    analysis["adapter"]["log"] = {"owner": "target", "path": None}
                    with self.assertRaisesRegex(ValueError, "port.*placeholder|\{port\}"):
                        self.module.render_start(analysis)

    def test_dynamic_command_may_consume_exported_port_without_a_placeholder(self) -> None:
        for kind, command in (
            ("managed-command", ["npm", "run", "liveware"]),
            ("existing-launcher", ["bash", "scripts/start-liveware.sh"]),
        ):
            with self.subTest(kind=kind):
                analysis = copy.deepcopy(READY)
                analysis["adapter"]["kind"] = kind
                analysis["adapter"]["command"] = command
                analysis["adapter"]["required_commands"] = [command[0]]
                analysis["adapter"]["log"] = {"owner": "target", "path": None}
                analysis["evidence"] = [
                    {
                        "path": "liveware/package.json",
                        "reason": "Command consumes exported PORT environment variable",
                    }
                ]
                text = self.module.render_start(analysis)
                self.assertIn("export PORT", text)
                self.assert_bash_syntax(text)

    def test_zero_placeholder_requires_exact_exported_port_evidence(self) -> None:
        for evidence in (
            [],
            [{"path": "liveware/package.json", "reason": "Node server entrypoint"}],
            [
                {
                    "path": "liveware/package.json",
                    "reason": "command consumes exported PORT environment variable",
                }
            ],
        ):
            with self.subTest(evidence=evidence):
                analysis = copy.deepcopy(READY)
                analysis["adapter"]["command"] = ["npm", "run", "liveware"]
                analysis["adapter"]["required_commands"] = ["npm"]
                analysis["adapter"]["log"] = {"owner": "target", "path": None}
                analysis["evidence"] = evidence
                with self.assertRaisesRegex(ValueError, "exported PORT.*evidence"):
                    self.module.render_start(analysis)

    def test_static_path_field_encodes_shell_syntax_and_option_like_data(self) -> None:
        analysis = copy.deepcopy(READY)
        static_path = '-p $(nope) `nope` "quoted";semi'
        analysis["adapter"] = {
            "kind": "static",
            "workdir": static_path,
            "command": [],
            "required_commands": [],
            "default_port": None,
            "readiness": None,
            "log": {"owner": "target", "path": None},
        }
        analysis["static_dir"] = static_path

        text = self.module.render_start(analysis)

        self.assertIn(
            '"$SKILL_ROOT/-p \\$(nope) \\`nope\\` \\"quoted\\";semi"',
            text,
        )
        self.assert_bash_syntax(text)

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
        existing["evidence"] = [
            {
                "path": "scripts/start-server.sh",
                "reason": "Command consumes exported PORT environment variable",
            }
        ]
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

    def test_resolved_adapter_and_evidence_paths_must_stay_inside_target(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            target = write_target(root)
            outside = root / "outside"
            outside.mkdir()

            unsafe_workdir = copy.deepcopy(READY)
            unsafe_workdir["target_root"] = str(target.resolve())
            unsafe_workdir["adapter"]["workdir"] = "service"
            (target / "service").symlink_to(outside, target_is_directory=True)

            unsafe_static = copy.deepcopy(READY)
            unsafe_static["target_root"] = str(target.resolve())
            unsafe_static["adapter"] = {
                "kind": "static",
                "workdir": "public",
                "command": [],
                "required_commands": [],
                "default_port": None,
                "readiness": None,
                "log": {"owner": "target", "path": None},
            }
            unsafe_static["static_dir"] = "public"
            (target / "public").symlink_to(outside, target_is_directory=True)

            unsafe_evidence = copy.deepcopy(READY)
            unsafe_evidence["target_root"] = str(target.resolve())
            unsafe_evidence["static_dir"] = None
            unsafe_evidence["evidence"] = [
                {"path": "proof.js", "reason": "User-confirmed server evidence"}
            ]
            (target / "proof.js").symlink_to(outside / "proof.js")

            for name, analysis in {
                "workdir": unsafe_workdir,
                "static-dir": unsafe_static,
                "evidence": unsafe_evidence,
            }.items():
                with self.subTest(name=name):
                    with self.assertRaisesRegex(ValueError, "outside the target"):
                        self.module.render_start(analysis)
                    with self.assertRaisesRegex(ValueError, "outside the target"):
                        self.module.render_setup(analysis)

    def test_resolved_paths_inside_target_remain_renderable(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            target = write_target(Path(tmp))
            real = target / "service-real"
            real.mkdir()
            (target / "service-link").symlink_to(real, target_is_directory=True)
            proof = real / "server.py"
            proof.write_text("DEFAULT_PORT = 5080\n", encoding="utf-8")
            analysis = copy.deepcopy(READY)
            analysis["target_root"] = str(target.resolve())
            analysis["adapter"]["workdir"] = "service-link"
            analysis["static_dir"] = None
            analysis["evidence"] = [
                {"path": "service-real/server.py", "reason": "Confirmed server evidence"}
            ]

            setup = self.module.render_setup(analysis)
            start = self.module.render_start(analysis)

        self.assertIn("# LIVEWARE ANALYSIS V1: ", setup)
        self.assertIn('cd -- "$SKILL_ROOT/service-link"', start)


if __name__ == "__main__":
    unittest.main()
