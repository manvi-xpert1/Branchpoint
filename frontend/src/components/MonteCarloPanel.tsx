import { useEffect, useMemo, useState } from "react";
import { Bar, BarChart, CartesianGrid, Cell, ResponsiveContainer, Tooltip, XAxis, YAxis } from "recharts";
import { api } from "../api/client";
import type { DomainSpec, EventDef, MonteCarloOut } from "../api/types";
import { formatMetric, metricDef, visibleMetrics } from "../lib/domains";
import { binIndexOf, histogram } from "../lib/histogram";
import { CHART } from "../lib/theme";
import { ErrorNotice, errorMessage, Metric, NumberInput, pct } from "./common";

/**
 * "Run N times": runs the scenario with seeds seed, seed+1, ... and shows the
 * spread of the domain's risk metric (downtime, mean wait, lost sales ...)
 * instead of a single number, plus what drives it.
 */
export function MonteCarloPanel({ spec, scenarioId, until, events, beforeRun }: {
  spec: DomainSpec;
  scenarioId: string;
  until: number;
  events: EventDef[];
  beforeRun: () => Promise<boolean>;
}) {
  const heavy = spec.name !== "software_infrastructure";
  const [runs, setRuns] = useState<number | null>(heavy ? 200 : 1000);
  const [result, setResult] = useState<MonteCarloOut | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    api.listMonteCarlo(scenarioId).then((list) => setResult(list[0] ?? null)).catch(() => {});
  }, [scenarioId]);

  const probabilistic = events.some((e) => e.probability < 1);

  const start = async () => {
    if (!(await beforeRun())) return;
    setBusy(true);
    setError(null);
    try {
      setResult(await api.runMonteCarlo(scenarioId, runs ?? 200, until));
    } catch (e) {
      setError(errorMessage(e));
    } finally {
      setBusy(false);
    }
  };

  return (
    <div className="card">
      <h2 style={{ marginBottom: 4 }}>Run many times (Monte Carlo)</h2>
      <p className="small muted" style={{ margin: "0 0 12px" }}>
        Runs the scenario repeatedly with a different random seed each time (seed, seed + 1, …). Probabilistic
        events sometimes happen and sometimes don't{heavy ? ", and arrivals or demand vary from run to run" : ""}, so
        the result is a spread of outcomes rather than one number.
      </p>
      {!probabilistic && !heavy && (
        <div className="notice info small" style={{ marginBottom: 12 }}>
          No event in this scenario has a probability below 1, so every run will be identical.
          Set an event's probability (for example 0.3) to see a spread.
        </div>
      )}
      <div className="row" style={{ justifyContent: "flex-start" }}>
        <span className="small muted fixed">Run</span>
        <span className="fixed" style={{ width: 90 }}>
          <NumberInput aria-label="Number of runs" value={runs} min={1} step={1}
            onChange={(v) => setRuns(v === null ? null : Math.max(1, Math.min(10_000, Math.round(v))))} />
        </span>
        <span className="small muted fixed">times, {until} {spec.time_unit} each</span>
        <button className="primary fixed" onClick={start} disabled={busy || !runs}>
          {busy ? <span className="spinner" /> : null} Run {runs ?? ""} times
        </button>
      </div>
      <ErrorNotice error={error} />
      {result && <MonteCarloResult spec={spec} result={result} events={events} />}
    </div>
  );
}

