import { useMemo, useState } from "react";
import { Link } from "react-router-dom";
import { Bar, BarChart, CartesianGrid, Legend, ResponsiveContainer, Tooltip, XAxis, YAxis } from "recharts";
import { api } from "../api/client";
import type { CompareOut, Metrics } from "../api/types";
import { ErrorNotice, errorMessage, fmt, NumberInput, pct } from "../components/common";
import { useWorkspace } from "./workspace";

const COLUMNS: { key: keyof Metrics; label: string; render: (m: Metrics) => string }[] = [
  { key: "availability", label: "Availability", render: (m) => pct(m.availability) },
  { key: "downtime", label: "Downtime", render: (m) => fmt(m.downtime) },
  { key: "degraded_time", label: "Degraded", render: (m) => fmt(m.degraded_time) },
  { key: "affected_components", label: "Affected", render: (m) => String(m.affected_components) },
  { key: "recovery_time", label: "Recovery", render: (m) => m.affected_components === 0 ? "–" : m.recovery_time === null ? "not recovered" : fmt(m.recovery_time) },
  { key: "cost", label: "Cost", render: (m) => fmt(m.cost) },
];

export default function ComparePage() {
  const ws = useWorkspace();
  const [chosen, setChosen] = useState<string[]>(() => ws.scenarios.map((s) => s.id));
  const [until, setUntil] = useState(30);
  const [result, setResult] = useState<CompareOut | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  const toggle = (id: string) => setChosen((c) => (c.includes(id) ? c.filter((x) => x !== id) : [...c, id]));
  const ordered = ws.scenarios.filter((s) => chosen.includes(s.id)).map((s) => s.id);

  const compare = async () => {
    setBusy(true);
    setError(null);
    try { setResult(await api.compareScenarios(ordered, until)); } catch (e) { setError(errorMessage(e)); } finally { setBusy(false); }
  };

  const chartData = useMemo(() => result?.runs.map((r) => ({
    name: r.scenario_name.length > 26 ? r.scenario_name.slice(0, 24) + "…" : r.scenario_name,
    Downtime: r.metrics.downtime,
    Degraded: r.metrics.degraded_time,
  })) ?? [], [result]);

  return (
    <div className="page">
      <div className="page-narrow stack" style={{ gap: 16 }}>
        <div>
          <h1>Compare decisions</h1>
          <p className="muted" style={{ margin: "4px 0 0" }}>
            Run several scenarios with the same duration and compare their outcomes side by side.
            There is no single "best" decision: weigh downtime against cost for your own goals.
          </p>
        </div>
        <div className="card">
          <div className="row" style={{ marginBottom: 10 }}>
            <h2>Scenarios</h2>
            <div className="row fixed">
              <button className="small" onClick={() => setChosen(ws.scenarios.map((s) => s.id))}>All</button>
              <button className="small" onClick={() => setChosen([])}>None</button>
            </div>
          </div>
          <div className="grid2">
            {ws.scenarios.map((s) => (
              <label key={s.id} className="check" style={{ marginBottom: 4 }}>
                <input type="checkbox" checked={chosen.includes(s.id)} onChange={() => toggle(s.id)} />
                <span>{s.name}</span>
              </label>
            ))}
          </div>
          {ws.scenarios.length === 0 && <p className="muted">No scenarios yet. <Link to="../scenarios">Create one</Link>.</p>}
          <div className="row" style={{ justifyContent: "flex-start", marginTop: 12 }}>
            <span className="small muted fixed">Simulate for</span>
            <span className="fixed" style={{ width: 90 }}><NumberInput aria-label="Comparison duration" value={until} min={1} onChange={(v) => setUntil(v && v > 0 ? v : 30)} /></span>
            <span className="small muted fixed">time units</span>
            <button className="primary fixed" onClick={compare} disabled={busy || ordered.length === 0}>
              {busy ? <span className="spinner" /> : null} Run & compare {ordered.length || ""}
            </button>
          </div>
        </div>
        <ErrorNotice error={error} />

        {result && (
          <>
            <div className="card" style={{ padding: 0, overflow: "auto" }}>
              <table aria-label="Comparison">
                <thead>
                  <tr>
                    <th>Scenario</th>
                    {COLUMNS.map((c) => <th key={c.key} className="num">{c.label}</th>)}
                    <th />
                  </tr>
                </thead>
                <tbody>
                  {result.runs.map((r) => (
                    <tr key={r.id}>
                      <td>{r.scenario_name}</td>
                      {COLUMNS.map((c) => (
                        <td key={c.key} className={`num ${result.runs.length > 1 && result.best[c.key]?.includes(r.id) ? "best" : ""}`}>
                          {c.render(r.metrics)}
                        </td>
                      ))}
                      <td className="num"><Link to={`/systems/${ws.system.id}/runs/${r.id}`}>Playback</Link></td>
                    </tr>
                  ))}
                </tbody>
              </table>
              <div className="small muted" style={{ padding: "8px 12px" }}>Green marks the best value in each column.</div>
            </div>
            <div className="card">
              <h2 style={{ marginBottom: 12 }}>Time unavailable vs degraded</h2>
              <div style={{ height: 60 + chartData.length * 44 }}>
                <ResponsiveContainer>
                  <BarChart data={chartData} layout="vertical" margin={{ left: 20, right: 20 }}>
                    <CartesianGrid strokeDasharray="3 3" horizontal={false} />
                    <XAxis type="number" domain={[0, until]} />
                    <YAxis type="category" dataKey="name" width={190} tick={{ fontSize: 12 }} />
                    <Tooltip />
                    <Legend />
                    <Bar dataKey="Downtime" stackId="a" fill="#dc2626" />
                    <Bar dataKey="Degraded" stackId="a" fill="#f59e0b" />
                  </BarChart>
                </ResponsiveContainer>
              </div>
            </div>
          </>
        )}
      </div>
    </div>
  );
}
