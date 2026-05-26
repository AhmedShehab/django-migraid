"""DAG utilities over the static MigrationNode graph."""

from __future__ import annotations

from collections import deque

from .scanner import MigrationNode


def leaf_nodes(nodes: dict[tuple[str, str], MigrationNode], app: str) -> list[MigrationNode]:
    """Nodes with no in-app dependents (current migration heads)."""
    app_keys = {k for k in nodes if k[0] == app}
    has_dependent: set[tuple[str, str]] = set()
    for key in app_keys:
        node = nodes[key]
        for dep in node.dependencies:
            if dep in app_keys:
                has_dependent.add(dep)
    return sorted([nodes[k] for k in app_keys if k not in has_dependent], key=lambda n: n.key)


def root_nodes(nodes: dict[tuple[str, str], MigrationNode], app: str) -> list[MigrationNode]:
    """Nodes with no in-app dependencies (migration starting points)."""
    app_keys = {k for k in nodes if k[0] == app}
    roots = []
    for key in app_keys:
        node = nodes[key]
        in_app_deps = [d for d in node.dependencies if d in app_keys]
        if not in_app_deps:
            roots.append(node)
    return sorted(roots, key=lambda n: n.key)


def topological_sort(nodes: dict[tuple[str, str], MigrationNode], app: str) -> list[MigrationNode]:
    """Return migrations for an app in dependency order (Kahn's algorithm)."""
    app_keys = [k for k in nodes if k[0] == app]

    adj: dict[tuple[str, str], list[tuple[str, str]]] = {k: [] for k in app_keys}
    in_degree: dict[tuple[str, str], int] = {k: 0 for k in app_keys}

    for key in app_keys:
        for dep in nodes[key].dependencies:
            if dep in adj:
                adj[dep].append(key)
                in_degree[key] += 1

    queue: deque[tuple[str, str]] = deque(sorted(k for k in app_keys if in_degree[k] == 0))
    result: list[MigrationNode] = []

    while queue:
        k = queue.popleft()
        result.append(nodes[k])
        for child in sorted(adj[k]):
            in_degree[child] -= 1
            if in_degree[child] == 0:
                queue.append(child)
                # Keep deque sorted for determinism
                queue = deque(sorted(queue))

    return result


def detect_cycles(
    nodes: dict[tuple[str, str], MigrationNode],
) -> list[list[tuple[str, str]]]:
    """DFS cycle detection. Returns list of cycles (each a list of keys)."""
    # Build forward adjacency: dep → dependent
    adj: dict[tuple[str, str], list[tuple[str, str]]] = {k: [] for k in nodes}
    for key, node in nodes.items():
        for dep in node.dependencies:
            if dep in adj:
                adj[dep].append(key)

    WHITE, GRAY, BLACK = 0, 1, 2
    color: dict[tuple[str, str], int] = {k: WHITE for k in nodes}
    parent: dict[tuple[str, str], tuple[str, str]] = {}
    cycles: list[list[tuple[str, str]]] = []

    def dfs(v: tuple[str, str]) -> None:
        color[v] = GRAY
        for w in sorted(adj.get(v, [])):
            if color[w] == GRAY:
                cycle: list[tuple[str, str]] = [w]
                curr = v
                while curr != w:
                    cycle.append(curr)
                    curr = parent.get(curr, w)
                cycles.append(list(reversed(cycle)))
            elif color[w] == WHITE:
                parent[w] = v
                dfs(w)
        color[v] = BLACK

    for k in sorted(nodes.keys()):
        if color[k] == WHITE:
            dfs(k)

    return cycles


def dangling_dependencies(
    nodes: dict[tuple[str, str], MigrationNode],
) -> list[tuple[MigrationNode, tuple[str, str]]]:
    """Return (node, missing_dep) pairs where a dependency doesn't exist on disk."""
    result: list[tuple[MigrationNode, tuple[str, str]]] = []
    all_keys = set(nodes.keys())
    for node in nodes.values():
        for dep in node.dependencies:
            if dep not in all_keys:
                result.append((node, dep))
    return result


def cross_app_dependencies(
    nodes: dict[tuple[str, str], MigrationNode], app: str
) -> dict[tuple[str, str], list[tuple[str, str]]]:
    """Map each app migration to its cross-app dependencies."""
    result: dict[tuple[str, str], list[tuple[str, str]]] = {}
    for key, node in nodes.items():
        if key[0] != app:
            continue
        cross = [d for d in node.dependencies if d[0] != app]
        if cross:
            result[key] = cross
    return result


def find_highest_number(
    nodes: dict[tuple[str, str], MigrationNode],
    app: str,
    exclude_keys: set[tuple[str, str]] | None = None,
) -> int:
    """Return the highest numeric prefix among app migrations (excluding given keys)."""
    exclude = exclude_keys or set()
    numbers = [
        node.number
        for key, node in nodes.items()
        if key[0] == app and key not in exclude and node.number is not None
    ]
    return max(numbers, default=0)
