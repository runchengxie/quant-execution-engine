"""Public facade for typed execution serialization.

The stable API remains in this module.  Implementation is split into common
wire primitives, explicit legacy-v1 migration, and the deterministic v2 codec
so later contract work can evolve without creating another monolithic hotspot.
"""

from __future__ import annotations

from ._serialization_common import (
    SCHEMA_VERSION,
    DomainModel,
    WireFormatError,
    WirePayload,
    WireScalar,
    WireValue,
    instrument_from_legacy,
    migrate_legacy_datetime,
)
from ._serialization_v1 import (
    fill_from_v1,
    fill_to_v1,
    order_event_from_v1,
    order_event_to_v1,
    order_intent_from_v1,
    order_intent_to_v1,
    portfolio_target_from_v1,
    portfolio_target_to_v1,
)
from ._serialization_v2 import (
    approved_target_from_v2,
    approved_target_to_v2,
    dumps_v2,
    fill_from_v2,
    fill_to_v2,
    from_v2_payload,
    loads_v2,
    order_event_from_v2,
    order_event_to_v2,
    order_intent_from_v2,
    order_intent_to_v2,
    portfolio_target_from_v2,
    portfolio_target_to_v2,
    to_v2_payload,
)

__all__ = [
    "DomainModel",
    "SCHEMA_VERSION",
    "WireFormatError",
    "WirePayload",
    "WireScalar",
    "WireValue",
    "approved_target_from_v2",
    "approved_target_to_v2",
    "dumps_v2",
    "fill_from_v1",
    "fill_from_v2",
    "fill_to_v1",
    "fill_to_v2",
    "from_v2_payload",
    "instrument_from_legacy",
    "loads_v2",
    "migrate_legacy_datetime",
    "order_event_from_v1",
    "order_event_from_v2",
    "order_event_to_v1",
    "order_event_to_v2",
    "order_intent_from_v1",
    "order_intent_from_v2",
    "order_intent_to_v1",
    "order_intent_to_v2",
    "portfolio_target_from_v1",
    "portfolio_target_from_v2",
    "portfolio_target_to_v1",
    "portfolio_target_to_v2",
    "to_v2_payload",
]
