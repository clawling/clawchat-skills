#!/usr/bin/env python3
from __future__ import annotations

import argparse
import ast
import importlib.util
import json
import os
import re
import shlex
import subprocess
import sys
from dataclasses import asdict, dataclass
from pathlib import Path
from types import ModuleType


SETUP_PATH = "liveware/scripts/setup.py"
START_PATH = "liveware/scripts/start.sh"
SCRIPTS_PATH = "liveware/scripts"
SUBPROCESS_APIS = {"run", "call", "check_call", "check_output", "Popen"}
APP_COLLECTION_NAMES = {"apps", "items", "data", "results", "payload"}
IDENTITY_NAMES = {"SKILL_NAME", "APP_NAME", "CLAWCHAT_APP_NAME"}
SHELL_OPERATORS = {"|", "||", "&&", ";", "&"}
CONTROL_WORDS = {"if", "then", "elif", "else", "do", "while", "until", "!", "command", "env"}
CREDENTIAL_PARTS = {"TOKEN", "PASSWORD", "PASSWD", "SECRET", "CREDENTIAL", "CREDENTIALS"}


@dataclass(frozen=True)
class Finding:
    code: str
    path: str
    message: str


def add(findings: list[Finding], code: str, path: str, message: str) -> None:
    if not any(item.code == code and item.path == path and item.message == message for item in findings):
        findings.append(Finding(code, path, message))


def dotted_name(node: ast.AST) -> str | None:
    if isinstance(node, ast.Name):
        return node.id
    if isinstance(node, ast.Attribute):
        prefix = dotted_name(node.value)
        return f"{prefix}.{node.attr}" if prefix else node.attr
    return None


def literal_string(node: ast.AST) -> str | None:
    return node.value if isinstance(node, ast.Constant) and isinstance(node.value, str) else None


def literal_integer(node: ast.AST) -> int | None:
    return node.value if isinstance(node, ast.Constant) and type(node.value) is int else None


def subscript_index(node: ast.Subscript) -> object:
    value = node.slice
    if isinstance(value, ast.Constant):
        return value.value
    return None


def path_parts(node: ast.AST) -> list[str] | None:
    if isinstance(node, ast.BinOp) and isinstance(node.op, ast.Div):
        left = path_parts(node.left)
        right = path_part(node.right)
        return left + [right] if left is not None and right is not None else None
    if isinstance(node, ast.Name) and node.id == "STATE_ROOT":
        return ["STATE_ROOT"]
    if (
        isinstance(node, ast.Call)
        and isinstance(node.func, ast.Attribute)
        and node.func.attr == "home"
        and isinstance(node.func.value, ast.Name)
        and node.func.value.id == "Path"
        and not node.args
    ):
        return ["HOME"]
    return None


def path_part(node: ast.AST) -> str | None:
    text = literal_string(node)
    if text is not None:
        return text
    if isinstance(node, ast.JoinedStr):
        pieces: list[str] = []
        for value in node.values:
            if isinstance(value, ast.Constant) and isinstance(value.value, str):
                pieces.append(value.value)
            elif isinstance(value, ast.FormattedValue) and isinstance(value.value, ast.Name):
                pieces.append(f"${{{value.value.id}}}")
            else:
                return None
        return "".join(pieces)
    return None


def credential_name(value: str) -> bool:
    normalized = re.sub(r"[^A-Za-z0-9]+", "_", value).upper().strip("_")
    parts = set(normalized.split("_"))
    return "API_KEY" in normalized or bool(parts & CREDENTIAL_PARTS)


def contains_words(words: list[str | None], expected: tuple[str, ...]) -> bool:
    lowered = [word.lower() if isinstance(word, str) else None for word in words]
    size = len(expected)
    return any(lowered[index : index + size] == list(expected) for index in range(len(lowered) - size + 1))


