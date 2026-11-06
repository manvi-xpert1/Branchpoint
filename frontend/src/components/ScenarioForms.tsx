import { useState } from "react";
import type {
  DependencyType, EventDef, EventType, InterventionDef, InterventionType, SystemDef,
} from "../api/types";
import { COMPONENT_KINDS, EVENT_LABELS } from "../lib/catalog";
import { Field, NumberInput } from "./common";
import { depId } from "./graph";

// ---- events -----------------------------------------------------------
export function EventEditor({
  event, targets, onChange, onRemove,
}: {
  event: EventDef;
  targets: string[];
  onChange: (e: EventDef) => void;
  onRemove: () => void;
}) {
  const set = (patch: Partial<EventDef>) => onChange({ ...event, ...patch });
  const isRecovery = event.type === "component_recovery";
  return (
    <div className="editable-row" data-testid={`event-${event.id}`}>
      <div className="row" style={{ marginBottom: 8 }}>
        <select aria-label="Event type" value={event.type} onChange={(e) => set({ type: e.target.value as EventType })}>
          {Object.entries(EVENT_LABELS).map(([v, l]) => <option key={v} value={v}>{l}</option>)}
        </select>
        <select aria-label="Event target" value={event.target_id} onChange={(e) => set({ target_id: e.target.value })}>
          {!targets.includes(event.target_id) && <option value={event.target_id}>{event.target_id} (missing)</option>}
          {targets.map((t) => <option key={t} value={t}>{t}</option>)}
        </select>
        <button className="ghost small fixed" onClick={onRemove} title="Remove event">✕</button>
      </div>
      <div className="grid3">
        <Field label="Start time">
          <NumberInput aria-label="Start time" value={event.start_time} min={0} onChange={(v) => set({ start_time: v ?? 0 })} />
        </Field>
        {!isRecovery && (
          <Field label="Duration">
            <NumberInput aria-label="Duration" value={event.duration} min={0} placeholder="until fixed"
              onChange={(v) => set({ duration: v && v > 0 ? v : null })} />
          </Field>
        )}
        {event.type === "traffic_spike" && (
          <Field label="Load ×">
            <NumberInput aria-label="Load multiplier" value={event.severity} min={0} onChange={(v) => set({ severity: v ?? 1 })} />
          </Field>
        )}
        <Field label="Probability">
          <NumberInput aria-label="Probability" value={event.probability} min={0} step={0.05}
            onChange={(v) => set({ probability: Math.min(1, Math.max(0, v ?? 1)) })} />
        </Field>
      </div>
      <div className="mono small muted" style={{ marginTop: 6 }}>id: {event.id}</div>
    </div>
  );
}

// ---- interventions ----------------------------------------------------
const IV_LABELS: Record<InterventionType, string> = {
  add_component: "Add component",
  remove_component: "Remove component",
  add_dependency: "Add dependency",
  remove_dependency: "Remove dependency",
  set_attribute: "Set attribute",
};

export function defaultParams(type: InterventionType, system: SystemDef): Record<string, unknown> {
  const first = system.components[0]?.id ?? "";
  switch (type) {
    case "add_component": return { id: "new_component", name: "New component", type: "service", attributes: {} };
    case "remove_component": return { id: first };
    case "add_dependency": return { source_id: first, target_id: system.components[1]?.id ?? first,
      dependency_type: "requires", group: null, propagation_delay: 0 };
    case "remove_dependency": return { id: system.dependencies[0] ? depId(system.dependencies[0]) : "" };
    case "set_attribute": return { component_id: first, key: "capacity", value: 1000 };
  }
}

