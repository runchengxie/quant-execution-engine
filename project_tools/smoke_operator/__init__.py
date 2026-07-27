"""Operator smoke harness package.

Exposes the public surface of the smoke operator harness. The standalone
entrypoint script ``smoke_operator_harness.py`` re-exports these names so that
existing importers (and tests that load that file by path) keep working.
"""

from __future__ import annotations

from project_tools.smoke_operator.audit import (
    append_skipped_step,
    audit_log_dir,
    discover_audit_log,
    finalize_skipped_steps,
    list_audit_logs,
    read_audit_summary,
)
from project_tools.smoke_operator.evidence import write_evidence
from project_tools.smoke_operator.parser import build_parser, main
from project_tools.smoke_operator.state import (
    build_operator_smoke_targets,
    canonical_symbol,
    latest_operator_outcome,
    latest_tracked_order_ref,
    symbol_matches,
)
from project_tools.smoke_operator.steps import (
    IBKR_SMOKE_ENV_KEYS,
    LONGPORT_SMOKE_ENV_KEYS,
    SmokeWorkflowStepError,
    apply_broker_env,
    capture_broker_env,
    classify_failed_step,
    planned_workflow_steps,
    qexec_broker_argv,
    run_broker_workflow_step,
    run_cli_subprocess_step,
    run_step,
    run_step_with_env,
    subprocess_env,
)
from project_tools.smoke_operator.workflow import (
    run_operator_smoke_workflow,
)

__all__ = [
    "IBKR_SMOKE_ENV_KEYS",
    "LONGPORT_SMOKE_ENV_KEYS",
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
    "latest_operator_outcome",
    "latest_tracked_order_ref",
    "list_audit_logs",
    "main",
    "planned_workflow_steps",
    "qexec_broker_argv",
    "read_audit_summary",
    "run_broker_workflow_step",
    "run_cli_subprocess_step",
    "run_operator_smoke_workflow",
    "run_step",
    "run_step_with_env",
    "subprocess_env",
    "symbol_matches",
    "write_evidence",
]
