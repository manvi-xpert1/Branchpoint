import { useState } from "react";
import type { ComponentDef, DependencyDef, DependencyType, SystemAnalysis, SystemDef } from "../api/types";
import { COMPONENT_KINDS, kindOf } from "../lib/catalog";
import { Field, NumberInput } from "./common";

const ID_PATTERN = /^[A-Za-z0-9_.-]+$/;

const KNOWN_ATTRIBUTES: { key: string; label: string; hint: string }[] = [
  { key: "capacity", label: "Capacity", hint: "Requests per second it can handle" },
  { key: "current_load", label: "Current load", hint: "Normal requests per second" },
  { key: "recovery_time", label: "Recovery time", hint: "Time units to recover after a failure with no set duration" },
  { key: "overload_failure_ratio", label: "Overload failure ratio", hint: "Fails when load > capacity × this (default 1.5)" },
];

// ---- component --------------------------------------------------------
export function ComponentInspector({
  component, allIds, blastRadius, onChange, onDelete,
}: {
  component: ComponentDef;
  allIds: string[];
  blastRadius?: string[];
  onChange: (patch: Partial<ComponentDef>) => void;
  onDelete: () => void;
}) {
  const [idText, setIdText] = useState(component.id);
  const [newKey, setNewKey] = useState("");
  const idError = !ID_PATTERN.test(idText)
    ? "Letters, digits, _ . - only"
    : idText !== component.id && allIds.includes(idText) ? "Id already used" : null;

  const setAttr = (key: string, value: unknown) => {
    const attributes = { ...component.attributes };
    if (value === null || value === undefined || value === "") delete attributes[key];
    else attributes[key] = value;
    onChange({ attributes });
  };
  const extraKeys = Object.keys(component.attributes).filter((k) => !KNOWN_ATTRIBUTES.some((a) => a.key === k));
  const types = COMPONENT_KINDS.some((k) => k.type === component.type)
    ? COMPONENT_KINDS : [...COMPONENT_KINDS, kindOf(component.type)];

  return (
    <>
      <div className="section">
        <h3>Component</h3>
        <Field label="Name">
          <input aria-label="Component name" value={component.name ?? ""} onChange={(e) => onChange({ name: e.target.value })} />
        </Field>
        <Field label="Id" hint={idError ?? "Used in events and the JSON definition"}>
          <input aria-label="Component id" className="mono" value={idText}
            onChange={(e) => setIdText(e.target.value)}
            onBlur={() => (idError ? setIdText(component.id) : idText !== component.id && onChange({ id: idText }))}
            onKeyDown={(e) => e.key === "Enter" && (e.target as HTMLInputElement).blur()} />
        </Field>
        <Field label="Type">
          <select aria-label="Component type" value={component.type} onChange={(e) => onChange({ type: e.target.value })}>
            {types.map((k) => <option key={k.type} value={k.type}>{k.label}</option>)}
          </select>
        </Field>
        <label className="check">
          <input type="checkbox" checked={component.entry_point} onChange={(e) => onChange({ entry_point: e.target.checked })} />
          <span>Entry point <span className="muted small">(availability is measured here)</span></span>
        </label>
      </div>

      <div className="section">
        <h3>Attributes</h3>
        {KNOWN_ATTRIBUTES.map((a) => (
          <Field key={a.key} label={a.label} hint={a.hint}>
            <NumberInput aria-label={a.label} value={component.attributes[a.key] as number | undefined}
              min={0} onChange={(v) => setAttr(a.key, v)} placeholder="not set" />
          </Field>
        ))}
        {extraKeys.map((k) => (
          <div className="row" key={k} style={{ marginBottom: 8 }}>
            <span className="mono small" style={{ flex: "0 0 110px", overflow: "hidden", textOverflow: "ellipsis" }}>{k}</span>
            <input value={String(component.attributes[k] ?? "")}
              onChange={(e) => setAttr(k, e.target.value === "" || isNaN(Number(e.target.value)) ? e.target.value : Number(e.target.value))} />
            <button className="ghost small fixed" onClick={() => setAttr(k, null)} title="Remove">✕</button>
          </div>
        ))}
        <div className="row">
          <input placeholder="custom attribute" value={newKey} onChange={(e) => setNewKey(e.target.value)} />
          <button className="small fixed" disabled={!newKey.trim() || newKey in component.attributes}
            onClick={() => { setAttr(newKey.trim(), 0); setNewKey(""); }}>Add</button>
        </div>
      </div>

      {blastRadius && (
        <div className="section">
          <h3>Blast radius</h3>
          {blastRadius.length === 0 ? (
            <p className="muted small" style={{ margin: 0 }}>Nothing depends on this component.</p>
          ) : (
            <p className="small" style={{ margin: 0 }}>
              If this fails, up to <b>{blastRadius.length}</b> component{blastRadius.length > 1 ? "s" : ""} could be
              affected (dashed on the canvas): {blastRadius.join(", ")}.
              <span className="muted"> Fallbacks and optional links may limit the real impact.</span>
            </p>
          )}
        </div>
      )}

      <div className="section">
        <button className="danger" onClick={onDelete}>Delete component</button>
      </div>
    </>
  );
}

