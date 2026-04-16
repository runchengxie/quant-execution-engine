"""IBKR paper broker adapter."""

from __future__ import annotations

from datetime import datetime, timezone
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
    utc_now_iso,
)
from .ibkr_runtime import IbkrRuntime, coerce_iso


def _as_float(value: Any) -> float:
    if value in (None, ""):
        return 0.0
    return float(value)


def _trade_status(value: Any) -> str:
    normalized = str(value or "").strip().upper()
    mapping = {
        "APIPENDING": "PENDING_NEW",
        "PENDINGSUBMIT": "PENDING_NEW",
        "PRESUBMITTED": "NEW",
        "SUBMITTED": "ACCEPTED",
        "PENDINGCANCEL": "PENDING_CANCEL",
        "APICANCELLED": "CANCELED",
        "CANCELLED": "CANCELED",
        "FILLED": "FILLED",
        "INACTIVE": "REJECTED",
    }
    return mapping.get(normalized, normalized or "NEW")


def _ticker_price(ticker: Any) -> float:
    market_price = getattr(ticker, "marketPrice", None)
    if callable(market_price):
        try:
            price = float(market_price())
            if price > 0:
                return price
        except Exception:
            pass
    for attr in ("last", "close", "bid", "ask"):
        try:
            price = float(getattr(ticker, attr, 0) or 0)
        except Exception:
            continue
        if price > 0:
            return price
    return 0.0


def _fill_side(value: Any) -> str:
    normalized = str(value or "").strip().upper()
    return {
        "BOT": "BUY",
        "BUY": "BUY",
        "SLD": "SELL",
        "SELL": "SELL",
    }.get(normalized, normalized or "BUY")


def _time_or_now(value: Any) -> str:
    if value in (None, ""):
        return utc_now_iso()
    return coerce_iso(value)


