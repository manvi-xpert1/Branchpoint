import { useCallback, useEffect, useMemo, useState } from "react";
import { Navigate, NavLink, Route, Routes, useParams } from "react-router-dom";
import { api } from "../api/client";
import { useDomains } from "../api/useDomains";
import type { ScenarioOut, SystemDef, SystemOut } from "../api/types";
import { ErrorNotice, errorMessage } from "../components/common";
import TopBar from "../components/TopBar";
import ComparePage from "./ComparePage";
import DesignPage from "./DesignPage";
import FuturesPage from "./FuturesPage";
import RunPage from "./RunPage";
import ScenariosPage from "./ScenariosPage";
import { toDef, WorkspaceContext, type Workspace } from "./workspace";

export default function SystemWorkspace() {
  const { systemId = "" } = useParams();
  const [system, setSystem] = useState<SystemOut | null>(null);
  const [draft, setDraft] = useState<SystemDef | null>(null);
  const [scenarios, setScenarios] = useState<ScenarioOut[]>([]);
  const [error, setError] = useState<string | null>(null);
  const [ready, setReady] = useState(false);
  const { domains, error: domainError } = useDomains();

  const reloadScenarios = useCallback(async () => {
    const list = await api.listScenarios(systemId);
    setScenarios(list);
    return list;
  }, [systemId]);

  const reloadSystem = useCallback(async () => {
    const s = await api.getSystem(systemId);
    setSystem(s);
    setDraft(toDef(s));
  }, [systemId]);

  useEffect(() => {
    setSystem(null);
    setReady(false);
    setError(null);
    Promise.all([reloadSystem(), reloadScenarios()]).then(() => setReady(true)).catch((e) => setError(errorMessage(e)));
  }, [reloadSystem, reloadScenarios]);

  const dirty = useMemo(
    () => !!system && !!draft && JSON.stringify(toDef(system)) !== JSON.stringify(draft),
    [system, draft],
  );

  useEffect(() => {
    if (!dirty) return;
    const warn = (e: BeforeUnloadEvent) => e.preventDefault();
    window.addEventListener("beforeunload", warn);
    return () => window.removeEventListener("beforeunload", warn);
  }, [dirty]);

  const spec = domains?.find((d) => d.name === system?.domain);
  if (error || domainError || (domains && system && !spec)) return (
    <div className="app"><TopBar /><div className="page"><ErrorNotice error={error ?? domainError ?? `Unknown domain ${system?.domain}`} /></div></div>
  );
  if (!system || !draft || !spec || !ready) return (
    <div className="app"><TopBar /><div className="page empty"><span className="spinner" /></div></div>
  );

  const ws: Workspace = {
    system,
    spec,
    draft,
    setDraft: (d) => setDraft((prev) => (typeof d === "function" ? d(prev!) : d)),
    dirty,
    saveDraft: async () => {
      const saved = await api.updateSystem(system.id, draft);
      setSystem(saved);
      setDraft(toDef(saved));
    },
    discardDraft: () => setDraft(toDef(system)),
    scenarios,
    reloadScenarios,
    reloadSystem,
  };

  // Absolute links: React Router 7 resolves relative links inside a "/*" route
  // from the current page, so "scenarios" on /design would become /design/scenarios.
  const base = `/systems/${system.id}`;

  return (
    <WorkspaceContext.Provider value={ws}>
      <div className="app">
        <TopBar>
          <span className="crumb"><b>{system.name}</b> <span className="domain-chip">{spec.label}</span></span>
          <nav className="tabs">
            <NavLink to={`${base}/design`}>Design{dirty ? " •" : ""}</NavLink>
            <NavLink to={`${base}/scenarios`}>Scenarios</NavLink>
            <NavLink to={`${base}/futures`}>Futures</NavLink>
            <NavLink to={`${base}/compare`}>Compare</NavLink>
          </nav>
        </TopBar>
        <div className="main">
          <Routes>
            <Route index element={<Navigate to={`${base}/design`} replace />} />
            <Route path="design" element={<DesignPage />} />
            <Route path="scenarios" element={<ScenariosPage />} />
            <Route path="scenarios/:scenarioId" element={<ScenariosPage />} />
            <Route path="runs/:runId" element={<RunPage />} />
            <Route path="compare" element={<ComparePage />} />
            <Route path="futures" element={<FuturesPage />} />
          </Routes>
        </div>
      </div>
    </WorkspaceContext.Provider>
  );
}