def command_words(call: ast.Call, subprocess_call: bool) -> list[str | None]:
    if subprocess_call:
        if not call.args:
            return []
        argument = call.args[0]
        if isinstance(argument, (ast.List, ast.Tuple)):
            return [literal_string(item) for item in argument.elts]
        text = literal_string(argument)
        return [text] if text is not None else []
    return [literal_string(item) for item in call.args]


def forbidden_python_words(words: list[str | None]) -> bool:
    concrete = [word.lower() if isinstance(word, str) else None for word in words]
    for index, word in enumerate(concrete):
        if word is None:
            continue
        base = os.path.basename(word)
        tail = concrete[index + 1 :]
        if base in {"pip", "pip3"} and tail[:1] == ["install"]:
            return True
        if base in {"python", "python3"} and tail[:3] == ["-m", "pip", "install"]:
            return True
        if base in {"npm", "pnpm", "yarn"} and tail[:1] in (["install"], ["add"]):
            return True
    return contains_words(words, ("app", "delete")) or contains_words(words, ("app", "remove"))


def shell_string_download(text: str) -> bool:
    return re.search(r"(?:^|[;&|]\s*)(?:curl|wget)\b[^\n]*\|\s*(?:ba)?sh\b", text, re.IGNORECASE) is not None


def exact_name_comparison(node: ast.AST) -> bool:
    for candidate in ast.walk(node):
        if not isinstance(candidate, ast.Compare) or not any(isinstance(operator, ast.Eq) for operator in candidate.ops):
            continue
        compared = [candidate.left, *candidate.comparators]
        if any(isinstance(item, ast.Name) and item.id in IDENTITY_NAMES for item in compared):
            return True
    return False


