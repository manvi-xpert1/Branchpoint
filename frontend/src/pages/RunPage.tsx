import { Background, Controls, ReactFlow, ReactFlowProvider } from "@xyflow/react";
import { useEffect, useMemo, useRef, useState } from "react";
import { CartesianGrid, Legend as ChartLegend, Line, LineChart, ReferenceLine, ResponsiveContainer, Tooltip, XAxis, YAxis } from "recharts";
import { Link, useParams } from "react-router-dom";
import { api } from "../api/client";
import type { ComponentDef, DependencyDef, DomainSpec, LogEntry, ReplayOut, RunOut, Status, SystemDef } from "../api/types";
import { ErrorNotice, errorMessage, fmt, Metric, StatusPill } from "../components/common";
import { formatMetric, hasFeature, tone, visibleMetrics } from "../lib/domains";
import { CHART } from "../lib/theme";
import { buildEdges, buildNodes, depId, Legend, nodeTypes } from "../components/graph";
import { freeSpot, layeredLayout, positionsFor, type Point } from "../lib/layout";
import { causalChain, eventTimes, segments, STATUS_COLORS, statusAt } from "../lib/timeline";
import { useWorkspace } from "./workspace";

/**
 * Same positions as the designer shows for the saved system. Components a
 * scenario adds (e.g. a replica) go next to the one they copy, or to the right.
 */
function runPositions(components: ComponentDef[], deps: DependencyDef[], saved: SystemDef, horizontal: boolean): Record<string, Point> {
  const base = positionsFor(saved.components, saved.dependencies, {}, horizontal);
  const auto = layeredLayout(components, deps, horizontal);
  const xs = Object.values(base).map((p) => p.x);
  const maxX = xs.length ? Math.max(...xs) : 0;
  const out: Record<string, Point> = {};
  let extra = 0;
  for (const c of components) {
    if (base[c.id]) { out[c.id] = base[c.id]; continue; }
    const original = base[c.id.replace(/_replica(_\d+)?$/, "")];
    out[c.id] = original
      ? freeSpot({ x: original.x + 210, y: original.y + 30 }, [...Object.values(base), ...Object.values(out)])
      : { x: maxX + 230 * ++extra, y: auto[c.id].y };
  }
  return out;
}

/** The moment with the most components in trouble: a useful starting frame. */
function peakTime(run: RunOut): number {
  let best = 0;
  let bestCount = 0;
  for (const t of eventTimes(run.log)) {
    const count = Object.values(run.timelines).filter((tl) => statusAt(tl, t) !== "healthy").length;
    if (count > bestCount) { best = t; bestCount = count; }
  }
  return best;
}

