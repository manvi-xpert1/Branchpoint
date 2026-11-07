import { useState } from "react";
import type { ComponentDef, DependencyDef, DomainSpec, FieldSpec, SystemAnalysis, SystemDef } from "../api/types";
import { entityType, hasFeature } from "../lib/domains";
import { Field, NumberInput } from "./common";

const ID_PATTERN = /^[A-Za-z0-9_.-]+$/;

/** An input for one catalog field (attribute, relationship setting or system parameter). */
export function FieldInput({ field, value, onChange }: {
  field: FieldSpec; value: unknown; onChange: (v: unknown) => void;
}) {
  const unit = field.unit ? ` (${field.unit})` : "";
  const placeholder = field.default !== null && field.default !== undefined ? `default ${String(field.default)}` : "not set";
  if (field.kind === "boolean") {
    const checked = value === undefined || value === null ? Boolean(field.default) : Boolean(value);
    return (
      <label className="check" title={field.help}>
        <input type="checkbox" aria-label={field.label} checked={checked} onChange={(e) => onChange(e.target.checked)} />
        <span>{field.label}{field.help && <span className="hint small muted" style={{ display: "block" }}>{field.help}</span>}</span>
      </label>
    );
  }
  if (field.kind === "choice") {
    return (
      <Field label={field.label} hint={field.help}>
        <select aria-label={field.label} value={String(value ?? field.default ?? "")} onChange={(e) => onChange(e.target.value)}>
          {field.choices.map((c) => <option key={c} value={c}>{c}</option>)}
        </select>
      </Field>
    );
  }
  if (field.kind === "text") {
    return (
      <Field label={field.label} hint={field.help}>
        <input aria-label={field.label} value={String(value ?? "")} onChange={(e) => onChange(e.target.value || null)} />
      </Field>
    );
  }
  const max = field.kind === "probability" ? 1 : field.max ?? undefined;
  return (
    <Field label={`${field.label}${unit}`} hint={field.help}>
      <NumberInput aria-label={field.label} value={typeof value === "number" ? value : null}
        min={field.min ?? undefined} step={field.kind === "integer" ? 1 : field.kind === "probability" ? 0.05 : "any"}
        placeholder={placeholder}
        onChange={(v) => {
          if (v === null) return onChange(null);
          let n = field.kind === "integer" ? Math.round(v) : v;
          if (field.min !== null && n < field.min) n = field.min;
          if (max !== undefined && n > max) n = max;
          onChange(n);
        }} />
    </Field>
  );
}

function setIn(obj: Record<string, unknown>, key: string, value: unknown): Record<string, unknown> {
  const next = { ...obj };
  if (value === null || value === undefined || value === "") delete next[key];
  else next[key] = value;
  return next;
}

function CustomAttributes({ attributes, known, onChange }: {
  attributes: Record<string, unknown>; known: string[]; onChange: (a: Record<string, unknown>) => void;
}) {
  const [newKey, setNewKey] = useState("");
  const extra = Object.keys(attributes).filter((k) => !known.includes(k));
  return (
    <>
      {extra.map((k) => (
        <div className="row" key={k} style={{ marginBottom: 8 }}>
          <span className="mono small" style={{ flex: "0 0 110px", overflow: "hidden", textOverflow: "ellipsis" }}>{k}</span>
          <input aria-label={`Custom attribute ${k}`} value={String(attributes[k] ?? "")}
            onChange={(e) => onChange(setIn(attributes, k,
              e.target.value === "" || isNaN(Number(e.target.value)) ? e.target.value : Number(e.target.value)))} />
          <button className="ghost small fixed" onClick={() => onChange(setIn(attributes, k, null))} title="Remove">✕</button>
        </div>
      ))}
      <div className="row">
        <input placeholder="custom attribute" aria-label="New custom attribute" value={newKey} onChange={(e) => setNewKey(e.target.value)} />
        <button className="small fixed" disabled={!newKey.trim() || newKey in attributes}
          onClick={() => { onChange({ ...attributes, [newKey.trim()]: 0 }); setNewKey(""); }}>Add</button>
      </div>
    </>
  );
}

