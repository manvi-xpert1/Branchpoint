import type { ComponentDef, DependencyDef } from "../api/types";

export interface Point { x: number; y: number }

const COL = 230;
const ROW = 150;

/**
 * Layered layout: components nobody depends on (entry points) go on top,
 * and each component sits one row below the deepest component that
 * depends on it. Dependencies therefore always point downwards.
 * Cycles are tolerated: a node is never pushed down twice along one path.
 */
export function layeredLayout(components: ComponentDef[], deps: DependencyDef[]): Record<string, Point> {
  const ids = components.map((c) => c.id);
  const known = new Set(ids);
  const dependsOn = new Map<string, string[]>(ids.map((id) => [id, []]));
  const hasDependents = new Set<string>();
  for (const d of deps) {
    if (!known.has(d.source_id) || !known.has(d.target_id)) continue;
    dependsOn.get(d.source_id)!.push(d.target_id);
    hasDependents.add(d.target_id);
  }

  const level = new Map<string, number>();
  const visit = (id: string, depth: number, path: Set<string>) => {
    if (path.has(id)) return; // cycle
    if ((level.get(id) ?? -1) >= depth) return;
    level.set(id, depth);
    path.add(id);
    for (const t of dependsOn.get(id)!) visit(t, depth + 1, path);
    path.delete(id);
  };
  const roots = ids.filter((id) => !hasDependents.has(id));
  for (const r of roots.length ? roots : ids.slice(0, 1)) visit(r, 0, new Set());
  for (const id of ids) if (!level.has(id)) visit(id, 0, new Set()); // pure cycles

  const rows = new Map<number, string[]>();
  for (const id of ids) {
    const l = level.get(id)!;
    rows.set(l, [...(rows.get(l) ?? []), id]);
  }
  const widest = Math.max(1, ...[...rows.values()].map((r) => r.length));
  const out: Record<string, Point> = {};
  for (const [l, row] of rows) {
    const offset = ((widest - row.length) * COL) / 2;
    row.forEach((id, i) => (out[id] = { x: offset + i * COL, y: l * ROW }));
  }
  return out;
}

/** Use saved positions where present; lay out everything else. */
export function positionsFor(
  components: ComponentDef[],
  deps: DependencyDef[],
  saved: Record<string, Point | null | undefined> = {},
): Record<string, Point> {
  const auto = layeredLayout(components, deps);
  const out: Record<string, Point> = {};
  for (const c of components) out[c.id] = saved[c.id] ?? c.layout ?? auto[c.id];
  return out;
}

const NODE_W = 170;
const NODE_H = 80;

/** First position near `start` that does not overlap an existing node. */
export function freeSpot(start: Point, taken: Point[]): Point {
  const overlaps = (p: Point) =>
    taken.some((q) => Math.abs(q.x - p.x) < NODE_W + 20 && Math.abs(q.y - p.y) < NODE_H + 20);
  // Search outward in rings of candidate offsets.
  for (let ring = 0; ring < 12; ring++) {
    for (const [dx, dy] of [[1, 0], [0, 1], [-1, 0], [0, -1], [1, 1], [-1, 1], [1, -1], [-1, -1]]) {
      const p = { x: Math.round(start.x + dx * ring * (NODE_W + 30)), y: Math.round(start.y + dy * ring * (NODE_H + 30)) };
      if (!overlaps(p)) return p;
    }
  }
  return start;
}
