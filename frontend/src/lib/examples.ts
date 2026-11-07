/**
 * The three built-in examples (copies of /examples/*.json). Importing one
 * creates a real system with its scenarios; every number shown afterwards
 * comes from running it.
 */
import coldchain from "../examples/coldchain.json";
import ecommerce from "../examples/ecommerce.json";
import hospital from "../examples/hospital.json";

export interface ExampleInfo {
  domain: string;
  title: string;
  tagline: string;
  explore: string[];
  data: { system: { name: string; components: unknown[] }; scenarios: { id: string; name: string; parent?: string | null }[] };
  /** Scenario (by file id) whose branches the Futures tab should open on. */
  focus: string;
}

export const EXAMPLES: ExampleInfo[] = [
  {
    domain: "software_infrastructure",
    title: "Software infrastructure",
    tagline: "Services, databases and caches that depend on each other.",
    explore: ["Outages and traffic spikes spreading through dependencies", "Replicas, fallbacks and faster restores",
      "Availability, downtime, latency and cost"],
    data: ecommerce as ExampleInfo["data"],
    focus: "db-down",
  },
  {
    domain: "hospital",
    title: "Hospital operations",
    tagline: "Patient flow through triage, emergency, wards and ICU.",
    explore: ["Arrival surges, staff shortages and closures", "Extra beds, bays and faster discharges",
      "Waiting times, patients leaving untreated, boarding, cost"],
    data: hospital as ExampleInfo["data"],
    focus: "surge",
  },
  {
    domain: "cold_chain",
    title: "Cold-chain logistics",
    tagline: "Chilled stock moving from suppliers to stores.",
    explore: ["Power cuts, refrigeration failures, road closures", "Backup power, safety stock and rerouting",
      "Fill rate, discarded units, on-time delivery, cost"],
    data: coldchain as ExampleInfo["data"],
    focus: "outage",
  },
];

export function exampleFor(domain: string): ExampleInfo | undefined {
  return EXAMPLES.find((e) => e.domain === domain);
}

/** The example's scenario tree as {name, children} for a small preview. */
export function scenarioTree(info: ExampleInfo): { name: string; branches: string[] } {
  const focus = info.data.scenarios.find((s) => s.id === info.focus);
  return {
    name: focus?.name ?? info.data.system.name,
    branches: info.data.scenarios.filter((s) => s.parent === info.focus).map((s) => s.name),
  };
}
