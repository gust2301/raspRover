"""Automotive inspection domain."""

from .repository import AutomotiveRepository
from .service import InspectionRunner

__all__ = ["AutomotiveRepository", "InspectionRunner"]
