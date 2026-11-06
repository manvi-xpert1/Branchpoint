import { useEffect, useMemo, useState } from "react";
import { Link, useNavigate, useParams } from "react-router-dom";
import { api } from "../api/client";
import type { EventDef, InterventionDef, RunSummary, ScenarioIn, ScenarioOut } from "../api/types";
import { ErrorNotice, errorMessage, Field, fmt, NumberInput, pct } from "../components/common";
import { depId } from "../components/graph";
import {
  defaultParams, EventEditor, InterventionEditor, summarizeEvent, summarizeIntervention,
} from "../components/ScenarioForms";
import { MonteCarloPanel } from "../components/MonteCarloPanel";
import { useToast } from "../components/Toast";
import { uniqueId } from "../lib/catalog";
import { componentIdsAfter, fallbackPreset, replicaPreset } from "../lib/presets";
import { toDef, useWorkspace } from "./workspace";

function toInput(s: ScenarioOut): ScenarioIn {
  return {
    name: s.name, description: s.description, parent_id: s.parent_id, seed: s.seed,
    events: s.events, interventions: s.interventions, remove_events: s.remove_events,
  };
}

/** Scenarios ordered depth-first so children follow their parent. */
function treeOrder(scenarios: ScenarioOut[]): { s: ScenarioOut; depth: number }[] {
  const byParent = new Map<string | null, ScenarioOut[]>();
  for (const s of scenarios) byParent.set(s.parent_id, [...(byParent.get(s.parent_id) ?? []), s]);
  const out: { s: ScenarioOut; depth: number }[] = [];
  const walk = (parent: string | null, depth: number) =>
    (byParent.get(parent) ?? []).forEach((s) => { out.push({ s, depth }); walk(s.id, depth + 1); });
  walk(null, 0);
  return out;
}

export default function ScenariosPage() {
  const ws = useWorkspace();
  const { scenarioId } = useParams();
  const navigate = useNavigate();
  const toast = useToast();
  const [error, setError] = useState<string | null>(null);
  const tree = useMemo(() => treeOrder(ws.scenarios), [ws.scenarios]);
  const selected = ws.scenarios.find((s) => s.id === scenarioId);

  useEffect(() => {
    if (!scenarioId && tree.length) navigate(tree[0].s.id, { replace: true });
  }, [scenarioId, tree, navigate]);

  const create = async (parent: ScenarioOut | null) => {
    setError(null);
    try {
      const s = parent
        ? await api.branchScenario(parent.id, `${parent.name}: alternative`)
        : await api.createScenario(ws.system.id, {
            name: "New scenario", description: "", parent_id: null, seed: null,
            events: [], interventions: [], remove_events: [],
          });
      await ws.reloadScenarios();
      navigate(`/systems/${ws.system.id}/scenarios/${s.id}`);
      toast(parent ? "Branch created. It inherits everything from its parent." : "Scenario created");
    } catch (e) {
      setError(errorMessage(e));
    }
  };

  const remove = async (s: ScenarioOut) => {
    if (!confirm(`Delete scenario "${s.name}" and its runs?`)) return;
    try {
      await api.deleteScenario(s.id);
      await ws.reloadScenarios();
      navigate(s.parent_id ? `/systems/${ws.system.id}/scenarios/${s.parent_id}` : `/systems/${ws.system.id}/scenarios`);
    } catch (e) {
      setError(errorMessage(e));
    }
  };

  return (
    <div className="split">
      <aside className="sidebar">
        <div className="section">
          <div className="row" style={{ marginBottom: 10 }}>
            <h3>Scenarios</h3>
            <button className="small fixed" onClick={() => create(null)}>New</button>
          </div>
          <div className="scenario-tree stack" style={{ gap: 2 }}>
            {tree.map(({ s, depth }) => (
              <Link key={s.id} to={`/systems/${ws.system.id}/scenarios/${s.id}`}
                className={`list-item ${s.id === scenarioId ? "active" : ""}`} style={{ color: "inherit" }}>
                {Array.from({ length: depth }).map((_, i) => <span key={i} className="indent" />)}
                {depth > 0 && <span className="muted">↳</span>}
                <span style={{ overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }}>{s.name}</span>
              </Link>
            ))}
            {tree.length === 0 && <p className="muted small">No scenarios yet. Create one to inject failures.</p>}
          </div>
        </div>
        <div className="section small muted">
          A <b>branch</b> starts as a copy of its parent: same events, same changes. Add an intervention to
          it, then compare the branches to see which decision works best.
        </div>
      </aside>
      <div className="page">
        <ErrorNotice error={error} />
        {ws.dirty && (
          <div className="notice warn">
            The design has unsaved changes. Scenarios run against the <b>saved</b> system.{" "}
            <Link to="../design">Go to Design</Link>
          </div>
        )}
        {selected ? (
          <ScenarioEditor key={selected.id + selected.updated_at} scenario={selected}
            onBranch={() => create(selected)} onDelete={() => remove(selected)} />
        ) : (
          tree.length === 0 && (
            <div className="card empty">
              <h2 style={{ color: "var(--text)", marginBottom: 8 }}>No scenarios</h2>
              <p>A scenario is an experiment: a set of events (such as a database failure) and optional
                interventions (such as adding a replica).</p>
              <button className="primary" onClick={() => create(null)}>Create scenario</button>
            </div>
          )
        )}
      </div>
    </div>
  );
}

