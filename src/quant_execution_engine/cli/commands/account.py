from __future__ import annotations

import os
from pathlib import Path

from ...account import get_account_snapshot, get_quotes
from ...broker import (
    get_broker_adapter,
    get_broker_capabilities,
    is_ibkr_broker,
    is_longport_broker,
    is_paper_broker,
    peek_broker_name,
    probe_ibkr_runtime_config,
    resolve_broker_name,
    resolve_default_account_label,
)
from ...broker.longport_credentials import (
    probe_longport_credentials,
    resolve_longport_runtime_value,
)
from ...evidence_bundle import (
    EvidenceBundleError,
    create_evidence_bundle,
    render_evidence_bundle_result,
)
from ...evidence_maturity import (
    build_broker_evidence_maturity_report,
    render_broker_evidence_maturity,
)
from ...execution import OrderLifecycleService
from ...health import HealthCheckError, render_health_result, run_health
from ...logging import get_logger
from ...preflight import run_preflight_checks
from ...renderers.jsonout import render_json, render_multiple_account_snapshots_json
from ...renderers.table import (
    render_exception_orders,
    render_multiple_account_snapshots,
    render_preflight_summary,
    render_quotes,
)
from ...risk import get_kill_switch_config, get_risk_config, is_manual_kill_switch_active
from .. import CommandResult
from ..render import (
    ReportError,
    get_run_report,
    list_run_reports,
    render_run_report,
    render_run_report_list,
)
from ._common import (
    _close_broker_adapter,
    _format_filter_summary,
    _resolve_exception_status_filter,
    _resolve_symbol_filter,
    _symbol_matches_filter,
)


def run_quote(tickers: list[str], broker: str | None = None) -> CommandResult:
    try:
        quotes_dict = get_quotes(tickers, broker_name=broker)
        return CommandResult(exit_code=0, stdout=render_quotes(list(quotes_dict.values())))
    except Exception as exc:
        requested_broker = peek_broker_name(broker) or "(unconfigured)"
        get_logger(__name__).error(
            "Failed to fetch quotes via broker %s: %s",
            requested_broker,
            exc,
        )
        return CommandResult(exit_code=1, stderr=str(exc))


def run_preflight(
    *,
    symbols: list[str] | None = None,
    account: str = "main",
    broker: str | None = None,
) -> CommandResult:
    try:
        result = run_preflight_checks(
            broker_name=broker,
            account_label=account,
            symbols=symbols or ["AAPL"],
        )
        return CommandResult(
            exit_code=1 if result.has_failures else 0,
            stdout=render_preflight_summary(result),
        )
    except Exception as exc:
        msg = f"Preflight failed: {exc}"
        get_logger(__name__).error(msg)
        return CommandResult(exit_code=1, stderr=msg)


def run_account(
    only_funds: bool = False,
    only_positions: bool = False,
    fmt: str = "table",
    account: str = "main",
    broker: str | None = None,
) -> CommandResult:
    try:
        if only_funds and only_positions:
            only_positions = False
        selected_broker = resolve_broker_name(broker)
        snapshot = get_account_snapshot(
            env="paper" if is_paper_broker(selected_broker) else "real",
            broker_name=selected_broker,
            account_label=account,
        )
        snapshots = [snapshot]
        if fmt == "json":
            output = render_multiple_account_snapshots_json(snapshots)
        else:
            output = render_multiple_account_snapshots(
                snapshots,
                only_funds=only_funds,
                only_positions=only_positions,
            )
        return CommandResult(exit_code=0, stdout=output)
    except Exception as exc:
        msg = f"Failed to get account overview: {exc}"
        get_logger(__name__).error(msg)
        return CommandResult(exit_code=1, stderr=msg)


