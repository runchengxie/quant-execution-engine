"""Step execution primitives for the operator smoke harness."""

from __future__ import annotations

import argparse
import os
import subprocess
import sys
from pathlib import Path
from types import SimpleNamespace

LONGPORT_SMOKE_ENV_KEYS = (
    "LONGPORT_APP_KEY",
    "LONGPORT_APP_SECRET",
    "LONGPORT_ACCESS_TOKEN",
    "LONGPORT_ACCESS_TOKEN_REAL",
    "LONGPORT_ACCESS_TOKEN_TEST",
    "LONGPORT_REGION",
    "LONGPORT_ENABLE_OVERNIGHT",
    "LONGBRIDGE_APP_KEY",
    "LONGBRIDGE_APP_SECRET",
    "LONGBRIDGE_ACCESS_TOKEN",
    "LONGBRIDGE_ACCESS_TOKEN_REAL",
    "LONGBRIDGE_ACCESS_TOKEN_TEST",
    "LONGBRIDGE_REGION",
    "LONGBRIDGE_ENABLE_OVERNIGHT",
)
IBKR_SMOKE_ENV_KEYS = (
    "IBKR_HOST",
    "IBKR_PORT",
    "IBKR_PORT_PAPER",
    "IBKR_CLIENT_ID",
    "IBKR_ACCOUNT_ID",
    "IBKR_CONNECT_TIMEOUT_SECONDS",
)


class SmokeWorkflowStepError(RuntimeError):
    """Raised when a smoke workflow step returns a non-zero exit code."""

    def __init__(self, payload: dict[str, object]) -> None:
        self.payload = payload
        super().__init__(f"{payload['name']} failed with exit code {payload['exit_code']}")


def capture_broker_env(broker: str) -> dict[str, str | None]:
    normalized = str(broker).strip().lower()
    if normalized.startswith("longport"):
        return {key: os.getenv(key) for key in LONGPORT_SMOKE_ENV_KEYS}
    if normalized == "ibkr-paper":
        return {key: os.getenv(key) for key in IBKR_SMOKE_ENV_KEYS}
    return {}


def apply_broker_env(env_snapshot: dict[str, str | None]) -> None:
    for key, value in env_snapshot.items():
        if value is None:
            os.environ.pop(key, None)
        else:
            os.environ[key] = value


def subprocess_env(env_snapshot: dict[str, str | None]) -> dict[str, str]:
    env = dict(os.environ)
    for key, value in env_snapshot.items():
        if value is None:
            env.pop(key, None)
        else:
            env[key] = value
    return env


def run_step(name: str, result: object) -> dict[str, object]:
    exit_code = int(getattr(result, "exit_code", 1))
    stdout = getattr(result, "stdout", None)
    stderr = getattr(result, "stderr", None)
    payload = {
        "name": name,
        "exit_code": exit_code,
        "stdout": stdout,
        "stderr": stderr,
    }
    print(f"\n== {name} ==")
    if stdout:
        print(stdout)
    if stderr:
        print(stderr, file=sys.stderr)
    if exit_code != 0:
        raise SmokeWorkflowStepError(payload)
    return payload


def run_step_with_env(
    env_snapshot: dict[str, str | None],
    name: str,
    fn,
    *args,
    **kwargs,
) -> dict[str, object]:
    apply_broker_env(env_snapshot)
    return run_step(name, fn(*args, **kwargs))


def run_cli_subprocess_step(
    env_snapshot: dict[str, str | None],
    name: str,
    argv: list[str],
) -> dict[str, object]:
    completed = subprocess.run(
        argv,
        cwd=str(_project_root()),
        env=subprocess_env(env_snapshot),
        capture_output=True,
        text=True,
        check=False,
    )
    return run_step(
        name,
        SimpleNamespace(
            exit_code=int(completed.returncode),
            stdout=completed.stdout.strip() or None,
            stderr=completed.stderr.strip() or None,
        ),
    )


def qexec_broker_argv(
    command: str,
    *,
    broker: str,
    account_label: str,
    positionals: list[str] | None = None,
    extra_args: list[str] | None = None,
) -> list[str]:
    return [
        sys.executable,
        "-m",
        "quant_execution_engine",
        command,
        *(positionals or []),
        "--broker",
        broker,
        "--account",
        account_label,
        *(extra_args or []),
    ]


def run_broker_workflow_step(
    env_snapshot: dict[str, str | None],
    *,
    name: str,
    cli_isolation: bool,
    cli_argv: list[str],
    direct_fn,
    direct_args: list[object] | None = None,
    direct_kwargs: dict[str, object] | None = None,
) -> dict[str, object]:
    if cli_isolation:
        return run_cli_subprocess_step(env_snapshot, name, cli_argv)
    return run_step_with_env(
        env_snapshot,
        name,
        direct_fn,
        *(direct_args or []),
        **(direct_kwargs or {}),
    )


def planned_workflow_steps(args: argparse.Namespace) -> list[str]:
    steps = ["config", "account", "quote"]
    if args.preflight_only:
        return steps
    steps.append("rebalance")
    if not args.execute:
        return steps
    steps.extend(["orders", "order", "reconcile", "exceptions"])
    if args.cleanup_open_orders:
        steps.append("cancel-all")
    return steps


def classify_failed_step(step_name: str | None) -> tuple[str | None, str | None]:
    if not step_name:
        return None, None
    return WORKFLOW_FAILURE_METADATA.get(
        str(step_name),
        (
            "WORKFLOW_STEP_FAILED",
            "Inspect the failed step stderr and the local state before retrying the workflow.",
        ),
    )


def _project_root() -> Path:

    from project_tools.smoke_operator_harness import PROJECT_ROOT

    return PROJECT_ROOT


WORKFLOW_FAILURE_METADATA: dict[str, tuple[str, str]] = {
    "config": (
        "CONFIG_CHECK_FAILED",
        "Inspect resolved config and credential sources before retrying the smoke workflow.",
    ),
    "account": (
        "ACCOUNT_CHECK_FAILED",
        "Run `qexec account` directly and confirm the resolved account/profile is reachable.",
    ),
    "quote": (
        "QUOTE_CHECK_FAILED",
        "Retry `qexec quote` and confirm market-data entitlements, "
        "symbol mapping, and broker connectivity.",
    ),
    "rebalance": (
        "REBALANCE_EXECUTION_FAILED",
        "Inspect the rebalance stderr, audit log, and local state before "
        "retrying the mutation step.",
    ),
    "orders": (
        "OPEN_ORDER_QUERY_FAILED",
        "Run `qexec reconcile` or inspect the local tracked state before "
        "relying on open-order output.",
    ),
    "order": (
        "TRACKED_ORDER_QUERY_FAILED",
        "Inspect the tracked order reference in local state, then rerun "
        "`qexec order` or `qexec reconcile`.",
    ),
    "reconcile": (
        "RECONCILE_FAILED",
        "Rerun `qexec reconcile` after checking broker/API health; inspect "
        "the state file if tracked status may be stale.",
    ),
    "exceptions": (
        "EXCEPTION_VIEW_FAILED",
        "Inspect the local tracked state and rerun `qexec exceptions` after reconcile if needed.",
    ),
    "cancel-all": (
        "BULK_CANCEL_FAILED",
        "Inspect remaining tracked open orders, then rerun `qexec cancel-all` "
        "or `qexec reconcile`.",
    ),
}
