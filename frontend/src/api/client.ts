import type {
  CompareOut,
  ImportOut,
  LogEntry,
  MonteCarloOut,
  ReplayOut,
  RunOut,
  RunSummary,
  ScenarioIn,
  ScenarioOut,
  SystemAnalysis,
  SystemDef,
  SystemOut,
  SystemSummary,
} from "./types";

export class ApiError extends Error {
  constructor(public status: number, message: string) {
    super(message);
  }
}

const BASE = import.meta.env.VITE_API_BASE ?? "";

async function request<T>(method: string, path: string, body?: unknown): Promise<T> {
  const res = await fetch(`${BASE}/api${path}`, {
    method,
    headers: body === undefined ? undefined : { "Content-Type": "application/json" },
    body: body === undefined ? undefined : JSON.stringify(body),
  });
  if (res.status === 204) return undefined as T;
  const text = await res.text();
  const data = text ? JSON.parse(text) : undefined;
  if (!res.ok) throw new ApiError(res.status, formatDetail(data?.detail) || res.statusText);
  return data as T;
}

/** FastAPI returns a string for our own errors and a list for schema errors. */
function formatDetail(detail: unknown): string {
  if (typeof detail === "string") return detail;
  if (Array.isArray(detail)) {
    return detail
      .map((d) => `${(d.loc ?? []).filter((p: unknown) => p !== "body").join(".")}: ${d.msg}`)
      .join("\n");
  }
  return "";
}

export const api = {
  listSystems: () => request<SystemSummary[]>("GET", "/systems"),
  getSystem: (id: string) => request<SystemOut>("GET", `/systems/${id}`),
  createSystem: (def: SystemDef) => request<SystemOut>("POST", "/systems", def),
  updateSystem: (id: string, def: SystemDef) => request<SystemOut>("PUT", `/systems/${id}`, def),
  deleteSystem: (id: string) => request<void>("DELETE", `/systems/${id}`),
  analyze: (def: SystemDef) => request<SystemAnalysis>("POST", "/analysis", def),
  exportSystem: (id: string) => request<unknown>("GET", `/systems/${id}/export`),
  importExperiment: (data: unknown) => request<ImportOut>("POST", "/experiments/import", data),

  listScenarios: (systemId: string) => request<ScenarioOut[]>("GET", `/systems/${systemId}/scenarios`),
  createScenario: (systemId: string, s: ScenarioIn) =>
    request<ScenarioOut>("POST", `/systems/${systemId}/scenarios`, s),
  updateScenario: (id: string, s: ScenarioIn) => request<ScenarioOut>("PUT", `/scenarios/${id}`, s),
  deleteScenario: (id: string) => request<void>("DELETE", `/scenarios/${id}`),
  branchScenario: (id: string, name?: string) =>
    request<ScenarioOut>("POST", `/scenarios/${id}/branch`, { name }),

  runScenario: (id: string, until: number) => request<RunOut>("POST", `/scenarios/${id}/runs`, { until }),
  listRuns: (scenarioId: string) => request<RunSummary[]>("GET", `/scenarios/${scenarioId}/runs`),
  getRun: (id: string) => request<RunOut>("GET", `/runs/${id}`),
  explain: (runId: string, seq: number) => request<LogEntry[]>("GET", `/runs/${runId}/explain/${seq}`),
  replay: (runId: string) => request<ReplayOut>("POST", `/runs/${runId}/replay`),
  compareScenarios: (scenarioIds: string[], until: number) =>
    request<CompareOut>("POST", "/compare", { scenario_ids: scenarioIds, until }),

  runMonteCarlo: (scenarioId: string, runs: number, until: number, baseSeed?: number | null) =>
    request<MonteCarloOut>("POST", `/scenarios/${scenarioId}/montecarlo`,
      { runs, until, base_seed: baseSeed ?? null }),
  listMonteCarlo: (scenarioId: string) =>
    request<MonteCarloOut[]>("GET", `/scenarios/${scenarioId}/montecarlo`),
};
