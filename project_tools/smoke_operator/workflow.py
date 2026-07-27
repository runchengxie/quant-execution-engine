"""Operator smoke workflow orchestration."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from project_tools.smoke_operator.audit import (
    append_skipped_step,
    discover_audit_log,
    finalize_skipped_steps,
    list_audit_logs,
)
from project_tools.smoke_operator.evidence import write_evidence
from project_tools.smoke_operator.state import (
    build_operator_smoke_targets,
    canonical_symbol,
    latest_operator_outcome,
)
from project_tools.smoke_operator.steps import (
    SmokeWorkflowStepError,
    apply_broker_env,
    capture_broker_env,
    classify_failed_step,
    qexec_broker_argv,
    run_broker_workflow_step,
    run_step_with_env,
)
from quant_execution_engine.broker import (
    is_paper_broker,
    resolve_broker_name,
)
from quant_execution_engine.targets import write_targets_json


def run_operator_smoke_workflow(args: argparse.Namespace) -> int:
    # Lazily bind CLI handlers from the harness facade so tests can monkeypatch
    # these names on ``project_tools.smoke_operator_harness`` at call time.
    from project_tools.smoke_operator_harness import (
        get_account_snapshot,
        get_broker_adapter,
        latest_tracked_order_ref,
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

    broker = resolve_broker_name(args.broker)
    if not is_paper_broker(broker) and not args.allow_non_paper:
        print(
            "Refusing non-paper broker for smoke operator harness. "
            "Pass --allow-non-paper to override.",
            file=sys.stderr,
        )
        return 2

    adapter = get_broker_adapter(broker_name=broker)
    try:
        resolved_account = adapter.resolve_account(args.account)
        account_label = resolved_account.label
    finally:
        close_fn = getattr(adapter, "close", None)
        if callable(close_fn):
            close_fn()

    canonical = canonical_symbol(args.symbol, args.market)
    broker_env = capture_broker_env(broker)
    longport_cli_isolation = str(broker).startswith("longport") and bool(args.execute)
    steps: list[dict[str, object]] = []
    skipped_steps: list[dict[str, str]] = []
    output_path = Path(args.output)
    order_ref: str | None = None
    operator_outcome: dict[str, object] | None = None
    audit_log_baseline = set(list_audit_logs())
    audit_log_path: Path | None = None
    audit_summary: dict[str, object] | None = None
    try:
        steps.append(run_step_with_env(broker_env, "config", run_config, True, broker=broker))
        steps.append(
            run_step_with_env(
                broker_env,
                "account",
                run_account,
                account=account_label,
                broker=broker,
            )
        )
        steps.append(run_step_with_env(broker_env, "quote", run_quote, [canonical], broker=broker))

        if args.preflight_only:
            print(
                "\n== preflight ==\n"
                "Preflight checks passed; skipping targets and broker mutation steps."
            )
            write_evidence(
                args=args,
                broker=broker,
                account_label=account_label,
                canonical=canonical,
                steps=steps,
                output_path=output_path,
                latest_order_ref=None,
                skipped_steps=skipped_steps,
                operator_outcome=None,
            )
            return 0

        apply_broker_env(broker_env)
        snapshot = get_account_snapshot(
            env="paper" if is_paper_broker(broker) else "real",
            include_quotes=False,
            broker_name=broker,
            account_label=account_label,
        )
        current_quantity = next(
            (
                int(position.quantity)
                for position in snapshot.positions
                if position.symbol.upper() == canonical
            ),
            0,
        )
        targets = build_operator_smoke_targets(
            symbol=args.symbol,
            market=args.market,
            current_quantity=current_quantity,
        )
        write_targets_json(
            output_path,
            asof="smoke-operator",
            source="smoke-operator-harness",
            targets=targets,
            notes=f"operator smoke for {canonical}",
        )
        print(
            f"\n== targets ==\n"
            f"Wrote {output_path} with target_quantity={targets[0]['target_quantity']}"
        )

        steps.append(
            run_broker_workflow_step(
                broker_env,
                name="rebalance",
                cli_isolation=longport_cli_isolation,
                cli_argv=qexec_broker_argv(
                    "rebalance",
                    broker=broker,
                    account_label=account_label,
                    positionals=[str(output_path)],
                    extra_args=["--execute"],
                ),
                direct_fn=run_rebalance,
                direct_args=[str(output_path)],
                direct_kwargs={
                    "account": account_label,
                    "dry_run": not args.execute,
                    "broker": broker,
                },
            )
        )
        audit_log_path, audit_summary = discover_audit_log(
            baseline_paths=audit_log_baseline,
            target_input_path=str(output_path),
        )

        if not args.execute:
            write_evidence(
                args=args,
                broker=broker,
                account_label=account_label,
                canonical=canonical,
                steps=steps,
                output_path=output_path,
                latest_order_ref=None,
                audit_log_path=audit_log_path,
                audit_summary=audit_summary,
            )
            return 0

        steps.append(
            run_broker_workflow_step(
                broker_env,
                name="orders",
                cli_isolation=longport_cli_isolation,
                cli_argv=qexec_broker_argv(
                    "orders",
                    broker=broker,
                    account_label=account_label,
                    extra_args=["--symbol", args.symbol],
                ),
                direct_fn=run_orders,
                direct_kwargs={
                    "account": account_label,
                    "broker": broker,
                    "symbol_filter": args.symbol,
                },
            )
        )
        operator_outcome = latest_operator_outcome(
            broker_name=broker,
            account_label=account_label,
            symbol_filter=args.symbol,
            target_input_path=str(output_path),
        )
        order_ref = latest_tracked_order_ref(
            broker_name=broker,
            account_label=account_label,
            symbol_filter=args.symbol,
            target_input_path=str(output_path),
        )
        if order_ref:
            steps.append(
                run_broker_workflow_step(
                    broker_env,
                    name="order",
                    cli_isolation=longport_cli_isolation,
                    cli_argv=qexec_broker_argv(
                        "order",
                        broker=broker,
                        account_label=account_label,
                        positionals=[order_ref],
                    ),
                    direct_fn=run_order,
                    direct_kwargs={
                        "order_ref": order_ref,
                        "account": account_label,
                        "broker": broker,
                    },
                )
            )
        else:
            print("\n== order ==\nNo tracked broker order found after rebalance")
            skip_reason = "no tracked order reference available after rebalance"
            if operator_outcome is not None and operator_outcome.get("status") == "BLOCKED":
                skip_reason = "latest tracked outcome is BLOCKED and has no broker order reference"
            append_skipped_step(
                skipped_steps,
                name="order",
                reason=skip_reason,
            )

        steps.append(
            run_broker_workflow_step(
                broker_env,
                name="reconcile",
                cli_isolation=longport_cli_isolation,
                cli_argv=qexec_broker_argv(
                    "reconcile",
                    broker=broker,
                    account_label=account_label,
                ),
                direct_fn=run_reconcile,
                direct_kwargs={
                    "account": account_label,
                    "broker": broker,
                },
            )
        )
        steps.append(
            run_broker_workflow_step(
                broker_env,
                name="exceptions",
                cli_isolation=longport_cli_isolation,
                cli_argv=qexec_broker_argv(
                    "exceptions",
                    broker=broker,
                    account_label=account_label,
                    extra_args=["--symbol", args.symbol],
                ),
                direct_fn=run_exceptions,
                direct_kwargs={
                    "account": account_label,
                    "broker": broker,
                    "symbol_filter": args.symbol,
                },
            )
        )

        if args.cleanup_open_orders:
            steps.append(
                run_broker_workflow_step(
                    broker_env,
                    name="cancel-all",
                    cli_isolation=longport_cli_isolation,
                    cli_argv=qexec_broker_argv(
                        "cancel-all",
                        broker=broker,
                        account_label=account_label,
                    ),
                    direct_fn=run_cancel_all,
                    direct_kwargs={
                        "account": account_label,
                        "broker": broker,
                    },
                )
            )

        operator_outcome = latest_operator_outcome(
            broker_name=broker,
            account_label=account_label,
            symbol_filter=args.symbol,
            target_input_path=str(output_path),
        )
        write_evidence(
            args=args,
            broker=broker,
            account_label=account_label,
            canonical=canonical,
            steps=steps,
            output_path=output_path,
            latest_order_ref=order_ref,
            skipped_steps=skipped_steps,
            operator_outcome=operator_outcome,
            audit_log_path=audit_log_path,
            audit_summary=audit_summary,
        )

        return 0
    except SmokeWorkflowStepError as exc:
        steps.append(exc.payload)
        failure_category, next_step_hint = classify_failed_step(str(exc.payload["name"]))
        if audit_log_path is None:
            audit_log_path, audit_summary = discover_audit_log(
                baseline_paths=audit_log_baseline,
                target_input_path=str(output_path),
            )
        operator_outcome = latest_operator_outcome(
            broker_name=broker,
            account_label=account_label,
            symbol_filter=args.symbol,
            target_input_path=str(output_path),
        )
        write_evidence(
            args=args,
            broker=broker,
            account_label=account_label,
            canonical=canonical,
            steps=steps,
            output_path=output_path,
            latest_order_ref=order_ref,
            success=False,
            failure_message=str(exc),
            failed_step=str(exc.payload["name"]),
            failure_category=failure_category,
            next_step_hint=next_step_hint,
            skipped_steps=finalize_skipped_steps(
                args=args,
                steps=steps,
                skipped_steps=skipped_steps,
                failed_step=str(exc.payload["name"]),
            ),
            operator_outcome=operator_outcome,
            audit_log_path=audit_log_path,
            audit_summary=audit_summary,
        )
        print(str(exc), file=sys.stderr)
        return 1