def run_config(
    show: bool = True, broker: str | None = None, *, check_gates: bool = False
) -> CommandResult:
    if not show:
        return CommandResult(exit_code=0)

    def _getenv_both(name_new: str, name_old: str, default: str = "") -> str:
        return os.getenv(name_new) or os.getenv(name_old) or default

    def _to_bool(value: str | None, default: bool = False) -> bool:
        if value is None:
            return default
        return str(value).strip().lower() in {"1", "true", "yes", "y", "on"}

    def _to_float(value: str | None, default: float = 0.0) -> float:
        try:
            return float(str(value)) if value is not None else default
        except Exception:
            return default

    def _to_int(value: str | None, default: int = 0) -> int:
        try:
            return int(float(str(value))) if value is not None else default
        except Exception:
            return default

    def _fmt_unlimited(value: float | int) -> str:
        try:
            if float(value) <= 0:
                return "Unlimited (0)"
        except Exception:
            return str(value)
        return f"{value}"

    try:
        selected_broker = resolve_broker_name(broker)
        capabilities = get_broker_capabilities(selected_broker)
        risk_cfg = get_risk_config()
        kill_switch_cfg = get_kill_switch_config()
        default_account = resolve_default_account_label()

        if check_gates:
            kill_active, _kill_reason = is_manual_kill_switch_active()

            def _gate_row(label: str, value: str, active: bool) -> str:
                return f"{label:<26s}{value:<22s}{'ACTIVE' if active else 'OFF'}"

            max_notional = float(risk_cfg.get("max_notional_per_order", 0.0) or 0.0)
            max_qty = int(float(risk_cfg.get("max_qty_per_order", 0) or 0))
            max_spread = int(float(risk_cfg.get("max_spread_bps", 0) or 0))
            max_partic = float(risk_cfg.get("max_participation_rate", 0) or 0)
            max_impact = int(float(risk_cfg.get("max_market_impact_bps", 0) or 0))
            kill_env = str(kill_switch_cfg.get("env_var") or "QEXEC_KILL_SWITCH")
            kill_state = "ACTIVE (execution blocked)" if kill_active else "inactive"
            fail_thresh = str(kill_switch_cfg.get("failure_threshold", 3) or 3)

            gates_output = [
                "=== Active Risk Gate Thresholds ===",
                "Broker: " + selected_broker,
                "",
                "Gate                      Threshold              Status",
                "-" * 60,
                _gate_row("max_notional_per_order", _fmt_unlimited(max_notional), max_notional > 0),
                _gate_row("max_qty_per_order", _fmt_unlimited(max_qty), max_qty > 0),
                _gate_row("max_spread_bps", str(max_spread), max_spread > 0),
                _gate_row("max_participation_rate", str(max_partic), max_partic > 0),
                _gate_row("max_market_impact_bps", str(max_impact), max_impact > 0),
                "",
                "Kill switch env:         " + kill_env,
                "Kill switch state:       " + kill_state,
                "Failure threshold:       " + fail_thresh,
                "",
                "Source: config/config.yaml  execution.risk.*",
            ]
            return CommandResult(exit_code=0, stdout="\n".join(gates_output))

        alpaca_key = os.getenv("ALPACA_API_KEY") or os.getenv("APCA_API_KEY_ID")
        alpaca_secret = os.getenv("ALPACA_SECRET_KEY") or os.getenv("APCA_API_SECRET_KEY")

        def _mask(value: str | None) -> str:
            if not value:
                return "(not set)"
            if len(value) <= 6:
                return "***"
            return value[:3] + "***" + value[-3:]

        lines = [
            "Execution Engine Effective Configuration:",
            "- Broker:                " + selected_broker,
            "- Default Account:       " + default_account,
            "- Account Selection:     "
            + ("supported" if capabilities.supports_account_selection else "single-account only"),
            "- Live Submit:           "
            + (
                "paper-only"
                if is_paper_broker(selected_broker)
                else "supported"
                if capabilities.supports_live_submit
                else "unsupported"
            ),
            "- Cancel / Query:        "
            + (
                "enabled"
                if capabilities.supports_cancel and capabilities.supports_order_query
                else "partial"
            ),
            "- Supported Order Types: " + ", ".join(capabilities.supported_order_types),
            "- Supported TIF:         " + ", ".join(capabilities.supported_time_in_force),
            "- Risk Max Notional:     "
            + _fmt_unlimited(float(risk_cfg.get("max_notional_per_order", 0.0) or 0.0)),
            "- Risk Max Quantity:     "
            + _fmt_unlimited(int(float(risk_cfg.get("max_qty_per_order", 0) or 0))),
            "- Risk Max Spread (bps): " + str(risk_cfg.get("max_spread_bps", 0) or 0),
            "- Risk Participation:    " + str(risk_cfg.get("max_participation_rate", 0) or 0),
            "- Kill Switch Env:       "
            + str(kill_switch_cfg.get("env_var") or "QEXEC_KILL_SWITCH"),
            "- Submit Mode:           "
            + str(
                capabilities.notes.get("submit_mode")
                or ("paper" if is_paper_broker(selected_broker) else "real")
            ),
        ]
        if is_longport_broker(selected_broker):
            longport_env_name = "paper" if selected_broker == "longport-paper" else "real"
            region, region_source = resolve_longport_runtime_value(
                ("LONGPORT_REGION", "LONGBRIDGE_REGION"),
                env_name=longport_env_name,
                default="hk",
            )
            overnight, overnight_source = resolve_longport_runtime_value(
                ("LONGPORT_ENABLE_OVERNIGHT", "LONGBRIDGE_ENABLE_OVERNIGHT"),
                env_name=longport_env_name,
                default="false",
            )
            local_max_notional = _getenv_both(
                "LONGPORT_MAX_NOTIONAL_PER_ORDER",
                "LONGBRIDGE_MAX_NOTIONAL_PER_ORDER",
                "0",
            )
            local_max_qty = _getenv_both(
                "LONGPORT_MAX_QTY_PER_ORDER", "LONGBRIDGE_MAX_QTY_PER_ORDER", "0"
            )
            tw_start = _getenv_both(
                "LONGPORT_TRADING_WINDOW_START",
                "LONGBRIDGE_TRADING_WINDOW_START",
                "09:30",
            )
            tw_end = _getenv_both(
                "LONGPORT_TRADING_WINDOW_END", "LONGBRIDGE_TRADING_WINDOW_END", "16:00"
            )
            credentials = probe_longport_credentials(longport_env_name)
            app_key = credentials.app_key
            app_secret = credentials.app_secret
            token = credentials.access_token
            app_key_source = credentials.app_key_source or "(not found)"
            app_secret_source = credentials.app_secret_source or "(not found)"
            token_source = credentials.access_token_source or "(not found)"
            resolved_region_source = region_source or "(default)"
            resolved_overnight_source = overnight_source or "(default)"
            lines.extend(
                [
                    "- Region:                " + region,
                    "- Region Source:         " + resolved_region_source,
                    "- Overnight:             "
                    + ("enabled" if _to_bool(overnight) else "disabled"),
                    "- Overnight Source:      " + resolved_overnight_source,
                    "- Local Max Notional:    "
                    + _fmt_unlimited(_to_float(local_max_notional, 0.0)),
                    "- Local Max Quantity:    " + _fmt_unlimited(_to_int(local_max_qty, 0)),
                    "- Trade Window:          " + f"{tw_start} - {tw_end}",
                    "- App Key:               " + _mask(app_key),
                    "- App Key Source:        " + app_key_source,
                    "- App Secret:            " + _mask(app_secret),
                    "- App Secret Source:     " + app_secret_source,
                    "- Access Token:          " + _mask(token),
                    "- Access Token Source:   " + token_source,
                ]
            )
        elif is_ibkr_broker(selected_broker):
            runtime_cfg = probe_ibkr_runtime_config()
            lines.extend(
                [
                    "- Runtime Stack:         " + runtime_cfg.runtime,
                    "- Gateway Host:          " + runtime_cfg.host,
                    "- Gateway Host Source:   " + runtime_cfg.host_source,
                    "- Paper Port:            " + str(runtime_cfg.port),
                    "- Paper Port Source:     " + runtime_cfg.port_source,
                    "- Client ID:             " + str(runtime_cfg.client_id),
                    "- Client ID Source:      " + runtime_cfg.client_id_source,
                    "- Account ID:            "
                    + (runtime_cfg.account_id or "(auto-detect via IB Gateway)"),
                    "- Account ID Source:     " + runtime_cfg.account_id_source,
                    "- Connect Timeout (s):   " + str(runtime_cfg.connect_timeout_seconds),
                    "- Timeout Source:        " + runtime_cfg.connect_timeout_source,
                    "- Market Scope:          US equities only",
                ]
            )
        elif selected_broker in {"alpaca", "alpaca-paper"}:
            lines.extend(
                [
                    "- Alpaca API Key:        " + _mask(alpaca_key),
                    "- Alpaca Secret:         " + _mask(alpaca_secret),
                ]
            )
        return CommandResult(exit_code=0, stdout="\n".join(lines))
    except Exception as exc:
        return CommandResult(exit_code=1, stderr=str(exc))


