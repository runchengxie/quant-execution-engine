"""IBKR runtime helpers and connection wrapper."""

from __future__ import annotations

import importlib
import os
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any

from .base import BrokerImportError, BrokerOrderRequest, BrokerValidationError


def _ibkr_import(path: str):
    module_name, _, attr_name = path.rpartition(".")
    try:
        module = importlib.import_module(module_name)
    except ImportError as exc:  # pragma: no cover - depends on optional package
        missing = getattr(exc, "name", None)
        if missing and missing not in {module_name, module_name.split(".")[0], "ib_insync"}:
            raise BrokerImportError(
                "ib_insync import failed because dependency "
                f"'{missing}' is missing. Install/update it with: uv sync --extra ibkr"
            ) from exc
        raise BrokerImportError(
            "ib_insync is not installed. Install it with: uv sync --extra ibkr"
        ) from exc
    return getattr(module, attr_name)


@dataclass(slots=True)
class IbkrRuntimeConfig:
    """Resolved non-secret IBKR runtime configuration."""

    host: str
    port: int
    client_id: int
    account_id: str | None
    connect_timeout_seconds: float
    runtime: str = "IB Gateway via TWS API"
    host_source: str = "(default)"
    port_source: str = "(default)"
    client_id_source: str = "(default)"
    account_id_source: str = "(default)"
    connect_timeout_source: str = "(default)"


def _env_value(names: tuple[str, ...], default: str | None = None) -> tuple[str | None, str]:
    for name in names:
        value = os.getenv(name)
        if value is not None and str(value).strip():
            return str(value).strip(), f"env ({name})"
    return default, "(default)"


def _int_env(names: tuple[str, ...], *, default: int) -> tuple[int, str]:
    raw, source = _env_value(names, str(default))
    try:
        return int(float(str(raw))), source
    except Exception as exc:  # pragma: no cover - defensive
        joined = "/".join(names)
        raise BrokerValidationError(f"invalid {joined} value: {raw}") from exc


def _float_env(names: tuple[str, ...], *, default: float) -> tuple[float, str]:
    raw, source = _env_value(names, str(default))
    try:
        return float(str(raw)), source
    except Exception as exc:  # pragma: no cover - defensive
        joined = "/".join(names)
        raise BrokerValidationError(f"invalid {joined} value: {raw}") from exc


def resolve_ibkr_runtime_config() -> IbkrRuntimeConfig:
    """Resolve the active IBKR paper runtime configuration."""

    host, host_source = _env_value(("IBKR_HOST",), "127.0.0.1")
    port, port_source = _int_env(("IBKR_PORT", "IBKR_PORT_PAPER"), default=4002)
    client_id, client_id_source = _int_env(("IBKR_CLIENT_ID",), default=1)
    account_id, account_id_source = _env_value(("IBKR_ACCOUNT_ID",), None)
    timeout, timeout_source = _float_env(
        ("IBKR_CONNECT_TIMEOUT_SECONDS",), default=5.0
    )
    return IbkrRuntimeConfig(
        host=str(host or "127.0.0.1"),
        port=port,
        client_id=client_id,
        account_id=account_id or None,
        connect_timeout_seconds=timeout,
        host_source=host_source,
        port_source=port_source,
        client_id_source=client_id_source,
        account_id_source=account_id_source,
        connect_timeout_source=timeout_source,
    )


def probe_ibkr_runtime_config() -> IbkrRuntimeConfig:
    """Return effective runtime configuration for operator-facing commands."""

    return resolve_ibkr_runtime_config()


