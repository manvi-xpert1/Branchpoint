import { useMemo, useState } from "react";
import { Link } from "react-router-dom";
import { Bar, BarChart, CartesianGrid, Cell, ResponsiveContainer, Tooltip, XAxis, YAxis } from "recharts";
import { api } from "../api/client";
import type { CompareOut, MonteCarloOut } from "../api/types";
import { ErrorNotice, errorMessage, NumberInput } from "../components/common";
import { bestIds, formatMetric, metricDef, visibleMetrics } from "../lib/domains";
import { CHART } from "../lib/theme";
import { useWorkspace } from "./workspace";

export default function ComparePage() {
  const ws = useWorkspace();
  const spec = ws.spec;
  const [chosen, setChosen] = useState<string[]>(() => ws.scenarios.map((s) => s.id));
  const [until, setUntil] = useState(spec.default_until);
  const [result, setResult] = useState<CompareOut | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const [withSpread, setWithSpread] = useState(false);
  const [mcRuns, setMcRuns] = useState<number | null>(spec.name === "software_infrastructure" ? 500 : 100);
  const [spread, setSpread] = useState<Record<string, MonteCarloOut>>({});
  const [chartMetric, setChartMetric] = useState(spec.risk_metric);

  const toggle = (id: string) => setChosen((c) => (c.includes(id) ? c.filter((x) => x !== id) : [...c, id]));
  const ordered = ws.scenarios.filter((s) => chosen.includes(s.id)).map((s) => s.id);

  const compare = async () => {
    setBusy(true);
    setError(null);
    setSpread({});
    try {
      setResult(await api.compareScenarios(ordered, until));
      if (withSpread) {
        // One scenario at a time, so a local SQLite database is never written to concurrently.
        const out: Record<string, MonteCarloOut> = {};
        for (const id of ordered) {
          out[id] = await api.runMonteCarlo(id, mcRuns ?? 100, until);
          setSpread({ ...out });
        }
      }
    } catch (e) {
      setError(errorMessage(e));
    } finally {
      setBusy(false);
    }
  };

  const columns = useMemo(() => (result ? visibleMetrics(spec, result.runs.map((r) => r.metrics)) : []), [result, spec]);
  const risk = metricDef(spec, spec.risk_metric);
  const hasSpread = Object.keys(spread).length > 0;
  const spreadBest = (pick: (m: MonteCarloOut) => number | null | undefined) =>
    bestIds(risk, Object.entries(spread).map(([id, m]) => ({ id, value: pick(m) })));
  const bestMean = spreadBest((m) => m.risk?.mean);
  const bestBad = spreadBest((m) => m.risk?.p95);
  const chartDef = metricDef(spec, chartMetric);
  const chartData = useMemo(() => result?.runs.map((r) => ({
    name: r.scenario_name.length > 30 ? r.scenario_name.slice(0, 28) + "…" : r.scenario_name,
    value: r.metrics[chartMetric] ?? 0,
    best: result.best[chartMetric]?.includes(r.id) ?? false,
  })) ?? [], [result, chartMetric]);

  return (
    <div className="page">
      <div className="page-narrow stack" style={{ gap: 16 }}>
        <div>
          <h1>Compare scenarios</h1>
          <p className="muted" style={{ margin: "4px 0 0" }}>
            Run several scenarios over the same window and compare every metric side by side. To weigh the
            metrics against your goals and get a ranking, use <Link to={`/systems/${ws.system.id}/futures`}>Futures</Link>.
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
          {ws.scenarios.length === 0 && <p className="muted">No scenarios yet. <Link to={`/systems/${ws.system.id}/scenarios`}>Create one</Link>.</p>}
          <div className="row" style={{ justifyContent: "flex-start", marginTop: 12, flexWrap: "wrap" }}>
            <span className="small muted fixed">Simulate for</span>
            <span className="fixed" style={{ width: 90 }}><NumberInput aria-label="Comparison duration" value={until} min={1} onChange={(v) => setUntil(v && v > 0 ? v : spec.default_until)} /></span>
            <span className="small muted fixed">{spec.time_unit}</span>
            <label className="check fixed" style={{ margin: 0 }}>
              <input type="checkbox" checked={withSpread} onChange={(e) => setWithSpread(e.target.checked)} />
              <span className="small">also run each</span>
            </label>
            <span className="fixed" style={{ width: 80 }}><NumberInput aria-label="Monte Carlo runs" value={mcRuns} min={1} step={1}
              onChange={(v) => setMcRuns(v === null ? null : Math.max(1, Math.min(10_000, Math.round(v))))} /></span>
            <span className="small muted fixed">times</span>
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
                    {columns.map((c) => <th key={c.key} className="num" title={c.description}>{c.label}</th>)}
                    {hasSpread && <th className="num" title={`Average ${risk.label.toLowerCase()} over the Monte Carlo runs`}>Expected {risk.label.toLowerCase()}</th>}
                    {hasSpread && <th className="num" title="Bad case over the Monte Carlo runs">Bad case</th>}
                    <th />
                  </tr>
                </thead>
                <tbody>
                  {result.runs.map((r) => (
                    <tr key={r.id}>
                      <td>{r.scenario_name}</td>
                      {columns.map((c) => (
                        <td key={c.key} className={`num ${result.runs.length > 1 && result.best[c.key]?.includes(r.id) ? "best" : ""}`}>
                          {formatMetric(c, r.metrics[c.key])}
                        </td>
                      ))}
                      {hasSpread && (spread[r.scenario_id] ? (
                        <>
                          <td className={`num ${bestMean.includes(r.scenario_id) ? "best" : ""}`}>{formatMetric(risk, spread[r.scenario_id].risk?.mean)}</td>
                          <td className={`num ${bestBad.includes(r.scenario_id) ? "best" : ""}`}>{formatMetric(risk, spread[r.scenario_id].risk?.p95)}</td>
                        </>
                      ) : <><td className="num muted">…</td><td className="num muted">…</td></>)}
                      <td className="num"><Link to={`/systems/${ws.system.id}/runs/${r.id}`}>Playback</Link></td>
                    </tr>
                  ))}
                </tbody>
              </table>
              <div className="small muted" style={{ padding: "8px 12px" }}>
                Green marks the best value in each column (lower or higher, as the domain defines).
                {hasSpread && <> The single-run columns use each scenario's own seed; the last two columns are
                  <b> model estimates</b> over {Object.values(spread)[0].runs} runs, not predictions of the real system.</>}
              </div>
            </div>
            <div className="card">
              <div className="row" style={{ marginBottom: 12 }}>
                <h2>{chartDef.label} by scenario</h2>
                <select className="fixed" style={{ width: 240 }} aria-label="Chart metric" value={chartMetric}
                  onChange={(e) => setChartMetric(e.target.value)}>
                  {columns.map((c) => <option key={c.key} value={c.key}>{c.label}</option>)}
                </select>
              </div>
              <div style={{ height: 60 + chartData.length * 44 }}>
                <ResponsiveContainer>
                  <BarChart data={chartData} layout="vertical" margin={{ left: 20, right: 30 }}>
                    <CartesianGrid strokeDasharray="3 3" horizontal={false} stroke={CHART.grid} />
                    <XAxis type="number" tick={{ fontSize: 12, fill: CHART.axis }} stroke={CHART.axis}
                      tickFormatter={(v) => formatMetric(chartDef, v)} />
                    <YAxis type="category" dataKey="name" width={230} tick={{ fontSize: 12, fill: CHART.cream }} stroke={CHART.axis} />
                    <Tooltip contentStyle={CHART.tooltip} formatter={(v) => [formatMetric(chartDef, Number(v), true), chartDef.label]} />
                    <Bar dataKey="value" radius={[0, 8, 8, 0]} isAnimationActive={false}>
                      {chartData.map((d, i) => <Cell key={i} fill={d.best ? CHART.ok : CHART.info} />)}
                    </Bar>
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
