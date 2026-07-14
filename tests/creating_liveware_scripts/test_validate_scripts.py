from __future__ import annotations

import base64
import copy
import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from tests.creating_liveware_scripts.helpers import REPO_ROOT, load_skill_script, write_target


class ValidateScriptsTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.validator = load_skill_script("validate_scripts")
        cls.renderer = load_skill_script("render_scripts")

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
                    "path": "$HOME/.clawling/apps/sample-skill.server.log"
                    if owner == "generated-start"
                    else None,
                },
            }
            static_dir = None
        return {
            "schema_version": 1,
            "status": "ready",
            "target_root": str(target.resolve()),
            "skill_name": "sample-skill",
            "display_name": "样例 🌙",
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

    def run_cli(self, target: Path, analysis: Path | None = None) -> subprocess.CompletedProcess[str]:
        command = [sys.executable, str(Path(self.validator.__file__)), str(target)]
        if analysis is not None:
            command.extend(["--analysis", str(analysis)])
        return subprocess.run(command, capture_output=True, text=True, check=False)

    def codes(self, findings: list[object]) -> set[str]:
        return {item.code for item in findings}

    def test_every_generated_adapter_is_a_zero_finding_canonical_pair(self) -> None:
        for kind in ("static", "managed-command", "existing-launcher", "external"):
            with self.subTest(kind=kind), tempfile.TemporaryDirectory() as tmp:
                target = write_target(Path(tmp))
                analysis = self.analysis(target, kind)
                setup, start = self.generated(analysis)
                self.assertEqual(setup.count("# LIVEWARE ANALYSIS V1: "), 1)
                self.assertEqual(start.count("# LIVEWARE ANALYSIS V1: "), 1)
                self.assertEqual(self.renderer.extract_analysis_manifest(setup), analysis)
                self.assertEqual(self.renderer.extract_analysis_manifest(start), analysis)
                self.assertEqual(self.validator.validate_texts(setup, start, analysis=analysis), [])
                self.write_scripts(target, setup, start)
                self.assertEqual(self.validator.validate_target(target, analysis=analysis), [])

    def test_target_validation_requires_both_fixed_paths(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            target = write_target(Path(tmp))
            findings = self.validator.validate_target(target)
        self.assertEqual(self.codes(findings), {"LW001", "LW005"})
        self.assertEqual(
            {(item.code, item.path, item.message) for item in findings},
            {
                (
                    "LW001",
                    str(target / "liveware" / "scripts" / "setup.py"),
                    "Required setup.py is missing.",
                ),
                (
                    "LW005",
                    str(target / "liveware" / "scripts" / "start.sh"),
                    "Required start.sh is missing.",
                ),
            },
        )

    def test_unmanifested_plausible_scripts_can_never_pass(self) -> None:
        setup = """#!/usr/bin/env python3
from pathlib import Path
STATE_ROOT = Path.home() / ".clawling" / "apps"
STATE_FILE = STATE_ROOT / f"{SKILL_NAME}.json"
"""
        start = """#!/usr/bin/env bash
set -euo pipefail
SKILL_NAME=sample-skill
STATE_FILE="${HOME}/.clawling/apps/${SKILL_NAME}.json"
test -f "$STATE_FILE"
"""
        self.assertTrue({"LW018", "LW019"} <= self.codes(self.validator.validate_texts(setup, start)))

    def test_fake_valid_manifest_cannot_authorize_unsafe_bodies(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            analysis = self.analysis(Path(tmp), "managed-command")
        marker = f"# LIVEWARE ANALYSIS V1: {self.renderer.encode_analysis_manifest(analysis)}\n"
        setup = marker + "import subprocess\nsubprocess.run('curl x | sh', shell=True)\n"
        start = marker + "curl https://example.invalid/install | sh\nkill -9 1\n"
        codes = self.codes(self.validator.validate_texts(setup, start))
        self.assertTrue({"LW018", "LW019", "LW011"} <= codes)

    def test_unchanged_manifest_does_not_hide_body_tampering(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            analysis = self.analysis(Path(tmp), "managed-command")
            setup, start = self.generated(analysis)
        changed_setup = setup.replace('SKILL_NAME = "sample-skill"', 'SKILL_NAME = "other"', 1)
        changed_start = start.replace("SERVER_COMMAND=(python3 server.py", "SERVER_COMMAND=(python3 evil.py", 1)
        self.assertIn("LW018", self.codes(self.validator.validate_texts(changed_setup, start)))
        self.assertIn("LW019", self.codes(self.validator.validate_texts(setup, changed_start)))

    def test_manifest_corruption_classes_map_to_deterministic_script_codes(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            analysis = self.analysis(Path(tmp))
            setup, start = self.generated(analysis)
        payload = self.renderer.encode_analysis_manifest(analysis)
        marker = f"# LIVEWARE ANALYSIS V1: {payload}"
        noncanonical = base64.urlsafe_b64encode(
            json.dumps(analysis, ensure_ascii=False).encode("utf-8")
        ).decode("ascii")

        for name, candidate in {
            "missing": setup.replace(marker + "\n", "", 1),
            "duplicate": setup.replace(marker, marker + "\n" + marker, 1),
            "malformed": setup.replace(marker, "# LIVEWARE ANALYSIS V1: %%%", 1),
            "noncanonical": setup.replace(marker, f"# LIVEWARE ANALYSIS V1: {noncanonical}", 1),
        }.items():
            with self.subTest(script="setup", name=name):
                self.assertIn("LW018", self.codes(self.validator.validate_texts(candidate, start)))

        for name, candidate in {
            "missing": start.replace(marker + "\n", "", 1),
            "duplicate": start.replace(marker, marker + "\n" + marker, 1),
            "malformed": start.replace(marker, "# LIVEWARE ANALYSIS V1: %%%", 1),
            "noncanonical": start.replace(marker, f"# LIVEWARE ANALYSIS V1: {noncanonical}", 1),
        }.items():
            with self.subTest(script="start", name=name):
                self.assertIn("LW019", self.codes(self.validator.validate_texts(setup, candidate)))

    def test_valid_but_different_manifests_are_rejected_on_both_scripts(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            analysis = self.analysis(Path(tmp))
            other = copy.deepcopy(analysis)
            other["display_name"] = "Other"
            setup = self.renderer.render_setup(analysis)
            start = self.renderer.render_start(other)
        codes = self.codes(self.validator.validate_texts(setup, start))
        self.assertTrue({"LW018", "LW019"} <= codes)

    def test_explicit_analysis_must_be_ready_and_equal_both_manifests(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            analysis = self.analysis(Path(tmp))
            setup, start = self.generated(analysis)
        other = copy.deepcopy(analysis)
        other["display_name"] = "Different"
        self.assertTrue(
            {"LW018", "LW019"}
            <= self.codes(self.validator.validate_texts(setup, start, analysis=other))
        )
        invalid = {**analysis, "status": "blocked"}
        findings = self.validator.validate_texts(setup, start, analysis=invalid)
        self.assertIn(
            ("LW018", "analysis.json", "Resolved schema-version-1 analysis with no issues is required."),
            {(item.code, item.path, item.message) for item in findings},
        )

    def test_schema_numeric_types_are_rejected_as_explicit_analysis(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            analysis = self.analysis(Path(tmp), "managed-command")
            setup, start = self.generated(analysis)

        for field, value in (
            ("schema_version", True),
            ("schema_version", 1.0),
            ("default_port", True),
            ("default_port", 6000.0),
        ):
            with self.subTest(field=field, value=value):
                invalid = copy.deepcopy(analysis)
                if field == "schema_version":
                    invalid[field] = value
                else:
                    invalid["adapter"][field] = value
                findings = self.validator.validate_texts(setup, start, analysis=invalid)
                self.assertIn(
                    (
                        "LW018",
                        "analysis.json",
                        "Resolved schema-version-1 analysis with no issues is required.",
                    ),
                    {(item.code, item.path, item.message) for item in findings},
                )

    def test_relative_generated_log_path_is_an_explicit_analysis_finding(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            analysis = self.analysis(Path(tmp), "managed-command")
            setup, start = self.generated(analysis)
        invalid = copy.deepcopy(analysis)
        invalid["adapter"]["log"]["path"] = "logs/server.log"
        findings = self.validator.validate_texts(setup, start, analysis=invalid)
        self.assertIn(
            (
                "LW018",
                "analysis.json",
                "Resolved schema-version-1 analysis with no issues is required.",
            ),
            {(item.code, item.path, item.message) for item in findings},
        )

    def test_embedded_or_duplicate_port_tokens_are_analysis_findings(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            analysis = self.analysis(Path(tmp), "managed-command")
            setup, start = self.generated(analysis)
        for command in (
            ["python3", "server.py", "--port={port}"],
            ["python3", "server.py", "{port}", "{port}"],
        ):
            with self.subTest(command=command):
                invalid = copy.deepcopy(analysis)
                invalid["adapter"]["command"] = command
                findings = self.validator.validate_texts(setup, start, analysis=invalid)
                self.assertIn(
                    (
                        "LW018",
                        "analysis.json",
                        "Resolved schema-version-1 analysis with no issues is required.",
                    ),
                    {(item.code, item.path, item.message) for item in findings},
                )

    def test_zero_port_token_without_exact_evidence_is_an_analysis_finding(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            analysis = self.analysis(Path(tmp), "managed-command")
            setup, start = self.generated(analysis)
        invalid = copy.deepcopy(analysis)
        invalid["adapter"]["command"] = ["npm", "run", "liveware"]
        invalid["adapter"]["required_commands"] = ["npm"]
        invalid["evidence"] = [
            {"path": "liveware/package.json", "reason": "Node server entrypoint"}
        ]
        findings = self.validator.validate_texts(setup, start, analysis=invalid)
        self.assertIn(
            (
                "LW018",
                "analysis.json",
                "Resolved schema-version-1 analysis with no issues is required.",
            ),
            {(item.code, item.path, item.message) for item in findings},
        )

    def test_schema_invalid_manifests_map_to_both_script_contract_codes(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            analysis = self.analysis(Path(tmp), "managed-command")
            setup, start = self.generated(analysis)
        original = self.renderer.encode_analysis_manifest(analysis)

        invalid_cases: dict[str, dict[str, object]] = {}
        top_extra = copy.deepcopy(analysis)
        top_extra["clientSecret"] = "never embed"
        invalid_cases["top-extra-credential"] = top_extra
        top_benign = copy.deepcopy(analysis)
        top_benign["author"] = "also not analyzer schema"
        invalid_cases["top-extra-benign"] = top_benign
        adapter_extra = copy.deepcopy(analysis)
        adapter_extra["adapter"]["extension"] = "no"
        invalid_cases["adapter-extra"] = adapter_extra
        readiness_extra = copy.deepcopy(analysis)
        readiness_extra["adapter"]["readiness"]["extension"] = "no"
        invalid_cases["readiness-extra"] = readiness_extra
        log_extra = copy.deepcopy(analysis)
        log_extra["adapter"]["log"]["extension"] = "no"
        invalid_cases["log-extra"] = log_extra
        evidence_extra = copy.deepcopy(analysis)
        evidence_extra["evidence"] = [
            {"path": "SKILL.md", "reason": "text may say token or password", "extension": "no"}
        ]
        invalid_cases["evidence-extra"] = evidence_extra

        for name, invalid in invalid_cases.items():
            with self.subTest(name=name):
                payload = base64.urlsafe_b64encode(
                    json.dumps(
                        invalid,
                        ensure_ascii=False,
                        sort_keys=True,
                        separators=(",", ":"),
                    ).encode("utf-8")
                ).decode("ascii")
                invalid_setup = setup.replace(original, payload, 1)
                invalid_start = start.replace(original, payload, 1)
                codes = self.codes(self.validator.validate_texts(invalid_setup, invalid_start))
                self.assertTrue({"LW018", "LW019"} <= codes)

    def test_schema_invalid_explicit_analysis_is_an_analysis_finding(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            analysis = self.analysis(Path(tmp))
            setup, start = self.generated(analysis)

        for key in ("clientSecret", "author"):
            with self.subTest(key=key):
                invalid = copy.deepcopy(analysis)
                invalid[key] = "not analyzer schema"
                findings = self.validator.validate_texts(setup, start, analysis=invalid)
                self.assertIn(
                    (
                        "LW018",
                        "analysis.json",
                        "Resolved schema-version-1 analysis with no issues is required.",
                    ),
                    {(item.code, item.path, item.message) for item in findings},
                )

    def test_target_root_mismatch_is_an_analysis_finding(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            target = write_target(Path(tmp))
            analysis = self.analysis(target)
            self.write_scripts(target, *self.generated(analysis))
            other = copy.deepcopy(analysis)
            other["target_root"] = str((target / "elsewhere").resolve())
            findings = self.validator.validate_target(target, analysis=other)
        self.assertIn(
            ("LW018", "analysis.json", "Analysis target_root does not match target."),
            {(item.code, item.path, item.message) for item in findings},
        )

    def test_embedded_target_root_is_bound_without_explicit_analysis(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            target = write_target(Path(tmp))
            analysis = self.analysis(target)
            analysis["target_root"] = str((target / "elsewhere").resolve())
            self.write_scripts(target, *self.generated(analysis))
            findings = self.validator.validate_target(target)
        self.assertIn(
            ("LW018", "analysis.json", "Analysis target_root does not match target."),
            {(item.code, item.path, item.message) for item in findings},
        )

    def test_double_slash_target_root_never_passes_with_or_without_explicit_analysis(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            target = write_target(Path(tmp))
            analysis = self.analysis(target)
            setup, start = self.generated(analysis)
            invalid = copy.deepcopy(analysis)
            invalid["target_root"] = "//" + str(target.resolve()).lstrip("/")

            self.write_scripts(target, setup, start)
            explicit = self.validator.validate_target(target, analysis=invalid)

            raw = json.dumps(
                invalid,
                ensure_ascii=False,
                sort_keys=True,
                separators=(",", ":"),
            ).encode("utf-8")
            invalid_payload = base64.urlsafe_b64encode(raw).decode("ascii")
            valid_payload = self.renderer.encode_analysis_manifest(analysis)
            invalid_setup = setup.replace(valid_payload, invalid_payload, 1)
            invalid_start = start.replace(valid_payload, invalid_payload, 1)
            self.write_scripts(target, invalid_setup, invalid_start)
            embedded = self.validator.validate_target(target)

        self.assertIn("LW018", self.codes(explicit))
        self.assertTrue({"LW018", "LW019"} <= self.codes(embedded))

    def test_validator_rejects_symlinked_parents_and_escaping_outputs_before_subprocess(self) -> None:
        for kind in ("liveware-parent", "scripts-parent", "setup-output", "start-output"):
            for explicit in (False, True):
                with self.subTest(kind=kind, explicit=explicit), tempfile.TemporaryDirectory() as tmp:
                    root = Path(tmp)
                    target = write_target(root)
                    outside = root / "outside"
                    outside.mkdir()
                    analysis = self.analysis(target)
                    setup, start = self.generated(analysis)
                    if kind == "liveware-parent":
                        outside_liveware = outside / "liveware"
                        outside_scripts = outside_liveware / "scripts"
                        outside_scripts.mkdir(parents=True)
                        (outside_scripts / "setup.py").write_text(setup, encoding="utf-8")
                        (outside_scripts / "start.sh").write_text(start, encoding="utf-8")
                        (target / "liveware").symlink_to(outside_liveware, target_is_directory=True)
                    elif kind == "scripts-parent":
                        (target / "liveware").mkdir()
                        outside_scripts = outside / "scripts"
                        outside_scripts.mkdir()
                        (outside_scripts / "setup.py").write_text(setup, encoding="utf-8")
                        (outside_scripts / "start.sh").write_text(start, encoding="utf-8")
                        (target / "liveware" / "scripts").symlink_to(
                            outside_scripts,
                            target_is_directory=True,
                        )
                    else:
                        self.write_scripts(target, setup, start)
                        name = "setup.py" if kind == "setup-output" else "start.sh"
                        output = target / "liveware" / "scripts" / name
                        outside_file = outside / name
                        outside_file.write_text(output.read_text(encoding="utf-8"), encoding="utf-8")
                        output.unlink()
                        output.symlink_to(outside_file)

                    with mock.patch.object(
                        Path,
                        "read_text",
                        side_effect=AssertionError("unsafe script path was read"),
                    ) as read, mock.patch.object(self.validator.subprocess, "run") as run:
                        findings = self.validator.validate_target(
                            target,
                            analysis=analysis if explicit else None,
                        )
                    self.assertTrue({"LW001", "LW005"} & self.codes(findings))
                    read.assert_not_called()
                    run.assert_not_called()

    def test_canonical_metadata_that_looks_diagnostic_remains_zero_finding(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            target = write_target(Path(tmp))
            analysis = self.analysis(target)
            analysis["display_name"] = (
                "npm install apps[0] os.environ.get('API_TOKEN') author authority"
            )
            setup, start = self.generated(analysis)
            self.assertEqual(self.validator.validate_texts(setup, start), [])
            self.write_scripts(target, setup, start)
            self.assertEqual(self.validator.validate_target(target), [])

    def test_python_and_bash_syntax_findings_remain_explicit(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            target = write_target(Path(tmp))
            analysis = self.analysis(target)
            setup, start = self.generated(analysis)
            findings = self.validator.validate_texts(setup + "\nif :\n", start)
            self.assertIn(
                ("LW006", "liveware/scripts/setup.py", "Python syntax error: invalid syntax"),
                {(item.code, item.path, item.message) for item in findings},
            )
            self.write_scripts(target, setup, start + "\nif then\n")
            findings = self.validator.validate_target(target)
        self.assertIn(
            (
                "LW014",
                str(target / "liveware" / "scripts" / "start.sh"),
                "Bash syntax validation failed.",
            ),
            {(item.code, item.path, item.message) for item in findings},
        )

    def test_nul_in_setup_text_returns_syntax_and_contract_findings(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            analysis = self.analysis(Path(tmp))
            setup, start = self.generated(analysis)

        findings = self.validator.validate_texts(setup + "\x00", start)

        self.assertIn(
            (
                "LW006",
                "liveware/scripts/setup.py",
                "Python syntax error: source contains invalid characters.",
            ),
            {(item.code, item.path, item.message) for item in findings},
        )
        self.assertIn("LW018", self.codes(findings))

    def test_canonical_setup_is_always_checked_for_python_syntax(self) -> None:
        renderer = self.validator.load_renderer()
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            assets = root / "assets"
            assets.mkdir()
            original_assets = Path(renderer.ASSET_ROOT)
            (assets / "setup.py.tmpl").write_text(
                (original_assets / "setup.py.tmpl").read_text(encoding="utf-8")
                + "\nif :\n",
                encoding="utf-8",
            )
            (assets / "start.sh.tmpl").write_text(
                (original_assets / "start.sh.tmpl").read_text(encoding="utf-8"),
                encoding="utf-8",
            )
            analysis = self.analysis(root)
            with mock.patch.object(renderer, "ASSET_ROOT", assets):
                setup = renderer.render_setup(analysis)
                start = renderer.render_start(analysis)
                findings = self.validator.validate_texts(setup, start, analysis=analysis)

        self.assertIn(
            ("LW006", "liveware/scripts/setup.py", "Python syntax error: invalid syntax"),
            {(item.code, item.path, item.message) for item in findings},
        )

    def test_validator_only_spawns_bash_syntax_check(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            target = write_target(Path(tmp))
            analysis = self.analysis(target)
            self.write_scripts(target, *self.generated(analysis))
            completed = mock.Mock(returncode=0)
            with mock.patch.object(self.validator.subprocess, "run", return_value=completed) as run:
                self.assertEqual(self.validator.validate_target(target), [])
        run.assert_called_once_with(
            ["bash", "-n", str(target / "liveware" / "scripts" / "start.sh")],
            capture_output=True,
            text=True,
            check=False,
        )

    def test_legacy_tarot_and_office_fail_with_concise_contract_codes(self) -> None:
        tarot_setup = (REPO_ROOT / "creative/tarot-arcana/liveware/scripts/setup.py").read_text(encoding="utf-8")
        tarot_start = (REPO_ROOT / "creative/tarot-arcana/liveware/scripts/start.sh").read_text(encoding="utf-8")
        tarot_codes = self.codes(self.validator.validate_texts(tarot_setup, tarot_start))
        self.assertTrue({"LW003", "LW010", "LW018", "LW019"} <= tarot_codes)

        office_setup = (
            REPO_ROOT / "productivity/clawchat-officecli/scripts/office-liveware-setup.py"
        ).read_text(encoding="utf-8")
        office_start = (
            REPO_ROOT / "productivity/clawchat-officecli/scripts/office-liveware-start.sh"
        ).read_text(encoding="utf-8")
        office_codes = self.codes(self.validator.validate_texts(office_setup, office_start))
        self.assertTrue({"LW002", "LW004", "LW018", "LW019"} <= office_codes)

    def test_obvious_forbidden_credentials_and_setup_invocation_are_reported(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            analysis = self.analysis(Path(tmp))
            setup, start = self.generated(analysis)
        setup += '\nSECRET = os.environ.get("API_TOKEN")\nsubprocess.run(["pip", "install", "x"])\n'
        start += "\npython3 liveware/scripts/setup.py\n"
        codes = self.codes(self.validator.validate_texts(setup, start))
        self.assertTrue({"LW008", "LW011", "LW015", "LW018", "LW019"} <= codes)

    def test_legacy_diagnostics_ignore_comments_and_unused_python_strings(self) -> None:
        setup = '''#!/usr/bin/env python3
# os.environ.get("API_TOKEN")
# subprocess.run(["pip", "install", "package"])
"""Documentation: os.environ.get("PASSWORD"); npm install package."""
VALUE = "subprocess.run(['liveware', 'app', 'delete', 'other'])"
'''
        start = '''#!/usr/bin/env bash
# kill "$EXISTING_PID"
# pkill server
# npm install package
# printenv API_TOKEN
printf '%s\\n' 'killall server; pip install package; ${API_TOKEN}'
'''

        findings = self.validator.validate_texts(setup, start)

        self.assertTrue({"LW018", "LW019"} <= self.codes(findings))
        self.assertTrue({"LW010", "LW011", "LW015"}.isdisjoint(self.codes(findings)))

    def test_cli_json_exit_status_for_success_corruption_and_invalid_analysis(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            target = write_target(root)
            analysis = self.analysis(target)
            self.write_scripts(target, *self.generated(analysis))
            analysis_path = root / "analysis.json"
            analysis_path.write_text(json.dumps(analysis, ensure_ascii=False), encoding="utf-8")

            success = self.run_cli(target, analysis_path)
            self.assertEqual(success.returncode, 0, success.stderr)
            self.assertEqual(json.loads(success.stdout), [])

            start_path = target / "liveware" / "scripts" / "start.sh"
            start_path.write_text(start_path.read_text(encoding="utf-8") + "# tamper\n", encoding="utf-8")
            failed = self.run_cli(target, analysis_path)
            self.assertEqual(failed.returncode, 1)
            self.assertIn("LW019", {item["code"] for item in json.loads(failed.stdout)})

            analysis_path.write_text("not json", encoding="utf-8")
            invalid = self.run_cli(target, analysis_path)
            self.assertEqual(invalid.returncode, 1)
            self.assertEqual({item["code"] for item in json.loads(invalid.stdout)}, {"LW018"})

    def test_cli_rejects_duplicate_keys_in_explicit_analysis(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            target = write_target(root)
            analysis = self.analysis(target)
            self.write_scripts(target, *self.generated(analysis))
            duplicate = json.dumps(analysis, ensure_ascii=False).replace(
                '"schema_version": 1',
                '"schema_version": 2, "schema_version": 1',
                1,
            )
            analysis_path = root / "analysis.json"
            analysis_path.write_text(duplicate, encoding="utf-8")

            result = self.run_cli(target, analysis_path)

        self.assertEqual(result.returncode, 1)
        self.assertEqual(result.stderr, "")
        self.assertEqual({item["code"] for item in json.loads(result.stdout)}, {"LW018"})

    def test_cli_returns_structured_findings_for_invalid_utf8_scripts(self) -> None:
        for name, code in (("setup.py", "LW018"), ("start.sh", "LW019")):
            with self.subTest(name=name), tempfile.TemporaryDirectory() as tmp:
                target = write_target(Path(tmp))
                analysis = self.analysis(target)
                self.write_scripts(target, *self.generated(analysis))
                (target / "liveware" / "scripts" / name).write_bytes(b"\xff\xfe")

                result = self.run_cli(target)

                self.assertEqual(result.returncode, 1)
                self.assertEqual(result.stderr, "")
                payload = json.loads(result.stdout)
                self.assertIn(code, {item["code"] for item in payload})

    def test_cli_returns_json_for_nul_in_utf8_setup(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            target = write_target(Path(tmp))
            analysis = self.analysis(target)
            setup, start = self.generated(analysis)
            self.write_scripts(target, setup + "\x00", start)

            result = self.run_cli(target)

        self.assertEqual(result.returncode, 1)
        self.assertEqual(result.stderr, "")
        payload = json.loads(result.stdout)
        codes = {item["code"] for item in payload}
        self.assertTrue({"LW006", "LW018"} <= codes)
        self.assertIn(
            {
                "code": "LW006",
                "path": "liveware/scripts/setup.py",
                "message": "Python syntax error: source contains invalid characters.",
            },
            payload,
        )

    def test_target_read_oserror_is_structured_before_bash(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            target = write_target(Path(tmp))
            analysis = self.analysis(target)
            self.write_scripts(target, *self.generated(analysis))
            original_read_text = Path.read_text

            def read_text(path: Path, *args: object, **kwargs: object) -> str:
                if path.name == "setup.py":
                    raise PermissionError("denied")
                return original_read_text(path, *args, **kwargs)

            with mock.patch.object(Path, "read_text", read_text), mock.patch.object(
                self.validator.subprocess,
                "run",
            ) as run:
                findings = self.validator.validate_target(target)

        self.assertIn("LW018", self.codes(findings))
        run.assert_not_called()

    def test_target_symlink_loop_is_structured_for_api_and_cli(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            loop = Path(tmp) / "loop"
            loop.symlink_to(loop, target_is_directory=True)

            direct = self.validator.validate_target(loop)
            cli = self.run_cli(loop)

        self.assertTrue({"LW001", "LW005"} <= self.codes(direct))
        self.assertEqual(cli.returncode, 1)
        self.assertEqual(cli.stderr, "")
        payload = json.loads(cli.stdout)
        self.assertTrue({"LW001", "LW005"} <= {item["code"] for item in payload})

    def test_canonical_pair_stops_validating_after_adapter_path_escapes(self) -> None:
        cases = ("workdir", "static-dir", "evidence")
        for kind in cases:
            with self.subTest(kind=kind), tempfile.TemporaryDirectory() as tmp:
                root = Path(tmp)
                target = write_target(root)
                outside = root / "outside"
                outside.mkdir()
                analysis = self.analysis(target, "managed-command")
                analysis["static_dir"] = None
                if kind == "workdir":
                    analysis["adapter"]["workdir"] = "service"
                    checked = target / "service"
                    checked.mkdir()
                elif kind == "static-dir":
                    analysis = self.analysis(target, "static")
                    analysis["adapter"]["workdir"] = "public"
                    analysis["static_dir"] = "public"
                    checked = target / "public"
                    checked.mkdir()
                else:
                    analysis["evidence"] = [
                        {"path": "proof.js", "reason": "Confirmed server evidence"}
                    ]
                    checked = target / "proof.js"
                    checked.write_text("server proof\n", encoding="utf-8")

                setup, start = self.generated(analysis)
                self.write_scripts(target, setup, start)
                if checked.is_dir():
                    checked.rmdir()
                    checked.symlink_to(outside, target_is_directory=True)
                else:
                    checked.unlink()
                    checked.symlink_to(outside / checked.name)

                findings = self.validator.validate_target(target, analysis=analysis)

            self.assertTrue({"LW018", "LW019"} <= self.codes(findings))


if __name__ == "__main__":
    unittest.main()
