"""Broker adapter selection helpers."""

from __future__ import annotations

from importlib import import_module
from typing import Any

from ..config import load_cfg
from .base import BrokerAdapter, BrokerCapabilityMatrix, BrokerValidationError


PAPER_BROKERS = frozenset({"alpaca", "alpaca-paper", "ibkr-paper", "longport-paper"})
LONGPORT_BROKERS = frozenset({"longport", "longport-paper"})
ALPACA_BROKERS = frozenset({"alpaca", "alpaca-paper"})
IBKR_BROKERS = frozenset({"ibkr-paper"})


def _broker_cfg() -> dict[str, Any]:
    cfg = load_cfg() or {}
    broker_cfg = cfg.get("broker") or {}
    return broker_cfg if isinstance(broker_cfg, dict) else {}


def peek_broker_name(explicit: str | None = None) -> str | None:
    """Return the configured backend name when available."""

    backend = explicit if explicit is not None else _broker_cfg().get("backend")
    normalized = str(backend or "").strip().lower()
    return normalized or None


def resolve_broker_name(explicit: str | None = None) -> str:
    """Return the selected broker backend name or raise when not configured."""

    backend = peek_broker_name(explicit)
    if backend:
        return backend
    raise BrokerValidationError(
        "broker backend is not configured. Set broker.backend in config.yaml or pass --broker explicitly."
    )


def _load_alpaca_adapter_cls():
    module = import_module(".alpaca", __package__)
    return module.AlpacaPaperBrokerAdapter


def _load_ibkr_adapter_cls():
    module = import_module(".ibkr", __package__)
    return module.IbkrPaperBrokerAdapter


def _load_longport_runtime() -> tuple[type[Any], type[Any], type[Any]]:
    module = import_module(".longport", __package__)
    return (
        module.LongPortBrokerAdapter,
        module.LongPortPaperBrokerAdapter,
        module.LongPortClient,
    )


def is_paper_broker(broker_name: str | None = None) -> bool:
    """Return whether the selected backend is a paper/simulated broker."""

    return resolve_broker_name(broker_name) in PAPER_BROKERS


def is_longport_broker(broker_name: str | None = None) -> bool:
    """Return whether the selected backend uses the LongPort SDK."""

    return resolve_broker_name(broker_name) in LONGPORT_BROKERS


def is_ibkr_broker(broker_name: str | None = None) -> bool:
    """Return whether the selected backend uses the IBKR runtime."""

    return resolve_broker_name(broker_name) in IBKR_BROKERS


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
        LongPortBrokerAdapter, _, _ = _load_longport_runtime()
        return LongPortBrokerAdapter.capabilities
    if backend == "longport-paper":
        _, LongPortPaperBrokerAdapter, _ = _load_longport_runtime()
        return LongPortPaperBrokerAdapter.capabilities
    if backend in IBKR_BROKERS:
        IbkrPaperBrokerAdapter = _load_ibkr_adapter_cls()
        return IbkrPaperBrokerAdapter.capabilities
    if backend in ALPACA_BROKERS:
        AlpacaPaperBrokerAdapter = _load_alpaca_adapter_cls()
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
        LongPortBrokerAdapter, _, _ = _load_longport_runtime()
        return LongPortBrokerAdapter(client=client)
    if backend == "longport-paper":
        _, LongPortPaperBrokerAdapter, _ = _load_longport_runtime()
        return LongPortPaperBrokerAdapter(client=client)
    if backend in IBKR_BROKERS:
        IbkrPaperBrokerAdapter = _load_ibkr_adapter_cls()
        return IbkrPaperBrokerAdapter(client=client)
    if backend in ALPACA_BROKERS:
        if client is not None:
            raise BrokerValidationError(
                "custom broker client injection is only supported for longport and ibkr backends"
            )
        AlpacaPaperBrokerAdapter = _load_alpaca_adapter_cls()
        return AlpacaPaperBrokerAdapter()

    raise BrokerValidationError(f"unsupported broker backend: {backend}")
