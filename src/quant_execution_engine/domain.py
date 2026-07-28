"""Framework-neutral, immutable execution domain models (public facade).

The models in this module are the typed boundary for new execution work.  The
mutable DTOs in :mod:`quant_execution_engine.models` and the version-1 state
records in :mod:`quant_execution_engine.execution_state` remain available for
the current CLI and recovery paths.  Conversion between those wire shapes and
these models belongs in :mod:`quant_execution_engine.serialization`.

The implementation now lives in the focused submodules (``_domain_enums`` /
``_domain_models`` / ``_domain_capabilities``); this file re-exports the public
surface so existing imports keep working unchanged.
"""

from ._domain_capabilities import (
    CapabilityValidationError,
    ExecutionCapabilities,
    order_intent_capability_violations,
    portfolio_target_capability_violations,
    validate_order_intent_capabilities,
    validate_portfolio_target_capabilities,
)
from ._domain_enums import (
    ExecutionEventType,
    OrderSide,
    OrderStatus,
    OrderType,
    TimeInForce,
)
from ._domain_models import (
    ApprovedTarget,
    Fill,
    InstrumentId,
    Money,
    OrderEvent,
    OrderIntent,
    PortfolioTarget,
)

__all__ = [
    "ApprovedTarget",
    "CapabilityValidationError",
    "ExecutionCapabilities",
    "ExecutionEventType",
    "Fill",
    "InstrumentId",
    "Money",
    "OrderEvent",
    "OrderIntent",
    "OrderSide",
    "OrderStatus",
    "OrderType",
    "PortfolioTarget",
    "TimeInForce",
    "order_intent_capability_violations",
    "portfolio_target_capability_violations",
    "validate_order_intent_capabilities",
    "validate_portfolio_target_capabilities",
]
