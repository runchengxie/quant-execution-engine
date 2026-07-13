from __future__ import annotations

import pytest

import quant_execution_engine._vnpy_bindings as bindings_module
from quant_execution_engine.vnpy_transport import (
    VnPyExecutionTransport,
    VnPyImportError,
)

pytestmark = pytest.mark.unit


class _NoopEventEngine:
    def register(self, event_type: str, handler: object) -> None:
        raise AssertionError("event registration must not happen without vn.py")

    def unregister(self, event_type: str, handler: object) -> None:
        raise AssertionError("event unregistration must not happen without vn.py")


class _NoopMainEngine:
    event_engine = _NoopEventEngine()


def test_leaf_import_fails_helpfully_when_optional_vnpy_is_missing(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    original = bindings_module.import_module

    def missing(name: str):
        if name.startswith("vnpy"):
            raise ImportError("simulated missing optional dependency")
        return original(name)

    monkeypatch.setattr(bindings_module, "import_module", missing)

    with pytest.raises(VnPyImportError, match="uv sync --extra vnpy"):
        VnPyExecutionTransport(_NoopMainEngine(), gateway_name="SIM")
