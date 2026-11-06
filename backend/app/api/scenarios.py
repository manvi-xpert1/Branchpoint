from fastapi import APIRouter, Depends, Response, status
from pydantic import BaseModel
from sqlalchemy.orm import Session

from ..schemas import ScenarioIn, ScenarioOut
from ..services import scenarios
from .deps import get_db

router = APIRouter(tags=["scenarios"])


class BranchIn(BaseModel):
    name: str | None = None


@router.get("/systems/{system_id}/scenarios", response_model=list[ScenarioOut])
def list_scenarios(system_id: str, db: Session = Depends(get_db)):
    return [scenarios.to_schema(s) for s in scenarios.list_for_system(db, system_id)]


@router.post("/systems/{system_id}/scenarios", response_model=ScenarioOut,
             status_code=status.HTTP_201_CREATED)
def create_scenario(system_id: str, data: ScenarioIn, db: Session = Depends(get_db)):
    return scenarios.to_schema(scenarios.create(db, system_id, data))


@router.get("/scenarios/{scenario_id}", response_model=ScenarioOut)
def get_scenario(scenario_id: str, db: Session = Depends(get_db)):
    return scenarios.to_schema(scenarios.get(db, scenario_id))


@router.put("/scenarios/{scenario_id}", response_model=ScenarioOut)
def update_scenario(scenario_id: str, data: ScenarioIn, db: Session = Depends(get_db)):
    return scenarios.to_schema(scenarios.update(db, scenario_id, data))


@router.post("/scenarios/{scenario_id}/branch", response_model=ScenarioOut,
             status_code=status.HTTP_201_CREATED)
def branch_scenario(scenario_id: str, data: BranchIn | None = None, db: Session = Depends(get_db)):
    return scenarios.to_schema(scenarios.branch(db, scenario_id, data.name if data else None))


@router.delete("/scenarios/{scenario_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_scenario(scenario_id: str, db: Session = Depends(get_db)):
    scenarios.delete(db, scenario_id)
    return Response(status_code=status.HTTP_204_NO_CONTENT)
