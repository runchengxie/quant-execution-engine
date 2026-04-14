"""Rebalancing service

Provides rebalancing-related business logic, including plan generation and execution.
"""

import json
from datetime import datetime
from decimal import ROUND_HALF_UP, Decimal
from pathlib import Path
from typing import Any

from .account import get_quotes
from .broker.base import BrokerAdapter
from .broker.factory import get_broker_adapter, resolve_broker_name, resolve_default_account_label
from .broker.longport import LongPortClient, _to_lb_symbol
from .config import load_cfg
from .execution import OrderLifecycleService
from .fees import FeeSchedule, estimate_fees
from .logging import get_logger, get_run_id
from .models import AccountSnapshot, Order, Position, RebalanceResult
from .targets import TargetEntry

logger = get_logger(__name__)


class RebalanceService:
    """Rebalancing service class"""

    def __init__(
        self,
        env: str = "real",
        client: LongPortClient | BrokerAdapter | None = None,
        *,
        broker_name: str | None = None,
        account_label: str | None = None,
    ):
        self.env = env
        self.client = client
        self.broker_name = resolve_broker_name(broker_name)
        self.account_label = resolve_default_account_label(account_label)
        self._last_reconcile_report = None

    def _get_client(self) -> Any:
        """Get client instance"""
        if not self.client:
            self.client = get_broker_adapter(broker_name=self.broker_name)
        return self.client

    def _get_adapter(self) -> BrokerAdapter:
        return get_broker_adapter(
            broker_name=self.broker_name,
            client=self._get_client(),
        )

    def close(self):
        """Close client connection"""
        if self.client:
            close_fn = getattr(self.client, "close", None)
            if callable(close_fn):
                close_fn()
            self.client = None

    @staticmethod
    def _coerce_lb_symbol(target: str | TargetEntry) -> str:
        if isinstance(target, TargetEntry):
            return _to_lb_symbol(target.symbol, market=target.market)
        return _to_lb_symbol(str(target).upper().strip())

    def _fetch_quotes(self, targets: list[str] | list[TargetEntry]) -> dict[str, float]:
        """Fetch quotes for given tickers or canonical targets."""
        lb_symbols = [self._coerce_lb_symbol(target) for target in targets]
        quote_objs = get_quotes(
            lb_symbols,
            client=self._get_client(),
            broker_name=self.broker_name,
        )
        return {sym: q.price for sym, q in quote_objs.items()}

    def _compute_effective_total(
        self,
        account_snapshot: AccountSnapshot,
        quotes: dict[str, float],
        target_gross_exposure: float,
    ) -> float:
        """Compute effective total portfolio value after applying exposure."""
        total_pos_value_recomp = 0.0
        any_zero_priced = False
        for pos in account_snapshot.positions:
            px = float(quotes.get(pos.symbol, 0.0) or 0.0)
            if px <= 0:
                px = float(pos.last_price or 0.0)
            if px <= 0 and pos.quantity > 0:
                any_zero_priced = True
                if float(pos.estimated_value or 0.0) > 0 and pos.quantity > 0:
                    try:
                        px = float(pos.estimated_value) / float(pos.quantity)
                    except Exception:
                        px = 0.0
            val = px * float(pos.quantity)
            if val <= 0 and float(pos.estimated_value or 0.0) > 0:
                val = float(pos.estimated_value)
            total_pos_value_recomp += val

        cash_usd = float(account_snapshot.cash_usd or 0.0)
        recomputed_total = cash_usd + float(total_pos_value_recomp)

        snapshot_total = float(account_snapshot.total_portfolio_value or 0.0)

        def _close(a: float, b: float) -> bool:
            if a <= 0 and b <= 0:
                return True
            denom = max(1.0, abs(b))
            return abs(a - b) <= 0.01 * denom

        if (
            snapshot_total > 0
            and _close(snapshot_total, recomputed_total)
            and not any_zero_priced
        ):
            effective_total = snapshot_total
        else:
            effective_total = recomputed_total

        exposure = max(0.0, float(target_gross_exposure))
        return effective_total * exposure

    def _build_order(
        self,
        lb_symbol: str,
        price: float,
        current_qty: int,
        target_qty_raw: float,
        allow_fractional: bool,
        client: Any,
        fs: FeeSchedule,
        frac_enable: bool,
        frac_step: Decimal,
    ) -> tuple[Position, Order | None]:
        """Build target position and corresponding order for a symbol."""
        lot_size = client.lot_size(lb_symbol)
        target_qty = (int(target_qty_raw) // lot_size) * lot_size
        target_qty_frac = Decimal(0)
        if price > 0 and frac_enable:
            target_qty_frac = Decimal(str(target_qty_raw)).quantize(
                frac_step, rounding=ROUND_HALF_UP
            )
        target_position = Position(
            symbol=lb_symbol,
            quantity=target_qty,
            last_price=price,
            estimated_value=target_qty * price,
            env=self.env,
        )

        delta_qty = target_qty - current_qty
        if abs(delta_qty) < lot_size:
            logger.info(
                f"跳过 {lb_symbol}：差额 {delta_qty} 小于最小交易单位 {lot_size}"
            )
            return target_position, None

        side = "BUY" if delta_qty > 0 else "SELL"
        qty_to_trade = abs(delta_qty)
        order = Order(
            symbol=lb_symbol,
            quantity=qty_to_trade,
            side=side,
            price=price,
            order_type="MARKET",
        )
        est_fee, frac_hint = estimate_fees(
            side=side,
            qty_int=qty_to_trade,
            price=price,
            any_fractional_lt1=(target_qty_frac > 0 and target_qty_frac < 1),
            fs=fs,
        )
        order.est_fees = est_fee
        order.est_frac_hint = frac_hint
        if frac_enable:
            order.target_qty_frac = float(target_qty_frac)
            order.rounded_target_qty = int(target_qty)
            order.rounding_loss = float(target_qty_frac - Decimal(int(target_qty)))

        return target_position, order

    def plan_rebalance(
        self,
        targets: list[TargetEntry],
        account_snapshot: AccountSnapshot,
        quotes: dict[str, float] | None = None,
        allow_fractional: bool = False,
        target_gross_exposure: float = 1.0,
    ) -> RebalanceResult:
        """Create rebalancing plan

        Args:
            targets: Canonical target entries
            account_snapshot: Current account snapshot

        Returns:
            RebalanceResult: Rebalancing plan result
        """
        if not targets:
            raise ValueError("目标列表不能为空")

        if quotes is None:
            try:
                quotes = self._fetch_quotes(targets)
            except Exception as e:
                logger.error(f"获取报价失败: {e}")
                raise

        weighted_targets = [target for target in targets if target.target_weight is not None]

        effective_total = self._compute_effective_total(
            account_snapshot, quotes, target_gross_exposure
        )
        target_value_per_stock = (
            effective_total / len(weighted_targets) if weighted_targets else 0.0
        )

        # Build current position mapping
        current_positions_map = {pos.symbol: pos for pos in account_snapshot.positions}

        # Generate rebalancing orders
        orders = []
        target_positions = []

        client = self._get_client()
        cfg = load_cfg() or {}
        fees_cfg = (cfg.get("fees") or {}) if isinstance(cfg, dict) else {}
        fs = FeeSchedule(
            commission=float(fees_cfg.get("commission", 0.0) or 0.0),
            platform_per_share=float(fees_cfg.get("platform_per_share", 0.005) or 0.0),
            fractional_pct_lt1=float(fees_cfg.get("fractional_pct_lt1", 0.012) or 0.0),
            fractional_cap_lt1=float(fees_cfg.get("fractional_cap_lt1", 0.99) or 0.0),
            sell_reg_fees_bps=float(fees_cfg.get("sell_reg_fees_bps", 0.0) or 0.0),
        )
        frac_cfg = (
            (cfg.get("fractional_preview") or {}) if isinstance(cfg, dict) else {}
        )
        frac_enable = bool(frac_cfg.get("enable", True))
        frac_step = Decimal(str(frac_cfg.get("default_step", 0.001)))

        for target in targets:
            lb_symbol = self._coerce_lb_symbol(target)
            symbol = target.symbol

            px = (quotes or {}).get(lb_symbol)
            if not px or px <= 0:
                logger.warning(f"跳过 {symbol}：无有效价格")
                continue

            price = float(px)
            current_position = current_positions_map.get(lb_symbol)
            current_qty = current_position.quantity if current_position else 0
            if target.target_quantity is not None:
                target_qty_raw = float(target.target_quantity)
            else:
                target_qty_raw = (
                    effective_total * float(target.target_weight or 0.0) / price
                )

            target_position, order = self._build_order(
                lb_symbol,
                price,
                current_qty,
                target_qty_raw,
                allow_fractional,
                client,
                fs,
                frac_enable,
                frac_step,
            )
            target_positions.append(target_position)
            if order:
                orders.append(order)

        # Handle existing positions not in target list: liquidate (treat target as 0)
        target_set = {self._coerce_lb_symbol(target) for target in targets}
        for sym, cur in current_positions_map.items():
            if sym in target_set:
                continue
            current_qty = int(cur.quantity)
            if current_qty <= 0:
                continue
            lot_size = client.lot_size(sym)
            # Round to lot
            qty_to_sell = (current_qty // lot_size) * lot_size
            if qty_to_sell <= 0:
                continue
            # Use existing quotes
            px = float((quotes or {}).get(sym, cur.last_price or 0.0))
            # Add 0 row to target positions for diff view
            target_positions.append(
                Position(
                    symbol=sym,
                    quantity=0,
                    last_price=px,
                    estimated_value=0.0,
                    env=self.env,
                )
            )
            o = Order(
                symbol=sym,
                quantity=qty_to_sell,
                side="SELL",
                price=px if px > 0 else None,
                order_type="MARKET",
            )
            est_fee, frac_hint = estimate_fees(
                side="SELL",
                qty_int=qty_to_sell,
                price=px or 0.0,
                any_fractional_lt1=False,
                fs=fs,
            )
            o.est_fees = est_fee
            o.est_frac_hint = frac_hint
            orders.append(o)

        return RebalanceResult(
            target_positions=target_positions,
            current_positions=account_snapshot.positions,
            orders=orders,
            total_portfolio_value=effective_total,
            target_value_per_stock=target_value_per_stock,
            env=self.env,
            broker_name=self.broker_name,
            account_label=self.account_label,
        )

    def execute_orders(
        self,
        orders: list[Order],
        dry_run: bool = True,
        *,
        target_source: str | None = None,
        target_asof: str | None = None,
        target_input_path: str | None = None,
    ) -> list[Order]:
        """Execute order list

        Args:
            orders: Order list
            dry_run: Whether in dry run mode

        Returns:
            List[Order]: Order list updated with execution results
        """
        if not orders:
            return []

        lifecycle = OrderLifecycleService(self._get_adapter())
        try:
            executed_orders = lifecycle.execute_orders(
                orders,
                account_label=self.account_label,
                dry_run=dry_run,
                target_source=target_source,
                target_asof=target_asof,
                target_input_path=target_input_path,
            )
            self._last_reconcile_report = lifecycle.last_reconcile_report
            return executed_orders
        except Exception as e:
            logger.error("执行订单失败: %s", e)
            for order in orders:
                order.status = "FAILED"
                order.error_message = str(e)
            return orders

    def save_audit_log(
        self, rebalance_result: RebalanceResult, dry_run: bool = True
    ) -> Path:
        """Save audit log

        Args:
            rebalance_result: Rebalancing result
            dry_run: Whether in dry run mode

        Returns:
            Path: Log file path
        """
        log_dir = Path("outputs/orders")
        log_dir.mkdir(parents=True, exist_ok=True)

        timestamp = datetime.now().strftime("%Y%m%d-%H%M%S")
        mode = "dry" if dry_run else "live"
        log_file = log_dir / f"{timestamp}_{self.env}_{mode}.jsonl"

        with open(log_file, "w", encoding="utf-8") as f:
            run_id = get_run_id()
            summary = {
                "record_type": "rebalance_summary",
                "env": self.env,
                "dry_run": dry_run,
                "broker_name": rebalance_result.broker_name,
                "account_label": rebalance_result.account_label,
                "run_id": run_id,
                "target_source": rebalance_result.target_source,
                "target_asof": rebalance_result.target_asof,
                "target_input_path": rebalance_result.target_input_path,
                "order_count": len(rebalance_result.orders),
                "reconcile_warnings": list(rebalance_result.reconcile_warnings or []),
            }
            f.write(json.dumps(summary, ensure_ascii=False) + "\n")
            for order in rebalance_result.orders:
                order_dict = {
                    "record_type": "order",
                    "symbol": order.symbol,
                    "quantity": order.quantity,
                    "side": order.side,
                    "price": order.price,
                    "status": order.status,
                    "order_id": order.order_id,
                    "broker_order_id": order.broker_order_id,
                    "client_order_id": order.client_order_id,
                    "broker_status": order.broker_status,
                    "intent_id": order.intent_id,
                    "parent_order_id": order.parent_order_id,
                    "child_order_id": order.child_order_id,
                    "filled_quantity": order.filled_quantity,
                    "remaining_quantity": order.remaining_quantity,
                    "avg_fill_price": order.avg_fill_price,
                    "reconcile_status": order.reconcile_status,
                    "risk_summary": order.risk_summary,
                    "risk_decisions": list(order.risk_decisions or []),
                    "timestamp": order.timestamp.isoformat()
                    if order.timestamp
                    else None,
                    "error_message": order.error_message,
                    "env": self.env,
                    "dry_run": dry_run,
                    "broker_name": rebalance_result.broker_name,
                    "account_label": rebalance_result.account_label,
                    "run_id": run_id,
                    "target_source": rebalance_result.target_source,
                    "target_asof": rebalance_result.target_asof,
                    "target_input_path": rebalance_result.target_input_path,
                }
                f.write(json.dumps(order_dict, ensure_ascii=False) + "\n")

            report = self._last_reconcile_report
            if report is not None:
                reconcile_dict = {
                    "record_type": "reconcile",
                    "broker_name": report.broker_name,
                    "account_label": report.account_label,
                    "fetched_at": report.fetched_at,
                    "open_order_count": len(report.open_orders),
                    "fill_count": len(report.fills),
                    "warnings": list(report.warnings),
                    "run_id": run_id,
                }
                f.write(json.dumps(reconcile_dict, ensure_ascii=False) + "\n")

        logger.info("审计日志已保存", extra={"log_file": str(log_file)})
        return log_file