class PythonContract(ast.NodeVisitor):
    def __init__(self) -> None:
        self.subprocess_modules = {"subprocess"}
        self.subprocess_functions: set[str] = set()
        self.login = False
        self.registration = False
        self.hermes_creation = False
        self.unsafe_app_creation = False
        self.unsafe_shell = False
        self.forbidden_operation = False
        self.credential_read = False
        self.first_app_fallback = False
        self.standard_state_root = False
        self.standard_state_file = False
        self.bad_state_path = False
        self.bad_state_identity = False
        self.stable_state_identity = False
        self.directory_modes: set[str] = set()
        self.file_mode = False
        self.bad_state_mode = False
        self.atomic_replace = False

    def visit_Import(self, node: ast.Import) -> None:
        for item in node.names:
            if item.name == "subprocess":
                self.subprocess_modules.add(item.asname or item.name)
        self.generic_visit(node)

    def visit_ImportFrom(self, node: ast.ImportFrom) -> None:
        if node.module == "subprocess":
            for item in node.names:
                if item.name in SUBPROCESS_APIS:
                    self.subprocess_functions.add(item.asname or item.name)
        self.generic_visit(node)

    def is_subprocess_call(self, node: ast.Call) -> bool:
        if isinstance(node.func, ast.Name):
            return node.func.id in self.subprocess_functions
        return (
            isinstance(node.func, ast.Attribute)
            and node.func.attr in SUBPROCESS_APIS
            and isinstance(node.func.value, ast.Name)
            and node.func.value.id in self.subprocess_modules
        )

    def visit_Assign(self, node: ast.Assign) -> None:
        names = {target.id for target in node.targets if isinstance(target, ast.Name)}
        parts = path_parts(node.value)
        if "STATE_ROOT" in names and parts == ["HOME", ".clawling", "apps"]:
            self.standard_state_root = True
        if "STATE_ROOT" in names and parts != ["HOME", ".clawling", "apps"]:
            self.bad_state_path = True
        if "STATE_FILE" in names and parts == ["STATE_ROOT", "${SKILL_NAME}.json"]:
            self.standard_state_file = True
        if "STATE_FILE" in names and parts != ["STATE_ROOT", "${SKILL_NAME}.json"]:
            self.bad_state_path = True
        self.generic_visit(node)

    def visit_Dict(self, node: ast.Dict) -> None:
        values = {
            key.value: value
            for key, value in zip(node.keys, node.values)
            if isinstance(key, ast.Constant) and isinstance(key.value, str)
        }
        if "app_name" in values:
            value = values["app_name"]
            stable = isinstance(value, ast.Name) and value.id == "SKILL_NAME"
            self.bad_state_identity = self.bad_state_identity or not stable
            if {"schema_version", "skill_name", "app_name"}.issubset(values):
                skill_value = values["skill_name"]
                self.stable_state_identity = self.stable_state_identity or (
                    stable and isinstance(skill_value, ast.Name) and skill_value.id == "SKILL_NAME"
                )
        self.generic_visit(node)

    def visit_Subscript(self, node: ast.Subscript) -> None:
        name = dotted_name(node.value)
        if name and name.rsplit(".", 1)[-1].lower() in APP_COLLECTION_NAMES and subscript_index(node) == 0:
            self.first_app_fallback = True
        if name and name.endswith("environ"):
            key = literal_string(node.slice)
            if key and credential_name(key):
                self.credential_read = True
        self.generic_visit(node)

    def visit_For(self, node: ast.For) -> None:
        collection = dotted_name(node.iter)
        if collection and collection.rsplit(".", 1)[-1].lower() in APP_COLLECTION_NAMES:
            has_return = any(isinstance(item, ast.Return) for item in ast.walk(node))
            if has_return and not exact_name_comparison(node):
                self.first_app_fallback = True
        self.generic_visit(node)

    def visit_If(self, node: ast.If) -> None:
        test_strings = {
            item.value.lower()
            for item in ast.walk(node.test)
            if isinstance(item, ast.Constant) and isinstance(item.value, str)
        }
        if test_strings & {"tarot", "arcana"}:
            self.first_app_fallback = True
        self.generic_visit(node)

    def visit_Call(self, node: ast.Call) -> None:
        name = dotted_name(node.func) or ""
        final_name = name.rsplit(".", 1)[-1]
        if final_name == "liveware_login":
            self.login = True
        if final_name == "register_app":
            self.registration = True

        subprocess_call = self.is_subprocess_call(node)
        if subprocess_call:
            for keyword in node.keywords:
                if keyword.arg == "shell" and not (
                    isinstance(keyword.value, ast.Constant) and keyword.value.value is False
                ):
                    self.unsafe_shell = True
                if keyword.arg is None and isinstance(keyword.value, ast.Dict):
                    for key, value in zip(keyword.value.keys, keyword.value.values):
                        if literal_string(key) == "shell" and not (
                            isinstance(value, ast.Constant) and value.value is False
                        ):
                            self.unsafe_shell = True

        words = command_words(node, subprocess_call)
        if subprocess_call or final_name in {"run_liveware", "check_output", "run"}:
            if forbidden_python_words(words):
                self.forbidden_operation = True
            if contains_words(words, ("app", "create")):
                if contains_words(words, ("--agent-type", "hermes")):
                    self.hermes_creation = True
                else:
                    self.unsafe_app_creation = True
            if words and isinstance(words[0], str) and shell_string_download(words[0]):
                self.forbidden_operation = True

        if name.endswith("environ.get") or final_name == "getenv":
            key = literal_string(node.args[0]) if node.args else None
            if key and credential_name(key):
                self.credential_read = True

        if final_name == "mkdir":
            receiver = dotted_name(node.func.value) if isinstance(node.func, ast.Attribute) else None
            mode = next((literal_integer(item.value) for item in node.keywords if item.arg == "mode"), None)
            if receiver in {"STATE_ROOT", "STATE_ROOT.parent"}:
                if mode == 0o700:
                    self.directory_modes.add(receiver)
                else:
                    self.bad_state_mode = True
        if name.endswith("chmod") and len(node.args) >= 2:
            target = dotted_name(node.args[0])
            mode = literal_integer(node.args[1])
            if target in {"STATE_ROOT", "STATE_ROOT.parent"}:
                if mode == 0o700:
                    self.directory_modes.add(target)
                else:
                    self.bad_state_mode = True
            if target == "temp_name":
                if mode == 0o600:
                    self.file_mode = True
                else:
                    self.bad_state_mode = True
        if name.endswith("replace") and len(node.args) >= 2:
            if dotted_name(node.args[0]) == "temp_name" and dotted_name(node.args[1]) == "STATE_FILE":
                self.atomic_replace = True
        self.generic_visit(node)

    @property
    def state_persistence_ok(self) -> bool:
        return (
            self.stable_state_identity
            and not self.bad_state_identity
            and not self.bad_state_mode
            and self.directory_modes == {"STATE_ROOT", "STATE_ROOT.parent"}
            and self.file_mode
            and self.atomic_replace
        )


