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
    is_ibkr_broker,
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
    "IbkrPaperBrokerAdapter",
    "LongPortBrokerAdapter",
    "LongPortPaperBrokerAdapter",
    "LongPortClient",
    "probe_ibkr_runtime_config",
    "resolve_ibkr_runtime_config",
    "_to_lb_symbol",
    "get_account_config",
    "get_broker_adapter",
    "get_broker_capabilities",
    "get_config",
    "getenv_both",
    "is_ibkr_broker",
    "is_longport_broker",
    "is_paper_broker",
    "peek_broker_name",
    "resolve_broker_name",
    "resolve_default_account_label",
]


def __getattr__(name: str):
    if name in {
        "IbkrPaperBrokerAdapter",
        "LongPortBrokerAdapter",
        "LongPortPaperBrokerAdapter",
        "LongPortClient",
        "probe_ibkr_runtime_config",
        "resolve_ibkr_runtime_config",
        "_to_lb_symbol",
        "get_config",
        "getenv_both",
    }:
        from .ibkr import IbkrPaperBrokerAdapter
        from .ibkr_runtime import (
            probe_ibkr_runtime_config,
            resolve_ibkr_runtime_config,
        )
        from .longport_adapter import (
            LongPortBrokerAdapter,
            LongPortPaperBrokerAdapter,
        )
        from .longport import (
            LongPortClient,
            _to_lb_symbol,
            get_config,
            getenv_both,
        )

        exports = {
            "IbkrPaperBrokerAdapter": IbkrPaperBrokerAdapter,
            "LongPortBrokerAdapter": LongPortBrokerAdapter,
            "LongPortPaperBrokerAdapter": LongPortPaperBrokerAdapter,
            "LongPortClient": LongPortClient,
            "probe_ibkr_runtime_config": probe_ibkr_runtime_config,
            "resolve_ibkr_runtime_config": resolve_ibkr_runtime_config,
            "_to_lb_symbol": _to_lb_symbol,
            "get_config": get_config,
            "getenv_both": getenv_both,
        }
        return exports[name]
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
