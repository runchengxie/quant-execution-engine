"""Broker integrations."""

from .base import (
    BrokerAdapter,
    BrokerCapabilityMatrix,
    BrokerError,
    BrokerImportError,
    BrokerOrderRecord,
    BrokerOrderRequest,
    BrokerValidationError,
    ResolvedBrokerAccount,
)
from .factory import (
    get_account_config,
    get_broker_adapter,
    get_broker_capabilities,
    is_longport_broker,
    is_paper_broker,
    peek_broker_name,
    resolve_broker_name,
    resolve_default_account_label,
)

__all__ = [
    "BrokerAdapter",
    "BrokerCapabilityMatrix",
    "BrokerError",
    "BrokerImportError",
    "BrokerOrderRecord",
    "BrokerOrderRequest",
    "BrokerValidationError",
    "ResolvedBrokerAccount",
    "LongPortBrokerAdapter",
    "LongPortPaperBrokerAdapter",
    "LongPortClient",
    "_to_lb_symbol",
    "get_account_config",
    "get_broker_adapter",
    "get_broker_capabilities",
    "get_config",
    "getenv_both",
    "is_longport_broker",
    "is_paper_broker",
    "peek_broker_name",
    "resolve_broker_name",
    "resolve_default_account_label",
]


def __getattr__(name: str):
    if name in {
        "LongPortBrokerAdapter",
        "LongPortPaperBrokerAdapter",
        "LongPortClient",
        "_to_lb_symbol",
        "get_config",
        "getenv_both",
    }:
        from .longport import (
            LongPortBrokerAdapter,
            LongPortClient,
            LongPortPaperBrokerAdapter,
            _to_lb_symbol,
            get_config,
            getenv_both,
        )

        exports = {
            "LongPortBrokerAdapter": LongPortBrokerAdapter,
            "LongPortPaperBrokerAdapter": LongPortPaperBrokerAdapter,
            "LongPortClient": LongPortClient,
            "_to_lb_symbol": _to_lb_symbol,
            "get_config": get_config,
            "getenv_both": getenv_both,
        }
        return exports[name]
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
