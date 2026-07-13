from __future__ import annotations

import json
import subprocess
import sys
from dataclasses import FrozenInstanceError, asdict
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from pathlib import Path
from typing import cast

import pytest

from quant_execution_engine.domain import (
    ApprovedTarget,
    CapabilityValidationError,
    ExecutionCapabilities,
    ExecutionEventType,
    Fill,
    InstrumentId,
    Money,
    OrderEvent,
    OrderIntent,
    OrderSide,
    OrderStatus,
    OrderType,
    PortfolioTarget,
    TimeInForce,
    validate_order_intent_capabilities,
    validate_portfolio_target_capabilities,
)
from quant_execution_engine.execution_state import OrderIntent as LegacyOrderIntent
from quant_execution_engine.serialization import (
    DomainModel,
    WireFormatError,
    dumps_v2,
    fill_from_v1,
    fill_to_v1,
    loads_v2,
    order_event_from_v1,
    order_intent_from_v1,
    order_intent_from_v2,
    order_intent_to_v1,
    order_intent_to_v2,
    portfolio_target_from_v1,
    to_v2_payload,
)

pytestmark = pytest.mark.unit

UTC_NOW = datetime(2026, 7, 13, 8, 30, tzinfo=timezone.utc)


def _instrument() -> InstrumentId:
    return InstrumentId(symbol="AAPL", market="US", currency="USD")


def _target(*, quantity: str = "1") -> PortfolioTarget:
    return PortfolioTarget(
        instrument=_instrument(),
        portfolio_id="paper-growth",
        as_of=UTC_NOW,
        target_quantity=Decimal(quantity),
        source="unit",
        notes="operator review",
        metadata={"strategy": "typed-domain", "tags": ["paper", "v2"]},
    )


def _intent(*, quantity: str = "1", opens_short: bool = False) -> OrderIntent:
    return OrderIntent(
        intent_id="intent-001",
        instrument=_instrument(),
        side=OrderSide.SELL if opens_short else OrderSide.BUY,
        quantity=Decimal(quantity),
        order_type=OrderType.LIMIT,
        limit_price=Decimal("198.1250"),
        time_in_force=TimeInForce.DAY,
        created_at=UTC_NOW,
        opens_short=opens_short,
        approval_id="approval-001",
        broker_name="paper",
        account_label="main",
        run_id="run-001",
        target_source="alpha-research",
        target_as_of=datetime(2026, 7, 12, tzinfo=timezone.utc),
        target_input_path="targets.json",
        metadata={"reason": "rebalance"},
    )


def test_domain_models_are_frozen_and_metadata_is_immutable() -> None:
    intent = _intent()

    with pytest.raises(FrozenInstanceError):
        intent.quantity = Decimal("2")  # type: ignore[misc]
    with pytest.raises(TypeError):
        intent.metadata["reason"] = "manual"  # type: ignore[index]

    assert isinstance(OrderSide.BUY, str)
    assert str(OrderSide.BUY) == "BUY"

    with pytest.raises(TypeError, match="side must be OrderSide"):
        OrderIntent(
            intent_id="untyped",
            instrument=_instrument(),
            side="BUY",  # type: ignore[arg-type]
            quantity=Decimal("1"),
            order_type=OrderType.MARKET,
            created_at=UTC_NOW,
        )

    with pytest.raises(TypeError, match="instrument must be InstrumentId"):
        OrderIntent(
            intent_id="bad-instrument",
            instrument="AAPL.US",  # type: ignore[arg-type]
            side=OrderSide.BUY,
            quantity=Decimal("1"),
            order_type=OrderType.MARKET,
            created_at=UTC_NOW,
        )

    with pytest.raises(TypeError, match="currency must be a string"):
        InstrumentId(symbol="AAPL", market="US", currency=123)  # type: ignore[arg-type]


def test_domain_rejects_naive_datetime_but_legacy_reader_migrates_it() -> None:
    with pytest.raises(ValueError, match="timezone-aware"):
        OrderIntent(
            intent_id="naive",
            instrument=_instrument(),
            side=OrderSide.BUY,
            quantity=Decimal("1"),
            order_type=OrderType.MARKET,
            created_at=datetime(2026, 7, 13, 8, 30),
        )

    legacy = {
        "intent_id": "legacy-naive",
        "symbol": "AAPL.US",
        "side": "BUY",
        "quantity": 1.25,
        "order_type": "MARKET",
        "created_at": "2026-07-13T08:30:00",
    }
    migrated = order_intent_from_v1(
        legacy,
        naive_timezone=timezone(timedelta(hours=8)),
    )

    assert migrated.created_at == datetime(2026, 7, 13, 0, 30, tzinfo=timezone.utc)
    assert migrated.quantity == Decimal("1.25")


