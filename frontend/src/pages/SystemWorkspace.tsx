import { useCallback, useEffect, useMemo, useState } from "react";
import { Navigate, NavLink, Route, Routes, useParams } from "react-router-dom";
import { api } from "../api/client";
import type { ScenarioOut, SystemDef, SystemOut } from "../api/types";
import { ErrorNotice, errorMessage } from "../components/common";
import TopBar from "../components/TopBar";
import ComparePage from "./ComparePage";
import DesignPage from "./DesignPage";
import RunPage from "./RunPage";
import ScenariosPage from "./ScenariosPage";
import { toDef, WorkspaceContext, type Workspace } from "./workspace";

export default function SystemWorkspace() {
  const { systemId = "" } = useParams();
  const [system, setSystem] = useState<SystemOut | null>(null);
  const [draft, setDraft] = useState<SystemDef | null>(null);
  const [scenarios, setScenarios] = useState<ScenarioOut[]>([]);
  const [error, setError] = useState<string | null>(null);

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
    setError(null);
    Promise.all([reloadSystem(), reloadScenarios()]).catch((e) => setError(errorMessage(e)));
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

  if (error) return (
    <div className="app"><TopBar /><div className="page"><ErrorNotice error={error} /></div></div>
  );
  if (!system || !draft) return (
    <div className="app"><TopBar /><div className="page empty"><span className="spinner" /></div></div>
  );

  const ws: Workspace = {
    system,
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

  return (
    <WorkspaceContext.Provider value={ws}>
      <div className="app">
        <TopBar>
          <span className="crumb"><b>{system.name}</b></span>
          <nav className="tabs">
            <NavLink to="design">Design{dirty ? " •" : ""}</NavLink>
            <NavLink to="scenarios">Scenarios</NavLink>
            <NavLink to="compare">Compare</NavLink>
          </nav>
        </TopBar>
        <div className="main">
          <Routes>
            <Route index element={<Navigate to="design" replace />} />
            <Route path="design" element={<DesignPage />} />
            <Route path="scenarios" element={<ScenariosPage />} />
            <Route path="scenarios/:scenarioId" element={<ScenariosPage />} />
            <Route path="runs/:runId" element={<RunPage />} />
            <Route path="compare" element={<ComparePage />} />
          </Routes>
        </div>
      </div>
    </WorkspaceContext.Provider>
  );
}
