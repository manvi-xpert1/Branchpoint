"""Graph algorithms, implemented by hand rather than with NetworkX.

Each component is a node. A dependency ``source -> target`` means
"source depends on target". For propagation the useful direction is the
reverse: when a target breaks, we need to know who depends on it, so we
keep both adjacency maps.
"""

from __future__ import annotations

from collections import deque

from ..models import Dependency, System


class DependencyGraph:
    def __init__(self, system: System) -> None:
        self.nodes: list[str] = list(system.components)
        # component -> dependencies it relies on (outgoing edges)
        self.depends_on: dict[str, list[Dependency]] = {n: [] for n in self.nodes}
        # component -> dependencies that point AT it (incoming edges)
        self.dependents: dict[str, list[Dependency]] = {n: [] for n in self.nodes}
        for dep in system.dependencies:
            self.depends_on[dep.source_id].append(dep)
            self.dependents[dep.target_id].append(dep)

    # ---- traversal ----------------------------------------------------
    def impact_bfs(self, start: str) -> dict[str, int]:
        """Every component that could be affected if ``start`` breaks.

        Returns {component_id: distance in hops}. Uses BFS, so components
        are discovered level by level (direct dependents first).
        This is the *possible* blast radius; the actual effect depends on
        rules such as fallbacks and optional dependencies.
        """
        distances = {start: 0}
        queue = deque([start])
        while queue:
            node = queue.popleft()
            for dep in self.dependents[node]:
                if dep.source_id not in distances:
                    distances[dep.source_id] = distances[node] + 1
                    queue.append(dep.source_id)
        return distances

    def find_cycle(self) -> list[str] | None:
        """Return one dependency cycle as a list of ids, or None.

        Iterative DFS with three colours: white (unvisited), grey (on the
        current path), black (done). Reaching a grey node means a cycle.
        """
        WHITE, GREY, BLACK = 0, 1, 2
        colour = {n: WHITE for n in self.nodes}
        parent: dict[str, str | None] = {}

        for root in self.nodes:
            if colour[root] != WHITE:
                continue
            parent[root] = None
            # stack holds (node, iterator over its outgoing edges)
            stack = [(root, iter(self.depends_on[root]))]
            colour[root] = GREY
            while stack:
                node, edges = stack[-1]
                for dep in edges:
                    nxt = dep.target_id
                    if colour[nxt] == WHITE:
                        colour[nxt] = GREY
                        parent[nxt] = node
                        stack.append((nxt, iter(self.depends_on[nxt])))
                        break
                    if colour[nxt] == GREY:  # back edge: rebuild the cycle
                        cycle = [nxt]
                        cur: str | None = node
                        while cur is not None and cur != nxt:
                            cycle.append(cur)
                            cur = parent[cur]
                        cycle.append(nxt)
                        return list(reversed(cycle))
                else:  # no more edges: node is finished
                    colour[node] = BLACK
                    stack.pop()
        return None

    def topological_order(self) -> list[str]:
        """Order components so each comes after everything it depends on.

        Kahn's algorithm. Raises ValueError if the graph has a cycle.
        """
        remaining = {n: len(self.depends_on[n]) for n in self.nodes}
        ready = deque(n for n in self.nodes if remaining[n] == 0)
        order: list[str] = []
        while ready:
            node = ready.popleft()
            order.append(node)
            for dep in self.dependents[node]:
                remaining[dep.source_id] -= 1
                if remaining[dep.source_id] == 0:
                    ready.append(dep.source_id)
        if len(order) != len(self.nodes):
            raise ValueError(f"Graph has a cycle: {' -> '.join(self.find_cycle() or [])}")
        return order
