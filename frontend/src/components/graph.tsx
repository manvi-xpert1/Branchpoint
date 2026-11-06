import { Handle, MarkerType, Position, type Edge, type Node, type NodeProps } from "@xyflow/react";
import type { ComponentDef, DependencyDef, Status } from "../api/types";
import { kindOf } from "../lib/catalog";
import type { Point } from "../lib/layout";

export interface ComponentNodeData extends Record<string, unknown> {
  component: ComponentDef;
  status?: Status;
  /** Extra CSS classes: "blast", "cycle", "chain" ... */
  flags?: string[];
}

export type ComponentNodeType = Node<ComponentNodeData, "component">;

function fmtLoad(attrs: Record<string, unknown>): string | null {
  const cap = attrs.capacity;
  const load = attrs.current_load;
  if (typeof cap !== "number") return null;
  return typeof load === "number" ? `${load}/${cap} rps` : `cap ${cap}`;
}

export function ComponentNode({ data, selected }: NodeProps<ComponentNodeType>) {
  const { component: c, status, flags = [] } = data;
  const kind = kindOf(c.type);
  const load = fmtLoad(c.attributes);
  const classes = ["node", status ?? "", selected ? "selected" : "", ...flags].join(" ");
  return (
    <div className={classes} data-testid={`node-${c.id}`} data-status={status}>
      {/* Edges arrive at the top (this component is depended on) ... */}
      <Handle type="target" position={Position.Top} />
      <div className="head">
        <div className="badge" style={{ background: kind.color }}>{kind.short}</div>
        <div style={{ minWidth: 0 }}>
          <div className="title" title={c.name ?? c.id}>
            {c.entry_point && <span className="star" title="Entry point">★ </span>}
            {c.name ?? c.id}
          </div>
          <div className="sub">{kind.label}</div>
        </div>
      </div>
      <div className="meta">
        <span>{load ?? " "}</span>
        {status && <span style={{ color: `var(--${status === "healthy" ? "ok" : status === "degraded" ? "warn" : "bad"})`, fontWeight: 600 }}>{status}</span>}
      </div>
      {/* ... and leave from the bottom (this component depends on others). */}
      <Handle type="source" position={Position.Bottom} />
    </div>
  );
}

export const nodeTypes = { component: ComponentNode };

export function depId(d: DependencyDef): string {
  return d.id ?? `${d.source_id}->${d.target_id}`;
}

const EDGE_STYLE: Record<string, React.CSSProperties> = {
  requires: { stroke: "#64748b", strokeWidth: 2 },
  optional: { stroke: "#94a3b8", strokeWidth: 2, strokeDasharray: "6 4" },
  fallback: { stroke: "#f59e0b", strokeWidth: 2, strokeDasharray: "2 4" },
};

export function edgeLabel(d: DependencyDef): string {
  const parts: string[] = [];
  if (d.dependency_type !== "requires") parts.push(d.dependency_type);
  if (d.group) parts.push(`[${d.group}]`);
  if (d.propagation_delay) parts.push(`delay ${d.propagation_delay}`);
  return parts.join(" ");
}

export function buildNodes(
  components: ComponentDef[],
  positions: Record<string, Point>,
  opts: { selectedId?: string | null; status?: Record<string, Status>; flags?: Record<string, string[]> } = {},
): ComponentNodeType[] {
  return components.map((c) => ({
    id: c.id,
    type: "component",
    position: positions[c.id] ?? { x: 0, y: 0 },
    selected: opts.selectedId === c.id,
    data: { component: c, status: opts.status?.[c.id], flags: opts.flags?.[c.id] },
  }));
}

export function buildEdges(
  deps: DependencyDef[],
  opts: { selectedId?: string | null; status?: Record<string, Status>; highlight?: Set<string> } = {},
): Edge[] {
  return deps.map((d) => {
    const id = depId(d);
    const base = EDGE_STYLE[d.dependency_type] ?? EDGE_STYLE.requires;
    const targetStatus = opts.status?.[d.target_id];
    const broken = targetStatus === "failed" || targetStatus === "degraded";
    const color = targetStatus === "failed" ? "#dc2626" : targetStatus === "degraded" ? "#d97706" : base.stroke;
    const selected = opts.selectedId === id;
    const highlighted = opts.highlight?.has(id);
    return {
      id,
      source: d.source_id,
      target: d.target_id,
      label: edgeLabel(d) || undefined,
      selected,
      animated: broken,
      style: {
        ...base,
        stroke: selected ? "#2563eb" : highlighted ? "#2563eb" : color,
        strokeWidth: selected || highlighted ? 3 : base.strokeWidth,
      },
      markerEnd: { type: MarkerType.ArrowClosed, color: selected || highlighted ? "#2563eb" : (color as string) },
      labelStyle: { fontSize: 11, fill: "#475569" },
    };
  });
}

export function Legend() {
  return (
    <div className="legend">
      <span><svg width="26" height="6"><line x1="0" y1="3" x2="26" y2="3" style={EDGE_STYLE.requires} /></svg>requires</span>
      <span><svg width="26" height="6"><line x1="0" y1="3" x2="26" y2="3" style={EDGE_STYLE.optional} /></svg>optional</span>
      <span><svg width="26" height="6"><line x1="0" y1="3" x2="26" y2="3" style={EDGE_STYLE.fallback} /></svg>fallback</span>
      <span className="muted">arrow points at the dependency</span>
    </div>
  );
}
