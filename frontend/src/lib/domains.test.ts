import { describe, expect, it } from "vitest";
import type { DomainSpec, MetricDef, ScenarioOut, SensitivityOut } from "../api/types";
import {
  bestIds, componentSummary, defaultAttributes, defaultGroup, eventTargets, formatMetric, futureGroups, inputLabel,
  tone, tornadoData, visibleMetrics,
} from "./domains";
import { layeredLayout } from "./layout";

const metric = (key: string, better: MetricDef["better"], format: MetricDef["format"] = "number", unit = ""): MetricDef =>
  ({ key, label: key, better, unit, format, description: "" });

const SPEC: DomainSpec = {
  name: "test", label: "Test", description: "", time_unit: "hours",
  entity_types: [{
    type: "ward", label: "Ward", short: "WD", color: "#fff", description: "",
    fields: [
      { key: "capacity", label: "Beds", kind: "integer", unit: "patients at once", default: 10, min: 0, max: null, choices: [], help: "" },
      { key: "service_time", label: "Mean time", kind: "number", unit: "hours", default: 2, min: 0, max: null, choices: [], help: "" },
      { key: "max_wait", label: "Leaves after", kind: "number", unit: "hours", default: null, min: 0, max: null, choices: [], help: "" },
    ],
  }],
  relationship_types: [{ type: "routes_to", label: "Routes to", description: "", style: "solid", fields: [] }],
  event_types: [
    { type: "closure", label: "Closure", description: "", target: "entity", severity_label: null, uses_duration: true, fields: [] },
    { type: "reefer", label: "Reefer", description: "", target: "relationship", severity_label: null, uses_duration: true, fields: [] },
  ],
  intervention_types: [],
  metrics: [metric("wait", "lower", "duration", "hours"), metric("fill", "higher", "percent"), metric("arrived", "neutral", "count"),
    metric("latency", "lower")],
  risk_metric: "wait", assumptions: [], parameters: [], default_objectives: [], open_entity_types: false,
  default_until: 72, features: [], edge_meaning: "",
};

describe("formatting and comparing metrics", () => {
  it("formats like the backend", () => {
    expect(formatMetric(metric("p", "higher", "percent"), 0.9512)).toBe("95.1%");
    expect(formatMetric(metric("m", "lower", "money"), 239380.4)).toBe("239,380");
    expect(formatMetric(metric("m", "lower", "money"), 12.5)).toBe("12.5");
    expect(formatMetric(metric("d", "lower", "duration", "hours"), 1.5781, true)).toBe("1.58 hours");
    expect(formatMetric(metric("d", "lower"), null)).toBe("–");
  });

  it("finds the best rows using the metric's direction, ignoring ties and missing values", () => {
    const rows = [{ id: "a", value: 3 }, { id: "b", value: 1 }, { id: "c", value: null }];
    expect(bestIds(metric("x", "lower"), rows)).toEqual(["b"]);
    expect(bestIds(metric("x", "higher"), rows)).toEqual(["a"]);
    expect(bestIds(metric("x", "neutral"), rows)).toEqual([]);
    expect(bestIds(metric("x", "lower"), [{ id: "a", value: 2 }, { id: "b", value: 2 }])).toEqual([]);
  });

  it("hides opt-in metrics that no row has", () => {
    expect(visibleMetrics(SPEC, [{ wait: 1, fill: 1, arrived: 3, latency: null }]).map((m) => m.key))
      .toEqual(["wait", "fill", "arrived"]);
  });

  it("colours problems", () => {
    expect(tone(metric("fill", "higher", "percent"), 1)).toBe("ok");
    expect(tone(metric("fill", "higher", "percent"), 0.9)).toBe("bad");
    expect(tone(metric("wait", "lower", "duration"), 2)).toBe("warn");
    expect(tone(metric("wait", "lower", "duration"), 0)).toBeUndefined();
  });
});

