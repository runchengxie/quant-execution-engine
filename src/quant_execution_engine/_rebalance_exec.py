"""RebalanceService execution layer.

Builds on :class:`RebalancePlanMixin`: order execution through
:class:`OrderLifecycleService` and audit-log persistence.
"""

from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path

from ._rebalance_plan import RebalancePlanMixin
from .execution import OrderLifecycleService
from .logging import get_logger, get_run_id
from .models import Order, RebalanceResult
from .risk import summarize_risk_decisions

logger = get_logger(__name__)


class RebalanceExecutionMixin(RebalancePlanMixin):
    """Order execution + audit-log persistence (execution layer)."""

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

    def save_audit_log(self, rebalance_result: RebalanceResult, dry_run: bool = True) -> Path:
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
            all_risk_decisions = [
                decision
                for order in rebalance_result.orders
                for decision in (order.risk_decisions or [])
            ]
            risk_decision_summary = summarize_risk_decisions(all_risk_decisions).to_payload()
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
                "risk_decision_summary": risk_decision_summary,
            }
            f.write(json.dumps(summary, ensure_ascii=False) + "\n")
            for order in rebalance_result.orders:
                order_risk_decision_summary = summarize_risk_decisions(
                    list(order.risk_decisions or [])
                ).to_payload()
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
                    "risk_decision_summary": order_risk_decision_summary,
                    "timestamp": order.timestamp.isoformat() if order.timestamp else None,
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

        rebalance_result.audit_log_path = str(log_file)
        logger.info("审计日志已保存", extra={"log_file": str(log_file)})
        return log_file
