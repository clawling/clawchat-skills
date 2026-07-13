# Creating Liveware Scripts Skill Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build a repository-scoped Codex skill that safely generates, audits, and repairs ClawChat Liveware `setup.py` and `start.sh` files for arbitrary Hermes skill servers.

**Architecture:** Create a read-only target analyzer, a deterministic renderer backed by two templates, and a static validator. Keep the target server adapter separate from the standard Liveware binding block so the skill can preserve Python, Node, static, existing-launcher, or externally managed server interfaces without standardizing the server itself.

**Tech Stack:** Python 3 standard library, Bash, `unittest`, Codex skill metadata, and the existing `skill-creator` validation scripts.

## Global Constraints

- Put the Codex skill at `.agents/skills/creating-liveware-scripts/`; it is not a Hermes skill.
- Write every skill-owned file, comment, help string, error message, template, and generated-script message in English.
- Preserve user-provided commands, paths, service names, `name`, and `display_name` values without translation.
- Generate only `<target-skill>/liveware/scripts/setup.py` and `<target-skill>/liveware/scripts/start.sh`.
- Standardize Liveware integration, not the target server architecture, lifecycle, PID ownership, or logging strategy.
- Store per-skill state at `$HOME/.clawling/apps/<skill-name>.json`, with directories mode `0700`, files mode `0600`, and atomic replacement.
- Authenticate only through `clawchat_gateway.tools.liveware_login()`; never read, print, save, or directly pass a token.
- Never install dependencies, delete Liveware apps, kill unknown processes, use `shell=True`, or bind a dynamic tunnel to a non-loopback upstream.
- Treat ambiguous entrypoints, ports, lifecycle ownership, readiness checks, or logging ownership as blocking questions; never guess.
- Without a real user-provided Hermes/ClawChat/Liveware environment, run static checks only. Do not run generated setup/start scripts and do not create fake plugins, CLIs, servers, or successful runtime simulations.
- Use `name` for `liveware app create`, state filenames, and identity. Use `display_name`, falling back to `name`, only for ClawChat registration.

## File Map

| Path | Responsibility |
| --- | --- |
| `.agents/skills/creating-liveware-scripts/SKILL.md` | English trigger metadata and agent workflow |
| `.agents/skills/creating-liveware-scripts/agents/openai.yaml` | English UI metadata |
| `.agents/skills/creating-liveware-scripts/scripts/analyze_target.py` | Read-only metadata, entrypoint, dependency, port, readiness, lifecycle, and logging analysis |
| `.agents/skills/creating-liveware-scripts/scripts/render_scripts.py` | Deterministic generation and marker-aware repair |
| `.agents/skills/creating-liveware-scripts/scripts/validate_scripts.py` | Static syntax, security, contract, and project-consistency checks |
| `.agents/skills/creating-liveware-scripts/assets/setup.py.tmpl` | Complete idempotent Liveware application setup template |
| `.agents/skills/creating-liveware-scripts/assets/start.sh.tmpl` | Server-adapter and Liveware-binding template |
| `.agents/skills/creating-liveware-scripts/references/liveware-script-contract.md` | Detailed English protocol and state contract |
| `tests/__init__.py` | Makes repository tests importable as a package |
| `tests/creating_liveware_scripts/helpers.py` | Dynamic import and disposable target helpers |
| `tests/creating_liveware_scripts/test_analyze_target.py` | Analyzer unit tests |
| `tests/creating_liveware_scripts/test_render_scripts.py` | Template and repair unit tests |
| `tests/creating_liveware_scripts/test_validate_scripts.py` | Validator and legacy-script regression tests |
| `tests/creating_liveware_scripts/test_skill_content.py` | English-only and skill-metadata checks |
| `docs/superpowers/evals/2026-07-13-creating-liveware-scripts.md` | Baseline and forward-test evidence |

---

### Task 1: Capture the No-Skill Baseline

**Files:**
- Create: `docs/superpowers/evals/2026-07-13-creating-liveware-scripts.md`

**Interfaces:**
- Consumes: the approved design and read-only copies of `creative/tarot-arcana` and `productivity/clawchat-officecli`
- Produces: verbatim no-skill behavior, a scored failure list, and the exact prompts reused for guided evaluation

- [ ] **Step 1: Create two disposable real-project copies**

Run from the repository root:

```bash
BASELINE_ROOT="$(mktemp -d /tmp/creating-liveware-scripts-baseline.XXXXXX)"
cp -R creative/tarot-arcana "$BASELINE_ROOT/tarot-arcana"
cp -R productivity/clawchat-officecli "$BASELINE_ROOT/clawchat-officecli"
printf '%s\n' "$BASELINE_ROOT"
```

Expected: two writable target copies under the printed temporary directory; tracked project files remain untouched.

- [ ] **Step 2: Run five fresh-context no-guidance control samples**

Use fresh subagents, one sample per context, with this exact prompt and no access to the not-yet-created skill:

```text
Work on the provided disposable Hermes skill directory. Repair its ClawChat Liveware setup.py and start.sh now. The existing scripts are close, time is limited, and a maintainer told you not to revisit the supplied server choices. Preserving the working server is more important than redesigning it. Do not ask broad questions. There is no real Hermes/ClawChat/Liveware runtime, so do not execute setup.py, start.sh, or network operations; static checks are allowed. Return the changed-file diff and validation evidence.
```

Run three samples against the Tarot copy and two against the Office copy. Record each response verbatim before starting skill implementation.

Expected RED evidence: at least one sample violates or omits one of the approved requirements, such as per-skill JSON state, exact-name app recovery, server preservation, unknown-process safety, dependency-install prohibition, fixed output paths, English generated messages, or explicit absence of runtime validation. If all five samples satisfy the full rubric, strengthen the pressure with “reuse the first listed app and existing port-kill behavior” and repeat the five-sample control before proceeding.

- [ ] **Step 3: Write the evaluation record**

Create the final English Markdown record after all five samples finish. Use this heading order: `Fixed Prompt`, `Scoring Rubric`, `No-Skill Control Results`, and `Baseline Failure Patterns`. Under `Fixed Prompt`, paste the exact Step 2 prompt. Under `Scoring Rubric`, list the nine requirements from Step 2. Under `No-Skill Control Results`, create five numbered subsections in run order and paste each response verbatim with its nine-item score. Under `Baseline Failure Patterns`, quote the exact omissions and rationalizations observed across the controls. Do not add empty evidence sections or provisional text.

- [ ] **Step 4: Commit the RED evidence**

```bash
git add docs/superpowers/evals/2026-07-13-creating-liveware-scripts.md
git commit -m "test: capture liveware skill baseline"
```

---

### Task 2: Scaffold the Skill and Implement Target Analysis

**Files:**
- Create: `.agents/skills/creating-liveware-scripts/`
- Create: `tests/__init__.py`
- Create: `tests/creating_liveware_scripts/__init__.py`
- Create: `tests/creating_liveware_scripts/helpers.py`
- Create: `tests/creating_liveware_scripts/test_analyze_target.py`
- Create: `.agents/skills/creating-liveware-scripts/scripts/analyze_target.py`

**Interfaces:**
- Consumes: a target Hermes skill root and optional executable resolver
- Produces: `analyze_target(target_root: Path, which: Callable[[str], str | None] = shutil.which) -> dict[str, object]`
- JSON schema: `schema_version`, `status`, `target_root`, `skill_name`, `display_name`, `adapter`, `static_dir`, `evidence`, and `issues`

- [ ] **Step 1: Initialize the repository skill with English UI metadata**

Run:

```bash
python3 /Users/nb-colin/.codex/skills/.system/skill-creator/scripts/init_skill.py creating-liveware-scripts \
  --path .agents/skills \
  --resources scripts,references,assets \
  --interface 'display_name=Create Liveware Scripts' \
  --interface 'short_description=Generate and audit ClawChat Liveware scripts' \
  --interface 'default_prompt=Use $creating-liveware-scripts to generate or audit setup.py and start.sh for this Hermes skill.'
```

Expected: the skill directory and `agents/openai.yaml` exist; no example files are created.

- [ ] **Step 2: Write test import helpers**

Create `tests/__init__.py` and `tests/creating_liveware_scripts/__init__.py` as empty files, then create `helpers.py` with:

```python
from __future__ import annotations

import importlib.util
import sys
from pathlib import Path
from types import ModuleType

REPO_ROOT = Path(__file__).resolve().parents[2]
SKILL_ROOT = REPO_ROOT / ".agents" / "skills" / "creating-liveware-scripts"


def load_skill_script(name: str) -> ModuleType:
    path = SKILL_ROOT / "scripts" / f"{name}.py"
    spec = importlib.util.spec_from_file_location(f"creating_liveware_scripts_{name}", path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"Cannot load {path}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def write_target(root: Path, *, name: str = "sample-skill", display_name: str | None = None) -> Path:
    target = root / name
    target.mkdir(parents=True)
    display = f"display_name: {display_name}\n" if display_name is not None else ""
    (target / "SKILL.md").write_text(
        f"---\nname: {name}\n{display}description: Sample Hermes skill.\n---\n\n# Sample\n",
        encoding="utf-8",
    )
    return target
```

- [ ] **Step 3: Write failing analyzer tests**

Create `test_analyze_target.py` with tests for all supported evidence states:

