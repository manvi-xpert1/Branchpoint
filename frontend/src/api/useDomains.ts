import { useEffect, useState } from "react";
import { api } from "./client";
import type { DomainSpec } from "./types";

// The catalogs never change while the app runs, so fetch them once and share.
let cache: Promise<DomainSpec[]> | null = null;

export function loadDomains(): Promise<DomainSpec[]> {
  if (!cache) cache = api.listDomains().catch((e) => { cache = null; throw e; });
  return cache;
}

export function useDomains(): { domains: DomainSpec[] | null; error: string | null } {
  const [domains, setDomains] = useState<DomainSpec[] | null>(null);
  const [error, setError] = useState<string | null>(null);
  useEffect(() => {
    let alive = true;
    loadDomains().then((d) => alive && setDomains(d)).catch((e) => alive && setError(String(e?.message ?? e)));
    return () => { alive = false; };
  }, []);
  return { domains, error };
}

export const DOMAIN_LABELS: Record<string, string> = {
  software_infrastructure: "Software infrastructure",
  hospital: "Hospital operations",
  cold_chain: "Cold-chain logistics",
};
