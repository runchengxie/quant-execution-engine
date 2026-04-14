"""Alpaca paper-trading broker adapter."""

from __future__ import annotations

import importlib
import os
from dataclasses import dataclass
from decimal import Decimal
from typing import Any

from ..models import AccountSnapshot, Position, Quote
from .base import (
    BrokerAdapter,
    BrokerCapabilityMatrix,
    BrokerFillRecord,
    BrokerImportError,
    BrokerOrderRecord,
    BrokerOrderRequest,
    BrokerReconcileReport,
    BrokerValidationError,
    ResolvedBrokerAccount,
)


def _alpaca_import(path: str):
    module_name, _, attr_name = path.rpartition(".")
    try:
        module = importlib.import_module(module_name)
    except ImportError as exc:  # pragma: no cover - depends on optional package
        missing = getattr(exc, "name", None)
        if missing and missing not in {module_name, module_name.split(".")[0], "alpaca"}:
            raise BrokerImportError(
                "alpaca-py import failed because dependency "
                f"'{missing}' is missing. Install/update it with: uv sync --extra alpaca"
            ) from exc
        raise BrokerImportError(
            "alpaca-py is not installed. Install it with: uv sync --extra alpaca"
        ) from exc
    return getattr(module, attr_name)


def _strip_market(symbol: str) -> str:
    cleaned = str(symbol).upper().strip()
    if cleaned.endswith(".US"):
        return cleaned[:-3]
    return cleaned


def _as_float(value: Any) -> float:
    if value in (None, ""):
        return 0.0
    if isinstance(value, Decimal):
        return float(value)
    return float(value)


def _alpaca_side(side: str):
    OrderSide = _alpaca_import("alpaca.trading.enums.OrderSide")
    return OrderSide.BUY if side.upper() == "BUY" else OrderSide.SELL


def _alpaca_tif(value: str):
    TimeInForce = _alpaca_import("alpaca.trading.enums.TimeInForce")
    name_map = {
        "DAY": "DAY",
        "GTC": "GTC",
    }
    attr = name_map.get(value.upper(), value.upper())
    return getattr(TimeInForce, attr)


@dataclass(slots=True)
class _AlpacaClients:
    trading: Any | None = None
    data: Any | None = None


