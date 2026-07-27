#!/usr/bin/env python3
"""Run a fixed execution/operator smoke workflow against a broker backend.

This module is a thin facade over the :mod:`project_tools.smoke_operator`
package. It is kept as a standalone, importable file so existing callers (and the
unit/e2e tests that load it by path) continue to work unchanged.
"""

from __future__ import annotations

import os  # noqa: F401  (kept for test monkeypatching via module.os)
import subprocess  # noqa: F401  (kept for test monkeypatching via module.subprocess)
from pathlib import Path

from project_tools.smoke_operator import (
    IBKR_SMOKE_ENV_KEYS,
    LONGPORT_SMOKE_ENV_KEYS,
    SmokeWorkflowStepError,
    append_skipped_step,
    apply_broker_env,
    audit_log_dir,
    build_operator_smoke_targets,
    build_parser,
    canonical_symbol,
    capture_broker_env,
    classify_failed_step,
    discover_audit_log,
    finalize_skipped_steps,
    latest_operator_outcome,
    latest_tracked_order_ref,
    list_audit_logs,
    main,
    planned_workflow_steps,
    qexec_broker_argv,
    read_audit_summary,
    run_broker_workflow_step,
    run_cli_subprocess_step,
    run_operator_smoke_workflow,
    run_step,
    run_step_with_env,
    subprocess_env,
    symbol_matches,
    write_evidence,
)
from quant_execution_engine.account import get_account_snapshot
from quant_execution_engine.broker import get_broker_adapter
from quant_execution_engine.cli import (
    run_account,
    run_cancel_all,
    run_config,
    run_exceptions,
    run_order,
    run_orders,
    run_quote,
    run_rebalance,
    run_reconcile,
)
from quant_execution_engine.execution import ExecutionStateStore

# Host-project root, used by the audit-log helpers in the package. Defined here
# (rather than in the package) so callers that reassign it on this module object
# affect the audit-log discovery path at runtime.
PROJECT_ROOT = Path(__file__).resolve().parents[1]

__all__ = [
    "IBKR_SMOKE_ENV_KEYS",
    "LONGPORT_SMOKE_ENV_KEYS",
    "PROJECT_ROOT",
    "ExecutionStateStore",
    "SmokeWorkflowStepError",
    "append_skipped_step",
    "apply_broker_env",
    "audit_log_dir",
    "build_operator_smoke_targets",
    "build_parser",
    "canonical_symbol",
    "capture_broker_env",
    "classify_failed_step",
    "discover_audit_log",
    "finalize_skipped_steps",
    "get_account_snapshot",
    "get_broker_adapter",
    "latest_operator_outcome",
    "latest_tracked_order_ref",
    "list_audit_logs",
    "main",
    "planned_workflow_steps",
    "qexec_broker_argv",
    "read_audit_summary",
    "run_account",
    "run_broker_workflow_step",
    "run_cancel_all",
    "run_cli_subprocess_step",
    "run_config",
    "run_exceptions",
    "run_operator_smoke_workflow",
    "run_order",
    "run_orders",
    "run_quote",
    "run_rebalance",
    "run_reconcile",
    "run_step",
    "run_step_with_env",
    "subprocess_env",
    "symbol_matches",
    "write_evidence",
]


if __name__ == "__main__":
    raise SystemExit(main())