function RunView({ run }: { run: RunOut }) {
  const ws = useWorkspace();
  const spec = ws.spec;
  const [view, setView] = useState<"graph" | "charts">("graph");
  const [t, setT] = useState(() => peakTime(run));
  const [playing, setPlaying] = useState(false);
  const [speed, setSpeed] = useState(1);
  const [selectedSeq, setSelectedSeq] = useState<number | null>(null);
  const [replay, setReplay] = useState<ReplayOut | "busy" | null>(null);
  const logRef = useRef<HTMLDivElement>(null);
  const times = useMemo(() => eventTimes(run.log), [run.log]);
  const components = run.system.components;
  const deps = run.system.dependencies;

  // Playback: the whole run takes ~12 seconds at 1x.
  useEffect(() => {
    if (!playing) return;
    let last = performance.now();
    let frame = 0;
    const tick = (now: number) => {
      const dt = ((now - last) / 1000) * (run.until / 12) * speed;
      last = now;
      setT((prev) => {
        const next = Math.min(run.until, prev + dt);
        if (next >= run.until) setPlaying(false);
        return next;
      });
      frame = requestAnimationFrame(tick);
    };
    frame = requestAnimationFrame(tick);
    return () => cancelAnimationFrame(frame);
  }, [playing, speed, run.until]);

  const status = useMemo(() => {
    const out: Record<string, Status> = {};
    for (const c of components) out[c.id] = statusAt(run.timelines[c.id], t);
    // Routes have their own status in some domains (e.g. a closed road).
    for (const d of deps) if (run.timelines[depId(d)]) out[depId(d)] = statusAt(run.timelines[depId(d)], t);
    return out;
  }, [components, deps, run.timelines, t]);

  const chain = useMemo(() => (selectedSeq === null ? [] : causalChain(run.log, selectedSeq)), [run.log, selectedSeq]);
  const chainComponents = useMemo(
    () => new Set(chain.filter((e) => e.kind === "status_change").map((e) => e.component_id)), [chain]);
  const chainEdges = useMemo(() => {
    const ids = new Set<string>();
    const comps = chain.filter((e) => e.kind === "status_change").map((e) => e.component_id);
    const flow = !hasFeature(spec, "propagation_delay");
    for (let i = 1; i < comps.length; i++) {
      deps.filter((d) => (d.source_id === comps[i] && d.target_id === comps[i - 1])
        || (flow && d.source_id === comps[i - 1] && d.target_id === comps[i])).forEach((d) => ids.add(depId(d)));
    }
    chain.forEach((e) => deps.some((d) => depId(d) === e.component_id) && ids.add(e.component_id));
    return ids;
  }, [chain, deps, spec]);

  const positions = useMemo(() => runPositions(components, deps, ws.system, !hasFeature(spec, "propagation_delay")),
    [components, deps, ws.system, spec]);
  const nodes = useMemo(() => buildNodes(spec, components, positions, {
    status,
    flags: Object.fromEntries([...chainComponents].map((id) => [id, ["chain"]])),
  }).map((n) => ({ ...n, draggable: false, connectable: false })), [spec, components, positions, status, chainComponents]);
  const edges = useMemo(() => buildEdges(spec, deps, { status, highlight: chainEdges }), [spec, deps, status, chainEdges]);

  const selectEntry = (e: LogEntry) => {
    setSelectedSeq(e.seq);
    setT(e.time);
    setPlaying(false);
  };

  const step = (dir: 1 | -1) => {
    setPlaying(false);
    const next = dir > 0 ? times.find((x) => x > t + 1e-9) : [...times].reverse().find((x) => x < t - 1e-9);
    setT(next ?? (dir > 0 ? run.until : 0));
  };

  const doReplay = async () => {
    setReplay("busy");
    try { setReplay(await api.replay(run.id)); } catch (e) {
      setReplay({ run_id: run.id, identical: false, differences: [errorMessage(e)] });
    }
  };

  const shown = visibleMetrics(spec, [run.metrics]).filter((d) => d.better !== "neutral" || d.format === "count");
  const nonHealthyNow = components.filter((c) => status[c.id] !== "healthy").length;

  return (
    <div className="split">
      <div className="column">
        <div className="toolbar" style={{ alignItems: "flex-start", flexDirection: "column", gap: 10, padding: "12px 16px" }}>
          <div className="row" style={{ width: "100%" }}>
            <div>
              <h1>{run.scenario_name}</h1>
              <div className="small muted">
                Run {run.id} · seed {run.seed} · {run.until} {spec.time_unit} · {fmt(run.elapsed_ms)} ms
                {run.skipped_events.length > 0 && <> · probabilistic events that did not occur: {run.skipped_events.join(", ")}</>}
              </div>
            </div>
            <div className="row fixed">
              <Link className="btn" to={`/systems/${ws.system.id}/scenarios/${run.scenario_id}`}>Edit scenario</Link>
              <Link className="btn" to={`/systems/${ws.system.id}/compare`}>Compare</Link>
              <button onClick={doReplay} disabled={replay === "busy"} title="Re-run from the stored snapshot and check the result is identical">
                {replay === "busy" ? <span className="spinner" /> : null} Verify replay
              </button>
            </div>
          </div>
          {replay && replay !== "busy" && (
            <div className={`notice ${replay.identical ? "ok" : "error"}`} style={{ margin: 0 }}>
              {replay.identical ? "Replay identical: same metrics and same event log." : `Replay differs:\n${replay.differences.join("\n")}`}
            </div>
          )}
          <div className="metric-grid" style={{ width: "100%" }}>
            {shown.map((d) => (
              <Metric key={d.key} label={d.label} value={formatMetric(d, run.metrics[d.key])} unit={d.format === "percent" ? undefined : d.unit}
                tone={tone(d, run.metrics[d.key])} hint={d.description} />
            ))}
          </div>
        </div>

        {run.series && Object.keys(run.series).length > 0 && (
          <div className="row fixed" style={{ gap: 0, alignSelf: "flex-start" }}>
            <button className={`seg ${view === "graph" ? "on" : ""}`} onClick={() => setView("graph")}>Graph</button>
            <button className={`seg ${view === "charts" ? "on" : ""}`} onClick={() => setView("charts")}>Charts over time</button>
          </div>
        )}
        {view === "charts" && run.series ? <SeriesView run={run} spec={spec} t={t} /> : (
        <div className="canvas">
          <ReactFlow nodes={nodes} edges={edges} nodeTypes={nodeTypes} fitView fitViewOptions={{ padding: 0.25, maxZoom: 1.1 }}
            nodesDraggable={false} nodesConnectable={false} elementsSelectable={false}
            onNodeClick={(_, n) => {
              const last = [...run.log].reverse().find((e) => e.kind === "status_change" && e.component_id === n.id && e.time <= t);
              if (last) setSelectedSeq(last.seq);
            }}
            proOptions={{ hideAttribution: true }}>
            <Background gap={24} size={1.4} color="rgba(255,226,180,.16)" />
            <Controls showInteractive={false} position="top-right" />
          </ReactFlow>
          <div className="canvas-chip" style={{ left: 12, top: 12 }}>
            <b>t = {fmt(t)}</b>{" "}
            <span style={{ color: nonHealthyNow === 0 ? "var(--ok-hi)" : "var(--bad-hi)" }}>
              {nonHealthyNow === 0 ? "all healthy" : `${nonHealthyNow} affected`}
            </span>
          </div>
          <div className="canvas-chip" style={{ left: 12, bottom: 12 }}>
            <Legend spec={spec} />
          </div>
        </div>
        )}

        <div className="playback">
          <button className="small" onClick={() => step(-1)} title="Previous event">⏮</button>
          <button className="small primary" style={{ minWidth: 70 }}
            onClick={() => { if (t >= run.until) setT(0); setPlaying((p) => !p); }}>{playing ? "❚❚ Pause" : "▶ Play"}</button>
          <button className="small" onClick={() => step(1)} title="Next event">⏭</button>
          <input type="range" aria-label="Simulation time" min={0} max={run.until} step={run.until / 600} value={t}
            onChange={(e) => { setPlaying(false); setT(Number(e.target.value)); }} />
          <select className="fixed" style={{ width: 70 }} value={speed} onChange={(e) => setSpeed(Number(e.target.value))} aria-label="Playback speed">
            {[0.5, 1, 2, 4].map((s) => <option key={s} value={s}>{s}×</option>)}
          </select>
          <span className="time">t={fmt(t, 1)} / {run.until}</span>
        </div>
        <Lanes run={run} t={t} onSeek={(x) => { setPlaying(false); setT(x); }} />
      </div>

      <aside className="inspector" style={{ display: "flex", flexDirection: "column" }}>
        {chain.length > 0 && (
          <div className="section">
            <div className="row" style={{ marginBottom: 10 }}>
              <h3>Why did this happen?</h3>
              <button className="ghost small fixed" onClick={() => setSelectedSeq(null)}>Clear</button>
            </div>
            <div className="chain">
              {chain.map((e) => (
                <div key={e.seq} className="chain-step">
                  <span className="mono muted">t={fmt(e.time)}</span> <b>{e.component_id}</b>
                  <div>{e.message}</div>
                </div>
              ))}
            </div>
          </div>
        )}
        <div className="section" style={{ paddingBottom: 6 }}>
          <h3 style={{ marginBottom: 0 }}>Event log</h3>
          <div className="small muted">Click an entry to trace its cause.</div>
        </div>
        <div className="log" ref={logRef} style={{ flex: 1, overflow: "auto", paddingBottom: 12 }}>
          {run.log.map((e) => (
            <div key={e.seq} data-testid={`log-${e.seq}`}
              className={`log-item ${e.time > t + 1e-9 ? "future" : ""} ${e.seq === selectedSeq ? "selected" : ""} ${chain.some((c) => c.seq === e.seq) ? "in-chain" : ""}`}
              onClick={() => selectEntry(e)}>
              <span className="t">{fmt(e.time)}</span>
              <span>
                <span className="comp">{e.component_id}</span>{" "}
                {e.kind === "event"
                  ? <span className="pill">{e.message}</span>
                  : <>{e.new_status && <StatusPill status={e.new_status} />} <span className="muted">{e.message.split(": ").slice(1).join(": ")}</span></>}
              </span>
            </div>
          ))}
          {run.log.length === 0 && <p className="muted small" style={{ padding: "0 16px" }}>Nothing happened: no events in this scenario.</p>}
        </div>
      </aside>
    </div>
  );
}

