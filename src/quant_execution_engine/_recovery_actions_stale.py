"""Bulk stale-retry recovery action for OrderLifecycleService.

Builds on :class:`OrderLifecycleRecoveryRepriceMixin`: cancel-and-retry locally
tracked stale open orders with zero fills (``retry_stale_orders``).
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

from ._recovery_actions_reprice import OrderLifecycleRecoveryRepriceMixin
from .execution_helpers import load_account_state
from .execution_state import ExecutionCancelResult, ExecutionRetryResult, ExecutionStaleRetryResult
from .logging import get_logger

logger = get_logger(__name__)


class OrderLifecycleRecoveryStaleMixin(OrderLifecycleRecoveryRepriceMixin):
    """Bulk stale-retry recovery action."""

    def retry_stale_orders(
        self,
        *,
        account_label: str,
        older_than_minutes: int,
    ) -> ExecutionStaleRetryResult:
        """Cancel and retry locally tracked stale open orders with zero fills."""

        if older_than_minutes <= 0:
            raise ValueError("older_than_minutes must be greater than 0")

        account, state = load_account_state(
            self.adapter,
            self.state_store,
            account_label,
        )
        cutoff = datetime.now(timezone.utc) - timedelta(minutes=int(older_than_minutes))
        warnings: list[str] = []
        targets = sorted(
            self._find_stale_retry_targets(state, cutoff=cutoff, warnings=warnings),
            key=lambda record: (
                self._timestamp_for_stale_retry(record)
                or datetime.min.replace(tzinfo=timezone.utc),
                record.broker_order_id,
            ),
        )

        cancel_results: list[ExecutionCancelResult] = []
        retry_results: list[ExecutionRetryResult] = []
        for target in targets:
            try:
                cancel_outcome = self.cancel_order(
                    account_label=account.label,
                    order_ref=target.broker_order_id,
                )
            except Exception as exc:
                message = f"{target.broker_order_id}: cancel failed: {exc}"
                warnings.append(message)
                logger.warning(
                    "Stale retry cancel failed for %s (%s/%s): %s",
                    target.broker_order_id,
                    self.adapter.backend_name,
                    account.label,
                    exc,
                )
                continue
            cancel_results.append(cancel_outcome)
            if cancel_outcome.status != "CANCELED":
                warnings.append(
                    f"{target.broker_order_id}: skipped retry because post-cancel "
                    f"status is {cancel_outcome.status}"
                )
                continue
            try:
                retry_outcome = self.retry_order(
                    account_label=account.label,
                    order_ref=target.broker_order_id,
                )
            except Exception as exc:
                message = f"{target.broker_order_id}: retry failed: {exc}"
                warnings.append(message)
                logger.warning(
                    "Stale retry submit failed for %s (%s/%s): %s",
                    target.broker_order_id,
                    self.adapter.backend_name,
                    account.label,
                    exc,
                )
                continue
            retry_results.append(retry_outcome)

        return ExecutionStaleRetryResult(
            broker_name=self.adapter.backend_name,
            account_label=account.label,
            state_path=self.state_store.path_for(self.adapter.backend_name, account.label),
            older_than_minutes=int(older_than_minutes),
            targeted_orders=len(targets),
            cancel_results=cancel_results,
            retry_results=retry_results,
            warnings=warnings,
        )
