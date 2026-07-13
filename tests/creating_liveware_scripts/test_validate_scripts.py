from __future__ import annotations

import copy
import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

from tests.creating_liveware_scripts.helpers import REPO_ROOT, load_skill_script, write_target


class ValidateScriptsTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.validator = load_skill_script("validate_scripts")
        cls.renderer = load_skill_script("render_scripts")
        cls.analyzer = load_skill_script("analyze_target")

    def analysis(self, target: Path, kind: str = "static") -> dict[str, object]:
        if kind == "static":
            adapter: dict[str, object] = {
                "kind": "static",
                "workdir": "liveware/static",
                "command": [],
                "required_commands": [],
                "default_port": None,
                "readiness": None,
                "log": {"owner": "target", "path": None},
            }
            static_dir: str | None = "liveware/static"
        else:
            command = [] if kind == "external" else ["python3", "server.py", "--port", "{port}"]
            required = [] if kind == "external" else ["python3"]
            owner = "generated-start" if kind == "managed-command" else "target"
            adapter = {
                "kind": kind,
                "workdir": "liveware",
                "command": command,
                "required_commands": required,
                "default_port": 6000,
                "readiness": {"kind": "http", "url": "http://127.0.0.1:{port}/healthz"},
                "log": {
                    "owner": owner,
                    "path": "$HOME/.clawling/apps/sample-skill.server.log" if owner == "generated-start" else None,
                },
            }
            static_dir = None
        return {
            "schema_version": 1,
            "status": "ready",
            "target_root": str(target.resolve()),
            "skill_name": "sample-skill",
            "display_name": "Sample Skill",
            "adapter": adapter,
            "static_dir": static_dir,
            "evidence": [],
            "issues": [],
        }

    def generated(self, analysis: dict[str, object]) -> tuple[str, str]:
        return self.renderer.render_setup(analysis), self.renderer.render_start(analysis)

    def write_scripts(self, target: Path, setup: str, start: str) -> None:
        scripts = target / "liveware" / "scripts"
        scripts.mkdir(parents=True, exist_ok=True)
        (scripts / "setup.py").write_text(setup, encoding="utf-8")
        (scripts / "start.sh").write_text(start, encoding="utf-8")

    def assert_finding(
        self,
        findings: list[object],
        code: str,
        path: str,
        message: str,
    ) -> None:
        triples = {(item.code, item.path, item.message) for item in findings}
        self.assertIn((code, path, message), triples)

    def run_cli(self, target: Path, analysis: Path | None = None) -> subprocess.CompletedProcess[str]:
        command = [sys.executable, str(Path(self.validator.__file__)), str(target)]
        if analysis is not None:
            command.extend(["--analysis", str(analysis)])
        return subprocess.run(command, capture_output=True, text=True, check=False)

    def test_generated_scripts_have_no_findings(self) -> None:
        analysis = {
            "schema_version": 1,
            "status": "ready",
            "target_root": "/tmp/sample-skill",
            "skill_name": "sample-skill",
            "display_name": "Sample Skill",
            "adapter": {
                "kind": "static",
                "workdir": "liveware/static",
                "command": [],
                "required_commands": [],
                "default_port": None,
                "readiness": None,
                "log": {"owner": "target", "path": None},
            },
            "static_dir": "liveware/static",
            "evidence": [],
            "issues": [],
        }
        findings = self.validator.validate_texts(
            self.renderer.render_setup(analysis), self.renderer.render_start(analysis)
        )
        self.assertEqual(findings, [])

    def test_every_generated_adapter_validates_against_analysis(self) -> None:
        for kind in ("static", "managed-command", "existing-launcher", "external"):
            with self.subTest(kind=kind), tempfile.TemporaryDirectory() as tmp:
                target = write_target(Path(tmp))
                analysis = self.analysis(target, kind)
                self.write_scripts(target, *self.generated(analysis))
                self.assertEqual(self.validator.validate_target(target, analysis=analysis), [])

    def test_detects_tarot_state_arguments_and_unknown_process_kill(self) -> None:
        setup = (REPO_ROOT / "creative/tarot-arcana/liveware/scripts/setup.py").read_text(encoding="utf-8")
        start = (REPO_ROOT / "creative/tarot-arcana/liveware/scripts/start.sh").read_text(encoding="utf-8")
        codes = {finding.code for finding in self.validator.validate_texts(setup, start)}
        self.assertIn("LW003", codes)
        self.assertIn("LW010", codes)

    def test_detects_office_legacy_state_and_first_app_fallback(self) -> None:
        setup = (REPO_ROOT / "productivity/clawchat-officecli/scripts/office-liveware-setup.py").read_text(encoding="utf-8")
        start = (REPO_ROOT / "productivity/clawchat-officecli/scripts/office-liveware-start.sh").read_text(encoding="utf-8")
        codes = {finding.code for finding in self.validator.validate_texts(setup, start)}
        self.assertIn("LW002", codes)
        self.assertIn("LW004", codes)

    def test_target_validation_requires_fixed_paths(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            target = write_target(Path(tmp))
            findings = self.validator.validate_target(target)
        self.assertEqual({finding.code for finding in findings}, {"LW001", "LW005"})
        self.assert_finding(
            findings,
            "LW001",
            str(target / "liveware" / "scripts" / "setup.py"),
            "Required setup.py is missing.",
        )
        self.assert_finding(
            findings,
            "LW005",
            str(target / "liveware" / "scripts" / "start.sh"),
            "Required start.sh is missing.",
        )

    def test_target_validation_detects_port_mismatch_against_analysis(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            target = write_target(Path(tmp))
            liveware = target / "liveware"
            scripts = liveware / "scripts"
            scripts.mkdir(parents=True)
            (liveware / "server.py").write_text("DEFAULT_PORT = 6000\n", encoding="utf-8")
            analysis = self.analyzer.analyze_target(target, which=lambda command: f"/bin/{command}")
            (scripts / "setup.py").write_text(self.renderer.render_setup(analysis), encoding="utf-8")
            start = self.renderer.render_start(analysis).replace('PORT="${PORT:-6000}"', 'PORT="${PORT:-5080}"')
            (scripts / "start.sh").write_text(start, encoding="utf-8")
            findings = self.validator.validate_target(target, analysis=analysis)
        self.assertIn("LW019", {finding.code for finding in findings})

    def test_python_and_bash_syntax_findings_use_contract_paths(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            target = write_target(Path(tmp))
            analysis = self.analysis(target)
            setup, start = self.generated(analysis)
            python_findings = self.validator.validate_texts(setup + "\nif :\n", start)
            self.assert_finding(
                python_findings,
                "LW006",
                "liveware/scripts/setup.py",
                "Python syntax error: invalid syntax",
            )

            self.write_scripts(target, setup, start + "\nif then\n")
            bash_findings = self.validator.validate_target(target)
            self.assert_finding(
                bash_findings,
                "LW014",
                str(target / "liveware" / "scripts" / "start.sh"),
                "Bash syntax validation failed.",
            )

    def test_comments_and_dead_strings_cannot_satisfy_state_path(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            analysis = self.analysis(Path(tmp))
            setup, start = self.generated(analysis)
        setup = setup.replace(
            'STATE_ROOT = Path.home() / ".clawling" / "apps"',
            'STATE_ROOT = Path("/tmp/legacy-state")\nUNUSED_STATE = \'Path.home() / ".clawling" / "apps"\'',
        )
        findings = self.validator.validate_texts(setup, start)
        self.assert_finding(
            findings,
            "LW002",
            "liveware/scripts/setup.py",
            "Setup does not use per-skill JSON app state.",
        )
        reassigned = self.renderer.render_setup(analysis) + '\nSTATE_ROOT = Path("/tmp/legacy-state")\n'
        self.assert_finding(
            self.validator.validate_texts(reassigned, start),
            "LW002",
            "liveware/scripts/setup.py",
            "Setup does not use per-skill JSON app state.",
        )

    def test_comments_and_dead_calls_cannot_satisfy_login_or_registration(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            analysis = self.analysis(Path(tmp))
            setup, start = self.generated(analysis)
        setup = setup.replace("login = await tools.liveware_login()", 'login = {"ok": True}')
        setup = setup.replace(
            "result = await tools.register_app(name=CLAWCHAT_APP_NAME, app_id=app_id, url=public_url(app_id))",
            "result = {}",
        )
        setup += '\n# await tools.liveware_login()\nDEAD_CALL = "tools.register_app(...)"\n'
        findings = self.validator.validate_texts(setup, start)
        self.assert_finding(
            findings,
            "LW009",
            "liveware/scripts/setup.py",
            "Setup is missing ClawChat login or registration.",
        )

    def test_dead_strings_cannot_satisfy_hermes_creation(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            analysis = self.analysis(Path(tmp))
            setup, start = self.generated(analysis)
        setup = setup.replace(
            'run_liveware(binary, "app", "create", SKILL_NAME, "--agent-type", "hermes")',
            'run_liveware(binary, "app", "create", SKILL_NAME)',
        )
        setup += '\nDEAD_AGENT_TYPE = \'"--agent-type", "hermes"\'\n'
        findings = self.validator.validate_texts(setup, start)
        self.assert_finding(
            findings,
            "LW016",
            "liveware/scripts/setup.py",
            "App creation is missing the Hermes agent type.",
        )
        unsafe_fallback = self.renderer.render_setup(analysis) + (
            '\nraw = run_liveware("liveware", "app", "create", SKILL_NAME)\n'
        )
        self.assert_finding(
            self.validator.validate_texts(unsafe_fallback, start),
            "LW016",
            "liveware/scripts/setup.py",
            "App creation is missing the Hermes agent type.",
        )

    def test_state_identity_modes_and_atomic_replace_are_semantic(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            analysis = self.analysis(Path(tmp))
            setup, start = self.generated(analysis)
        variants = {
            "identity": setup.replace('"app_name": SKILL_NAME,', '"app_name": CLAWCHAT_APP_NAME,'),
            "file-mode": setup.replace("os.chmod(temp_name, 0o600)", "os.chmod(temp_name, 0o644)\n        _ = '0o600'"),
            "later-permissive-file-mode": setup.replace(
                "os.replace(temp_name, STATE_FILE)",
                "os.chmod(temp_name, 0o644)\n        os.replace(temp_name, STATE_FILE)",
            ),
            "directory-mode": setup.replace("mode=0o700", "mode=0o755").replace(
                "os.chmod(STATE_ROOT.parent, 0o700)", "os.chmod(STATE_ROOT.parent, 0o755)"
            ).replace("os.chmod(STATE_ROOT, 0o700)", "os.chmod(STATE_ROOT, 0o755)\n    _ = '0o700'"),
            "atomic-replace": setup.replace(
                "os.replace(temp_name, STATE_FILE)", "os.rename(temp_name, STATE_FILE)\n        _ = 'os.replace(temp_name, STATE_FILE)'"
            ),
        }
        for name, candidate in variants.items():
            with self.subTest(name=name):
                findings = self.validator.validate_texts(candidate, start)
                self.assert_finding(
                    findings,
                    "LW017",
                    "liveware/scripts/setup.py",
                    "State persistence is not atomic with required permissions and stable identity.",
                )

    def test_python_contract_accepts_ordinary_quote_and_import_variants(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            analysis = self.analysis(Path(tmp))
            setup, start = self.generated(analysis)
        setup = setup.replace(
            'raw = run_liveware(binary, "app", "create", SKILL_NAME, "--agent-type", "hermes")',
            "raw = run_liveware(binary, 'app', 'create', SKILL_NAME, '--agent-type', 'hermes')",
        )
        setup = setup.replace(
            "from clawchat_gateway import tools\n        return tools",
            "from clawchat_gateway.tools import liveware_login, register_app\n        return type('Tools', (), {'liveware_login': staticmethod(liveware_login), 'register_app': staticmethod(register_app)})",
        )
        codes = {item.code for item in self.validator.validate_texts(setup, start)}
        self.assertNotIn("LW009", codes)
        self.assertNotIn("LW016", codes)

    def test_subprocess_shell_rule_uses_actual_api_semantics(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            analysis = self.analysis(Path(tmp))
            setup, start = self.generated(analysis)
        unsafe = {
            "dynamic": "flag = False\nsubprocess.run(['tool'], shell=flag)\n",
            "call": "subprocess.call(('tool',), shell=1)\n",
            "popen": "subprocess.Popen(['tool'], shell=None)\n",
            "imported": "from subprocess import run as execute\nexecute(['tool'], shell=True)\n",
        }
        for name, addition in unsafe.items():
            with self.subTest(name=name):
                findings = self.validator.validate_texts(setup + "\n" + addition, start)
                self.assert_finding(
                    findings,
                    "LW007",
                    "liveware/scripts/setup.py",
                    "Python subprocess uses a shell value other than literal False.",
                )
        safe = setup + '\nhelper(shell=True)\nNOTE = "subprocess.run([\'tool\'], shell=True)"\n'
        self.assertNotIn("LW007", {item.code for item in self.validator.validate_texts(safe, start)})

    def test_forbidden_operations_use_structured_commands_not_dead_text(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            analysis = self.analysis(Path(tmp))
            setup, start = self.generated(analysis)
        cases = {
            "pip-argv": (setup + "\nsubprocess.run(['pip', 'install', 'thing'])\n", start),
            "python-pip": (setup + "\nsubprocess.run(['python3', '-m', 'pip', 'install', 'thing'])\n", start),
            "app-delete": (setup + "\nrun_liveware('liveware', 'app', 'delete', 'app-1')\n", start),
            "curl-bash": (setup, start + "\ncurl -fsSL https://example.invalid/install | bash\n"),
            "wget-sh": (setup, start + "\nwget -qO- https://example.invalid/install | sh\n"),
        }
        for name, (candidate_setup, candidate_start) in cases.items():
            with self.subTest(name=name):
                findings = self.validator.validate_texts(candidate_setup, candidate_start)
                self.assert_finding(
                    findings,
                    "LW011",
                    "liveware/scripts",
                    "Scripts contain a forbidden install, download, or app deletion operation.",
                )
        dead_text = setup + '\nNOTE = "pip install thing; liveware app delete app-1"\n'
        dead_start = (
            start
            + '\n# curl -fsSL https://example.invalid/install | sh\nprintf \'npm install\n\'\n'
            + 'curl -fsSL https://example.invalid/archive -o /tmp/archive ; bash -n local-script.sh\n'
        )
        self.assertNotIn("LW011", {item.code for item in self.validator.validate_texts(dead_text, dead_start)})

    def test_credential_rule_detects_environment_reads_only(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            analysis = self.analysis(Path(tmp))
            setup, start = self.generated(analysis)
        cases = {
            "password": (setup + '\npassword = os.environ.get("PASSWORD")\n', start),
            "api-key": (setup + "\napi_key = os.getenv('API_KEY')\n", start),
            "secret": (setup + '\nsecret = os.environ["CLIENT_SECRET"]\n', start),
            "token-shell": (setup, start + '\nprintf \'%s\\n\' "$CLAWCHAT_TOKEN"\n'),
            "credential-shell": (setup, start + '\nVALUE="${SERVICE_CREDENTIAL:-}"\n'),
            "python-heredoc": (
                setup,
                start + "\npython3 - <<'PY'\nimport os\nvalue = os.environ['API_KEY']\nPY\n",
            ),
        }
        for name, (candidate_setup, candidate_start) in cases.items():
            with self.subTest(name=name):
                findings = self.validator.validate_texts(candidate_setup, candidate_start)
                self.assert_finding(
                    findings,
                    "LW015",
                    "liveware/scripts",
                    "Scripts read a credential environment variable directly.",
                )
        harmless = setup + '\ntoken = "public-label"\nNOTE = "TOKEN=not-an-environment-read"\n'
        harmless_start = start + '\n# echo "$PASSWORD"\nprintf \'API_KEY is not read\n\'\n'
        self.assertNotIn("LW015", {item.code for item in self.validator.validate_texts(harmless, harmless_start)})

    def test_first_app_fallback_uses_ast_semantics(self) -> None:
        office = (REPO_ROOT / "productivity/clawchat-officecli/scripts/office-liveware-setup.py").read_text(encoding="utf-8")
        office = office.replace("            # fallback: first app\n", "")
        with tempfile.TemporaryDirectory() as tmp:
            analysis = self.analysis(Path(tmp))
            valid_setup, start = self.generated(analysis)
        indexing = valid_setup + '\napps = []\napp_id = apps[0]["id"] if apps else None\n'
        for name, setup in (("unfiltered-loop", office), ("first-index", indexing)):
            with self.subTest(name=name):
                self.assert_finding(
                    self.validator.validate_texts(setup, start),
                    "LW004",
                    "liveware/scripts/setup.py",
                    "App recovery can fall back to a non-matching app.",
                )
        dead = valid_setup + '\nNOTE = "fallback: first app"\n'
        self.assertNotIn("LW004", {item.code for item in self.validator.validate_texts(dead, start)})

    def test_start_state_path_requires_an_actual_standard_assignment(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            analysis = self.analysis(Path(tmp))
            setup, start = self.generated(analysis)
        start = start.replace(
            'STATE_FILE="${HOME}/.clawling/apps/${SKILL_NAME}.json"',
            'STATE_FILE="${HOME}/legacy.env"\n# STATE_FILE uses .clawling/apps/ in the standard version',
        )
        self.assert_finding(
            self.validator.validate_texts(setup, start),
            "LW003",
            "liveware/scripts/start.sh",
            "Start does not read the standard state file.",
        )

    def test_start_setup_invocation_is_detected_despite_guidance(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            analysis = self.analysis(Path(tmp))
            setup, start = self.generated(analysis)
        invocations = {
            "direct": "python3 liveware/scripts/setup.py",
            "assigned-path": 'SETUP_SCRIPT="liveware/scripts/setup.py"\npython3 "$SETUP_SCRIPT"',
        }
        for name, invocation in invocations.items():
            with self.subTest(name=name):
                self.assert_finding(
                    self.validator.validate_texts(setup, start + "\n" + invocation + "\n"),
                    "LW008",
                    "liveware/scripts/start.sh",
                    "Start invokes setup instead of requiring existing state.",
                )

    def test_unknown_process_kills_and_owned_child_distinction(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            analysis = self.analysis(Path(tmp))
            setup, start = self.generated(analysis)
        unsafe = {
            "kill-signal": 'kill -9 "$PID"',
            "kill-option-separator": 'kill -- "$PID"',
            "pkill": "pkill python3",
            "killall": "killall node",
            "lsof-pid": 'PID=$(lsof -ti ":$PORT")\nkill "$PID"',
            "indirect-pid": 'PID="$OTHER_PID"\nkill "$PID"',
            "reassigned-child": 'PID=$!\nPID="$OTHER_PID"\nkill "$PID"',
            "assigned-after-kill": 'kill "$PID"\nPID=$!',
            "python-kill": "python3 - <<'PY'\nimport os\nos.kill(123, 15)\nPY",
        }
        for name, addition in unsafe.items():
            with self.subTest(name=name):
                findings = self.validator.validate_texts(setup, start + "\n" + addition + "\n")
                self.assert_finding(
                    findings,
                    "LW010",
                    "liveware/scripts/start.sh",
                    "Start can terminate a process it cannot prove it owns.",
                )
        safe = start + '\n"${SERVER_COMMAND[@]}" &\nOWNED_PID=$!\nkill "$OWNED_PID"\n'
        self.assertNotIn("LW010", {item.code for item in self.validator.validate_texts(setup, safe)})

    def test_marker_structure_requires_exact_ordered_whole_lines(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            analysis = self.analysis(Path(tmp))
            setup, start = self.generated(analysis)
        begin_adapter = "# BEGIN TARGET SERVER ADAPTER"
        end_adapter = "# END TARGET SERVER ADAPTER"
        begin_binding = "# BEGIN LIVEWARE BINDING"
        end_binding = "# END LIVEWARE BINDING"
        malformed = {
            "fake-comment": start.replace(begin_adapter, f"# fake {begin_adapter}"),
            "duplicate": start.replace(begin_adapter, f"{begin_adapter}\n{begin_adapter}"),
            "reordered": start.replace(begin_adapter, "__BEGIN_ADAPTER__", 1)
            .replace(begin_binding, begin_adapter, 1)
            .replace("__BEGIN_ADAPTER__", begin_binding, 1),
            "nested": start.replace(end_adapter, "__END_ADAPTER__", 1)
            .replace(end_binding, end_adapter, 1)
            .replace("__END_ADAPTER__", end_binding, 1),
            "missing-end": start.replace(end_binding, "# binding end omitted"),
        }
        for name, candidate in malformed.items():
            with self.subTest(name=name):
                self.assert_finding(
                    self.validator.validate_texts(setup, candidate),
                    "LW012",
                    "liveware/scripts/start.sh",
                    "Start has invalid repair-safe block markers.",
                )

    def test_binding_validation_uses_only_the_exact_binding_block(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            analysis = self.analysis(Path(tmp), "managed-command")
            setup, start = self.generated(analysis)
        remote = start.replace(
            '"$LIVEWARE_BIN" tunnel bind "$APP_ID" "http://127.0.0.1:${PORT}"',
            '"$LIVEWARE_BIN" tunnel bind "$APP_ID" "http://0.0.0.0:${PORT}"',
        )
        remote += '\n# unrelated http://127.0.0.1:${PORT}\n# tunnel bind-static elsewhere\n'
        missing = start.replace(
            '"$LIVEWARE_BIN" tunnel bind "$APP_ID" "http://127.0.0.1:${PORT}"',
            'printf \'binding omitted\n\'',
        )
        for name, candidate in (("remote", remote), ("missing", missing)):
            with self.subTest(name=name):
                self.assert_finding(
                    self.validator.validate_texts(setup, candidate),
                    "LW013",
                    "liveware/scripts/start.sh",
                    "Liveware binding is missing, ambiguous, or not explicitly loopback-only.",
                )
        single_quotes = start.replace(
            '"$LIVEWARE_BIN" tunnel bind "$APP_ID" "http://127.0.0.1:${PORT}"',
            "'$LIVEWARE_BIN' tunnel bind '$APP_ID' 'http://127.0.0.1:${PORT}'",
        )
        self.assertNotIn("LW013", {item.code for item in self.validator.validate_texts(setup, single_quotes)})

    def test_analysis_requires_ready_schema_no_issues_and_matching_target(self) -> None:
        mutations = {
            "schema": lambda data: data.update(schema_version=2),
            "status": lambda data: data.update(status="blocked"),
            "issues": lambda data: data.update(issues=["unresolved"]),
            "missing-issues": lambda data: data.pop("issues"),
            "target-mismatch": lambda data: data.update(target_root="/tmp/other-skill"),
            "empty-target": lambda data: data.update(target_root=""),
        }
        for name, mutate in mutations.items():
            with self.subTest(name=name), tempfile.TemporaryDirectory() as tmp:
                target = write_target(Path(tmp))
                valid = self.analysis(target)
                self.write_scripts(target, *self.generated(valid))
                candidate = copy.deepcopy(valid)
                mutate(candidate)
                findings = self.validator.validate_target(target, analysis=candidate)
                self.assertIn("LW018", {item.code for item in findings})

    def test_canonical_renderer_covers_every_adapter_field(self) -> None:
        mutations = {
            "kind": lambda adapter: adapter.update(kind="existing-launcher"),
            "workdir": lambda adapter: adapter.update(workdir="other"),
            "command": lambda adapter: adapter.update(command=["python3", "other.py", "--port", "{port}"]),
            "required": lambda adapter: adapter.update(required_commands=["python3", "helper"]),
            "port": lambda adapter: adapter.update(default_port=7000),
            "readiness": lambda adapter: adapter.update(
                readiness={"kind": "http", "url": "http://127.0.0.1:{port}/ready"}
            ),
            "log": lambda adapter: adapter.update(
                log={"owner": "generated-start", "path": "$HOME/.clawling/apps/other.log"}
            ),
        }
        for name, mutate in mutations.items():
            with self.subTest(name=name), tempfile.TemporaryDirectory() as tmp:
                target = write_target(Path(tmp))
                valid = self.analysis(target, "managed-command")
                self.write_scripts(target, *self.generated(valid))
                candidate = copy.deepcopy(valid)
                adapter = candidate["adapter"]
                assert isinstance(adapter, dict)
                mutate(adapter)
                findings = self.validator.validate_target(target, analysis=candidate)
                self.assertIn("LW019", {item.code for item in findings})

        with tempfile.TemporaryDirectory() as tmp:
            target = write_target(Path(tmp))
            valid = self.analysis(target)
            self.write_scripts(target, *self.generated(valid))
            candidate = copy.deepcopy(valid)
            candidate["static_dir"] = "public"
            self.assertIn("LW019", {item.code for item in self.validator.validate_target(target, analysis=candidate)})

    def test_canonical_renderer_detects_setup_and_scaffold_identity_changes(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            target = write_target(Path(tmp))
            analysis = self.analysis(target)
            setup, start = self.generated(analysis)
            setup = setup.replace('"app_name": SKILL_NAME,', '"app_name": CLAWCHAT_APP_NAME,', 1)
            start = start.replace("SKILL_NAME=sample-skill", "SKILL_NAME=other-skill")
            self.write_scripts(target, setup, start)
            findings = self.validator.validate_target(target, analysis=analysis)
        self.assertIn("LW018", {item.code for item in findings})
        self.assertIn("LW019", {item.code for item in findings})

    def test_renderer_rejection_maps_adapter_failure_to_lw019(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            target = write_target(Path(tmp))
            valid = self.analysis(target, "managed-command")
            self.write_scripts(target, *self.generated(valid))
            candidate = copy.deepcopy(valid)
            adapter = candidate["adapter"]
            assert isinstance(adapter, dict)
            adapter["default_port"] = "6000"
            findings = self.validator.validate_target(target, analysis=candidate)
        self.assert_finding(
            findings,
            "LW019",
            "liveware/scripts/start.sh",
            "Generated start or adapter does not match analysis.",
        )

    def test_cli_analysis_failures_are_deterministic_json_findings(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            target = write_target(root)
            cases = {
                "missing": (root / "missing.json", "Analysis file could not be read."),
                "malformed": (root / "malformed.json", "Analysis file is not valid JSON."),
                "invalid-encoding": (root / "invalid-encoding.json", "Analysis file could not be read."),
                "non-object": (root / "non-object.json", "Analysis JSON must be an object."),
            }
            cases["malformed"][0].write_text("{broken", encoding="utf-8")
            cases["invalid-encoding"][0].write_bytes(b"\xff")
            cases["non-object"][0].write_text("[]", encoding="utf-8")
            for name, (path, message) in cases.items():
                with self.subTest(name=name):
                    result = self.run_cli(target, path)
                    self.assertEqual(result.returncode, 1)
                    self.assertEqual(result.stderr, "")
                    payload = json.loads(result.stdout)
                    self.assertEqual(payload, [{"code": "LW018", "message": message, "path": str(path)}])

    def test_cli_returns_json_and_contract_exit_status(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            target = write_target(root)
            analysis = self.analysis(target)
            self.write_scripts(target, *self.generated(analysis))
            analysis_path = root / "analysis.json"
            analysis_path.write_text(json.dumps(analysis), encoding="utf-8")
            valid = self.run_cli(target, analysis_path)
            self.assertEqual(valid.returncode, 0)
            self.assertEqual(valid.stderr, "")
            self.assertEqual(json.loads(valid.stdout), [])

            (target / "liveware" / "scripts" / "start.sh").unlink()
            invalid = self.run_cli(target, analysis_path)
            self.assertEqual(invalid.returncode, 1)
            self.assertEqual(invalid.stderr, "")
            payload = json.loads(invalid.stdout)
            self.assertEqual([item["code"] for item in payload], ["LW005"])


if __name__ == "__main__":
    unittest.main()