def test_v2_reader_rejects_naive_timestamp_and_numeric_decimal() -> None:
    payload = order_intent_to_v2(_intent())
    payload["created_at"] = "2026-07-13T08:30:00"
    with pytest.raises(WireFormatError, match="timezone-aware"):
        order_intent_from_v2(payload)

    payload = order_intent_to_v2(_intent())
    payload["quantity"] = 1.5
    with pytest.raises(WireFormatError, match="decimal string"):
        order_intent_from_v2(payload)


def test_v2_json_is_deterministic_and_uses_decimal_strings() -> None:
    intent = _intent(quantity="1.5000")

    first = dumps_v2(intent)
    second = dumps_v2(intent)
    payload = json.loads(first)

    assert first == second
    assert first.endswith("\n")
    assert payload["schema_version"] == 2
    assert payload["quantity"] == "1.5"
    assert payload["limit_price"] == "198.125"
    assert payload["created_at"].endswith("Z")
    assert loads_v2(first) == intent

    with pytest.raises(TypeError, match="unsupported execution domain model"):
        to_v2_payload(cast(DomainModel, object()))


def test_all_v2_domain_representations_round_trip() -> None:
    target = _target(quantity="2.500")
    approved = ApprovedTarget(
        approval_id="approval-001",
        target=target,
        approved_at=UTC_NOW,
        policy_reference="policy://paper/v3",
        account_label="main",
        valid_until=UTC_NOW + timedelta(hours=1),
        max_notional=Money(Decimal("10000.00"), "usd"),
    )
    event = OrderEvent(
        event_id="event-001",
        event_type=ExecutionEventType.PARTIALLY_FILLED,
        occurred_at=UTC_NOW,
        instrument=_instrument(),
        status=OrderStatus.PARTIALLY_FILLED,
        broker_name="paper",
        account_label="main",
        broker_order_id="broker-001",
        intent_id="intent-001",
        side=OrderSide.BUY,
        quantity=Decimal("2.5"),
        filled_quantity=Decimal("1.25"),
        remaining_quantity=Decimal("1.25"),
        average_fill_price=Decimal("198.125"),
    )
    fill = Fill(
        fill_id="fill-001",
        broker_order_id="broker-001",
        instrument=_instrument(),
        quantity=Decimal("1.25"),
        price=Decimal("198.125"),
        filled_at=UTC_NOW,
        broker_name="paper",
        account_label="main",
        intent_id="intent-001",
        side=OrderSide.BUY,
        commission=Money(Decimal("0.35"), "USD"),
    )

    for model in (target, approved, _intent(), event, fill):
        assert loads_v2(dumps_v2(model)) == model

    assert fill.notional == Money(Decimal("247.65625"), "USD")


def test_legacy_order_intent_round_trip_keeps_current_state_dto_compatible() -> None:
    legacy = LegacyOrderIntent(
        intent_id="legacy-intent",
        symbol="600519.SH.CN",
        side="SELL",
        quantity=100.0,
        order_type="LIMIT",
        limit_price=1500.25,
        broker_name="longport-paper",
        account_label="main",
        target_source="strategy-pipeline",
        target_asof="2026-07-12",
        target_input_path="targets.json",
        run_id="run-legacy",
        created_at="2026-07-13T08:30:00Z",
        metadata={"strategy": "value"},
    )
    legacy_payload = asdict(legacy)

    migrated = order_intent_from_v1(legacy_payload)
    v1_again = order_intent_to_v1(migrated)
    migrated_again = order_intent_from_v1(v1_again)

    assert migrated_again == migrated
    assert migrated.instrument == InstrumentId(
        symbol="600519",
        market="CN",
        exchange="SH",
    )
    assert migrated.quantity == Decimal("100.0")
    assert migrated.side is OrderSide.SELL


def test_legacy_target_reader_allows_negative_and_fractional_domain_values() -> None:
    target = portfolio_target_from_v1(
        {
            "symbol": "AAPL",
            "market": "US",
            "target_quantity": -1.5,
            "metadata": {"source_row": 3},
        },
        as_of="2026-07-13",
        portfolio_id="long-short",
    )

    assert target.target_quantity == Decimal("-1.5")
    assert target.as_of == datetime(2026, 7, 13, tzinfo=timezone.utc)