function ScenarioEditor({ scenario, onBranch, onDelete }: {
  scenario: ScenarioOut; onBranch: () => void; onDelete: () => void;
}) {
  const ws = useWorkspace();
  const navigate = useNavigate();
  const toast = useToast();
  const system = useMemo(() => toDef(ws.system), [ws.system]);
  const [draft, setDraft] = useState<ScenarioIn>(() => toInput(scenario));
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState<"save" | "run" | null>(null);
  const [until, setUntil] = useState(30);
  const [runs, setRuns] = useState<RunSummary[]>([]);
  const dirty = JSON.stringify(draft) !== JSON.stringify(toInput(scenario));

  useEffect(() => { api.listRuns(scenario.id).then(setRuns).catch(() => {}); }, [scenario.id]);

  const parent = ws.scenarios.find((s) => s.id === scenario.parent_id);
  const inheritedEvents = parent?.resolved_events ?? [];
  const inheritedInterventions = (parent?.resolved_interventions ?? [])
    .filter((i) => !draft.interventions.some((o) => o.id === i.id));
  const allInterventions = [...inheritedInterventions, ...draft.interventions];
  const targets = componentIdsAfter(system, allInterventions);
  const set = (patch: Partial<ScenarioIn>) => setDraft((d) => ({ ...d, ...patch }));

  const takenEventIds = [...inheritedEvents, ...draft.events].map((e) => e.id);
  const takenIvIds = allInterventions.map((i) => i.id);

  const addEvent = () => {
    const target = targets.find((t) => system.components.find((c) => c.id === t)?.type === "database") ?? targets[0] ?? "";
    const ev: EventDef = {
      id: uniqueId(`fail_${target}`, takenEventIds), type: "component_failure", target_id: target,
      start_time: 5, duration: null, severity: 1, probability: 1,
    };
    set({ events: [...draft.events, ev] });
  };

  const addIntervention = (type: InterventionDef["type"] = "set_attribute") =>
    set({ interventions: [...draft.interventions, {
      id: uniqueId(type, takenIvIds), type, params: defaultParams(type, system), cost: 0, description: "",
    }] });

  const save = async (): Promise<boolean> => {
    setBusy("save");
    setError(null);
    try {
      await api.updateScenario(scenario.id, draft);
      await ws.reloadScenarios();
      return true;
    } catch (e) {
      setError(errorMessage(e));
      return false;
    } finally {
      setBusy(null);
    }
  };

  const run = async () => {
    if (dirty && !(await save())) return;
    setBusy("run");
    setError(null);
    try {
      const r = await api.runScenario(scenario.id, until);
      navigate(`/systems/${ws.system.id}/runs/${r.id}`);
    } catch (e) {
      setError(errorMessage(e));
      setBusy(null);
    }
  };

  const toggleRemoved = (id: string) =>
    set({ remove_events: draft.remove_events.includes(id)
      ? draft.remove_events.filter((x) => x !== id) : [...draft.remove_events, id] });

  return (
    <div className="page-narrow stack" style={{ gap: 16, maxWidth: 860 }}>
      <div className="row" style={{ alignItems: "flex-start" }}>
        <div>
          <h1>{scenario.name}</h1>
          {scenario.lineage.length > 1 && (
            <div className="small muted" style={{ marginTop: 4 }}>
              Branch of {scenario.lineage.slice(0, -1).map((id) => ws.scenarios.find((s) => s.id === id)?.name ?? id).join(" → ")}
            </div>
          )}
        </div>
        <div className="row fixed">
          <button onClick={onBranch} title="Create a child scenario that inherits this one">Branch</button>
          <button className="danger" onClick={onDelete} disabled={scenario.children.length > 0}
            title={scenario.children.length ? "Delete its branches first" : "Delete scenario"}>Delete</button>
          <button onClick={save} disabled={!dirty || busy !== null}>{busy === "save" ? <span className="spinner" /> : null}{dirty ? "Save" : "Saved"}</button>
        </div>
      </div>
      <ErrorNotice error={error} />

      <div className="card">
        <div className="grid2">
          <Field label="Name"><input aria-label="Scenario name" value={draft.name} onChange={(e) => set({ name: e.target.value })} /></Field>
          <Field label="Random seed" hint="Same seed, same result for probabilistic events">
            <NumberInput aria-label="Seed" value={draft.seed} step={1} onChange={(v) => set({ seed: v === null ? null : Math.round(v) })} />
          </Field>
        </div>
        <Field label="Description">
          <input value={draft.description} placeholder="What does this experiment test?" onChange={(e) => set({ description: e.target.value })} />
        </Field>
      </div>

      <div className="card">
        <div className="row" style={{ marginBottom: 12 }}>
          <h2>Events</h2>
          <button className="small fixed" onClick={addEvent} disabled={!targets.length}>Add event</button>
        </div>
        {inheritedEvents.map((e) => {
          const removed = draft.remove_events.includes(e.id);
          const overridden = draft.events.some((o) => o.id === e.id);
          return (
            <div key={e.id} className={`editable-row inherited ${removed || overridden ? "removed" : ""} row`}>
              <span><span className="pill">inherited</span> {summarizeEvent(e)}</span>
              {!overridden && (
                <button className="small fixed" onClick={() => toggleRemoved(e.id)}>
                  {removed ? "Restore" : "Remove in this branch"}
                </button>
              )}
            </div>
          );
        })}
        {draft.events.map((e, i) => (
          <EventEditor key={i} event={e} targets={targets}
            onChange={(ev) => set({ events: draft.events.map((x, j) => (j === i ? ev : x)) })}
            onRemove={() => set({ events: draft.events.filter((_, j) => j !== i) })} />
        ))}
        {!inheritedEvents.length && !draft.events.length && (
          <p className="muted small" style={{ margin: 0 }}>No events: the run shows normal operation (a baseline).</p>
        )}
      </div>

      <div className="card">
        <div className="row" style={{ marginBottom: 12 }}>
          <h2>Interventions</h2>
          <button className="small fixed" onClick={() => addIntervention()}>Add custom</button>
        </div>
        <Presets system={system} existing={allInterventions}
          onAdd={(ivs) => { set({ interventions: [...draft.interventions, ...ivs] }); toast(`Added ${ivs.length} intervention step(s)`); }} />
        {inheritedInterventions.map((iv) => (
          <div key={iv.id} className="editable-row inherited">
            <span className="pill">inherited</span> {summarizeIntervention(iv)}
            {iv.cost ? <span className="muted"> · cost {iv.cost}</span> : null}
          </div>
        ))}
        {draft.interventions.map((iv, i) => (
          <InterventionEditor key={i} iv={iv} system={system} componentIds={targets}
            onChange={(n) => set({ interventions: draft.interventions.map((x, j) => (j === i ? n : x)) })}
            onRemove={() => set({ interventions: draft.interventions.filter((_, j) => j !== i) })} />
        ))}
      </div>

      <div className="card">
        <h2 style={{ marginBottom: 12 }}>Run</h2>
        <div className="row" style={{ justifyContent: "flex-start" }}>
          <label className="row fixed" style={{ gap: 6 }}>
            <span className="small muted">Simulate for</span>
            <span style={{ width: 90 }}><NumberInput aria-label="Simulation duration" value={until} min={1} onChange={(v) => setUntil(v && v > 0 ? v : 30)} /></span>
            <span className="small muted">time units</span>
          </label>
          <button className="primary fixed" onClick={run} disabled={busy !== null}>
            {busy === "run" ? <span className="spinner" /> : "▶"} {dirty ? "Save & run" : "Run simulation"}
          </button>
        </div>
        {runs.length > 0 && (
          <table style={{ marginTop: 14 }}>
            <thead><tr><th>Run</th><th className="num">Availability</th><th className="num">Downtime</th><th className="num">Affected</th><th /></tr></thead>
            <tbody>
              {runs.slice(0, 5).map((r) => (
                <tr key={r.id}>
                  <td className="small">{new Date(r.created_at).toLocaleString()} <span className="muted">· {r.until}t · seed {r.seed}</span></td>
                  <td className="num">{pct(r.metrics.availability)}</td>
                  <td className="num">{fmt(r.metrics.downtime)}</td>
                  <td className="num">{r.metrics.affected_components}</td>
                  <td className="num"><Link to={`/systems/${ws.system.id}/runs/${r.id}`}>View</Link></td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
      </div>

      <MonteCarloPanel scenarioId={scenario.id} until={until}
        events={[...inheritedEvents.filter((e) => !draft.remove_events.includes(e.id)
          && !draft.events.some((o) => o.id === e.id)), ...draft.events]}
        beforeRun={async () => !dirty || save()} />
    </div>
  );
}

function Presets({ system, existing, onAdd }: {
  system: ReturnType<typeof toDef>; existing: InterventionDef[]; onAdd: (ivs: InterventionDef[]) => void;
}) {
  const depended = system.components.filter((c) => system.dependencies.some((d) => d.target_id === c.id));
  const [replicaOf, setReplicaOf] = useState(depended[0]?.id ?? "");
  const [replicaCost, setReplicaCost] = useState<number | null>(300);
  const [fbDep, setFbDep] = useState(system.dependencies[0] ? depId(system.dependencies[0]) : "");
  const dep = system.dependencies.find((d) => depId(d) === fbDep);
  const fbCandidates = system.components.filter((c) => dep && c.id !== dep.source_id && c.id !== dep.target_id);
  const [fbChoice, setFbChoice] = useState("");
  // Keep the choice valid when the selected dependency changes.
  const fbTarget = fbCandidates.some((c) => c.id === fbChoice) ? fbChoice : fbCandidates[0]?.id ?? "";
  const setFbTarget = setFbChoice;
  const [fbCost, setFbCost] = useState<number | null>(50);

  if (!system.dependencies.length) return null;
  return (
    <div className="grid2" style={{ marginBottom: 12 }}>
      <div className="editable-row" style={{ marginBottom: 0 }}>
        <div className="small" style={{ fontWeight: 600, marginBottom: 6 }}>Add a replica</div>
        <div className="row">
          <select aria-label="Replica of" value={replicaOf} onChange={(e) => setReplicaOf(e.target.value)}>
            {depended.map((c) => <option key={c.id} value={c.id}>{c.name ?? c.id}</option>)}
          </select>
          <span className="fixed" style={{ width: 80 }}><NumberInput aria-label="Replica cost" value={replicaCost} min={0} placeholder="cost" onChange={setReplicaCost} /></span>
          <button className="small fixed" disabled={!replicaOf}
            onClick={() => onAdd(replicaPreset(system, replicaOf, existing, replicaCost ?? 0))}>Add</button>
        </div>
        <div className="hint small muted" style={{ marginTop: 4 }}>Dependents can fail over to the copy.</div>
      </div>
      <div className="editable-row" style={{ marginBottom: 0 }}>
        <div className="small" style={{ fontWeight: 600, marginBottom: 6 }}>Add a fallback</div>
        <div className="row" style={{ marginBottom: 6 }}>
          <select aria-label="Fallback for dependency" value={fbDep} onChange={(e) => setFbDep(e.target.value)}>
            {system.dependencies.map((d) => <option key={depId(d)} value={depId(d)}>{d.source_id} → {d.target_id}</option>)}
          </select>
        </div>
        <div className="row">
          <select aria-label="Fallback component" value={fbTarget} onChange={(e) => setFbTarget(e.target.value)}>
            <option value="" disabled>fall back to…</option>
            {fbCandidates.map((c) => <option key={c.id} value={c.id}>{c.name ?? c.id}</option>)}
          </select>
          <span className="fixed" style={{ width: 80 }}><NumberInput aria-label="Fallback cost" value={fbCost} min={0} placeholder="cost" onChange={setFbCost} /></span>
          <button className="small fixed" disabled={!dep || !fbTarget}
            onClick={() => dep && onAdd(fallbackPreset(system, dep.source_id, dep.target_id, fbTarget, existing, fbCost ?? 0))}>Add</button>
        </div>
        <div className="hint small muted" style={{ marginTop: 4 }}>Keeps running degraded when the target fails.</div>
      </div>
    </div>
  );
}