describe("catalog-driven editing", () => {
  it("starts new components with the field defaults that are set", () => {
    expect(defaultAttributes(SPEC.entity_types[0].fields)).toEqual({ capacity: 10, service_time: 2 });
  });

  it("summarises a component from its first fields", () => {
    expect(componentSummary(SPEC, { id: "w", type: "ward", entry_point: false, attributes: { capacity: 34, service_time: 20 } }))
      .toBe("34 beds · 20 h");
    expect(componentSummary(SPEC, { id: "g", type: "gateway", entry_point: true, attributes: { capacity: 1000, current_load: 600 } }))
      .toBe("600/1000 rps");
  });

  it("offers routes as targets for relationship events", () => {
    const system = { name: "s", domain: "test", description: "", components: [], dependencies: [
      { id: "a->b", source_id: "a", target_id: "b", dependency_type: "routes_to", propagation_delay: 0 }] };
    expect(eventTargets(SPEC, "reefer", system, ["a", "b"])).toEqual(["a->b"]);
    expect(eventTargets(SPEC, "closure", system, ["a", "b"])).toEqual(["a", "b"]);
  });
});

const scenario = (id: string, parent: string | null, lineage: string[]): ScenarioOut => ({
  id, parent_id: parent, lineage, name: id, system_id: "s", description: "", seed: 1, events: [], interventions: [],
  remove_events: [], children: [], resolved_events: [], resolved_interventions: [], created_at: "", updated_at: "",
});

describe("futures", () => {
  const scenarios = [
    scenario("base", null, ["base"]),
    scenario("surge", "base", ["base", "surge"]),
    scenario("beds", "surge", ["base", "surge", "beds"]),
    scenario("bays", "surge", ["base", "surge", "bays"]),
  ];

  it("groups each scenario with its branches, then all", () => {
    const groups = futureGroups(scenarios);
    expect(groups.map((g) => [g.id, g.scenarioIds])).toEqual([
      ["base", ["base", "surge"]],
      ["surge", ["surge", "beds", "bays"]],
      ["all", ["base", "surge", "beds", "bays"]],
    ]);
    expect(groups[1].label).toBe("surge and its 2 branches");
  });

  it("opens on the group with the most decisions", () => {
    expect(defaultGroup(futureGroups(scenarios), scenarios)?.id).toBe("surge");
    expect(defaultGroup(futureGroups([scenarios[0]]), [scenarios[0]])?.id).toBe("all");
  });

  it("turns sensitivity rows into tornado bars relative to the baseline", () => {
    const sens: SensitivityOut = { scenario_id: "x", metric: "wait", baseline: 2, delta: 0.2, runs: 1, elapsed_ms: 1, rows: [
      { id: "attribute:w:capacity", kind: "attribute", target: "w", key: "capacity", value: 10, low_value: 8, high_value: 12, low: 5, high: 1.5, swing: 3.5 },
      { id: "parameter:system:x", kind: "parameter", target: "system", key: "x", value: 1, low_value: 0.8, high_value: 1.2, low: 2, high: 2, swing: 0 },
    ] };
    const system = { name: "s", domain: "test", description: "", dependencies: [],
      components: [{ id: "w", name: "Ward A", type: "ward", entry_point: false, attributes: {} }] };
    const rows = tornadoData(sens, (r) => inputLabel(r, SPEC, system));
    expect(rows).toEqual([{ label: "Ward A: Beds", low: 3, high: -0.5, swing: 3.5 }]);
  });
});

describe("layout", () => {
  it("lays flow domains out left to right", () => {
    const comps = ["a", "b"].map((id) => ({ id, type: "ward", entry_point: false, attributes: {} }));
    const deps = [{ source_id: "a", target_id: "b", dependency_type: "routes_to", propagation_delay: 0 }];
    const vertical = layeredLayout(comps, deps);
    const horizontal = layeredLayout(comps, deps, true);
    expect(vertical.b.y).toBeGreaterThan(vertical.a.y);
    expect(horizontal.b.x).toBeGreaterThan(horizontal.a.x);
    expect(horizontal.b.y).toBe(horizontal.a.y);
  });
});
