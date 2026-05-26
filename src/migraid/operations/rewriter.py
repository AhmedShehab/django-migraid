"""libcst-based migration file rewriter.

Preserves all formatting, comments, and whitespace — no noisy diffs.
"""

from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING, cast

import libcst as cst

if TYPE_CHECKING:
    from libcst.metadata import MetadataWrapper  # noqa: F401


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


def _detect_quote_char(node: cst.Element) -> str:
    if isinstance(node.value, cst.SimpleString):
        stripped = node.value.value.lstrip("rRbBuU")
        return "'" if stripped.startswith("'") else '"'
    return '"'


class DependencyTransformer(cst.CSTTransformer):
    """Replace dependency tuples matching `replacements` keys with their values.

    Only operates on the `dependencies`, `run_before`, and `replaces` attributes
    of the `Migration` class.
    """

    def __init__(self, replacements: dict[tuple[str, str], tuple[str, str]]) -> None:
        super().__init__()
        self.replacements = replacements
        self._class_stack: list[str] = []
        self._in_dep_list = False

    def visit_ClassDef(self, node: cst.ClassDef) -> bool | None:
        self._class_stack.append(node.name.value)
        return True

    def leave_ClassDef(
        self, original_node: cst.ClassDef, updated_node: cst.ClassDef
    ) -> cst.BaseStatement | cst.FlattenSentinel[cst.BaseStatement] | cst.RemovalSentinel:
        if self._class_stack and self._class_stack[-1] == original_node.name.value:
            self._class_stack.pop()
        return updated_node

    def visit_Assign(self, node: cst.Assign) -> bool | None:
        in_migration = bool(self._class_stack) and self._class_stack[-1] == "Migration"
        if not in_migration:
            return True
        for target in node.targets:
            if isinstance(target.target, cst.Name) and target.target.value in (
                "dependencies",
                "run_before",
                "replaces",
            ):
                self._in_dep_list = True
                break
        return True

    def leave_Assign(
        self, original_node: cst.Assign, updated_node: cst.Assign
    ) -> cst.BaseSmallStatement:
        self._in_dep_list = False
        return updated_node

    def leave_Tuple(self, original_node: cst.Tuple, updated_node: cst.Tuple) -> cst.BaseExpression:
        if not self._in_dep_list or not self.replacements:
            return updated_node

        elements = [e for e in updated_node.elements if not isinstance(e, cst.StarredElement)]
        if len(elements) != 2:
            return updated_node

        s0 = _extract_string(elements[0].value)
        s1 = _extract_string(elements[1].value)
        if s0 is None or s1 is None:
            return updated_node

        dep = (s0, s1)
        if dep not in self.replacements:
            return updated_node

        new_dep = self.replacements[dep]
        quote_char = _detect_quote_char(cast(cst.Element, elements[0]))

        new_elements = list(updated_node.elements)
        idx0 = next(
            i for i, e in enumerate(updated_node.elements) if not isinstance(e, cst.StarredElement)
        )
        idx1 = next(
            i
            for i, e in enumerate(updated_node.elements)
            if not isinstance(e, cst.StarredElement) and i > idx0
        )

        new_elements[idx0] = elements[0].with_changes(
            value=cst.SimpleString(f"{quote_char}{new_dep[0]}{quote_char}")
        )
        new_elements[idx1] = elements[1].with_changes(
            value=cst.SimpleString(f"{quote_char}{new_dep[1]}{quote_char}")
        )

        return updated_node.with_changes(elements=new_elements)


def rewrite_dependencies_in_source(
    source: str,
    replacements: dict[tuple[str, str], tuple[str, str]],
) -> str:
    if not replacements:
        return source
    tree = cst.parse_module(source)
    transformer = DependencyTransformer(replacements)
    new_tree = tree.visit(transformer)
    return new_tree.code


def rewrite_dependencies(
    path: Path,
    replacements: dict[tuple[str, str], tuple[str, str]],
) -> str:
    source = path.read_text(encoding="utf-8")
    return rewrite_dependencies_in_source(source, replacements)