def test_capability_validation_is_separate_from_domain_construction() -> None:
    target = _target(quantity="-1.5")
    intent = _intent(quantity="1.5", opens_short=True)
    long_only = ExecutionCapabilities()

    with pytest.raises(CapabilityValidationError) as target_error:
        validate_portfolio_target_capabilities(target, long_only)
    assert target_error.value.violations == (
        "negative target requires short-selling capability",
        "fractional target quantity is not supported",
    )

    with pytest.raises(CapabilityValidationError) as intent_error:
        validate_order_intent_capabilities(intent, long_only)
    assert "short-sale order intent is not supported" in intent_error.value.violations
    assert "fractional order quantity is not supported" in intent_error.value.violations
    assert "order type LIMIT is not supported" in intent_error.value.violations

    capable = ExecutionCapabilities(
        supports_short=True,
        supports_fractional=True,
        supported_order_types=frozenset({OrderType.MARKET, OrderType.LIMIT}),
        quantity_increment=Decimal("0.5"),
    )
    validate_portfolio_target_capabilities(target, capable)
    validate_order_intent_capabilities(intent, capable)


def test_legacy_broker_order_and_fill_readers_normalize_without_sdk_types() -> None:
    event = order_event_from_v1(
        {
            "broker_order_id": "broker-001",
            "symbol": "AAPL.US",
            "side": "BUY",
            "quantity": 2.5,
            "broker_name": "paper",
            "account_label": "main",
            "filled_quantity": 1.25,
            "remaining_quantity": 1.25,
            "status": "CANCELED",
            "avg_fill_price": 198.125,
            "updated_at": "2026-07-13T08:30:00Z",
            "raw": {"broker_code": "ok"},
        }
    )
    fill = fill_from_v1(
        {
            "fill_id": "fill-001",
            "intent_id": "intent-001",
            "parent_order_id": "parent-001",
            "broker_order_id": "broker-001",
            "symbol": "AAPL.US",
            "quantity": 1.25,
            "price": 198.125,
            "broker_name": "paper",
            "account_label": "main",
            "filled_at": "2026-07-13T08:30:00Z",
        }
    )

    assert event.status is OrderStatus.CANCELLED
    assert event.event_type is ExecutionEventType.CANCELLED
    assert event.quantity == Decimal("2.5")
    assert fill.quantity == Decimal("1.25")
    assert fill.metadata["parent_order_id"] == "parent-001"
    assert fill_from_v1(fill_to_v1(fill)) == Fill(
        fill_id=fill.fill_id,
        broker_order_id=fill.broker_order_id,
        instrument=fill.instrument,
        quantity=fill.quantity,
        price=fill.price,
        filled_at=fill.filled_at,
        broker_name=fill.broker_name,
        account_label=fill.account_label,
        metadata=cast(dict[str, object], fill.metadata),
    )

    unknown = order_event_from_v1(
        {
            "broker_order_id": "broker-unknown",
            "symbol": "AAPL.US",
            "quantity": 1,
            "broker_name": "paper",
            "account_label": "main",
            "status": "BROKER_FROZEN",
            "updated_at": "2026-07-13T08:30:00Z",
        }
    )
    assert unknown.status is OrderStatus.UNKNOWN
    assert unknown.metadata["legacy_status"] == "BROKER_FROZEN"


def test_domain_and_codec_import_without_optional_broker_or_framework_sdks() -> None:
    source_root = Path(__file__).resolve().parents[2] / "src"
    script = """
import importlib.abc
import sys

blocked = {"alpaca", "ib_insync", "longport", "qlib", "vnpy"}

class BlockOptionalSdk(importlib.abc.MetaPathFinder):
    def find_spec(self, fullname, path=None, target=None):
        if fullname.split(".", 1)[0] in blocked:
            raise AssertionError(f"optional SDK imported: {fullname}")
        return None

sys.meta_path.insert(0, BlockOptionalSdk())
import quant_execution_engine.domain
import quant_execution_engine.serialization
"""
    completed = subprocess.run(
        [sys.executable, "-c", script],
        cwd=source_root.parent,
        env={"PYTHONPATH": str(source_root)},
        check=False,
        capture_output=True,
        text=True,
    )

    assert completed.returncode == 0, completed.stderr