class IbkrRuntime:
    """Thin wrapper around ib_insync for synchronous broker operations."""

    def __init__(
        self,
        *,
        config: IbkrRuntimeConfig | None = None,
        ib_client: Any | None = None,
    ) -> None:
        self.config = config or resolve_ibkr_runtime_config()
        self._ib = ib_client
        self._contract_cache: dict[str, Any] = {}
        self._account_id: str | None = None

    def _connect_error(self, exc: Exception) -> RuntimeError:
        return RuntimeError(
            "unable to connect to IB Gateway at "
            f"{self.config.host}:{self.config.port} for ibkr-paper: {exc}"
        )

    def _get_ib(self) -> Any:
        if self._ib is None:
            IB = _ibkr_import("ib_insync.IB")
            self._ib = IB()

        ib = self._ib
        is_connected = getattr(ib, "isConnected", None)
        if callable(is_connected) and is_connected():
            return ib
        if not hasattr(ib, "connect"):
            return ib
        try:
            ib.connect(
                host=self.config.host,
                port=self.config.port,
                clientId=self.config.client_id,
                timeout=self.config.connect_timeout_seconds,
            )
        except TypeError:
            ib.connect(
                self.config.host,
                self.config.port,
                self.config.client_id,
                timeout=self.config.connect_timeout_seconds,
            )
        except Exception as exc:  # pragma: no cover - depends on runtime state
            raise self._connect_error(exc) from exc

        is_connected = getattr(ib, "isConnected", None)
        if callable(is_connected) and not is_connected():
            raise self._connect_error(RuntimeError("connection did not become ready"))
        return ib

    def _sleep(self, seconds: float) -> None:
        ib = self._get_ib()
        sleep_fn = getattr(ib, "sleep", None)
        if callable(sleep_fn):
            sleep_fn(seconds)
            return
        time.sleep(seconds)

    def _managed_accounts(self) -> list[str]:
        ib = self._get_ib()
        managed = getattr(ib, "managedAccounts", None)
        if callable(managed):
            raw = managed()
        else:
            raw = managed or []
        return [str(account).strip() for account in raw if str(account).strip()]

    def _raw_account_values(self) -> list[Any]:
        summary = self._get_ib().accountSummary()
        return list(summary or [])

    def resolve_account_id(self) -> str | None:
        if self._account_id is not None:
            return self._account_id

        configured = str(self.config.account_id or "").strip() or None
        available = self._managed_accounts()
        if configured:
            if available and configured not in available:
                raise BrokerValidationError(
                    f"configured IBKR_ACCOUNT_ID '{configured}' is not available via IB Gateway"
                )
            self._account_id = configured
            return self._account_id

        if len(available) == 1:
            self._account_id = available[0]
            return self._account_id

        if len(available) > 1:
            raise BrokerValidationError(
                "multiple IBKR accounts detected; set IBKR_ACCOUNT_ID for ibkr-paper"
            )

        inferred = sorted(
            {
                str(getattr(value, "account", "")).strip()
                for value in self._raw_account_values()
                if str(getattr(value, "account", "")).strip()
            }
        )
        if len(inferred) == 1:
            self._account_id = inferred[0]
            return self._account_id
        if len(inferred) > 1:
            raise BrokerValidationError(
                "multiple IBKR accounts detected in account summary; set IBKR_ACCOUNT_ID"
            )
        self._account_id = None
        return None

    def normalize_symbol(self, symbol: str) -> str:
        cleaned = str(symbol).strip().upper()
        if not cleaned:
            raise BrokerValidationError("symbol must not be empty")
        if "." not in cleaned:
            return f"{cleaned}.US"
        base, suffix = cleaned.rsplit(".", 1)
        if not base:
            raise BrokerValidationError(f"invalid symbol: {symbol}")
        if suffix != "US":
            raise BrokerValidationError(
                "ibkr-paper only supports US equities in the initial slice: "
                f"{cleaned}"
            )
        return f"{base}.US"

    def canonical_symbol_for_contract(self, contract: Any) -> str | None:
        symbol = str(getattr(contract, "symbol", "")).strip().upper()
        sec_type = str(getattr(contract, "secType", "")).strip().upper()
        currency = str(getattr(contract, "currency", "")).strip().upper()
        if not symbol:
            return None
        if sec_type and sec_type != "STK":
            return None
        if currency and currency != "USD":
            return None
        return f"{symbol}.US"

    def qualify_stock(self, symbol: str) -> tuple[str, Any]:
        canonical = self.normalize_symbol(symbol)
        cached = self._contract_cache.get(canonical)
        if cached is not None:
            return canonical, cached

        Stock = _ibkr_import("ib_insync.Stock")
        contract = Stock(canonical[:-3], "SMART", "USD")
        qualified = list(self._get_ib().qualifyContracts(contract) or [])
        if not qualified:
            raise BrokerValidationError(f"unable to resolve IBKR contract for {canonical}")
        resolved = qualified[0]
        self._contract_cache[canonical] = resolved
        return canonical, resolved

    def request_tickers(self, symbols: list[str]) -> dict[str, Any]:
        resolved: list[tuple[str, Any]] = [self.qualify_stock(symbol) for symbol in symbols]
        if not resolved:
            return {}
        contracts = [contract for _, contract in resolved]
        tickers = list(self._get_ib().reqTickers(*contracts) or [])
        results: dict[str, Any] = {}
        for (canonical, _contract), ticker in zip(resolved, tickers):
            results[canonical] = ticker
        return results

    def get_account_values(self, account_id: str | None = None) -> list[Any]:
        selected_account = account_id or self.resolve_account_id()
        values = self._raw_account_values()
        if not selected_account:
            return values
        return [
            value
            for value in values
            if not str(getattr(value, "account", "")).strip()
            or str(getattr(value, "account", "")).strip() == selected_account
        ]

    def get_positions(self, account_id: str | None = None) -> list[Any]:
        selected_account = account_id or self.resolve_account_id()
        positions = list(self._get_ib().positions() or [])
        if not selected_account:
            return positions
        return [
            position
            for position in positions
            if str(getattr(position, "account", "")).strip() == selected_account
        ]

    def submit_order(
        self,
        contract: Any,
        request: BrokerOrderRequest,
        *,
        account_id: str | None = None,
    ) -> Any:
        quantity = float(request.quantity)
        if float(int(quantity)) != quantity:
            raise BrokerValidationError(
                "ibkr-paper currently only supports whole-share quantities"
            )
        qty = int(quantity)
        if request.order_type == "LIMIT":
            LimitOrder = _ibkr_import("ib_insync.LimitOrder")
            order = LimitOrder(request.side, qty, float(request.limit_price or 0.0))
        else:
            MarketOrder = _ibkr_import("ib_insync.MarketOrder")
            order = MarketOrder(request.side, qty)
        order.tif = request.time_in_force.upper()
        order.outsideRth = bool(request.extended_hours)
        resolved_account = account_id or self.resolve_account_id()
        if resolved_account:
            order.account = resolved_account
        if request.client_order_id:
            order.orderRef = request.client_order_id
        trade = self._get_ib().placeOrder(contract, order)
        self._sleep(0.2)
        return trade

    def _trade_order_id(self, trade: Any) -> str | None:
        order = getattr(trade, "order", None)
        order_id = getattr(order, "orderId", None)
        if order_id in (None, ""):
            return None
        return str(order_id)

    def _known_trades(self) -> list[Any]:
        ib = self._get_ib()
        trades: list[Any] = []
        for name, kwargs in (
            ("trades", {}),
            ("openTrades", {}),
            ("reqCompletedOrders", {"apiOnly": False}),
        ):
            method = getattr(ib, name, None)
            if not callable(method):
                continue
            try:
                payload = method(**kwargs)
            except TypeError:
                payload = method()
            except Exception:
                continue
            trades.extend(list(payload or []))
        deduped: dict[str, Any] = {}
        for trade in trades:
            order_id = self._trade_order_id(trade)
            if order_id is not None:
                deduped[order_id] = trade
        return list(deduped.values())

    def get_trade(self, broker_order_id: str) -> Any:
        normalized = str(broker_order_id).strip()
        for trade in self._known_trades():
            if self._trade_order_id(trade) == normalized:
                return trade
        raise RuntimeError(f"IBKR order not found: {normalized}")

    def list_open_trades(self, account_id: str | None = None) -> list[Any]:
        selected_account = account_id or self.resolve_account_id()
        method = getattr(self._get_ib(), "openTrades", None)
        trades = list(method() or []) if callable(method) else []
        if not selected_account:
            return trades
        filtered: list[Any] = []
        for trade in trades:
            order = getattr(trade, "order", None)
            account = str(getattr(order, "account", "")).strip()
            if not account or account == selected_account:
                filtered.append(trade)
        return filtered

    def cancel_order(self, broker_order_id: str) -> None:
        trade = self.get_trade(broker_order_id)
        self._get_ib().cancelOrder(getattr(trade, "order"))
        self._sleep(0.2)

    def list_fills(
        self,
        *,
        account_id: str | None = None,
        broker_order_id: str | None = None,
    ) -> list[Any]:
        selected_account = account_id or self.resolve_account_id()
        method = getattr(self._get_ib(), "reqExecutions", None)
        fills = list(method() or []) if callable(method) else []
        results: list[Any] = []
        expected_order_id = None if broker_order_id is None else str(broker_order_id).strip()
        for fill in fills:
            execution = getattr(fill, "execution", None)
            contract = getattr(fill, "contract", None)
            if execution is None or contract is None:
                continue
            fill_account = str(getattr(execution, "acctNumber", "")).strip()
            if selected_account and fill_account and fill_account != selected_account:
                continue
            order_id = str(getattr(execution, "orderId", "")).strip()
            if expected_order_id is not None and order_id != expected_order_id:
                continue
            results.append(fill)
        return results

    def close(self) -> None:
        if self._ib is None:
            return
        is_connected = getattr(self._ib, "isConnected", None)
        if callable(is_connected) and not is_connected():
            return
        disconnect = getattr(self._ib, "disconnect", None)
        if callable(disconnect):
            disconnect()


def coerce_iso(value: Any) -> str:
    """Normalize IBKR time-like payloads to ISO-8601 UTC text."""

    if value in (None, ""):
        return datetime.now(timezone.utc).isoformat()
    if isinstance(value, datetime):
        parsed = value
    else:
        try:
            parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
        except Exception:
            return str(value)
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc).isoformat()