export function InterventionEditor({
  iv, system, componentIds, onChange, onRemove,
}: {
  iv: InterventionDef;
  system: SystemDef;
  componentIds: string[];
  onChange: (iv: InterventionDef) => void;
  onRemove: () => void;
}) {
  const p = iv.params as Record<string, any>;
  const setP = (patch: Record<string, unknown>) => onChange({ ...iv, params: { ...p, ...patch } });
  const compSelect = (label: string, key: string) => (
    <Field label={label}>
      <select aria-label={label} value={p[key] ?? ""} onChange={(e) => setP({ [key]: e.target.value })}>
        {!componentIds.includes(p[key]) && <option value={p[key] ?? ""}>{p[key] || "choose…"}</option>}
        {componentIds.map((c) => <option key={c} value={c}>{c}</option>)}
      </select>
    </Field>
  );

  return (
    <div className="editable-row" data-testid={`intervention-${iv.id}`}>
      <div className="row" style={{ marginBottom: 8 }}>
        <select aria-label="Intervention type" value={iv.type}
          onChange={(e) => {
            const type = e.target.value as InterventionType;
            onChange({ ...iv, type, params: defaultParams(type, system) });
          }}>
          {Object.entries(IV_LABELS).map(([v, l]) => <option key={v} value={v}>{l}</option>)}
        </select>
        <button className="ghost small fixed" onClick={onRemove} title="Remove intervention">✕</button>
      </div>

      {iv.type === "add_component" && (
        <>
          <div className="grid2">
            <Field label="Id"><input className="mono" value={p.id ?? ""} onChange={(e) => setP({ id: e.target.value })} /></Field>
            <Field label="Type">
              <select value={p.type ?? "service"} onChange={(e) => setP({ type: e.target.value })}>
                {COMPONENT_KINDS.map((k) => <option key={k.type} value={k.type}>{k.label}</option>)}
              </select>
            </Field>
          </div>
          <Field label="Name"><input value={p.name ?? ""} onChange={(e) => setP({ name: e.target.value })} /></Field>
          <JsonField label="Attributes" value={p.attributes ?? {}} onChange={(attributes) => setP({ attributes })} />
        </>
      )}
      {iv.type === "remove_component" && compSelect("Component", "id")}
      {iv.type === "add_dependency" && (
        <>
          <div className="grid2">
            {compSelect("Dependent (source)", "source_id")}
            {compSelect("Depends on (target)", "target_id")}
            <Field label="Type">
              <select value={p.dependency_type ?? "requires"} onChange={(e) => setP({ dependency_type: e.target.value as DependencyType })}>
                <option>requires</option><option>optional</option><option>fallback</option>
              </select>
            </Field>
            <Field label="Group">
              <input value={p.group ?? ""} placeholder="none" onChange={(e) => setP({ group: e.target.value || null })} />
            </Field>
          </div>
          <Field label="Propagation delay">
            <NumberInput value={p.propagation_delay ?? 0} min={0} onChange={(v) => setP({ propagation_delay: v ?? 0 })} />
          </Field>
        </>
      )}
      {iv.type === "remove_dependency" && (
        <Field label="Dependency">
          <select aria-label="Dependency to remove" value={p.id ?? ""} onChange={(e) => setP({ id: e.target.value })}>
            {!system.dependencies.some((d) => depId(d) === p.id) && <option value={p.id ?? ""}>{p.id || "choose…"}</option>}
            {system.dependencies.map((d) => <option key={depId(d)} value={depId(d)}>{depId(d)}</option>)}
          </select>
        </Field>
      )}
      {iv.type === "set_attribute" && (
        <div className="grid3">
          {compSelect("Component", "component_id")}
          <Field label="Attribute"><input value={p.key ?? ""} onChange={(e) => setP({ key: e.target.value })} /></Field>
          <Field label="Value">
            <input value={p.value ?? ""} onChange={(e) => {
              const v = e.target.value;
              setP({ value: v !== "" && !isNaN(Number(v)) ? Number(v) : v });
            }} />
          </Field>
        </div>
      )}

      <div className="grid2" style={{ marginTop: 8 }}>
        <Field label="Cost">
          <NumberInput aria-label="Cost" value={iv.cost} min={0} onChange={(v) => onChange({ ...iv, cost: v ?? 0 })} />
        </Field>
        <Field label="Description">
          <input value={iv.description} onChange={(e) => onChange({ ...iv, description: e.target.value })} />
        </Field>
      </div>
      <div className="mono small muted" style={{ marginTop: 6 }}>id: {iv.id}</div>
    </div>
  );
}

function JsonField({ label, value, onChange }: { label: string; value: unknown; onChange: (v: any) => void }) {
  const [text, setText] = useState(JSON.stringify(value));
  const [error, setError] = useState(false);
  return (
    <Field label={label} hint={error ? "Invalid JSON object" : 'e.g. {"capacity": 1000}'}>
      <input className="mono" value={text} style={error ? { borderColor: "var(--bad)" } : undefined}
        onChange={(e) => {
          setText(e.target.value);
          try {
            const parsed = JSON.parse(e.target.value || "{}");
            if (typeof parsed !== "object" || Array.isArray(parsed) || parsed === null) throw new Error();
            setError(false);
            onChange(parsed);
          } catch {
            setError(true);
          }
        }} />
    </Field>
  );
}

export function summarizeIntervention(iv: InterventionDef): string {
  if (iv.description) return iv.description;
  const p = iv.params as Record<string, any>;
  switch (iv.type) {
    case "add_component": return `Add ${p.id}`;
    case "remove_component": return `Remove ${p.id}`;
    case "add_dependency": return `${p.source_id} → ${p.target_id} (${p.dependency_type ?? "requires"})`;
    case "remove_dependency": return `Remove dependency ${p.id}`;
    case "set_attribute": return `${p.component_id}.${p.key} = ${p.value}`;
  }
}

export function summarizeEvent(e: EventDef): string {
  const what = EVENT_LABELS[e.type] ?? e.type;
  const dur = e.duration ? ` for ${e.duration}` : "";
  const sev = e.type === "traffic_spike" ? ` ×${e.severity}` : "";
  const prob = e.probability < 1 ? ` (p=${e.probability})` : "";
  return `${what}${sev} on ${e.target_id} at t=${e.start_time}${dur}${prob}`;
}
