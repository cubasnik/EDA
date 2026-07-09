"""Shared FastAPI dependencies."""
from eda.core.engine import ActivationEngine
from eda.core.store import Store, get_store


def store_dep() -> Store:
    return get_store()


def engine_dep() -> ActivationEngine:
    return ActivationEngine(get_store())
