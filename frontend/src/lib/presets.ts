/**
 * Intervention presets: common "what if" changes expressed as the plain
 * interventions the backend understands.
 *
 * Replicas and fallbacks only help if the dependency is in a *group*
 * (the source needs one member of the group). If an existing dependency
 * has no group, the preset replaces it with a grouped copy first.
 */
import type { DependencyDef, InterventionDef, SystemDef } from "../api/types";
import { uniqueId } from "./catalog";

function pool(dep: DependencyDef, takenIds: Set<string>): { group: string; steps: InterventionDef[] } {
  if (dep.group) return { group: dep.group, steps: [] };
  const depId = dep.id ?? `${dep.source_id}->${dep.target_id}`;
  const group = `${dep.target_id}_pool`;
  const newId = uniqueId(`${depId}_pooled`, takenIds);
  takenIds.add(newId);
  return {
    group,
    steps: [
      { id: uniqueId(`ungroup_${dep.source_id}_${dep.target_id}`, takenIds), type: "remove_dependency",
        params: { id: depId }, cost: 0, description: "" },
      { id: uniqueId(`regroup_${dep.source_id}_${dep.target_id}`, takenIds), type: "add_dependency",
        params: { ...dep, id: newId, group }, cost: 0,
        description: `Make ${dep.source_id} -> ${dep.target_id} part of group ${group}` },
    ],
  };
}

function taken(system: SystemDef, existing: InterventionDef[]): Set<string> {
  return new Set([
    ...existing.map((i) => i.id),
    ...system.dependencies.map((d) => d.id ?? `${d.source_id}->${d.target_id}`),
    ...system.components.map((c) => c.id),
  ]);
}

/** Add a replica of `componentId` that every dependent can fail over to. */
export function replicaPreset(
  system: SystemDef, componentId: string, existing: InterventionDef[], cost = 0,
): InterventionDef[] {
  const original = system.components.find((c) => c.id === componentId);
  if (!original) return [];
  const ids = taken(system, existing);
  const replicaId = uniqueId(`${componentId}_replica`, ids);
  ids.add(replicaId);
  const out: InterventionDef[] = [{
    id: uniqueId(`add_${replicaId}`, ids), type: "add_component", cost,
    description: `Add replica of ${original.name ?? componentId}`,
    params: { id: replicaId, name: `${original.name ?? componentId} (replica)`, type: original.type,
      attributes: { ...original.attributes } },
  }];
  for (const dep of system.dependencies.filter((d) => d.target_id === componentId)) {
    const { group, steps } = pool(dep, ids);
    steps.forEach((s) => ids.add(s.id));
    const depId = uniqueId(`${dep.source_id}->${replicaId}`, ids);
    ids.add(depId);
    out.push(...steps, {
      id: uniqueId(`use_${replicaId}_from_${dep.source_id}`, ids), type: "add_dependency", cost: 0,
      description: `${dep.source_id} can fail over to ${replicaId}`,
      params: { id: depId, source_id: dep.source_id, target_id: replicaId,
        dependency_type: "requires", group, propagation_delay: dep.propagation_delay },
    });
  }
  return out;
}

/** Let `sourceId` fall back to `fallbackId` (in degraded mode) when `targetId` fails. */
export function fallbackPreset(
  system: SystemDef, sourceId: string, targetId: string, fallbackId: string,
  existing: InterventionDef[], cost = 0,
): InterventionDef[] {
  const dep = system.dependencies.find((d) => d.source_id === sourceId && d.target_id === targetId);
  if (!dep || fallbackId === sourceId) return [];
  const ids = taken(system, existing);
  const { group, steps } = pool(dep, ids);
  steps.forEach((s) => ids.add(s.id));
  const depId = uniqueId(`${sourceId}->${fallbackId}_fallback`, ids);
  ids.add(depId);
  return [...steps, {
    id: uniqueId(`fallback_${sourceId}_to_${fallbackId}`, ids), type: "add_dependency", cost,
    description: `${sourceId} falls back to ${fallbackId} when ${targetId} is down`,
    params: { id: depId, source_id: sourceId, target_id: fallbackId, dependency_type: "fallback",
      group, propagation_delay: dep.propagation_delay },
  }];
}

/**
 * Component ids that exist once a list of interventions is applied, so
 * events can target components that a scenario adds.
 */
export function componentIdsAfter(system: SystemDef, interventions: InterventionDef[]): string[] {
  const ids = system.components.map((c) => c.id);
  for (const iv of interventions) {
    const id = iv.params.id as string | undefined;
    if (iv.type === "add_component" && id && !ids.includes(id)) ids.push(id);
    if (iv.type === "remove_component" && id) {
      const i = ids.indexOf(id);
      if (i >= 0) ids.splice(i, 1);
    }
  }
  return ids;
}
