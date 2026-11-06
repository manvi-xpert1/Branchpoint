import { useEffect, useRef, useState } from "react";
import { useNavigate } from "react-router-dom";
import { api } from "../api/client";
import type { SystemSummary } from "../api/types";
import { ErrorNotice, errorMessage } from "../components/common";
import { useToast } from "../components/Toast";
import TopBar from "../components/TopBar";
import example from "../examples/ecommerce.json";

export default function ProjectsPage() {
  const [systems, setSystems] = useState<SystemSummary[] | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const fileInput = useRef<HTMLInputElement>(null);
  const navigate = useNavigate();
  const toast = useToast();

  const load = () =>
    api.listSystems().then(setSystems).catch((e) => setError(`Cannot reach the API: ${errorMessage(e)}`));
  useEffect(() => { load(); }, []);

  const act = async (fn: () => Promise<void>) => {
    setBusy(true);
    setError(null);
    try { await fn(); } catch (e) { setError(errorMessage(e)); } finally { setBusy(false); }
  };

  const createBlank = () => act(async () => {
    const s = await api.createSystem({
      name: "Untitled system", domain: "software_infrastructure", description: "",
      components: [], dependencies: [],
    });
    navigate(`/systems/${s.id}/design`);
  });

  const importData = (data: unknown) => act(async () => {
    const out = await api.importExperiment(data);
    toast(`Imported ${Object.keys(out.scenario_ids).length} scenarios`);
    navigate(`/systems/${out.system_id}/design`);
  });

  const importFile = async (file: File) => {
    try {
      importData(JSON.parse(await file.text()));
    } catch (e) {
      setError(`Not valid JSON: ${errorMessage(e)}`);
    }
  };

  const remove = (s: SystemSummary) => {
    if (!confirm(`Delete "${s.name}" with all its scenarios and runs?`)) return;
    act(async () => { await api.deleteSystem(s.id); await load(); toast("System deleted"); });
  };

  return (
    <div className="app">
      <TopBar />
      <main className="page">
        <div className="page-narrow stack" style={{ gap: 20 }}>
          <div className="row" style={{ alignItems: "flex-end" }}>
            <div>
              <h1>Systems</h1>
              <p className="muted" style={{ margin: "4px 0 0" }}>
                Model a system, inject failures, branch scenarios and compare decisions.
              </p>
            </div>
            <div className="fixed row">
              <button onClick={() => importData(example)} disabled={busy}>Load example</button>
              <button onClick={() => fileInput.current?.click()} disabled={busy}>Import JSON…</button>
              <button className="primary" onClick={createBlank} disabled={busy}>New system</button>
              <input ref={fileInput} type="file" accept=".json,application/json" hidden
                onChange={(e) => { const f = e.target.files?.[0]; if (f) importFile(f); e.target.value = ""; }} />
            </div>
          </div>
          <ErrorNotice error={error} />
          {systems === null && !error && <div className="empty"><span className="spinner" /></div>}
          {systems?.length === 0 && (
            <div className="card empty">
              <h2 style={{ color: "var(--text)", marginBottom: 8 }}>No systems yet</h2>
              <p>Start from the e-commerce example (a database outage with three recovery options),
                or build your own.</p>
              <button className="primary" onClick={() => importData(example)} disabled={busy}>Load example</button>
            </div>
          )}
          <div className="cards">
            {systems?.map((s) => (
              <div key={s.id} className="card system-card" onClick={() => navigate(`/systems/${s.id}/design`)}>
                <div className="row">
                  <h2>{s.name}</h2>
                  <button className="ghost small danger fixed" title="Delete"
                    onClick={(e) => { e.stopPropagation(); remove(s); }}>Delete</button>
                </div>
                {s.description && <div className="muted small">{s.description}</div>}
                <div className="row small muted" style={{ justifyContent: "flex-start", gap: 14 }}>
                  <span className="fixed">{s.component_count} components</span>
                  <span className="fixed">{s.dependency_count} dependencies</span>
                  <span className="fixed">{s.scenario_count} scenarios</span>
                </div>
                <div className="small muted">Updated {new Date(s.updated_at).toLocaleString()}</div>
              </div>
            ))}
          </div>
        </div>
      </main>
    </div>
  );
}
