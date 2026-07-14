#!/usr/bin/env python3
from __future__ import annotations

import argparse
import importlib.util
import json
import os
import re
import shutil
from functools import lru_cache
from pathlib import Path
from types import ModuleType
from typing import Callable

NAME_RE = re.compile(r"^[a-z0-9][a-z0-9-]{0,62}$")
PORT_RE = re.compile(r"^([1-9][0-9]{0,4})$")
DEFAULT_PORT_RE = re.compile(r"(?m)^\s*DEFAULT_PORT\s*=\s*([0-9]+)\s*$")
MANAGER_RE = (
    r"(?:(?:a|the)[ \t]+)?(?:docker[ \t]+compose|supervisord?|"
    r"(?:deployment[ \t]+)?supervisor|systemd(?:[ \t]+service[ \t]+unit)?|"
    r"systemctl|s6|service[ \t]+manager|launcher|pm2)"
)
ENTITY_RE = r"(?:service(?:[ \t]+lifecycle)?|server(?:[ \t]+lifecycle)?|process|lifecycle)"
REFERENCE_LIFECYCLE_PATTERNS = (
    re.compile(
        rf"(?:the[ \t]+)?{ENTITY_RE}[ \t]+(?:is[ \t]+)?"
        rf"(?:owned|managed|controlled|started|launched|run|runs)[ \t]+"
        rf"(?:by|with|under|through|via)[ \t]+{MANAGER_RE}"
        rf"(?:[ \t]+(?:in[ \t]+production|at[ \t]+runtime))?",
        re.IGNORECASE,
    ),
    re.compile(
        rf"{MANAGER_RE}[ \t]+(?:owns?|manages?|controls?|starts?|launches?|runs?)[ \t]+"
        rf"(?:the[ \t]+)?{ENTITY_RE}(?:[ \t]+(?:in[ \t]+production|at[ \t]+runtime))?",
        re.IGNORECASE,
    ),
    re.compile(
        rf"(?:use|run|start|launch|invoke)[ \t]+{MANAGER_RE}[ \t]+(?:to[ \t]+)?"
        rf"(?:run|start|launch|manage)[ \t]+(?:the[ \t]+)?{ENTITY_RE}",
        re.IGNORECASE,
    ),
    re.compile(
        r"(?:use[ \t]+)?systemctl[ \t]+(?:start|enable|restart)[ \t]+[A-Za-z0-9_.@-]+\.service",
        re.IGNORECASE,
    ),
)
REFERENCE_SCRIPT_ACTION_RE = re.compile(
    r"\b(?:use|run|start|launch|invoke)\b[ \t]+(scripts?/[A-Za-z0-9_./-]+)",
    re.IGNORECASE,
)
LIFECYCLE_SCRIPT_SUFFIXES = frozenset({".sh", ".py", ".js", ".mjs", ".cjs"})
LIFECYCLE_ACTIONS = frozenset({"start", "run", "launch", "launcher", "serve", "server"})
LIFECYCLE_OBJECTS = frozenset({"liveware", "server", "service", "app"})
PM2_CONFIG_NAMES = frozenset(
    {
        "ecosystem.config.js",
        "ecosystem.config.cjs",
        "ecosystem.config.mjs",
        "pm2.config.js",
        "pm2.config.cjs",
        "pm2.config.mjs",
    }
)
REFERENCE_EXAMPLE_RE = re.compile(
    r"\b(?:badge|badges|color[ \t]+labels?|docs?|documentation|examples?|lint|linting|tests?|testing)\b",
    re.IGNORECASE,
)


def reference_declares_lifecycle(text: str) -> bool:
    for statement in re.split(r"[!?;\n]+|\.(?=\s|$)", text):
        statement = statement.strip()
        if not statement:
            continue
        if any(pattern.fullmatch(statement) is not None for pattern in REFERENCE_LIFECYCLE_PATTERNS):
            return True
        for match in REFERENCE_SCRIPT_ACTION_RE.finditer(statement):
            if (
                lifecycle_script_name(Path(match.group(1)))
                and REFERENCE_EXAMPLE_RE.search(statement[match.end():]) is None
            ):
                return True
    return False


def lifecycle_script_name(path: Path) -> bool:
    if path.suffix.lower() not in LIFECYCLE_SCRIPT_SUFFIXES:
        return False
    if path.stem.lower() == "start":
        return True
    tokens = set(re.findall(r"[a-z0-9]+", path.stem.lower()))
    return bool(tokens & LIFECYCLE_ACTIONS) and bool(tokens & LIFECYCLE_OBJECTS)


def path_is_within(path: Path, root: Path) -> bool:
    try:
        path.relative_to(root)
    except ValueError:
        return False
    return True


def path_present(path: Path) -> bool:
    try:
        return path.exists() or path.is_symlink()
    except OSError:
        return True