def run_evidence_maturity(fmt: str = "table") -> CommandResult:
    try:
        records = build_broker_evidence_maturity_report()
        if fmt == "json":
            return CommandResult(
                exit_code=0,
                stdout=render_json([record.to_payload() for record in records]),
            )
        return CommandResult(exit_code=0, stdout=render_broker_evidence_maturity(records))
    except Exception as exc:
        msg = f"Evidence maturity report failed: {exc}"
        get_logger(__name__).error(msg)
        return CommandResult(exit_code=1, stderr=msg)


def run_evidence_pack(
    *,
    run_id: str,
    output_dir: str | None = None,
    operator_notes: list[str] | None = None,
) -> CommandResult:
    try:
        result = create_evidence_bundle(
            run_id=run_id,
            output_dir=Path(output_dir) if output_dir else None,
            operator_notes=operator_notes,
        )
        exit_code = 1 if result.missing_count else 0
        return CommandResult(exit_code=exit_code, stdout=render_evidence_bundle_result(result))
    except EvidenceBundleError as exc:
        return CommandResult(exit_code=1, stderr=str(exc))
    except Exception as exc:
        msg = f"Evidence pack failed: {exc}"
        get_logger(__name__).error(msg)
        return CommandResult(exit_code=1, stderr=msg)


