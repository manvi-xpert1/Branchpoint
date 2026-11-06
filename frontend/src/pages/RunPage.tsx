import { Background, Controls, ReactFlow, ReactFlowProvider } from "@xyflow/react";
import { useEffect, useMemo, useRef, useState } from "react";
import { Link, useParams } from "react-router-dom";
import { api } from "../api/client";
import type { ComponentDef, DependencyDef, LogEntry, ReplayOut, RunOut, Status, SystemDef } from "../api/types";
import { ErrorNotice, errorMessage, fmt, Metric, pct, StatusPill } from "../components/common";
import { buildEdges, buildNodes, depId, Legend, nodeTypes } from "../components/graph";
import { freeSpot, layeredLayout, positionsFor, type Point } from "../lib/layout";
import { causalChain, eventTimes, segments, STATUS_COLORS, statusAt } from "../lib/timeline";
import { useWorkspace } from "./workspace";

/**
 * Same positions as the designer shows for the saved system. Components a
 * scenario adds (e.g. a replica) go next to the one they copy, or to the right.
 */
function runPositions(components: ComponentDef[], deps: DependencyDef[], saved: SystemDef): Record<string, Point> {
  const base = positionsFor(saved.components, saved.dependencies);
  const auto = layeredLayout(components, deps);
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
    return out;
  }, [components, run.timelines, t]);

  const chain = useMemo(() => (selectedSeq === null ? [] : causalChain(run.log, selectedSeq)), [run.log, selectedSeq]);
  const chainComponents = useMemo(
    () => new Set(chain.filter((e) => e.kind === "status_change").map((e) => e.component_id)), [chain]);
  const chainEdges = useMemo(() => {
    const ids = new Set<string>();
    const comps = chain.filter((e) => e.kind === "status_change").map((e) => e.component_id);
    for (let i = 1; i < comps.length; i++) {
      deps.filter((d) => d.source_id === comps[i] && d.target_id === comps[i - 1]).forEach((d) => ids.add(depId(d)));
    }
    return ids;
  }, [chain, deps]);

  const positions = useMemo(() => runPositions(components, deps, ws.system), [components, deps, ws.system]);
  const nodes = useMemo(() => buildNodes(components, positions, {
    status,
    flags: Object.fromEntries([...chainComponents].map((id) => [id, ["chain"]])),
  }).map((n) => ({ ...n, draggable: false, connectable: false })), [components, positions, status, chainComponents]);
  const edges = useMemo(() => buildEdges(deps, { status, highlight: chainEdges }), [deps, status, chainEdges]);

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

  const m = run.metrics;
  const nonHealthyNow = Object.values(status).filter((s) => s !== "healthy").length;

  return (
    <div className="split">
      <div className="column">
        <div className="toolbar" style={{ alignItems: "flex-start", flexDirection: "column", gap: 10, padding: "12px 16px" }}>
          <div className="row" style={{ width: "100%" }}>
            <div>
              <h1>{run.scenario_name}</h1>
              <div className="small muted">
                Run {run.id} · seed {run.seed} · {run.until} time units · {fmt(run.elapsed_ms)} ms
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
            <Metric label="Availability" value={pct(m.availability)} tone={m.availability < 1 ? "bad" : "ok"} />
            <Metric label="Downtime" value={fmt(m.downtime)} tone={m.downtime > 0 ? "bad" : undefined} />
            <Metric label="Degraded time" value={fmt(m.degraded_time)} tone={m.degraded_time > 0 ? "warn" : undefined} />
            <Metric label="Affected components" value={String(m.affected_components)} />
            <Metric label="Recovery time" value={m.affected_components === 0 ? "–" : m.recovery_time === null ? "not recovered" : fmt(m.recovery_time)} />
            <Metric label="Intervention cost" value={fmt(m.cost)} />
          </div>
        </div>

        <div className="canvas">
          <ReactFlow nodes={nodes} edges={edges} nodeTypes={nodeTypes} fitView fitViewOptions={{ padding: 0.25, maxZoom: 1.1 }}
            nodesDraggable={false} nodesConnectable={false} elementsSelectable={false}
            onNodeClick={(_, n) => {
              const last = [...run.log].reverse().find((e) => e.kind === "status_change" && e.component_id === n.id && e.time <= t);
              if (last) setSelectedSeq(last.seq);
            }}
            proOptions={{ hideAttribution: true }}>
            <Background gap={20} color="#e5e7eb" />
            <Controls showInteractive={false} />
          </ReactFlow>
          <div style={{ position: "absolute", left: 12, top: 12, background: "rgba(255,255,255,.92)", padding: "6px 10px", borderRadius: 6 }}>
            <div className="small"><b>t = {fmt(t)}</b> · {nonHealthyNow === 0 ? "all healthy" : `${nonHealthyNow} component${nonHealthyNow > 1 ? "s" : ""} affected`}</div>
          </div>
          <div style={{ position: "absolute", left: 12, bottom: 12, background: "rgba(255,255,255,.9)", padding: "4px 8px", borderRadius: 6 }}>
            <Legend />
          </div>
        </div>

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
  const ids = run.system.components.map((c) => c.id);
  const name = (id: string) => run.system.components.find((c) => c.id === id)?.name ?? id;
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
            <line x1={t} x2={t} y1={0} y2={1} stroke="#111827" strokeWidth={run.until / 400} vectorEffect="non-scaling-stroke" />
          </svg>
        </div>
      ))}
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
