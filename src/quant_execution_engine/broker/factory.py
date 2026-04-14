"""Broker adapter selection helpers."""

from __future__ import annotations

from typing import Any

from ..config import load_cfg
from .alpaca import AlpacaPaperBrokerAdapter
from .base import BrokerAdapter, BrokerCapabilityMatrix, BrokerValidationError
from .longport import LongPortBrokerAdapter, LongPortClient


def _broker_cfg() -> dict[str, Any]:
    cfg = load_cfg() or {}
    broker_cfg = cfg.get("broker") or {}
    return broker_cfg if isinstance(broker_cfg, dict) else {}


def resolve_broker_name(explicit: str | None = None) -> str:
    """Return the selected broker backend name."""

    backend = explicit or _broker_cfg().get("backend") or "longport"
    return str(backend).strip().lower()


def resolve_default_account_label(explicit: str | None = None) -> str:
    """Return the selected account label."""

    if explicit:
        return str(explicit).strip() or "main"
    broker_cfg = _broker_cfg()
    return str(broker_cfg.get("default_account") or "main").strip() or "main"


def get_account_config(label: str | None = None) -> dict[str, Any]:
    """Return account configuration for the selected label."""

    broker_cfg = _broker_cfg()
    accounts = broker_cfg.get("accounts") or {}
    if not isinstance(accounts, dict):
        return {}
    resolved_label = resolve_default_account_label(label)
    raw = accounts.get(resolved_label) or {}
    return raw if isinstance(raw, dict) else {}


def get_broker_capabilities(broker_name: str | None = None) -> BrokerCapabilityMatrix:
    """Return declared capabilities without instantiating network clients."""

    backend = resolve_broker_name(broker_name)
    if backend == "longport":
        return LongPortBrokerAdapter.capabilities
    if backend in {"alpaca", "alpaca-paper"}:
        return AlpacaPaperBrokerAdapter.capabilities
    raise BrokerValidationError(f"unsupported broker backend: {backend}")


def get_broker_adapter(
    *,
    broker_name: str | None = None,
    client: Any | None = None,
) -> BrokerAdapter:
    """Instantiate the configured broker adapter."""

    if isinstance(client, BrokerAdapter):
        return client

    backend = resolve_broker_name(broker_name)
    if backend == "longport":
        longport_client = client if isinstance(client, LongPortClient) else None
        return LongPortBrokerAdapter(client=longport_client)
    if backend in {"alpaca", "alpaca-paper"}:
        if client is not None:
            raise BrokerValidationError(
                "custom broker client injection is only supported for longport"
            )
        return AlpacaPaperBrokerAdapter()

    raise BrokerValidationError(f"unsupported broker backend: {backend}")

