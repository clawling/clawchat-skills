from __future__ import annotations

import re
import stat
import tempfile
import unittest
from pathlib import Path

from tests.creating_liveware_scripts.helpers import (
    SKILL_ROOT,
    load_skill_script,
    write_target,
)


class SkillContentTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.skill_text = (SKILL_ROOT / "SKILL.md").read_text(encoding="utf-8")
        cls.contract_text = (
            SKILL_ROOT / "references" / "liveware-script-contract.md"
        ).read_text(encoding="utf-8")
        cls.ui_text = (SKILL_ROOT / "agents" / "openai.yaml").read_text(
            encoding="utf-8"
        )

    def test_all_skill_owned_text_is_english(self) -> None:
        offenders = []
        for path in SKILL_ROOT.rglob("*"):
            if path.is_file() and path.suffix in {".md", ".yaml", ".py", ".tmpl"}:
                if re.search(r"[\u3400-\u9fff]", path.read_text(encoding="utf-8")):
                    offenders.append(str(path.relative_to(SKILL_ROOT)))
        self.assertEqual(offenders, [])

    def test_frontmatter_is_trigger_only_and_names_fixed_files(self) -> None:
        frontmatter = self.skill_text.split("---", 2)[1].strip().splitlines()
        self.assertEqual(
            frontmatter,
            [
                "name: creating-liveware-scripts",
                "description: Use when creating, auditing, or repairing ClawChat Liveware setup.py and start.sh files for a Hermes skill.",
            ],
        )
        self.assertIn("liveware/scripts/setup.py", self.skill_text)
        self.assertIn("liveware/scripts/start.sh", self.skill_text)
        self.assertIn(
            "Read `references/liveware-script-contract.md` completely.",
            self.skill_text,
        )

    def test_skill_defines_generate_audit_and_repair_modes(self) -> None:
        for phrase in (
            "Generate or apply",
            "Audit",
            "Repair",
            "Audit is read-only",
            "Rebuild `liveware/scripts/setup.py`",
            "matching current setup/start manifests",
            "byte-canonical outside the binding block",
            "Stop when manifests or markers are missing, invalid, or mismatched",
            "run the renderer without `--apply` for a repair preview",
            "rerun the renderer with `--apply`",
            "If repair proof fails, show the read-only canonical diff and do not write",
        ):
            self.assertIn(phrase, self.skill_text)

    def test_workflow_uses_complete_python_commands_and_external_analysis_file(self) -> None:
        commands = (
            'python3 -B .agents/skills/creating-liveware-scripts/scripts/analyze_target.py "$TARGET" >"$ANALYSIS_JSON"',
            'python3 -B .agents/skills/creating-liveware-scripts/scripts/render_scripts.py "$TARGET" "$ANALYSIS_JSON"',
            'python3 -B .agents/skills/creating-liveware-scripts/scripts/render_scripts.py "$TARGET" "$ANALYSIS_JSON" --apply',
            'python3 -B .agents/skills/creating-liveware-scripts/scripts/validate_scripts.py "$TARGET" --analysis "$ANALYSIS_JSON"',
            'python3 -B .agents/skills/creating-liveware-scripts/scripts/validate_scripts.py "$TARGET"',
        )
        for command in commands:
            self.assertIn(command, self.skill_text)
        self.assertIn(
            'ANALYSIS_DIR="$(mktemp -d /tmp/creating-liveware-scripts.XXXXXX)"',
            self.skill_text,
        )
        self.assertIn('ANALYSIS_JSON="$ANALYSIS_DIR/analysis.json"', self.skill_text)
        self.assertIn('>"$ANALYSIS_JSON" || test "$?" -eq 2', self.skill_text)
        for path in (SKILL_ROOT / "scripts").glob("*.py"):
            self.assertEqual(path.stat().st_mode & stat.S_IXUSR, 0)

    def test_workflow_scopes_non_ready_and_port_behavior_exactly(self) -> None:
        for phrase in (
            "Generate and Repair require ready analysis",
            "Audit continues when analysis is not ready",
            "Audit a non-ready target without `--analysis`",
            "Generate/Repair only: status is not `ready`",
            "Only a managed-command adapter refuses an occupied port",
        ):
            self.assertIn(phrase, self.skill_text + "\n" + self.contract_text)

    def test_skill_stays_concise_and_example_uses_exact_readiness_url(self) -> None:
        body = self.skill_text.split("---", 2)[2]
        self.assertLessEqual(len(re.findall(r"\b[\w$<>/{}`.-]+\b", body)), 500)
        self.assertIn("http://127.0.0.1:{port}/healthz", self.skill_text)

    def test_contract_defines_log_path_and_port_token_rules(self) -> None:
        for phrase in (
            "normalized absolute path",
            "`$HOME/` or `${HOME}/`",
            "must not contain `..` or control characters",
            "standalone `{port}` argv item",
            "at most once",
            "consumes the exported `PORT` environment variable",
            'reason exactly `Command consumes exported PORT environment variable`',
        ):
            self.assertIn(phrase, self.contract_text)

    def test_audit_continues_for_non_ready_analysis_without_writing(self) -> None:
        for phrase in (
            "Audit continues when analysis is not ready",
            "run the validator without `--analysis`",
            "report both analyzer issues and validator findings",
            "Do not run `py_compile` in Audit mode",
        ):
            self.assertIn(phrase, self.skill_text)

        analyzer = load_skill_script("analyze_target")
        validator = load_skill_script("validate_scripts")
        with tempfile.TemporaryDirectory() as tmp:
            target = write_target(Path(tmp))
            analysis = analyzer.analyze_target(target)
            scripts = target / "liveware" / "scripts"
            scripts.mkdir(parents=True)
            (scripts / "setup.py").write_text("print('legacy')\n", encoding="utf-8")
            (scripts / "start.sh").write_text(
                "#!/usr/bin/env bash\ntrue\n", encoding="utf-8"
            )
            before = {
                str(path.relative_to(target)): (path.read_bytes(), path.stat().st_mode)
                for path in target.rglob("*")
                if path.is_file()
            }
            findings = validator.validate_target(target)
            after = {
                str(path.relative_to(target)): (path.read_bytes(), path.stat().st_mode)
                for path in target.rglob("*")
                if path.is_file()
            }
        self.assertEqual(analysis["status"], "ambiguous")
        self.assertTrue(findings)
        self.assertTrue({"LW018", "LW019"} <= {item.code for item in findings})
        self.assertEqual(after, before)

    def test_skill_requires_evidence_and_preserves_any_server_shape(self) -> None:
        for phrase in (
            "inspect every evidence path and reason",
            "Do not prescribe Python, Node, a script, or a service shape",
            "command, service manager, lifecycle, readiness, and logging",
            "Do not guess an entrypoint, port, lifecycle owner, readiness check, or log path",
        ):
            self.assertIn(phrase, self.skill_text)

    def test_skill_requires_static_only_validation_without_real_runtime(self) -> None:
        self.assertIn(
            "Do not run generated setup.py or start.sh without a real user-provided environment",
            self.skill_text,
        )
        self.assertIn("Report that runtime validation was not performed", self.skill_text)
        self.assertIn("Never claim fake runtime success", self.skill_text)

    def test_skill_has_scan_sections_example_and_baseline_counters(self) -> None:
        for heading in (
            "## Quick Reference",
            "## Example",
            "## Common Mistakes",
            "## Red Flags",
        ):
            self.assertIn(heading, self.skill_text)
        self.assertIn("externally managed Node service", self.skill_text)
        self.assertIn(
            '"The service already exists" is not permission to guess its port or lifecycle.',
            self.skill_text,
        )
        self.assertIn(
            '"Just verify it" is not permission to run fixtures or generated scripts.',
            self.skill_text,
        )

    def test_contract_defines_closed_analysis_and_canonical_trust_boundary(self) -> None:
        for phrase in (
            "closed schema",
            "No additional fields are allowed",
            "managed-command",
            "existing-launcher",
            "external",
            "static",
            "target-relative `path` and a `reason`",
            "# LIVEWARE ANALYSIS V1: <payload>",
            "identical canonical manifest",
            "exactly re-render both scripts",
            "arbitrary extension fields",
            "must not contain credentials",
            "normalized absolute path with exactly one leading slash",
            "http://127.0.0.1:{port}/",
            "Static adapters require `workdir == static_dir`",
            "External and existing-launcher adapters require target-owned logging",
        ):
            self.assertIn(phrase, self.contract_text)

    def test_external_node_example_uses_the_readiness_placeholder(self) -> None:
        self.assertIn(
            "http://127.0.0.1:{port}/healthz",
            self.skill_text,
        )
        self.assertNotIn(
            "full loopback readiness URL",
            self.skill_text,
        )

    def test_contract_defines_state_setup_and_start_protocols(self) -> None:
        for phrase in (
            "$HOME/.clawling/apps/<skill-name>.json",
            "Multiple Liveware apps per agent",
            "liveware_login()",
            "register_app",
            "one exact `name` match only",
            "never invoke setup automatically",
            "wait for readiness",
            "liveware tunnel bind-static",
            "Liveware ready: <public-url>",
            "command output, not server logging",
        ):
            self.assertIn(phrase, self.contract_text)

    def test_contract_defines_safety_and_runtime_boundary(self) -> None:
        for phrase in (
            "Do not install or download",
            "delete an app",
            "kill an unknown process",
            "read credentials",
            "shell=True",
            "Static validation only",
            "runtime validation was not performed",
            "resolved adapter and evidence paths",
            "Automatic Python and Node candidates are evidence only",
            "user confirms the exact argv, default port",
            "bounded action tokens",
            "service units",
            "PM2",
        ):
            self.assertIn(phrase, self.contract_text)

    def test_contract_requires_confirmed_dynamic_interfaces_and_safe_lifecycle_scan(self) -> None:
        combined = self.skill_text + "\n" + self.contract_text
        for phrase in (
            "Automatic Python and Node candidates are evidence only",
            "Only a static adapter can become `ready` automatically",
            "exact argv, default port, readiness check, lifecycle and logging ownership",
            "root, `liveware/`, `scripts/`, and `liveware/scripts/`",
            "Bullet and numbered-list prefixes",
            "Symlinked lifecycle and reference paths",
            "non-object `scripts` value",
        ):
            self.assertIn(phrase, combined)

    def test_documents_contain_no_initializer_scaffold(self) -> None:
        combined = "\n".join((self.skill_text, self.contract_text, self.ui_text))
        for placeholder in ("[TODO", "@@", "Structuring This Skill"):
            self.assertNotIn(placeholder, combined)

    def test_ui_metadata_is_exact(self) -> None:
        self.assertEqual(
            self.ui_text,
            'interface:\n'
            '  display_name: "Create Liveware Scripts"\n'
            '  short_description: "Generate and audit ClawChat Liveware scripts"\n'
            '  default_prompt: "Use $creating-liveware-scripts to generate or audit setup.py and start.sh for this Hermes skill."\n',
        )


if __name__ == "__main__":
    unittest.main()
