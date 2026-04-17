"""Backward-compatible exports for execution lifecycle services."""

from __future__ import annotations

from . import execution_service as _impl
from .execution_service import *  # noqa: F401,F403

ExecutionStateStore = _impl.ExecutionStateStore


class OrderLifecycleService(_impl.OrderLifecycleService):
    """Compatibility shim keeping module-level monkeypatch behavior stable."""

    def __init__(self, *args, **kwargs) -> None:
        _impl.ExecutionStateStore = ExecutionStateStore
        super().__init__(*args, **kwargs)
