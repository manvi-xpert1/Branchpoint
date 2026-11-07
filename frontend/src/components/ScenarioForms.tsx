import { useState } from "react";
import type { DomainSpec, EventDef, InterventionDef, InterventionType, SystemDef } from "../api/types";
import { defaultAttributes, entityType, eventTargets, eventType, hasFeature } from "../lib/domains";
import { Field, NumberInput } from "./common";
import { depId } from "./graph";

// ---- events -----------------------------------------------------------
export function EventEditor({
  spec, event, system, componentIds, onChange, onRemove,
}: {
  spec: DomainSpec;
  event: EventDef;
  system: SystemDef;
  /** Component ids that exist after the scenario's interventions. */
  componentIds: string[];
  onChange: (e: EventDef) => void;
  onRemove: () => void;
}) {
  const set = (patch: Partial<EventDef>) => onChange({ ...event, ...patch });
  const et = eventType(spec, event.type);
  const targets = eventTargets(spec, event.type, system, componentIds);
  const changeType = (type: string) => {
    const next = eventType(spec, type);
    const nextTargets = eventTargets(spec, type, system, componentIds);
    set({
      type,
      target_id: nextTargets.includes(event.target_id) ? event.target_id : nextTargets[0] ?? "",
      severity: next?.severity_label ? (event.severity !== 1 ? event.severity : 2) : 1,
      duration: next?.uses_duration === false ? null : event.duration,
    });
  };
  return (
    <div className="editable-row" data-testid={`event-${event.id}`}>
      <div className="row" style={{ marginBottom: 8 }}>
        <select aria-label="Event type" value={event.type} onChange={(e) => changeType(e.target.value)}>
          {!et && <option value={event.type}>{event.type}</option>}
          {spec.event_types.map((t) => <option key={t.type} value={t.type}>{t.label}</option>)}
        </select>
        <select aria-label="Event target" value={event.target_id} onChange={(e) => set({ target_id: e.target.value })}>
          {!targets.includes(event.target_id) && <option value={event.target_id}>{event.target_id || "choose…"} (missing)</option>}
          {targets.map((t) => <option key={t} value={t}>{targetName(system, t)}</option>)}
        </select>
        <button className="ghost small fixed" onClick={onRemove} title="Remove event">✕</button>
      </div>
      {et?.description && <div className="small muted" style={{ margin: "-2px 0 8px" }}>{et.description}</div>}
      <div className="grid3">
        <Field label={`Start (${spec.time_unit})`}>
          <NumberInput aria-label="Start time" value={event.start_time} min={0} onChange={(v) => set({ start_time: v ?? 0 })} />
        </Field>
        {et?.uses_duration !== false && (
          <Field label="Duration">
            <NumberInput aria-label="Duration" value={event.duration} min={0} placeholder="until fixed"
              onChange={(v) => set({ duration: v && v > 0 ? v : null })} />
          </Field>
        )}
        {et?.severity_label && (
          <Field label={et.severity_label}>
            <NumberInput aria-label={et.severity_label} value={event.severity} min={0} onChange={(v) => set({ severity: v ?? 1 })} />
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

function targetName(system: SystemDef, id: string): string {
  const c = system.components.find((x) => x.id === id);
  if (c) return c.name && c.name !== c.id ? `${c.name} (${c.id})` : c.id;
  const d = system.dependencies.find((x) => depId(x) === id);
  if (d) {
    const n = (cid: string) => system.components.find((x) => x.id === cid)?.name ?? cid;
    return `${n(d.source_id)} → ${n(d.target_id)}`;
  }
  return id;
}

// ---- interventions ----------------------------------------------------
/** Typed value from a text box: numbers become numbers, everything else stays text. */
function parseValue(v: string): string | number {
  return v !== "" && !isNaN(Number(v)) ? Number(v) : v;
}

export function defaultParams(type: InterventionType, system: SystemDef, spec: DomainSpec): Record<string, unknown> {
  const firstComp = system.components[0];
  const first = firstComp?.id ?? "";
  const firstDep = system.dependencies[0];
  const rel = spec.relationship_types[0];
  switch (type) {
    case "add_component": {
      const kind = spec.entity_types[1] ?? spec.entity_types[0];
      return { id: `new_${kind?.type ?? "component"}`, name: `New ${kind?.label.toLowerCase() ?? "component"}`,
        type: kind?.type ?? "service", attributes: defaultAttributes(kind?.fields ?? []) };
    }
    case "remove_component": return { id: first };
    case "add_dependency": return { source_id: first, target_id: system.components[1]?.id ?? first,
      dependency_type: rel?.type ?? "requires", group: null, propagation_delay: 0,
      attributes: defaultAttributes(rel?.fields ?? []) };
    case "remove_dependency": return { id: firstDep ? depId(firstDep) : "" };
    case "set_attribute": {
      const field = firstComp ? entityType(spec, firstComp.type).fields.find((f) => f.kind !== "boolean") : undefined;
      const current = field && firstComp ? firstComp.attributes[field.key] : undefined;
      return { component_id: first, key: field?.key ?? "", value: typeof current === "number" ? current : field?.default ?? "" };
    }
    case "set_dependency_attribute": {
      const field = rel?.fields[0];
      return { dependency_id: firstDep ? depId(firstDep) : "", key: field?.key ?? "", value: field?.default ?? "" };
    }
    case "set_parameter": {
      const field = spec.parameters[0];
      return { key: field?.key ?? Object.keys(system.parameters ?? {})[0] ?? "", value: field?.default ?? "" };
    }
  }
}

/** A key picker: the catalog's fields as options, plus free text for custom keys. */
function KeyPicker({ label, value, fields, onChange }: {
  label: string; value: string; fields: { key: string; label: string; unit: string }[]; onChange: (k: string) => void;
}) {
  const known = fields.some((f) => f.key === value);
  return (
    <Field label={label}>
      <select aria-label={label} value={known ? value : "__custom"} onChange={(e) => e.target.value !== "__custom" && onChange(e.target.value)}>
        {fields.map((f) => <option key={f.key} value={f.key}>{f.label}{f.unit ? ` (${f.unit})` : ""}</option>)}
        <option value="__custom">{known || !value ? "Other…" : `Other: ${value}`}</option>
      </select>
      {!known && <input aria-label={`${label} name`} className="mono" style={{ marginTop: 4 }} value={value}
        placeholder="attribute name" onChange={(e) => onChange(e.target.value)} />}
    </Field>
  );
}

export function InterventionEditor({
  spec, iv, system, componentIds, onChange, onRemove,
}: {
  spec: DomainSpec;
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
            onChange({ ...iv, type, params: defaultParams(type, system, spec) });
          }}>
          {spec.intervention_types.map((t) => <option key={t.type} value={t.type}>{t.label}</option>)}
        </select>
        <button className="ghost small fixed" onClick={onRemove} title="Remove intervention">✕</button>
      </div>

      {iv.type === "add_component" && (
        <>
          <div className="grid2">
            <Field label="Id"><input className="mono" value={p.id ?? ""} onChange={(e) => setP({ id: e.target.value })} /></Field>
            <Field label="Type">
              <select value={p.type ?? ""} onChange={(e) => setP({
                type: e.target.value, attributes: defaultAttributes(entityType(spec, e.target.value).fields) })}>
                {spec.entity_types.map((k) => <option key={k.type} value={k.type}>{k.label}</option>)}
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
            {compSelect(hasFeature(spec, "groups") ? "Dependent (source)" : "From", "source_id")}
            {compSelect(hasFeature(spec, "groups") ? "Depends on (target)" : "To", "target_id")}
            <Field label="Type">
              <select value={p.dependency_type ?? ""} onChange={(e) => setP({ dependency_type: e.target.value })}>
                {spec.relationship_types.map((r) => <option key={r.type} value={r.type}>{r.label}</option>)}
              </select>
            </Field>
            {hasFeature(spec, "groups") && (
              <Field label="Group">
                <input value={p.group ?? ""} placeholder="none" onChange={(e) => setP({ group: e.target.value || null })} />
              </Field>
            )}
          </div>
          {hasFeature(spec, "propagation_delay") && (
            <Field label="Propagation delay">
              <NumberInput value={p.propagation_delay ?? 0} min={0} onChange={(v) => setP({ propagation_delay: v ?? 0 })} />
            </Field>
          )}
          <JsonField label="Settings" value={p.attributes ?? {}} onChange={(attributes) => setP({ attributes })} />
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
          <KeyPicker label="Attribute" value={p.key ?? ""} onChange={(key) => setP({ key })}
            fields={entityType(spec, system.components.find((c) => c.id === p.component_id)?.type ?? "").fields
              .filter((f) => f.kind !== "boolean")} />
          <Field label="Value">
            <input value={p.value ?? ""} onChange={(e) => {
              const v = e.target.value;
              setP({ value: v !== "" && !isNaN(Number(v)) ? Number(v) : v });
            }} />
          </Field>
        </div>
      )}
      {iv.type === "set_dependency_attribute" && (
        <div className="grid3">
          <Field label="Dependency">
            <select aria-label="Dependency to change" value={p.dependency_id ?? ""} onChange={(e) => setP({ dependency_id: e.target.value })}>
              {!system.dependencies.some((d) => depId(d) === p.dependency_id) && <option value={p.dependency_id ?? ""}>{p.dependency_id || "choose…"}</option>}
              {system.dependencies.map((d) => <option key={depId(d)} value={depId(d)}>{depId(d)}</option>)}
            </select>
          </Field>
          <KeyPicker label="Attribute" value={p.key ?? ""} onChange={(key) => setP({ key })}
            fields={(spec.relationship_types.find((r) => r.type === system.dependencies.find((d) => depId(d) === p.dependency_id)?.dependency_type)?.fields ?? [])
              .filter((f) => f.kind !== "boolean")} />
          <Field label="Value"><input value={p.value ?? ""} onChange={(e) => setP({ value: parseValue(e.target.value) })} /></Field>
        </div>
      )}
      {iv.type === "set_parameter" && (
        <div className="grid2">
          <KeyPicker label="Parameter" value={p.key ?? ""} onChange={(key) => setP({ key })}
            fields={spec.parameters} />
          <Field label="Value"><input aria-label="Parameter value" value={p.value ?? ""} onChange={(e) => setP({ value: parseValue(e.target.value) })} /></Field>
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
    case "set_dependency_attribute": return `${p.dependency_id}.${p.key} = ${p.value}`;
    case "set_parameter": return `Parameter ${p.key} = ${p.value}`;
  }
}

export function summarizeEvent(spec: DomainSpec, e: EventDef): string {
  const et = eventType(spec, e.type);
  const what = et?.label ?? e.type;
  const dur = e.duration ? ` for ${e.duration}` : "";
  const sev = et?.severity_label ? ` (${et.severity_label.toLowerCase()} ${e.severity})` : "";
  const prob = e.probability < 1 ? ` (p=${e.probability})` : "";
  return `${what}${sev} on ${e.target_id} at t=${e.start_time}${dur}${prob}`;
}
