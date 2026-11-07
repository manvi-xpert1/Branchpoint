import { useEffect, useRef, useState } from "react";
import { useNavigate } from "react-router-dom";
import { api } from "../api/client";
import type { SystemSummary } from "../api/types";
import { DOMAIN_LABELS, useDomains } from "../api/useDomains";
import { ErrorNotice, errorMessage } from "../components/common";
import { useToast } from "../components/Toast";
import TopBar from "../components/TopBar";
import { EXAMPLES, type ExampleInfo } from "../lib/examples";

export default function ProjectsPage() {
  const [systems, setSystems] = useState<SystemSummary[] | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const [creating, setCreating] = useState(false);
  const fileInput = useRef<HTMLInputElement>(null);
  const navigate = useNavigate();
  const toast = useToast();
  const { domains } = useDomains();

  const load = () =>
    api.listSystems().then(setSystems).catch((e) => setError(`Cannot reach the API: ${errorMessage(e)}`));
  useEffect(() => { load(); }, []);

  const act = async (fn: () => Promise<void>) => {
    setBusy(true);
    setError(null);
    try { await fn(); } catch (e) { setError(errorMessage(e)); } finally { setBusy(false); }
  };

  const createBlank = (domain: string) => act(async () => {
    const spec = domains?.find((d) => d.name === domain);
    const params = Object.fromEntries((spec?.parameters ?? []).filter((p) => p.default !== null).map((p) => [p.key, p.default]));
    const s = await api.createSystem({
      name: `Untitled ${spec?.label.toLowerCase() ?? "system"}`, domain, description: "",
      components: [], dependencies: [], parameters: params,
    });
    navigate(`/systems/${s.id}/design`);
  });

  const openExample = (ex: ExampleInfo) => act(async () => {
    const out = await api.importExperiment(ex.data);
    toast(`Imported ${Object.keys(out.scenario_ids).length} scenarios`);
    navigate(`/systems/${out.system_id}/futures?group=${out.scenario_ids[ex.focus] ?? ""}`);
  });

  const importFile = async (file: File) => {
    try {
      const data = JSON.parse(await file.text());
      act(async () => {
        const out = await api.importExperiment(data);
        toast(`Imported ${Object.keys(out.scenario_ids).length} scenarios`);
        navigate(`/systems/${out.system_id}/design`);
      });
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
      <TopBar showSystemsLink={false} />
      <main className="page">
        <div className="page-narrow stack" style={{ gap: 20 }}>
          <div className="row" style={{ alignItems: "flex-end", flexWrap: "wrap" }}>
            <div>
              <h1>Your systems</h1>
              <p className="muted" style={{ margin: "4px 0 0" }}>
                Model a system, branch its future once per decision, and compare where each one leads.
              </p>
            </div>
            <div className="fixed row">
              <button onClick={() => fileInput.current?.click()} disabled={busy}>Import JSON…</button>
              <button className="primary" onClick={() => setCreating((c) => !c)} disabled={busy} aria-expanded={creating}>New system</button>
              <input ref={fileInput} type="file" accept=".json,application/json" hidden
                onChange={(e) => { const f = e.target.files?.[0]; if (f) importFile(f); e.target.value = ""; }} />
            </div>
          </div>
          {creating && (
            <div className="card">
              <h2 style={{ marginBottom: 10 }}>What are you modelling?</h2>
              <div className="cards">
                {(domains ?? []).map((d) => (
                  <button key={d.name} className="domain-choice" onClick={() => createBlank(d.name)} disabled={busy}>
                    <b>{d.label}</b><span className="small muted">{d.description}</span>
                  </button>
                ))}
              </div>
            </div>
          )}
          <ErrorNotice error={error} />

          <div>
            <h2 style={{ marginBottom: 10 }}>Examples</h2>
            <div className="cards">
              {EXAMPLES.map((ex) => (
                <button key={ex.domain} className="domain-choice" onClick={() => openExample(ex)} disabled={busy}
                  data-testid={`load-${ex.domain}`}>
                  <span className="domain-chip">{ex.title}</span>
                  <b>{ex.data.system.name}</b>
                  <span className="small muted">{ex.tagline} {ex.data.scenarios.length} scenarios.</span>
                </button>
              ))}
            </div>
          </div>

          {systems === null && !error && <div className="empty"><span className="spinner" /></div>}
          {systems && systems.length > 0 && <h2>Saved</h2>}
          <div className="cards">
            {systems?.map((s) => (
              <div key={s.id} className="card system-card" onClick={() => navigate(`/systems/${s.id}/design`)}>
                <div className="row">
                  <h2>{s.name}</h2>
                  <button className="ghost small danger fixed" title="Delete"
                    onClick={(e) => { e.stopPropagation(); remove(s); }}>Delete</button>
                </div>
                <span className="domain-chip" style={{ alignSelf: "flex-start" }}>{DOMAIN_LABELS[s.domain] ?? s.domain}</span>
                {s.description && <div className="muted small clamp">{s.description}</div>}
                <div className="row small muted" style={{ justifyContent: "flex-start", gap: "4px 14px", flexWrap: "wrap" }}>
                  <span className="fixed">{s.component_count} parts</span>
                  <span className="fixed">{s.dependency_count} connections</span>
                  <span className="fixed">{s.scenario_count} scenarios</span>
                </div>
                <div className="small muted">Updated {new Date(s.updated_at).toLocaleString()}</div>
              </div>
            ))}
          </div>
          {systems?.length === 0 && <p className="muted">No saved systems yet: open an example or create a new one.</p>}
        </div>
      </main>
    </div>
  );
}
