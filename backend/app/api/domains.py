"""Domain catalogs: what each domain offers (entity, event and decision types, metrics)."""

from fastapi import APIRouter, HTTPException

from ..domains.registry import all_domains, get_domain
from ..schemas import DomainOut

router = APIRouter(tags=["domains"])


@router.get("/domains", response_model=list[DomainOut])
def list_domains():
    return [d.spec.to_dict() for d in all_domains()]


@router.get("/domains/{name}", response_model=DomainOut)
def get_domain_spec(name: str):
    try:
        return get_domain(name).spec.to_dict()
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