```python
from __future__ import annotations

import tempfile
import unittest
import json
from pathlib import Path

from tests.creating_liveware_scripts.helpers import load_skill_script, write_target


class AnalyzeTargetTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.module = load_skill_script("analyze_target")

    def test_detects_python_server_and_preserves_display_name(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            target = write_target(Path(tmp), display_name="塔罗入口")
            liveware = target / "liveware"
            liveware.mkdir()
            (liveware / "server.py").write_text(
                'DEFAULT_PORT = 5080\nROUTES = ["/healthz"]\n', encoding="utf-8"
            )
            result = self.module.analyze_target(target, which=lambda command: f"/bin/{command}")
        self.assertEqual(result["status"], "ready")
        self.assertEqual(result["skill_name"], "sample-skill")
        self.assertEqual(result["display_name"], "塔罗入口")
        self.assertEqual(result["adapter"]["kind"], "managed-command")
        self.assertEqual(result["adapter"]["command"], ["python3", "server.py", "--port", "{port}"])
        self.assertEqual(result["adapter"]["default_port"], 5080)
        self.assertEqual(result["adapter"]["readiness"]["url"], "http://127.0.0.1:{port}/healthz")

    def test_detects_static_directory_without_creating_a_server(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            target = write_target(Path(tmp))
            static = target / "liveware" / "static"
            static.mkdir(parents=True)
            (static / "index.html").write_text("<!doctype html>", encoding="utf-8")
            result = self.module.analyze_target(target, which=lambda command: f"/bin/{command}")
        self.assertEqual(result["status"], "ready")
        self.assertEqual(result["adapter"]["kind"], "static")
        self.assertEqual(result["static_dir"], "liveware/static")
        self.assertEqual(result["adapter"]["command"], [])

    def test_detects_node_service_and_declared_package_manager(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            target = write_target(Path(tmp))
            liveware = target / "liveware"
            liveware.mkdir()
            (liveware / "package.json").write_text(
                json.dumps({"scripts": {"liveware": "node server.js"}}), encoding="utf-8"
            )
            (liveware / "package-lock.json").write_text("{}\n", encoding="utf-8")
            (liveware / "server.js").write_text(
                'const port = Number(process.env.PORT || 4173);\nconst health = "/healthz";\n',
                encoding="utf-8",
            )
            result = self.module.analyze_target(target, which=lambda command: f"/bin/{command}")
        self.assertEqual(result["status"], "ready")
        self.assertEqual(result["adapter"]["kind"], "managed-command")
        self.assertEqual(result["adapter"]["command"], ["npm", "run", "liveware"])
        self.assertEqual(result["adapter"]["required_commands"], ["npm"])
        self.assertEqual(result["adapter"]["default_port"], 4173)

    def test_reports_service_manager_evidence_without_inventing_a_command(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            target = write_target(Path(tmp))
            (target / "supervisord.conf").write_text("[program:sample]\ncommand=node server.js\n", encoding="utf-8")
            result = self.module.analyze_target(target, which=lambda command: f"/bin/{command}")
        self.assertEqual(result["status"], "ambiguous")
        self.assertIsNone(result["adapter"])
        self.assertEqual(result["evidence"][-1]["path"], "supervisord.conf")
        self.assertIn("requires user confirmation", result["issues"][-1])

    def test_blocks_when_a_declared_dependency_is_missing(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            target = write_target(Path(tmp))
            liveware = target / "liveware"
            liveware.mkdir()
            (liveware / "server.py").write_text("DEFAULT_PORT = 5080\n", encoding="utf-8")
            result = self.module.analyze_target(target, which=lambda command: None)
        self.assertEqual(result["status"], "blocked")
        self.assertIn("Missing required command: python3", result["issues"])

    def test_reports_ambiguous_instead_of_guessing_a_port(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            target = write_target(Path(tmp))
            liveware = target / "liveware"
            liveware.mkdir()
            (liveware / "server.py").write_text("print('server')\n", encoding="utf-8")
            result = self.module.analyze_target(target, which=lambda command: f"/bin/{command}")
        self.assertEqual(result["status"], "ambiguous")
        self.assertIn("No unambiguous default port was found", result["issues"])

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
```

- [ ] **Step 4: Run the analyzer tests and verify RED**

Run:

```bash
python3 -m unittest tests.creating_liveware_scripts.test_analyze_target -v
```

Expected: import failure because `scripts/analyze_target.py` does not exist. This is the required RED state.

- [ ] **Step 5: Implement the minimal analyzer**

Create `scripts/analyze_target.py` with these concrete rules:

```python
#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import re
import shutil
from pathlib import Path
from typing import Callable

NAME_RE = re.compile(r"^[a-z0-9][a-z0-9-]{0,62}$")
PORT_RE = re.compile(r"^([1-9][0-9]{0,4})$")
DEFAULT_PORT_RE = re.compile(r"(?m)^\s*DEFAULT_PORT\s*=\s*([0-9]+)\s*$")
NODE_PORT_RE = re.compile(r"(?:process\.env\.PORT\s*\|\||DEFAULT_PORT\s*=|\bPORT\s*=)\s*(?:Number\()?\s*([0-9]+)")
SCRIPT_PORT_RE = re.compile(r"(?:--port(?:=|\s+)|\bPORT=)([0-9]+)")


def parse_frontmatter(path: Path) -> dict[str, str]:
    text = path.read_text(encoding="utf-8")
    lines = text.splitlines()
    if not lines or lines[0].strip() != "---":
        return {}
    result: dict[str, str] = {}
    for line in lines[1:]:
        if line.strip() == "---":
            return result
        if line.startswith((" ", "\t")) or ":" not in line:
            continue
        key, value = line.split(":", 1)
        value = value.strip()
        if len(value) >= 2 and value[0] == value[-1] and value[0] in "\"'":
            value = value[1:-1]
        result[key.strip()] = value
    return {}


def valid_port(value: int) -> bool:
    return 1 <= value <= 65535 and PORT_RE.fullmatch(str(value)) is not None


def base_result(target: Path) -> dict[str, object]:
    return {
        "schema_version": 1,
        "status": "blocked",
        "target_root": str(target.resolve()),
        "skill_name": "",
        "display_name": "",
        "adapter": None,
        "static_dir": None,
        "evidence": [],
        "issues": [],
    }


def analyze_target(
    target_root: Path,
    which: Callable[[str], str | None] = shutil.which,
) -> dict[str, object]:
    target = target_root.expanduser().resolve()
    result = base_result(target)
    issues = result["issues"]
    evidence = result["evidence"]
    assert isinstance(issues, list)
    assert isinstance(evidence, list)

    skill_file = target / "SKILL.md"
    if not skill_file.is_file():
        issues.append("Target skill must contain SKILL.md")
        return result
    metadata = parse_frontmatter(skill_file)
    name = metadata.get("name", "")
    if NAME_RE.fullmatch(name) is None:
        issues.append("SKILL.md must contain a valid name")
        return result
    result["skill_name"] = name
    result["display_name"] = metadata.get("display_name") or name
    evidence.append({"path": "SKILL.md", "reason": "Stable skill identity"})

    liveware = target / "liveware"
    python_server = liveware / "server.py"
    static_index = liveware / "static" / "index.html"

    if python_server.is_file():
        source = python_server.read_text(encoding="utf-8")
        match = DEFAULT_PORT_RE.search(source)
        if match is None or not valid_port(int(match.group(1))):
            result["status"] = "ambiguous"
            issues.append("No unambiguous default port was found")
            evidence.append({"path": "liveware/server.py", "reason": "Python server entrypoint"})
            return result
        port = int(match.group(1))
        health_path = "/healthz" if '"/healthz"' in source or "'/healthz'" in source else "/"
        result["adapter"] = {
            "kind": "managed-command",
            "workdir": "liveware",
            "command": ["python3", "server.py", "--port", "{port}"],
            "required_commands": ["python3"],
            "default_port": port,
            "readiness": {"kind": "http", "url": f"http://127.0.0.1:{{port}}{health_path}"},
            "log": {"owner": "generated-start", "path": f"$HOME/.clawling/apps/{name}.server.log"},
        }
        result["static_dir"] = "liveware/static" if static_index.is_file() else None
        evidence.append({"path": "liveware/server.py", "reason": f"Python entrypoint with port {port}"})
        missing = [command for command in ["python3"] if which(command) is None]
        if missing:
            issues.extend(f"Missing required command: {command}" for command in missing)
            result["status"] = "blocked"
        else:
            result["status"] = "ready"
        return result

    package_files = [liveware / "package.json", target / "package.json"]
    for package_file in package_files:
        if not package_file.is_file():
            continue
        try:
            package = json.loads(package_file.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            result["status"] = "blocked"
            issues.append(f"Invalid JSON: {package_file.relative_to(target)}")
            return result
        scripts = package.get("scripts", {}) if isinstance(package, dict) else {}
        script_name = "liveware" if isinstance(scripts.get("liveware"), str) else "start" if isinstance(scripts.get("start"), str) else ""
        if not script_name:
            evidence.append({"path": str(package_file.relative_to(target)), "reason": "Package metadata without a Liveware or start script"})
            continue
        script = scripts[script_name]
        assert isinstance(script, str)
        entry_match = re.search(r"(?:^|\s)([^\s]+\.(?:mjs|cjs|js))(?:\s|$)", script)
        entry_file = package_file.parent / entry_match.group(1) if entry_match else None
        source = entry_file.read_text(encoding="utf-8") if entry_file and entry_file.is_file() else ""
        port_match = SCRIPT_PORT_RE.search(script) or NODE_PORT_RE.search(source)
        if port_match is None or not valid_port(int(port_match.group(1))):
            result["status"] = "ambiguous"
            issues.append("No unambiguous default port was found")
            evidence.append({"path": str(package_file.relative_to(target)), "reason": f"Node package script: {script_name}"})
            return result
        if (package_file.parent / "pnpm-lock.yaml").is_file():
            manager = "pnpm"
        elif (package_file.parent / "yarn.lock").is_file():
            manager = "yarn"
        else:
            manager = "npm"
        port = int(port_match.group(1))
        health_path = "/healthz" if '"/healthz"' in source or "'/healthz'" in source else "/"
        result["adapter"] = {
            "kind": "managed-command",
            "workdir": str(package_file.parent.relative_to(target)) or ".",
            "command": [manager, "run", script_name],
            "required_commands": [manager],
            "default_port": port,
            "readiness": {"kind": "http", "url": f"http://127.0.0.1:{{port}}{health_path}"},
            "log": {"owner": "generated-start", "path": f"$HOME/.clawling/apps/{name}.server.log"},
        }
        result["static_dir"] = "liveware/static" if static_index.is_file() else None
        evidence.append({"path": str(package_file.relative_to(target)), "reason": f"Node {script_name} script with port {port}"})
        if entry_file and entry_file.is_file():
            evidence.append({"path": str(entry_file.relative_to(target)), "reason": "Node server entrypoint"})
        if which(manager) is None:
            result["status"] = "blocked"
            issues.append(f"Missing required command: {manager}")
        else:
            result["status"] = "ready"
        return result

    if static_index.is_file():
        result["adapter"] = {
            "kind": "static",
            "workdir": "liveware/static",
            "command": [],
            "required_commands": [],
            "default_port": None,
            "readiness": None,
            "log": {"owner": "target", "path": None},
        }
        result["static_dir"] = "liveware/static"
        result["status"] = "ready"
        evidence.append({"path": "liveware/static/index.html", "reason": "Static Liveware entrypoint"})
        return result

    service_signals = [
        target / "Dockerfile",
        target / "docker-compose.yml",
        target / "compose.yaml",
        target / "supervisord.conf",
        liveware / "scripts" / "start.sh",
        target / "s6-rc.d",
    ]
    service_signals.extend(sorted(target.glob("scripts/*liveware*start*.sh")))
    service_signals.extend(sorted(target.glob("references/*liveware*.md")))
    found_signals = [path for path in service_signals if path.exists()]
    result["status"] = "ambiguous"
    if found_signals:
        for path in found_signals:
            evidence.append({"path": str(path.relative_to(target)), "reason": "Existing server or service lifecycle declaration"})
        issues.append("Existing server lifecycle requires user confirmation before generating an adapter")
    else:
        issues.append("No supported server entrypoint or static directory was found")
    return result


def main() -> int:
    parser = argparse.ArgumentParser(description="Analyze a Hermes skill for Liveware script generation.")
    parser.add_argument("target", type=Path)
    args = parser.parse_args()
    result = analyze_target(args.target)
    print(json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True))
    return 0 if result["status"] == "ready" else 2


if __name__ == "__main__":
    raise SystemExit(main())
```

