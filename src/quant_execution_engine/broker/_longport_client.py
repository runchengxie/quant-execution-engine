"""LongPort trading client implementation.

Previously the ``LongPortClient`` class lived inside ``broker/longport.py``.
It is extracted here to keep that module a thin, test-friendly re-export shell.

SDK enum symbols (``OrderType``, ``OrderSide``, ``TimeInForceType``,
``Config``, ``Market``) are accessed through ``quant_execution_engine.broker.longport``
(via the module alias ``_lp``) rather than imported directly. This preserves the
behaviour expected by tests that ``monkeypatch`` those names on the ``longport``
module (e.g. ``patch("quant_execution_engine.broker.longport.OrderType")``).
"""

from __future__ import annotations

import os
import time
from collections.abc import Iterable
from datetime import date, datetime
from decimal import Decimal
from typing import Any
from zoneinfo import ZoneInfo

from ..logging import get_logger
from ..models import Quote
from . import longport as _lp
from ._longport_helpers import (
    _cash_snapshot_from_asset,
    _default_broker_limits_from_env,
    _extended_hours_enabled,
    _LazyContext,
    _make_longport_context_factory,
    _market_enum,
    _stock_position_map_from_response,
)
from .longport_credentials import (
    resolve_longport_credentials,
    resolve_longport_runtime_value,
)
from .longport_support import (
    BrokerLimits,
    Env,
    getenv_both,
)
from .longport_support import (
    coerce_iso as _coerce_iso,
)
from .longport_support import (
    market_of as _market_of,
)
from .longport_support import (
    market_tz as _market_tz,
)
from .longport_support import (
    to_lb_symbol as _to_lb_symbol,
)

logger = get_logger(__name__)


