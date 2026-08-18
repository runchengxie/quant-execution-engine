"""Deterministic offline mock broker adapter.

The ``mock-sim`` backend simulates order submission, fill, cancel, query, and
reconcile entirely on disk. It needs no network, no credentials, and no external
SDK. Simulated state (cash, positions, orders, fills) is persisted under
``QEXEC_MOCK_SIM_STATE_DIR`` so interrupted runs can be resumed from the same
directory with consistent output.

Use it for offline end-to-end evidence chains and restart-recovery checks. It
does not prove anything about real broker channels. Broker capabilities must be
judged per backend; evidence from ``mock-sim`` never transfers to another
backend.
"""

from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
from typing import Any

from ..models import AccountSnapshot, Position, Quote
from .base import (
    BrokerAdapter,
    BrokerCapabilityMatrix,
    BrokerFillRecord,
    BrokerOrderRecord,
    BrokerOrderRequest,
    BrokerReconcileReport,
    BrokerValidationError,
    ResolvedBrokerAccount,
)

MOCK_SIM_STATE_DIR_ENV = "QEXEC_MOCK_SIM_STATE_DIR"
MOCK_SIM_CLOCK_ENV = "QEXEC_MOCK_SIM_CLOCK"
MOCK_SIM_PRICE_ENV = "QEXEC_MOCK_SIM_PRICE"
MOCK_SIM_CASH_ENV = "QEXEC_MOCK_SIM_CASH_USD"

DEFAULT_CLOCK = "2026-01-01T00:00:00+00:00"
DEFAULT_CASH_USD = 1_000_000.0

_OPEN_STATUSES = frozenset({"NEW", "ACCEPTED", "PENDING_NEW", "PARTIALLY_FILLED"})
_TERMINAL_STATUSES = frozenset({"FILLED", "CANCELED", "REJECTED", "EXPIRED", "FAILED"})


def _env_str(name: str, default: str) -> str:
    raw = os.getenv(name)
    return raw if raw else default


def _env_float(name: str, default: float) -> float:
    raw = os.getenv(name)
    if raw is None or raw == "":
        return default
    try:
        value = float(raw)
    except ValueError:
        return default
    return value if value > 0 else default


def _deterministic_price(symbol: str) -> float:
    digest = hashlib.sha256(str(symbol).upper().encode("utf-8")).hexdigest()
    seed = int(digest[:8], 16)
    cents = 500 + (seed % 30000)
    return round(cents / 100.0, 2)


def _is_cn_symbol(symbol: str) -> bool:
    return str(symbol).upper().endswith(".CN")


