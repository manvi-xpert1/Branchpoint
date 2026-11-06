// Mirrors backend/app/schemas.py. Keep the two in sync.

export type Status = "healthy" | "degraded" | "failed";
export type DependencyType = "requires" | "optional" | "fallback";
export type EventType =
  | "component_failure"
  | "component_recovery"
  | "traffic_spike"
  | "latency_increase";
export type InterventionType =
  | "add_component"
  | "remove_component"
  | "add_dependency"
  | "remove_dependency"
  | "set_attribute";

export interface ComponentDef {
  id: string;
  name?: string | null;
  type: string;
  entry_point: boolean;
  attributes: Record<string, unknown>;
  layout?: { x: number; y: number } | null;
}

export interface DependencyDef {
  id?: string | null;
  source_id: string;
  target_id: string;
  dependency_type: DependencyType;
  group?: string | null;
  propagation_delay: number;
}

export interface SystemDef {
  name: string;
  domain: string;
  description: string;
  components: ComponentDef[];
  dependencies: DependencyDef[];
}

export interface SystemOut extends SystemDef {
  id: string;
  created_at: string;
  updated_at: string;
}

export interface SystemSummary {
  id: string;
  name: string;
  domain: string;
  description: string;
  component_count: number;
  dependency_count: number;
  scenario_count: number;
  updated_at: string;
}

export interface SystemAnalysis {
  valid: boolean;
  errors: string[];
  warnings: string[];
  cycle: string[] | null;
  topological_order: string[] | null;
  entry_points: string[];
  blast_radius: Record<string, string[]>;
}

export interface EventDef {
  id: string;
  type: EventType;
  target_id: string;
  start_time: number;
  duration?: number | null;
  severity: number;
  probability: number;
}

export interface InterventionDef {
  id: string;
  type: InterventionType;
  params: Record<string, unknown>;
  cost: number;
  description: string;
}

export interface ScenarioIn {
  name: string;
  description: string;
  parent_id: string | null;
  seed: number | null;
  events: EventDef[];
  interventions: InterventionDef[];
  remove_events: string[];
}

export interface ScenarioOut {
  id: string;
  system_id: string;
  parent_id: string | null;
  name: string;
  description: string;
  seed: number;
  events: EventDef[];
  interventions: InterventionDef[];
  remove_events: string[];
  children: string[];
  lineage: string[];
  resolved_events: EventDef[];
  resolved_interventions: InterventionDef[];
  created_at: string;
  updated_at: string;
}

export interface Metrics {
  duration: number;
  availability: number;
  downtime: number;
  degraded_time: number;
  affected_components: number;
  recovery_time: number | null;
  cost: number;
}

export interface LogEntry {
  seq: number;
  time: number;
  kind: "event" | "status_change";
  component_id: string;
  message: string;
  cause_seq: number | null;
  event_id: string | null;
  old_status: Status | null;
  new_status: Status | null;
}

export interface RunSummary {
  id: string;
  scenario_id: string;
  scenario_name: string;
  status: string;
  seed: number;
  until: number;
  metrics: Metrics;
  elapsed_ms: number;
  created_at: string;
}

export interface RunOut extends RunSummary {
  /** System as simulated (interventions applied). Has no layout info. */
  system: SystemDef;
  skipped_events: string[];
  timelines: Record<string, [number, Status][]>;
  log: LogEntry[];
}

export interface CompareOut {
  runs: RunSummary[];
  best: Partial<Record<keyof Metrics, string[]>>;
}

export interface ReplayOut {
  run_id: string;
  identical: boolean;
  differences: string[];
}

export interface ImportOut {
  system_id: string;
  scenario_ids: Record<string, string>;
}
