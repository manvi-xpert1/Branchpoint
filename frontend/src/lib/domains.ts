/**
 * Helpers that read a domain catalog (GET /api/domains). Pure functions, no
 * React, so they are easy to test. Every screen uses these instead of
 * hard-coding one domain's components, events or metrics.
 */
import type {
  ComponentDef, DependencyDef, DomainSpec, EntityType, EventTypeSpec, FieldSpec, MetricDef, Metrics,
  ScenarioOut, SensitivityOut, SystemDef,
} from "../api/types";

export function entityType(spec: DomainSpec, type: string): EntityType {
  return spec.entity_types.find((e) => e.type === type) ?? {
    type, label: type, short: type.slice(0, 2).toUpperCase(), color: "#C9AE85", fields: [], description: "",
  };
}

export function eventType(spec: DomainSpec, type: string): EventTypeSpec | undefined {
  return spec.event_types.find((e) => e.type === type);
}

export function hasFeature(spec: DomainSpec, feature: string): boolean {
  return spec.features.includes(feature);
}

/** Attribute values to start a new component (or route) with: every field default that is set. */
export function defaultAttributes(fields: FieldSpec[]): Record<string, unknown> {
  const out: Record<string, unknown> = {};
  for (const f of fields) if (f.default !== null && f.default !== undefined) out[f.key] = f.default;
  return out;
}

export function metricDef(spec: DomainSpec, key: string): MetricDef {
  return spec.metrics.find((m) => m.key === key) ?? {
    key, label: key, better: "neutral", unit: "", format: "number", description: "",
  };
}

function trimNumber(n: number, digits = 2): string {
  if (Number.isInteger(n)) return n.toLocaleString("en-US");
  if (Math.abs(n) >= 1000) return Math.round(n).toLocaleString("en-US");
  return n.toFixed(digits).replace(/\.?0+$/, "");
}

/** Same rules as the backend's format_value, plus a unit when useful. */
export function formatMetric(def: MetricDef, value: number | null | undefined, withUnit = false): string {
  if (value === null || value === undefined || Number.isNaN(value)) return "–";
  if (def.format === "percent") return `${(value * 100).toFixed(1)}%`;
  const text = def.format === "money" ? trimNumber(value, Math.abs(value) < 1000 ? 2 : 0) : trimNumber(value);
  return withUnit && def.unit ? `${text} ${def.unit}` : text;
}

/** Metrics that have a value in at least one of the rows (opt-in metrics without data are hidden). */
export function visibleMetrics(spec: DomainSpec, rows: Metrics[]): MetricDef[] {
  return spec.metrics.filter((m) => rows.some((r) => r[m.key] !== null && r[m.key] !== undefined));
}

/** Ids of the rows with the best value of a metric (none for neutral metrics or ties across all). */
export function bestIds(def: MetricDef, rows: { id: string; value: number | null | undefined }[]): string[] {
  if (def.better === "neutral") return [];
  const present = rows.filter((r) => r.value !== null && r.value !== undefined) as { id: string; value: number }[];
  if (present.length < 2) return [];
  const values = present.map((r) => r.value);
  const best = def.better === "lower" ? Math.min(...values) : Math.max(...values);
  if (values.every((v) => v === best)) return [];
  return present.filter((r) => Math.abs(r.value - best) < 1e-9).map((r) => r.id);
}

/** Is this value a problem worth colouring? (e.g. downtime > 0, fill rate < 100%) */
export function tone(def: MetricDef, value: number | null | undefined): "ok" | "warn" | "bad" | undefined {
  if (value === null || value === undefined) return undefined;
  if (def.format === "percent" && def.better === "higher") return value >= 0.999 ? "ok" : value >= 0.95 ? "warn" : "bad";
  if (def.better === "lower" && (def.format === "count" || def.format === "duration") && def.key !== "cost") {
    return value > 0 ? "warn" : undefined;
  }
  return undefined;
}

