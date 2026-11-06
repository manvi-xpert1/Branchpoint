from fastapi import APIRouter, Depends, Query, Response, status
from sqlalchemy.orm import Session

from ..schemas import ExperimentIn, ImportOut, SystemAnalysis, SystemIn, SystemOut, SystemSummary
from ..services import experiments, systems
from .deps import get_db

router = APIRouter(tags=["systems"])


@router.get("/systems", response_model=list[SystemSummary])
def list_systems(db: Session = Depends(get_db)):
    return systems.list_summaries(db)


@router.post("/systems", response_model=SystemOut, status_code=status.HTTP_201_CREATED)
def create_system(data: SystemIn, db: Session = Depends(get_db)):
    return systems.to_schema(systems.create(db, data))


@router.get("/systems/{system_id}", response_model=SystemOut)
def get_system(system_id: str, db: Session = Depends(get_db)):
    return systems.to_schema(systems.get(db, system_id))


@router.put("/systems/{system_id}", response_model=SystemOut)
def update_system(system_id: str, data: SystemIn, db: Session = Depends(get_db)):
    """Replace the whole definition (how the visual editor will save)."""
    return systems.to_schema(systems.update(db, system_id, data))


@router.delete("/systems/{system_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_system(system_id: str, db: Session = Depends(get_db)):
    systems.delete(db, system_id)
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.get("/systems/{system_id}/analysis", response_model=SystemAnalysis)
def analyze_saved_system(system_id: str, db: Session = Depends(get_db)):
    return systems.analyze(systems.to_input(systems.get(db, system_id)))


@router.post("/analysis", response_model=SystemAnalysis)
def analyze_draft(data: SystemIn):
    """Validate an unsaved definition, e.g. live while the user edits."""
    return systems.analyze(data)


@router.post("/experiments/import", response_model=ImportOut, status_code=status.HTTP_201_CREATED)
def import_experiment(data: ExperimentIn, db: Session = Depends(get_db)):
    return experiments.import_experiment(db, data)


@router.get("/systems/{system_id}/export")
def export_experiment(system_id: str, until: float = Query(30.0, gt=0), db: Session = Depends(get_db)):
    return experiments.export_experiment(db, system_id, until)
