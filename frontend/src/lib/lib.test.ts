import { describe, expect, it } from "vitest";
import type { ComponentDef, DependencyDef, LogEntry, SystemDef } from "../api/types";
import { uniqueId } from "./catalog";
import { binIndexOf, histogram } from "./histogram";
import { freeSpot, layeredLayout } from "./layout";
import { componentIdsAfter, fallbackPreset, replicaPreset } from "./presets";
import { causalChain, eventTimes, segments, statusAt, worst } from "./timeline";

const comp = (id: string, type = "service"): ComponentDef => ({ id, type, entry_point: false, attributes: {} });
const dep = (s: string, t: string, extra: Partial<DependencyDef> = {}): DependencyDef => ({
  id: `${s}->${t}`, source_id: s, target_id: t, dependency_type: "requires", group: null, propagation_delay: 0, ...extra,
});

describe("layeredLayout", () => {
  it("puts dependents above their dependencies", () => {
    const pos = layeredLayout([comp("gw"), comp("svc"), comp("db")], [dep("gw", "svc"), dep("svc", "db")]);
    expect(pos.gw.y).toBeLessThan(pos.svc.y);
    expect(pos.svc.y).toBeLessThan(pos.db.y);
  });

  it("uses the deepest path when a component is reachable in several ways", () => {
    // gw -> db directly and via svc: db must sit below svc.
    const pos = layeredLayout([comp("gw"), comp("svc"), comp("db")], [dep("gw", "db"), dep("gw", "svc"), dep("svc", "db")]);
    expect(pos.db.y).toBeGreaterThan(pos.svc.y);
  });

  it("terminates on cycles and places every node", () => {
    const pos = layeredLayout([comp("a"), comp("b")], [dep("a", "b"), dep("b", "a")]);
    expect(Object.keys(pos).sort()).toEqual(["a", "b"]);
  });
});

describe("freeSpot", () => {
  it("returns the start when free and avoids overlaps otherwise", () => {
    expect(freeSpot({ x: 0, y: 0 }, [])).toEqual({ x: 0, y: 0 });
    const p = freeSpot({ x: 0, y: 0 }, [{ x: 10, y: 10 }]);
    expect(Math.abs(p.x - 10) >= 190 || Math.abs(p.y - 10) >= 100).toBe(true);
  });
});

describe("timeline helpers", () => {
  const tl: [number, "healthy" | "degraded" | "failed"][] = [[0, "healthy"], [5, "failed"], [15, "healthy"]];

  it("statusAt treats a change at exactly t as already happened", () => {
    expect(statusAt(tl, 4.9)).toBe("healthy");
    expect(statusAt(tl, 5)).toBe("failed");
    expect(statusAt(tl, 15)).toBe("healthy");
    expect(statusAt(undefined, 3)).toBe("healthy");
  });

  it("segments clip to the run length", () => {
    expect(segments(tl, 10)).toEqual([[0, 5, "healthy"], [5, 10, "failed"]]);
  });

  it("worst picks the most severe status", () => {
    expect(worst(["healthy", "degraded"])).toBe("degraded");
    expect(worst(["degraded", "failed", "healthy"])).toBe("failed");
  });

  it("causalChain follows cause links back to the root event", () => {
    const log: LogEntry[] = [
      { seq: 0, time: 5, kind: "event", component_id: "db", message: "failure begins", cause_seq: null, event_id: "e", old_status: null, new_status: null },
      { seq: 1, time: 5, kind: "status_change", component_id: "db", message: "", cause_seq: 0, event_id: null, old_status: "healthy", new_status: "failed" },
      { seq: 2, time: 6, kind: "status_change", component_id: "svc", message: "", cause_seq: 1, event_id: null, old_status: "healthy", new_status: "failed" },
    ];
    expect(causalChain(log, 2).map((e) => e.seq)).toEqual([0, 1, 2]);
    expect(eventTimes(log)).toEqual([5, 6]);
  });
});

describe("presets", () => {
  const system: SystemDef = {
    name: "t", domain: "software_infrastructure", description: "",
    components: [comp("svc"), comp("db", "database"), comp("cache", "cache")],
    dependencies: [dep("svc", "db")],
  };

  it("replica preset groups the existing dependency and adds a failover link", () => {
    const ivs = replicaPreset(system, "db", [], 300);
    expect(ivs.map((i) => i.type)).toEqual(["add_component", "remove_dependency", "add_dependency", "add_dependency"]);
    expect(ivs[0].params.id).toBe("db_replica");
    expect(ivs[0].cost).toBe(300);
    const groups = ivs.filter((i) => i.type === "add_dependency").map((i) => i.params.group);
    expect(new Set(groups).size).toBe(1);
    expect(groups[0]).toBe("db_pool");
  });

  it("does not regroup a dependency that already has a group", () => {
    const grouped = { ...system, dependencies: [dep("svc", "db", { group: "data" })] };
    const ivs = fallbackPreset(grouped, "svc", "db", "cache", [], 50);
    expect(ivs).toHaveLength(1);
    expect(ivs[0].params).toMatchObject({ dependency_type: "fallback", group: "data", target_id: "cache" });
  });

  it("generates unique intervention ids", () => {
    const first = replicaPreset(system, "db", []);
    const second = replicaPreset(system, "db", first);
    const ids = [...first, ...second].map((i) => i.id);
    expect(new Set(ids).size).toBe(ids.length);
  });

  it("componentIdsAfter includes added and drops removed components", () => {
    const ivs = replicaPreset(system, "db", []);
    expect(componentIdsAfter(system, ivs)).toContain("db_replica");
    expect(componentIdsAfter(system, [{ id: "r", type: "remove_component", params: { id: "cache" }, cost: 0, description: "" }]))
      .not.toContain("cache");
  });
});

describe("uniqueId", () => {
  it("slugifies and avoids collisions", () => {
    expect(uniqueId("My Service", [])).toBe("my_service");
    expect(uniqueId("service", ["service", "service_2"])).toBe("service_3");
  });
});

describe("histogram", () => {
  it("uses one bar per distinct value when there are few", () => {
    const bins = histogram([0, 10, 0, 4, 14, 0, 10]);
    expect(bins.map((b) => [b.label, b.count])).toEqual([["0", 3], ["4", 1], ["10", 2], ["14", 1]]);
  });

  it("splits into equal-width ranges when values are spread out", () => {
    const values = Array.from({ length: 100 }, (_, i) => i); // 0..99
    const bins = histogram(values, 10);
    expect(bins).toHaveLength(10);
    expect(bins.every((b) => b.count === 10)).toBe(true);
    expect(bins.reduce((n, b) => n + b.count, 0)).toBe(100); // the max value is not lost
  });

  it("returns nothing for no values", () => {
    expect(histogram([])).toEqual([]);
  });

  it("finds the bar a value falls in, including interpolated percentiles", () => {
    const bins = histogram([0, 4, 10, 14]);
    expect(binIndexOf(bins, 10)).toBe(2);
    expect(binIndexOf(bins, 12)).toBe(2);
    expect(binIndexOf(bins, 14)).toBe(3);
    expect(binIndexOf(bins, -1)).toBe(-1);
  });
});