_RENDERER: ModuleType | None = None


def load_renderer() -> ModuleType:
    global _RENDERER
    if _RENDERER is None:
        path = Path(__file__).with_name("render_scripts.py")
        spec = importlib.util.spec_from_file_location("creating_liveware_scripts_renderer_for_validation", path)
        if spec is None or spec.loader is None:
            raise RuntimeError("Renderer could not be loaded.")
        module = importlib.util.module_from_spec(spec)
        sys.modules[spec.name] = module
        spec.loader.exec_module(module)
        _RENDERER = module
    return _RENDERER


def strip_shell_comment(line: str) -> str:
    quote: str | None = None
    escaped = False
    for index, character in enumerate(line):
        if escaped:
            escaped = False
            continue
        if character == "\\" and quote != "'":
            escaped = True
            continue
        if quote:
            if character == quote:
                quote = None
            continue
        if character in {"'", '"'}:
            quote = character
        elif character == "#" and (index == 0 or line[index - 1].isspace()):
            return line[:index]
    return line


def shell_tokens(line: str) -> list[str]:
    try:
        lexer = shlex.shlex(line, posix=True, punctuation_chars="|;&")
        lexer.whitespace_split = True
        lexer.commenters = "#"
        return list(lexer)
    except ValueError:
        return []


def command_segments(tokens: list[str]) -> list[list[str]]:
    segments: list[list[str]] = [[]]
    for token in tokens:
        if token in SHELL_OPERATORS:
            if segments[-1]:
                segments.append([])
            continue
        segments[-1].append(token)
    return [segment for segment in segments if segment]


def command_head(segment: list[str]) -> tuple[str, list[str]]:
    index = 0
    while index < len(segment):
        token = segment[index]
        if token in CONTROL_WORDS or re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*=.*", token):
            index += 1
            continue
        return os.path.basename(token), segment[index + 1 :]
    return "", []


def shell_expansions(line: str) -> list[str]:
    result: list[str] = []
    index = 0
    quote: str | None = None
    while index < len(line):
        character = line[index]
        if character == "\\" and quote != "'":
            index += 2
            continue
        if character in {"'", '"'}:
            if quote == character:
                quote = None
            elif quote is None:
                quote = character
            index += 1
            continue
        if character == "$" and quote != "'":
            match = re.match(r"\$\{?([A-Za-z_][A-Za-z0-9_]*)", line[index:])
            if match:
                result.append(match.group(1))
                index += len(match.group(0))
                continue
        index += 1
    return result


def split_heredocs(text: str) -> tuple[list[str], list[str]]:
    lines = text.splitlines()
    shell_lines: list[str] = []
    python_bodies: list[str] = []
    index = 0
    while index < len(lines):
        line = lines[index]
        shell_lines.append(line)
        match = re.search(r"<<-?\s*(['\"]?)([A-Za-z_][A-Za-z0-9_]*)\1", line)
        if match is None:
            index += 1
            continue
        delimiter = match.group(2)
        body: list[str] = []
        index += 1
        while index < len(lines) and lines[index].strip() != delimiter:
            body.append(lines[index])
            index += 1
        if re.search(r"\bpython(?:3)?\b", line):
            python_bodies.append("\n".join(body))
        if index < len(lines):
            shell_lines.append(lines[index])
        index += 1
    return shell_lines, python_bodies


