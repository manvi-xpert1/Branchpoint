import { createContext, useContext } from "react";
import type { ScenarioOut, SystemDef, SystemOut } from "../api/types";

export interface Workspace {
  system: SystemOut;
  /** Unsaved edits from the designer; survives switching tabs. */
  draft: SystemDef;
  setDraft: (d: SystemDef | ((prev: SystemDef) => SystemDef)) => void;
  dirty: boolean;
  saveDraft: () => Promise<void>;
  discardDraft: () => void;
  scenarios: ScenarioOut[];
  reloadScenarios: () => Promise<ScenarioOut[]>;
  reloadSystem: () => Promise<void>;
}

export const WorkspaceContext = createContext<Workspace | null>(null);

export function useWorkspace(): Workspace {
  const ws = useContext(WorkspaceContext);
  if (!ws) throw new Error("useWorkspace outside SystemWorkspace");
  return ws;
}

export function toDef(s: SystemOut): SystemDef {
  return {
    name: s.name,
    domain: s.domain,
    description: s.description,
    components: s.components,
    dependencies: s.dependencies,
  };
}
