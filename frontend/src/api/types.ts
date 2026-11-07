// Mirrors backend/app/schemas.py. Keep the two in sync.

export type Status = "healthy" | "degraded" | "failed";
/** Relationship type: depends on the domain (requires / routes_to / ships_to ...). */
export type DependencyType = string;
/** Event type: depends on the domain (see DomainSpec.event_types). */
export type EventType = string;
export type InterventionType =
  | "add_component"
  | "remove_component"
  | "add_dependency"
  | "remove_dependency"
  | "set_attribute"
  | "set_dependency_attribute"
  | "set_parameter";

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
  /** Domain-specific relationship data (routing share, travel time, ...). */
  attributes?: Record<string, unknown>;
}

export interface SystemDef {
  name: string;
  domain: string;
  description: string;
  components: ComponentDef[];
  dependencies: DependencyDef[];
  /** System-wide variables that scenarios can change (set_parameter). */
  parameters?: Record<string, unknown>;
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
  /** Domain-specific event settings. */
  params?: Record<string, unknown>;
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

/** Any domain's metrics: key -> value. The domain catalog describes each key. */
export type Metrics = Record<string, number | null>;

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
  domain?: string;
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
  /** Status over time for components, and for routes in domains that have route statuses. */
  timelines: Record<string, [number, Status][]>;
  /** variable -> entity -> [time, value] points (queue length, stock, load, ...). */
  series?: Record<string, Record<string, [number, number | null][]>>;
  log: LogEntry[];
}

export interface CompareOut {
  runs: RunSummary[];
  best: Record<string, string[]>;
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

/** Infrastructure-only summary kept for older screens; null in other domains. */
export interface MonteCarloAggregates {
  downtime_mean: number;
  downtime_p50: number;
  downtime_p95: number;
  downtime_max: number;
  p_any_downtime: number;
  availability_mean: number;
  degraded_time_mean: number;
  event_frequency: Record<string, number>;
}

export interface MetricStats {
  mean: number | null;
  std: number | null;
  min: number | null;
  p5: number | null;
  p50: number | null;
  p95: number | null;
  max: number | null;
  missing: number;
}

export interface RiskSummary {
  metric: string;
  mean: number | null;
  /** The bad-case percentile (p5 for higher-is-better metrics). */
  p95: number | null;
  worst_5_percent_mean: number | null;
  p_nonzero: number | null;
}

export interface Driver {
  event_id: string;
  frequency: number;
  mean_if_occurred: number;
  mean_if_not: number;
  impact: number;
}

export interface MonteCarloOut {
  id: string;
  scenario_id: string;
  scenario_name: string;
  runs: number;
  base_seed: number;
  until: number;
  deterministic: boolean;
  aggregates: MonteCarloAggregates | null;
  downtimes: number[];
  elapsed_ms: number;
  created_at: string;
  domain: string;
  risk_metric: string;
  risk_values: (number | null)[];
  event_frequency: Record<string, number>;
  metric_stats: Record<string, MetricStats>;
  risk: RiskSummary | null;
  drivers: Driver[];
}

// ---- domain catalogs (GET /api/domains) ------------------------------
export type FieldKind = "number" | "integer" | "probability" | "text" | "boolean" | "choice";

export interface FieldSpec {
  key: string;
  label: string;
  kind: FieldKind;
  unit: string;
  default: unknown;
  min: number | null;
  max: number | null;
  choices: string[];
  help: string;
}

export interface EntityType {
  type: string;
  label: string;
  short: string;
  color: string;
  fields: FieldSpec[];
  description: string;
}

export interface RelationshipType {
  type: string;
  label: string;
  description: string;
  style: "solid" | "dashed" | "dotted";
  fields: FieldSpec[];
}

export interface EventTypeSpec {
  type: string;
  label: string;
  description: string;
  target: "entity" | "relationship";
  severity_label: string | null;
  uses_duration: boolean;
  fields: FieldSpec[];
}

export interface MetricDef {
  key: string;
  label: string;
  better: "lower" | "higher" | "neutral";
  unit: string;
  format: "number" | "percent" | "duration" | "count" | "money";
  description: string;
}

export interface DomainSpec {
  name: string;
  label: string;
  description: string;
  time_unit: string;
  entity_types: EntityType[];
  relationship_types: RelationshipType[];
  event_types: EventTypeSpec[];
  intervention_types: { type: InterventionType; label: string; description: string }[];
  metrics: MetricDef[];
  risk_metric: string;
  assumptions: string[];
  parameters: FieldSpec[];
  default_objectives: [string, number][];
  open_entity_types: boolean;
  default_until: number;
  features: string[];
  edge_meaning: string;
}

// ---- decisions ---------------------------------------------------------
export interface Objective {
  metric: string;
  weight: number;
  direction: "minimize" | "maximize" | null;
}

export interface Constraint {
  metric: string;
  op: "<=" | ">=" | "<" | ">";
  value: number;
  confidence: number | null;
  label: string;
}

export interface DecisionModel {
  objectives: Objective[];
  constraints: Constraint[];
}

export interface DecisionModelOut extends DecisionModel {
  is_default: boolean;
}

export interface EvaluateRequest {
  scenario_ids?: string[] | null;
  until: number;
  runs: number;
  base_seed?: number | null;
  baseline_id?: string | null;
  model?: DecisionModel | null;
}

export interface ConstraintCheck {
  metric: string;
  description: string;
  value: number | null;
  satisfied: boolean;
  satisfied_share: number | null;
}

export interface ObjectiveScore {
  metric: string;
  value: number | null;
  score: number;
  weight: number;
  contribution: number;
}

export interface FutureOut {
  id: string;
  name: string;
  rank: number;
  score: number;
  feasible: boolean;
  pareto: boolean;
  dominated_by: string[];
  values: Record<string, number | null>;
  metrics: Metrics;
  constraints: ConstraintCheck[];
  objectives: ObjectiveScore[];
  stats: Record<string, MetricStats> | null;
  risk: RiskSummary | null;
  drivers: Driver[];
}

export interface Insight {
  kind: "recommendation" | "tradeoff" | "dominated" | "constraint" | "risk" | "robustness" | "opportunity";
  text: string;
  future_ids: string[];
  metrics: string[];
}

export interface EvaluationOut {
  system_id: string;
  domain: string;
  until: number;
  runs: number;
  model: DecisionModel;
  futures: FutureOut[];
  skipped_objectives: string[];
  recommended: string | null;
  robust: boolean | null;
  weight_flips: { metric: string; factor: number; winner: string | null }[];
  baseline_id: string | null;
  insights: Insight[];
  elapsed_ms: number;
}

export interface SensitivityRow {
  id: string;
  kind: "attribute" | "parameter" | "event";
  target: string;
  key: string;
  value: number;
  low_value: number;
  high_value: number;
  low: number | null;
  high: number | null;
  swing: number;
}

export interface SensitivityOut {
  scenario_id: string;
  metric: string;
  baseline: number | null;
  delta: number;
  runs: number;
  rows: SensitivityRow[];
  elapsed_ms: number;
}