class MockSimBrokerAdapter(BrokerAdapter):
    """Deterministic no-network simulator with a persisted order book."""

    backend_name = "mock-sim"
    capabilities = BrokerCapabilityMatrix(
        name="mock-sim",
        supports_live_submit=False,
        supports_cancel=True,
        supports_order_query=True,
        supports_open_order_listing=True,
        supports_order_history=True,
        supports_fill_history=True,
        supports_reconcile=True,
        supports_account_selection=True,
        supports_fractional=False,
        supports_short=False,
        supported_order_types=("MARKET", "LIMIT"),
        supported_time_in_force=("DAY", "GTC"),
        notes={
            "mode": "paper",
            "scope": "deterministic offline simulation only",
            "live_submit": (
                "false: submit/cancel/query are simulated, never routed to a real broker"
            ),
            "state_dir_env": MOCK_SIM_STATE_DIR_ENV,
            "clock_env": MOCK_SIM_CLOCK_ENV,
            "price_env": MOCK_SIM_PRICE_ENV,
            "cash_env": MOCK_SIM_CASH_ENV,
        },
    )

    def __init__(self) -> None:
        self._state_root = Path(_env_str(MOCK_SIM_STATE_DIR_ENV, "outputs/mock-sim")).expanduser()

    def _clock(self) -> str:
        return _env_str(MOCK_SIM_CLOCK_ENV, DEFAULT_CLOCK)

    def _book_path(self, account_label: str) -> Path:
        safe = "".join(ch if ch.isalnum() or ch in "._-" else "-" for ch in account_label)
        return self._state_root / f"{safe}.json"

    def _load_book(self, account_label: str) -> dict[str, Any]:
        path = self._book_path(account_label)
        if not path.exists():
            return {
                "version": 1,
                "account_label": account_label,
                "cash_usd": _env_float(MOCK_SIM_CASH_ENV, DEFAULT_CASH_USD),
                "positions": {},
                "orders": {},
                "fills": {},
                "order_seq": 0,
            }
        raw = json.loads(path.read_text(encoding="utf-8"))
        if not isinstance(raw, dict):
            raise BrokerValidationError(f"corrupt mock-sim state file: {path}")
        return raw

    def _save_book(self, book: dict[str, Any]) -> None:
        path = self._book_path(str(book.get("account_label") or "main"))
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(book, ensure_ascii=False, indent=2), encoding="utf-8")

    def resolve_account(self, account_label: str | None = None) -> ResolvedBrokerAccount:
        return ResolvedBrokerAccount(label=str(account_label or "main").strip() or "main")

    def get_account_snapshot(
        self,
        account: ResolvedBrokerAccount | None = None,
        *,
        include_quotes: bool = True,
    ) -> AccountSnapshot:
        resolved = account or self.resolve_account()
        book = self._load_book(resolved.label)
        positions: list[Position] = []
        for symbol, quantity in sorted(book.get("positions", {}).items()):
            qty = int(quantity)
            if qty == 0:
                continue
            price = self.get_quotes([symbol])[symbol].price
            positions.append(
                Position(
                    symbol=str(symbol),
                    quantity=qty,
                    last_price=price,
                    estimated_value=qty * price,
                    env="paper",
                )
            )
        total = float(book.get("cash_usd", 0.0)) + sum(
            float(position.estimated_value) for position in positions
        )
        return AccountSnapshot(
            env="paper",
            cash_usd=float(book.get("cash_usd", 0.0)),
            positions=positions,
            total_market_value=sum(float(position.estimated_value) for position in positions),
            total_portfolio_value=total,
            base_currency="USD",
        )

    def get_quotes(self, symbols: list[str], *, include_depth: bool = False) -> dict[str, Quote]:
        clock = self._clock()
        price_override = _env_float(MOCK_SIM_PRICE_ENV, 0.0)
        results: dict[str, Quote] = {}
        for symbol in symbols:
            price = price_override or _deterministic_price(symbol)
            results[str(symbol)] = Quote(
                symbol=str(symbol),
                price=price,
                timestamp=clock,
                bid=round(price * 0.999, 4) if include_depth else None,
                ask=round(price * 1.001, 4) if include_depth else None,
                daily_volume=1_000_000.0 if include_depth else None,
            )
        return results

    def lot_size(self, symbol: str) -> int:
        return 100 if _is_cn_symbol(symbol) else 1

    def submit_order(self, request: BrokerOrderRequest) -> BrokerOrderRecord:
        resolved = request.account or self.resolve_account()
        book = self._load_book(resolved.label)
        price = self.get_quotes([request.symbol])[request.symbol].price
        order_seq = int(book.get("order_seq", 0)) + 1
        broker_order_id = f"mock-{order_seq:06d}"
        book["order_seq"] = order_seq
        clock = self._clock()

        limit_price = float(request.limit_price or 0.0)
        if request.order_type == "LIMIT":
            fillable = (request.side == "BUY" and limit_price >= price) or (
                request.side == "SELL" and limit_price <= price
            )
        else:
            fillable = True

        record = BrokerOrderRecord(
            broker_order_id=broker_order_id,
            symbol=request.symbol,
            side=request.side,
            quantity=request.quantity,
            broker_name=self.backend_name,
            account_label=resolved.label,
            status="NEW",
            client_order_id=request.client_order_id,
            submitted_at=clock,
            updated_at=clock,
            raw={"order_type": request.order_type},
        )

        if fillable:
            quantity = float(request.quantity)
            positions = book.setdefault("positions", {})
            current = float(positions.get(request.symbol, 0.0))
            if request.side == "SELL" and current < quantity:
                raise BrokerValidationError(
                    f"mock-sim rejects SELL {request.symbol}: held {current}, requested {quantity}"
                )
            if request.side == "BUY":
                cost = quantity * price
                if float(book.get("cash_usd", 0.0)) < cost:
                    raise BrokerValidationError(
                        f"mock-sim rejects BUY {request.symbol}: insufficient cash"
                    )
                book["cash_usd"] = float(book.get("cash_usd", 0.0)) - cost
                positions[request.symbol] = current + quantity
            else:
                book["cash_usd"] = float(book.get("cash_usd", 0.0)) + quantity * price
                positions[request.symbol] = current - quantity

            record.status = "FILLED"
            record.filled_quantity = quantity
            record.remaining_quantity = 0.0
            record.avg_fill_price = price
            record.updated_at = clock
            fills = book.setdefault("fills", {})
            fills.setdefault(broker_order_id, []).append(
                {
                    "fill_id": f"{broker_order_id}-fill",
                    "broker_order_id": broker_order_id,
                    "symbol": request.symbol,
                    "quantity": quantity,
                    "price": price,
                    "broker_name": self.backend_name,
                    "account_label": resolved.label,
                    "filled_at": clock,
                }
            )

        book["orders"][broker_order_id] = {
            "broker_order_id": broker_order_id,
            "symbol": request.symbol,
            "side": request.side,
            "quantity": request.quantity,
            "broker_name": self.backend_name,
            "account_label": resolved.label,
            "filled_quantity": record.filled_quantity,
            "remaining_quantity": record.remaining_quantity,
            "status": record.status,
            "client_order_id": request.client_order_id,
            "avg_fill_price": record.avg_fill_price,
            "submitted_at": clock,
            "updated_at": record.updated_at,
        }
        self._save_book(book)
        return record

    def _record_from_book(self, order: dict[str, Any], account_label: str) -> BrokerOrderRecord:
        return BrokerOrderRecord(
            broker_order_id=str(order.get("broker_order_id")),
            symbol=str(order.get("symbol")),
            side=str(order.get("side")),
            quantity=float(order.get("quantity") or 0.0),
            broker_name=str(order.get("broker_name") or self.backend_name),
            account_label=str(order.get("account_label") or account_label),
            filled_quantity=float(order.get("filled_quantity") or 0.0),
            remaining_quantity=(
                float(order["remaining_quantity"])
                if order.get("remaining_quantity") is not None
                else max(
                    0.0,
                    float(order.get("quantity") or 0.0)
                    - float(order.get("filled_quantity") or 0.0),
                )
            ),
            status=str(order.get("status")),
            client_order_id=order.get("client_order_id"),
            avg_fill_price=(
                float(order["avg_fill_price"]) if order.get("avg_fill_price") is not None else None
            ),
            submitted_at=str(order.get("submitted_at")),
            updated_at=str(order.get("updated_at")),
            message=order.get("message"),
            raw=dict(order.get("raw") or {}),
        )

    def get_order(
        self,
        broker_order_id: str,
        account: ResolvedBrokerAccount | None = None,
    ) -> BrokerOrderRecord:
        resolved = account or self.resolve_account()
        book = self._load_book(resolved.label)
        order = book.get("orders", {}).get(broker_order_id)
        if order is None:
            raise BrokerValidationError(
                f"mock-sim order not found: {broker_order_id} for {resolved.label}"
            )
        return self._record_from_book(order, resolved.label)

    def list_open_orders(
        self,
        account: ResolvedBrokerAccount | None = None,
    ) -> list[BrokerOrderRecord]:
        resolved = account or self.resolve_account()
        book = self._load_book(resolved.label)
        return [
            self._record_from_book(order, resolved.label)
            for order in sorted(
                book.get("orders", {}).values(),
                key=lambda item: str(item.get("broker_order_id")),
            )
            if str(order.get("status") or "").upper() in _OPEN_STATUSES
        ]

    def list_order_history(
        self,
        account: ResolvedBrokerAccount | None = None,
        *,
        symbol: str | None = None,
        broker_order_id: str | None = None,
    ) -> list[BrokerOrderRecord]:
        resolved = account or self.resolve_account()
        book = self._load_book(resolved.label)
        records = [
            self._record_from_book(order, resolved.label)
            for order in sorted(
                book.get("orders", {}).values(),
                key=lambda item: str(item.get("broker_order_id")),
            )
        ]
        if symbol is not None:
            records = [record for record in records if record.symbol == symbol]
        if broker_order_id is not None:
            records = [record for record in records if record.broker_order_id == broker_order_id]
        return records

    def cancel_order(
        self,
        broker_order_id: str,
        account: ResolvedBrokerAccount | None = None,
    ) -> None:
        resolved = account or self.resolve_account()
        book = self._load_book(resolved.label)
        order = book.get("orders", {}).get(broker_order_id)
        if order is None:
            raise BrokerValidationError(
                f"mock-sim order not found: {broker_order_id} for {resolved.label}"
            )
        if str(order.get("status") or "").upper() in _TERMINAL_STATUSES:
            return
        order["status"] = "CANCELED"
        order["updated_at"] = self._clock()
        self._save_book(book)

    def list_fills(
        self,
        account: ResolvedBrokerAccount | None = None,
        *,
        broker_order_id: str | None = None,
    ) -> list[BrokerFillRecord]:
        resolved = account or self.resolve_account()
        book = self._load_book(resolved.label)
        fills: list[BrokerFillRecord] = []
        for order_id, entries in sorted(book.get("fills", {}).items()):
            if broker_order_id is not None and order_id != broker_order_id:
                continue
            for fill in entries:
                fills.append(
                    BrokerFillRecord(
                        fill_id=str(fill.get("fill_id")),
                        broker_order_id=str(fill.get("broker_order_id")),
                        symbol=str(fill.get("symbol")),
                        quantity=float(fill.get("quantity") or 0.0),
                        price=float(fill.get("price") or 0.0),
                        broker_name=str(fill.get("broker_name") or self.backend_name),
                        account_label=str(fill.get("account_label") or resolved.label),
                        filled_at=str(fill.get("filled_at")),
                    )
                )
        return fills

    def list_fill_history(
        self,
        account: ResolvedBrokerAccount | None = None,
        *,
        symbol: str | None = None,
        broker_order_id: str | None = None,
    ) -> list[BrokerFillRecord]:
        resolved = account or self.resolve_account()
        fills = self.list_fills(resolved, broker_order_id=broker_order_id)
        if symbol is not None:
            fills = [fill for fill in fills if fill.symbol == symbol]
        return fills

    def reconcile(
        self,
        account: ResolvedBrokerAccount | None = None,
    ) -> BrokerReconcileReport:
        resolved = account or self.resolve_account()
        open_orders = self.list_open_orders(resolved)
        fills: list[BrokerFillRecord] = []
        for order in open_orders:
            fills.extend(self.list_fills(resolved, broker_order_id=order.broker_order_id))
        return BrokerReconcileReport(
            broker_name=self.backend_name,
            account_label=resolved.label,
            fetched_at=self._clock(),
            open_orders=open_orders,
            fills=fills,
        )