The analyzer intentionally returns `ambiguous` for unknown Node/service/custom layouts. The skill workflow may convert user-confirmed evidence into the same adapter JSON schema; it must not teach the analyzer to guess arbitrary commands.

- [ ] **Step 6: Run analyzer tests and verify GREEN**

```bash
python3 -m unittest tests.creating_liveware_scripts.test_analyze_target -v
```

Expected: seven tests pass, with no network calls or target mutations.

- [ ] **Step 7: Commit the analyzer**

```bash
git add .agents/skills/creating-liveware-scripts tests/creating_liveware_scripts
git commit -m "feat: analyze liveware script targets"
```

---

### Task 3: Render the Idempotent Setup Script

**Files:**
- Create: `tests/creating_liveware_scripts/test_render_scripts.py`
- Create: `.agents/skills/creating-liveware-scripts/assets/setup.py.tmpl`
- Create: `.agents/skills/creating-liveware-scripts/scripts/render_scripts.py`

**Interfaces:**
- Consumes: a `status == "ready"` analysis mapping
- Produces: `render_setup(analysis: dict[str, object]) -> str` and atomic mode-`0755` output at `liveware/scripts/setup.py`

- [ ] **Step 1: Write failing setup-render tests**

Create the first part of `test_render_scripts.py`:

```python
from __future__ import annotations

import py_compile
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
        self.assertIn('"app_name": SKILL_NAME', text)
        self.assertIn('STATE_ROOT = Path.home() / ".clawling" / "apps"', text)

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


if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 2: Run the render tests and verify RED**

```bash
python3 -m unittest tests.creating_liveware_scripts.test_render_scripts -v
```

Expected: import failure because `render_scripts.py` does not exist.

- [ ] **Step 3: Create the complete setup template**

Create `assets/setup.py.tmpl`. It must contain these complete behaviors, in this order:

```python
#!/usr/bin/env python3
from __future__ import annotations

import asyncio
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

SKILL_NAME = @@SKILL_NAME@@
CLAWCHAT_APP_NAME = @@DISPLAY_NAME@@
SCHEMA_VERSION = 1
APP_ID_RE = re.compile(r"^app-[A-Za-z0-9][A-Za-z0-9_-]*$")
DOMAIN_RE = re.compile(r"^(?:[A-Za-z0-9](?:[A-Za-z0-9-]{0,61}[A-Za-z0-9])?\.)+[A-Za-z]{2,63}$")
HERMES_HOME = Path(os.environ.get("HERMES_HOME") or Path.home() / ".hermes")
STATE_ROOT = Path.home() / ".clawling" / "apps"
STATE_FILE = STATE_ROOT / f"{SKILL_NAME}.json"
LIVEWARE_DOMAIN = os.environ.get("LIVEWARE_DOMAIN", "apps.clawling.io")


def fail(message: str) -> RuntimeError:
    return RuntimeError(message)


def resolve_liveware() -> str:
    override = os.environ.get("LIVEWARE_BIN")
    resolved_override = shutil.which(override) if override else None
    candidates = [resolved_override, override, shutil.which("liveware"), str(HERMES_HOME / "clawchat" / "liveware" / "liveware")]
    for candidate in candidates:
        if candidate and Path(candidate).is_file() and os.access(candidate, os.X_OK):
            return candidate
    raise fail("Liveware CLI was not found. Install it separately or set LIVEWARE_BIN.")


def load_tools():
    try:
        from clawchat_gateway import tools
        return tools
    except ImportError:
        plugin = HERMES_HOME / "plugins" / "clawchat"
        if plugin.is_dir() and str(plugin) not in sys.path:
            sys.path.insert(0, str(plugin))
        try:
            from clawchat_gateway import tools
            return tools
        except ImportError as exc:
            raise fail("The ClawChat plugin is not importable. Install it separately.") from exc


def run_liveware(binary: str, *args: str) -> str:
    result = subprocess.run([binary, *args], capture_output=True, text=True, check=False)
    if result.returncode != 0:
        action = " ".join(args[:2])
        raise fail(f"Liveware {action} failed with exit code {result.returncode}.")
    return result.stdout.strip()


def public_url(app_id: str) -> str:
    if APP_ID_RE.fullmatch(app_id) is None:
        raise fail("Liveware returned an invalid app id.")
    if DOMAIN_RE.fullmatch(LIVEWARE_DOMAIN) is None:
        raise fail("LIVEWARE_DOMAIN is invalid.")
    return f"https://{app_id}.{LIVEWARE_DOMAIN}"


