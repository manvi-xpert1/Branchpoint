import { useEffect, useMemo, useState } from "react";
import { Bar, BarChart, CartesianGrid, Cell, ResponsiveContainer, Tooltip, XAxis, YAxis } from "recharts";
import { api } from "../api/client";
import type { EventDef, MonteCarloOut } from "../api/types";
import { binIndexOf, histogram } from "../lib/histogram";
import { ErrorNotice, errorMessage, fmt, Metric, NumberInput, pct } from "./common";

/**
 * "Run N times": runs the scenario with seeds seed, seed+1, ... and shows
 * the spread of downtime instead of a single number.
 */
export function MonteCarloPanel({ scenarioId, until, events, beforeRun }: {
  scenarioId: string;
  until: number;
  /** Resolved events, used to label the event-frequency list. */
  events: EventDef[];
  /** Saves unsaved edits first; returns false if that failed. */
  beforeRun: () => Promise<boolean>;
}) {
  const [runs, setRuns] = useState<number | null>(1000);
  const [result, setResult] = useState<MonteCarloOut | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  // Show the latest stored batch, if there is one.
  useEffect(() => {
    api.listMonteCarlo(scenarioId).then((list) => setResult(list[0] ?? null)).catch(() => {});
  }, [scenarioId]);

  const probabilistic = events.some((e) => e.probability < 1);

  const start = async () => {
    if (!(await beforeRun())) return;
    setBusy(true);
    setError(null);
    try {
      setResult(await api.runMonteCarlo(scenarioId, runs ?? 1000, until));
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
        Runs the scenario repeatedly with a different random seed each time (seed, seed + 1, …), so
        probabilistic events sometimes happen and sometimes don't. The result is a spread of outcomes
        rather than one number.
      </p>
      {!probabilistic && (
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
        <span className="small muted fixed">times, {fmt(until)} time units each</span>
        <button className="primary fixed" onClick={start} disabled={busy || !runs}>
          {busy ? <span className="spinner" /> : null} Run {runs ?? ""} times
        </button>
      </div>
      <ErrorNotice error={error} />
      {result && <MonteCarloResult result={result} events={events} />}
    </div>
  );
}

function MonteCarloResult({ result, events }: { result: MonteCarloOut; events: EventDef[] }) {
  const a = result.aggregates;
  const bins = useMemo(() => histogram(result.downtimes), [result.downtimes]);
  const p95Bar = binIndexOf(bins, a.downtime_p95);
  const data = bins.map((b) => ({ ...b, share: b.count / result.runs }));
  const label = (id: string) => {
    const e = events.find((x) => x.id === id);
    return e ? `${id} (p = ${e.probability})` : id;
  };

  return (
    <div className="stack" style={{ gap: 14, marginTop: 14 }}>
      <div className="notice warn small" role="note">
        These are <b>model estimates</b> from {result.runs} simulated runs of a rule-based model, not
        predictions of how your real system will behave.
      </div>

      <div className="metric-grid">
        <Metric label="Expected downtime" value={fmt(a.downtime_mean)} tone={a.downtime_mean > 0 ? "bad" : undefined}
          hint="Average downtime over all runs" />
        <Metric label="Typical (p50)" value={fmt(a.downtime_p50)} hint="Half the runs had at most this much downtime" />
        <Metric label="Bad case (p95)" value={fmt(a.downtime_p95)} tone={a.downtime_p95 > 0 ? "bad" : undefined}
          hint="95% of runs had at most this much downtime" />
        <Metric label="Worst run" value={fmt(a.downtime_max)} />
        <Metric label="Runs with downtime" value={pct(a.p_any_downtime)} />
        <Metric label="Mean availability" value={pct(a.availability_mean)} />
      </div>

      <div>
        <div className="small" style={{ fontWeight: 600, marginBottom: 6 }}>
          Downtime per run <span className="muted" style={{ fontWeight: 400 }}>· darker bar contains the p95</span>
        </div>
        <div style={{ height: 220 }} aria-label="Downtime histogram">
          <ResponsiveContainer>
            <BarChart data={data} margin={{ left: 0, right: 10, top: 4, bottom: 12 }}>
              <CartesianGrid strokeDasharray="3 3" vertical={false} />
              <XAxis dataKey="label" tick={{ fontSize: 12 }}
                label={{ value: "downtime (time units)", position: "insideBottom", offset: -2, fontSize: 12 }} height={40} />
              <YAxis allowDecimals={false} tick={{ fontSize: 12 }} width={40} />
              <Tooltip formatter={(v: number, _n, item) => [`${v} runs (${pct(item.payload.share)})`, "Runs"]}
                labelFormatter={(l) => `Downtime ${l}`} />
              <Bar dataKey="count" isAnimationActive={false}>
                {data.map((_, i) => (
                  <Cell key={i} fill={i === p95Bar ? "#991b1b" : "#f87171"} />
                ))}
              </Bar>
            </BarChart>
          </ResponsiveContainer>
        </div>
      </div>

      {Object.keys(a.event_frequency).length > 0 && (
        <table aria-label="Event frequency">
          <thead><tr><th>Event</th><th className="num">Happened in</th></tr></thead>
          <tbody>
            {Object.entries(a.event_frequency).map(([id, f]) => (
              <tr key={id}><td className="small">{label(id)}</td><td className="num">{pct(f)}</td></tr>
            ))}
          </tbody>
        </table>
      )}
      <div className="small muted">
        {result.runs} runs · seeds {result.base_seed}–{result.base_seed + result.runs - 1} · {fmt(result.until)} time units ·
        computed in {fmt(result.elapsed_ms / 1000)} s{result.deterministic ? " · deterministic scenario" : ""}
      </div>
    </div>
  );
}
