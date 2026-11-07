import { Handle, MarkerType, Position, type Edge, type Node, type NodeProps } from "@xyflow/react";
import type { ComponentDef, DependencyDef, DomainSpec, Status } from "../api/types";
import { componentSummary, entityType, hasFeature, relId } from "../lib/domains";
import type { Point } from "../lib/layout";

export interface ComponentNodeData extends Record<string, unknown> {
  component: ComponentDef;
  kind: { short: string; label: string; color: string };
  summary: string;
  status?: Status;
  /** Extra CSS classes: "blast", "cycle", "chain" ... */
  flags?: string[];
  showEntry: boolean;
  /** Flow domains read left to right: connections leave on the right and arrive on the left. */
  horizontal: boolean;
}

export type ComponentNodeType = Node<ComponentNodeData, "component">;

export function ComponentNode({ data, selected }: NodeProps<ComponentNodeType>) {
  const { component: c, kind, summary, status, flags = [], showEntry, horizontal } = data;
  const classes = ["node", status ?? "", selected ? "selected" : "", ...flags].join(" ");
  return (
    <div className={classes} data-testid={`node-${c.id}`} data-status={status}>
      <Handle type="target" position={horizontal ? Position.Left : Position.Top} />
      <div className="head">
        <div className="badge" style={{ background: kind.color }}>{kind.short}</div>
        <div style={{ minWidth: 0 }}>
          <div className="title" title={c.name ?? c.id}>
            {showEntry && c.entry_point && <span className="star" title="Entry point">★ </span>}
            {c.name ?? c.id}
          </div>
          <div className="sub">{kind.label}</div>
        </div>
      </div>
      <div className="meta">
        <span>{summary || " "}</span>
        {status && <span className={`status-${status}`} style={{ fontWeight: 600 }}>{status}</span>}
      </div>
      <Handle type="source" position={horizontal ? Position.Right : Position.Bottom} />
    </div>
  );
}

export const nodeTypes = { component: ComponentNode };

export const depId = relId;

/*
 * Edges on the dark stage: gold lines (dashed / dotted per the relationship
 * type's style), crimson / orange when carrying a failure / degradation.
 */
const GOLD = "#E9B85A";
const FALLBACK_BLUE = "#8FB8E0";
const FAILED = "#FF6B81";
const DEGRADED = "#F59A3E";
const HIGHLIGHT = "#FFF3DC";

const DASH: Record<string, string | undefined> = { solid: undefined, dashed: "7 5", dotted: "2 5" };

function baseStyle(spec: DomainSpec, d: DependencyDef): React.CSSProperties {
  const rt = spec.relationship_types.find((r) => r.type === d.dependency_type);
  const style = rt?.style ?? "solid";
  return {
    stroke: style === "dotted" && hasFeature(spec, "groups") ? FALLBACK_BLUE : GOLD,
    strokeWidth: 2,
    strokeDasharray: DASH[style],
  };
}

const glow = (color: string) => `drop-shadow(0 0 4px ${color})`;

export function edgeLabel(spec: DomainSpec, d: DependencyDef): string {
  const parts: string[] = [];
  const a = d.attributes ?? {};
  if (hasFeature(spec, "groups")) {
    if (d.dependency_type !== spec.relationship_types[0]?.type) parts.push(d.dependency_type);
    if (d.group) parts.push(`[${d.group}]`);
    if (d.propagation_delay) parts.push(`delay ${d.propagation_delay}`);
    if (typeof a.load_share === "number") parts.push(`load ×${a.load_share}`);
  } else if (typeof a.probability === "number" && a.probability < 1) {
    parts.push(`${Math.round(a.probability * 100)}%`);
  } else if (typeof a.travel_time === "number") {
    parts.push(`${a.travel_time} h${a.refrigerated === false ? " · not chilled" : ""}`);
  }
  return parts.join(" ");
}

export function buildNodes(
  spec: DomainSpec,
  components: ComponentDef[],
  positions: Record<string, Point>,
  opts: { selectedId?: string | null; status?: Record<string, Status>; flags?: Record<string, string[]> } = {},
): ComponentNodeType[] {
  const showEntry = hasFeature(spec, "entry_points");
  const horizontal = !hasFeature(spec, "propagation_delay");
  return components.map((c) => {
    const k = entityType(spec, c.type);
    return {
      id: c.id,
      type: "component",
      position: positions[c.id] ?? { x: 0, y: 0 },
      selected: opts.selectedId === c.id,
      data: {
        component: c, kind: { short: k.short, label: k.label, color: k.color },
        summary: componentSummary(spec, c), status: opts.status?.[c.id], flags: opts.flags?.[c.id], showEntry, horizontal,
      },
    };
  });
}

export function buildEdges(
  spec: DomainSpec,
  deps: DependencyDef[],
  opts: { selectedId?: string | null; status?: Record<string, Status>; highlight?: Set<string> } = {},
): Edge[] {
  // Status propagation domains colour an edge by the status of what it points at;
  // flow domains colour it only by its own status (e.g. a closed route).
  const byTarget = hasFeature(spec, "propagation_delay");
  return deps.map((d) => {
    const id = depId(d);
    const base = baseStyle(spec, d);
    const st = opts.status?.[id] ?? (byTarget ? opts.status?.[d.target_id] : undefined);
    const broken = st === "failed" || st === "degraded";
    const color = st === "failed" ? FAILED : st === "degraded" ? DEGRADED : (base.stroke as string);
    const selected = opts.selectedId === id;
    const highlighted = opts.highlight?.has(id);
    const stroke = selected || highlighted ? HIGHLIGHT : color;
    return {
      id,
      source: d.source_id,
      target: d.target_id,
      label: edgeLabel(spec, d) || undefined,
      selected,
      animated: broken,
      style: {
        ...base,
        stroke,
        strokeWidth: selected || highlighted ? 3 : broken ? 2.6 : base.strokeWidth,
        filter: glow(stroke),
      },
      markerEnd: { type: MarkerType.ArrowClosed, color: stroke },
      labelStyle: { fontSize: 11, fill: "#FFF3DC" },
      labelBgStyle: { fill: "#3D2614" },
      labelBgPadding: [6, 3] as [number, number],
      labelBgBorderRadius: 8,
    };
  });
}

export function Legend({ spec }: { spec: DomainSpec }) {
  return (
    <div className="legend">
      {spec.relationship_types.map((r) => {
        const style = baseStyle(spec, { source_id: "", target_id: "", dependency_type: r.type, propagation_delay: 0 });
        return (
          <span key={r.type} title={r.description}>
            <svg width="26" height="6"><line x1="0" y1="3" x2="26" y2="3" style={style} /></svg>{r.label.toLowerCase()}
          </span>
        );
      })}
      <span><svg width="26" height="6"><line x1="0" y1="3" x2="26" y2="3" stroke={FAILED} strokeWidth={2.6} /></svg>
        {hasFeature(spec, "propagation_delay") ? "carrying a failure" : "closed / failing"}</span>
      <span>{spec.edge_meaning}</span>
    </div>
  );
}