def shell_forbidden(tokens: list[str]) -> bool:
    segments = command_segments(tokens)
    commands = [command_head(segment) for segment in segments]
    for command, arguments in commands:
        lower = [item.lower() for item in arguments]
        base = command.lower()
        if base in {"pip", "pip3"} and lower[:1] == ["install"]:
            return True
        if base in {"python", "python3"} and lower[:3] == ["-m", "pip", "install"]:
            return True
        if base in {"npm", "pnpm", "yarn"} and lower[:1] in (["install"], ["add"]):
            return True
        if lower[:2] in (["app", "delete"], ["app", "remove"]):
            return True
        if base in {"sh", "bash"} and "-c" in arguments:
            command_index = arguments.index("-c")
            if command_index + 1 < len(arguments) and shell_string_download(arguments[command_index + 1]):
                return True
    for index, token in enumerate(tokens):
        if token != "|":
            continue
        left_boundary = max((position for position in range(index) if tokens[position] in SHELL_OPERATORS), default=-1)
        right_boundary = next(
            (position for position in range(index + 1, len(tokens)) if tokens[position] in SHELL_OPERATORS),
            len(tokens),
        )
        left, _ = command_head(tokens[left_boundary + 1 : index])
        right, _ = command_head(tokens[index + 1 : right_boundary])
        if left.lower() in {"curl", "wget"} and right.lower() in {"sh", "bash"}:
            return True
    return False


def invokes_setup(tokens: list[str], setup_variables: set[str]) -> bool:
    for segment in command_segments(tokens):
        command, arguments = command_head(segment)
        setup_arguments = []
        for item in arguments:
            variable = re.fullmatch(r"\$\{?([A-Za-z_][A-Za-z0-9_]*)\}?", item)
            if item.rstrip("/ ").endswith("setup.py") or (variable and variable.group(1) in setup_variables):
                setup_arguments.append(item)
        if command.rstrip("/ ").endswith("setup.py"):
            return True
        if command in {"python", "python3", "bash", "sh", "source", "."} and setup_arguments:
            return True
    return False


def unsafe_kill(tokens: list[str], owned: set[str]) -> bool:
    for segment in command_segments(tokens):
        command, arguments = command_head(segment)
        if command in {"pkill", "killall"}:
            return True
        if command != "kill":
            continue
        targets: list[str] = []
        for argument in arguments:
            if re.match(r"^\d*[<>]", argument):
                break
            if argument == "--" or argument.startswith("-"):
                continue
            targets.append(argument)
        if not targets:
            continue
        for target in targets:
            match = re.fullmatch(r"\$\{?([A-Za-z_][A-Za-z0-9_]*)\}?", target)
            if match is None or match.group(1) not in owned:
                return True
    return False


def unsafe_kill_flow(code_lines: list[str], tokens_by_line: list[list[str]]) -> bool:
    owned: set[str] = set()
    for line, tokens in zip(code_lines, tokens_by_line):
        assignment = re.fullmatch(r"\s*([A-Za-z_][A-Za-z0-9_]*)\s*=\s*(.*?)\s*", line)
        if assignment is not None:
            name, value = assignment.groups()
            if re.fullmatch(r"\"?\$!\"?", value):
                owned.add(name)
            else:
                owned.discard(name)
        if unsafe_kill(tokens, owned):
            return True
    return False


def python_body_facts(body: str) -> tuple[bool, bool, bool]:
    try:
        tree = ast.parse(body)
    except SyntaxError:
        return False, False, False
    contract = PythonContract()
    contract.visit(tree)
    kills = any(
        isinstance(node, ast.Call)
        and (dotted_name(node.func) or "") in {"os.kill", "os.killpg", "signal.pthread_kill"}
        for node in ast.walk(tree)
    )
    return kills, contract.forbidden_operation, contract.credential_read


