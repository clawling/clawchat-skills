#!/usr/bin/env python3
from __future__ import annotations

import argparse
import importlib.util
import json
import os
import re
from functools import lru_cache
from pathlib import Path
from types import ModuleType

NAME_RE = re.compile(r"^[a-z0-9][a-z0-9-]{0,62}$")
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
LIFECYCLE_SCRIPT_SUFFIXES = frozenset({".sh", ".py", ".js", ".mjs", ".cjs", ".ts", ".rb"})
LIFECYCLE_ACTIONS = frozenset({"start", "run", "launch", "launcher", "serve"})
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
REFERENCE_SCRIPT_HARMLESS_RE = re.compile(
    r"^(?:(?:for[ \t]+(?:tests?|testing|linting)(?:[ \t]+only)?)|"
    r"(?:as[ \t]+an?[ \t]+example)),[ \t]+|"
    r"[ \t]+for[ \t]+(?:tests?|testing|linting)(?:[ \t]+only)?$",
    re.IGNORECASE,
)
REFERENCE_LEADING_QUALIFIER_RE = re.compile(
    r"^(?:(?:in|for)[ \t]+production|(?:at|during)[ \t]+runtime)[,:][ \t]+",
    re.IGNORECASE,
)
REFERENCE_ACTION_NEGATION_RE = re.compile(
    r"(?:\b(?:for[ \t]+example|as[ \t]+an?[ \t]+example|example(?=[ \t]*:)|"
    r"do[ \t]+not|should[ \t]+not|not|never|obsolete|deprecated)\b|"
    r"\bdon['’]t\b)",
    re.IGNORECASE,
)
REFERENCE_ACTION_OBSOLETE_RE = re.compile(
    r"^[ \t]*(?:\([ \t]*)?(?:is[ \t]+)?(?:obsolete|deprecated)\b",
    re.IGNORECASE,
)
REFERENCE_ACTION_BOUNDARY_RE = re.compile(r",|\b(?:but|then)\b", re.IGNORECASE)


