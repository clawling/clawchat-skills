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
