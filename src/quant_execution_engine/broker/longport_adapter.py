"""Broker adapters backed by the LongPort SDK wrapper."""

from __future__ import annotations

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
from .longport import LongPortClient, _coerce_iso, _enum_value, _normalize_order_status
from ..fx import to_usd
from ..models import AccountSnapshot, Position, Quote


class _BaseLongPortBrokerAdapter(BrokerAdapter):
    """Shared LongPort adapter behavior for real and paper backends."""

    client_env = "real"
    snapshot_env = "real"

    def __init__(self, client: LongPortClient | None = None) -> None:
        self.client = client or LongPortClient(env=self.client_env)

    def resolve_account(self, account_label: str | None = None) -> ResolvedBrokerAccount:
        label = str(account_label or "main").strip() or "main"
        if label != "main":
            raise BrokerValidationError(
                f"{self.backend_name} does not support switching broker accounts via --account: {label}"
            )
        return ResolvedBrokerAccount(label=label)

    def get_account_snapshot(
        self,
        account: ResolvedBrokerAccount | None = None,
        *,
        include_quotes: bool = True,
    ) -> AccountSnapshot:
        resolved = account or self.resolve_account()
        cash_usd, stock_position_map, net_assets, base_ccy = self.client.portfolio_snapshot()
        quotes = (
            self.client.quote_snapshot(list(stock_position_map.keys()))
            if include_quotes and stock_position_map
            else {}
        )
        positions = [
            Position(
                symbol=symbol,
                quantity=int(quantity),
                last_price=float(quotes.get(symbol).price if symbol in quotes else 0.0),
                estimated_value=float(quotes.get(symbol).price if symbol in quotes else 0.0)
                * int(quantity),
                env=self.snapshot_env,
            )
            for symbol, quantity in stock_position_map.items()
        ]
        for symbol, (units, nav, _ccy) in self.client.fund_positions().items():
            positions.append(
                Position(
                    symbol=symbol,
                    quantity=int(units),
                    last_price=float(nav),
                    estimated_value=float(units) * float(nav),
                    env=self.snapshot_env,
                )
            )
        tpv = 0.0
        if net_assets:
            if str(base_ccy).upper() == "USD":
                tpv = float(net_assets)
            else:
                converted = to_usd(float(net_assets), str(base_ccy))
                tpv = float(converted) if converted is not None else 0.0
        return AccountSnapshot(
            env=self.snapshot_env,
            cash_usd=float(cash_usd),
            positions=positions,
            total_portfolio_value=tpv,
            base_currency=str(base_ccy).upper() if base_ccy else None,
        )

    def get_quotes(
        self, symbols: list[str], *, include_depth: bool = False
    ) -> dict[str, Quote]:
        return self.client.quote_snapshot(symbols, include_depth=include_depth)

    def lot_size(self, symbol: str) -> int:
        return self.client.lot_size(symbol)

    def submit_order(self, request: BrokerOrderRequest) -> BrokerOrderRecord:
        resolved = request.account or self.resolve_account()
        if request.order_type == "LIMIT":
            response = self.client.submit_limit(
                request.symbol,
                float(request.limit_price or 0.0),
                request.quantity if request.side == "BUY" else -request.quantity,
                remark=request.client_order_id,
            )
        else:
            response = self.client.submit_market(
                request.symbol,
                request.quantity if request.side == "BUY" else -request.quantity,
                remark=request.client_order_id,
            )
        return self.get_order(str(response.order_id), resolved)

    def get_order(
        self,
        broker_order_id: str,
        account: ResolvedBrokerAccount | None = None,
    ) -> BrokerOrderRecord:
        resolved = account or self.resolve_account()
        detail = self.client.get_order_detail(broker_order_id)
        quantity = float(getattr(detail, "quantity", 0) or 0)
        filled_quantity = float(getattr(detail, "executed_quantity", 0) or 0)
        return BrokerOrderRecord(
            broker_order_id=str(getattr(detail, "order_id", broker_order_id)),
            symbol=str(getattr(detail, "symbol", "")),
            side=str(_enum_value(getattr(detail, "side", ""))).upper(),
            quantity=quantity,
            filled_quantity=filled_quantity,
            remaining_quantity=max(0.0, quantity - filled_quantity),
            status=_normalize_order_status(getattr(detail, "status", "")),
            broker_name=self.backend_name,
            account_label=resolved.label,
            client_order_id=str(getattr(detail, "remark", "") or "") or None,
            avg_fill_price=float(getattr(detail, "executed_price", 0) or 0) or None,
            submitted_at=_coerce_iso(getattr(detail, "submitted_at", "")),
            updated_at=_coerce_iso(
                getattr(detail, "updated_at", None) or getattr(detail, "submitted_at", "")
            ),
            message=str(getattr(detail, "msg", "") or "") or None,
            raw={
                "order_type": str(_enum_value(getattr(detail, "order_type", ""))),
                "time_in_force": str(_enum_value(getattr(detail, "time_in_force", ""))),
            },
        )

    def list_open_orders(
        self,
        account: ResolvedBrokerAccount | None = None,
    ) -> list[BrokerOrderRecord]:
        resolved = account or self.resolve_account()
        records: list[BrokerOrderRecord] = []
        for order in self.client.list_orders():
            status = _normalize_order_status(getattr(order, "status", ""))
            if status in {"FILLED", "CANCELED", "REJECTED", "EXPIRED"}:
                continue
            quantity = float(getattr(order, "quantity", 0) or 0)
            filled_quantity = float(getattr(order, "executed_quantity", 0) or 0)
            records.append(
                BrokerOrderRecord(
                    broker_order_id=str(getattr(order, "order_id", "")),
                    symbol=str(getattr(order, "symbol", "")),
                    side=str(_enum_value(getattr(order, "side", ""))).upper(),
                    quantity=quantity,
                    filled_quantity=filled_quantity,
                    remaining_quantity=max(0.0, quantity - filled_quantity),
                    status=status,
                    broker_name=self.backend_name,
                    account_label=resolved.label,
                    client_order_id=str(getattr(order, "remark", "") or "") or None,
                    avg_fill_price=float(getattr(order, "executed_price", 0) or 0)
                    or None,
                    submitted_at=_coerce_iso(getattr(order, "submitted_at", "")),
                    updated_at=_coerce_iso(
                        getattr(order, "updated_at", None)
                        or getattr(order, "submitted_at", "")
                    ),
                    message=str(getattr(order, "msg", "") or "") or None,
                )
            )
        return records

    def cancel_order(
        self,
        broker_order_id: str,
        account: ResolvedBrokerAccount | None = None,
    ) -> None:
        self.client.cancel_order_by_id(broker_order_id)

    def list_fills(
        self,
        account: ResolvedBrokerAccount | None = None,
        *,
        broker_order_id: str | None = None,
    ) -> list[BrokerFillRecord]:
        resolved = account or self.resolve_account()
        executions = self.client.list_executions(order_id=broker_order_id)
        fills: list[BrokerFillRecord] = []
        for execution in executions:
            fills.append(
                BrokerFillRecord(
                    fill_id=str(getattr(execution, "trade_id", "")),
                    broker_order_id=str(getattr(execution, "order_id", "")),
                    symbol=str(getattr(execution, "symbol", "")),
                    quantity=float(getattr(execution, "quantity", 0) or 0),
                    price=float(getattr(execution, "price", 0) or 0),
                    broker_name=self.backend_name,
                    account_label=resolved.label,
                    filled_at=_coerce_iso(getattr(execution, "trade_done_at", "")),
                    raw={},
                )
            )
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
            open_orders=open_orders,
            fills=fills,
        )

    def close(self) -> None:
        self.client.close()


class LongPortBrokerAdapter(_BaseLongPortBrokerAdapter):
    """Real-broker LongPort adapter."""

    backend_name = "longport"
    client_env = "real"
    snapshot_env = "real"
    capabilities = BrokerCapabilityMatrix(
        name="longport",
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
        notes={"account_selection": "single account only", "submit_mode": "real"},
    )


class LongPortPaperBrokerAdapter(_BaseLongPortBrokerAdapter):
    """Paper-trading LongPort adapter."""

    backend_name = "longport-paper"
    client_env = "paper"
    snapshot_env = "paper"
    capabilities = BrokerCapabilityMatrix(
        name="longport-paper",
        supports_live_submit=False,
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
        notes={"account_selection": "single account only", "submit_mode": "paper"},
    )


__all__ = [
    "LongPortBrokerAdapter",
    "LongPortPaperBrokerAdapter",
]
