import type { LogEntry, Status } from "../api/types";

export type Timeline = [number, Status][];

const RANK: Record<Status, number> = { healthy: 0, degraded: 1, failed: 2 };

/** Status at time t. Changes at exactly t count as already happened. */
export function statusAt(timeline: Timeline | undefined, t: number): Status {
  if (!timeline || timeline.length === 0) return "healthy";
  let current = timeline[0][1];
  for (const [time, status] of timeline) {
    if (time > t) break;
    current = status;
  }
  return current;
}

export function worst(statuses: Status[]): Status {
  return statuses.reduce<Status>((w, s) => (RANK[s] > RANK[w] ? s : w), "healthy");
}

/** Turn a timeline into [start, end, status] segments clipped to [0, until]. */
export function segments(timeline: Timeline, until: number): [number, number, Status][] {
  const out: [number, number, Status][] = [];
  timeline.forEach(([start, status], i) => {
    const end = i + 1 < timeline.length ? timeline[i + 1][0] : until;
    const s = Math.min(start, until);
    const e = Math.min(end, until);
    if (e > s) out.push([s, e, status]);
  });
  return out;
}

/** Sorted distinct times at which something happened (for step controls). */
export function eventTimes(log: LogEntry[]): number[] {
  return [...new Set(log.map((e) => e.time))].sort((a, b) => a - b);
}

/** Every log entry on the causal path to `seq` (inclusive). */
export function causalChain(log: LogEntry[], seq: number): LogEntry[] {
  const bySeq = new Map(log.map((e) => [e.seq, e]));
  const chain: LogEntry[] = [];
  let cur = bySeq.get(seq);
  while (cur) {
    chain.push(cur);
    cur = cur.cause_seq === null ? undefined : bySeq.get(cur.cause_seq);
  }
  return chain.reverse();
}

export const STATUS_COLORS: Record<Status, string> = {
  healthy: "var(--ok)",
  degraded: "var(--warn)",
  failed: "var(--bad)",
};
