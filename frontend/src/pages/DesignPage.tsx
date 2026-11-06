import {
  Background,
  Controls,
  MiniMap,
  ReactFlow,
  ReactFlowProvider,
  useReactFlow,
  type Connection,
  type EdgeChange,
  type FinalConnectionState,
  type NodeChange,
} from "@xyflow/react";
import { useEffect, useMemo, useRef, useState } from "react";
import { api } from "../api/client";
import type { ComponentDef, DependencyDef, SystemAnalysis, SystemDef } from "../api/types";
import { download, ErrorNotice, errorMessage } from "../components/common";
import { buildEdges, buildNodes, depId, Legend, nodeTypes } from "../components/graph";
import { DependencyInspector, ComponentInspector, SystemInspector } from "../components/Inspectors";
import { useToast } from "../components/Toast";
import { COMPONENT_KINDS, kindOf, uniqueId } from "../lib/catalog";
import { freeSpot, layeredLayout, positionsFor } from "../lib/layout";
import { useWorkspace } from "./workspace";

type Selection = { kind: "node" | "edge"; id: string } | null;

/** The definition without canvas positions: what matters for analysis. */
function structural(def: SystemDef): string {
  return JSON.stringify({ ...def, components: def.components.map(({ layout: _l, ...c }) => c) });
}

function useAnalysis(draft: SystemDef): SystemAnalysis | null {
  const [analysis, setAnalysis] = useState<SystemAnalysis | null>(null);
  const key = structural(draft);
  useEffect(() => {
    const handle = window.setTimeout(() => {
      api.analyze(JSON.parse(key)).then(setAnalysis).catch(() => setAnalysis(null));
    }, 350);
    return () => window.clearTimeout(handle);
  }, [key]);
  return analysis;
}