def validate_start(start: str, findings: list[Finding]) -> None:
    shell_lines, python_bodies = split_heredocs(start)
    code_lines = [strip_shell_comment(line) for line in shell_lines]
    tokens_by_line = [shell_tokens(line) for line in code_lines]

    state_values = [
        token.removeprefix("STATE_FILE=")
        for tokens in tokens_by_line
        for token in tokens
        if token.startswith("STATE_FILE=")
    ]
    standard_state = "${HOME}/.clawling/apps/${SKILL_NAME}.json"
    state_reads = sum(
        1
        for line in code_lines
        if re.search(r"\$(?:\{)?STATE_FILE(?:\}|\b)", line) is not None
    )
    if state_values != [standard_state] or state_reads < 1:
        add(findings, "LW003", START_PATH, "Start does not read the standard state file.")

    setup_variables = {
        match.group(1)
        for tokens in tokens_by_line
        for token in tokens
        if (match := re.fullmatch(r"([A-Za-z_][A-Za-z0-9_]*)=(.*setup\.py)", token)) is not None
    }
    if any(invokes_setup(tokens, setup_variables) for tokens in tokens_by_line):
        add(findings, "LW008", START_PATH, "Start invokes setup instead of requiring existing state.")

    python_kill = False
    python_forbidden = False
    python_credential = False
    for body in python_bodies:
        kills, forbidden, credential = python_body_facts(body)
        python_kill = python_kill or kills
        python_forbidden = python_forbidden or forbidden
        python_credential = python_credential or credential
    if python_kill or unsafe_kill_flow(code_lines, tokens_by_line):
        add(findings, "LW010", START_PATH, "Start can terminate a process it cannot prove it owns.")

    if python_forbidden or any(shell_forbidden(tokens) for tokens in tokens_by_line):
        add(findings, "LW011", SCRIPTS_PATH, "Scripts contain a forbidden install, download, or app deletion operation.")

    if python_credential or any(credential_name(name) for line in code_lines for name in shell_expansions(line)):
        add(findings, "LW015", SCRIPTS_PATH, "Scripts read a credential environment variable directly.")

    renderer = load_renderer()
    try:
        spans = renderer.parse_marker_spans(start)
    except ValueError:
        add(findings, "LW012", START_PATH, "Start has invalid repair-safe block markers.")
        return

    binding = start[spans[renderer.BEGIN_BINDING][1] : spans[renderer.END_BINDING][0]]
    binding_commands: list[tuple[str, list[str]]] = []
    for line in binding.splitlines():
        tokens = shell_tokens(line)
        for index, token in enumerate(tokens[:-1]):
            if token == "tunnel" and tokens[index + 1] in {"bind", "bind-static"}:
                binding_commands.append((tokens[index + 1], tokens[index + 2 :]))
    binding_ok = len(binding_commands) == 1
    if binding_ok and binding_commands[0][0] == "bind":
        urls = [item for item in binding_commands[0][1] if item.startswith("http://")]
        binding_ok = len(urls) == 1 and re.fullmatch(r"http://127\.0\.0\.1:[^/\s]+(?:/[^\s]*)?", urls[0]) is not None
    if not binding_ok:
        add(
            findings,
            "LW013",
            START_PATH,
            "Liveware binding is missing, ambiguous, or not explicitly loopback-only.",
        )


