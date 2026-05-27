"""libcst-based migration file rewriter.

Preserves all formatting, comments, and whitespace — no noisy diffs.
"""

from __future__ import annotations

from collections.abc import Sequence
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


# ---------------------------------------------------------------------------
# Linearize: collapse a migration's in-app dependencies to a single predecessor
# ---------------------------------------------------------------------------


def _element_key(element: cst.BaseElement) -> tuple[str, str] | None:
    """Return the (app, name) tuple an element holds, or None if it isn't one."""
    if isinstance(element, cst.StarredElement):
        return None
    value = element.value
    if not isinstance(value, cst.Tuple):
        return None
    inner = [e for e in value.elements if not isinstance(e, cst.StarredElement)]
    if len(inner) != 2:
        return None
    s0 = _extract_string(inner[0].value)
    s1 = _extract_string(inner[1].value)
    if s0 is None or s1 is None:
        return None
    return (s0, s1)


def _set_element_key(element: cst.Element, new_key: tuple[str, str]) -> cst.Element:
    """Rewrite the two strings inside a dependency tuple, preserving quote style."""
    tup = cast(cst.Tuple, element.value)
    elements = list(tup.elements)
    idxs = [i for i, e in enumerate(elements) if not isinstance(e, cst.StarredElement)]
    i0, i1 = idxs[0], idxs[1]
    quote = _detect_quote_char(cast(cst.Element, elements[i0]))
    elements[i0] = elements[i0].with_changes(value=cst.SimpleString(f"{quote}{new_key[0]}{quote}"))
    elements[i1] = elements[i1].with_changes(value=cst.SimpleString(f"{quote}{new_key[1]}{quote}"))
    return element.with_changes(value=tup.with_changes(elements=elements))