function Designer() {
  const ws = useWorkspace();
  const { draft, setDraft } = ws;
  const toast = useToast();
  const flow = useReactFlow();
  const [selection, setSelection] = useState<Selection>(null);
  const [mode, setMode] = useState<"visual" | "json">("visual");
  const [jsonText, setJsonText] = useState("");
  const [jsonError, setJsonError] = useState<string | null>(null);
  const [saveError, setSaveError] = useState<string | null>(null);
  const [saving, setSaving] = useState(false);
  const analysis = useAnalysis(draft);

  const positions = useMemo(
    () => positionsFor(draft.components, draft.dependencies),
    [draft.components, draft.dependencies],
  );

  // Highlight the blast radius of the selected component, and any cycle.
  const flags = useMemo(() => {
    const out: Record<string, string[]> = {};
    const add = (id: string, f: string) => (out[id] = [...(out[id] ?? []), f]);
    if (selection?.kind === "node") analysis?.blast_radius[selection.id]?.forEach((id) => add(id, "blast"));
    analysis?.cycle?.forEach((id) => add(id, "cycle"));
    return out;
  }, [analysis, selection]);

  const [sizes, setSizes] = useState<Record<string, { width: number; height: number }>>({});
  const nodes = useMemo(
    () => buildNodes(draft.components, positions, { selectedId: selection?.kind === "node" ? selection.id : null, flags })
      .map((n) => (sizes[n.id] ? { ...n, measured: sizes[n.id] } : n)),
    [draft.components, positions, selection, flags, sizes],
  );
  const edges = useMemo(
    () => buildEdges(draft.dependencies, { selectedId: selection?.kind === "edge" ? selection.id : null }),
    [draft.dependencies, selection],
  );

  // ---- editing operations -------------------------------------------
  const updateComponent = (id: string, patch: Partial<ComponentDef>) =>
    setDraft((d) => {
      const newId = patch.id;
      const renamed = newId && newId !== id;
      return {
        ...d,
        components: d.components.map((c) => (c.id === id ? { ...c, ...patch } : c)),
        dependencies: renamed
          ? d.dependencies.map((dep) => {
              const s = dep.source_id === id ? newId : dep.source_id;
              const t = dep.target_id === id ? newId : dep.target_id;
              const autoId = dep.id === `${dep.source_id}->${dep.target_id}`;
              return { ...dep, source_id: s, target_id: t, id: autoId ? `${s}->${t}` : dep.id };
            })
          : d.dependencies,
      };
    });

  const removeComponents = (ids: string[]) =>
    setDraft((d) => ({
      ...d,
      components: d.components.filter((c) => !ids.includes(c.id)),
      dependencies: d.dependencies.filter((x) => !ids.includes(x.source_id) && !ids.includes(x.target_id)),
    }));

  const updateDependency = (id: string, patch: Partial<DependencyDef>) =>
    setDraft((d) => ({ ...d, dependencies: d.dependencies.map((x) => (depId(x) === id ? { ...x, ...patch } : x)) }));

  const removeDependencies = (ids: string[]) =>
    setDraft((d) => ({ ...d, dependencies: d.dependencies.filter((x) => !ids.includes(depId(x))) }));

  const addComponent = (type: string) => {
    const kind = kindOf(type);
    const id = uniqueId(type, draft.components.map((c) => c.id));
    const bounds = document.querySelector(".canvas")?.getBoundingClientRect();
    const center = bounds
      ? flow.screenToFlowPosition({ x: bounds.left + bounds.width / 2, y: bounds.top + bounds.height / 2 })
      : { x: 0, y: 0 };
    const component: ComponentDef = {
      id, name: kind.label, type, entry_point: type === "gateway" && !draft.components.some((c) => c.entry_point),
      attributes: { ...kind.defaults }, layout: freeSpot({ x: center.x - 85, y: center.y - 40 }, Object.values(positions)),
    };
    setDraft((d) => ({ ...d, components: [...d.components, component] }));
    setSelection({ kind: "node", id });
  };

  const onConnect = (c: Connection) => {
    if (!c.source || !c.target || c.source === c.target) return;
    connectedRef.current = true;
    const id = `${c.source}->${c.target}`;
    if (draft.dependencies.some((d) => depId(d) === id)) {
      toast("That dependency already exists");
      return;
    }
    setDraft((d) => ({
      ...d,
      dependencies: [...d.dependencies, {
        id, source_id: c.source, target_id: c.target, dependency_type: "requires", group: null, propagation_delay: 0,
      }],
    }));
    setSelection({ kind: "edge", id });
  };

  // Dropping a connection anywhere on a component (not just on its small
  // handle) also creates the dependency.
  const connectedRef = useRef(false);
  const onConnectStart = () => { connectedRef.current = false; };
  const onConnectEnd = (event: MouseEvent | TouchEvent, state: FinalConnectionState) => {
    if (connectedRef.current || !state.fromNode) return;
    const point = "changedTouches" in event ? event.changedTouches[0] : event;
    const el = document.elementFromPoint(point.clientX, point.clientY)?.closest(".react-flow__node");
    const target = el?.getAttribute("data-id");
    if (!target) return;
    const from = state.fromNode.id;
    // Dragging from a top (target) handle means "this is depended on by".
    const fromTop = state.fromHandle?.type === "target";
    onConnect({ source: fromTop ? target : from, target: fromTop ? from : target, sourceHandle: null, targetHandle: null });
  };

  const onNodesChange = (changes: NodeChange[]) => {
    const moved: Record<string, { x: number; y: number }> = {};
    const removed: string[] = [];
    const measured: Record<string, { width: number; height: number }> = {};
    for (const ch of changes) {
      if (ch.type === "dimensions" && ch.dimensions) measured[ch.id] = ch.dimensions;
      if (ch.type === "position" && ch.position) moved[ch.id] = ch.position;
      if (ch.type === "remove") removed.push(ch.id);
    }
    if (Object.keys(measured).length) setSizes((prev) => ({ ...prev, ...measured }));
    if (Object.keys(moved).length) {
      setDraft((d) => ({
        ...d,
        components: d.components.map((c) =>
          moved[c.id] ? { ...c, layout: { x: Math.round(moved[c.id].x), y: Math.round(moved[c.id].y) } } : c),
      }));
    }
    if (removed.length) {
      removeComponents(removed);
      setSelection(null);
    }
  };

  const onEdgesChange = (changes: EdgeChange[]) => {
    const removed = changes.filter((c) => c.type === "remove").map((c) => c.id);
    if (removed.length) {
      removeDependencies(removed);
      setSelection(null);
    }
  };

  const autoLayout = () => {
    const pos = layeredLayout(draft.components, draft.dependencies);
    setDraft((d) => ({ ...d, components: d.components.map((c) => ({ ...c, layout: pos[c.id] })) }));
    window.setTimeout(() => flow.fitView({ padding: 0.2, duration: 300 }), 50);
  };

  // ---- save / json ----------------------------------------------------
  const save = async () => {
    setSaving(true);
    setSaveError(null);
    try {
      await ws.saveDraft();
      toast("System saved");
    } catch (e) {
      setSaveError(errorMessage(e));
    } finally {
      setSaving(false);
    }
  };

  const switchMode = (m: "visual" | "json") => {
    if (m === "json") setJsonText(JSON.stringify(draft, null, 2));
    setJsonError(null);
    setMode(m);
  };

  const applyJson = () => {
    try {
      const parsed = JSON.parse(jsonText);
      if (!Array.isArray(parsed.components) || !Array.isArray(parsed.dependencies)) {
        throw new Error('Expected "components" and "dependencies" arrays');
      }
      setDraft({
        name: parsed.name ?? draft.name,
        domain: parsed.domain ?? draft.domain,
        description: parsed.description ?? "",
        components: parsed.components.map((c: Partial<ComponentDef>) => ({
          entry_point: false, attributes: {}, type: "service", ...c,
        }) as ComponentDef),
        dependencies: parsed.dependencies.map((d: Partial<DependencyDef>) => ({
          dependency_type: "requires", group: null, propagation_delay: 0, ...d,
        }) as DependencyDef),
      });
      setJsonError(null);
      toast("JSON applied. Save to keep it.");
      setMode("visual");
    } catch (e) {
      setJsonError(errorMessage(e));
    }
  };

  const exportJson = async () => {
    if (ws.dirty) toast("Exporting the last saved version");
    download(`${ws.system.name.replace(/\W+/g, "_").toLowerCase() || "system"}.json`, await api.exportSystem(ws.system.id));
  };

  const selectedComponent = selection?.kind === "node" ? draft.components.find((c) => c.id === selection.id) : undefined;
  const selectedDependency = selection?.kind === "edge" ? draft.dependencies.find((d) => depId(d) === selection.id) : undefined;

  return (
    <div className="split">
      <div className="column">
        <div className="toolbar">
          <div className="row fixed" style={{ gap: 0 }}>
            <button className={`seg ${mode === "visual" ? "on" : ""}`} onClick={() => switchMode("visual")}>Visual</button>
            <button className={`seg ${mode === "json" ? "on" : ""}`} onClick={() => switchMode("json")}>JSON</button>
          </div>
          {mode === "visual" && (
            <>
              <span className="muted small" style={{ marginLeft: 8 }}>Add:</span>
              {COMPONENT_KINDS.map((k) => (
                <button key={k.type} className="small" onClick={() => addComponent(k.type)} title={`Add ${k.label}`}>
                  <span className="dot" style={{ background: k.color }} /> {k.label}
                </button>
              ))}
              <button className="small" onClick={autoLayout} disabled={!draft.components.length}>Auto-layout</button>
            </>
          )}
          <div className="spacer" />
          <button className="small" onClick={exportJson}>Export</button>
          {ws.dirty && <button className="small" onClick={() => { ws.discardDraft(); setSelection(null); }}>Discard</button>}
          <button className="primary" onClick={save} disabled={!ws.dirty || saving}>
            {saving ? <span className="spinner" /> : null} {ws.dirty ? "Save" : "Saved"}
          </button>
        </div>
        {saveError && <div style={{ padding: "8px 12px 0" }}><ErrorNotice error={saveError} /></div>}

        {mode === "visual" ? (
          <div className="canvas">
            <ReactFlow
              nodes={nodes}
              edges={edges}
              nodeTypes={nodeTypes}
              onNodesChange={onNodesChange}
              onEdgesChange={onEdgesChange}
              onConnect={onConnect}
              onConnectStart={onConnectStart}
              onConnectEnd={onConnectEnd}
              onNodeClick={(_, n) => setSelection({ kind: "node", id: n.id })}
              onEdgeClick={(_, e) => setSelection({ kind: "edge", id: e.id })}
              onPaneClick={() => setSelection(null)}
              deleteKeyCode={["Backspace", "Delete"]}
              fitView
              fitViewOptions={{ padding: 0.25, maxZoom: 1.1 }}
              proOptions={{ hideAttribution: true }}
            >
              <Background gap={20} color="#e5e7eb" />
              <Controls showInteractive={false} />
              <MiniMap pannable zoomable nodeStrokeWidth={3} style={{ height: 90, width: 140 }} />
            </ReactFlow>
            {draft.components.length === 0 && (
              <div className="empty" style={{ position: "absolute", inset: "30% 0 auto", pointerEvents: "none" }}>
                <h2 style={{ color: "var(--text)" }}>Empty system</h2>
                <p>Add components from the toolbar, then drag from a component's bottom handle<br />
                  to the component it depends on.</p>
              </div>
            )}
            <div style={{ position: "absolute", left: 12, bottom: 12, background: "rgba(255,255,255,.9)", padding: "4px 8px", borderRadius: 6 }}>
              <Legend />
            </div>
          </div>
        ) : (
          <div className="column" style={{ padding: 12, gap: 8 }}>
            <ErrorNotice error={jsonError} />
            <textarea aria-label="System JSON" value={jsonText} onChange={(e) => setJsonText(e.target.value)}
              style={{ flex: 1 }} spellCheck={false} />
            <div className="row" style={{ justifyContent: "flex-end" }}>
              <button className="fixed" onClick={() => switchMode("visual")}>Cancel</button>
              <button className="primary fixed" onClick={applyJson}>Apply JSON</button>
            </div>
          </div>
        )}
      </div>

      <aside className="inspector">
        {selectedComponent ? (
          <ComponentInspector
            key={selectedComponent.id}
            component={selectedComponent}
            allIds={draft.components.map((c) => c.id)}
            blastRadius={analysis?.blast_radius[selectedComponent.id]}
            onChange={(patch) => {
              updateComponent(selectedComponent.id, patch);
              if (patch.id) setSelection({ kind: "node", id: patch.id });
            }}
            onDelete={() => { removeComponents([selectedComponent.id]); setSelection(null); }}
          />
        ) : selectedDependency ? (
          <DependencyInspector
            key={depId(selectedDependency)}
            dependency={selectedDependency}
            components={draft.components}
            onChange={(patch) => updateDependency(depId(selectedDependency), patch)}
            onDelete={() => { removeDependencies([depId(selectedDependency)]); setSelection(null); }}
          />
        ) : (
          <SystemInspector draft={draft} analysis={analysis}
            onChange={(patch) => setDraft((d) => ({ ...d, ...patch }))} />
        )}
      </aside>
    </div>
  );
}

export default function DesignPage() {
  return (
    <ReactFlowProvider>
      <Designer />
    </ReactFlowProvider>
  );
}
