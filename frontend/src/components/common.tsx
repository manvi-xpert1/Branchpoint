import type { ReactNode } from "react";
import type { Status } from "../api/types";

export function Field({ label, hint, children }: { label: string; hint?: ReactNode; children: ReactNode }) {
  return (
    <label className="field">
      <span>{label}</span>
      {children}
      {hint && <span className="hint">{hint}</span>}
    </label>
  );
}

/** Number input that allows an empty value (null). */
export function NumberInput({
  value, onChange, min, step = "any", placeholder, ...rest
}: {
  value: number | null | undefined;
  onChange: (v: number | null) => void;
  min?: number;
  step?: string | number;
  placeholder?: string;
  "aria-label"?: string;
}) {
  return (
    <input
      type="number"
      value={value ?? ""}
      min={min}
      step={step}
      placeholder={placeholder}
      aria-label={rest["aria-label"]}
      onChange={(e) => onChange(e.target.value === "" ? null : Number(e.target.value))}
    />
  );
}

export function StatusPill({ status }: { status: Status }) {
  return <span className={`pill ${status}`}><span className="dot" style={{ background: "currentColor" }} />{status}</span>;
}

export function ErrorNotice({ error }: { error: string | null }) {
  return error ? <div className="notice error" role="alert">{error}</div> : null;
}

export function fmt(n: number | null | undefined, digits = 2): string {
  if (n === null || n === undefined) return "–";
  return Number.isInteger(n) ? String(n) : n.toFixed(digits).replace(/\.?0+$/, "");
}

export function pct(n: number): string {
  return `${(n * 100).toFixed(1)}%`;
}

export function download(filename: string, data: unknown) {
  const blob = new Blob([JSON.stringify(data, null, 2)], { type: "application/json" });
  const url = URL.createObjectURL(blob);
  const a = document.createElement("a");
  a.href = url;
  a.download = filename;
  a.click();
  URL.revokeObjectURL(url);
}

export function errorMessage(e: unknown): string {
  return e instanceof Error ? e.message : String(e);
}
