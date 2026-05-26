"""Tier 1: static libcst-based migration file scanner.

Parses migration files without importing them — works on broken/mid-rebase repos.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path

import libcst as cst


@dataclass
class OperationInfo:
    name: str
    has_reverse: bool = False


@dataclass
class MigrationNode:
    app_label: str
    name: str
    path: Path
    dependencies: list[tuple[str, str]] = field(default_factory=list)
    run_before: list[tuple[str, str]] = field(default_factory=list)
    replaces: list[tuple[str, str]] = field(default_factory=list)
    initial: bool = False
    operations: list[OperationInfo] = field(default_factory=list)

    @property
    def key(self) -> tuple[str, str]:
        return (self.app_label, self.name)

    @property
    def number(self) -> int | None:
        m = re.match(r"^(\d+)", self.name)
        return int(m.group(1)) if m else None

    @property
    def name_suffix(self) -> str:
        m = re.match(r"^\d+_(.*)", self.name)
        return m.group(1) if m else self.name

    @property
    def is_merge_migration(self) -> bool:
        return "merge" in self.name_suffix.lower()


def _extract_string(node: cst.BaseExpression) -> str | None:
    if isinstance(node, cst.SimpleString):
        val = node.value
        stripped = val.lstrip("rRbBuU")
        if stripped.startswith('"""') or stripped.startswith("'''"):
            return stripped[3:-3]
        if stripped.startswith('"'):
            return stripped[1:-1]
        if stripped.startswith("'"):
            return stripped[1:-1]
    return None


def _extract_dep_tuple(node: cst.BaseExpression) -> tuple[str, str] | None:
    if not isinstance(node, cst.Tuple):
        return None
    elements = [e for e in node.elements if not isinstance(e, cst.StarredElement)]
    if len(elements) != 2:
        return None
    s0 = _extract_string(elements[0].value)
    s1 = _extract_string(elements[1].value)
    if s0 is None or s1 is None:
        return None
    return (s0, s1)


def _extract_dep_list(node: cst.BaseExpression) -> list[tuple[str, str]]:
    result: list[tuple[str, str]] = []
    if not isinstance(node, cst.List):
        return result
    for element in node.elements:
        if isinstance(element, cst.StarredElement):
            continue
        dep = _extract_dep_tuple(element.value)
        if dep is not None:
            result.append(dep)
    return result


def _has_reverse_arg(call: cst.Call, kwarg_name: str) -> bool:
    positional = [arg for arg in call.args if arg.keyword is None]
    if len(positional) >= 2:
        return True
    return any(
        arg.keyword is not None and arg.keyword.value == kwarg_name
        for arg in call.args
    )


def _extract_operations(node: cst.BaseExpression) -> list[OperationInfo]:
    result: list[OperationInfo] = []
    if not isinstance(node, cst.List):
        return result
    for element in node.elements:
        if isinstance(element, cst.StarredElement):
            continue
        val = element.value
        if not isinstance(val, cst.Call):
            continue
        func = val.func
        if isinstance(func, cst.Attribute):
            name = func.attr.value
        elif isinstance(func, cst.Name):
            name = func.value
        else:
            continue

        if name == "RunPython":
            result.append(
                OperationInfo(name=name, has_reverse=_has_reverse_arg(val, "reverse_code"))
            )
        elif name == "RunSQL":
            result.append(
                OperationInfo(name=name, has_reverse=_has_reverse_arg(val, "reverse_sql"))
            )
        else:
            result.append(OperationInfo(name=name, has_reverse=True))
    return result


class _MigrationVisitor(cst.CSTVisitor):
    def __init__(self) -> None:
        self._class_stack: list[str] = []
        self.dependencies: list[tuple[str, str]] = []
        self.run_before: list[tuple[str, str]] = []
        self.replaces: list[tuple[str, str]] = []
        self.initial: bool = False
        self.operations: list[OperationInfo] = []

    @property
    def _in_migration_class(self) -> bool:
        return bool(self._class_stack) and self._class_stack[-1] == "Migration"

    def visit_ClassDef(self, node: cst.ClassDef) -> bool | None:
        self._class_stack.append(node.name.value)
        return None

    def leave_ClassDef(self, node: cst.ClassDef) -> None:
        if self._class_stack and self._class_stack[-1] == node.name.value:
            self._class_stack.pop()

    def visit_Assign(self, node: cst.Assign) -> bool | None:
        if not self._in_migration_class:
            return None
        for target_node in node.targets:
            if not isinstance(target_node.target, cst.Name):
                continue
            attr = target_node.target.value
            if attr in ("dependencies", "run_before", "replaces"):
                parsed = _extract_dep_list(node.value)
                if attr == "dependencies":
                    self.dependencies = parsed
                elif attr == "run_before":
                    self.run_before = parsed
                else:
                    self.replaces = parsed
            elif attr == "initial":
                if isinstance(node.value, cst.Name):
                    self.initial = node.value.value == "True"
            elif attr == "operations":
                self.operations = _extract_operations(node.value)
        return None


def parse_migration_file(app_label: str, name: str, path: Path) -> MigrationNode | None:
    try:
        source = path.read_text(encoding="utf-8")
        tree = cst.parse_module(source)
        wrapper = cst.MetadataWrapper(tree)
        visitor = _MigrationVisitor()
        wrapper.visit(visitor)
        return MigrationNode(
            app_label=app_label,
            name=name,
            path=path,
            dependencies=visitor.dependencies,
            run_before=visitor.run_before,
            replaces=visitor.replaces,
            initial=visitor.initial,
            operations=visitor.operations,
        )
    except Exception:
        return None


def scan_app_migrations(app_label: str, migrations_dir: Path) -> list[MigrationNode]:
    nodes: list[MigrationNode] = []
    for path in sorted(migrations_dir.glob("*.py")):
        if path.name.startswith("__"):
            continue
        node = parse_migration_file(app_label, path.stem, path)
        if node is not None:
            nodes.append(node)
    return nodes


def scan_dirs(app_dirs: list[tuple[str, Path]]) -> dict[tuple[str, str], MigrationNode]:
    result: dict[tuple[str, str], MigrationNode] = {}
    for app_label, migrations_dir in app_dirs:
        for node in scan_app_migrations(app_label, migrations_dir):
            result[node.key] = node
    return result