class LinearizeTransformer(cst.CSTTransformer):
    """Rewrite a single migration so its in-app deps collapse to one predecessor.

    - ``dependencies``: keep exactly one in-app entry pointing at ``predecessor``
      (swapping an existing in-app tuple in place, or inserting one if none
      existed), drop any extra in-app tuples, and keep cross-app tuples (rewritten
      through ``rename_map`` so a sibling app's renames are followed). With
      ``strip_cross_app`` the cross-app tuples are dropped too.
    - ``run_before`` / ``replaces``: tuples are only swapped through ``rename_map``
      (the linearize command bans in-app ``run_before`` upstream, so these are
      cross-app or squash references that must merely follow renames).
    """

    def __init__(
        self,
        app_label: str,
        predecessor: tuple[str, str] | None,
        rename_map: dict[tuple[str, str], tuple[str, str]],
        *,
        strip_cross_app: bool = False,
    ) -> None:
        super().__init__()
        self.app_label = app_label
        self.predecessor = predecessor
        self.rename_map = rename_map
        self.strip_cross_app = strip_cross_app
        self._class_stack: list[str] = []
        self._current_attr: str | None = None

    def visit_ClassDef(self, node: cst.ClassDef) -> bool | None:
        self._class_stack.append(node.name.value)
        return True

    def leave_ClassDef(
        self, original_node: cst.ClassDef, updated_node: cst.ClassDef
    ) -> cst.BaseStatement:
        if self._class_stack and self._class_stack[-1] == original_node.name.value:
            self._class_stack.pop()
        return updated_node

    def visit_Assign(self, node: cst.Assign) -> bool | None:
        self._current_attr = None
        in_migration = bool(self._class_stack) and self._class_stack[-1] == "Migration"
        if in_migration:
            for target in node.targets:
                if isinstance(target.target, cst.Name) and target.target.value in (
                    "dependencies",
                    "run_before",
                    "replaces",
                ):
                    self._current_attr = target.target.value
                    break
        return True

    def leave_Assign(
        self, original_node: cst.Assign, updated_node: cst.Assign
    ) -> cst.BaseSmallStatement:
        attr = self._current_attr
        self._current_attr = None
        if attr is None or not isinstance(updated_node.value, cst.List):
            return updated_node
        if attr == "dependencies":
            new_list = self._rebuild_dependencies(updated_node.value)
        else:
            new_list = self._swap_only(updated_node.value)
        return updated_node.with_changes(value=new_list)

    def _swap_only(self, list_node: cst.List) -> cst.List:
        new_elements: list[cst.BaseElement] = []
        for element in list_node.elements:
            key = _element_key(element)
            if key is not None and key in self.rename_map:
                new_elements.append(
                    _set_element_key(cast(cst.Element, element), self.rename_map[key])
                )
            else:
                new_elements.append(element)
        return list_node.with_changes(elements=new_elements)

    def _rebuild_dependencies(self, list_node: cst.List) -> cst.List:
        original = list(list_node.elements)
        new_elements: list[cst.BaseElement] = []
        in_app_used = False

        for element in original:
            key = _element_key(element)
            if key is None:
                new_elements.append(element)  # starred / unparseable — leave alone
                continue
            if key[0] == self.app_label:
                if self.predecessor is not None and not in_app_used:
                    new_elements.append(
                        _set_element_key(cast(cst.Element, element), self.predecessor)
                    )
                    in_app_used = True
                # extra in-app tuples (or no predecessor at all) are dropped
            elif not self.strip_cross_app:
                new_key = self.rename_map.get(key, key)
                if new_key != key:
                    new_elements.append(_set_element_key(cast(cst.Element, element), new_key))
                else:
                    new_elements.append(element)

        if self.predecessor is not None and not in_app_used:
            new_elements.append(self._make_element(self.predecessor, original))

        # Only fix up commas when the element count changed (drop/insert); pure
        # swaps keep their original byte-for-byte layout.
        if len(new_elements) != len(original):
            new_elements = self._normalize_commas(new_elements, original)
        return list_node.with_changes(elements=new_elements)

    @staticmethod
    def _make_element(
        key: tuple[str, str], template_elements: Sequence[cst.BaseElement]
    ) -> cst.Element:
        """Build a fresh ``("app", "name")`` element, copying a sibling's layout."""
        template: cst.Element | None = None
        for tmpl in template_elements:
            if isinstance(tmpl, cst.Element) and _element_key(tmpl) is not None:
                template = tmpl
                break
        quote = '"'
        if template is not None:
            inner = cast(cst.Tuple, template.value).elements
            quote = _detect_quote_char(cast(cst.Element, inner[0]))
        tup = cst.Tuple(
            elements=[
                cst.Element(cst.SimpleString(f"{quote}{key[0]}{quote}")),
                cst.Element(cst.SimpleString(f"{quote}{key[1]}{quote}")),
            ]
        )
        if template is not None:
            return template.with_changes(value=tup)
        return cst.Element(value=tup)

    @staticmethod
    def _normalize_commas(
        elements: list[cst.BaseElement], original: list[cst.BaseElement]
    ) -> list[cst.BaseElement]:
        """Keep commas valid after a drop/insert and preserve the list's layout.

        Non-final elements must carry a comma; the final element inherits the
        *original* last element's comma, so a multi-line list keeps its trailing
        comma + newline-before-``]`` (and a single-line one keeps none).
        """
        if not elements:
            return elements
        last_comma: cst.Comma | cst.MaybeSentinel = (
            original[-1].comma if original else cst.MaybeSentinel.DEFAULT
        )
        fixed: list[cst.BaseElement] = []
        last = len(elements) - 1
        for i, element in enumerate(elements):
            if i == last:
                fixed.append(element.with_changes(comma=last_comma))
            elif isinstance(element.comma, cst.Comma):
                fixed.append(element)
            else:
                fixed.append(
                    element.with_changes(
                        comma=cst.Comma(whitespace_after=cst.SimpleWhitespace(" "))
                    )
                )
        return fixed


def linearize_dependencies_in_source(
    source: str,
    app_label: str,
    predecessor: tuple[str, str] | None,
    rename_map: dict[tuple[str, str], tuple[str, str]],
    *,
    strip_cross_app: bool = False,
) -> str:
    tree = cst.parse_module(source)
    transformer = LinearizeTransformer(
        app_label, predecessor, rename_map, strip_cross_app=strip_cross_app
    )
    return tree.visit(transformer).code


def linearize_dependencies(
    path: Path,
    app_label: str,
    predecessor: tuple[str, str] | None,
    rename_map: dict[tuple[str, str], tuple[str, str]],
    *,
    strip_cross_app: bool = False,
) -> str:
    source = path.read_text(encoding="utf-8")
    return linearize_dependencies_in_source(
        source, app_label, predecessor, rename_map, strip_cross_app=strip_cross_app
    )