class IbkrPaperBrokerAdapter(BrokerAdapter):
    """Adapter backed by IBKR paper trading through IB Gateway."""

    backend_name = "ibkr-paper"
    capabilities = BrokerCapabilityMatrix(
        name="ibkr-paper",
        supports_live_submit=True,
        supports_cancel=True,
        supports_order_query=True,
        supports_open_order_listing=True,
        supports_reconcile=True,
        supports_account_selection=False,
        supports_fractional=False,
        supports_short=False,
        supports_extended_hours=True,
        supported_order_types=("MARKET", "LIMIT"),
        supported_time_in_force=("DAY", "GTC"),
        notes={
            "mode": "paper",
            "submit_mode": "paper",
            "runtime": "IB Gateway via TWS API",
            "market_scope": "US equities only",
        },
    )

    def __init__(self, client: IbkrRuntime | None = None) -> None:
        self.client = client or IbkrRuntime()

    def resolve_account(self, account_label: str | None = None) -> ResolvedBrokerAccount:
        label = str(account_label or "main").strip() or "main"
        if label != "main":
            raise BrokerValidationError(
                f"{self.backend_name} does not support switching broker accounts via --account: {label}"
            )
        broker_account_id = self.client.resolve_account_id()
        metadata = {"runtime": "IB Gateway via TWS API", "scope": "US equities only"}
        if broker_account_id:
            metadata["broker_account_id"] = broker_account_id
        return ResolvedBrokerAccount(
            label=label,
            broker_account_id=broker_account_id,
            metadata=metadata,
        )

    def _account_id(self, account: ResolvedBrokerAccount | None) -> str | None:
        if account is not None and account.broker_account_id:
            return account.broker_account_id
        return self.client.resolve_account_id()

    def get_account_snapshot(
        self,
        account: ResolvedBrokerAccount | None = None,
        *,
        include_quotes: bool = True,
    ) -> AccountSnapshot:
        resolved = account or self.resolve_account()
        account_id = self._account_id(resolved)
        account_values = self.client.get_account_values(account_id)
        positions_raw = self.client.get_positions(account_id)

        quotes_by_symbol: dict[str, Quote] = {}
        supported_symbols: list[str] = []
        for position in positions_raw:
            canonical = self.client.canonical_symbol_for_contract(
                getattr(position, "contract", None)
            )
            if canonical is None:
                continue
            if float(getattr(position, "position", 0) or 0) <= 0:
                continue
            supported_symbols.append(canonical)
        if include_quotes and supported_symbols:
            quotes_by_symbol = self.get_quotes(list(dict.fromkeys(supported_symbols)))

        positions: list[Position] = []
        for position in positions_raw:
            contract = getattr(position, "contract", None)
            canonical = self.client.canonical_symbol_for_contract(contract)
            quantity = int(float(getattr(position, "position", 0) or 0))
            if canonical is None or quantity <= 0:
                continue
            quote = quotes_by_symbol.get(canonical)
            last_price = (
                float(quote.price)
                if quote is not None and float(quote.price) > 0
                else _as_float(getattr(position, "avgCost", None))
            )
            positions.append(
                Position(
                    symbol=canonical,
                    quantity=quantity,
                    last_price=last_price,
                    estimated_value=float(quantity) * float(last_price or 0.0),
                    env="paper",
                )
            )

        cash_usd = 0.0
        total_portfolio_value = 0.0
        base_currency = "USD"
        for value in account_values:
            tag = str(getattr(value, "tag", "")).strip()
            currency = str(getattr(value, "currency", "")).strip().upper()
            if tag == "TotalCashValue" and currency in {"", "USD"}:
                raw_value = _as_float(getattr(value, "value", None))
                cash_usd = raw_value
            if tag == "NetLiquidation" and currency in {"", "USD"}:
                raw_value = _as_float(getattr(value, "value", None))
                total_portfolio_value = raw_value
                base_currency = currency or base_currency

        return AccountSnapshot(
            env="paper",
            cash_usd=cash_usd,
            positions=positions,
            total_portfolio_value=total_portfolio_value,
            base_currency=base_currency,
        )

    def get_quotes(
        self, symbols: list[str], *, include_depth: bool = False
    ) -> dict[str, Quote]:
        tickers = self.client.request_tickers(symbols)
        results: dict[str, Quote] = {}
        for canonical, ticker in tickers.items():
            time_value = (
                getattr(ticker, "time", None)
                or getattr(ticker, "rtTime", None)
                or datetime.now(timezone.utc)
            )
            results[canonical] = Quote(
                symbol=canonical,
                price=_ticker_price(ticker),
                timestamp=coerce_iso(time_value),
                bid=_as_float(getattr(ticker, "bid", None)) if include_depth else None,
                ask=_as_float(getattr(ticker, "ask", None)) if include_depth else None,
                daily_volume=_as_float(getattr(ticker, "volume", None))
                if include_depth
                else None,
            )
        return results

    def lot_size(self, symbol: str) -> int:
        self.client.normalize_symbol(symbol)
        return 1

    def _trade_to_record(
        self,
        trade: Any,
        account: ResolvedBrokerAccount,
        *,
        canonical_symbol: str | None = None,
    ) -> BrokerOrderRecord:
        order = getattr(trade, "order", None)
        order_status = getattr(trade, "orderStatus", None)
        contract = getattr(trade, "contract", None)
        raw_symbol = canonical_symbol or self.client.canonical_symbol_for_contract(contract)
        if raw_symbol is None:
            raw_symbol = self.client.normalize_symbol(getattr(contract, "symbol", ""))
        quantity = _as_float(getattr(order, "totalQuantity", None))
        filled_quantity = _as_float(getattr(order_status, "filled", None))
        if filled_quantity <= 0:
            fills = getattr(trade, "fills", None) or []
            filled_quantity = sum(
                _as_float(getattr(getattr(fill, "execution", None), "shares", None))
                for fill in fills
            )
        remaining_quantity = _as_float(getattr(order_status, "remaining", None))
        if remaining_quantity <= 0 and quantity > 0:
            remaining_quantity = max(0.0, quantity - filled_quantity)
        submitted_at = utc_now_iso()
        updated_at = submitted_at
        saw_log_time = False
        for entry in getattr(trade, "log", None) or []:
            entry_time = getattr(entry, "time", None)
            normalized = _time_or_now(entry_time)
            if not saw_log_time:
                submitted_at = normalized
                saw_log_time = True
            updated_at = normalized
        message = (
            str(getattr(order_status, "warningText", "")).strip()
            or str(getattr(trade, "advancedError", "")).strip()
            or None
        )
        return BrokerOrderRecord(
            broker_order_id=str(getattr(order, "orderId", "")),
            symbol=raw_symbol,
            side=str(getattr(order, "action", "")).strip().upper(),
            quantity=quantity,
            filled_quantity=filled_quantity,
            remaining_quantity=remaining_quantity,
            status=_trade_status(getattr(order_status, "status", None)),
            broker_name=self.backend_name,
            account_label=account.label,
            client_order_id=str(getattr(order, "orderRef", "")).strip() or None,
            avg_fill_price=_as_float(getattr(order_status, "avgFillPrice", None)) or None,
            submitted_at=submitted_at,
            updated_at=updated_at,
            message=message,
            raw={
                "time_in_force": str(getattr(order, "tif", "")).strip() or None,
                "outside_rth": bool(getattr(order, "outsideRth", False)),
            },
        )

    def submit_order(self, request: BrokerOrderRequest) -> BrokerOrderRecord:
        resolved = request.account or self.resolve_account()
        canonical, contract = self.client.qualify_stock(request.symbol)
        trade = self.client.submit_order(
            contract,
            request,
            account_id=self._account_id(resolved),
        )
        return self._trade_to_record(trade, resolved, canonical_symbol=canonical)

    def get_order(
        self,
        broker_order_id: str,
        account: ResolvedBrokerAccount | None = None,
    ) -> BrokerOrderRecord:
        resolved = account or self.resolve_account()
        try:
            trade = self.client.get_trade(broker_order_id)
        except Exception:
            fills = self.list_fills(resolved, broker_order_id=broker_order_id)
            if not fills:
                raise
            aggregate_qty = sum(fill.quantity for fill in fills)
            avg_fill = sum(fill.quantity * fill.price for fill in fills) / aggregate_qty
            return BrokerOrderRecord(
                broker_order_id=str(broker_order_id),
                symbol=fills[0].symbol,
                side=_fill_side(fills[0].raw.get("side", "BUY")),
                quantity=aggregate_qty,
                filled_quantity=aggregate_qty,
                remaining_quantity=0.0,
                status="FILLED",
                broker_name=self.backend_name,
                account_label=resolved.label,
                avg_fill_price=avg_fill,
                submitted_at=fills[0].filled_at,
                updated_at=fills[-1].filled_at,
            )
        return self._trade_to_record(trade, resolved)

    def list_open_orders(
        self,
        account: ResolvedBrokerAccount | None = None,
    ) -> list[BrokerOrderRecord]:
        resolved = account or self.resolve_account()
        results: list[BrokerOrderRecord] = []
        for trade in self.client.list_open_trades(self._account_id(resolved)):
            record = self._trade_to_record(trade, resolved)
            if record.status in {
                "NEW",
                "ACCEPTED",
                "PENDING_NEW",
                "PENDING_CANCEL",
                "PARTIALLY_FILLED",
            }:
                results.append(record)
        return results

    def cancel_order(
        self,
        broker_order_id: str,
        account: ResolvedBrokerAccount | None = None,
    ) -> None:
        _ = account or self.resolve_account()
        self.client.cancel_order(broker_order_id)

    def list_fills(
        self,
        account: ResolvedBrokerAccount | None = None,
        *,
        broker_order_id: str | None = None,
    ) -> list[BrokerFillRecord]:
        resolved = account or self.resolve_account()
        account_id = self._account_id(resolved)
        fills_raw = self.client.list_fills(
            account_id=account_id,
            broker_order_id=broker_order_id,
        )
        fills: list[BrokerFillRecord] = []
        for index, fill in enumerate(fills_raw, start=1):
            contract = getattr(fill, "contract", None)
            execution = getattr(fill, "execution", None)
            if contract is None or execution is None:
                continue
            canonical = self.client.canonical_symbol_for_contract(contract)
            if canonical is None:
                continue
            fill_id = str(getattr(execution, "execId", "")).strip() or (
                f"{getattr(execution, 'orderId', '')}-fill-{index}"
            )
            fills.append(
                BrokerFillRecord(
                    fill_id=fill_id,
                    broker_order_id=str(getattr(execution, "orderId", "")).strip(),
                    symbol=canonical,
                    quantity=_as_float(getattr(execution, "shares", None)),
                    price=_as_float(getattr(execution, "price", None)),
                    broker_name=self.backend_name,
                    account_label=resolved.label,
                    filled_at=_time_or_now(
                        getattr(fill, "time", None)
                        or getattr(execution, "time", None)
                    ),
                    raw={
                        "exchange": str(getattr(execution, "exchange", "")).strip(),
                        "side": _fill_side(getattr(execution, "side", None)),
                    },
                )
            )
        return fills

    def reconcile(
        self,
        account: ResolvedBrokerAccount | None = None,
    ) -> BrokerReconcileReport:
        resolved = account or self.resolve_account()
        open_orders = self.list_open_orders(resolved)
        fills = self.list_fills(resolved)
        return BrokerReconcileReport(
            broker_name=self.backend_name,
            account_label=resolved.label,
            open_orders=open_orders,
            fills=fills,
        )

    def close(self) -> None:
        self.client.close()
