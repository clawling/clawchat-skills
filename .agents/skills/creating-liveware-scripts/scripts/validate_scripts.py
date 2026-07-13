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
from dataclasses import asdict, dataclass, field
from pathlib import Path
from types import ModuleType


SETUP_PATH = "liveware/scripts/setup.py"
START_PATH = "liveware/scripts/start.sh"
SCRIPTS_PATH = "liveware/scripts"
SUBPROCESS_APIS = {"run", "call", "check_call", "check_output", "Popen"}
IDENTITY_NAMES = {"SKILL_NAME", "APP_NAME", "CLAWCHAT_APP_NAME"}
SHELL_OPERATORS = {"|", "||", "&&", ";", "&"}
CONTROL_WORDS = {"if", "then", "elif", "else", "do", "while", "until", "!", "command", "env", "builtin"}
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


def command_words(
    call: ast.Call,
    subprocess_call: bool,
    literal_argv: dict[str, list[str | None]] | None = None,
) -> list[str | None]:
    if subprocess_call:
        if not call.args:
            return []
        argument = call.args[0]
        if isinstance(argument, (ast.List, ast.Tuple)):
            return [literal_string(item) for item in argument.elts]
        if isinstance(argument, ast.Name) and literal_argv is not None:
            return literal_argv.get(argument.id, [])
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


def exact_name_comparison(node: ast.AST, app_value_names: set[str]) -> bool:
    for candidate in ast.walk(node):
        if not isinstance(candidate, ast.Compare) or not any(
            isinstance(operator, ast.Eq) for operator in candidate.ops
        ):
            continue
        compared = [candidate.left, *candidate.comparators]
        identity = any(isinstance(item, ast.Name) and item.id in IDENTITY_NAMES for item in compared)
        app_value = any(
            isinstance(name, ast.Name) and name.id in app_value_names
            for item in compared
            for name in ast.walk(item)
        )
        if identity and app_value:
            return True
    return False


def has_unguarded_return(node: ast.AST, app_value_names: set[str], exact_guard: bool = False) -> bool:
    if isinstance(node, ast.Return):
        return not exact_guard
    if isinstance(node, ast.Assign):
        source_is_app_value = any(
            isinstance(name, ast.Name) and name.id in app_value_names for name in ast.walk(node.value)
        )
        for target in node.targets:
            if isinstance(target, ast.Name):
                if source_is_app_value:
                    app_value_names.add(target.id)
                else:
                    app_value_names.discard(target.id)
        return False
    if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef, ast.Lambda)):
        return False
    if isinstance(node, ast.If):
        body_guard = exact_guard or exact_name_comparison(node.test, app_value_names)
        body_names = set(app_value_names)
        else_names = set(app_value_names)
        return any(has_unguarded_return(item, body_names, body_guard) for item in node.body) or any(
            has_unguarded_return(item, else_names, exact_guard) for item in node.orelse
        )
    return any(has_unguarded_return(child, app_value_names, exact_guard) for child in ast.iter_child_nodes(node))


