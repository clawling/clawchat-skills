from __future__ import annotations

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

    def test_detects_tarot_state_arguments_and_unknown_process_kill(self) -> None:
        setup = (REPO_ROOT / "creative/tarot-arcana/liveware/scripts/setup.py").read_text(encoding="utf-8")
        start = (REPO_ROOT / "creative/tarot-arcana/liveware/scripts/start.sh").read_text(encoding="utf-8")
        codes = {finding.code for finding in self.validator.validate_texts(setup, start)}
        self.assertIn("LW003", codes)
        self.assertIn("LW008", codes)
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


if __name__ == "__main__":
    unittest.main()