class LongPortClient:
    """LongPort client for stock trading and querying.

    Provides a unified interface to access LongPort's trading and quote functionality.
    """

    def __init__(self, env: str | None = None, limits: BrokerLimits | None = None, config=None):
        """Initialize LongPort client.

        Args:
            config: LongPort configuration object, if None then read from environment variables
        """
        _lp._ensure_longport_sdk_installed()
        requested_env = str(env or "real").strip().lower()
        self.env = Env.PAPER if requested_env == "paper" else Env.REAL
        self.region, _region_source = resolve_longport_runtime_value(
            ("LONGPORT_REGION", "LONGBRIDGE_REGION"),
            env_name=self.env.value,
            default="hk",
        )
        credentials = resolve_longport_credentials(self.env.value)
        self.app_key = credentials.app_key
        self.app_secret = credentials.app_secret
        self.token_test = (
            credentials.access_token
            if self.env == Env.PAPER
            else getenv_both("LONGPORT_ACCESS_TOKEN_TEST", "LONGBRIDGE_ACCESS_TOKEN_TEST")
        )
        self.token_real = (
            credentials.access_token
            if self.env == Env.REAL
            else os.getenv("LONGPORT_ACCESS_TOKEN") or os.getenv("LONGPORT_ACCESS_TOKEN_REAL")
        )
        access_token = credentials.access_token

        # Inject token/region via environment variables, then use SDK's
        # from_env to select the correct endpoint and default config.
        self._prev_env = {
            "LONGPORT_APP_KEY": os.getenv("LONGPORT_APP_KEY"),
            "LONGPORT_APP_SECRET": os.getenv("LONGPORT_APP_SECRET"),
            "LONGPORT_ACCESS_TOKEN": os.getenv("LONGPORT_ACCESS_TOKEN"),
            "LONGPORT_ACCESS_TOKEN_TEST": os.getenv("LONGPORT_ACCESS_TOKEN_TEST"),
            "LONGPORT_REGION": os.getenv("LONGPORT_REGION"),
        }
        os.environ["LONGPORT_APP_KEY"] = self.app_key
        os.environ["LONGPORT_APP_SECRET"] = self.app_secret
        os.environ["LONGPORT_ACCESS_TOKEN"] = access_token
        if self.env == Env.PAPER:
            os.environ["LONGPORT_ACCESS_TOKEN_TEST"] = access_token
        if self.region:
            os.environ["LONGPORT_REGION"] = self.region
        # Uniformly use SDK recommended from_env to ensure correct region and routing
        self.config = _lp.Config.from_env()

        # Lazily construct quote/trade contexts to avoid failing at init time
        # in environments with intermittent connectivity or region mismatch.
        # Use lightweight wrappers that only create the underlying contexts
        # when a method is actually invoked.

        self.quote = _LazyContext(_make_longport_context_factory(self.region, "quote"))
        self.trade = _LazyContext(_make_longport_context_factory(self.region, "trade"))
        # Backward compatible attribute names expected by older code/tests
        self.q = self.quote
        self.t = self.trade

        # Build limits from env if not explicitly provided. 0 means unlimited.
        self.limits = limits if limits is not None else _default_broker_limits_from_env()

        self.allow_extended = _extended_hours_enabled(self.env.value)

        # Cache related
        self._session_cache: dict[str, list[tuple[int, int, str]]] = {}
        self._session_cache_expire_at: float = 0.0
        self._is_trading_day_cache: dict[str, bool] = {}
        self._day_cache_expire_at: float = 0.0
        self._cache_ttl_seconds: int = 600

    def _quote_context(self):
        quote_ctx = getattr(self, "q", None) or getattr(self, "quote", None)
        if quote_ctx is None:
            raise AttributeError("Quote context not initialised")
        return quote_ctx

    def _trade_context(self):
        trade_ctx = getattr(self, "t", None) or getattr(self, "trade", None)
        if trade_ctx is None:
            raise AttributeError("Trade context not initialised")
        return trade_ctx

    def _account_asset(self) -> tuple[object | None, Exception | None]:
        trade_ctx = self._trade_context()
        last_err: Exception | None = None
        for fn_name in ("asset", "account_balance"):
            fn = getattr(trade_ctx, fn_name, None)
            if not fn:
                continue
            try:
                return fn(), None
            except Exception as e:  # pragma: no cover - depends on live SDK/network
                last_err = e
                logger.debug(f"调用 {fn_name}() 获取资金失败: {e}")
        return None, last_err

    def _submit_order(
        self,
        *,
        symbol: str,
        order_type: _lp.OrderType,
        quantity: float,
        price: float | None = None,
        tif: _lp.TimeInForceType | None = None,
        remark: str | None = None,
    ):
        trade_ctx = self._trade_context()
        side = _lp.OrderSide.Buy if quantity >= 0 else _lp.OrderSide.Sell
        payload = {
            "symbol": _to_lb_symbol(symbol),
            "order_type": order_type,
            "side": side,
            "submitted_quantity": Decimal(str(abs(quantity))),
            "time_in_force": tif or _lp.TimeInForceType.Day,
            "remark": remark,
        }
        if price is not None:
            payload["submitted_price"] = Decimal(str(price))
        return trade_ctx.submit_order(**payload)

    # ---------- Quote Data ----------
    def quote_last(self, symbols: Iterable[str]) -> dict[str, tuple[float, str]]:
        """Get last quotes for given symbols.

        Args:
            symbols: List of ticker symbols

        Returns:
            Dict mapping symbol to (last_price, timestamp) tuple
        """
        bars: dict[str, tuple[float, str]] = {}
        symbol_list = [_to_lb_symbol(x) for x in symbols]
        quote_ctx = self._quote_context()
        ret = quote_ctx.quote(symbol_list)
        for i in ret:
            # Prefer last_done, fallback to prev_close if missing/zero
            px = float(str((getattr(i, "last_done", 0) or 0) or 0))
            if px <= 0:
                prev = getattr(i, "prev_close", None)
                if prev not in (None, 0):
                    try:
                        px = float(str(prev))
                    except Exception:
                        px = 0.0
            bars[i.symbol] = (px, getattr(i, "timestamp", "") or "")
        return bars

    def quote_snapshot(
        self, symbols: Iterable[str], *, include_depth: bool = False
    ) -> dict[str, Quote]:
        """Return richer quote snapshots with optional bid/ask depth."""

        quote_ctx = self._quote_context()

        symbol_list = [_to_lb_symbol(symbol) for symbol in symbols]
        quotes = quote_ctx.quote(symbol_list)
        depth_map: dict[str, tuple[float | None, float | None]] = {}
        if include_depth:
            for symbol in symbol_list:
                try:
                    depth = quote_ctx.depth(symbol)
                    bid = None
                    ask = None
                    if getattr(depth, "bids", None):
                        bid_raw = getattr(depth.bids[0], "price", None)
                        bid = float(bid_raw) if bid_raw is not None else None
                    if getattr(depth, "asks", None):
                        ask_raw = getattr(depth.asks[0], "price", None)
                        ask = float(ask_raw) if ask_raw is not None else None
                    depth_map[symbol] = (bid, ask)
                except Exception:
                    depth_map[symbol] = (None, None)

        result: dict[str, Quote] = {}
        for item in quotes:
            price = float(str((getattr(item, "last_done", 0) or 0) or 0))
            if price <= 0:
                prev_close = getattr(item, "prev_close", None)
                if prev_close not in (None, 0):
                    price = float(str(prev_close))
            bid, ask = depth_map.get(item.symbol, (None, None))
            result[item.symbol] = Quote(
                symbol=item.symbol,
                price=price,
                timestamp=_coerce_iso(getattr(item, "timestamp", "")),
                bid=bid,
                ask=ask,
                daily_volume=float(getattr(item, "volume", 0) or 0),
            )
        return result

    def candles(
        self,
        symbol: str,
        start: date,
        end: date,
        period,
        adjust: int | None = None,
    ):
        """Fetch historical candle data for a symbol.

        Parameters mirror the underlying SDK's ``history_candlesticks_by_date``
        call; the method mainly ensures the ticker is converted to the
        LongPort format and that parameters are forwarded correctly.
        """

        quote_ctx = self._quote_context()
        lb_symbol = _to_lb_symbol(symbol)
        market = _market_enum(_market_of(lb_symbol))
        return quote_ctx.history_candlesticks_by_date(lb_symbol, period, market, start, end, adjust)

    def submit_limit(
        self,
        symbol: str,
        price: float,
        quantity: float,
        tif: _lp.TimeInForceType | None = None,
        remark: str | None = None,
    ):
        """Submit a limit order.

        The sign of ``quantity`` determines the order side: positive for buy
        orders and negative for sell orders. ``quantity`` is converted to its
        absolute value when sending to the broker. ``price`` and ``quantity``
        are converted to ``Decimal`` to avoid floating point issues.
        """

        return self._submit_order(
            symbol=symbol,
            order_type=_lp.OrderType.LO,
            quantity=quantity,
            price=price,
            tif=tif,
            remark=remark,
        )

    def submit_market(
        self,
        symbol: str,
        quantity: float,
        tif: _lp.TimeInForceType | None = None,
        remark: str | None = None,
    ):
        """Submit a market order."""

        return self._submit_order(
            symbol=symbol,
            order_type=_lp.OrderType.MO,
            quantity=quantity,
            tif=tif,
            remark=remark,
        )

    def get_order_detail(self, order_id: str):
        """Return detailed order state."""

        trade_ctx = self._trade_context()
        return trade_ctx.order_detail(order_id)

    def cancel_order_by_id(self, order_id: str) -> None:
        """Cancel an order by broker order id."""

        trade_ctx = self._trade_context()
        trade_ctx.cancel_order(order_id)

    def list_orders(
        self,
        *,
        symbol: str | None = None,
        order_id: str | None = None,
        include_history: bool = False,
    ) -> list[Any]:
        """List orders, defaulting to today's open-order surface."""

        trade_ctx = self._trade_context()
        symbol_fmt = _to_lb_symbol(symbol) if symbol else None
        if include_history:
            return list(trade_ctx.history_orders(symbol=symbol_fmt))
        return list(trade_ctx.today_orders(symbol=symbol_fmt, order_id=order_id))

    def list_executions(
        self,
        *,
        symbol: str | None = None,
        order_id: str | None = None,
        include_history: bool = False,
    ) -> list[Any]:
        """List fill/execution events."""

        trade_ctx = self._trade_context()
        symbol_fmt = _to_lb_symbol(symbol) if symbol else None
        if include_history:
            return list(trade_ctx.history_executions(symbol=symbol_fmt))
        return list(trade_ctx.today_executions(symbol=symbol_fmt, order_id=order_id))

    def portfolio_snapshot(
        self,
    ) -> tuple[float, dict[str, int], float | None, str | None]:
        """
        Get account snapshot including cash and position information.

        Returns:
            Tuple of (cash_usd, stock_position_map, net_assets, base_currency)
            - cash_usd: USD available cash only (no FX conversion)
            - stock_position_map: {'AAPL.US': 100, ...}
            - net_assets: Total assets from broker (multi-currency/positions), if available
            - base_currency: Currency of net_assets (e.g. 'HKD')

        Compatible with different SDK versions of asset/balance and
        stock_positions/position_list return formats.
        """
        cash_usd = 0.0
        pos_map: dict[str, int] = {}
        net_assets: float | None = None
        base_ccy: str | None = None

        asset, last_err = self._account_asset()
        if asset is None:
            if last_err is not None:
                logger.warning(f"无法获取账户资金信息，视为0（原因: {last_err}）")
        else:
            cash_usd, net_assets, base_ccy = _cash_snapshot_from_asset(asset)

        try:
            trade_ctx = self._trade_context()
            pos_fn = getattr(trade_ctx, "stock_positions", None) or getattr(
                trade_ctx, "position_list", None
            )
            if not pos_fn:
                return cash_usd, pos_map, net_assets, base_ccy
            pos_map = _stock_position_map_from_response(pos_fn())
        except Exception as e:
            logger.warning(f"获取持仓信息失败: {e}")

        return cash_usd, pos_map, net_assets, base_ccy

    def fund_positions(self) -> dict[str, tuple[float, float, str]]:
        """
        Get fund position information.

        Returns:
            Fund position mapping: { symbol => (holding_units, current_nav, currency) }
            - symbol: Fund code/ISIN returned by LongPort
            - holding_units: Holding units (float)
            - current_nav: Current net asset value (float)
            - currency: Currency code
        """
        result: dict[str, tuple[float, float, str]] = {}
        try:
            fn = getattr(self._trade_context(), "fund_positions", None)
            if not fn:
                return result
            resp = fn()
            # Format: resp.list[account].fund_info[*]
            accounts = getattr(resp, "list", None) or []
            for acc in accounts:
                fund_info = getattr(acc, "fund_info", None) or []
                for it in fund_info:
                    sym = (
                        getattr(it, "symbol", None)
                        if not isinstance(it, dict)
                        else it.get("symbol")
                    )
                    units = (
                        getattr(it, "holding_units", None)
                        if not isinstance(it, dict)
                        else it.get("holding_units")
                    )
                    nav = (
                        getattr(it, "current_net_asset_value", None)
                        if not isinstance(it, dict)
                        else it.get("current_net_asset_value")
                    )
                    ccy = (
                        getattr(it, "currency", None)
                        if not isinstance(it, dict)
                        else it.get("currency")
                    )
                    if sym is None or units is None or nav is None:
                        continue
                    try:
                        u = float(units)
                        p = float(nav)
                    except Exception:
                        continue
                    result[str(sym)] = (u, p, str(ccy or ""))
        except Exception as e:
            # Failure to get fund positions doesn't affect main flow
            logger.warning(f"获取基金持仓失败: {e}")
        return result

    def lot_size(self, symbol: str) -> int:
        """Get the lot size (shares per lot) for a stock.

        Args:
            symbol: Stock symbol

        Returns:
            Shares per lot
        """
        # Fast path: US stocks default to 1, avoiding static-info permission noise.
        if _market_of(symbol) == "US":
            return 1
        try:
            info = self.quote.static_info([_to_lb_symbol(symbol)])
            if info and info[0].lot_size:
                return max(1, int(info[0].lot_size))
        except Exception as e:
            logger.warning(f"获取 {symbol} 的 lot size 失败: {e}")
        return 1

    # ---------- Internal: Authoritative market info caching ----------
    def _refresh_caches_if_needed(self) -> None:
        """Refresh trading session and trading day cache if expired."""
        now_ts = time.time()
        # Refresh trading session cache
        if now_ts >= self._session_cache_expire_at:
            try:
                resp = self.quote.trading_session()
                session_map: dict[str, list[tuple[int, int, str]]] = {}
                for item in getattr(resp, "market_trade_session", []) or []:
                    market = getattr(item, "market", "").upper()
                    sessions = []
                    for seg in getattr(item, "trade_session", []) or []:
                        beg = int(getattr(seg, "beg_time", 0))  # hhmm
                        end = int(getattr(seg, "end_time", 0))  # hhmm
                        code = getattr(seg, "trade_session", None)
                        # Convention: None/0 => Regular, 1 => Pre, 2 => Post,
                        # 3 => Overnight when supported.
                        if code in (None, 0):
                            kind = "Regular"
                        elif code == 1:
                            kind = "Pre"
                        elif code == 2:
                            kind = "Post"
                        elif code == 3:
                            kind = "Overnight"
                        else:
                            kind = "Other"
                        sessions.append((beg, end, kind))
                    if market:
                        session_map[market] = sessions
                self._session_cache = session_map
                self._session_cache_expire_at = now_ts + self._cache_ttl_seconds
            except Exception:
                # Clear and expire immediately when unavailable, leave to fallback logic
                self._session_cache = {}
                self._session_cache_expire_at = 0.0

        # Refresh "is today a trading day" cache (by market)
        if now_ts >= self._day_cache_expire_at:
            try:
                date.today()
                # We only populate when a market is used, clear first
                self._is_trading_day_cache = {}
                self._day_cache_expire_at = now_ts + self._cache_ttl_seconds
            except Exception:
                self._is_trading_day_cache = {}
                self._day_cache_expire_at = 0.0

    def _is_trading_day(self, market_str: str) -> bool:
        # Check cache first
        if market_str in self._is_trading_day_cache:
            return self._is_trading_day_cache[market_str]
        try:
            today = date.today()
            resp = self.quote.trading_days(_market_enum(market_str), today, today)
            days = set(getattr(resp, "trade_day", []) or [])
            # API returns YYMMDD string, simply check if today is in it
            yymmdd = today.strftime("%Y%m%d")[2:]  # Convert to YYMMDD
            ok = yymmdd in days
            self._is_trading_day_cache[market_str] = ok
            return ok
        except Exception:
            # API failure: conservatively return False (fail closed)
            self._is_trading_day_cache[market_str] = False
            return False

    # ---------- Pre-order checks ----------
    def _check_window(self, symbol: str) -> None:
        """Check if current time is within trading window.

        Uses LongPort authoritative trading session and trading day interface.
        Falls back to local time estimation if the interface is unavailable.
        """
        self._refresh_caches_if_needed()

        symbol_fmt = _to_lb_symbol(symbol)
        market_str = _market_of(symbol_fmt)

        # 1) Reject if not a trading day
        if not self._is_trading_day(market_str):
            raise RuntimeError("非交易日，禁止交易")

        # 2) Authoritative segment determination
        sessions = self._session_cache.get(market_str, [])
        if sessions:
            tz = ZoneInfo(_market_tz(market_str))
            now_ex = datetime.now(tz)
            hhmm = now_ex.hour * 100 + now_ex.minute

            # Allowed segments
            def allowed(kind: str) -> bool:
                if kind == "Regular":
                    return True
                # Pre/Post/Overnight: only allow when extended hours are enabled
                return self.allow_extended and (kind in {"Pre", "Post", "Overnight", "Other"})

            in_any = any(beg <= hhmm <= end and allowed(kind) for beg, end, kind in sessions)
            if not in_any:
                allowed_kinds = {k for _, _, k in sessions if allowed(k)}
                win = (
                    ", ".join(
                        [
                            f"{beg:04d}-{end:04d}({k})"
                            for beg, end, k in sessions
                            if k in allowed_kinds
                        ]
                    )
                    or "无"
                )
                raise RuntimeError(f"不在允许的交易时段：{win}")
            return

        # 3) Fallback: rough local time string check (original logic)
        now_local = datetime.now().strftime("%H:%M")
        if not (self.limits.trading_window_start <= now_local <= self.limits.trading_window_end):
            raise RuntimeError(
                "不在交易时段 "
                f"{self.limits.trading_window_start}-{self.limits.trading_window_end}"
                "（降级判定）"
            )

    def _check_lot(self, symbol: str, qty: int) -> None:
        """Check if quantity is valid lot size."""
        sec = self.quote.static_info([symbol])[0]
        lot = max(1, sec.lot_size or 1)
        if qty % lot != 0:
            raise RuntimeError(f"{symbol} 数量需为最小交易单位 {lot} 的整数倍")

    # ---------- Order placement (market order equal weight example) ----------
    def place_order(
        self,
        symbol: str,
        qty: int,
        side: str,
        dry_run: bool = True,
        est_px: float | None = None,
    ) -> dict:
        """Place order with risk controls.

        Args:
            symbol: Stock symbol
            qty: Quantity to trade
            side: Order side (BUY/SELL)
            dry_run: If True, only simulate the order

        Returns:
            Order result dictionary
        """
        if qty <= 0:
            raise ValueError("下单数量必须为正")

        symbol_formatted = _to_lb_symbol(symbol)

        # Dry run or TEST: skip time window check, but keep lot and amount estimation
        if dry_run:
            lot = self.lot_size(symbol_formatted)
            if qty % lot != 0:
                raise RuntimeError(f"{symbol_formatted} 数量需为最小交易单位 {lot} 的整数倍")
            px = (
                float(est_px)
                if est_px is not None
                else self.quote_last([symbol]).get(symbol_formatted, (0.0, ""))[0]
            )
            notional = px * qty
            # Do not enforce local notional cap in dry run; broker will enforce actual limits.
            if (
                self.limits.max_notional_per_order
                and self.limits.max_notional_per_order > 0
                and notional > self.limits.max_notional_per_order
            ):
                logger.warning(
                    "估算成交金额 %.2f 超过本地预设上限 %.0f，继续（干跑模式不拦截）",
                    notional,
                    self.limits.max_notional_per_order,
                )
            return {
                "env": self.env.value,
                "dry_run": True,
                "symbol": symbol_formatted,
                "qty": qty,
                "side": side,
                "est_px": px,
                "est_notional": notional,
                "ts": time.time(),
            }

        # Real order: strict checks
        self._check_window(symbol_formatted)  # Original logic called here again
        self._check_lot(symbol_formatted, qty)
        if self.limits.max_qty_per_order and qty > self.limits.max_qty_per_order:
            raise RuntimeError(f"超过单笔数量上限 {self.limits.max_qty_per_order}")
        px = (
            float(est_px)
            if est_px is not None
            else self.quote_last([symbol]).get(symbol_formatted, (0.0, ""))[0]
        )
        notional = px * qty
        # Do not enforce local notional cap; rely on broker-side risk control instead.
        if (
            self.limits.max_notional_per_order
            and self.limits.max_notional_per_order > 0
            and notional > self.limits.max_notional_per_order
        ):
            logger.warning(
                "估算成交金额 %.2f 超过本地预设上限 %.0f，继续下单（以券商风控为准）",
                notional,
                self.limits.max_notional_per_order,
            )

        response = self.submit_market(
            symbol_formatted,
            qty if side.upper() == "BUY" else -qty,
            remark=f"qexec:{side.upper()}:{qty}",
        )
        return {
            "env": self.env.value,
            "dry_run": False,
            "symbol": symbol_formatted,
            "qty": qty,
            "side": side,
            "est_px": px,
            "est_notional": notional,
            "ts": time.time(),
            "success": True,
            "order_id": getattr(response, "order_id", None),
        }

    def close(self):
        """Close quote and trade contexts without requiring SDK close support."""
        for ctx in (self.quote, self.trade):
            try:
                fn = getattr(ctx, "close", None)
                if callable(fn):
                    fn()
            except Exception:
                # Ignore close exceptions to avoid affecting main flow
                pass
        # Restore environment variables to avoid affecting later instances.
        try:
            for k, v in (getattr(self, "_prev_env", {}) or {}).items():
                if v is None:
                    os.environ.pop(k, None)
                else:
                    os.environ[k] = v
        except Exception:
            # Any restoration failure should not affect the caller
            pass
