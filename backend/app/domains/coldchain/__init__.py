"""Cold-chain supply and logistics (tracks exposure; does not judge product safety)."""

from .model import ColdChainDomain
from .spec import COLDCHAIN_SPEC

__all__ = ["ColdChainDomain", "COLDCHAIN_SPEC"]