/** One swimlane per component, coloured by status over time. Click to seek. */
function Lanes({ run, t, onSeek }: { run: RunOut; t: number; onSeek: (t: number) => void }) {
  const routeIds = run.system.dependencies.map(depId).filter((id) => run.timelines[id]?.some(([, s]) => s !== "healthy"));
  const ids = [...run.system.components.map((c) => c.id), ...routeIds];
  const compName = (id: string) => run.system.components.find((c) => c.id === id)?.name ?? id;
  const name = (id: string) => {
    const d = run.system.dependencies.find((x) => depId(x) === id);
    return d ? `${compName(d.source_id)} → ${compName(d.target_id)}` : compName(id);
  };
  return (
    <div className="lanes" aria-label="Status timeline">
      {ids.map((id) => (
        <div className="lane" key={id}>
          <span className="name" title={name(id)}>{name(id)}</span>
          <svg viewBox={`0 0 ${run.until} 1`} preserveAspectRatio="none"
            onClick={(e) => {
              const box = e.currentTarget.getBoundingClientRect();
              onSeek(((e.clientX - box.left) / box.width) * run.until);
            }}>
            {segments(run.timelines[id] ?? [[0, "healthy"]], run.until).map(([s, end, st], i) => (
              <rect key={i} x={s} y={0} width={end - s} height={1} fill={STATUS_COLORS[st]} opacity={st === "healthy" ? 0.35 : 0.9} />
            ))}
            <line x1={t} x2={t} y1={0} y2={1} stroke="var(--text)" strokeWidth={run.until / 400} vectorEffect="non-scaling-stroke" />
          </svg>
        </div>
      ))}
    </div>
  );
}