def reference_declares_lifecycle(text: str) -> bool:
    text = re.sub(r"\be\.g\.(?=[ \t]*,?)", "For example", text, flags=re.IGNORECASE)
    for statement in re.split(r"[!?;\n]+|\.(?=\s|$)", text):
        statement = re.sub(
            r"^\s*(?:(?:[-*+])|(?:[0-9]+[.)]))\s+",
            "",
            statement,
        ).strip()
        statement = REFERENCE_LEADING_QUALIFIER_RE.sub("", statement, count=1)
        if not statement:
            continue
        if any(pattern.fullmatch(statement) is not None for pattern in REFERENCE_LIFECYCLE_PATTERNS):
            return True
        for match in REFERENCE_SCRIPT_ACTION_RE.finditer(statement):
            before = statement[: match.start()].strip()
            previous_action = REFERENCE_SCRIPT_ACTION_RE.search(statement, 0, match.start())
            qualifier_context = before
            if previous_action is not None:
                boundaries = list(REFERENCE_ACTION_BOUNDARY_RE.finditer(before))
                if boundaries:
                    qualifier_context = before[boundaries[-1].end() :].strip()
            action_is_qualified = (
                REFERENCE_ACTION_NEGATION_RE.search(qualifier_context) is not None
                or REFERENCE_ACTION_OBSOLETE_RE.match(statement[match.end() :]) is not None
            )
            if (
                lifecycle_script_name(Path(match.group(1)))
                and (
                    previous_action is not None
                    or REFERENCE_SCRIPT_HARMLESS_RE.search(statement) is None
                )
                and not action_is_qualified
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


def broken_or_unresolvable_symlink(path: Path) -> bool:
    try:
        if not path.is_symlink():
            return False
        path.resolve(strict=True)
    except (OSError, RuntimeError):
        return True
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
) -> tuple[list[Path], list[Path], list[Path], list[Path]]:
    unreadable: list[Path] = []
    unsafe: list[Path] = []
    broken: list[Path] = []
    start = liveware / "scripts" / "start.sh"
    manager_names = (
        "Dockerfile",
        "docker-compose.yml",
        "docker-compose.yaml",
        "compose.yml",
        "compose.yaml",
        "supervisord.conf",
        "supervisor.conf",
        "s6",
        "s6-rc.d",
    )
    paths = [parent / name for parent in (target, liveware) for name in manager_names]
    for parent in (target, liveware):
        paths.extend(parent / name for name in sorted(PM2_CONFIG_NAMES))
    if not is_exact_canonical_generated_start(start, target, skill_name):
        paths.append(start)

    def list_directory(directory: Path) -> list[Path]:
        if not path_present(directory):
            return []
        if broken_or_unresolvable_symlink(directory):
            broken.append(directory)
            return []
        if not path_resolves_inside(directory, target):
            unsafe.append(directory)
            return []
        try:
            if not directory.is_dir():
                return []
            if not os.access(directory, os.R_OK | os.X_OK):
                raise PermissionError(directory)
            return sorted(directory.iterdir())
        except (OSError, RuntimeError):
            unreadable.append(directory)
            return []

    for directory in (target, liveware, target / "scripts", liveware / "scripts"):
        for path in list_directory(directory):
            if path.suffix.lower() != ".service" and not lifecycle_script_name(path):
                continue
            if broken_or_unresolvable_symlink(path):
                broken.append(path)
                continue
            if not path_resolves_inside(path, target):
                unsafe.append(path)
                continue
            try:
                is_file = path.is_file()
            except OSError:
                unreadable.append(path)
                continue
            if not is_file:
                continue
            relative = target_relative(path, target)
            if relative == "liveware/scripts/start.sh" and is_exact_canonical_generated_start(
                path,
                target,
                skill_name,
            ):
                continue
            paths.append(path)

    references = target / "references"
    pending = [references]
    visited: set[Path] = set()
    while pending:
        directory = pending.pop()
        if not path_present(directory):
            continue
        if not path_resolves_inside(directory, target):
            unsafe.append(directory)
            continue
        try:
            resolved = directory.resolve(strict=False)
        except (OSError, RuntimeError):
            unreadable.append(directory)
            continue
        if resolved in visited:
            continue
        visited.add(resolved)
        for path in list_directory(directory):
            if broken_or_unresolvable_symlink(path):
                broken.append(path)
                continue
            if not path_resolves_inside(path, target):
                unsafe.append(path)
                continue
            try:
                if path.is_dir():
                    pending.append(path)
                    continue
                if not path.is_file():
                    continue
                declared_signal = reference_declares_lifecycle(
                    path.read_text(encoding="utf-8")
                )
            except (OSError, UnicodeError, RuntimeError):
                unreadable.append(path)
                continue
            if declared_signal:
                paths.append(path)

    unique: list[Path] = []
    seen: set[Path] = set()
    for path in paths:
        if broken_or_unresolvable_symlink(path):
            broken.append(path)
            continue
        if path_present(path) and not path_resolves_inside(path, target):
            unsafe.append(path)
            continue
        if path_present(path) and path not in seen:
            seen.add(path)
            unique.append(path)
    return unique, unreadable, unsafe, broken


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
    if not path_present(path):
        return False
    if broken_or_unresolvable_symlink(path):
        record_path_issue(
            result,
            target,
            path,
            f"{label} is a broken or unresolvable symlink",
            f"Unresolvable {label}",
        )
        return True
    if path_resolves_inside(path, target):
        return False
    record_path_issue(
        result,
        target,
        path,
        f"{label} resolves outside the target root",
        f"Unsafe {label}",
    )
    return True


