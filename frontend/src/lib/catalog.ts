/** Component types offered in the editor palette, with sensible defaults. */
export interface ComponentKind {
  type: string;
  label: string;
  short: string; // 2-letter badge
  color: string;
  defaults: Record<string, number>;
}

export const COMPONENT_KINDS: ComponentKind[] = [
  // Badge colours: light tints that read on the dark teal graph stage, with dark text.
  { type: "gateway", label: "API Gateway", short: "GW", color: "#E9B85A", defaults: { capacity: 1000, current_load: 600 } },
  { type: "service", label: "Service", short: "SV", color: "#8FB8E0", defaults: { capacity: 800, current_load: 400 } },
  { type: "database", label: "Database", short: "DB", color: "#CFA6E6", defaults: { capacity: 1000, current_load: 600, recovery_time: 10 } },
  { type: "cache", label: "Cache", short: "CA", color: "#F59A3E", defaults: { capacity: 5000, current_load: 1000 } },
  { type: "queue", label: "Queue", short: "QU", color: "#EBD48F", defaults: { capacity: 2000, current_load: 500 } },
  { type: "external", label: "External API", short: "EX", color: "#C9AE85", defaults: {} },
];

export function kindOf(type: string): ComponentKind {
  return (
    COMPONENT_KINDS.find((k) => k.type === type) ?? {
      type, label: type, short: type.slice(0, 2).toUpperCase(), color: "#C9AE85", defaults: {},
    }
  );
}

export const EVENT_LABELS: Record<string, string> = {
  component_failure: "Failure",
  component_recovery: "Recovery",
  traffic_spike: "Traffic spike",
  latency_increase: "Latency increase",
};

/** Make an id like "service_2" that is not in `taken`. */
export function uniqueId(base: string, taken: Iterable<string>): string {
  const used = new Set(taken);
  const clean = base.toLowerCase().replace(/[^a-z0-9_.-]+/g, "_").replace(/^_+|_+$/g, "") || "item";
  if (!used.has(clean)) return clean;
  for (let i = 2; ; i++) if (!used.has(`${clean}_${i}`)) return `${clean}_${i}`;
}