const SERIES_LABELS: Record<string, string> = {
  queue: "Patients waiting", in_use: "Beds / staff in use", inventory: "Stock on hand", load: "Load", latency: "End-to-end latency",
};

/** Line charts of the run's time series (queues, stock, load ...), with the playback time marked. */
function SeriesView({ run, spec, t }: { run: RunOut; spec: DomainSpec; t: number }) {
  const variables = Object.keys(run.series ?? {});
  const [variable, setVariable] = useState(variables[0]);
  const byEntity = run.series?.[variable] ?? {};
  const entities = Object.keys(byEntity);
  const name = (id: string) => run.system.components.find((c) => c.id === id)?.name ?? id;
  // Merge the entities' points into rows keyed by time (all series share sampling times in practice).
  const data = useMemo(() => {
    const rows = new Map<number, Record<string, number | null>>();
    for (const [id, points] of Object.entries(byEntity)) {
      for (const [time, value] of points) {
        const row = rows.get(time) ?? { time };
        row[id] = value;
        rows.set(time, row);
      }
    }
    return [...rows.values()].sort((a, b) => (a.time as number) - (b.time as number));
  }, [byEntity]);
  return (
    <div className="canvas chart-stage">
      <div className="row" style={{ padding: "12px 16px 0", justifyContent: "flex-start" }}>
        <span className="small fixed" style={{ color: "var(--on-dark-muted)" }}>Show</span>
        <select className="fixed" style={{ width: 220 }} aria-label="Time series" value={variable}
          onChange={(e) => setVariable(e.target.value)}>
          {variables.map((v) => <option key={v} value={v}>{SERIES_LABELS[v] ?? v}</option>)}
        </select>
        <span className="small fixed" style={{ color: "var(--on-dark-muted)" }}>sampled over {run.until} {spec.time_unit}</span>
      </div>
      <div style={{ position: "absolute", inset: "56px 12px 12px 0" }}>
        <ResponsiveContainer>
          <LineChart data={data} margin={{ left: 10, right: 20, top: 10, bottom: 10 }}>
            <CartesianGrid strokeDasharray="3 3" stroke={CHART.grid} />
            <XAxis dataKey="time" type="number" domain={[0, run.until]} tick={{ fontSize: 12, fill: CHART.axis }} stroke={CHART.axis} />
            <YAxis tick={{ fontSize: 12, fill: CHART.axis }} stroke={CHART.axis} width={50} />
            <Tooltip contentStyle={CHART.tooltip} labelFormatter={(l) => `t = ${fmt(Number(l), 1)}`} />
            <ChartLegend wrapperStyle={{ fontSize: 12, color: CHART.cream }} />
            <ReferenceLine x={t} stroke={CHART.cream} strokeDasharray="4 3" />
            {entities.map((id, i) => (
              <Line key={id} dataKey={id} name={name(id)} type={variable === "inventory" ? "stepAfter" : "linear"}
                stroke={CHART.series[i % CHART.series.length]} dot={false} strokeWidth={2} isAnimationActive={false}
                connectNulls={false} />
            ))}
          </LineChart>
        </ResponsiveContainer>
      </div>
    </div>
  );
}

export default function RunPage() {
  const { runId = "" } = useParams();
  const [run, setRun] = useState<RunOut | null>(null);
  const [error, setError] = useState<string | null>(null);
  useEffect(() => {
    setRun(null);
    api.getRun(runId).then(setRun).catch((e) => setError(errorMessage(e)));
  }, [runId]);
  if (error) return <div className="page"><ErrorNotice error={error} /></div>;
  if (!run) return <div className="page empty"><span className="spinner" /></div>;
  return <ReactFlowProvider><RunView key={run.id} run={run} /></ReactFlowProvider>;
}
