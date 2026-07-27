from __future__ import annotations

from pathlib import Path

from ...account import get_account_snapshot, get_quotes
from ...broker import is_paper_broker, resolve_broker_name
from ...guards import validate_live_execution_guard
from ...logging import get_logger
from ...rebalance import RebalanceService
from ...renderers.diff import render_rebalance_diff
from ...targets import read_targets_json
from .. import CommandResult


def run_rebalance(
    input_file: str,
    account: str = "main",
    dry_run: bool = True,
    target_gross_exposure: float = 1.0,
    broker: str | None = None,
) -> CommandResult:
    logger = get_logger(__name__)
    file_path = Path(input_file)

    if not file_path.exists():
        return CommandResult(exit_code=1, stderr=f"File not found: {input_file}")

    if file_path.suffix.lower() != ".json":
        return CommandResult(
            exit_code=1,
            stderr=(
                "Legacy workbook inputs are deprecated for live execution. "
                "Provide a canonical targets JSON and rerun "
                "'qexec rebalance <targets.json>'."
            ),
        )

    try:
        selected_broker = resolve_broker_name(broker)
        env_name = "paper" if is_paper_broker(selected_broker) else "real"
        guard_error = validate_live_execution_guard(env_name=env_name, dry_run=dry_run)
        if guard_error:
            return CommandResult(exit_code=1, stderr=guard_error)
        logger.info("Mode: %s", "dry-run" if dry_run else "live")
        logger.info("Reading targets file: %s", input_file)
        logger.info("Broker: %s", selected_broker)
        logger.info("Account: %s", account)

        targets_doc = read_targets_json(file_path, require_canonical=True)

        service = RebalanceService(
            env=env_name,
            broker_name=selected_broker,
            account_label=account,
        )
        client = service._get_client()
        account_snapshot = get_account_snapshot(
            env=env_name,
            include_quotes=False,
            client=client,
            broker_name=selected_broker,
            account_label=account,
        )

        target_symbols = {f"{target.symbol}.{target.market}" for target in targets_doc.targets}
        held_symbols = {position.symbol for position in account_snapshot.positions}
        all_symbols = sorted(target_symbols | held_symbols)
        if all_symbols:
            quote_objs = get_quotes(
                all_symbols,
                client=client,
                broker_name=selected_broker,
            )
            quote_map = {symbol: quote.price for symbol, quote in quote_objs.items()}
        else:
            quote_map = {}

        if quote_map and account_snapshot.positions:
            for position in account_snapshot.positions:
                price = float(quote_map.get(position.symbol, position.last_price or 0.0) or 0.0)
                if price > 0:
                    position.last_price = price
                    position.estimated_value = float(price) * float(position.quantity)
            total_market_value = sum(
                float(position.estimated_value) for position in account_snapshot.positions
            )
            account_snapshot.total_market_value = total_market_value
            if not account_snapshot.total_portfolio_value:
                account_snapshot.total_portfolio_value = (
                    float(account_snapshot.cash_usd) + total_market_value
                )

        try:
            effective_exposure = targets_doc.target_gross_exposure
            if target_gross_exposure != 1.0 and targets_doc.target_gross_exposure == 1.0:
                effective_exposure = target_gross_exposure

            result = service.plan_rebalance(
                targets_doc.targets,
                account_snapshot,
                quotes=quote_map,
                target_gross_exposure=effective_exposure,
            )
            result.dry_run = dry_run
            result.sheet_name = targets_doc.asof or file_path.stem
            result.target_source = targets_doc.source
            result.target_asof = targets_doc.asof or file_path.stem
            result.target_input_path = str(file_path)
            result.broker_name = selected_broker
            result.account_label = account

            result.orders = service.execute_orders(
                result.orders,
                dry_run=dry_run,
                target_source=result.target_source,
                target_asof=result.target_asof,
                target_input_path=result.target_input_path,
            )
            if service._last_reconcile_report is not None:
                result.reconcile_warnings = list(service._last_reconcile_report.warnings)
            audit_log_path = service.save_audit_log(result, dry_run=dry_run)
            result.audit_log_path = str(audit_log_path)
            diff_view = render_rebalance_diff(result, account_snapshot)
            return CommandResult(
                exit_code=0,
                stdout=diff_view.text,
                rich_renderable=diff_view.rich,
            )
        finally:
            service.close()
    except Exception as exc:
        logger.error("Rebalance failed: %s", exc)
        return CommandResult(exit_code=1, stderr=str(exc))
