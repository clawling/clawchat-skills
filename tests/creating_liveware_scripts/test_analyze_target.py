from __future__ import annotations

import tempfile
import unittest
import json
import subprocess
import sys
from pathlib import Path
from unittest import mock

from tests.creating_liveware_scripts.helpers import REPO_ROOT, load_skill_script, write_target


class AnalyzeTargetTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.module = load_skill_script("analyze_target")
        cls.renderer = load_skill_script("render_scripts")

    def write_python_candidate(self, target: Path) -> None:
        liveware = target / "liveware"
        liveware.mkdir(exist_ok=True)
        (liveware / "server.py").write_text(
            'DEFAULT_PORT = 5080\nROUTES = ["/healthz"]\n',
            encoding="utf-8",
        )

    def write_node_candidate(self, target: Path) -> None:
        liveware = target / "liveware"
        liveware.mkdir(exist_ok=True)
        (liveware / "package.json").write_text(
            json.dumps({"scripts": {"liveware": "node server.js"}}),
            encoding="utf-8",
        )
        (liveware / "server.js").write_text(
            'const port = Number(process.env.PORT || 4173);\nserver.listen(port);\nconst health = "/healthz";\n',
            encoding="utf-8",
        )

    def write_static_candidate(self, target: Path) -> None:
        static = target / "liveware" / "static"
        static.mkdir(parents=True, exist_ok=True)
        (static / "index.html").write_text("<!doctype html>", encoding="utf-8")

    def test_python_server_requires_a_user_confirmed_interface(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            target = write_target(Path(tmp), display_name="塔罗入口")
            liveware = target / "liveware"
            liveware.mkdir()
            (liveware / "server.py").write_text(
                'DEFAULT_PORT = 5080\nROUTES = ["/healthz"]\n', encoding="utf-8"
            )
            result = self.module.analyze_target(target)
        self.assertEqual(result["status"], "ambiguous")
        self.assertEqual(result["target_root"], str(target.resolve()))
        self.assertFalse(result["target_root"].startswith("//"))
        self.assertEqual(result["skill_name"], "sample-skill")
        self.assertEqual(result["display_name"], "塔罗入口")
        self.assertIsNone(result["adapter"])
        self.assertEqual(result["evidence"][-1]["path"], "liveware/server.py")
        issue = result["issues"][-1]
        for required in (
            "exact argv",
            "default port",
            "readiness",
            "lifecycle",
            "logging",
            "PORT",
        ):
            self.assertIn(required, issue)

    def test_python_source_never_proves_a_dynamic_interface(self) -> None:
        sources = (
            'DEFAULT_PORT = 5080\nROUTES = ["/healthz"]\n',
            'DEFAULT_PORT = 5080\nprint("/healthz")\n',
            'DEFAULT_PORT = 5080\nthis is not valid python\n',
        )
        for source in sources:
            with self.subTest(source=source), tempfile.TemporaryDirectory() as tmp:
                target = write_target(Path(tmp))
                liveware = target / "liveware"
                liveware.mkdir()
                (liveware / "server.py").write_text(source, encoding="utf-8")
                result = self.module.analyze_target(target)
            self.assertIn(result["status"], {"ambiguous", "blocked"})
            self.assertIsNone(result["adapter"])
            self.assertIn(
                "liveware/server.py",
                {item["path"] for item in result["evidence"]},
            )

    def test_detects_static_directory_without_creating_a_server(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            target = write_target(Path(tmp))
            static = target / "liveware" / "static"
            static.mkdir(parents=True)
            (static / "index.html").write_text("<!doctype html>", encoding="utf-8")
            result = self.module.analyze_target(target)
        self.assertEqual(result["status"], "ready")
        self.assertEqual(result["adapter"]["kind"], "static")
        self.assertEqual(result["static_dir"], "liveware/static")
        self.assertEqual(result["adapter"]["command"], [])

    def test_node_service_requires_user_confirmed_interface(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            target = write_target(Path(tmp))
            liveware = target / "liveware"
            liveware.mkdir()
            (liveware / "package.json").write_text(
                json.dumps({"scripts": {"liveware": "node server.js"}}), encoding="utf-8"
            )
            (liveware / "package-lock.json").write_text("{}\n", encoding="utf-8")
            (liveware / "server.js").write_text(
                'const port = Number(process.env.PORT || 4173);\nserver.listen(port);\nconst health = "/healthz";\n',
                encoding="utf-8",
            )
            result = self.module.analyze_target(target)
        self.assertEqual(result["status"], "ambiguous")
        self.assertIsNone(result["adapter"])
        self.assertEqual(
            {item["path"] for item in result["evidence"]},
            {"SKILL.md", "liveware/package.json", "liveware/server.js"},
        )
        self.assertIn("exact argv", result["issues"][-1])
        self.assertIn("exported PORT", result["issues"][-1])
        self.assertIn("readiness", result["issues"][-1])
        self.assertIn("lifecycle", result["issues"][-1])
        self.assertIn("logging", result["issues"][-1])

    def test_node_hardcoded_port_is_ambiguous_without_exported_port_evidence(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            target = write_target(Path(tmp))
            liveware = target / "liveware"
            liveware.mkdir()
            (liveware / "package.json").write_text(
                json.dumps({"scripts": {"liveware": "node server.js --port 4173"}}),
                encoding="utf-8",
            )
            (liveware / "server.js").write_text(
                "const port = 4173;\n",
                encoding="utf-8",
            )
            result = self.module.analyze_target(target)
        self.assertEqual(result["status"], "ambiguous")
        self.assertIsNone(result["adapter"])
        self.assertIn("exported PORT", result["issues"][-1])

    def test_non_object_package_scripts_is_structured_for_api_and_cli(self) -> None:
        for scripts in (None, [], "node server.js"):
            with self.subTest(scripts=scripts), tempfile.TemporaryDirectory() as tmp:
                target = write_target(Path(tmp))
                liveware = target / "liveware"
                liveware.mkdir()
                (liveware / "package.json").write_text(
                    json.dumps({"scripts": scripts}),
                    encoding="utf-8",
                )
                api_result = self.module.analyze_target(target)
                completed = subprocess.run(
                    [sys.executable, str(Path(self.module.__file__)), str(target)],
                    capture_output=True,
                    text=True,
                    check=False,
                )
            self.assertIn(api_result["status"], {"blocked", "ambiguous"})
            self.assertIsNone(api_result["adapter"])
            self.assertEqual(
                set(api_result),
                {
                    "schema_version",
                    "status",
                    "target_root",
                    "skill_name",
                    "display_name",
                    "adapter",
                    "static_dir",
                    "evidence",
                    "issues",
                },
            )
            self.assertEqual(completed.returncode, 2)
            self.assertEqual(completed.stderr, "")
            self.assertEqual(json.loads(completed.stdout)["status"], api_result["status"])

    def test_reports_service_manager_evidence_without_inventing_a_command(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            target = write_target(Path(tmp))
            (target / "supervisord.conf").write_text("[program:sample]\ncommand=node server.js\n", encoding="utf-8")
            result = self.module.analyze_target(target)
        self.assertEqual(result["status"], "ambiguous")
        self.assertIsNone(result["adapter"])
        self.assertEqual(result["evidence"][-1]["path"], "supervisord.conf")
        self.assertIn("requires user confirmation", result["issues"][-1])

    def test_existing_lifecycle_evidence_precedes_every_automatic_candidate(self) -> None:
        cases = (
            (
                "python-start",
                self.write_python_candidate,
                lambda target: (
                    (target / "liveware" / "scripts").mkdir(parents=True),
                    (target / "liveware" / "scripts" / "start.sh").write_text(
                        "#!/usr/bin/env bash\nnohup python3 server.py &\n",
                        encoding="utf-8",
                    ),
                ),
                "liveware/scripts/start.sh",
            ),
            (
                "node-docker",
                self.write_node_candidate,
                lambda target: (target / "Dockerfile").write_text(
                    "CMD [\"npm\", \"run\", \"liveware\"]\n",
                    encoding="utf-8",
                ),
                "Dockerfile",
            ),
            (
                "static-supervisor",
                self.write_static_candidate,
                lambda target: (target / "supervisord.conf").write_text(
                    "[program:liveware]\ncommand=serve liveware/static\n",
                    encoding="utf-8",
                ),
                "supervisord.conf",
            ),
        )
        for name, write_candidate, write_signal, signal_path in cases:
            with self.subTest(name=name), tempfile.TemporaryDirectory() as tmp:
                target = write_target(Path(tmp))
                write_candidate(target)
                write_signal(target)
                result = self.module.analyze_target(target)
            self.assertEqual(result["status"], "ambiguous")
            self.assertIsNone(result["adapter"])
            paths = {item["path"] for item in result["evidence"]}
            self.assertIn(signal_path, paths)
            self.assertTrue(
                any("candidate" in item["reason"].lower() for item in result["evidence"]),
                result["evidence"],
            )

    def test_dynamic_candidate_and_lifecycle_request_one_complete_interface(self) -> None:
        cases = (
            (
                "python-docker",
                self.write_python_candidate,
                "Dockerfile",
                "FROM python:3.12\n",
                "Python",
                "liveware/server.py",
            ),
            (
                "node-docker",
                self.write_node_candidate,
                "Dockerfile",
                "FROM node:22\n",
                "Node",
                "liveware/package.json",
            ),
        )
        for name, write_candidate, signal_path, signal_text, kind, candidate_path in cases:
            with self.subTest(name=name), tempfile.TemporaryDirectory() as tmp:
                target = write_target(Path(tmp))
                write_candidate(target)
                (target / signal_path).write_text(signal_text, encoding="utf-8")
                result = self.module.analyze_target(target)

            self.assertEqual(result["status"], "ambiguous")
            self.assertIsNone(result["adapter"])
            self.assertEqual(len(result["issues"]), 1)
            issue = result["issues"][0]
            self.assertIn(kind, issue)
            for required in (
                "exact argv",
                "default port",
                "readiness",
                "lifecycle",
                "logging",
                "exported PORT",
                "standalone {port}",
            ):
                self.assertIn(required, issue)
            paths = {item["path"] for item in result["evidence"]}
            self.assertIn(signal_path, paths)
            self.assertIn(candidate_path, paths)

    def test_lifecycle_does_not_hide_invalid_node_metadata_or_entrypoints(self) -> None:
        cases = (
            (
                "broken-entry",
                json.dumps({"scripts": {"liveware": "node server.js"}}),
                lambda liveware: (liveware / "server.js").symlink_to("missing-server.js"),
                "liveware/server.js",
            ),
            (
                "malformed-package",
                "{not-json\n",
                lambda liveware: None,
                "liveware/package.json",
            ),
            (
                "non-object-scripts",
                json.dumps({"scripts": []}),
                lambda liveware: None,
                "liveware/package.json",
            ),
        )
        for name, package_text, write_entry, invalid_path in cases:
            with self.subTest(name=name), tempfile.TemporaryDirectory() as tmp:
                target = write_target(Path(tmp))
                liveware = target / "liveware"
                liveware.mkdir()
                (liveware / "package.json").write_text(package_text, encoding="utf-8")
                write_entry(liveware)
                (target / "Dockerfile").write_text("FROM node:22\n", encoding="utf-8")

                api_result = self.module.analyze_target(target)
                completed = subprocess.run(
                    [sys.executable, str(Path(self.module.__file__)), str(target)],
                    capture_output=True,
                    text=True,
                    check=False,
                )

            self.assertEqual(api_result["status"], "blocked")
            self.assertIsNone(api_result["adapter"])
            paths = {item["path"] for item in api_result["evidence"]}
            self.assertIn(invalid_path, paths)
            self.assertIn("Dockerfile", paths)
            self.assertEqual(completed.returncode, 2)
            self.assertEqual(completed.stderr, "")
            cli_result = json.loads(completed.stdout)
            self.assertEqual(cli_result["status"], "blocked")
            self.assertIn(invalid_path, {item["path"] for item in cli_result["evidence"]})
            self.assertIn("Dockerfile", {item["path"] for item in cli_result["evidence"]})

    def test_all_supported_lifecycle_signal_shapes_block_automatic_detection(self) -> None:
        signal_writers = {
            "compose.yaml": lambda target: (target / "compose.yaml").write_text(
                "services:\n  app:\n    image: sample\n", encoding="utf-8"
            ),
            "s6-rc.d": lambda target: (target / "s6-rc.d").mkdir(),
            "scripts/start-liveware-service.sh": lambda target: (
                (target / "scripts").mkdir(),
                (target / "scripts" / "start-liveware-service.sh").write_text(
                    "#!/usr/bin/env bash\nexec sample-service\n", encoding="utf-8"
                ),
            ),
            "references/runtime.md": lambda target: (
                (target / "references").mkdir(),
                (target / "references" / "runtime.md").write_text(
                    "The service lifecycle is owned by the deployment supervisor.\n",
                    encoding="utf-8",
                ),
            ),
        }
        for signal_path, write_signal in signal_writers.items():
            with self.subTest(signal=signal_path), tempfile.TemporaryDirectory() as tmp:
                target = write_target(Path(tmp))
                self.write_static_candidate(target)
                write_signal(target)
                result = self.module.analyze_target(target)
            self.assertEqual(result["status"], "ambiguous")
            self.assertIn(signal_path, {item["path"] for item in result["evidence"]})

    def test_generic_and_non_shell_lifecycle_launchers_block_static_detection(self) -> None:
        launchers = {
            "run-liveware.py": "import liveware_server\nliveware_server.run()\n",
            "start.js": "app.listen(process.env.PORT);\n",
            "start.ts": "serve();\n",
            "liveware/run-liveware.py": "import liveware_server\nliveware_server.run()\n",
            "liveware/start.js": "app.listen(process.env.PORT);\n",
            "liveware/start.rb": "serve\n",
            "scripts/start.sh": "#!/usr/bin/env bash\nexec liveware-server\n",
            "scripts/run-liveware.py": "import liveware_server\nliveware_server.run()\n",
            "scripts/start.js": "app.listen(process.env.PORT);\n",
            "scripts/start.ts": "serve();\n",
            "scripts/launch-app.mjs": "export default {};\n",
            "liveware/scripts/start.rb": "serve\n",
        }
        for launcher, content in launchers.items():
            with self.subTest(launcher=launcher), tempfile.TemporaryDirectory() as tmp:
                target = write_target(Path(tmp))
                self.write_static_candidate(target)
                path = target / launcher
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_text(content, encoding="utf-8")
                result = self.module.analyze_target(target)
            self.assertEqual(result["status"], "ambiguous")
            self.assertIn(launcher, {item["path"] for item in result["evidence"]})

    def test_harmless_script_names_do_not_count_as_lifecycle_evidence(self) -> None:
        scripts = {
            "scripts/restart-tests.sh": "#!/usr/bin/env bash\nprintf 'tests only\\n'\n",
            "scripts/test-liveware.py": "print('schema test only')\n",
            "scripts/liveware-lint.js": "console.log('lint only');\n",
            "scripts/start.md": "Runbook only.\n",
            "scripts/start.txt": "Runbook only.\n",
            "scripts/start.backup": "Runbook only.\n",
        }
        for script, content in scripts.items():
            with self.subTest(script=script), tempfile.TemporaryDirectory() as tmp:
                target = write_target(Path(tmp))
                self.write_static_candidate(target)
                directory = target / "scripts"
                directory.mkdir()
                (target / script).write_text(content, encoding="utf-8")
                result = self.module.analyze_target(target)
            self.assertEqual(result["status"], "ready")
            self.assertEqual(result["adapter"]["kind"], "static")

    def test_unrelated_outside_symlinks_do_not_count_as_lifecycle_evidence(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            target = write_target(root)
            self.write_static_candidate(target)
            outside = root / "outside"
            outside.mkdir()
            note = outside / "README.md"
            note.write_text("Unrelated notes.\n", encoding="utf-8")
            (target / "README-link.md").symlink_to(note)
            scripts = target / "scripts"
            scripts.mkdir()
            harmless = outside / "restart-tests.sh"
            harmless.write_text("#!/usr/bin/env bash\ntrue\n", encoding="utf-8")
            (scripts / "restart-tests.sh").symlink_to(harmless)
            result = self.module.analyze_target(target)
        self.assertEqual(result["status"], "ready")
        self.assertEqual(result["adapter"]["kind"], "static")

    def test_reference_filename_without_lifecycle_declaration_does_not_block(self) -> None:
        texts = (
            "# Product notes\nThis page describes visible UI labels only.\n",
            "The Docker SDK client is available through the API.\n",
            "The Start command is displayed in the menu.\n",
            "Run scripts/check-liveware.sh for linting only.\n",
            "For tests, run scripts/start-server.sh.\n",
            "For linting only, use scripts/start-server.sh.\n",
            "As an example, run scripts/start-server.sh.\n",
            "For example, run scripts/start-server.sh.\n",
            "E.g., launch scripts/start-server.sh.\n",
            "Do not run scripts/start-server.sh.\n",
            "Never invoke scripts/start-server.sh.\n",
            "Run scripts/start-server.sh is obsolete.\n",
            "Use deprecated scripts/start-server.sh.\n",
            "This deprecated example says to run scripts/start-server.sh.\n",
            "You should never launch scripts/start-server.sh.\n",
        )
        for text in texts:
            with self.subTest(text=text), tempfile.TemporaryDirectory() as tmp:
                target = write_target(Path(tmp))
                self.write_static_candidate(target)
                references = target / "references"
                references.mkdir()
                (references / "service.md").write_text(text, encoding="utf-8")
                result = self.module.analyze_target(target)
            self.assertEqual(result["status"], "ready")
            self.assertEqual(result["adapter"]["kind"], "static")

    def test_reference_action_qualifiers_do_not_hide_later_affirmative_commands(self) -> None:
        texts = (
            "Do not run scripts/old-start-server.sh; run scripts/start-server.sh.\n",
            "Do not run scripts/old-start-server.sh but run scripts/start-server.sh.\n",
            "For example, run scripts/example-start-server.sh. Run scripts/start-server.sh.\n",
            "Never invoke scripts/old-start-server.sh; use scripts/run-liveware.py.\n",
        )
        for text in texts:
            with self.subTest(text=text), tempfile.TemporaryDirectory() as tmp:
                target = write_target(Path(tmp))
                self.write_static_candidate(target)
                references = target / "references"
                references.mkdir()
                (references / "runtime.md").write_text(text, encoding="utf-8")
                result = self.module.analyze_target(target)
            self.assertEqual(result["status"], "ambiguous")
            self.assertIn(
                "references/runtime.md",
                {item["path"] for item in result["evidence"]},
            )

    def test_common_negative_example_and_deprecated_actions_are_harmless(self) -> None:
        texts = (
            "Don't run scripts/start-server.sh.\n",
            "You should not run scripts/start-server.sh.\n",
            "You shouldn't run scripts/start-server.sh.\n",
            "You can't run scripts/start-server.sh.\n",
            "Example: run scripts/start-server.sh.\n",
            "Run scripts/start-server.sh (deprecated).\n",
        )
        for text in texts:
            with self.subTest(text=text), tempfile.TemporaryDirectory() as tmp:
                target = write_target(Path(tmp))
                self.write_static_candidate(target)
                references = target / "references"
                references.mkdir()
                (references / "runtime.md").write_text(text, encoding="utf-8")
                result = self.module.analyze_target(target)
            self.assertEqual(result["status"], "ready")
            self.assertEqual(result["adapter"]["kind"], "static")

    def test_unrelated_not_before_colon_does_not_suppress_a_launcher(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            target = write_target(Path(tmp))
            self.write_static_candidate(target)
            references = target / "references"
            references.mkdir()
            (references / "runtime.md").write_text(
                "It is not optional: run scripts/start-server.sh.\n",
                encoding="utf-8",
            )

            api_result = self.module.analyze_target(target)
            completed = subprocess.run(
                [sys.executable, str(Path(self.module.__file__)), str(target)],
                capture_output=True,
                text=True,
                check=False,
            )

        self.assertEqual(api_result["status"], "ambiguous")
        self.assertIn(
            "references/runtime.md",
            {item["path"] for item in api_result["evidence"]},
        )
        self.assertEqual(completed.returncode, 2)
        self.assertEqual(completed.stderr, "")
        cli_result = json.loads(completed.stdout)
        self.assertEqual(cli_result["status"], "ambiguous")
        self.assertIn(
            "references/runtime.md",
            {item["path"] for item in cli_result["evidence"]},
        )

    def test_negative_action_scope_ends_at_an_affirmative_clause(self) -> None:
        texts = (
            "Don't run scripts/old-start-server.sh, but run scripts/start-server.sh.\n",
            "You should not run scripts/old-start-server.sh; use scripts/run-liveware.py.\n",
            "Example: run scripts/example-start-server.sh, then run scripts/start-server.sh.\n",
            "Run scripts/old-start-server.sh (deprecated), but run scripts/start-server.sh.\n",
        )
        for text in texts:
            with self.subTest(text=text), tempfile.TemporaryDirectory() as tmp:
                target = write_target(Path(tmp))
                self.write_static_candidate(target)
                references = target / "references"
                references.mkdir()
                (references / "runtime.md").write_text(text, encoding="utf-8")
                result = self.module.analyze_target(target)
            self.assertEqual(result["status"], "ambiguous")
            self.assertIn(
                "references/runtime.md",
                {item["path"] for item in result["evidence"]},
            )

    def test_common_reference_lifecycle_ownership_phrases_are_detected(self) -> None:
        declarations = (
            "systemd owns the service lifecycle.\n",
            "The server is managed with systemd.\n",
            "The service runs under supervisor.\n",
            "PM2 manages the service in production.\n",
            "The server is managed by a systemd service unit.\n",
            "Use systemctl start probe.service.\n",
            "- PM2 manages the service in production.\n",
            "1. The service runs under supervisor.\n",
            "Run scripts/start-server.sh in production and update documentation.\n",
            "Run scripts/start-server.sh to launch the service and run tests afterward.\n",
            "In production, PM2 manages the service.\n",
            "At runtime, the service is managed by systemd.\n",
            "For production, supervisor runs the service.\n",
            "During runtime, the server runs under s6.\n",
            "In production: PM2 manages the service.\n",
            "- At runtime: systemd owns the process.\n",
        )
        for declaration in declarations:
            with self.subTest(declaration=declaration), tempfile.TemporaryDirectory() as tmp:
                target = write_target(Path(tmp))
                self.write_static_candidate(target)
                references = target / "references"
                references.mkdir()
                (references / "runtime.md").write_text(declaration, encoding="utf-8")
                result = self.module.analyze_target(target)
            self.assertEqual(result["status"], "ambiguous")
            self.assertIn(
                "references/runtime.md",
                {item["path"] for item in result["evidence"]},
            )

    def test_lifecycle_qualifiers_do_not_cross_sentence_boundaries(self) -> None:
        texts = (
            "In production. PM2 appears in a screenshot.\n",
            "At runtime. The Start command is displayed in the menu.\n",
            "For production. This page documents PM2 badges.\n",
        )
        for text in texts:
            with self.subTest(text=text), tempfile.TemporaryDirectory() as tmp:
                target = write_target(Path(tmp))
                self.write_static_candidate(target)
                references = target / "references"
                references.mkdir()
                (references / "runtime.md").write_text(text, encoding="utf-8")
                result = self.module.analyze_target(target)
            self.assertEqual(result["status"], "ready")
            self.assertEqual(result["adapter"]["kind"], "static")

    def test_broken_known_symlinks_return_structured_block_for_api_and_cli(self) -> None:
        def python_candidate(target: Path) -> str:
            (target / "liveware").mkdir(exist_ok=True)
            (target / "liveware" / "server.py").symlink_to("missing-server.py")
            return "liveware/server.py"

        def node_candidate(target: Path) -> str:
            (target / "liveware").mkdir(exist_ok=True)
            (target / "liveware" / "package.json").symlink_to("missing-package.json")
            return "liveware/package.json"

        def static_candidate(target: Path) -> str:
            index = target / "liveware" / "static" / "index.html"
            index.unlink()
            index.symlink_to("missing-index.html")
            return "liveware/static/index.html"

        def node_entry(target: Path) -> str:
            liveware = target / "liveware"
            (liveware / "package.json").write_text(
                json.dumps({"scripts": {"liveware": "node server.js"}}),
                encoding="utf-8",
            )
            (liveware / "server.js").symlink_to("missing-server.js")
            return "liveware/server.js"

        def lifecycle_file(target: Path) -> str:
            scripts = target / "scripts"
            scripts.mkdir()
            (scripts / "start.sh").symlink_to("missing-start.sh")
            return "scripts/start.sh"

        def liveware_lifecycle_file(target: Path) -> str:
            scripts = target / "liveware" / "scripts"
            scripts.mkdir()
            (scripts / "start.sh").symlink_to("missing-start.sh")
            return "liveware/scripts/start.sh"

        def manager_file(target: Path) -> str:
            (target / "Dockerfile").symlink_to("missing-Dockerfile")
            return "Dockerfile"

        def reference_file(target: Path) -> str:
            references = target / "references"
            references.mkdir()
            (references / "runtime.md").symlink_to("missing-runtime.md")
            return "references/runtime.md"

        def reference_directory(target: Path) -> str:
            (target / "references").symlink_to("missing-references", target_is_directory=True)
            return "references"

        for build in (
            python_candidate,
            node_candidate,
            static_candidate,
            node_entry,
            lifecycle_file,
            liveware_lifecycle_file,
            manager_file,
            reference_file,
            reference_directory,
        ):
            with self.subTest(build=build.__name__), tempfile.TemporaryDirectory() as tmp:
                target = write_target(Path(tmp))
                self.write_static_candidate(target)
                relative = build(target)
                api_result = self.module.analyze_target(target)
                completed = subprocess.run(
                    [sys.executable, str(Path(self.module.__file__)), str(target)],
                    capture_output=True,
                    text=True,
                    check=False,
                )

            self.assertEqual(api_result["status"], "blocked")
            self.assertIsNone(api_result["adapter"])
            self.assertIn(relative, {item["path"] for item in api_result["evidence"]})
            self.assertTrue(any("symlink" in issue.lower() for issue in api_result["issues"]))
            self.assertEqual(completed.returncode, 2)
            self.assertEqual(completed.stderr, "")
            cli_result = json.loads(completed.stdout)
            self.assertEqual(cli_result["status"], "blocked")
            self.assertIn(relative, {item["path"] for item in cli_result["evidence"]})

    def test_lifecycle_and_reference_symlinks_are_containment_checked(self) -> None:
        def lifecycle_file(target: Path, storage: Path, outside: bool) -> str:
            storage.mkdir(exist_ok=True)
            destination = storage / "run-liveware.py"
            destination.write_text("print('launcher')\n", encoding="utf-8")
            scripts = target / "scripts"
            scripts.mkdir()
            (scripts / "run-liveware.py").symlink_to(destination)
            return "scripts/run-liveware.py"

        def scripts_directory(target: Path, storage: Path, outside: bool) -> str:
            storage.mkdir(exist_ok=True)
            (storage / "start.js").write_text("app.listen(4173);\n", encoding="utf-8")
            (target / "scripts").symlink_to(storage, target_is_directory=True)
            return "scripts/start.js"

        def reference_file(target: Path, storage: Path, outside: bool) -> str:
            storage.mkdir(exist_ok=True)
            destination = storage / "runtime.md"
            destination.write_text("PM2 manages the service.\n", encoding="utf-8")
            references = target / "references"
            references.mkdir()
            (references / "runtime.md").symlink_to(destination)
            return "references/runtime.md"

        def references_directory(target: Path, storage: Path, outside: bool) -> str:
            storage.mkdir(exist_ok=True)
            (storage / "runtime.md").write_text(
                "- PM2 manages the service.\n",
                encoding="utf-8",
            )
            (target / "references").symlink_to(storage, target_is_directory=True)
            return "references/runtime.md"

        builders = (lifecycle_file, scripts_directory, reference_file, references_directory)
        for build in builders:
            for outside in (False, True):
                with (
                    self.subTest(build=build.__name__, outside=outside),
                    tempfile.TemporaryDirectory() as tmp,
                ):
                    root = Path(tmp)
                    target = write_target(root)
                    self.write_static_candidate(target)
                    storage = (
                        root / "outside" / build.__name__
                        if outside
                        else target / "contained" / build.__name__
                    )
                    storage.parent.mkdir(parents=True, exist_ok=True)
                    evidence_path = build(target, storage, outside)
                    result = self.module.analyze_target(target)
                if outside:
                    self.assertEqual(result["status"], "blocked")
                    self.assertIsNone(result["adapter"])
                    self.assertTrue(any("outside" in issue.lower() for issue in result["issues"]))
                    expected_evidence = {
                        evidence_path,
                        evidence_path.split("/", 1)[0],
                    }
                else:
                    self.assertEqual(result["status"], "ambiguous")
                    expected_evidence = {evidence_path}
                self.assertTrue(
                    expected_evidence
                    & {item["path"] for item in result["evidence"]}
                )

    def test_lifecycle_directory_oserror_returns_structured_block(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            target = write_target(Path(tmp))
            self.write_static_candidate(target)
            scripts = target / "scripts"
            scripts.mkdir()
            original = Path.iterdir

            def raising(path: Path):
                if path.resolve() == scripts.resolve():
                    raise OSError("simulated enumeration failure")
                return original(path)

            with mock.patch.object(Path, "iterdir", raising):
                result = self.module.analyze_target(target)
        self.assertEqual(result["status"], "blocked")
        self.assertIsNone(result["adapter"])
        self.assertIn("scripts", {item["path"] for item in result["evidence"]})

    def test_service_units_and_pm2_configs_are_lifecycle_evidence(self) -> None:
        paths = (
            "probe.service",
            "liveware/probe.service",
            "ecosystem.config.js",
            "liveware/pm2.config.cjs",
        )
        for relative in paths:
            with self.subTest(relative=relative), tempfile.TemporaryDirectory() as tmp:
                target = write_target(Path(tmp))
                self.write_static_candidate(target)
                path = target / relative
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_text("module.exports = {};\n", encoding="utf-8")
                result = self.module.analyze_target(target)
            self.assertEqual(result["status"], "ambiguous")
            self.assertIn(relative, {item["path"] for item in result["evidence"]})

    def test_reference_and_script_examples_without_ownership_are_safe(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            target = write_target(Path(tmp))
            self.write_static_candidate(target)
            references = target / "references"
            references.mkdir()
            (references / "runtime.md").write_text(
                "This guide explains the service lifecycle. Run unit tests with pytest.\n"
                "Use PM2 badges in documentation.\n"
                "The PM2 dashboard manages server color labels.\n"
                "Use scripts/start-server.sh for linting only.\n",
                encoding="utf-8",
            )
            scripts = target / "scripts"
            scripts.mkdir()
            (scripts / "examples.js").write_text(
                "console.log('server.start() is an example only');\n",
                encoding="utf-8",
            )
            result = self.module.analyze_target(target)
        self.assertEqual(result["status"], "ready")
        self.assertEqual(result["adapter"]["kind"], "static")

    def test_unreadable_lifecycle_directories_are_structured_for_api_and_cli(self) -> None:
        for directory_name in ("scripts", "references"):
            with self.subTest(directory=directory_name), tempfile.TemporaryDirectory() as tmp:
                target = write_target(Path(tmp))
                self.write_static_candidate(target)
                directory = target / directory_name
                directory.mkdir()
                filename = "start.js" if directory_name == "scripts" else "runtime.md"
                (directory / filename).write_text(
                    "PM2 manages the service.\n",
                    encoding="utf-8",
                )
                directory.chmod(0)
                try:
                    api_result = self.module.analyze_target(target)
                    completed = subprocess.run(
                        [sys.executable, str(Path(self.module.__file__)), str(target)],
                        capture_output=True,
                        text=True,
                        check=False,
                    )
                finally:
                    directory.chmod(0o755)

            self.assertIn(api_result["status"], {"blocked", "ambiguous"})
            self.assertIn(directory_name, {item["path"] for item in api_result["evidence"]})
            self.assertEqual(completed.returncode, 2)
            self.assertEqual(completed.stderr, "")
            self.assertIn(json.loads(completed.stdout)["status"], {"blocked", "ambiguous"})

    def test_unreadable_reference_cannot_prove_lifecycle_absence(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            target = write_target(Path(tmp))
            self.write_static_candidate(target)
            references = target / "references"
            references.mkdir()
            (references / "runtime.md").write_bytes(b"\xff")

            api_result = self.module.analyze_target(target)
            completed = subprocess.run(
                [sys.executable, str(Path(self.module.__file__)), str(target)],
                capture_output=True,
                text=True,
                check=False,
            )

        self.assertIn(api_result["status"], {"blocked", "ambiguous"})
        self.assertIn(
            "references/runtime.md",
            {item["path"] for item in api_result["evidence"]},
        )
        self.assertEqual(completed.returncode, 2)
        self.assertEqual(completed.stderr, "")
        self.assertIn(json.loads(completed.stdout)["status"], {"blocked", "ambiguous"})

    def test_symlinked_automatic_candidates_outside_target_never_become_ready(self) -> None:
        def static_parent(target: Path, outside: Path) -> str:
            external = outside / "static"
            external.mkdir()
            (external / "index.html").write_text("<!doctype html>", encoding="utf-8")
            (target / "liveware").mkdir()
            (target / "liveware" / "static").symlink_to(external, target_is_directory=True)
            return "liveware/static/index.html"

        def static_file(target: Path, outside: Path) -> str:
            external = outside / "index.html"
            external.write_text("<!doctype html>", encoding="utf-8")
            static = target / "liveware" / "static"
            static.mkdir(parents=True)
            (static / "index.html").symlink_to(external)
            return "liveware/static/index.html"

        def python_server(target: Path, outside: Path) -> str:
            external = outside / "server.py"
            external.write_text("DEFAULT_PORT = 5080\n", encoding="utf-8")
            (target / "liveware").mkdir()
            (target / "liveware" / "server.py").symlink_to(external)
            return "liveware/server.py"

        def package_file(target: Path, outside: Path) -> str:
            external = outside / "package.json"
            external.write_text(
                json.dumps({"scripts": {"liveware": "node server.js"}}),
                encoding="utf-8",
            )
            (outside / "server.js").write_text(
                "const port = process.env.PORT || 4173;\nserver.listen(port);\n",
                encoding="utf-8",
            )
            (target / "liveware").mkdir()
            (target / "liveware" / "package.json").symlink_to(external)
            return "liveware/package.json"

        def node_entry(target: Path, outside: Path) -> str:
            (target / "liveware").mkdir()
            (target / "liveware" / "package.json").write_text(
                json.dumps({"scripts": {"liveware": "node server.js"}}),
                encoding="utf-8",
            )
            external = outside / "server.js"
            external.write_text(
                "const port = process.env.PORT || 4173;\nserver.listen(port);\n",
                encoding="utf-8",
            )
            (target / "liveware" / "server.js").symlink_to(external)
            return "liveware/server.js"

        def liveware_parent(target: Path, outside: Path) -> str:
            external = outside / "liveware"
            external.mkdir()
            (external / "server.py").write_text("DEFAULT_PORT = 5080\n", encoding="utf-8")
            (target / "liveware").symlink_to(external, target_is_directory=True)
            return "liveware/server.py"

        for build in (
            static_parent,
            static_file,
            python_server,
            package_file,
            node_entry,
            liveware_parent,
        ):
            with self.subTest(build=build.__name__), tempfile.TemporaryDirectory() as tmp:
                root = Path(tmp)
                target = write_target(root)
                outside = root / "outside"
                outside.mkdir()
                evidence_path = build(target, outside)
                result = self.module.analyze_target(target)
            self.assertIn(result["status"], {"blocked", "ambiguous"})
            self.assertIsNone(result["adapter"])
            self.assertIn(evidence_path, {item["path"] for item in result["evidence"]})
            self.assertTrue(any("outside" in issue.lower() for issue in result["issues"]))

    def test_unreadable_inputs_return_structured_analysis_for_api_and_cli(self) -> None:
        cases = ("SKILL.md", "liveware/server.py", "liveware/package.json", "liveware/server.js")
        for relative in cases:
            with self.subTest(relative=relative), tempfile.TemporaryDirectory() as tmp:
                target = write_target(Path(tmp))
                liveware = target / "liveware"
                liveware.mkdir(exist_ok=True)
                if relative.endswith("server.py"):
                    (target / relative).write_bytes(b"\xff")
                elif relative.endswith("package.json"):
                    (target / relative).write_bytes(b"\xff")
                elif relative.endswith("server.js"):
                    (liveware / "package.json").write_text(
                        json.dumps({"scripts": {"liveware": "node server.js"}}),
                        encoding="utf-8",
                    )
                    (target / relative).write_bytes(b"\xff")
                else:
                    (target / relative).write_bytes(b"\xff")

                api_result = self.module.analyze_target(target)
                completed = subprocess.run(
                    [sys.executable, str(Path(self.module.__file__)), str(target)],
                    capture_output=True,
                    text=True,
                    check=False,
                )
            self.assertIn(api_result["status"], {"blocked", "ambiguous"})
            self.assertTrue(api_result["issues"])
            self.assertEqual(completed.returncode, 2)
            self.assertEqual(completed.stderr, "")
            cli_result = json.loads(completed.stdout)
            self.assertIn(cli_result["status"], {"blocked", "ambiguous"})
            self.assertTrue(cli_result["issues"])

    def test_oserror_at_each_required_read_is_structured_instead_of_raising(self) -> None:
        def build(target: Path, relative: str) -> Path:
            path = target / relative
            if relative == "SKILL.md":
                return path
            liveware = target / "liveware"
            liveware.mkdir()
            if relative == "liveware/server.py":
                path.write_text("DEFAULT_PORT = 5080\n", encoding="utf-8")
            elif relative == "liveware/package.json":
                path.write_text(
                    json.dumps({"scripts": {"liveware": "node server.js"}}),
                    encoding="utf-8",
                )
            else:
                (liveware / "package.json").write_text(
                    json.dumps({"scripts": {"liveware": "node server.js"}}),
                    encoding="utf-8",
                )
                path.write_text(
                    "const port = process.env.PORT || 4173;\nserver.listen(port);\n",
                    encoding="utf-8",
                )
            return path

        for relative in (
            "SKILL.md",
            "liveware/server.py",
            "liveware/package.json",
            "liveware/server.js",
        ):
            with self.subTest(relative=relative), tempfile.TemporaryDirectory() as tmp:
                target = write_target(Path(tmp))
                failing = build(target, relative)
                original = Path.read_text

                def raising(path: Path, *args: object, **kwargs: object) -> str:
                    if path.resolve() == failing.resolve():
                        raise OSError("simulated read failure")
                    return original(path, *args, **kwargs)

                with mock.patch.object(Path, "read_text", raising):
                    result = self.module.analyze_target(target)
            self.assertIn(result["status"], {"blocked", "ambiguous"})
            self.assertIn(relative, {item["path"] for item in result["evidence"]})
            self.assertTrue(any("read" in issue.lower() for issue in result["issues"]))

    def test_exact_canonical_generated_start_is_not_lifecycle_ambiguity(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            target = write_target(Path(tmp))
            self.write_static_candidate(target)
            first = self.module.analyze_target(target)
            scripts = target / "liveware" / "scripts"
            scripts.mkdir(parents=True)
            (scripts / "start.sh").write_text(
                self.renderer.render_start(first),
                encoding="utf-8",
            )
            second = self.module.analyze_target(target)
        self.assertEqual(first["status"], "ready")
        self.assertEqual(second, first)

    def test_plausible_or_tampered_generated_markers_do_not_hide_a_launcher(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            target = write_target(Path(tmp))
            self.write_static_candidate(target)
            analysis = self.module.analyze_target(target)
            scripts = target / "liveware" / "scripts"
            scripts.mkdir(parents=True)
            canonical = self.renderer.render_start(analysis)
            (scripts / "start.sh").write_text(
                canonical.replace(
                    "# Static content requires no server process.",
                    "# Tampered static launcher.\n# Static content requires no server process.",
                    1,
                ),
                encoding="utf-8",
            )
            result = self.module.analyze_target(target)
        self.assertEqual(result["status"], "ambiguous")
        self.assertIn(
            "liveware/scripts/start.sh",
            {item["path"] for item in result["evidence"]},
        )

    def test_real_tarot_launcher_prevents_automatic_python_replacement(self) -> None:
        target = REPO_ROOT / "skills" / "tarot-arcana"
        result = self.module.analyze_target(target)
        self.assertEqual(result["status"], "ambiguous")
        self.assertIsNone(result["adapter"])
        self.assertIn(
            "scripts/liveware/start.sh",
            {item["path"] for item in result["evidence"]},
        )

    def test_python_candidate_does_not_probe_dependencies_before_confirmation(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            target = write_target(Path(tmp))
            liveware = target / "liveware"
            liveware.mkdir()
            (liveware / "server.py").write_text("DEFAULT_PORT = 5080\n", encoding="utf-8")
            result = self.module.analyze_target(target)
        self.assertEqual(result["status"], "ambiguous")
        self.assertIsNone(result["adapter"])
        self.assertFalse(any("Missing required command" in issue for issue in result["issues"]))

    def test_reports_ambiguous_instead_of_guessing_a_port(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            target = write_target(Path(tmp))
            liveware = target / "liveware"
            liveware.mkdir()
            (liveware / "server.py").write_text("print('server')\n", encoding="utf-8")
            result = self.module.analyze_target(target)
        self.assertEqual(result["status"], "ambiguous")
        self.assertIn("exact argv", result["issues"][-1])

    def test_blocks_invalid_or_missing_skill_metadata(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            target = Path(tmp) / "broken"
            target.mkdir()
            (target / "SKILL.md").write_text("# Missing frontmatter\n", encoding="utf-8")
            result = self.module.analyze_target(target)
        self.assertEqual(result["status"], "blocked")
        self.assertIn("SKILL.md must contain a valid name", result["issues"])


if __name__ == "__main__":
    unittest.main()