@dataclass
class PythonScope:
    literal_argv: dict[str, list[str | None]]
    literal_dicts: dict[str, dict[str, ast.AST]]
    app_sources: set[str]
    forbidden_argv: set[str] = field(default_factory=set)
    unsafe_kwargs: set[str] = field(default_factory=set)
    state_relevant: bool = False
    directory_modes: set[str] = field(default_factory=set)
    bad_state_mode: bool = False
    next_state_temp: int = 0
    state_handles: dict[str, int] = field(default_factory=dict)
    state_temps: dict[str, int] = field(default_factory=dict)
    state_streams: dict[str, int] = field(default_factory=dict)
    state_dump_temps: set[int] = field(default_factory=set)
    state_identity_temps: set[int] = field(default_factory=set)
    bad_state_identity_temps: set[int] = field(default_factory=set)
    file_mode_temps: set[int] = field(default_factory=set)
    bad_file_mode_temps: set[int] = field(default_factory=set)
    atomic_replace_temps: set[int] = field(default_factory=set)
    state_event: int = 0
    dump_events: dict[int, int] = field(default_factory=dict)
    file_mode_events: dict[int, int] = field(default_factory=dict)
    replace_events: dict[int, int] = field(default_factory=dict)
    ambiguous_state_flow: bool = False


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
        self.state_writer_seen = False
        self.stable_state_identity = False
        self.directory_modes: set[str] = set()
        self.file_mode = False
        self.atomic_replace = False
        self.invalid_state_writer = False
        self.scopes: list[PythonScope] = []

    @property
    def scope(self) -> PythonScope:
        return self.scopes[-1]

    def visit_scope(self, statements: list[ast.stmt]) -> None:
        scope = PythonScope({}, {}, set())
        self.scopes.append(scope)
        for statement in statements:
            self.visit(statement)
        self.scopes.pop()
        if scope.state_relevant and scope.state_dump_temps:
            self.state_writer_seen = True
            temp_writes_ok = all(
                temp in scope.state_identity_temps
                and temp not in scope.bad_state_identity_temps
                and temp in scope.file_mode_temps
                and temp not in scope.bad_file_mode_temps
                and temp in scope.atomic_replace_temps
                and scope.dump_events[temp] < scope.file_mode_events[temp] < scope.replace_events[temp]
                for temp in scope.state_dump_temps
            )
            writer_ok = (
                temp_writes_ok
                and not scope.bad_state_mode
                and not scope.ambiguous_state_flow
                and scope.directory_modes == {"STATE_ROOT", "STATE_ROOT.parent"}
            )
            self.invalid_state_writer = self.invalid_state_writer or not writer_ok
            if writer_ok:
                self.stable_state_identity = True
                self.directory_modes.update(scope.directory_modes)
                self.file_mode = True
                self.atomic_replace = True

    def visit_Module(self, node: ast.Module) -> None:
        self.visit_scope(node.body)

    def visit_FunctionDef(self, node: ast.FunctionDef) -> None:
        for decorator in node.decorator_list:
            self.visit(decorator)
        for default in [*node.args.defaults, *node.args.kw_defaults]:
            if default is not None:
                self.visit(default)
        if node.returns is not None:
            self.visit(node.returns)
        self.visit_scope(node.body)

    def visit_AsyncFunctionDef(self, node: ast.AsyncFunctionDef) -> None:
        self.visit_FunctionDef(node)

    def visit_ClassDef(self, node: ast.ClassDef) -> None:
        for decorator in node.decorator_list:
            self.visit(decorator)
        for base in node.bases:
            self.visit(base)
        for keyword in node.keywords:
            self.visit(keyword.value)
        self.visit_scope(node.body)

    def literal_dict(self, node: ast.AST) -> dict[str, ast.AST] | None:
        if isinstance(node, ast.Name):
            return self.scope.literal_dicts.get(node.id)
        if not isinstance(node, ast.Dict):
            return None
        values: dict[str, ast.AST] = {}
        for key, value in zip(node.keys, node.values):
            name = literal_string(key) if key is not None else None
            if name is None:
                return None
            values[name] = value
        return values

    def dataflow_snapshot(
        self,
    ) -> tuple[dict[str, list[str | None]], dict[str, dict[str, ast.AST]], set[str], set[str], set[str]]:
        return (
            dict(self.scope.literal_argv),
            {name: dict(values) for name, values in self.scope.literal_dicts.items()},
            set(self.scope.app_sources),
            set(self.scope.forbidden_argv),
            set(self.scope.unsafe_kwargs),
        )

    def restore_dataflow(
        self,
        snapshot: tuple[
            dict[str, list[str | None]],
            dict[str, dict[str, ast.AST]],
            set[str],
            set[str],
            set[str],
        ],
    ) -> None:
        argv, dictionaries, apps, forbidden, unsafe = snapshot
        self.scope.literal_argv = dict(argv)
        self.scope.literal_dicts = {name: dict(values) for name, values in dictionaries.items()}
        self.scope.app_sources = set(apps)
        self.scope.forbidden_argv = set(forbidden)
        self.scope.unsafe_kwargs = set(unsafe)

    @staticmethod
    def dictionary_signature(values: dict[str, ast.AST]) -> tuple[tuple[str, str], ...]:
        return tuple(sorted((key, ast.dump(value, include_attributes=False)) for key, value in values.items()))

    def merge_dataflow(
        self,
        left: tuple[dict[str, list[str | None]], dict[str, dict[str, ast.AST]], set[str], set[str], set[str]],
        right: tuple[dict[str, list[str | None]], dict[str, dict[str, ast.AST]], set[str], set[str], set[str]],
    ) -> None:
        left_argv, left_dicts, left_apps, left_forbidden, left_unsafe = left
        right_argv, right_dicts, right_apps, right_forbidden, right_unsafe = right
        self.scope.literal_argv = {
            name: value for name, value in left_argv.items() if right_argv.get(name) == value
        }
        self.scope.literal_dicts = {
            name: values
            for name, values in left_dicts.items()
            if name in right_dicts
            and self.dictionary_signature(values) == self.dictionary_signature(right_dicts[name])
        }
        self.scope.app_sources = left_apps | right_apps
        self.scope.forbidden_argv = left_forbidden | right_forbidden
        self.scope.unsafe_kwargs = left_unsafe | right_unsafe

    def visit_If(self, node: ast.If) -> None:
        for candidate in ast.walk(node):
            if not isinstance(candidate, ast.Call):
                continue
            name = dotted_name(candidate.func) or ""
            first = dotted_name(candidate.args[0]) if candidate.args else None
            if (
                self.is_state_tempfile_call(candidate)
                or (name == "json.dump" and len(candidate.args) >= 2 and dotted_name(candidate.args[1]) in self.scope.state_streams)
                or (name == "os.chmod" and first in {*self.scope.state_temps, "STATE_ROOT", "STATE_ROOT.parent"})
                or (
                    name == "os.replace"
                    and first in self.scope.state_temps
                    and len(candidate.args) >= 2
                    and dotted_name(candidate.args[1]) == "STATE_FILE"
                )
            ):
                self.scope.ambiguous_state_flow = True
                break
        self.visit(node.test)
        before = self.dataflow_snapshot()
        for statement in node.body:
            self.visit(statement)
        body = self.dataflow_snapshot()
        self.restore_dataflow(before)
        for statement in node.orelse:
            self.visit(statement)
        otherwise = self.dataflow_snapshot()

        self.merge_dataflow(body, otherwise)

    def is_app_list_call(self, node: ast.AST) -> bool:
        if not isinstance(node, ast.Call):
            return False
        subprocess_call = self.is_subprocess_call(node)
        words = command_words(node, subprocess_call, self.scope.literal_argv)
        if subprocess_call:
            head = words[0] if words else None
            return (
                isinstance(head, str)
                and os.path.basename(head).lower() == "liveware"
                and contains_words(words[1:], ("app", "list"))
            )
        return isinstance(node.func, ast.Name) and node.func.id == "run_liveware" and contains_words(
            words, ("app", "list")
        )

    def is_state_tempfile_call(self, node: ast.AST) -> bool:
        if not isinstance(node, ast.Call) or dotted_name(node.func) != "tempfile.mkstemp":
            return False
        directory = next((item.value for item in node.keywords if item.arg == "dir"), None)
        return dotted_name(directory) == "STATE_ROOT"

    def is_app_source(self, node: ast.AST) -> bool:
        if self.is_app_list_call(node):
            return True
        if isinstance(node, ast.Name):
            return node.id in self.scope.app_sources
        if isinstance(node, ast.Attribute):
            return self.is_app_source(node.value)
        if isinstance(node, ast.Call):
            if dotted_name(node.func) == "json.loads" and node.args:
                return self.is_app_source(node.args[0])
            if (
                isinstance(node.func, ast.Attribute)
                and node.func.attr in {"get", "splitlines"}
                and self.is_app_source(node.func.value)
            ):
                return True
            return False
        if isinstance(node, ast.IfExp):
            return self.is_app_source(node.body) or self.is_app_source(node.orelse)
        if isinstance(node, (ast.List, ast.Tuple, ast.Set)):
            return any(self.is_app_source(item) for item in node.elts)
        return False

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
        literal_words = (
            [literal_string(item) for item in node.value.elts]
            if isinstance(node.value, (ast.List, ast.Tuple))
            else None
        )
        literal_mapping = self.literal_dict(node.value)
        app_source = self.is_app_source(node.value)
        for name in names:
            self.scope.literal_argv.pop(name, None)
            self.scope.literal_dicts.pop(name, None)
            self.scope.app_sources.discard(name)
            self.scope.forbidden_argv.discard(name)
            self.scope.unsafe_kwargs.discard(name)
            self.scope.state_handles.pop(name, None)
            self.scope.state_temps.pop(name, None)
            self.scope.state_streams.pop(name, None)
            if literal_words is not None:
                self.scope.literal_argv[name] = literal_words
                if forbidden_python_words(literal_words):
                    self.scope.forbidden_argv.add(name)
            if literal_mapping is not None:
                self.scope.literal_dicts[name] = literal_mapping
                shell = literal_mapping.get("shell")
                if shell is not None and not (isinstance(shell, ast.Constant) and shell.value is False):
                    self.scope.unsafe_kwargs.add(name)
            if app_source:
                self.scope.app_sources.add(name)
        for target in node.targets:
            if isinstance(target, ast.Subscript) and isinstance(target.value, ast.Name):
                self.scope.literal_argv.pop(target.value.id, None)
                self.scope.literal_dicts.pop(target.value.id, None)
            if self.is_state_tempfile_call(node.value) and isinstance(target, (ast.Tuple, ast.List)):
                outputs = [item.id for item in target.elts if isinstance(item, ast.Name)]
                if len(outputs) >= 2:
                    for output in outputs:
                        self.scope.state_handles.pop(output, None)
                        self.scope.state_temps.pop(output, None)
                        self.scope.state_streams.pop(output, None)
                    self.scope.next_state_temp += 1
                    temp = self.scope.next_state_temp
                    self.scope.state_handles[outputs[0]] = temp
                    self.scope.state_temps[outputs[1]] = temp
        self.generic_visit(node)

    def visit_With(self, node: ast.With) -> None:
        for item in node.items:
            self.visit(item.context_expr)
            context = item.context_expr
            if (
                isinstance(context, ast.Call)
                and dotted_name(context.func) == "os.fdopen"
                and context.args
                and isinstance(context.args[0], ast.Name)
                and isinstance(item.optional_vars, ast.Name)
            ):
                temp = self.scope.state_handles.get(context.args[0].id)
                if temp is not None:
                    self.scope.state_streams[item.optional_vars.id] = temp
        for statement in node.body:
            self.visit(statement)

    def visit_Subscript(self, node: ast.Subscript) -> None:
        if self.is_app_source(node.value) and subscript_index(node) == 0:
            self.first_app_fallback = True
        name = dotted_name(node.value)
        if name == "os.environ":
            key = literal_string(node.slice)
            if key and credential_name(key):
                self.credential_read = True
        self.generic_visit(node)

    def visit_For(self, node: ast.For) -> None:
        if self.is_app_source(node.iter):
            app_value_names = {
                item.id for item in ast.walk(node.target) if isinstance(item, ast.Name)
            }
            if any(has_unguarded_return(item, app_value_names) for item in node.body):
                self.first_app_fallback = True
        self.visit(node.iter)
        self.visit(node.target)
        before = self.dataflow_snapshot()
        for statement in node.body:
            self.visit(statement)
        after_body = self.dataflow_snapshot()
        self.merge_dataflow(before, after_body)
        before_else = self.dataflow_snapshot()
        for statement in node.orelse:
            self.visit(statement)
        self.merge_dataflow(before_else, self.dataflow_snapshot())

    def visit_While(self, node: ast.While) -> None:
        self.visit(node.test)
        before = self.dataflow_snapshot()
        for statement in node.body:
            self.visit(statement)
        self.merge_dataflow(before, self.dataflow_snapshot())
        before_else = self.dataflow_snapshot()
        for statement in node.orelse:
            self.visit(statement)
        self.merge_dataflow(before_else, self.dataflow_snapshot())

    def visit_Call(self, node: ast.Call) -> None:
        name = dotted_name(node.func) or ""
        final_name = name.rsplit(".", 1)[-1]
        if (
            isinstance(node.func, ast.Attribute)
            and isinstance(node.func.value, ast.Name)
            and node.func.attr
            in {
                "append",
                "clear",
                "extend",
                "insert",
                "pop",
                "popitem",
                "remove",
                "reverse",
                "setdefault",
                "sort",
                "update",
            }
        ):
            owner = node.func.value.id
            method = node.func.attr
            argv = self.scope.literal_argv.get(owner)
            mapping = self.scope.literal_dicts.get(owner)
            new_argv: list[str | None] | None = None
            new_mapping: dict[str, ast.AST] | None = None
            if argv is not None:
                new_argv = list(argv)
                try:
                    if method == "clear":
                        new_argv.clear()
                    elif method == "pop" and (not node.args or literal_integer(node.args[0]) is not None):
                        new_argv.pop(literal_integer(node.args[0]) if node.args else -1)
                    elif method == "append" and node.args:
                        new_argv.append(literal_string(node.args[0]))
                    elif method == "extend" and node.args and isinstance(node.args[0], (ast.List, ast.Tuple)):
                        new_argv.extend(literal_string(item) for item in node.args[0].elts)
                    elif method == "remove" and node.args:
                        new_argv.remove(literal_string(node.args[0]))
                    elif method == "insert" and len(node.args) >= 2 and literal_integer(node.args[0]) is not None:
                        new_argv.insert(literal_integer(node.args[0]) or 0, literal_string(node.args[1]))
                    elif method == "reverse":
                        new_argv.reverse()
                    elif method == "sort":
                        if all(isinstance(item, str) for item in new_argv):
                            new_argv.sort()
                        else:
                            new_argv = None
                    else:
                        new_argv = None
                except (IndexError, TypeError, ValueError):
                    new_argv = None
            if mapping is not None:
                new_mapping = dict(mapping)
                if method == "clear":
                    new_mapping.clear()
                elif method == "update" and node.args:
                    update = self.literal_dict(node.args[0])
                    new_mapping = {**new_mapping, **update} if update is not None else None
                elif method == "pop" and node.args and literal_string(node.args[0]) is not None:
                    new_mapping.pop(literal_string(node.args[0]) or "", None)
                elif method == "setdefault" and node.args and literal_string(node.args[0]) is not None:
                    new_mapping.setdefault(literal_string(node.args[0]) or "", node.args[1] if len(node.args) > 1 else ast.Constant(None))
                else:
                    new_mapping = None
            self.scope.literal_argv.pop(owner, None)
            self.scope.literal_dicts.pop(owner, None)
            self.scope.forbidden_argv.discard(owner)
            self.scope.unsafe_kwargs.discard(owner)
            if new_argv is not None:
                self.scope.literal_argv[owner] = new_argv
                if forbidden_python_words(new_argv):
                    self.scope.forbidden_argv.add(owner)
            if new_mapping is not None:
                self.scope.literal_dicts[owner] = new_mapping
                shell = new_mapping.get("shell")
                if shell is not None and not (isinstance(shell, ast.Constant) and shell.value is False):
                    self.scope.unsafe_kwargs.add(owner)
        if name == "tools.liveware_login":
            self.login = True
        if name == "tools.register_app":
            self.registration = True

        subprocess_call = self.is_subprocess_call(node)
        if subprocess_call:
            if node.args and isinstance(node.args[0], ast.Name) and node.args[0].id in self.scope.forbidden_argv:
                self.forbidden_operation = True
            for keyword in node.keywords:
                if keyword.arg == "shell" and not (
                    isinstance(keyword.value, ast.Constant) and keyword.value.value is False
                ):
                    self.unsafe_shell = True
                if keyword.arg is None:
                    if isinstance(keyword.value, ast.Name) and keyword.value.id in self.scope.unsafe_kwargs:
                        self.unsafe_shell = True
                    values = self.literal_dict(keyword.value)
                    if values is not None and "shell" in values:
                        value = values["shell"]
                        if not (isinstance(value, ast.Constant) and value.value is False):
                            self.unsafe_shell = True

        words = command_words(node, subprocess_call, self.scope.literal_argv)
        if subprocess_call or (isinstance(node.func, ast.Name) and node.func.id == "run_liveware"):
            if forbidden_python_words(words):
                self.forbidden_operation = True
            if isinstance(node.func, ast.Name) and node.func.id == "run_liveware" and contains_words(
                words, ("app", "create")
            ):
                if contains_words(words, ("--agent-type", "hermes")):
                    self.hermes_creation = True
                else:
                    self.unsafe_app_creation = True
            if words and isinstance(words[0], str) and shell_string_download(words[0]):
                self.forbidden_operation = True

        if name in {"os.environ.get", "os.getenv"}:
            key = literal_string(node.args[0]) if node.args else None
            if key and credential_name(key):
                self.credential_read = True

        if final_name == "mkdir":
            receiver = dotted_name(node.func.value) if isinstance(node.func, ast.Attribute) else None
            mode = next((literal_integer(item.value) for item in node.keywords if item.arg == "mode"), None)
            if receiver in {"STATE_ROOT", "STATE_ROOT.parent"}:
                self.scope.state_relevant = True
                if mode == 0o700:
                    self.scope.directory_modes.add(receiver)
                else:
                    self.scope.bad_state_mode = True
        if self.is_state_tempfile_call(node):
            self.scope.state_relevant = True
        if (
            name == "json.dump"
            and len(node.args) >= 2
            and isinstance(node.args[1], ast.Name)
            and node.args[1].id in self.scope.state_streams
        ):
            temp = self.scope.state_streams[node.args[1].id]
            self.scope.state_event += 1
            self.scope.state_dump_temps.add(temp)
            self.scope.dump_events[temp] = self.scope.state_event
            values = self.literal_dict(node.args[0])
            identity_ok = values is not None and all(
                isinstance(values.get(key), ast.Name) and values[key].id == expected
                for key, expected in {
                    "schema_version": "SCHEMA_VERSION",
                    "skill_name": "SKILL_NAME",
                    "app_name": "SKILL_NAME",
                }.items()
            )
            if identity_ok:
                self.scope.state_identity_temps.add(temp)
            else:
                self.scope.bad_state_identity_temps.add(temp)
        if name == "os.chmod" and len(node.args) >= 2:
            target = dotted_name(node.args[0])
            mode = literal_integer(node.args[1])
            if target in {"STATE_ROOT", "STATE_ROOT.parent"}:
                self.scope.state_relevant = True
                if mode == 0o700:
                    self.scope.directory_modes.add(target)
                else:
                    self.scope.bad_state_mode = True
            temp = self.scope.state_temps.get(target or "")
            if temp is not None:
                self.scope.state_event += 1
                if mode == 0o600:
                    self.scope.file_mode_temps.add(temp)
                    self.scope.file_mode_events[temp] = self.scope.state_event
                else:
                    self.scope.bad_file_mode_temps.add(temp)
        if name == "os.replace" and len(node.args) >= 2:
            temp = self.scope.state_temps.get(dotted_name(node.args[0]) or "")
            if temp is not None and dotted_name(node.args[1]) == "STATE_FILE":
                self.scope.state_relevant = True
                self.scope.state_event += 1
                self.scope.atomic_replace_temps.add(temp)
                self.scope.replace_events[temp] = self.scope.state_event
        self.generic_visit(node)

    @property
    def state_persistence_ok(self) -> bool:
        return (
            self.state_writer_seen
            and self.stable_state_identity
            and not self.invalid_state_writer
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
        match = re.search(
            r"(?<!<)<<-?(?!<)\s*(?:'([^'\n]+)'|\"([^\"\n]+)\"|([^\s;&|()<>]+))",
            line,
        )
        if match is None:
            index += 1
            continue
        delimiter = next(group for group in match.groups() if group is not None)
        body: list[str] = []
        index += 1
        while index < len(lines) and lines[index].strip() != delimiter:
            body.append(lines[index])
            index += 1
        introducer = strip_shell_comment(line[: match.start()]).lstrip()
        python_command = re.search(
            r"(?:^|[;&|()]|\$\()\s*(?:env(?:\s+[A-Za-z_][A-Za-z0-9_]*=[^\s]+)*\s+)?"
            r"(?:command\s+)?(?:[^\s/]+/)?python(?:3)?\b",
            introducer,
        )
        if python_command is not None and re.search(r"(?:^|\s)-(?=\s|$)", introducer[python_command.end() :]):
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


def shell_variable(token: str) -> str | None:
    match = re.fullmatch(r"\$\{?([A-Za-z_][A-Za-z0-9_]*)\}?", token)
    return match.group(1) if match is not None else None


def resolve_shell_token(token: str, variables: dict[str, str]) -> str:
    name = shell_variable(token)
    return variables.get(name, token) if name is not None else token


def invokes_setup_segment(segment: list[str], variables: dict[str, str]) -> bool:
    command, arguments = command_head(segment)
    command = resolve_shell_token(command, variables)
    arguments = [resolve_shell_token(item, variables) for item in arguments]
    if command.rstrip("/ ").endswith("setup.py"):
        return True
    return command in {"python", "python3", "bash", "sh", "source", "."} and any(
        item.rstrip("/ ").endswith("setup.py") for item in arguments
    )


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


def shell_flow(tokens_by_line: list[list[str]]) -> tuple[bool, bool]:
    variables: dict[str, str] = {}
    owned: set[str] = set()
    setup = False
    unsafe = False
    for tokens in tokens_by_line:
        for segment in command_segments(tokens):
            command, _ = command_head(segment)
            if not command:
                for token in segment:
                    assignment = re.fullmatch(r"([A-Za-z_][A-Za-z0-9_]*)=(.*)", token)
                    if assignment is None:
                        continue
                    name, value = assignment.groups()
                    variables[name] = value
                    if value == "$!":
                        owned.add(name)
                    else:
                        owned.discard(name)
            setup = setup or invokes_setup_segment(segment, variables)
            unsafe = unsafe or unsafe_kill(segment, owned)
    return setup, unsafe


def direct_credential_read(tokens: list[str]) -> bool:
    for segment in command_segments(tokens):
        command, arguments = command_head(segment)
        if command == "printenv" and any(not item.startswith("-") and credential_name(item) for item in arguments):
            return True
    return False


def shell_line_reads_state(line: str, tokens: list[str]) -> bool:
    if "STATE_FILE" not in shell_expansions(line):
        return False
    return any(command_head(segment)[0] for segment in command_segments(tokens))


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
        1 for line, tokens in zip(code_lines, tokens_by_line) if shell_line_reads_state(line, tokens)
    )
    if state_values != [standard_state] or state_reads < 1:
        add(findings, "LW003", START_PATH, "Start does not read the standard state file.")

    invokes_setup, unsafe_shell_kill = shell_flow(tokens_by_line)
    if invokes_setup:
        add(findings, "LW008", START_PATH, "Start invokes setup instead of requiring existing state.")

    python_kill = False
    python_forbidden = False
    python_credential = False
    for body in python_bodies:
        kills, forbidden, credential = python_body_facts(body)
        python_kill = python_kill or kills
        python_forbidden = python_forbidden or forbidden
        python_credential = python_credential or credential
    if python_kill or unsafe_shell_kill:
        add(findings, "LW010", START_PATH, "Start can terminate a process it cannot prove it owns.")

    if python_forbidden or any(shell_forbidden(tokens) for tokens in tokens_by_line):
        add(findings, "LW011", SCRIPTS_PATH, "Scripts contain a forbidden install, download, or app deletion operation.")

    if (
        python_credential
        or any(credential_name(name) for line in code_lines for name in shell_expansions(line))
        or any(direct_credential_read(tokens) for tokens in tokens_by_line)
    ):
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
        for segment in command_segments(tokens):
            if not segment or segment[0] not in {"$LIVEWARE_BIN", "${LIVEWARE_BIN}"}:
                continue
            arguments = segment[1:]
            if len(arguments) >= 2 and arguments[0] == "tunnel" and arguments[1] in {"bind", "bind-static"}:
                binding_commands.append((arguments[1], arguments[2:]))
    binding_ok = len(binding_commands) == 1
    if binding_ok and binding_commands[0][0] == "bind":
        arguments = binding_commands[0][1]
        binding_ok = (
            len(arguments) == 2
            and arguments[0] in {"$APP_ID", "${APP_ID}"}
            and re.fullmatch(r"http://127\.0\.0\.1:[^/\s]+(?:/[^\s]*)?", arguments[1]) is not None
        )
    elif binding_ok:
        arguments = binding_commands[0][1]
        binding_ok = len(arguments) == 2 and arguments[0] in {"$APP_ID", "${APP_ID}"}
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