def run_exceptions(
    *,
    account: str = "main",
    broker: str | None = None,
    status_filter: str | None = None,
    symbol_filter: str | None = None,
) -> CommandResult:
    adapter = None
    try:
        adapter = get_broker_adapter(broker_name=broker)
        service = OrderLifecycleService(adapter)
        statuses = _resolve_exception_status_filter(status_filter)
        allowed_symbols = _resolve_symbol_filter(symbol_filter)
        records = service.list_exception_orders(
            account_label=account,
            statuses=statuses,
        )
        if allowed_symbols is not None:
            records = [
                record
                for record in records
                if _symbol_matches_filter(record.symbol, allowed_symbols)
            ]
        if not records and (status_filter or symbol_filter):
            filter_summary = _format_filter_summary(
                status_filter=status_filter,
                symbol_filter=symbol_filter,
            )
            return CommandResult(
                exit_code=0,
                stdout=f"No tracked execution exceptions matching filters: {filter_summary}",
            )
        return CommandResult(exit_code=0, stdout=render_exception_orders(records))
    except Exception as exc:
        msg = f"Failed to load tracked execution exceptions: {exc}"
        get_logger(__name__).error(msg)
        return CommandResult(exit_code=1, stderr=msg)
    finally:
        _close_broker_adapter(adapter)


def run_report(
    *,
    run_id: str | None = None,
    broker: str | None = None,
    last_n: int | None = None,
) -> CommandResult:
    """Generate a human-readable execution run report."""
    try:
        if run_id:
            report = get_run_report(run_id)
            return CommandResult(exit_code=0, stdout=render_run_report(report))
        reports = list_run_reports(broker_filter=broker, last_n=last_n)
        return CommandResult(exit_code=0, stdout=render_run_report_list(reports))
    except ReportError as exc:
        return CommandResult(exit_code=1, stderr=str(exc))
    except Exception as exc:
        return CommandResult(exit_code=1, stderr=f"Report failed: {exc}")


def run_health_cmd(
    *,
    broker: str | None = None,
    account: str = "main",
) -> CommandResult:
    """Run quick health check."""
    try:
        result = run_health(broker_name=broker, account_label=account)
        return CommandResult(
            exit_code=0 if result.healthy else 1,
            stdout=render_health_result(result),
        )
    except HealthCheckError as exc:
        return CommandResult(exit_code=1, stderr=str(exc))
    except Exception as exc:
        return CommandResult(exit_code=1, stderr=f"Health check failed: {exc}")