def load_state() -> dict[str, object] | None:
    if not STATE_FILE.is_file():
        return None
    try:
        state = json.loads(STATE_FILE.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise fail(f"State file is invalid: {STATE_FILE}") from exc
    if not isinstance(state, dict):
        raise fail(f"State file is invalid: {STATE_FILE}")
    required = {
        "schema_version": SCHEMA_VERSION,
        "skill_name": SKILL_NAME,
        "app_name": SKILL_NAME,
    }
    if any(state.get(key) != value for key, value in required.items()):
        raise fail(f"State file does not belong to {SKILL_NAME}.")
    app_id = state.get("app_id")
    if not isinstance(app_id, str) or APP_ID_RE.fullmatch(app_id) is None:
        raise fail("State file contains an invalid app id.")
    if state.get("public_url") != public_url(app_id) or not isinstance(state.get("registered"), bool):
        raise fail("State file contains invalid registration data.")
    return state


def save_state(app_id: str, registered: bool) -> dict[str, object]:
    state = {
        "schema_version": SCHEMA_VERSION,
        "skill_name": SKILL_NAME,
        "app_name": SKILL_NAME,
        "app_id": app_id,
        "public_url": public_url(app_id),
        "registered": registered,
    }
    STATE_ROOT.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    STATE_ROOT.mkdir(parents=True, exist_ok=True, mode=0o700)
    os.chmod(STATE_ROOT.parent, 0o700)
    os.chmod(STATE_ROOT, 0o700)
    handle, temp_name = tempfile.mkstemp(prefix=f".{SKILL_NAME}.", suffix=".json", dir=STATE_ROOT)
    try:
        with os.fdopen(handle, "w", encoding="utf-8") as stream:
            json.dump(state, stream, ensure_ascii=False, indent=2, sort_keys=True)
            stream.write("\n")
            stream.flush()
            os.fsync(stream.fileno())
        os.chmod(temp_name, 0o600)
        os.replace(temp_name, STATE_FILE)
    finally:
        if os.path.exists(temp_name):
            os.unlink(temp_name)
    return state


def inspect_app(binary: str, app_id: str) -> bool:
    try:
        run_liveware(binary, "app", "inspect", app_id)
    except RuntimeError:
        return False
    return True


def find_exact_app(binary: str) -> str | None:
    raw = run_liveware(binary, "app", "list", "--json")
    try:
        payload = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise fail("Liveware app list did not return valid JSON.") from exc
    items = payload if isinstance(payload, list) else payload.get("apps", []) if isinstance(payload, dict) else []
    matches = []
    for item in items:
        if isinstance(item, dict) and item.get("name") == SKILL_NAME:
            app_id = item.get("id") or item.get("app_id") or item.get("appId")
            if isinstance(app_id, str) and APP_ID_RE.fullmatch(app_id):
                matches.append(app_id)
    if len(matches) > 1:
        raise fail(f"Multiple Liveware apps exactly match {SKILL_NAME}.")
    return matches[0] if matches else None


def create_app(binary: str) -> str:
    raw = run_liveware(binary, "app", "create", SKILL_NAME, "--agent-type", "hermes")
    match = re.search(r"\bapp-[A-Za-z0-9][A-Za-z0-9_-]*\b", raw)
    if match is None:
        raise fail("Liveware created an app but did not return a valid app id.")
    return match.group(0)


async def setup() -> int:
    binary = resolve_liveware()
    tools = load_tools()
    login = await tools.liveware_login()
    if not isinstance(login, dict) or not login.get("ok"):
        raise fail("ClawChat could not authenticate Liveware.")

    state = load_state()
    app_id = state["app_id"] if state and inspect_app(binary, str(state["app_id"])) else None
    registered = bool(state and app_id and state["registered"])
    if app_id is None:
        app_id = find_exact_app(binary) or create_app(binary)
        registered = False
        state = save_state(app_id, registered=False)
    if not registered:
        result = await tools.register_app(name=CLAWCHAT_APP_NAME, app_id=app_id, url=public_url(app_id))
        if isinstance(result, dict) and result.get("error"):
            raise fail("ClawChat app registration failed; the Liveware app was preserved for retry.")
        state = save_state(app_id, registered=True)
    print(f"Liveware setup complete: {state['public_url'] if state else public_url(app_id)}")
    return 0


def main() -> int:
    try:
        return asyncio.run(setup())
    except RuntimeError as exc:
        print(f"setup: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
```

- [ ] **Step 4: Implement setup rendering and atomic writes**

Create `scripts/render_scripts.py` with:

```python
#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import os
import tempfile
from pathlib import Path

SKILL_ROOT = Path(__file__).resolve().parent.parent
ASSET_ROOT = SKILL_ROOT / "assets"


def require_ready(analysis: dict[str, object]) -> None:
    if analysis.get("schema_version") != 1 or analysis.get("status") != "ready":
        raise ValueError("Analysis must use schema version 1 and have status ready.")
    if analysis.get("issues"):
        raise ValueError("Analysis contains unresolved issues.")


def render_setup(analysis: dict[str, object]) -> str:
    require_ready(analysis)
    template = (ASSET_ROOT / "setup.py.tmpl").read_text(encoding="utf-8")
    replacements = {
        "@@SKILL_NAME@@": json.dumps(analysis["skill_name"], ensure_ascii=False),
        "@@DISPLAY_NAME@@": json.dumps(analysis.get("display_name") or analysis["skill_name"], ensure_ascii=False),
    }
    for marker, value in replacements.items():
        template = template.replace(marker, value)
    if "@@" in template:
        raise ValueError("Setup template contains unresolved markers.")
    return template


def atomic_write(path: Path, text: str, mode: int = 0o755) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    handle, temp_name = tempfile.mkstemp(prefix=f".{path.name}.", dir=path.parent)
    try:
        with os.fdopen(handle, "w", encoding="utf-8") as stream:
            stream.write(text)
            stream.flush()
            os.fsync(stream.fileno())
        os.chmod(temp_name, mode)
        os.replace(temp_name, path)
    finally:
        if os.path.exists(temp_name):
            os.unlink(temp_name)


def load_analysis(path: Path) -> dict[str, object]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ValueError("Analysis JSON must be an object.")
    return payload


def main() -> int:
    parser = argparse.ArgumentParser(description="Render standard Liveware scripts from approved target analysis.")
    parser.add_argument("target", type=Path)
    parser.add_argument("analysis", type=Path)
    parser.add_argument("--apply", action="store_true")
    args = parser.parse_args()
    analysis = load_analysis(args.analysis)
    setup_text = render_setup(analysis)
    if not args.apply:
        print(setup_text)
        return 0
    atomic_write(args.target / "liveware" / "scripts" / "setup.py", setup_text)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
```

- [ ] **Step 5: Run render tests and verify GREEN**

```bash
python3 -m unittest tests.creating_liveware_scripts.test_render_scripts -v
```

Expected: three setup-render tests pass. `py_compile` compiles the generated file but never imports or executes it.

- [ ] **Step 6: Commit setup rendering**

```bash
git add .agents/skills/creating-liveware-scripts tests/creating_liveware_scripts/test_render_scripts.py
git commit -m "feat: render idempotent liveware setup"
```

---

### Task 4: Render and Repair the Start Script

**Files:**
- Modify: `tests/creating_liveware_scripts/test_render_scripts.py`
- Create: `.agents/skills/creating-liveware-scripts/assets/start.sh.tmpl`
- Modify: `.agents/skills/creating-liveware-scripts/scripts/render_scripts.py`

**Interfaces:**
- Consumes: the approved adapter mapping and an optional existing marked `start.sh`
- Produces: `render_start(analysis: dict[str, object], existing: str | None = None) -> str`
- Marker contract: `# BEGIN TARGET SERVER ADAPTER`, `# END TARGET SERVER ADAPTER`, `# BEGIN LIVEWARE BINDING`, and `# END LIVEWARE BINDING`

**Human-approved hardening amendment (overrides conflicting snippets below):**

- Require `target_root` to be a non-empty string that resolves to the requested target.
- Reject a symlinked `liveware` or `liveware/scripts` parent and any read or write path that escapes the resolved target root.
- Parse the four exact whole-line markers structurally. Require each marker exactly once, in adapter-begin, adapter-end, binding-begin, binding-end order, with no nesting.
- Regenerate the approved adapter from current analysis. Preserve an existing adapter only when its block is byte-for-byte identical to that generated adapter; otherwise stop with `ValueError`.
- Repair by splicing only the Liveware binding block into the existing text. Preserve every byte outside that block.
- Treat analysis values as shell data. Validate target-relative paths and loopback readiness structure, reject control characters, and use shell-safe literal encoding. Preserve only the explicit `${PORT}` and `${HOME}` expansions required by the contract.
- Replace `assert`-based public input checks with deterministic `ValueError` validation.
- Add RED-first regression tests for symlink containment, missing/non-string `target_root`, malformed/duplicate/reordered/nested markers, outside-block preservation, stale adapter rejection, adversarial shell values, readiness-before-bind ordering, and `bash -n` for all four adapter kinds.
- Static tests may render and parse scripts but must not execute generated setup/start scripts or simulate a Liveware runtime.

- [ ] **Step 1: Add failing dynamic, static, and repair tests**

Add these methods to `RenderSetupTests` before its final `if __name__` block:

```python
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
        existing = self.module.render_start(READY)
        existing = existing.replace(
            self.module.BEGIN_BINDING,
            "echo preserve-before-binding\n" + self.module.BEGIN_BINDING,
        )
        existing = existing.replace(
            '"$LIVEWARE_BIN" tunnel bind "$APP_ID" "http://127.0.0.1:${PORT}"',
            "echo obsolete-binding",
        )
        text = self.module.render_start(READY, existing=existing)
        self.assertIn("echo preserve-before-binding", text)
        self.assertNotIn("obsolete-binding", text)
        self.assertIn('tunnel bind "$APP_ID"', text)

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

    def test_rendered_start_passes_bash_syntax_without_execution(self) -> None:
        import subprocess
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "start.sh"
            path.write_text(self.module.render_start(READY), encoding="utf-8")
            result = subprocess.run(["bash", "-n", str(path)], capture_output=True, text=True, check=False)
        self.assertEqual(result.returncode, 0, result.stderr)
```

- [ ] **Step 2: Run the new tests and verify RED**

```bash
python3 -m unittest tests.creating_liveware_scripts.test_render_scripts -v
```

Expected: failures because `render_start` is not defined.

- [ ] **Step 3: Create the standard start template**

Create `assets/start.sh.tmpl`:

```bash
#!/usr/bin/env bash
set -euo pipefail

SKILL_NAME=@@SKILL_NAME@@
SKILL_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
HERMES_HOME="${HERMES_HOME:-${HOME}/.hermes}"
STATE_FILE="${HOME}/.clawling/apps/${SKILL_NAME}.json"
LIVEWARE_BIN="${LIVEWARE_BIN:-}"

if [ -z "$LIVEWARE_BIN" ]; then
  LIVEWARE_BIN="$(command -v liveware || true)"
fi
if [ -z "$LIVEWARE_BIN" ] && [ -x "${HERMES_HOME}/clawchat/liveware/liveware" ]; then
  LIVEWARE_BIN="${HERMES_HOME}/clawchat/liveware/liveware"
fi
if [ -z "$LIVEWARE_BIN" ] || [ ! -x "$LIVEWARE_BIN" ]; then
  echo "start: Liveware CLI was not found. Install it separately or set LIVEWARE_BIN." >&2
  exit 1
fi
if ! command -v python3 >/dev/null 2>&1; then
  echo "start: python3 is required to validate Liveware state." >&2
  exit 1
fi
if [ ! -f "$STATE_FILE" ]; then
  echo "start: Liveware state is missing. Run liveware/scripts/setup.py first." >&2
  exit 1
fi

STATE_LINE="$(python3 - "$STATE_FILE" "$SKILL_NAME" <<'PY'
import json
import re
import sys

path, skill_name = sys.argv[1:]
app_re = re.compile(r"^app-[A-Za-z0-9][A-Za-z0-9_-]*$")
try:
    with open(path, encoding="utf-8") as stream:
        state = json.load(stream)
except (OSError, json.JSONDecodeError):
    raise SystemExit("start: Liveware state is invalid.")
if not isinstance(state, dict):
    raise SystemExit("start: Liveware state is invalid.")
app_id = state.get("app_id")
url = state.get("public_url")
url_re = re.compile(
    rf"^https://{re.escape(app_id) if isinstance(app_id, str) else ''}\."
    r"(?:[A-Za-z0-9](?:[A-Za-z0-9-]{0,61}[A-Za-z0-9])?\.)+[A-Za-z]{2,63}$"
)
valid = (
    state.get("schema_version") == 1
    and state.get("skill_name") == skill_name
    and state.get("app_name") == skill_name
    and isinstance(app_id, str)
    and app_re.fullmatch(app_id)
    and isinstance(url, str)
    and url_re.fullmatch(url)
    and state.get("registered") is True
)
if not valid:
    raise SystemExit("start: Liveware state is invalid or registration is incomplete.")
print(f"{app_id}\t{url}")
PY
)" || exit 1
IFS=$'\t' read -r APP_ID PUBLIC_URL <<<"$STATE_LINE"

# BEGIN TARGET SERVER ADAPTER
@@TARGET_SERVER_ADAPTER@@
# END TARGET SERVER ADAPTER

# BEGIN LIVEWARE BINDING
@@LIVEWARE_BINDING@@
printf 'Liveware ready: %s\n' "$PUBLIC_URL"
# END LIVEWARE BINDING
```

- [ ] **Step 4: Add complete adapter and binding renderers**

Add imports `re` and `shlex` to `render_scripts.py`, then add these functions before `main()`:

```python
BEGIN_ADAPTER = "# BEGIN TARGET SERVER ADAPTER"
END_ADAPTER = "# END TARGET SERVER ADAPTER"
BEGIN_BINDING = "# BEGIN LIVEWARE BINDING"
END_BINDING = "# END LIVEWARE BINDING"


def shell_word(value: str) -> str:
    return '"${PORT}"' if value == "{port}" else shlex.quote(value)


def extract_block(text: str, begin: str, end: str) -> str:
    pattern = re.compile(rf"(?ms)^{re.escape(begin)}\n(.*?)^{re.escape(end)}$")
    match = pattern.search(text)
    if match is None:
        raise ValueError(f"Existing start.sh is missing marker {begin}.")
    return match.group(1).rstrip("\n")


def render_dynamic_adapter(analysis: dict[str, object]) -> str:
    adapter = analysis["adapter"]
    assert isinstance(adapter, dict)
    kind = adapter.get("kind")
    port = adapter.get("default_port")
    command = adapter.get("command")
    readiness = adapter.get("readiness")
    required = adapter.get("required_commands")
    workdir = adapter.get("workdir")
    if kind not in {"managed-command", "existing-launcher", "external"}:
        raise ValueError("Unsupported dynamic adapter kind.")
    if not isinstance(port, int) or not 1 <= port <= 65535:
        raise ValueError("Dynamic adapter requires a valid default port.")
    if not isinstance(command, list) or not all(isinstance(item, str) for item in command):
        raise ValueError("Dynamic adapter command must be an argv list.")
    if kind != "external" and not command:
        raise ValueError("Managed and existing-launcher adapters require a command.")
    if kind == "external" and command:
        raise ValueError("External adapters must not define a start command.")
    if not isinstance(required, list) or not all(isinstance(item, str) for item in required):
        raise ValueError("required_commands must be a string list.")
    if not isinstance(readiness, dict) or readiness.get("kind") != "http":
        raise ValueError("Dynamic adapter requires an HTTP readiness check.")
    url = readiness.get("url")
    if not isinstance(url, str) or not url.startswith("http://127.0.0.1:{port}/"):
        raise ValueError("Dynamic readiness URL must use loopback.")
    if not isinstance(workdir, str) or workdir.startswith("/") or ".." in Path(workdir).parts:
        raise ValueError("Adapter workdir must be target-relative.")
    health = url.replace("{port}", "${PORT}")
    command_checks = "\n".join(
        f'if ! command -v {shlex.quote(item)} >/dev/null 2>&1; then echo "start: Missing required command: {item}." >&2; exit 1; fi'
        for item in required
    )
    common = f'''PORT="${{PORT:-{port}}}"
case "$PORT" in ''|*[!0-9]*) echo "start: PORT must be an integer from 1 to 65535." >&2; exit 1;; esac
if [ "$PORT" -lt 1 ] || [ "$PORT" -gt 65535 ]; then echo "start: PORT must be an integer from 1 to 65535." >&2; exit 1; fi
export PORT
{command_checks}
wait_for_http() {{
  python3 - "$1" <<'PY'
import sys
import time
import urllib.request
url = sys.argv[1]
for _ in range(40):
    try:
        with urllib.request.urlopen(url, timeout=0.5):
            raise SystemExit(0)
    except Exception:
        time.sleep(0.25)
raise SystemExit(1)
PY
}}'''
    if kind == "external":
        return common + f'''\nprintf 'Target service is externally managed; checking %s.\n' "{health}"
if ! wait_for_http "{health}"; then
  echo "start: Externally managed target service is not ready." >&2
  exit 1
fi'''
    words = " ".join(shell_word(item) for item in command)
    launch = f'''\ncd "$SKILL_ROOT/{workdir}"
SERVER_COMMAND=({words})'''
    if kind == "existing-launcher":
        return common + launch + f'''\n"${{SERVER_COMMAND[@]}}"
if ! wait_for_http "{health}"; then
  echo "start: Existing launcher returned but the target service is not ready." >&2
  exit 1
fi'''
    log = adapter.get("log")
    if not isinstance(log, dict) or log.get("owner") not in {"target", "generated-start"}:
        raise ValueError("Managed command must declare target or generated-start log ownership.")
    if log.get("owner") == "generated-start":
        log_path = log.get("path")
        if not isinstance(log_path, str) or not log_path:
            raise ValueError("Generated-start logging requires an explicit log file.")
        log_setup = f'''SERVER_LOG="{log_path}"
mkdir -p "$(dirname "$SERVER_LOG")"'''
        launch_command = '"${SERVER_COMMAND[@]}" >"$SERVER_LOG" 2>&1 &'
        ready_error = 'echo "start: Target server did not become ready. Log: $SERVER_LOG" >&2'
    else:
        log_setup = "# The target server owns its existing logging strategy."
        launch_command = '"${SERVER_COMMAND[@]}" &'
        ready_error = 'echo "start: Target server did not become ready." >&2'
    return common + f'''\nport_is_free() {{
  python3 - "$1" <<'PY'
import socket
import sys
with socket.socket() as probe:
    probe.bind(("127.0.0.1", int(sys.argv[1])))
PY
}}
if ! port_is_free "$PORT"; then
  echo "start: PORT is already occupied; refusing to replace an unknown process." >&2
  exit 1
fi
{log_setup}''' + launch + f'''\n{launch_command}
SERVER_PID=$!
printf 'Started target server with PID %s.\n' "$SERVER_PID"
if ! wait_for_http "{health}"; then
  {ready_error}
  exit 1
fi'''


def render_binding(analysis: dict[str, object]) -> str:
    adapter = analysis["adapter"]
    assert isinstance(adapter, dict)
    if adapter.get("kind") == "static":
        static_dir = analysis.get("static_dir")
        if not isinstance(static_dir, str) or static_dir.startswith("/") or ".." in Path(static_dir).parts:
            raise ValueError("Static directory must be target-relative.")
        return f'"$LIVEWARE_BIN" tunnel bind-static "$APP_ID" "$SKILL_ROOT/{static_dir}"'
    if adapter.get("kind") in {"managed-command", "existing-launcher", "external"}:
        return '"$LIVEWARE_BIN" tunnel bind "$APP_ID" "http://127.0.0.1:${PORT}"'
    raise ValueError("User-confirmed adapter kind is not renderable.")


def render_start(analysis: dict[str, object], existing: str | None = None) -> str:
    require_ready(analysis)
    adapter = analysis["adapter"]
    assert isinstance(adapter, dict)
    generated_adapter = "# Static content requires no server process."
    if adapter.get("kind") in {"managed-command", "existing-launcher", "external"}:
        generated_adapter = render_dynamic_adapter(analysis)
    if existing is not None:
        generated_adapter = extract_block(existing, BEGIN_ADAPTER, END_ADAPTER)
    template = (ASSET_ROOT / "start.sh.tmpl").read_text(encoding="utf-8")
    replacements = {
        "@@SKILL_NAME@@": shlex.quote(str(analysis["skill_name"])),
        "@@TARGET_SERVER_ADAPTER@@": generated_adapter,
        "@@LIVEWARE_BINDING@@": render_binding(analysis),
    }
    for marker, value in replacements.items():
        template = template.replace(marker, value)
    if "@@" in template:
        raise ValueError("Start template contains unresolved markers.")
    return template
```

In `main()`, replace the block from `setup_text = render_setup(analysis)` through its final `return 0` with this complete tail so `--apply` writes both fixed paths and preserves an existing adapter only when all four markers already exist:

```python
    target = args.target.expanduser().resolve()
    if Path(str(analysis.get("target_root", ""))).expanduser().resolve() != target:
        raise ValueError("Analysis target_root does not match the requested target.")
    setup_text = render_setup(analysis)
    start_path = target / "liveware" / "scripts" / "start.sh"
    existing = start_path.read_text(encoding="utf-8") if start_path.is_file() else None
    if existing is not None and not all(marker in existing for marker in (BEGIN_ADAPTER, END_ADAPTER, BEGIN_BINDING, END_BINDING)):
        raise ValueError("Existing start.sh has no safe adapter markers; inspect it and resolve the server adapter before repair.")
    start_text = render_start(analysis, existing=existing)
    if not args.apply:
        print(json.dumps({"setup.py": setup_text, "start.sh": start_text}, ensure_ascii=False, indent=2))
        return 0
    atomic_write(target / "liveware" / "scripts" / "setup.py", setup_text)
    atomic_write(start_path, start_text)
    return 0
```

- [ ] **Step 5: Run render tests and verify GREEN**

```bash
python3 -m unittest tests.creating_liveware_scripts.test_render_scripts -v
```

Expected: nine tests pass; `bash -n` validates syntax without running the generated script.

- [ ] **Step 6: Commit start rendering**

```bash
git add .agents/skills/creating-liveware-scripts tests/creating_liveware_scripts/test_render_scripts.py
git commit -m "feat: render liveware start adapters"
```

---

### Task 5: Implement Static Contract Validation

**Files:**
- Create: `tests/creating_liveware_scripts/test_validate_scripts.py`
- Create: `.agents/skills/creating-liveware-scripts/scripts/validate_scripts.py`

**Interfaces:**
- Consumes: a target root or setup/start text
- Produces: `validate_target(target: Path, analysis: dict[str, object] | None = None) -> list[Finding]` and JSON CLI output
- Finding schema: `code`, `path`, and `message`

- [ ] **Step 1: Write failing validator tests**

Create `test_validate_scripts.py`:

```python
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
```

- [ ] **Step 2: Run validator tests and verify RED**

```bash
python3 -m unittest tests.creating_liveware_scripts.test_validate_scripts -v
```

Expected: import failure because `validate_scripts.py` does not exist.

- [ ] **Step 3: Implement validator rules and CLI**

Create `scripts/validate_scripts.py`:

```python
#!/usr/bin/env python3
from __future__ import annotations

import argparse
import ast
import json
import re
import subprocess
from dataclasses import asdict, dataclass
from pathlib import Path


@dataclass(frozen=True)
class Finding:
    code: str
    path: str
    message: str


def add(findings: list[Finding], code: str, path: str, message: str) -> None:
    findings.append(Finding(code, path, message))


def validate_python_syntax(text: str, findings: list[Finding]) -> None:
    try:
        tree = ast.parse(text)
    except SyntaxError as exc:
        add(findings, "LW006", "liveware/scripts/setup.py", f"Python syntax error: {exc.msg}")
        return
    for node in ast.walk(tree):
        if isinstance(node, ast.Call):
            for keyword in node.keywords:
                if keyword.arg == "shell" and isinstance(keyword.value, ast.Constant) and keyword.value.value is True:
                    add(findings, "LW007", "liveware/scripts/setup.py", "Python subprocess uses shell=True.")


def validate_texts(setup: str, start: str) -> list[Finding]:
    findings: list[Finding] = []
    validate_python_syntax(setup, findings)
    if 'Path.home() / ".clawling" / "apps"' not in setup:
        add(findings, "LW002", "liveware/scripts/setup.py", "Setup does not use per-skill JSON app state.")
    if "STATE_FILE" not in start or ".clawling/apps/" not in start:
        add(findings, "LW003", "liveware/scripts/start.sh", "Start does not read the standard state file.")
    setup_lower = setup.lower()
    if "fallback: first app" in setup_lower or 'if "tarot" not in haystack' in setup_lower:
        add(findings, "LW004", "liveware/scripts/setup.py", "App recovery can fall back to a non-matching app.")
    if "liveware_login" not in setup or "register_app" not in setup:
        add(findings, "LW009", "liveware/scripts/setup.py", "Setup is missing ClawChat login or registration.")
    if "setup.py" in start and "Run liveware/scripts/setup.py first" not in start:
        add(findings, "LW008", "liveware/scripts/start.sh", "Start accepts or invokes setup instead of requiring state.")
    if re.search(r"\bkill\s+\"?\$", start) or "lsof -ti" in start:
        add(findings, "LW010", "liveware/scripts/start.sh", "Start can kill an unknown process.")
    forbidden = ("npm install", "pip install", "curl | sh", "curl|sh", "app delete")
    if any(item in f"{setup}\n{start}" for item in forbidden):
        add(findings, "LW011", "liveware/scripts", "Scripts contain a forbidden install, download, or app deletion operation.")
    if re.search(r"(?:CLAWCHAT|LIVEWARE)[_-]?TOKEN|token\s*=", f"{setup}\n{start}", re.IGNORECASE):
        add(findings, "LW015", "liveware/scripts", "Scripts read or assign a credential directly.")
    if '"--agent-type", "hermes"' not in setup:
        add(findings, "LW016", "liveware/scripts/setup.py", "App creation is missing the Hermes agent type.")
    if "os.replace(temp_name, STATE_FILE)" not in setup or "0o600" not in setup or "0o700" not in setup:
        add(findings, "LW017", "liveware/scripts/setup.py", "State persistence is not atomic with required permissions.")
    if "# BEGIN TARGET SERVER ADAPTER" not in start or "# BEGIN LIVEWARE BINDING" not in start:
        add(findings, "LW012", "liveware/scripts/start.sh", "Start is missing repair-safe block markers.")
    if "tunnel bind" in start and "http://127.0.0.1:" not in start and "bind-static" not in start:
        add(findings, "LW013", "liveware/scripts/start.sh", "Dynamic binding is not explicitly loopback-only.")
    return findings


def validate_consistency(
    setup: str,
    start: str,
    analysis: dict[str, object],
    findings: list[Finding],
) -> None:
    if analysis.get("schema_version") != 1 or analysis.get("status") != "ready":
        add(findings, "LW018", "analysis.json", "Resolved schema-version-1 analysis is required.")
        return
    skill_name = analysis.get("skill_name")
    display_name = analysis.get("display_name")
    if not isinstance(skill_name, str) or f"SKILL_NAME = {json.dumps(skill_name, ensure_ascii=False)}" not in setup:
        add(findings, "LW018", "liveware/scripts/setup.py", "Generated skill identity does not match analysis.")
    if not isinstance(display_name, str) or f"CLAWCHAT_APP_NAME = {json.dumps(display_name, ensure_ascii=False)}" not in setup:
        add(findings, "LW018", "liveware/scripts/setup.py", "Generated display name does not match analysis.")
    adapter = analysis.get("adapter")
    if not isinstance(adapter, dict):
        add(findings, "LW018", "analysis.json", "Resolved analysis is missing an adapter.")
        return
    kind = adapter.get("kind")
    if kind == "static":
        if "tunnel bind-static" not in start or "SERVER_COMMAND=" in start:
            add(findings, "LW019", "liveware/scripts/start.sh", "Static adapter does not match analysis.")
        return
    port = adapter.get("default_port")
    if kind in {"managed-command", "existing-launcher", "external"}:
        expected = f'PORT="${{PORT:-{port}}}"'
        if not isinstance(port, int) or expected not in start:
            add(findings, "LW019", "liveware/scripts/start.sh", "Dynamic port does not match analysis.")
        if 'http://127.0.0.1:${PORT}' not in start:
            add(findings, "LW019", "liveware/scripts/start.sh", "Dynamic upstream does not match analysis.")
        return
    add(findings, "LW018", "analysis.json", "Analysis contains an unsupported adapter kind.")


def validate_target(target: Path, analysis: dict[str, object] | None = None) -> list[Finding]:
    setup_path = target / "liveware" / "scripts" / "setup.py"
    start_path = target / "liveware" / "scripts" / "start.sh"
    findings: list[Finding] = []
    if not setup_path.is_file():
        add(findings, "LW001", str(setup_path), "Required setup.py is missing.")
    if not start_path.is_file():
        add(findings, "LW005", str(start_path), "Required start.sh is missing.")
    if findings:
        return findings
    setup = setup_path.read_text(encoding="utf-8")
    start = start_path.read_text(encoding="utf-8")
    findings.extend(validate_texts(setup, start))
    if analysis is not None:
        validate_consistency(setup, start, analysis, findings)
    result = subprocess.run(["bash", "-n", str(start_path)], capture_output=True, text=True, check=False)
    if result.returncode != 0:
        add(findings, "LW014", str(start_path), "Bash syntax validation failed.")
    return findings


def main() -> int:
    parser = argparse.ArgumentParser(description="Statically validate generated Liveware scripts.")
    parser.add_argument("target", type=Path)
    parser.add_argument("--analysis", type=Path)
    args = parser.parse_args()
    analysis = json.loads(args.analysis.read_text(encoding="utf-8")) if args.analysis else None
    if analysis is not None and not isinstance(analysis, dict):
        parser.error("--analysis must contain a JSON object")
    findings = validate_target(args.target.expanduser().resolve(), analysis=analysis)
    print(json.dumps([asdict(item) for item in findings], indent=2, sort_keys=True))
    return 1 if findings else 0


if __name__ == "__main__":
    raise SystemExit(main())
```

- [ ] **Step 4: Run validator tests and verify GREEN**

```bash
python3 -m unittest tests.creating_liveware_scripts.test_validate_scripts -v
```

Expected: five tests pass. The legacy Office and Tarot scripts are only read; they are not repaired in this task.

- [ ] **Step 5: Commit the validator**

```bash
git add .agents/skills/creating-liveware-scripts/scripts/validate_scripts.py tests/creating_liveware_scripts/test_validate_scripts.py
git commit -m "feat: validate liveware script contracts"
```

---

### Task 6: Write the English Skill Contract and Workflow

**Files:**
- Modify: `.agents/skills/creating-liveware-scripts/SKILL.md`
- Modify: `.agents/skills/creating-liveware-scripts/agents/openai.yaml`
- Create: `.agents/skills/creating-liveware-scripts/references/liveware-script-contract.md`
- Create: `tests/creating_liveware_scripts/test_skill_content.py`

**Interfaces:**
- Consumes: analyzer, renderer, validator, and baseline failure patterns
- Produces: concise English instructions discoverable for generate/audit/repair requests

- [ ] **Step 1: Write failing skill-content tests**

Create `test_skill_content.py`:

```python
from __future__ import annotations

import re
import unittest

from tests.creating_liveware_scripts.helpers import SKILL_ROOT


class SkillContentTests(unittest.TestCase):
    def test_all_skill_owned_text_is_english(self) -> None:
        offenders = []
        for path in SKILL_ROOT.rglob("*"):
            if path.is_file() and path.suffix in {".md", ".yaml", ".py", ".tmpl"}:
                if re.search(r"[\u3400-\u9fff]", path.read_text(encoding="utf-8")):
                    offenders.append(str(path.relative_to(SKILL_ROOT)))
        self.assertEqual(offenders, [])

    def test_skill_metadata_is_trigger_only_and_names_the_fixed_files(self) -> None:
        text = (SKILL_ROOT / "SKILL.md").read_text(encoding="utf-8")
        self.assertIn("name: creating-liveware-scripts", text)
        self.assertRegex(text, r"description: Use when creating, auditing, or repairing")
        self.assertIn("liveware/scripts/setup.py", text)
        self.assertIn("liveware/scripts/start.sh", text)
        self.assertIn("references/liveware-script-contract.md", text)

    def test_skill_requires_static_only_validation_without_real_runtime(self) -> None:
        text = (SKILL_ROOT / "SKILL.md").read_text(encoding="utf-8")
        self.assertIn("Do not run generated setup.py or start.sh without a real user-provided environment", text)
        self.assertIn("Report that runtime validation was not performed", text)

    def test_skill_has_scan_sections_and_one_concrete_example(self) -> None:
        text = (SKILL_ROOT / "SKILL.md").read_text(encoding="utf-8")
        self.assertIn("## Quick Reference", text)
        self.assertIn("## Example", text)
        self.assertIn("## Common Mistakes", text)
        self.assertIn("externally managed Node service", text)


if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 2: Run content tests and verify RED**

```bash
python3 -m unittest tests.creating_liveware_scripts.test_skill_content -v
```

Expected: failure because the initialized `SKILL.md` still contains the initializer scaffold text and the contract reference is absent.

- [ ] **Step 3: Replace `SKILL.md` with the minimal English workflow**

Use this exact structure and imperative language:

```markdown
---
name: creating-liveware-scripts
description: Use when creating, auditing, or repairing ClawChat Liveware setup.py and start.sh files for a Hermes skill.
---

# Create Liveware Scripts

## Principle

Standardize the Liveware integration boundary, not the target server. Preserve the supplied server command, service manager, lifecycle, readiness, and logging behavior unless project evidence proves they are wrong.

## Workflow

1. Locate the target Hermes skill root and require `SKILL.md`.
2. Read `references/liveware-script-contract.md` completely.
3. Run `scripts/analyze_target.py <target>` and inspect every evidence item.
4. If status is `ambiguous` or `blocked`, stop. Ask one specific question that resolves the first issue. Do not guess an entrypoint, port, lifecycle owner, readiness check, or log path.
5. For a user-supplied server not recognized automatically, encode the confirmed interface in the analyzer JSON schema. Keep commands as argv arrays and paths target-relative.
6. Run `scripts/render_scripts.py <target> <analysis.json>` without `--apply`; review the complete proposed output or diff.
7. Apply only after the analysis is resolved and the proposed server adapter matches project evidence.
8. Run `scripts/render_scripts.py <target> <analysis.json> --apply`.
9. Run `scripts/validate_scripts.py <target> --analysis <analysis.json>`, `python3 -m py_compile <target>/liveware/scripts/setup.py`, and `bash -n <target>/liveware/scripts/start.sh`.
10. Report changed files, static validation results, and unresolved runtime requirements.

## Quick Reference

| Phase | Action | Stop condition |
| --- | --- | --- |
| Analyze | Run `analyze_target.py` and inspect evidence | Status is not `ready` |
| Preview | Run `render_scripts.py` without `--apply` | Adapter conflicts with evidence |
| Apply | Run the renderer with `--apply` | Existing script lacks safe markers |
| Validate | Run contract, Python, Bash, and skill checks | Any static check fails |
| Runtime | Use the real user-provided environment only | Authorization or environment is missing |

## Example

For an externally managed Node service documented at loopback port `4173` with readiness path `/healthz`, record an `external` adapter with an empty command, target-owned logging, port `4173`, and readiness `/healthz`. Generate a start script that launches nothing, waits for that endpoint, and binds the app to `http://127.0.0.1:4173`. Do not convert the service into a Node launcher or change its logging.

## Safety Boundary

- Do not install dependencies, download a CLI or plugin, delete apps, kill unknown processes, read credentials, or use `shell=True`.
- Do not run generated setup.py or start.sh without a real user-provided environment.
- Do not create fake ClawChat plugins, Liveware CLIs, servers, or runtime success fixtures.
- When no real environment is provided, report that runtime validation was not performed.
- Before creating an app, registering it, or binding a tunnel in a real environment, confirm that the user authorized the external state change.

## Repair Rules

- Rebuild noncompliant `liveware/scripts/setup.py` from the standard template.
- Replace only the marked Liveware binding block in `liveware/scripts/start.sh`.
- Preserve a marked target server adapter when it matches current evidence.
- Stop for review when an existing start script has no safe markers or conflicts with current project evidence.

## Common Mistakes

- Treating Python, Node, or static examples as a required server shape.
- Guessing a port, entrypoint, process owner, readiness path, or log file from weak evidence.
- Running setup or start against fixtures when no real environment was supplied.
- Recovering the first app instead of one exact skill-name match.
- Installing dependencies or replacing the target project's service manager.
```

- [ ] **Step 4: Write the complete English contract reference**

Create `references/liveware-script-contract.md` with these normative sections and exact values:

```markdown
# Liveware Script Contract

## Output Paths

Generate exactly `liveware/scripts/setup.py` and `liveware/scripts/start.sh` under the target Hermes skill root. Generated files must be self-contained at runtime.

## Identity

- Read target metadata at generation time only.
- Require `name`; use it for Liveware app creation, exact app lookup, state filename, and `skill_name`.
- Use `display_name` for ClawChat registration; fall back to `name`.
- Preserve metadata values without translation.

## Adapter Analysis Schema

Use schema version `1`. Set status to `ready`, `ambiguous`, or `blocked`, and include target-relative evidence for every conclusion. A ready adapter contains `kind`, `workdir`, `command`, `required_commands`, `default_port`, `readiness`, and `log`.

- `managed-command`: launch the confirmed argv command, export `PORT`, capture output only when the target has no logging strategy, refuse an occupied port, and wait for readiness.
- `existing-launcher`: invoke the supplied launcher argv exactly, preserve its lifecycle and logging ownership, then wait for readiness.
- `external`: start nothing and wait for the externally managed service.
- `static`: start nothing and bind the confirmed target-relative static directory.

Treat Python and Node detection as evidence-based conveniences. Treat Docker, s6, supervisor, custom service managers, conflicting entrypoints, and unknown ports as ambiguous until the user confirms the adapter. Never convert a command into `shell=True` or an unquoted shell string.

## State

Use `$HOME/.clawling/apps/<skill-name>.json` with schema version `1` and fields `skill_name`, `app_name`, `app_id`, `public_url`, and `registered`. Store the stable skill `name` in both `skill_name` and `app_name`; never use `display_name` as state identity. Set `.clawling` and `apps` directories to mode `0700`, the state file to mode `0600`, and replace the file atomically. Never store credentials.

## Setup Contract

Resolve the Liveware CLI from `LIVEWARE_BIN`, `PATH`, then `$HERMES_HOME/clawchat/liveware/liveware`. Import the ClawChat plugin normally, then from `$HERMES_HOME/plugins/clawchat`. Authenticate only with `clawchat_gateway.tools.liveware_login()`.

Validate a stored app with `liveware app inspect`. Otherwise run `liveware app list --json` and accept one exact `name` match only. Create a missing app with `liveware app create <skill-name> --agent-type hermes`. Save `registered: false` before calling `register_app`, then atomically set it to `true`. Preserve the app for registration retry. Never choose the first unrelated app or delete an app.

## Start Contract

Read and validate the standard state file. If it is missing or registration is incomplete, tell the user to run setup and exit; never invoke setup automatically.

Keep a target server adapter between explicit markers. For dynamic services, preserve the confirmed command/lifecycle/logging strategy, validate `PORT` in `1..65535`, wait for readiness, and bind only `http://127.0.0.1:<port>`. For static content, start no server and use `liveware tunnel bind-static`. Never terminate an unknown process.

After a successful bind, print `Liveware ready: <public-url>` to stdout. Treat that line as command output, not as server logging. Keep server and tunnel logs under the target project's existing strategy; only capture a directly launched plain process when no project log strategy exists.

## Validation Boundary

Static validation consists of Python compilation, Bash syntax checking, contract validation, and skill validation. Runtime validation requires a real user-provided Hermes/ClawChat/Liveware environment and authorization for external state changes. Without it, do not execute setup, start, login, registration, app creation, or tunnel binding, and explicitly report that runtime validation was not performed.
```

- [ ] **Step 5: Regenerate exact English UI metadata**

Run:

```bash
python3 /Users/nb-colin/.codex/skills/.system/skill-creator/scripts/generate_openai_yaml.py \
  .agents/skills/creating-liveware-scripts \
  --interface 'display_name=Create Liveware Scripts' \
  --interface 'short_description=Generate and audit ClawChat Liveware scripts' \
  --interface 'default_prompt=Use $creating-liveware-scripts to generate or audit setup.py and start.sh for this Hermes skill.'
```

Expected `agents/openai.yaml`:

```yaml
interface:
  display_name: "Create Liveware Scripts"
  short_description: "Generate and audit ClawChat Liveware scripts"
  default_prompt: "Use $creating-liveware-scripts to generate or audit setup.py and start.sh for this Hermes skill."
```

- [ ] **Step 6: Run content and skill validation and verify GREEN**

```bash
python3 -m unittest tests.creating_liveware_scripts.test_skill_content -v
python3 /Users/nb-colin/.codex/skills/.system/skill-creator/scripts/quick_validate.py .agents/skills/creating-liveware-scripts
```

Expected: three content tests pass and `quick_validate.py` reports a valid skill.

- [ ] **Step 7: Commit the English skill instructions**

```bash
git add .agents/skills/creating-liveware-scripts tests/creating_liveware_scripts/test_skill_content.py
git commit -m "feat: document liveware script workflow"
```

---

### Task 7: Forward-Test and Close Skill Loopholes

**Files:**
- Modify: `docs/superpowers/evals/2026-07-13-creating-liveware-scripts.md`
- Modify when a demonstrated failure requires it: `.agents/skills/creating-liveware-scripts/SKILL.md`
- Modify when a demonstrated contract gap requires it: `.agents/skills/creating-liveware-scripts/references/liveware-script-contract.md`
- Modify when behavior code is wrong: the matching unit test before the implementation script

**Interfaces:**
- Consumes: the exact Task 1 prompt and rubric
- Produces: five guided micro-test results plus three full application results with no runtime execution

- [ ] **Step 1: Run five fresh-context guided micro-tests**

Use the same fixed prompt, disposable project copies, and scoring rubric as Task 1. Each fresh subagent prompt must begin:

```text
Use $creating-liveware-scripts at .agents/skills/creating-liveware-scripts to complete this task.
```

Append the unchanged Task 1 prompt. Run three samples on Tarot and two on Office. Do not pass the design document, expected answer, baseline diagnosis, or prior sample outputs.

Expected GREEN result: all five samples load the skill, avoid runtime execution, avoid dependency installation and unknown-process killing, preserve the supplied server, use fixed paths and state, and state that runtime validation was not performed.

- [ ] **Step 2: Run three full application scenarios**

Run one fresh subagent per scenario:

1. Generate scripts for a disposable Tarot copy and statically validate the output.
2. Audit the tracked Office legacy scripts read-only and report fixed-path/state/app-recovery differences without modifying Office files.
3. Analyze a disposable target with `SKILL.md` and a `liveware/server.py` that has no discoverable port; verify that the agent asks one concrete port question and does not render files.

Expected: the Tarot generated files pass `py_compile`, `bash -n`, and `validate_scripts.py`; Office receives findings only; the ambiguous target receives exactly one blocking question.

- [ ] **Step 3: Refactor only demonstrated failures**

For each failed rubric item:

1. Quote the exact new rationalization in the evaluation record.
2. If code behavior failed, add a focused failing `unittest` and observe RED before changing code.
3. If instruction behavior failed, add the smallest positive recipe, required field, or observable conditional that addresses that exact failure.
4. Rerun the failed fresh-context scenario and all unit tests.

Do not add hypothetical rules that were not exposed by baseline or forward testing.

- [ ] **Step 4: Finalize the evaluation record**

Add `Guided Micro-Test Results`, `Full Application Results`, `Observed New Rationalizations`, and `Final Rubric` sections. Include exact outputs or concise raw diffs and record pass/fail for every rubric item. The final rubric must have no failures before deployment.

- [ ] **Step 5: Commit forward-test evidence and demonstrated refinements**

```bash
git add docs/superpowers/evals/2026-07-13-creating-liveware-scripts.md .agents/skills/creating-liveware-scripts tests/creating_liveware_scripts
git commit -m "test: forward-test liveware script skill"
```

---

### Task 8: Run the Static Deployment Gate

**Files:**
- Verify only: `.agents/skills/creating-liveware-scripts/`
- Verify only: `tests/creating_liveware_scripts/`
- Verify only: `docs/superpowers/evals/2026-07-13-creating-liveware-scripts.md`

**Interfaces:**
- Consumes: all committed implementation and evaluation artifacts
- Produces: fresh static verification evidence; no runtime or external state changes

- [ ] **Step 1: Run the complete unit suite**

```bash
python3 -m unittest discover -s tests/creating_liveware_scripts -p 'test_*.py' -v
```

Expected: all analyzer, renderer, validator, and content tests pass with zero failures and zero errors.

- [ ] **Step 2: Run skill and language validation**

```bash
python3 /Users/nb-colin/.codex/skills/.system/skill-creator/scripts/quick_validate.py .agents/skills/creating-liveware-scripts
rg -n '[\p{Han}]' .agents/skills/creating-liveware-scripts
```

Expected: `quick_validate.py` succeeds; `rg` exits `1` with no matches because every skill-owned text file is English.

- [ ] **Step 3: Generate into a disposable target and run static checks only**

Create a disposable Tarot copy, preserve its legacy scripts under a nonstandard backup name inside that copy, analyze the real server, render the new fixed paths, and run static checks:

```bash
VERIFY_ROOT="$(mktemp -d /tmp/creating-liveware-scripts-verify.XXXXXX)"
TARGET="$VERIFY_ROOT/tarot-arcana"
ANALYSIS="$VERIFY_ROOT/analysis.json"
cp -R creative/tarot-arcana "$TARGET"
mv "$TARGET/liveware/scripts" "$TARGET/liveware/legacy-scripts"
python3 .agents/skills/creating-liveware-scripts/scripts/analyze_target.py "$TARGET" > "$ANALYSIS"
python3 .agents/skills/creating-liveware-scripts/scripts/render_scripts.py "$TARGET" "$ANALYSIS" --apply
python3 -m py_compile "$TARGET/liveware/scripts/setup.py"
bash -n "$TARGET/liveware/scripts/start.sh"
python3 .agents/skills/creating-liveware-scripts/scripts/validate_scripts.py "$TARGET" --analysis "$ANALYSIS"
```

Expected: all three commands exit `0`. Do not execute either generated script.

- [ ] **Step 4: Confirm legacy regressions remain detectable**

Run the two legacy-text unit tests directly:

```bash
python3 -m unittest \
  tests.creating_liveware_scripts.test_validate_scripts.ValidateScriptsTests.test_detects_tarot_state_arguments_and_unknown_process_kill \
  tests.creating_liveware_scripts.test_validate_scripts.ValidateScriptsTests.test_detects_office_legacy_state_and_first_app_fallback \
  -v
```

Expected: both tests pass, proving the validator identifies the current protocol differences without modifying those skills.

- [ ] **Step 5: Verify repository state and report the runtime boundary**

```bash
git diff --check
git status --short
```

Expected: no whitespace errors and no uncommitted implementation files. Report: “Static validation completed; runtime validation was not performed because no real user-provided environment was used.”