// ---- dependency -------------------------------------------------------
const TYPE_HELP: Record<DependencyType, string> = {
  requires: "Fails or degrades together with its dependency.",
  optional: "Losing the dependency only degrades the dependent.",
  fallback: "A backup: keeps the dependent running in degraded mode. Give it the same group as the primary.",
};

export function DependencyInspector({
  dependency, components, onChange, onDelete,
}: {
  dependency: DependencyDef;
  components: ComponentDef[];
  onChange: (patch: Partial<DependencyDef>) => void;
  onDelete: () => void;
}) {
  const name = (id: string) => components.find((c) => c.id === id)?.name ?? id;
  const autoId = dependency.id === `${dependency.source_id}->${dependency.target_id}`;
  const swap = () => onChange({
    source_id: dependency.target_id,
    target_id: dependency.source_id,
    id: autoId ? `${dependency.target_id}->${dependency.source_id}` : dependency.id,
  });
  return (
    <>
      <div className="section">
        <h3>Dependency</h3>
        <p style={{ margin: "0 0 12px" }}>
          <b>{name(dependency.source_id)}</b> depends on <b>{name(dependency.target_id)}</b>
        </p>
        <Field label="Type" hint={TYPE_HELP[dependency.dependency_type]}>
          <select aria-label="Dependency type" value={dependency.dependency_type}
            onChange={(e) => onChange({ dependency_type: e.target.value as DependencyType })}>
            <option value="requires">requires</option>
            <option value="optional">optional</option>
            <option value="fallback">fallback</option>
          </select>
        </Field>
        <Field label="Group" hint="Dependencies in the same group are interchangeable: one healthy member is enough (replicas, fallbacks).">
          <input aria-label="Dependency group" value={dependency.group ?? ""} placeholder="none"
            onChange={(e) => onChange({ group: e.target.value || null })} />
        </Field>
        <Field label="Propagation delay" hint="Time units before a change in the dependency reaches the dependent.">
          <NumberInput aria-label="Propagation delay" value={dependency.propagation_delay} min={0}
            onChange={(v) => onChange({ propagation_delay: v ?? 0 })} />
        </Field>
        <div className="mono small muted">id: {dependency.id}</div>
      </div>
      <div className="section row" style={{ justifyContent: "flex-start" }}>
        <button className="fixed" onClick={swap}>Reverse direction</button>
        <button className="danger fixed" onClick={onDelete}>Delete</button>
      </div>
    </>
  );
}

// ---- system -----------------------------------------------------------
export function SystemInspector({
  draft, analysis, onChange,
}: {
  draft: SystemDef;
  analysis: SystemAnalysis | null;
  onChange: (patch: Partial<SystemDef>) => void;
}) {
  return (
    <>
      <div className="section">
        <h3>System</h3>
        <Field label="Name">
          <input aria-label="System name" value={draft.name} onChange={(e) => onChange({ name: e.target.value })} />
        </Field>
        <Field label="Description">
          <textarea aria-label="System description" rows={3} value={draft.description} style={{ fontFamily: "inherit", fontSize: 14 }}
            onChange={(e) => onChange({ description: e.target.value })} />
        </Field>
        <div className="small muted">
          {draft.components.length} components · {draft.dependencies.length} dependencies · domain {draft.domain}
        </div>
      </div>
      <div className="section">
        <h3>Validation</h3>
        {!analysis && <span className="muted small">Checking…</span>}
        {analysis?.errors.map((e) => <div key={e} className="notice error">{e}</div>)}
        {analysis?.warnings.map((w) => <div key={w} className="notice warn">{w}</div>)}
        {analysis?.valid && analysis.warnings.length === 0 && <div className="notice ok">No problems found.</div>}
        {analysis?.valid && analysis.entry_points.length > 0 && (
          <div className="small muted">Entry points: {analysis.entry_points.join(", ")}</div>
        )}
      </div>
      <div className="section small muted">
        <h3>How to edit</h3>
        <ul style={{ paddingLeft: 18, margin: 0, lineHeight: 1.6 }}>
          <li>Add components from the toolbar.</li>
          <li>Drag from a component's <b>bottom</b> handle to the component it <b>depends on</b>.</li>
          <li>Click a component or arrow to edit it; press Delete to remove it.</li>
          <li>Save when done. Scenarios always use the saved version.</li>
        </ul>
      </div>
    </>
  );
}