def inspect_node_package(
    result: dict[str, object],
    target: Path,
    package_file: Path,
) -> tuple[bool, str, Path | None]:
    package_source = read_analysis_text(result, target, package_file, "Node package metadata")
    if package_source is None:
        return False, "", None
    try:
        package = json.loads(package_source)
    except json.JSONDecodeError:
        record_path_issue(
            result,
            target,
            package_file,
            f"Invalid JSON: {package_file.relative_to(target)}",
            "Invalid Node package metadata",
        )
        return False, "", None
    if not isinstance(package, dict):
        record_path_issue(
            result,
            target,
            package_file,
            f"Package metadata must be a JSON object: {package_file.relative_to(target)}",
            "Node package metadata must be an object",
        )
        return False, "", None
    scripts = package.get("scripts", {})
    if not isinstance(scripts, dict):
        record_path_issue(
            result,
            target,
            package_file,
            f"Package scripts must be a JSON object: {package_file.relative_to(target)}",
            "Node package scripts must be an object",
        )
        return False, "", None
    script_name = (
        "liveware"
        if isinstance(scripts.get("liveware"), str)
        else "start"
        if isinstance(scripts.get("start"), str)
        else ""
    )
    if not script_name:
        return True, "", None
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
        return False, script_name, entry_file
    if entry_file is not None and entry_file.is_file():
        entry_source = read_analysis_text(result, target, entry_file, "Node server entrypoint")
        if entry_source is None:
            return False, script_name, entry_file
    return True, script_name, entry_file


def analyze_target(target_root: Path) -> dict[str, object]:
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

    found_signals, unreadable_lifecycle, unsafe_lifecycle, broken_lifecycle = lifecycle_signals(
        target,
        liveware,
        name,
    )
    if broken_lifecycle:
        for path in broken_lifecycle:
            record_path_issue(
                result,
                target,
                path,
                f"Lifecycle or reference evidence is a broken or unresolvable symlink: {target_relative(path, target)}",
                "Unresolvable lifecycle or reference evidence",
            )
        evidence.extend(
            item
            for item in automatic_candidate_evidence(
                target,
                python_server,
                package_files,
                static_index,
            )
            if item not in evidence
        )
        return result
    if unsafe_lifecycle:
        for path in unsafe_lifecycle:
            record_path_issue(
                result,
                target,
                path,
                f"Lifecycle or reference evidence resolves outside the target root: {target_relative(path, target)}",
                "Unsafe lifecycle or reference evidence",
            )
        evidence.extend(
            item
            for item in automatic_candidate_evidence(
                target,
                python_server,
                package_files,
                static_index,
            )
            if item not in evidence
        )
        return result
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
        for path in found_signals:
            item = {
                "path": str(path.relative_to(target)),
                "reason": "Existing server or service lifecycle declaration",
            }
            if item not in evidence:
                evidence.append(item)
        for package_file in package_files:
            if not package_file.is_file():
                continue
            valid, _, _ = inspect_node_package(result, target, package_file)
            if not valid:
                return result
        result["status"] = "ambiguous"
        candidate_evidence = automatic_candidate_evidence(
            target,
            python_server,
            package_files,
            static_index,
        )
        evidence.extend(candidate_evidence)
        dynamic_kinds: list[str] = []
        if python_server.is_file():
            dynamic_kinds.append("Python")
        if any(path.is_file() for path in package_files):
            dynamic_kinds.append("Node")
        if dynamic_kinds:
            kinds = " and ".join(dynamic_kinds)
            issues.append(
                f"Existing lifecycle and {kinds} candidate require confirmation of the exact argv, default port, readiness check, lifecycle and logging ownership, and whether the command consumes exported PORT or uses a standalone {{port}} argument"
            )
        else:
            issues.append("Existing server lifecycle requires user confirmation before generating an adapter")
        return result

    if python_server.is_file():
        source = read_analysis_text(result, target, python_server, "Python server entrypoint")
        if source is None:
            return result
        del source
        result["status"] = "ambiguous"
        evidence.append(
            {
                "path": "liveware/server.py",
                "reason": "Python server candidate requiring interface confirmation",
            }
        )
        issues.append(
            "Confirm the Python command's exact argv, default port, readiness check, lifecycle and logging ownership, and whether it consumes exported PORT or uses a standalone {port} argument"
        )
        return result

    for package_file in package_files:
        if not package_file.is_file():
            continue
        valid, script_name, entry_file = inspect_node_package(result, target, package_file)
        if not valid:
            return result
        if not script_name:
            evidence.append({"path": str(package_file.relative_to(target)), "reason": "Package metadata without a Liveware or start script"})
            continue
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
            "Confirm the Node command's exact argv, default port, readiness check, lifecycle and logging ownership, and whether it consumes exported PORT or uses a standalone {port} argument"
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