class AlpacaPaperBrokerAdapter(BrokerAdapter):
    """Adapter backed by Alpaca paper trading."""

    backend_name = "alpaca-paper"
    capabilities = BrokerCapabilityMatrix(
        name="alpaca-paper",
        supports_live_submit=True,
        supports_cancel=True,
        supports_order_query=True,
        supports_open_order_listing=True,
        supports_reconcile=True,
        supports_account_selection=False,
        supports_fractional=True,
        supports_short=True,
        supports_extended_hours=True,
        supported_order_types=("MARKET", "LIMIT"),
        supported_time_in_force=("DAY", "GTC"),
        notes={"mode": "paper"},
    )

    def __init__(self) -> None:
        self._clients: _AlpacaClients | None = None

    def _credentials(self) -> tuple[str, str]:
        api_key = os.getenv("ALPACA_API_KEY") or os.getenv("APCA_API_KEY_ID")
        secret_key = os.getenv("ALPACA_SECRET_KEY") or os.getenv("APCA_API_SECRET_KEY")
        if not api_key or not secret_key:
            raise BrokerValidationError(
                "missing ALPACA_API_KEY / ALPACA_SECRET_KEY for alpaca-paper"
            )
        return str(api_key), str(secret_key)

    def _get_clients(self) -> _AlpacaClients:
        if self._clients is None:
            self._clients = _AlpacaClients()
        return self._clients

    def _get_trading_client(self) -> Any:
        clients = self._get_clients()
        if clients.trading is None:
            TradingClient = _alpaca_import("alpaca.trading.client.TradingClient")
            api_key, secret_key = self._credentials()
            clients.trading = TradingClient(
                api_key=api_key,
                secret_key=secret_key,
                paper=True,
            )
        return clients.trading

    def _get_data_client(self) -> Any:
        clients = self._get_clients()
        if clients.data is None:
            StockHistoricalDataClient = _alpaca_import(
                "alpaca.data.historical.stock.StockHistoricalDataClient"
            )
            api_key, secret_key = self._credentials()
            clients.data = StockHistoricalDataClient(
                api_key=api_key,
                secret_key=secret_key,
            )
        return clients.data

    def resolve_account(self, account_label: str | None = None) -> ResolvedBrokerAccount:
        label = account_label or "main"
        if label != "main":
            raise BrokerValidationError(
                f"alpaca-paper does not support account selection: {label}"
            )
        return ResolvedBrokerAccount(label=label)

    def get_account_snapshot(
        self,
        account: ResolvedBrokerAccount | None = None,
        *,
        include_quotes: bool = True,
    ) -> AccountSnapshot:
        resolved = account or self.resolve_account()
        trading = self._get_trading_client()
        account_obj = trading.get_account()
        positions: list[Position] = []
        for pos in trading.get_all_positions():
            qty = int(float(pos.qty))
            price = _as_float(getattr(pos, "current_price", None))
            market_value = _as_float(getattr(pos, "market_value", None))
            positions.append(
                Position(
                    symbol=f"{_strip_market(pos.symbol)}.US",
                    quantity=qty,
                    last_price=price,
                    estimated_value=market_value if market_value > 0 else qty * price,
                    env="paper",
                )
            )
        return AccountSnapshot(
            env="paper",
            cash_usd=_as_float(getattr(account_obj, "cash", None)),
            positions=positions,
            total_portfolio_value=_as_float(
                getattr(account_obj, "portfolio_value", None)
            ),
            base_currency="USD",
        )

    def get_quotes(
        self, symbols: list[str], *, include_depth: bool = False
    ) -> dict[str, Quote]:
        data_client = self._get_data_client()
        StockLatestTradeRequest = _alpaca_import(
            "alpaca.data.requests.StockLatestTradeRequest"
        )
        StockLatestQuoteRequest = _alpaca_import(
            "alpaca.data.requests.StockLatestQuoteRequest"
        )

        request_symbols = [_strip_market(symbol) for symbol in symbols]
        trades = data_client.get_stock_latest_trade(
            StockLatestTradeRequest(symbol_or_symbols=request_symbols)
        )
        quotes_payload: dict[str, Any] = {}
        if include_depth:
            quotes_payload = data_client.get_stock_latest_quote(
                StockLatestQuoteRequest(symbol_or_symbols=request_symbols)
            )

        results: dict[str, Quote] = {}
        for raw_symbol in request_symbols:
            trade = trades[raw_symbol]
            quote_payload = quotes_payload.get(raw_symbol) if include_depth else None
            symbol = f"{raw_symbol}.US"
            results[symbol] = Quote(
                symbol=symbol,
                price=_as_float(getattr(trade, "price", None)),
                timestamp=str(getattr(trade, "timestamp", "")),
                bid=_as_float(getattr(quote_payload, "bid_price", None))
                if quote_payload
                else None,
                ask=_as_float(getattr(quote_payload, "ask_price", None))
                if quote_payload
                else None,
                daily_volume=None,
            )
        return results

    def lot_size(self, symbol: str) -> int:
        return 1

    def submit_order(self, request: BrokerOrderRequest) -> BrokerOrderRecord:
        resolved = request.account or self.resolve_account()
        trading = self._get_trading_client()
        side = _alpaca_side(request.side)
        tif = _alpaca_tif(request.time_in_force)
        if request.order_type == "LIMIT":
            LimitOrderRequest = _alpaca_import("alpaca.trading.requests.LimitOrderRequest")
            order_req = LimitOrderRequest(
                symbol=_strip_market(request.symbol),
                qty=request.quantity,
                side=side,
                time_in_force=tif,
                limit_price=request.limit_price,
                client_order_id=request.client_order_id,
                extended_hours=request.extended_hours,
            )
        else:
            MarketOrderRequest = _alpaca_import(
                "alpaca.trading.requests.MarketOrderRequest"
            )
            order_req = MarketOrderRequest(
                symbol=_strip_market(request.symbol),
                qty=request.quantity,
                side=side,
                time_in_force=tif,
                client_order_id=request.client_order_id,
                extended_hours=request.extended_hours,
            )
        order = trading.submit_order(order_req)
        return self.get_order(str(order.id), resolved)

    def get_order(
        self,
        broker_order_id: str,
        account: ResolvedBrokerAccount | None = None,
    ) -> BrokerOrderRecord:
        resolved = account or self.resolve_account()
        order = self._get_trading_client().get_order_by_id(broker_order_id)
        status = str(getattr(order, "status", "new")).upper()
        qty = _as_float(getattr(order, "qty", None))
        filled_qty = _as_float(getattr(order, "filled_qty", None))
        return BrokerOrderRecord(
            broker_order_id=str(getattr(order, "id", broker_order_id)),
            symbol=f"{_strip_market(getattr(order, 'symbol', ''))}.US",
            side=str(getattr(order, "side", "")).upper(),
            quantity=qty,
            filled_quantity=filled_qty,
            remaining_quantity=max(0.0, qty - filled_qty),
            status=status,
            broker_name=self.backend_name,
            account_label=resolved.label,
            client_order_id=getattr(order, "client_order_id", None),
            avg_fill_price=_as_float(getattr(order, "filled_avg_price", None))
            or None,
            submitted_at=str(getattr(order, "submitted_at", "")),
            updated_at=str(
                getattr(order, "updated_at", None) or getattr(order, "submitted_at", "")
            ),
            raw={"status": status},
        )

    def list_open_orders(
        self,
        account: ResolvedBrokerAccount | None = None,
    ) -> list[BrokerOrderRecord]:
        resolved = account or self.resolve_account()
        orders = self._get_trading_client().get_orders()
        open_statuses = {"NEW", "ACCEPTED", "PENDING_NEW", "PARTIALLY_FILLED"}
        results: list[BrokerOrderRecord] = []
        for order in orders:
            record = self.get_order(str(order.id), resolved)
            if record.status in open_statuses:
                results.append(record)
        return results

    def cancel_order(
        self,
        broker_order_id: str,
        account: ResolvedBrokerAccount | None = None,
    ) -> None:
        self._get_trading_client().cancel_order_by_id(broker_order_id)

    def list_fills(
        self,
        account: ResolvedBrokerAccount | None = None,
        *,
        broker_order_id: str | None = None,
    ) -> list[BrokerFillRecord]:
        resolved = account or self.resolve_account()
        if broker_order_id is None:
            return []
        order = self._get_trading_client().get_order_by_id(broker_order_id)
        filled_qty = _as_float(getattr(order, "filled_qty", None))
        filled_avg = _as_float(getattr(order, "filled_avg_price", None))
        if filled_qty <= 0 or filled_avg <= 0:
            return []
        return [
            BrokerFillRecord(
                fill_id=f"{broker_order_id}-fill",
                broker_order_id=broker_order_id,
                symbol=f"{_strip_market(getattr(order, 'symbol', ''))}.US",
                quantity=filled_qty,
                price=filled_avg,
                broker_name=self.backend_name,
                account_label=resolved.label,
                filled_at=str(getattr(order, "updated_at", "")),
                raw={"status": str(getattr(order, "status", "")).upper()},
            )
        ]

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
            open_orders=open_orders,
            fills=fills,
        )
