"""QEE facade for external callers (e.g. intraday-trader).

Provides a clean Python API so callers never need to shell out to ``qexec``.
Designed for long-only, single-account, Alpaca-paper usage.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from .broker.base import BrokerReconcileReport
from .broker.factory import get_broker_adapter
from .logging import get_logger, get_run_id
from .models import Order
from .rebalance import RebalanceService
from .targets import TargetEntry, Targets, read_targets_json, write_targets_json

logger = get_logger(__name__)


@dataclass(slots=True)
class QEEExecutionResult:
    """Structured result returned by :meth:`QEEFacade.execute`."""

    run_id: str
    dry_run: bool
    broker_name: str
    orders: list[Order] = field(default_factory=list)
    target_positions: list[Any] = field(default_factory=list)
    current_positions: list[Any] = field(default_factory=list)
    total_portfolio_value: float = 0.0
    audit_log_path: str = ""
    reconcile_report: BrokerReconcileReport | None = None
    reconcile_warnings: list[str] = field(default_factory=list)
    error: str | None = None

    @property
    def executed(self) -> bool:
        return not self.dry_run and self.error is None

    @property
    def order_count(self) -> int:
        return len(self.orders)

    def to_dict(self) -> dict[str, Any]:
        return {
            "run_id": self.run_id,
            "dry_run": self.dry_run,
            "broker_name": self.broker_name,
            "order_count": self.order_count,
            "total_portfolio_value": self.total_portfolio_value,
            "audit_log_path": self.audit_log_path,
            "error": self.error,
            "reconcile_warnings": list(self.reconcile_warnings),
        }


class QEEFacade:
    """Minimal facade over :class:`RebalanceService` for external callers.

    Usage from intraday-trader::

        from quant_execution_engine.facade import QEEFacade

        facade = QEEFacade(broker_name="alpaca-paper")

        targets = [
            {"symbol": "AAPL", "market": "US", "target_quantity": 10},
        ]
        result = facade.execute(targets, dry_run=True)
        if result.error:
            logger.error("QEE execution failed: %s", result.error)
    """

    def __init__(
        self,
        *,
        broker_name: str = "alpaca-paper",
        account_label: str | None = None,
    ) -> None:
        self.broker_name = broker_name
        self._service = RebalanceService(
            env="paper" if "paper" in broker_name else "real",
            broker_name=broker_name,
            account_label=account_label,
        )

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def execute(
        self,
        targets: list[dict[str, Any]],
        *,
        dry_run: bool = True,
        target_source: str = "intraday-trader",
        target_asof: str | None = None,
        allow_fractional: bool = False,
        target_gross_exposure: float = 1.0,
    ) -> QEEExecutionResult:
        """Execute a list of target entries through the QEE pipeline.

        Args:
            targets: List of dicts, each with ``symbol``, ``market``, and
                     either ``target_weight`` or ``target_quantity``.
            dry_run: If True, plan only without submitting orders.
            target_source: Provenance label for audit trail.
            target_asof: ISO-8601 timestamp for the target snapshot.
        """
        run_id = get_run_id()

        try:
            # 1. Parse targets
            target_entries = _dicts_to_entries(targets)

            # 2. Get account snapshot
            adapter = get_broker_adapter(broker_name=self.broker_name)
            account_snapshot = adapter.get_account_snapshot()

            # 3. Plan rebalance
            rebalance_result = self._service.plan_rebalance(
                target_entries,
                account_snapshot,
                allow_fractional=allow_fractional,
                target_gross_exposure=target_gross_exposure,
            )

            # 4. Execute orders (or dry-run)
            executed_orders = self._service.execute_orders(
                rebalance_result.orders,
                dry_run=dry_run,
                target_source=target_source,
                target_asof=target_asof,
            )

            # 5. Save audit log
            audit_path = self._service.save_audit_log(rebalance_result, dry_run=dry_run)

            # 6. Reconcile
            reconcile_warnings: list[str] = []
            reconcile_report: BrokerReconcileReport | None = None
            try:
                reconcile_report = adapter.reconcile()
            except Exception:
                logger.debug("Reconcile skipped or failed", exc_info=True)

            if reconcile_report:
                reconcile_warnings = _collect_reconcile_warnings(reconcile_report)

            return QEEExecutionResult(
                run_id=run_id,
                dry_run=dry_run,
                broker_name=self.broker_name,
                orders=executed_orders,
                target_positions=list(rebalance_result.target_positions),
                current_positions=list(rebalance_result.current_positions),
                total_portfolio_value=rebalance_result.total_portfolio_value,
                audit_log_path=str(audit_path),
                reconcile_report=reconcile_report,
                reconcile_warnings=reconcile_warnings,
            )

        except Exception as exc:
            logger.error("QEE execution failed: %s", exc)
            return QEEExecutionResult(
                run_id=run_id,
                dry_run=dry_run,
                broker_name=self.broker_name,
                error=str(exc),
            )

    def export_targets_json(
        self,
        targets: Sequence[TargetEntry | dict[str, Any]],
        out_path: Path,
        *,
        source: str = "intraday-trader",
        asof: str | None = None,
        target_gross_exposure: float = 1.0,
        notes: str | None = None,
    ) -> Path:
        """Write canonical targets.json without executing."""
        return write_targets_json(
            out_path=out_path,
            targets=list(targets),
            source=source,
            asof=asof,
            target_gross_exposure=target_gross_exposure,
            notes=notes,
            default_market="US",
        )

    def read_targets_json(self, path: Path) -> Targets:
        """Read and validate a canonical targets.json file."""
        return read_targets_json(path, require_canonical=True, default_market="US")

    def dry_run_from_file(
        self,
        targets_path: Path,
        *,
        target_gross_exposure: float = 1.0,
    ) -> QEEExecutionResult:
        """Convenience: read targets from a file, then dry-run."""
        targets_doc = read_targets_json(targets_path, default_market="US")
        target_dicts = [entry.to_payload() for entry in targets_doc.targets]
        return self.execute(
            target_dicts,
            dry_run=True,
            target_source=targets_doc.source or "file",
            target_asof=targets_doc.asof,
            target_gross_exposure=target_gross_exposure,
        )

    def get_account_snapshot(self) -> dict[str, Any]:
        """Return a summary dict of the current account state."""
        adapter = get_broker_adapter(broker_name=self.broker_name)
        snapshot = adapter.get_account_snapshot()
        return {
            "cash_usd": snapshot.cash_usd,
            "total_portfolio_value": snapshot.total_portfolio_value,
            "base_currency": snapshot.base_currency,
            "position_count": len(snapshot.positions),
            "positions": [
                {
                    "symbol": p.symbol,
                    "quantity": p.quantity,
                    "estimated_value": p.estimated_value,
                }
                for p in snapshot.positions
            ],
        }


# ------------------------------------------------------------------
# Internal helpers
# ------------------------------------------------------------------


def _dicts_to_entries(targets: list[dict[str, Any]]) -> list[TargetEntry]:
    entries: list[TargetEntry] = []
    for item in targets:
        if isinstance(item, TargetEntry):
            entries.append(item)
            continue
        entries.append(
            TargetEntry(
                symbol=str(item["symbol"]),
                market=str(item.get("market", "US")),
                target_weight=item.get("target_weight"),
                target_quantity=item.get("target_quantity"),
                notes=item.get("notes"),
                metadata=dict(item.get("metadata", {})),
            )
        )
    return entries


def _collect_reconcile_warnings(report: BrokerReconcileReport) -> list[str]:
    warnings: list[str] = []
    for order in report.open_orders:
        if order.status in {"REJECTED", "EXPIRED"}:
            warnings.append(f"Order {order.broker_order_id} ({order.symbol}) is {order.status}")
    return warnings
