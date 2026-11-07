import { useRef, useState } from "react";
import { Link, useNavigate } from "react-router-dom";
import { api } from "../api/client";
import { ErrorNotice, errorMessage } from "../components/common";
import { useToast } from "../components/Toast";
import { Logo } from "../components/TopBar";
import { EXAMPLES, scenarioTree, type ExampleInfo } from "../lib/examples";

const STEPS = [
  { title: "Model the system", text: "Draw services, hospital units or warehouses and how they connect, with their capacities and costs." },
  { title: "Branch the future", text: "Start from a situation (an outage, a flu surge, a power cut) and branch it once per decision you are considering." },
  { title: "Simulate", text: "Run each future once with a fixed seed, or hundreds of times to see the spread and what drives the risk." },
  { title: "Decide", text: "Say what matters and set hard limits. Branchpoint scores the futures, shows the trade-offs and what the answer depends on." },
];

const WHY = [
  { title: "Same start, different choices", text: "Branches share their starting conditions and even their random numbers, so differences come from the decisions, not from luck." },
  { title: "Every effect has a cause", text: "Click anything that went wrong and follow the chain back to the event that started it." },
  { title: "Uncertainty is visible", text: "Monte Carlo runs show the bad case and the worst 5% of runs, not just an average, and which event drives the risk." },
  { title: "Decisions, not just dashboards", text: "Weighted objectives, hard limits, Pareto sets and a check of whether the winner survives different weights." },
  { title: "What matters most", text: "Sensitivity analysis nudges every input and ranks them by how much they change the outcome." },
  { title: "Reproducible", text: "Every run stores a snapshot and a seed. Replay it later and get exactly the same result." },
];

export default function LandingPage() {
  const navigate = useNavigate();
  const toast = useToast();
  const fileInput = useRef<HTMLInputElement>(null);
  const [busy, setBusy] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);

  const act = async (key: string, fn: () => Promise<void>) => {
    setBusy(key);
    setError(null);
    try { await fn(); } catch (e) { setError(`Could not start: ${errorMessage(e)}. Is the backend running?`); } finally { setBusy(null); }
  };

  const openExample = (ex: ExampleInfo) => act(ex.domain, async () => {
    const out = await api.importExperiment(ex.data);
    toast(`Loaded ${ex.data.system.name}: ${Object.keys(out.scenario_ids).length} scenarios`);
    navigate(`/systems/${out.system_id}/futures?group=${out.scenario_ids[ex.focus] ?? ""}`);
  });

  const importFile = async (file: File) => {
    try {
      const data = JSON.parse(await file.text());
      act("file", async () => {
        const out = await api.importExperiment(data);
        navigate(`/systems/${out.system_id}/design`);
      });
    } catch (e) {
      setError(`That file is not valid JSON: ${errorMessage(e)}`);
    }
  };

  return (
    <div className="landing">
      <div className="landing-inner">
        <header className="topbar">
          <Link to="/" className="brand"><Logo /> Branchpoint</Link>
          <nav style={{ display: "flex", gap: 2 }} aria-label="Page sections">
            <a className="nav-link" href="#domains">Domains</a>
            <a className="nav-link" href="#how">How it works</a>
            <a className="nav-link" href="#why">Why Branchpoint</a>
          </nav>
          <span className="spacer" />
          <Link to="/systems" className="btn primary">Open Branchpoint</Link>
        </header>

        <section className="hero">
          <div className="hero-main">
            <span className="eyebrow">Alternative future simulation &amp; decision intelligence</span>
            <h1>Explore alternative futures. Make better decisions.</h1>
            <p>
              Model a system, branch the situation once for every decision you are weighing, and simulate where
              each one leads. Branchpoint compares the futures against what matters to you and shows why.
            </p>
            <div className="hero-domains" aria-hidden>
              {EXAMPLES.map((ex) => <span key={ex.domain} className="chip">{ex.title}</span>)}
            </div>
          </div>

          <div className="start-card">
            <div>
              <h2 style={{ fontSize: 22 }}>Start with a real example</h2>
              <p className="muted small" style={{ margin: "4px 0 6px" }}>
                Each loads a ready-made system with decisions to compare and opens the futures dashboard.
                Everything is simulated on your own computer.
              </p>
            </div>
            {EXAMPLES.map((ex, i) => (
              <button key={ex.domain} className={`start-option ${i === 0 ? "primary" : ""}`} onClick={() => openExample(ex)}
                disabled={busy !== null} data-testid={`example-${ex.domain}`}>
                <span className="label">{ex.data.system.name}
                  <small>{ex.title} · {ex.data.system.components.length} parts · {ex.data.scenarios.length} scenarios</small>
                </span>
                {busy === ex.domain ? <span className="spinner" /> : <span aria-hidden>›</span>}
              </button>
            ))}
            <div className="row">
              <Link to="/systems" className="btn small">Build your own</Link>
              <button className="small" onClick={() => fileInput.current?.click()} disabled={busy !== null}>Import JSON…</button>
            </div>
            <input ref={fileInput} type="file" accept=".json,application/json" hidden
              onChange={(e) => { const f = e.target.files?.[0]; if (f) importFile(f); e.target.value = ""; }} />
            <ErrorNotice error={error} />
          </div>
        </section>

        <section id="domains" className="stack" style={{ gap: 14 }}>
          <h2 className="section-title">One engine, three worlds</h2>
          <div className="domain-grid">
            {EXAMPLES.map((ex) => {
              const tree = scenarioTree(ex);
              return (
                <article key={ex.domain} className="domain-card">
                  <h3>{ex.title}</h3>
                  <p className="muted">{ex.tagline}</p>
                  <ul className="explore">
                    {ex.explore.map((x) => <li key={x}>{x}</li>)}
                  </ul>
                  <div className="tree-preview" aria-label={`Scenario tree of ${ex.data.system.name}`}>
                    <div className="tree-root">{tree.name}</div>
                    <ul>{tree.branches.map((b) => <li key={b}>{b.replace(`${tree.name} + `, "+ ")}</li>)}</ul>
                  </div>
                  <button className="primary" onClick={() => openExample(ex)} disabled={busy !== null}>
                    {busy === ex.domain ? <span className="spinner" /> : null} Compare these futures
                  </button>
                </article>
              );
            })}
          </div>
        </section>

        <section id="how" className="stack" style={{ gap: 14 }}>
          <h2 className="section-title">How it works</h2>
          <ol className="feature-grid four">
            {STEPS.map((s, i) => (
              <li key={s.title} className="feature">
                <div className="step-num">{i + 1}</div>
                <h3 style={{ marginTop: 10 }}>{s.title}</h3>
                <p>{s.text}</p>
              </li>
            ))}
          </ol>
        </section>

        <section id="why" className="stack" style={{ gap: 14 }}>
          <h2 className="section-title">Why Branchpoint</h2>
          <div className="feature-grid">
            {WHY.map((w) => (
              <div key={w.title} className="feature">
                <h3>{w.title}</h3>
                <p>{w.text}</p>
              </div>
            ))}
          </div>
        </section>

        <section className="honesty">
          <b>What Branchpoint is not.</b> Its models are simplified and the examples use made-up numbers. Results
          are estimates from the inputs you enter, not predictions. The hospital model is for operational planning
          and makes no clinical claims; the cold-chain model tracks exposure against a tolerance you set and does
          not judge product safety. No real-world data sources are connected.
        </section>
      </div>
    </div>
  );
}
