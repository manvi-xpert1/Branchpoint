"""Maps a system's ``domain`` string to its Domain.

To add a domain, write a ``Domain`` subclass with a ``spec`` and call
``register_domain`` here.
"""

from __future__ import annotations

from .base import Domain
from .coldchain import ColdChainDomain
from .hospital import HospitalDomain
from .infrastructure import InfrastructureDomain

_DOMAINS: dict[str, Domain] = {}


def register_domain(domain: Domain) -> None:
    _DOMAINS[domain.name] = domain


def get_domain(name: str) -> Domain:
    try:
        return _DOMAINS[name]
    except KeyError:
        raise ValueError(f"Unknown domain {name!r}; available: {sorted(_DOMAINS)}") from None


def all_domains() -> list[Domain]:
    return list(_DOMAINS.values())


def known_relationship_types() -> set[str]:
    """Relationship types used by any domain (checked when a Dependency is built)."""
    return {t for d in _DOMAINS.values() for t in d.spec.relationship_type_names}


def known_event_types() -> set[str]:
    """Event types used by any domain (checked when an Event is built)."""
    return {t for d in _DOMAINS.values() for t in d.spec.event_type_names}


register_domain(InfrastructureDomain())
register_domain(HospitalDomain())
register_domain(ColdChainDomain())
