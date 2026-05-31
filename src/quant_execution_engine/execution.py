"""Backward-compatible exports for execution lifecycle services."""

from __future__ import annotations

from typing import Any

from . import execution_service as _impl
from .execution_service import *  # type: ignore[misc] # noqa: F401,F403
from .execution_state import *  # noqa: F401,F403

ExecutionStateStore: Any = _impl.ExecutionStateStore  # type: ignore[no-redef]


class OrderLifecycleService(_impl.OrderLifecycleService):  # type: ignore[no-redef]
    """Compatibility shim keeping module-level monkeypatch behavior stable."""

    def __init__(self, *args: Any, **kwargs: Any) -> None:
        _impl.ExecutionStateStore = ExecutionStateStore  # type: ignore[misc]
        super().__init__(*args, **kwargs)
