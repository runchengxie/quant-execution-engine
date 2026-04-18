"""Broker adapter contracts and shared execution records."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any

from ..models import AccountSnapshot, Quote


def utc_now_iso() -> str:
    """Return an ISO-8601 UTC timestamp string."""

    return datetime.now(timezone.utc).isoformat()


class BrokerError(RuntimeError):
    """Base error raised by broker adapter operations."""


class BrokerValidationError(BrokerError):
    """Raised when a broker request is invalid before submission."""


class UnsupportedBrokerOperationError(BrokerError):
    """Raised when an adapter cannot support a requested operation."""


class BrokerImportError(BrokerError):
    """Raised when an optional broker dependency is unavailable."""


@dataclass(slots=True)
class ResolvedBrokerAccount:
    """Normalized broker account reference."""

    label: str
    broker_account_id: str | None = None
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass(slots=True)
class BrokerCapabilityMatrix:
    """Machine-readable broker capability declaration."""

    name: str
    supports_live_submit: bool = False
    supports_cancel: bool = False
    supports_order_query: bool = False
    supports_open_order_listing: bool = False
    supports_order_history: bool = False
    supports_fill_history: bool = False
    supports_reconcile: bool = False
    supports_account_selection: bool = False
    supports_fractional: bool = False
    supports_short: bool = False
    supports_extended_hours: bool = False
    supported_order_types: tuple[str, ...] = ("MARKET",)
    supported_time_in_force: tuple[str, ...] = ("DAY",)
    notes: dict[str, Any] = field(default_factory=dict)


@dataclass(slots=True)
class BrokerOrderRequest:
    """Broker-neutral order submission payload."""

    symbol: str
    quantity: float
    side: str
    order_type: str = "MARKET"
    limit_price: float | None = None
    time_in_force: str = "DAY"
    client_order_id: str | None = None
    account: ResolvedBrokerAccount | None = None
    extended_hours: bool = False
    metadata: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        self.side = str(self.side).upper()
        self.order_type = str(self.order_type).upper()
        self.time_in_force = str(self.time_in_force).upper()
        if self.quantity <= 0:
            raise ValueError("broker order quantity must be greater than 0")
        if self.side not in {"BUY", "SELL"}:
            raise ValueError(f"unsupported order side: {self.side}")
        if self.order_type not in {"MARKET", "LIMIT"}:
            raise ValueError(f"unsupported order type: {self.order_type}")
        if self.order_type == "LIMIT" and (
            self.limit_price is None or self.limit_price <= 0
        ):
            raise ValueError("limit orders require a positive limit_price")


@dataclass(slots=True)
class BrokerOrderRecord:
    """Normalized broker order state."""

    broker_order_id: str
    symbol: str
    side: str
    quantity: float
    broker_name: str
    account_label: str
    filled_quantity: float = 0.0
    remaining_quantity: float | None = None
    status: str = "NEW"
    client_order_id: str | None = None
    avg_fill_price: float | None = None
    submitted_at: str = field(default_factory=utc_now_iso)
    updated_at: str = field(default_factory=utc_now_iso)
    message: str | None = None
    raw: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        self.side = str(self.side).upper()
        self.status = str(self.status).upper()
        if self.remaining_quantity is None:
            self.remaining_quantity = max(0.0, float(self.quantity) - float(self.filled_quantity))


@dataclass(slots=True)
class BrokerFillRecord:
    """Normalized fill/execution event."""

    fill_id: str
    broker_order_id: str
    symbol: str
    quantity: float
    price: float
    broker_name: str
    account_label: str
    filled_at: str = field(default_factory=utc_now_iso)
    raw: dict[str, Any] = field(default_factory=dict)


@dataclass(slots=True)
class BrokerReconcileReport:
    """Result of a reconcile pass."""

    broker_name: str
    account_label: str
    fetched_at: str = field(default_factory=utc_now_iso)
    open_orders: list[BrokerOrderRecord] = field(default_factory=list)
    fills: list[BrokerFillRecord] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)


class BrokerAdapter:
    """Base broker adapter with explicit unsupported defaults."""

    backend_name = "unknown"
    capabilities = BrokerCapabilityMatrix(name="unknown")

    def resolve_account(self, account_label: str | None = None) -> ResolvedBrokerAccount:
        return ResolvedBrokerAccount(label=account_label or "main")

    def get_account_snapshot(
        self,
        account: ResolvedBrokerAccount | None = None,
        *,
        include_quotes: bool = True,
    ) -> AccountSnapshot:
        raise UnsupportedBrokerOperationError(
            f"{self.backend_name} does not implement account snapshots"
        )

    def get_quotes(
        self, symbols: list[str], *, include_depth: bool = False
    ) -> dict[str, Quote]:
        raise UnsupportedBrokerOperationError(
            f"{self.backend_name} does not implement quote retrieval"
        )

    def lot_size(self, symbol: str) -> int:
        return 1

    def submit_order(self, request: BrokerOrderRequest) -> BrokerOrderRecord:
        raise UnsupportedBrokerOperationError(
            f"{self.backend_name} does not support order submission"
        )

    def get_order(
        self,
        broker_order_id: str,
        account: ResolvedBrokerAccount | None = None,
    ) -> BrokerOrderRecord:
        raise UnsupportedBrokerOperationError(
            f"{self.backend_name} does not support order lookup"
        )

    def list_open_orders(
        self,
        account: ResolvedBrokerAccount | None = None,
    ) -> list[BrokerOrderRecord]:
        raise UnsupportedBrokerOperationError(
            f"{self.backend_name} does not support open-order listing"
        )

    def list_order_history(
        self,
        account: ResolvedBrokerAccount | None = None,
        *,
        symbol: str | None = None,
        broker_order_id: str | None = None,
    ) -> list[BrokerOrderRecord]:
        raise UnsupportedBrokerOperationError(
            f"{self.backend_name} does not support broker-side order history"
        )

    def cancel_order(
        self,
        broker_order_id: str,
        account: ResolvedBrokerAccount | None = None,
    ) -> None:
        raise UnsupportedBrokerOperationError(
            f"{self.backend_name} does not support order cancellation"
        )

    def list_fills(
        self,
        account: ResolvedBrokerAccount | None = None,
        *,
        broker_order_id: str | None = None,
    ) -> list[BrokerFillRecord]:
        return []

    def list_fill_history(
        self,
        account: ResolvedBrokerAccount | None = None,
        *,
        symbol: str | None = None,
        broker_order_id: str | None = None,
    ) -> list[BrokerFillRecord]:
        raise UnsupportedBrokerOperationError(
            f"{self.backend_name} does not support broker-side fill history"
        )

    def reconcile(
        self,
        account: ResolvedBrokerAccount | None = None,
    ) -> BrokerReconcileReport:
        resolved = account or self.resolve_account()
        return BrokerReconcileReport(
            broker_name=self.backend_name,
            account_label=resolved.label,
        )

    def close(self) -> None:
        """Release resources held by the adapter."""
