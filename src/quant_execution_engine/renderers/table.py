"""Table renderer (public facade).

This module keeps the public surface that the rest of the codebase and the
test-suite import from ``quant_execution_engine.renderers.table``. The actual
implementations live in the focused submodules (``_table_market`` /
``_table_broker`` / ``_table_execution`` / ``_table_state``); this file is a
thin shell that re-exports them so external imports keep working unchanged.
"""

from ._table_broker import (
    render_broker_fill_history,
    render_broker_order_history,
    render_broker_orders,
    render_exception_orders,
)
from ._table_execution import (
    render_accept_partial_summary,
    render_bulk_cancel_summary,
    render_cancel_summary,
    render_order_trace,
    render_reconcile_summary,
    render_reprice_summary,
    render_resume_remaining_summary,
    render_retry_summary,
    render_stale_retry_summary,
    render_tracked_order_detail,
)
from ._table_market import (
    render_account_snapshot,
    render_multiple_account_snapshots,
    render_orders,
    render_quotes,
    render_rebalance_plan,
)
from ._table_state import (
    render_preflight_summary,
    render_state_doctor_summary,
    render_state_prune_summary,
    render_state_repair_summary,
)

__all__ = [
    "render_accept_partial_summary",
    "render_account_snapshot",
    "render_broker_fill_history",
    "render_broker_order_history",
    "render_broker_orders",
    "render_bulk_cancel_summary",
    "render_cancel_summary",
    "render_exception_orders",
    "render_multiple_account_snapshots",
    "render_order_trace",
    "render_orders",
    "render_preflight_summary",
    "render_quotes",
    "render_rebalance_plan",
    "render_reconcile_summary",
    "render_reprice_summary",
    "render_resume_remaining_summary",
    "render_retry_summary",
    "render_stale_retry_summary",
    "render_state_doctor_summary",
    "render_state_prune_summary",
    "render_state_repair_summary",
    "render_tracked_order_detail",
]