def path_resolves_inside(path: Path, target: Path) -> bool:
    try:
        return path_is_within(path.resolve(strict=False), target)
    except (OSError, RuntimeError):
        return False


def target_relative(path: Path, target: Path) -> str:
    try:
        relative = path.relative_to(target)
    except ValueError:
        return "."
    if relative.is_absolute() or ".." in relative.parts:
        return "."
    return str(relative)


@lru_cache(maxsize=1)
def load_renderer() -> ModuleType:
    path = Path(__file__).resolve().with_name("render_scripts.py")
    spec = importlib.util.spec_from_file_location(
        "creating_liveware_scripts_analyzer_renderer",
        path,
    )
    if spec is None or spec.loader is None:
        raise RuntimeError(f"Cannot load renderer: {path}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def is_exact_canonical_generated_start(path: Path, target: Path, skill_name: str) -> bool:
    if not path.is_file() or path.is_symlink():
        return False
    try:
        text = path.read_text(encoding="utf-8")
        renderer = load_renderer()
        analysis = renderer.extract_analysis_manifest(text)
        if analysis.get("target_root") != str(target) or analysis.get("skill_name") != skill_name:
            return False
        return renderer.render_start(analysis) == text
    except (OSError, UnicodeError, RuntimeError, ValueError):
        return False


def lifecycle_signals(
    target: Path,
    liveware: Path,
    skill_name: str,
) -> tuple[list[Path], list[Path]]:
    unreadable: list[Path] = []
    start = liveware / "scripts" / "start.sh"
    paths = [
        target / "Dockerfile",
        target / "docker-compose.yml",
        target / "docker-compose.yaml",
        target / "compose.yml",
        target / "compose.yaml",
        target / "supervisord.conf",
        target / "supervisor.conf",
        target / "s6",
        target / "s6-rc.d",
    ]
    try:
        paths.extend(sorted(target.glob("*.service")))
    except (OSError, RuntimeError):
        unreadable.append(target)
    try:
        if liveware.is_dir() and not liveware.is_symlink():
            paths.extend(sorted(liveware.glob("*.service")))
    except (OSError, RuntimeError):
        unreadable.append(liveware)
    for parent in (target, liveware):
        paths.extend(parent / name for name in sorted(PM2_CONFIG_NAMES))
    if not is_exact_canonical_generated_start(start, target, skill_name):
        paths.append(start)
    scripts = target / "scripts"
    try:
        if scripts.is_dir() and not scripts.is_symlink():
            if not os.access(scripts, os.R_OK | os.X_OK):
                raise PermissionError(scripts)
            for path in sorted(scripts.iterdir()):
                if (
                    path.is_file()
                    and not path.is_symlink()
                    and lifecycle_script_name(path)
                ):
                    paths.append(path)
    except (OSError, RuntimeError):
        unreadable.append(scripts)

    references = target / "references"
    try:
        if references.is_dir() and not references.is_symlink():
            if not os.access(references, os.R_OK | os.X_OK):
                raise PermissionError(references)
            for path in sorted(references.rglob("*")):
                if not path.is_file() or path.is_symlink():
                    continue
                try:
                    declared_signal = reference_declares_lifecycle(
                        path.read_text(encoding="utf-8")
                    )
                except (OSError, UnicodeError):
                    unreadable.append(path)
                    continue
                if declared_signal:
                    paths.append(path)
    except (OSError, RuntimeError):
        unreadable.append(references)

    unique: list[Path] = []
    seen: set[Path] = set()
    for path in paths:
        if path_present(path) and path not in seen:
            seen.add(path)
            unique.append(path)
    return unique, unreadable


def automatic_candidate_evidence(
    target: Path,
    python_server: Path,
    package_files: list[Path],
    static_index: Path,
) -> list[dict[str, str]]:
    candidates: list[dict[str, str]] = []
    if python_server.is_file():
        candidates.append(
            {"path": str(python_server.relative_to(target)), "reason": "Automatic Python server candidate"}
        )
    for package_file in package_files:
        if package_file.is_file():
            candidates.append(
                {"path": str(package_file.relative_to(target)), "reason": "Automatic Node package candidate"}
            )
    if static_index.is_file():
        candidates.append(
            {"path": str(static_index.relative_to(target)), "reason": "Automatic static content candidate"}
        )
    return candidates


def parse_frontmatter_text(text: str) -> dict[str, str]:
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


def parse_frontmatter(path: Path) -> dict[str, str]:
    return parse_frontmatter_text(path.read_text(encoding="utf-8"))


def valid_port(value: int) -> bool:
    return 1 <= value <= 65535 and PORT_RE.fullmatch(str(value)) is not None


def base_result(target: Path) -> dict[str, object]:
    return {
        "schema_version": 1,
        "status": "blocked",
        "target_root": str(target),
        "skill_name": "",
        "display_name": "",
        "adapter": None,
        "static_dir": None,
        "evidence": [],
        "issues": [],
    }


def record_path_issue(
    result: dict[str, object],
    target: Path,
    path: Path,
    issue: str,
    reason: str,
) -> None:
    issues = result["issues"]
    evidence = result["evidence"]
    assert isinstance(issues, list)
    assert isinstance(evidence, list)
    result["status"] = "blocked"
    relative = target_relative(path, target)
    item = {"path": relative, "reason": reason}
    if item not in evidence:
        evidence.append(item)
    if issue not in issues:
        issues.append(issue)


def read_analysis_text(
    result: dict[str, object],
    target: Path,
    path: Path,
    label: str,
) -> str | None:
    try:
        return path.read_text(encoding="utf-8")
    except (OSError, UnicodeError) as exc:
        record_path_issue(
            result,
            target,
            path,
            f"Could not read {target_relative(path, target)} as UTF-8: {exc.__class__.__name__}",
            f"Unreadable {label}",
        )
        return None


def reject_escaping_candidate(
    result: dict[str, object],
    target: Path,
    path: Path,
    label: str,
) -> bool:
    if not path_present(path) or path_resolves_inside(path, target):
        return False
    record_path_issue(
        result,
        target,
        path,
        f"{label} resolves outside the target root",
        f"Unsafe {label}",
    )
    return True


def analyze_target(
    target_root: Path,
    which: Callable[[str], str | None] = shutil.which,
) -> dict[str, object]:
    try:
        target = target_root.expanduser().resolve()
    except (OSError, RuntimeError) as exc:
        target = target_root.expanduser().absolute()
        result = base_result(target)
        result["issues"] = [f"Target root could not be resolved: {exc.__class__.__name__}"]
        result["evidence"] = [{"path": ".", "reason": "Unresolvable target root"}]
        return result
    result = base_result(target)
    issues = result["issues"]
    evidence = result["evidence"]
    assert isinstance(issues, list)
    assert isinstance(evidence, list)

    skill_file = target / "SKILL.md"
    if reject_escaping_candidate(result, target, skill_file, "SKILL.md"):
        return result
    if not skill_file.is_file():
        issues.append("Target skill must contain SKILL.md")
        return result
    skill_text = read_analysis_text(result, target, skill_file, "skill metadata")
    if skill_text is None:
        return result
    metadata = parse_frontmatter_text(skill_text)
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
    package_files = [liveware / "package.json", target / "package.json"]

    for candidate, label in (
        (python_server, "Python server candidate"),
        (static_index, "static content candidate"),
        *[(path, "Node package candidate") for path in package_files],
    ):
        if reject_escaping_candidate(result, target, candidate, label):
            return result

    found_signals, unreadable_lifecycle = lifecycle_signals(target, liveware, name)
    if unreadable_lifecycle:
        result["status"] = "blocked"
        for path in unreadable_lifecycle:
            evidence.append(
                {
                    "path": target_relative(path, target),
                    "reason": "Unreadable lifecycle evidence",
                }
            )
        evidence.extend(
            automatic_candidate_evidence(
                target,
                python_server,
                package_files,
                static_index,
            )
        )
        issues.append("Lifecycle evidence could not be read or enumerated safely")
        return result
    if found_signals:
        result["status"] = "ambiguous"
        for path in found_signals:
            evidence.append(
                {
                    "path": str(path.relative_to(target)),
                    "reason": "Existing server or service lifecycle declaration",
                }
            )
        evidence.extend(
            automatic_candidate_evidence(
                target,
                python_server,
                package_files,
                static_index,
            )
        )
        issues.append("Existing server lifecycle requires user confirmation before generating an adapter")
        return result

    if python_server.is_file():
        source = read_analysis_text(result, target, python_server, "Python server entrypoint")
        if source is None:
            return result
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

    for package_file in package_files:
        if not package_file.is_file():
            continue
        package_source = read_analysis_text(result, target, package_file, "Node package metadata")
        if package_source is None:
            return result
        try:
            package = json.loads(package_source)
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
        if entry_file is not None and reject_escaping_candidate(
            result,
            target,
            entry_file,
            "Node server entrypoint",
        ):
            return result
        if entry_file and entry_file.is_file():
            entry_source = read_analysis_text(result, target, entry_file, "Node server entrypoint")
            if entry_source is None:
                return result
        result["status"] = "ambiguous"
        evidence.append(
            {
                "path": str(package_file.relative_to(target)),
                "reason": f"Node package script requires a confirmed interface: {script_name}",
            }
        )
        if entry_file and entry_file.is_file():
            evidence.append(
                {
                    "path": str(entry_file.relative_to(target)),
                    "reason": "Node server entrypoint requiring interface confirmation",
                }
            )
        issues.append(
            "Confirm the Node command's exact argv and default port, and whether it consumes exported PORT or uses a standalone {port} argument"
        )
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

    result["status"] = "ambiguous"
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
