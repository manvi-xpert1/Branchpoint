"""Hospital operations and patient flow (an operational model, not clinical advice)."""

from .model import HospitalDomain
from .spec import HOSPITAL_SPEC

__all__ = ["HospitalDomain", "HOSPITAL_SPEC"]
