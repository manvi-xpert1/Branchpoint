"""Runtime of the three example experiments (one per domain).

    python benchmarks/domains.py          # writes benchmarks/results/domains.csv

For each example: the time of one run of every scenario (fastest of 5),
and the time of a 100-run Monte Carlo batch of its focus scenario.
"""

from __future__ import annotations

import csv
import json
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))

from app.config import load_experiment  # noqa: E402
from app.simulation.branching import run_scenario  # noqa: E402
from app.simulation.montecarlo import run_monte_carlo  # noqa: E402

EXAMPLES = [("ecommerce.json", "db-down"), ("hospital.json", "surge"), ("coldchain.json", "heatwave")]


def main() -> int:
    rows = []
    for name, focus in EXAMPLES:
        exp = load_experiment(json.loads((ROOT / "examples" / name).read_text()))
        for s in exp.scenarios:
            best = min(_time(lambda: run_scenario(exp.system, s, exp.until)) for _ in range(5))
            result = run_scenario(exp.system, s, exp.until)
            rows.append({"example": name, "scenario": s.id, "kind": "single run", "runs": 1,
                         "seconds": round(best, 5), "log_entries": len(result.log)})
        scenario = next(s for s in exp.scenarios if s.id == focus)
        seconds = _time(lambda: run_monte_carlo(exp.system, scenario, exp.until, 100))
        rows.append({"example": name, "scenario": focus, "kind": "monte carlo", "runs": 100,
                     "seconds": round(seconds, 4), "log_entries": ""})
    out = ROOT / "benchmarks" / "results" / "domains.csv"
    out.parent.mkdir(parents=True, exist_ok=True)
    with out.open("w", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)
    for name, _ in EXAMPLES:
        single = [r for r in rows if r["example"] == name and r["kind"] == "single run"]
        mc = next(r for r in rows if r["example"] == name and r["kind"] == "monte carlo")
        print(f"{name:<16} one run: {1000 * max(r['seconds'] for r in single):7.1f} ms (slowest scenario)   "
              f"100 Monte Carlo runs: {mc['seconds']:.2f} s")
    print(f"wrote {out.relative_to(ROOT)}")
    return 0


def _time(fn) -> float:
    start = time.perf_counter()
    fn()
    return time.perf_counter() - start


if __name__ == "__main__":
    raise SystemExit(main())