// ---- component --------------------------------------------------------
export function ComponentInspector({
  spec, component, allIds, blastRadius, onChange, onDelete,
}: {
  spec: DomainSpec;
  component: ComponentDef;
  allIds: string[];
  blastRadius?: string[];
  onChange: (patch: Partial<ComponentDef>) => void;
  onDelete: () => void;
}) {
  const [idText, setIdText] = useState(component.id);
  const idError = !ID_PATTERN.test(idText)
    ? "Letters, digits, _ . - only"
    : idText !== component.id && allIds.includes(idText) ? "Id already used" : null;
  const kind = entityType(spec, component.type);
  const types = spec.entity_types.some((k) => k.type === component.type) ? spec.entity_types : [...spec.entity_types, kind];
  const setAttr = (key: string, value: unknown) => onChange({ attributes: setIn(component.attributes, key, value) });

  return (
    <>
      <div className="section">
        <h3>{kind.label}</h3>
        {kind.description && <p className="small muted" style={{ margin: "-4px 0 10px" }}>{kind.description}</p>}
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
        {hasFeature(spec, "entry_points") && (
          <label className="check">
            <input type="checkbox" checked={component.entry_point} onChange={(e) => onChange({ entry_point: e.target.checked })} />
            <span>Entry point <span className="muted small">(availability is measured here)</span></span>
          </label>
        )}
      </div>

      <div className="section">
        <h3>Settings</h3>
        {kind.fields.map((f) => (
          <FieldInput key={f.key} field={f} value={component.attributes[f.key]} onChange={(v) => setAttr(f.key, v)} />
        ))}
        <CustomAttributes attributes={component.attributes} known={kind.fields.map((f) => f.key)}
          onChange={(attributes) => onChange({ attributes })} />
      </div>

      {blastRadius && hasFeature(spec, "propagation_delay") && (
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
        <button className="danger" onClick={onDelete}>Delete {kind.label.toLowerCase()}</button>
      </div>
    </>
  );
}

// ---- relationship -----------------------------------------------------
export function DependencyInspector({
  spec, dependency, components, onChange, onDelete,
}: {
  spec: DomainSpec;
  dependency: DependencyDef;
  components: ComponentDef[];
  onChange: (patch: Partial<DependencyDef>) => void;
  onDelete: () => void;
}) {
  const name = (id: string) => components.find((c) => c.id === id)?.name ?? id;
  const autoId = dependency.id === `${dependency.source_id}->${dependency.target_id}`;
  const rt = spec.relationship_types.find((r) => r.type === dependency.dependency_type);
  const statusDomain = hasFeature(spec, "propagation_delay");
  const swap = () => onChange({
    source_id: dependency.target_id,
    target_id: dependency.source_id,
    id: autoId ? `${dependency.target_id}->${dependency.source_id}` : dependency.id,
  });
  const attrs = dependency.attributes ?? {};
  return (
    <>
      <div className="section">
        <h3>{statusDomain ? "Dependency" : rt?.label ?? "Connection"}</h3>
        <p style={{ margin: "0 0 12px" }}>
          {statusDomain
            ? <><b>{name(dependency.source_id)}</b> depends on <b>{name(dependency.target_id)}</b></>
            : <><b>{name(dependency.source_id)}</b> → <b>{name(dependency.target_id)}</b></>}
        </p>
        {spec.relationship_types.length > 1 && (
          <Field label="Type" hint={rt?.description}>
            <select aria-label="Dependency type" value={dependency.dependency_type}
              onChange={(e) => onChange({ dependency_type: e.target.value })}>
              {spec.relationship_types.map((r) => <option key={r.type} value={r.type}>{r.label}</option>)}
            </select>
          </Field>
        )}
        {spec.relationship_types.length === 1 && rt?.description && <p className="small muted">{rt.description}</p>}
        {hasFeature(spec, "groups") && (
          <Field label="Group" hint="Dependencies in the same group are interchangeable: one healthy member is enough (replicas, fallbacks).">
            <input aria-label="Dependency group" value={dependency.group ?? ""} placeholder="none"
              onChange={(e) => onChange({ group: e.target.value || null })} />
          </Field>
        )}
        {hasFeature(spec, "propagation_delay") && (
          <Field label="Propagation delay" hint="Time units before a change in the dependency reaches the dependent.">
            <NumberInput aria-label="Propagation delay" value={dependency.propagation_delay} min={0}
              onChange={(v) => onChange({ propagation_delay: v ?? 0 })} />
          </Field>
        )}
        {rt?.fields.map((f) => (
          <FieldInput key={f.key} field={f} value={attrs[f.key]}
            onChange={(v) => onChange({ attributes: setIn(attrs, f.key, v) })} />
        ))}
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
  spec, draft, analysis, onChange,
}: {
  spec: DomainSpec;
  draft: SystemDef;
  analysis: SystemAnalysis | null;
  onChange: (patch: Partial<SystemDef>) => void;
}) {
  const params = draft.parameters ?? {};
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
          {draft.components.length} components · {draft.dependencies.length} connections · {spec.label}
        </div>
      </div>
      {spec.parameters.length > 0 && (
        <div className="section">
          <h3>System parameters</h3>
          {spec.parameters.map((f) => (
            <FieldInput key={f.key} field={f} value={params[f.key]}
              onChange={(v) => onChange({ parameters: setIn(params, f.key, v) })} />
          ))}
        </div>
      )}
      <div className="section">
        <h3>Validation</h3>
        {!analysis && <span className="muted small">Checking…</span>}
        {analysis?.errors.map((e) => <div key={e} className="notice error">{e}</div>)}
        {analysis?.warnings.map((w) => <div key={w} className="notice warn">{w}</div>)}
        {analysis?.valid && analysis.warnings.length === 0 && <div className="notice ok">No problems found.</div>}
        {analysis?.valid && hasFeature(spec, "entry_points") && analysis.entry_points.length > 0 && (
          <div className="small muted">Entry points: {analysis.entry_points.join(", ")}</div>
        )}
      </div>
      <div className="section small muted">
        <h3>How to edit</h3>
        <ul style={{ paddingLeft: 18, margin: 0, lineHeight: 1.6 }}>
          <li>Add {spec.entity_types.map((e) => e.label.toLowerCase()).slice(0, 3).join(", ")}… from the toolbar.</li>
          <li>Drag from a box's <b>bottom</b> handle to another box to connect them. {spec.edge_meaning}</li>
          <li>Click a box or arrow to edit it; press Delete to remove it.</li>
          <li>Save when done. Scenarios always use the saved version.</li>
        </ul>
      </div>
      <details className="section small">
        <summary><b>Model assumptions</b></summary>
        <ul style={{ paddingLeft: 18, margin: "8px 0 0", lineHeight: 1.55 }} className="muted">
          {spec.assumptions.map((a) => <li key={a}>{a}</li>)}
        </ul>
      </details>
    </>
  );
}