/** One-line summary shown on a graph node, from the component's first set fields. */
export function componentSummary(spec: DomainSpec, c: ComponentDef): string {
  const a = c.attributes;
  if (typeof a.capacity === "number" && typeof a.current_load === "number") return `${a.current_load}/${a.capacity} rps`;
  const parts: string[] = [];
  for (const f of entityType(spec, c.type).fields) {
    const v = a[f.key];
    if (typeof v === "number" && parts.length < 2) parts.push(`${trimNumber(v)}${f.unit ? " " + shortUnit(f.unit) : ""}`);
  }
  return parts.join(" · ");
}

function shortUnit(unit: string): string {
  return unit.replace("patients at once", "beds").replace("patients/hour", "/h").replace("units/hour", "/h")
    .replace("requests/s", "rps").replace("hours", "h").replace("time units", "t");
}

/** Relationship id as the backend builds it. */
export function relId(d: DependencyDef): string {
  return d.id ?? `${d.source_id}->${d.target_id}`;
}

/** Targets an event can point at: components, or routes for relationship events. */
export function eventTargets(spec: DomainSpec, type: string, system: SystemDef, componentIds: string[]): string[] {
  const et = eventType(spec, type);
  return et?.target === "relationship" ? system.dependencies.map(relId) : componentIds;
}

// ---- futures ------------------------------------------------------------
export interface FutureGroup {
  id: string;
  label: string;
  scenarioIds: string[];
}

/**
 * Sets of scenarios worth comparing: each scenario with branches (itself plus
 * its direct branches: "the same situation, different decisions"), then all.
 */
export function futureGroups(scenarios: ScenarioOut[]): FutureGroup[] {
  const groups: FutureGroup[] = [];
  for (const s of scenarios) {
    const kids = scenarios.filter((c) => c.parent_id === s.id);
    if (kids.length) {
      groups.push({
        id: s.id,
        label: `${s.name} and its ${kids.length} branch${kids.length > 1 ? "es" : ""}`,
        scenarioIds: [s.id, ...kids.map((k) => k.id)],
      });
    }
  }
  if (scenarios.length) groups.push({ id: "all", label: `All ${scenarios.length} scenarios`, scenarioIds: scenarios.map((s) => s.id) });
  return groups;
}

/** Start with the group that has the most decisions to compare, preferring branches of a branch. */
export function defaultGroup(groups: FutureGroup[], scenarios: ScenarioOut[]): FutureGroup | undefined {
  const depth = (id: string) => scenarios.find((s) => s.id === id)?.lineage.length ?? 0;
  const branchGroups = groups.filter((g) => g.id !== "all");
  if (!branchGroups.length) return groups[0];
  return [...branchGroups].sort((a, b) =>
    (b.scenarioIds.length - a.scenarioIds.length) || (depth(b.id) - depth(a.id)))[0];
}

// ---- sensitivity --------------------------------------------------------
/** Plain-language name of a sensitivity input, e.g. "Medical ward: Beds / staff". */
export function inputLabel(row: { kind: string; target: string; key: string }, spec: DomainSpec, system: SystemDef): string {
  if (row.kind === "attribute") {
    const c = system.components.find((x) => x.id === row.target);
    const f = c ? entityType(spec, c.type).fields.find((x) => x.key === row.key) : undefined;
    return `${c?.name ?? row.target}: ${f?.label ?? row.key.replace(/_/g, " ")}`;
  }
  if (row.kind === "parameter") {
    return `System: ${spec.parameters.find((p) => p.key === row.key)?.label ?? row.key.replace(/_/g, " ")}`;
  }
  return `Event ${row.target}: ${row.key}`;
}

export interface TornadoRow {
  label: string;
  /** Change in the metric when the input is lowered / raised (relative to the baseline). */
  low: number;
  high: number;
  swing: number;
}

export function tornadoData(sens: SensitivityOut, label: (row: SensitivityOut["rows"][number]) => string, limit = 10): TornadoRow[] {
  const base = sens.baseline ?? 0;
  return sens.rows
    .filter((r) => r.swing > 0 && r.low !== null && r.high !== null)
    .slice(0, limit)
    .map((r) => ({ label: label(r), low: (r.low as number) - base, high: (r.high as number) - base, swing: r.swing }));
}