def validate_python(setup: str, findings: list[Finding]) -> None:
    try:
        tree = ast.parse(setup)
    except SyntaxError as exc:
        add(findings, "LW006", SETUP_PATH, f"Python syntax error: {exc.msg}")
        return
    contract = PythonContract()
    contract.visit(tree)
    if not (contract.standard_state_root and contract.standard_state_file) or contract.bad_state_path:
        add(findings, "LW002", SETUP_PATH, "Setup does not use per-skill JSON app state.")
    if contract.first_app_fallback:
        add(findings, "LW004", SETUP_PATH, "App recovery can fall back to a non-matching app.")
    if contract.unsafe_shell:
        add(findings, "LW007", SETUP_PATH, "Python subprocess uses a shell value other than literal False.")
    if not (contract.login and contract.registration):
        add(findings, "LW009", SETUP_PATH, "Setup is missing ClawChat login or registration.")
    if contract.forbidden_operation:
        add(findings, "LW011", SCRIPTS_PATH, "Scripts contain a forbidden install, download, or app deletion operation.")
    if contract.credential_read:
        add(findings, "LW015", SCRIPTS_PATH, "Scripts read a credential environment variable directly.")
    if not contract.hermes_creation or contract.unsafe_app_creation:
        add(findings, "LW016", SETUP_PATH, "App creation is missing the Hermes agent type.")
    if not contract.state_persistence_ok:
        add(
            findings,
            "LW017",
            SETUP_PATH,
            "State persistence is not atomic with required permissions and stable identity.",
        )


def validate_texts(setup: str, start: str) -> list[Finding]:
    findings: list[Finding] = []
    validate_python(setup, findings)
    validate_start(start, findings)
    return findings


def validate_consistency(
    setup: str,
    start: str,
    analysis: dict[str, object],
    findings: list[Finding],
    target: Path | None = None,
) -> None:
    if (
        analysis.get("schema_version") != 1
        or analysis.get("status") != "ready"
        or analysis.get("issues") != []
    ):
        add(findings, "LW018", "analysis.json", "Resolved schema-version-1 analysis with no issues is required.")
        return
    renderer = load_renderer()
    if target is not None:
        try:
            renderer.resolve_target_root(analysis, target)
        except (OSError, RuntimeError, TypeError, ValueError):
            add(findings, "LW018", "analysis.json", "Analysis target_root does not match target.")
            return
    try:
        expected_setup = renderer.render_setup(analysis)
    except (KeyError, TypeError, ValueError):
        add(findings, "LW018", SETUP_PATH, "Generated setup does not match analysis.")
    else:
        if setup != expected_setup:
            add(findings, "LW018", SETUP_PATH, "Generated setup does not match analysis.")
    try:
        expected_start = renderer.render_start(analysis)
    except (KeyError, TypeError, ValueError):
        add(findings, "LW019", START_PATH, "Generated start or adapter does not match analysis.")
    else:
        if start != expected_start:
            add(findings, "LW019", START_PATH, "Generated start or adapter does not match analysis.")


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
        validate_consistency(setup, start, analysis, findings, target=target)
    result = subprocess.run(["bash", "-n", str(start_path)], capture_output=True, text=True, check=False)
    if result.returncode != 0:
        add(findings, "LW014", str(start_path), "Bash syntax validation failed.")
    return findings


def print_findings(findings: list[Finding]) -> None:
    print(json.dumps([asdict(item) for item in findings], indent=2, sort_keys=True))


def load_cli_analysis(path: Path) -> tuple[dict[str, object] | None, Finding | None]:
    try:
        text = path.read_text(encoding="utf-8")
    except (OSError, UnicodeError):
        return None, Finding("LW018", str(path), "Analysis file could not be read.")
    try:
        payload = json.loads(text)
    except json.JSONDecodeError:
        return None, Finding("LW018", str(path), "Analysis file is not valid JSON.")
    if not isinstance(payload, dict):
        return None, Finding("LW018", str(path), "Analysis JSON must be an object.")
    return payload, None


def main() -> int:
    parser = argparse.ArgumentParser(description="Statically validate generated Liveware scripts.")
    parser.add_argument("target", type=Path)
    parser.add_argument("--analysis", type=Path)
    args = parser.parse_args()
    analysis = None
    if args.analysis is not None:
        analysis, finding = load_cli_analysis(args.analysis)
        if finding is not None:
            print_findings([finding])
            return 1
    findings = validate_target(args.target.expanduser().resolve(), analysis=analysis)
    print_findings(findings)
    return 1 if findings else 0


if __name__ == "__main__":
    raise SystemExit(main())
