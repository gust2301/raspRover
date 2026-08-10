"""Module API Web — serveur FastAPI + dashboard de contrôle RaspRover."""

from typing import Any

__all__ = ["app"]


def __getattr__(name: str) -> Any:
    """Load FastAPI lazily so database helpers remain independently importable."""
    if name != "app":
        raise AttributeError(name)
    from .server import app

    return app
