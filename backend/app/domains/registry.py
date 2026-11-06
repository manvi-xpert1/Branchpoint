"""Maps a system's ``domain`` string to its rules."""

from .base import DomainRules
from .infrastructure import InfrastructureRules

_DOMAINS: dict[str, type[DomainRules]] = {
    InfrastructureRules.name: InfrastructureRules,
}


def get_domain(name: str) -> DomainRules:
    try:
        return _DOMAINS[name]()
    except KeyError:
        raise ValueError(f"Unknown domain {name!r}; available: {sorted(_DOMAINS)}") from None


def register_domain(rules: type[DomainRules]) -> None:
    _DOMAINS[rules.name] = rules
