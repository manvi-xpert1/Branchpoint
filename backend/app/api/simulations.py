from fastapi import APIRouter, Depends, status
from sqlalchemy.orm import Session

from ..schemas import (CompareOut, CompareRequest, LogEntryOut, MonteCarloOut, MonteCarloRequest,
                       ReplayOut, RunOut, RunRequest, RunSummary)
from ..services import montecarlo, runs, scenarios
from .deps import get_db

router = APIRouter(tags=["simulations"])


@router.post("/scenarios/{scenario_id}/runs", response_model=RunOut, status_code=status.HTTP_201_CREATED)
def run_scenario(scenario_id: str, data: RunRequest | None = None, db: Session = Depends(get_db)):
    until = (data or RunRequest()).until
    return runs.to_schema(runs.execute(db, scenarios.get(db, scenario_id), until))


@router.get("/scenarios/{scenario_id}/runs", response_model=list[RunSummary])
def list_runs(scenario_id: str, db: Session = Depends(get_db)):
    return [runs.to_summary(r) for r in runs.list_for_scenario(db, scenario_id)]


@router.get("/runs/{run_id}", response_model=RunOut)
def get_run(run_id: str, db: Session = Depends(get_db)):
    return runs.to_schema(runs.get(db, run_id))


@router.get("/runs/{run_id}/explain/{seq}", response_model=list[LogEntryOut])
def explain(run_id: str, seq: int, db: Session = Depends(get_db)):
    """Trace a log entry back through its causes to the original event."""
    return runs.explain(runs.get(db, run_id), seq)


@router.post("/runs/{run_id}/replay", response_model=ReplayOut)
def replay(run_id: str, db: Session = Depends(get_db)):
    """Re-run from the stored snapshot and verify the result is identical."""
    return runs.replay(runs.get(db, run_id))


@router.post("/compare", response_model=CompareOut)
def compare(data: CompareRequest, db: Session = Depends(get_db)):
    return runs.compare(db, data.run_ids, data.scenario_ids, data.until)


@router.post("/scenarios/{scenario_id}/montecarlo", response_model=MonteCarloOut,
             status_code=status.HTTP_201_CREATED)
def run_monte_carlo(scenario_id: str, data: MonteCarloRequest | None = None,
                    db: Session = Depends(get_db)):
    """Run the scenario N times (seed base_seed + i) and store the summary."""
    data = data or MonteCarloRequest()
    row = montecarlo.execute(db, scenarios.get(db, scenario_id), data.runs, data.until, data.base_seed)
    return montecarlo.to_schema(row)


@router.get("/scenarios/{scenario_id}/montecarlo", response_model=list[MonteCarloOut])
def list_monte_carlo(scenario_id: str, db: Session = Depends(get_db)):
    return [montecarlo.to_schema(r) for r in montecarlo.list_for_scenario(db, scenario_id)]


@router.get("/montecarlo/{mc_id}", response_model=MonteCarloOut)
def get_monte_carlo(mc_id: str, db: Session = Depends(get_db)):
    return montecarlo.to_schema(montecarlo.get(db, mc_id))
