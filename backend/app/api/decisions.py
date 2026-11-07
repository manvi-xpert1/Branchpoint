"""Decision layer: objectives and constraints, evaluating futures, sensitivity analysis."""

from fastapi import APIRouter, Body, Depends
from sqlalchemy.orm import Session

from ..schemas import DecisionModelIn, DecisionModelOut, EvaluateRequest, EvaluationOut, SensitivityOut, SensitivityRequest
from ..services import decisions
from .deps import get_db

router = APIRouter(tags=["decisions"])


@router.get("/systems/{system_id}/objectives", response_model=DecisionModelOut)
def get_objectives(system_id: str, db: Session = Depends(get_db)):
    """The saved objectives and constraints, or the domain's defaults."""
    return decisions.get_objectives(db, system_id)


@router.put("/systems/{system_id}/objectives", response_model=DecisionModelOut)
def set_objectives(system_id: str, data: DecisionModelIn | None = Body(default=None),
                   db: Session = Depends(get_db)):
    """Save objectives and constraints. An empty body resets to the defaults."""
    return decisions.set_objectives(db, system_id, data)


@router.post("/systems/{system_id}/evaluate", response_model=EvaluationOut)
def evaluate(system_id: str, data: EvaluateRequest | None = None, db: Session = Depends(get_db)):
    """Run each scenario (once, or many times) and score, rank and explain the futures."""
    return decisions.evaluate_system(db, system_id, data or EvaluateRequest())


@router.post("/scenarios/{scenario_id}/sensitivity", response_model=SensitivityOut)
def sensitivity(scenario_id: str, data: SensitivityRequest | None = None, db: Session = Depends(get_db)):
    """Which inputs move the chosen metric the most? (one-at-a-time, +/- delta)"""
    return decisions.sensitivity_for(db, scenario_id, data or SensitivityRequest())