export function MonteCarloResult({ spec, result, events }: { spec: DomainSpec; result: MonteCarloOut; events: EventDef[] }) {
  const riskDef = metricDef(spec, result.risk_metric);
  const values = useMemo(() => (result.risk_values.length ? result.risk_values : result.downtimes)
    .filter((v): v is number => v !== null), [result]);
  const bins = useMemo(() => histogram(values), [values]);
  const risk = result.risk;
  const p95Bar = risk?.p95 !== null && risk?.p95 !== undefined ? binIndexOf(bins, risk.p95) : -1;
  const data = bins.map((b) => ({ ...b, share: b.count / result.runs }));
  const freq = Object.keys(result.event_frequency ?? {}).length ? result.event_frequency : result.aggregates?.event_frequency ?? {};
  const label = (id: string) => {
    const e = events.find((x) => x.id === id);
    return e ? `${id} (p = ${e.probability})` : id;
  };
  const stats = result.metric_stats ?? {};
  const rows = visibleMetrics(spec, [Object.fromEntries(Object.entries(stats).map(([k, s]) => [k, s.mean]))]);
  const higher = riskDef.better === "higher";

  return (
    <div className="stack" style={{ gap: 14, marginTop: 14 }}>
      <div className="notice warn small" role="note">
        These are <b>model estimates</b> from {result.runs} simulated runs, not predictions of how the real
        system will behave. They are only as good as the numbers and probabilities entered.
      </div>

      {risk && (
        <div className="metric-grid">
          <Metric label={`Expected ${riskDef.label.toLowerCase()}`} value={formatMetric(riskDef, risk.mean)}
            hint="Average over all runs" />
          <Metric label="Typical (p50)" value={formatMetric(riskDef, stats[riskDef.key]?.p50)} hint="Half the runs were better than this" />
          <Metric label={higher ? "Bad case (p5)" : "Bad case (p95)"} value={formatMetric(riskDef, risk.p95)}
            hint={higher ? "95% of runs did at least this well" : "95% of runs had at most this"} />
          <Metric label="Worst 5% of runs" value={formatMetric(riskDef, risk.worst_5_percent_mean)}
            hint="Average of the worst 5% (expected shortfall)" />
          {risk.p_nonzero !== null && <Metric label={`Runs with any ${riskDef.label.toLowerCase()}`} value={pct(risk.p_nonzero)} />}
        </div>
      )}

      <div>
        <div className="small" style={{ fontWeight: 600, marginBottom: 6 }}>
          {riskDef.label} per run <span className="muted" style={{ fontWeight: 400 }}>(the purple bar contains the bad case)</span>
        </div>
        <div style={{ height: 220 }} aria-label="Risk histogram">
          <ResponsiveContainer>
            <BarChart data={data} margin={{ left: 0, right: 10, top: 4, bottom: 12 }}>
              <CartesianGrid strokeDasharray="3 3" vertical={false} stroke={CHART.grid} />
              <XAxis dataKey="label" tick={{ fontSize: 12, fill: CHART.axis }} stroke={CHART.axis}
                label={{ value: `${riskDef.label.toLowerCase()}${riskDef.unit ? ` (${riskDef.unit})` : ""}`, position: "insideBottom", offset: -2, fontSize: 12, fill: CHART.axis }} height={40} />
              <YAxis allowDecimals={false} tick={{ fontSize: 12, fill: CHART.axis }} stroke={CHART.axis} width={40} />
              <Tooltip cursor={{ fill: "rgba(255,226,180,.08)" }} contentStyle={CHART.tooltip}
                formatter={(v, _n, item) => [`${v} runs (${pct((item.payload as { share: number }).share)})`, "Runs"]}
                labelFormatter={(l) => `${riskDef.label} ${l}`} />
              <Bar dataKey="count" isAnimationActive={false} radius={[8, 8, 2, 2]}>
                {data.map((_, i) => <Cell key={i} fill={i === p95Bar ? CHART.prob : CHART.info} />)}
              </Bar>
            </BarChart>
          </ResponsiveContainer>
        </div>
      </div>

      {result.drivers.length > 0 && (
        <table aria-label="Risk drivers">
          <thead><tr><th>Risk driver</th><th className="num">Happened in</th>
            <th className="num">{riskDef.label} when it happened</th><th className="num">when it didn't</th></tr></thead>
          <tbody>
            {result.drivers.map((d) => (
              <tr key={d.event_id}>
                <td className="small">{label(d.event_id)}</td>
                <td className="num">{pct(d.frequency)}</td>
                <td className="num">{formatMetric(riskDef, d.mean_if_occurred)}</td>
                <td className="num">{formatMetric(riskDef, d.mean_if_not)}</td>
              </tr>
            ))}
          </tbody>
        </table>
      )}

      {Object.keys(freq).length > 0 && result.drivers.length === 0 && (
        <table aria-label="Event frequency">
          <thead><tr><th>Event</th><th className="num">Happened in</th></tr></thead>
          <tbody>
            {Object.entries(freq).map(([id, f]) => (
              <tr key={id}><td className="small">{label(id)}</td><td className="num">{pct(f)}</td></tr>
            ))}
          </tbody>
        </table>
      )}

      {rows.length > 0 && (
        <details>
          <summary className="small"><b>Spread of every metric</b></summary>
          <table aria-label="Metric spread" style={{ marginTop: 8 }}>
            <thead><tr><th>Metric</th><th className="num">Mean</th><th className="num">p5</th><th className="num">p50</th><th className="num">p95</th></tr></thead>
            <tbody>
              {rows.map((m) => (
                <tr key={m.key}>
                  <td className="small">{m.label}</td>
                  <td className="num">{formatMetric(m, stats[m.key].mean)}</td>
                  <td className="num">{formatMetric(m, stats[m.key].p5)}</td>
                  <td className="num">{formatMetric(m, stats[m.key].p50)}</td>
                  <td className="num">{formatMetric(m, stats[m.key].p95)}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </details>
      )}
      <div className="small muted">
        {result.runs} runs · seeds {result.base_seed}–{result.base_seed + result.runs - 1} · {result.until} {spec.time_unit} ·
        computed in {(result.elapsed_ms / 1000).toFixed(2)} s{result.deterministic ? " · no probabilistic events" : ""}
      </div>
    </div>
  );
}
