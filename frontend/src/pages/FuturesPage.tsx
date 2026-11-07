import { useEffect, useMemo, useRef, useState } from "react";
import { Link, useNavigate, useSearchParams } from "react-router-dom";
import {
  Bar, BarChart, CartesianGrid, Legend, ReferenceLine, ResponsiveContainer, Scatter, ScatterChart, Tooltip, XAxis, YAxis, ZAxis,
} from "recharts";
import { api } from "../api/client";
import type {
  Constraint, DecisionModel, DomainSpec, EvaluationOut, FutureOut, Insight, MetricDef, SensitivityOut,
} from "../api/types";
import { ErrorNotice, errorMessage, NumberInput, pct } from "../components/common";
import { useToast } from "../components/Toast";
import {
  bestIds, defaultGroup, formatMetric, futureGroups, inputLabel, metricDef, tornadoData, visibleMetrics,
} from "../lib/domains";
import { CHART } from "../lib/theme";
import { toDef, useWorkspace } from "./workspace";

const RUN_OPTIONS = [1, 50, 200, 500];

export default function FuturesPage() {
  const ws = useWorkspace();
  const spec = ws.spec;
  const navigate = useNavigate();
  const toast = useToast();
  const groups = useMemo(() => futureGroups(ws.scenarios), [ws.scenarios]);
  const [params] = useSearchParams();
  const [groupId, setGroupId] = useState(() => {
    const wanted = params.get("group");
    return groups.some((g) => g.id === wanted) ? wanted! : defaultGroup(groups, ws.scenarios)?.id ?? "all";
  });
  const group = groups.find((g) => g.id === groupId) ?? groups[0];
  const [runs, setRuns] = useState(1);
  const [until, setUntil] = useState(spec.default_until);
  const [saved, setSaved] = useState<DecisionModel | null>(null);
  const [isDefault, setIsDefault] = useState(true);
  const [model, setModel] = useState<DecisionModel | null>(null);
  const [result, setResult] = useState<EvaluationOut | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [focus, setFocus] = useState<string | null>(null);
  const requestId = useRef(0);

  useEffect(() => {
    api.getObjectives(ws.system.id).then((m) => {
      const clean = { objectives: m.objectives, constraints: m.constraints };
      setSaved(clean);
      setModel(clean);
      setIsDefault(m.is_default);
    }).catch((e) => setError(errorMessage(e)));
  }, [ws.system.id]);

  const evaluate = async () => {
    if (!model || !group) return;
    const id = ++requestId.current;
    setBusy(true);
    setError(null);
    try {
      const out = await api.evaluate(ws.system.id, { scenario_ids: group.scenarioIds, until, runs, model });
      if (id === requestId.current) setResult(out);
    } catch (e) {
      if (id === requestId.current) setError(errorMessage(e));
    } finally {
      if (id === requestId.current) setBusy(false);
    }
  };

  // With one run per future, re-evaluate as the weights change (it is fast). Monte Carlo waits for the button.
  const key = JSON.stringify([model, groupId, until, runs]);
  useEffect(() => {
    if (!model || !group || runs !== 1) return;
    const handle = window.setTimeout(evaluate, 450);
    return () => window.clearTimeout(handle);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [key]);

  const dirty = !!saved && !!model && JSON.stringify(saved) !== JSON.stringify(model);
  const saveModel = async () => {
    if (!model) return;
    try {
      const m = await api.setObjectives(ws.system.id, model);
      setSaved({ objectives: m.objectives, constraints: m.constraints });
      setIsDefault(m.is_default);
      toast("Objectives saved for this system");
    } catch (e) { setError(errorMessage(e)); }
  };
  const resetModel = async () => {
    try {
      const m = await api.setObjectives(ws.system.id, null);
      const clean = { objectives: m.objectives, constraints: m.constraints };
      setSaved(clean); setModel(clean); setIsDefault(true);
      toast(`Back to the ${spec.label.toLowerCase()} defaults`);
    } catch (e) { setError(errorMessage(e)); }
  };

  const playback = async (scenarioId: string) => {
    try {
      const run = await api.runScenario(scenarioId, until);
      navigate(`/systems/${ws.system.id}/runs/${run.id}`);
    } catch (e) { setError(errorMessage(e)); }
  };

  if (!ws.scenarios.length) {
    return (
      <div className="page"><div className="card empty page-narrow">
        <h2 style={{ marginBottom: 8 }}>No futures yet</h2>
        <p>Create a scenario, then branch it to try different decisions. Each branch is an alternative future.</p>
        <Link className="btn primary" to={`/systems/${ws.system.id}/scenarios`}>Go to Scenarios</Link>
      </div></div>
    );
  }

  return (
    <div className="split">
      <aside className="sidebar">
        {model && (
          <ObjectivesEditor spec={spec} model={model} onChange={setModel} runs={runs}
            dirty={dirty} isDefault={isDefault} onSave={saveModel} onReset={resetModel}
            skipped={result?.skipped_objectives ?? []} />
        )}
      </aside>
      <div className="page">
        <div className="stack" style={{ gap: 16, maxWidth: 1180, margin: "0 auto" }}>
          <div>
            <h1>Alternative futures</h1>
            <p className="muted" style={{ margin: "4px 0 0" }}>
              Every scenario below is simulated, then scored against your objectives. Scores are relative to
              the futures compared here (100 = best on everything you care about).
            </p>
          </div>

          <div className="card controls-card">
            <label className="field" style={{ flex: "2 1 260px" }}>
              <span>Futures to compare</span>
              <select aria-label="Futures to compare" value={group?.id} onChange={(e) => { setGroupId(e.target.value); setResult(null); }}>
                {groups.map((g) => <option key={g.id} value={g.id}>{g.label}</option>)}
              </select>
            </label>
            <label className="field" style={{ flex: "1 1 170px" }}>
              <span>Runs per future</span>
              <select aria-label="Runs per future" value={runs} onChange={(e) => { setRuns(Number(e.target.value)); setResult(null); }}>
                {RUN_OPTIONS.map((r) => <option key={r} value={r}>{r === 1 ? "1 (seeded, instant)" : `${r} (Monte Carlo)`}</option>)}
              </select>
            </label>
            <label className="field" style={{ flex: "1 1 130px" }}>
              <span>Window ({spec.time_unit})</span>
              <NumberInput aria-label="Simulation window" value={until} min={1} onChange={(v) => setUntil(v && v > 0 ? v : spec.default_until)} />
            </label>
            <button className="primary" style={{ alignSelf: "flex-end", marginBottom: 10 }} onClick={evaluate} disabled={busy || !model}>
              {busy ? <span className="spinner" /> : null} {runs === 1 ? "Evaluate" : `Simulate ${runs * (group?.scenarioIds.length ?? 0)} runs`}
            </button>
          </div>
          {runs > 1 && !result && !busy && (
            <div className="notice info small">Monte Carlo runs each future {runs} times. With
              many futures this can take a little while; scores then use the average of the runs.</div>
          )}
          <ErrorNotice error={error} />
          {busy && !result && <div className="empty"><span className="spinner" /> Simulating futures…</div>}

          {result && (
            <Results spec={spec} result={result} busy={busy} focus={focus} setFocus={setFocus} onPlayback={playback} />
          )}
          {result && <SensitivityPanel spec={spec} result={result} until={until} focus={focus} setFocus={setFocus} />}

          <details className="card">
            <summary><b>How this model works ({spec.label})</b></summary>
            <ul className="small muted" style={{ paddingLeft: 18, margin: "10px 0 0", lineHeight: 1.6 }}>
              {spec.assumptions.map((a) => <li key={a}>{a}</li>)}
              <li>Scores use min-max normalisation across the futures shown: the best value of each objective scores 1,
                the worst 0, and the weighted average is shown out of 100.</li>
            </ul>
          </details>
        </div>
      </div>
    </div>
  );
}

// ---- objectives & constraints -------------------------------------------------
function ObjectivesEditor({ spec, model, onChange, runs, dirty, isDefault, onSave, onReset, skipped }: {
  spec: DomainSpec; model: DecisionModel; onChange: (m: DecisionModel) => void; runs: number;
  dirty: boolean; isDefault: boolean; onSave: () => void; onReset: () => void; skipped: string[];
}) {
  const used = new Set(model.objectives.map((o) => o.metric));
  const available = spec.metrics.filter((m) => m.better !== "neutral" && !used.has(m.key));
  const setObjectives = (objectives: DecisionModel["objectives"]) => onChange({ ...model, objectives });
  const setConstraints = (constraints: Constraint[]) => onChange({ ...model, constraints });
  return (
    <>
      <div className="section">
        <div className="row" style={{ marginBottom: 4 }}>
          <h3 style={{ margin: 0 }}>What matters to you</h3>
          {dirty && <span className="pill warn fixed">unsaved</span>}
        </div>
        <p className="small muted" style={{ margin: "0 0 12px" }}>
          Drag a weight to say how much an objective matters. 0 ignores it.
        </p>
        {model.objectives.map((o, i) => {
          const def = metricDef(spec, o.metric);
          return (
            <div key={o.metric} className="objective" data-testid={`objective-${o.metric}`}>
              <div className="row">
                <span className="small" style={{ fontWeight: 600 }}>{def.label}</span>
                <span className="small muted fixed">{def.better === "higher" ? "higher is better" : "lower is better"}</span>
                <button className="ghost small fixed" aria-label={`Remove ${def.label}`}
                  onClick={() => setObjectives(model.objectives.filter((_, j) => j !== i))}>✕</button>
              </div>
              <div className="row">
                <input type="range" min={0} max={5} step={0.5} value={o.weight} aria-label={`Weight of ${def.label}`}
                  onChange={(e) => setObjectives(model.objectives.map((x, j) => (j === i ? { ...x, weight: Number(e.target.value) } : x)))} />
                <span className="weight fixed">×{o.weight}</span>
              </div>
              {skipped.includes(o.metric) && <div className="small muted">No data in these futures, so it is ignored.</div>}
            </div>
          );
        })}
        {available.length > 0 && (
          <select aria-label="Add objective" value="" onChange={(e) => e.target.value &&
            setObjectives([...model.objectives, { metric: e.target.value, weight: 1, direction: null }])}>
            <option value="">+ Add an objective…</option>
            {available.map((m) => <option key={m.key} value={m.key}>{m.label}</option>)}
          </select>
        )}
      </div>

      <div className="section">
        <h3>Hard limits</h3>
        <p className="small muted" style={{ margin: "-4px 0 10px" }}>A future that breaks a limit is ranked last, whatever its score.</p>
        {model.constraints.map((c, i) => (
          <ConstraintRow key={i} spec={spec} c={c} runs={runs}
            onChange={(n) => setConstraints(model.constraints.map((x, j) => (j === i ? n : x)))}
            onRemove={() => setConstraints(model.constraints.filter((_, j) => j !== i))} />
        ))}
        <button className="small" onClick={() => {
          const m = spec.metrics.find((x) => x.better !== "neutral")!;
          setConstraints([...model.constraints, { metric: m.key, op: m.better === "higher" ? ">=" : "<=",
            value: m.format === "percent" ? 0.95 : 0, confidence: null, label: "" }]);
        }}>+ Add a limit</button>
      </div>

      <div className="section row" style={{ flexWrap: "wrap" }}>
        <button className="fixed" onClick={onSave} disabled={!dirty}>Save for this system</button>
        <button className="fixed ghost" onClick={onReset} disabled={isDefault && !dirty}>Reset to defaults</button>
      </div>
    </>
  );
}

function ConstraintRow({ spec, c, runs, onChange, onRemove }: {
  spec: DomainSpec; c: Constraint; runs: number; onChange: (c: Constraint) => void; onRemove: () => void;
}) {
  const def = metricDef(spec, c.metric);
  const percent = def.format === "percent";
  return (
    <div className="editable-row" style={{ padding: 10 }}>
      <div className="row" style={{ marginBottom: 6 }}>
        <select aria-label="Limit metric" value={c.metric} onChange={(e) => onChange({ ...c, metric: e.target.value })}>
          {spec.metrics.filter((m) => m.better !== "neutral").map((m) => <option key={m.key} value={m.key}>{m.label}</option>)}
        </select>
        <button className="ghost small fixed" onClick={onRemove} aria-label="Remove limit">✕</button>
      </div>
      <div className="row">
        <select className="fixed" style={{ width: 64 }} aria-label="Limit operator" value={c.op}
          onChange={(e) => onChange({ ...c, op: e.target.value as Constraint["op"] })}>
          {["<=", ">=", "<", ">"].map((op) => <option key={op} value={op}>{op.replace("<=", "≤").replace(">=", "≥")}</option>)}
        </select>
        <NumberInput aria-label="Limit value" value={percent ? Math.round(c.value * 1000) / 10 : c.value}
          onChange={(v) => onChange({ ...c, value: v === null ? 0 : percent ? v / 100 : v })} />
        <span className="small muted fixed">{percent ? "%" : def.unit}</span>
      </div>
      {runs > 1 && (
        <label className="check small" style={{ marginTop: 6, marginBottom: 0 }}>
          <input type="checkbox" checked={c.confidence !== null}
            onChange={(e) => onChange({ ...c, confidence: e.target.checked ? 0.9 : null })} />
          {c.confidence === null ? <span>Only require it in a share of runs</span> : <>
            <span>in at least</span>
            <span style={{ width: 64 }}><NumberInput aria-label="Confidence" value={Math.round(c.confidence * 100)} min={1}
              onChange={(v) => onChange({ ...c, confidence: Math.min(1, Math.max(0.01, (v ?? 90) / 100)) })} /></span>
            <span>% of runs</span>
          </>}
        </label>
      )}
    </div>
  );
}

// ---- results --------------------------------------------------------------------
function Results({ spec, result, busy, focus, setFocus, onPlayback }: {
  spec: DomainSpec; result: EvaluationOut; busy: boolean; focus: string | null;
  setFocus: (id: string) => void; onPlayback: (id: string) => void;
}) {
  const names = Object.fromEntries(result.futures.map((f) => [f.id, f.name]));
  const objectiveDefs = result.model.objectives.filter((o) => o.weight > 0 && !result.skipped_objectives.includes(o.metric))
    .map((o) => metricDef(spec, o.metric));
  const rec = result.futures.find((f) => f.id === result.recommended);
  const headline = result.insights.find((i) => i.kind === "recommendation") ?? result.insights[0];
  const robustness = result.insights.find((i) => i.kind === "robustness");

  return (
    <div className="stack" style={{ gap: 16, opacity: busy ? 0.6 : 1, transition: "opacity .2s" }}>
      <div className={`card recommendation ${rec ? "" : "none"}`}>
        <div className="small" style={{ textTransform: "uppercase", letterSpacing: ".08em", opacity: .8 }}>
          {rec ? "Best future for your objectives" : "No future meets every limit"}
        </div>
        <h2 style={{ fontSize: 24, margin: "4px 0 6px" }}>{rec ? rec.name : "Relax a limit or try another decision"}</h2>
        {headline && <p style={{ margin: 0 }}>{headline.text}</p>}
        {robustness && <p className="small" style={{ margin: "6px 0 0", opacity: .85 }}>{robustness.text}</p>}
        <div className="small" style={{ marginTop: 8, opacity: .75 }}>
          {result.futures.length} futures · {result.runs === 1 ? "one seeded run each" : `${result.runs} runs each (means)`} ·
          {" "}{result.until} {spec.time_unit} · computed in {(result.elapsed_ms / 1000).toFixed(2)} s
        </div>
      </div>

      <div className="futures-grid">
        {result.futures.map((f) => (
          <FutureCard key={f.id} spec={spec} f={f} defs={objectiveDefs} names={names} recommended={f.id === result.recommended}
            focused={focus === f.id} onFocus={() => setFocus(f.id)} onPlayback={() => onPlayback(f.id)} runs={result.runs} />
        ))}
      </div>

      <div className="grid-2-cols">
        <TradeoffChart spec={spec} result={result} defs={objectiveDefs} />
        <InsightList insights={result.insights} names={names} />
      </div>

      <MetricTable spec={spec} result={result} />
      {result.runs > 1 && <RiskTable spec={spec} result={result} />}
    </div>
  );
}

function FutureCard({ spec, f, defs, names, recommended, focused, onFocus, onPlayback, runs }: {
  spec: DomainSpec; f: FutureOut; defs: MetricDef[]; names: Record<string, string>; recommended: boolean;
  focused: boolean; onFocus: () => void; onPlayback: () => void; runs: number;
}) {
  const score = Math.round(f.score * 100);
  return (
    <div className={`card future ${recommended ? "best" : ""} ${f.feasible ? "" : "infeasible"} ${focused ? "focused" : ""}`}
      data-testid={`future-${f.rank}`}>
      <div className="row" style={{ alignItems: "flex-start" }}>
        <span className="rank fixed">{f.rank}</span>
        <div style={{ minWidth: 0 }}>
          <div className="future-name" title={f.name}>{f.name}</div>
          <div className="tags">
            {recommended && <span className="pill healthy">recommended</span>}
            {f.pareto && <span className="pill info" title="No other future is at least as good on every objective">Pareto</span>}
            {!f.feasible && <span className="pill failed">breaks a limit</span>}
            {f.dominated_by.length > 0 && <span className="pill" title="Another future is at least as good on every objective">beaten by {names[f.dominated_by[0]]}</span>}
          </div>
        </div>
        <span className="score fixed" aria-label={`Score ${score}`}>{score}</span>
      </div>
      <div className="score-bar"><span style={{ width: `${Math.max(2, score)}%` }} /></div>
      <dl className="kv">
        {defs.slice(0, 4).map((d) => {
          const s = f.objectives.find((o) => o.metric === d.key);
          return (
            <div key={d.key}>
              <dt>{d.label}</dt>
              <dd className={s?.score === 1 ? "good" : s?.score === 0 ? "poor" : ""}>{formatMetric(d, f.values[d.key] ?? f.metrics[d.key], true)}</dd>
            </div>
          );
        })}
      </dl>
      {f.constraints.filter((c) => !c.satisfied).map((c) => (
        <div key={c.description} className="small" style={{ color: "var(--bad)" }}>
          ✕ {c.description}: {formatMetric(metricDef(spec, c.metric), c.value)}
          {c.satisfied_share !== null && runs > 1 ? ` (holds in ${pct(c.satisfied_share)} of runs)` : ""}
        </div>
      ))}
      <div className="row" style={{ marginTop: 8, justifyContent: "flex-start" }}>
        <button className="small fixed" onClick={onPlayback} title="Run once and watch it unfold">▶ Playback</button>
        <button className="small fixed" onClick={onFocus} title="Which inputs move this future the most?">What matters?</button>
      </div>
    </div>
  );
}

const KIND_ICON: Record<Insight["kind"], string> = {
  recommendation: "★", tradeoff: "⇄", dominated: "▽", constraint: "!", risk: "⚠", robustness: "⚖", opportunity: "↗",
};

function InsightList({ insights, names }: { insights: Insight[]; names: Record<string, string> }) {
  return (
    <div className="card">
      <h2 style={{ marginBottom: 10 }}>Insights</h2>
      <p className="small muted" style={{ margin: "-4px 0 10px" }}>Generated from the simulated numbers above.</p>
      <ul className="insights">
        {insights.map((i, k) => (
          <li key={k} className={`insight ${i.kind}`} title={i.future_ids.map((id) => names[id]).join(", ")}>
            <span className="icon" aria-hidden>{KIND_ICON[i.kind]}</span><span>{i.text}</span>
          </li>
        ))}
      </ul>
    </div>
  );
}

function TradeoffChart({ spec, result, defs }: { spec: DomainSpec; result: EvaluationOut; defs: MetricDef[] }) {
  const options = visibleMetrics(spec, result.futures.map((f) => f.metrics)).filter((m) => m.better !== "neutral");
  const [x, setX] = useState(defs[0]?.key ?? options[0]?.key);
  const [y, setY] = useState(defs[1]?.key ?? options[1]?.key ?? options[0]?.key);
  const xd = metricDef(spec, x);
  const yd = metricDef(spec, y);
  const point = (f: FutureOut) => ({ x: f.metrics[x] ?? 0, y: f.metrics[y] ?? 0, name: f.name, rank: f.rank });
  const sets = [
    { name: "Recommended", color: CHART.gold, data: result.futures.filter((f) => f.id === result.recommended).map(point) },
    { name: "Pareto", color: CHART.ok, data: result.futures.filter((f) => f.pareto && f.feasible && f.id !== result.recommended).map(point) },
    { name: "Beaten", color: CHART.info, data: result.futures.filter((f) => !f.pareto && f.feasible).map(point) },
    { name: "Breaks a limit", color: CHART.bad, data: result.futures.filter((f) => !f.feasible).map(point) },
  ].filter((s) => s.data.length);
  return (
    <div className="card">
      <h2 style={{ marginBottom: 8 }}>Trade-offs</h2>
      <div className="row" style={{ marginBottom: 8 }}>
        <select aria-label="Horizontal axis" value={x} onChange={(e) => setX(e.target.value)}>
          {options.map((m) => <option key={m.key} value={m.key}>→ {m.label}</option>)}
        </select>
        <select aria-label="Vertical axis" value={y} onChange={(e) => setY(e.target.value)}>
          {options.map((m) => <option key={m.key} value={m.key}>↑ {m.label}</option>)}
        </select>
      </div>
      <div style={{ height: 280 }} aria-label="Trade-off chart">
        <ResponsiveContainer>
          <ScatterChart margin={{ left: 6, right: 16, top: 10, bottom: 20 }}>
            <CartesianGrid strokeDasharray="3 3" stroke={CHART.grid} />
            <XAxis type="number" dataKey="x" name={xd.label} tick={{ fontSize: 11, fill: CHART.axis }} stroke={CHART.axis}
              tickFormatter={(v) => formatMetric(xd, v)} domain={["auto", "auto"]}
              label={{ value: `${xd.label} (${xd.better} is better)`, position: "insideBottom", offset: -10, fontSize: 11, fill: CHART.axis }} />
            <YAxis type="number" dataKey="y" name={yd.label} tick={{ fontSize: 11, fill: CHART.axis }} stroke={CHART.axis}
              tickFormatter={(v) => formatMetric(yd, v)} width={64} domain={["auto", "auto"]} />
            <ZAxis range={[90, 90]} />
            <Tooltip contentStyle={CHART.tooltip} cursor={{ strokeDasharray: "3 3", stroke: CHART.axis }}
              content={({ payload }) => {
                const p = payload?.[0]?.payload as { name: string; x: number; y: number; rank: number } | undefined;
                return p ? (
                  <div style={{ ...CHART.tooltip, padding: "8px 10px" }}>
                    <b>#{p.rank} {p.name}</b><br />{xd.label}: {formatMetric(xd, p.x, true)}<br />{yd.label}: {formatMetric(yd, p.y, true)}
                  </div>
                ) : null;
              }} />
            <Legend wrapperStyle={{ fontSize: 12, color: CHART.cream }} />
            {sets.map((s) => <Scatter key={s.name} name={s.name} data={s.data} fill={s.color} isAnimationActive={false} />)}
          </ScatterChart>
        </ResponsiveContainer>
      </div>
      <p className="small muted" style={{ margin: 0 }}>
        Pareto futures are the defensible choices: no other future beats them on every objective. Which one is
        best depends on your weights.
      </p>
    </div>
  );
}

function MetricTable({ spec, result }: { spec: DomainSpec; result: EvaluationOut }) {
  const cols = visibleMetrics(spec, result.futures.map((f) => f.metrics));
  const best = Object.fromEntries(cols.map((c) => [c.key, bestIds(c, result.futures.map((f) => ({ id: f.id, value: f.metrics[c.key] })))]));
  return (
    <div className="card" style={{ padding: 0, overflow: "auto" }}>
      <div style={{ padding: "16px 18px 6px" }}>
        <h2>Every metric</h2>
        {result.runs > 1 && <p className="small muted" style={{ margin: "4px 0 0" }}>Averages over {result.runs} runs per future.</p>}
      </div>
      <table aria-label="Metrics of every future">
        <thead><tr><th>Future</th>{cols.map((c) => <th key={c.key} className="num" title={c.description}>{c.label}</th>)}</tr></thead>
        <tbody>
          {result.futures.map((f) => (
            <tr key={f.id}>
              <td>#{f.rank} {f.name}</td>
              {cols.map((c) => <td key={c.key} className={`num ${best[c.key].includes(f.id) ? "best" : ""}`}>{formatMetric(c, f.metrics[c.key])}</td>)}
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

function RiskTable({ spec, result }: { spec: DomainSpec; result: EvaluationOut }) {
  const risk = metricDef(spec, spec.risk_metric);
  return (
    <div className="card" style={{ padding: 0, overflow: "auto" }}>
      <div style={{ padding: "16px 18px 6px" }}>
        <h2>Risk: {risk.label.toLowerCase()}</h2>
        <p className="small muted" style={{ margin: "4px 0 0" }}>
          Spread over {result.runs} runs per future (model estimates). The main driver is the probabilistic event
          that changes {risk.label.toLowerCase()} the most between runs where it happens and runs where it doesn't.
        </p>
      </div>
      <table aria-label="Risk of every future">
        <thead><tr><th>Future</th><th className="num">Mean</th><th className="num">Bad case</th><th className="num">Worst 5%</th><th>Main driver</th></tr></thead>
        <tbody>
          {result.futures.map((f) => {
            const d = f.drivers[0];
            return (
              <tr key={f.id}>
                <td>#{f.rank} {f.name}</td>
                <td className="num">{formatMetric(risk, f.risk?.mean)}</td>
                <td className="num">{formatMetric(risk, f.risk?.p95)}</td>
                <td className="num">{formatMetric(risk, f.risk?.worst_5_percent_mean)}</td>
                <td className="small">{d && Math.abs(d.impact) > 0
                  ? `${d.event_id}: ${formatMetric(risk, d.mean_if_occurred)} when it happens (${pct(d.frequency)}) vs ${formatMetric(risk, d.mean_if_not)}`
                  : <span className="muted">no probabilistic events</span>}</td>
              </tr>
            );
          })}
        </tbody>
      </table>
    </div>
  );
}

// ---- sensitivity ---------------------------------------------------------------
function SensitivityPanel({ spec, result, until, focus, setFocus }: {
  spec: DomainSpec; result: EvaluationOut; until: number; focus: string | null; setFocus: (id: string) => void;
}) {
  const ws = useWorkspace();
  const target = focus ?? result.recommended ?? result.futures[0]?.id;
  const [metric, setMetric] = useState(spec.risk_metric);
  const [runs, setRuns] = useState(1);
  const [sens, setSens] = useState<SensitivityOut | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const def = metricDef(spec, metric);
  const system = useMemo(() => toDef(ws.system), [ws.system]);
  const options = visibleMetrics(spec, result.futures.map((f) => f.metrics)).filter((m) => m.better !== "neutral");

  useEffect(() => { setSens(null); }, [target, metric, runs]);

  const run = async () => {
    if (!target) return;
    setBusy(true);
    setError(null);
    try {
      setSens(await api.sensitivity(target, { until, metric, runs }));
    } catch (e) { setError(errorMessage(e)); } finally { setBusy(false); }
  };
  const data = sens ? tornadoData(sens, (r) => inputLabel(r, spec, system)) : [];

  return (
    <div className="card" id="sensitivity">
      <h2 style={{ marginBottom: 4 }}>What matters most?</h2>
      <p className="small muted" style={{ margin: "0 0 12px" }}>
        Each numeric input is lowered and raised by 20% (one at a time, same random numbers), and the inputs are
        ranked by how much they move the result. Long bars are where better information or a decision pays off most.
      </p>
      <div className="row" style={{ flexWrap: "wrap" }}>
        <select aria-label="Future to analyse" value={target ?? ""} onChange={(e) => setFocus(e.target.value)}>
          {result.futures.map((f) => <option key={f.id} value={f.id}>#{f.rank} {f.name}</option>)}
        </select>
        <select aria-label="Metric to analyse" value={metric} onChange={(e) => setMetric(e.target.value)}>
          {options.map((m) => <option key={m.key} value={m.key}>{m.label}</option>)}
        </select>
        <select className="fixed" style={{ width: 170 }} aria-label="Runs per point" value={runs} onChange={(e) => setRuns(Number(e.target.value))}>
          <option value={1}>1 run per point</option><option value={30}>30 runs per point</option>
        </select>
        <button className="primary fixed" onClick={run} disabled={busy || !target}>
          {busy ? <span className="spinner" /> : null} Analyse
        </button>
      </div>
      <ErrorNotice error={error} />
      {sens && (data.length ? (
        <>
          <div className="small muted" style={{ margin: "12px 0 4px" }}>
            Baseline {def.label.toLowerCase()}: <b style={{ color: "var(--text)" }}>{formatMetric(def, sens.baseline, true)}</b>.
            Bars show the change when the input is 20% lower (blue) or higher (gold). {sens.rows.length} inputs tested in {(sens.elapsed_ms / 1000).toFixed(1)} s.
          </div>
          <div style={{ height: 50 + data.length * 34 }} aria-label="Sensitivity chart">
            <ResponsiveContainer>
              <BarChart data={data} layout="vertical" margin={{ left: 10, right: 30, top: 6 }} barGap={0}>
                <CartesianGrid strokeDasharray="3 3" horizontal={false} stroke={CHART.grid} />
                <XAxis type="number" tick={{ fontSize: 11, fill: CHART.axis }} stroke={CHART.axis} tickFormatter={(v) => formatMetric(def, v)} />
                <YAxis type="category" dataKey="label" width={250} tick={{ fontSize: 11.5, fill: CHART.cream }} stroke={CHART.axis} />
                <ReferenceLine x={0} stroke={CHART.cream} />
                <Tooltip contentStyle={CHART.tooltip} formatter={(v, n) => [`${Number(v) >= 0 ? "+" : ""}${formatMetric(def, Number(v))}`, n]} />
                <Legend wrapperStyle={{ fontSize: 12, color: CHART.cream }} />
                <Bar dataKey="low" name="input −20%" fill={CHART.info} isAnimationActive={false} radius={4} />
                <Bar dataKey="high" name="input +20%" fill={CHART.gold} isAnimationActive={false} radius={4} />
              </BarChart>
            </ResponsiveContainer>
          </div>
        </>
      ) : <div className="notice info small" style={{ marginTop: 12 }}>No input changes {def.label.toLowerCase()} by ±20% in this future.</div>)}
    </div>
  );
}
