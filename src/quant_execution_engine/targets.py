"""Targets JSON utilities.

Defines the canonical, market-aware targets format used by rebalance execution.
"""

from __future__ import annotations

import json
import math
from collections.abc import Sequence
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

SCHEMA_VERSION = 2
CN_SYMBOL_SUFFIXES = {"SH", "SZ", "BJ", "XSHG", "XSHE"}
CN_CANONICAL_SUFFIX = {"SH": "SH", "SZ": "SZ", "BJ": "BJ", "XSHG": "SH", "XSHE": "SZ"}
KNOWN_MARKETS = {"US", "HK", "CN", "SG"}

_EXECUTION_MARKET_SUFFIXES = {
    ".HK": "HK",
    ".XHKG": "HK",
    ".US": "US",
    ".CN": "CN",
    ".SH": "CN",
    ".SZ": "CN",
    ".BJ": "CN",
    ".XSHG": "CN",
    ".XSHE": "CN",
}


def resolve_target_output_path(value: str | Path) -> Path:
    """Resolve a targets artifact path relative to the current working directory."""
    path = Path(value).expanduser()
    return path.resolve() if path.is_absolute() else (Path.cwd() / path).resolve()


@dataclass(frozen=True, slots=True)
class TargetPruningResult:
    """Result of applying execution-target weight pruning rules."""

    retained_indices: tuple[int, ...]
    output_weights: tuple[float, ...]
    metadata: dict[str, object]


def prune_target_weights(
    weights: Sequence[float],
    *,
    min_target_weight: float | None = None,
    cumulative_target_weight: float | None = None,
    renormalize_target_weights: bool = False,
) -> TargetPruningResult:
    """Apply minimum and cumulative weight rules in stable input order.

    The returned indices refer to the original sequence.  The cumulative rule
    keeps the first item crossing the requested limit so the result does not
    silently exclude the target boundary.
    """
    values = tuple(float(value) for value in weights)
    if not values:
        raise ValueError("target pruning requires at least one weight")
    if any(not math.isfinite(value) for value in values):
        raise ValueError("target weights must be finite")
    if any(value < 0 for value in values):
        raise ValueError("target weights must be non-negative")
    if min_target_weight is not None and (
        min_target_weight < 0 or not math.isfinite(float(min_target_weight))
    ):
        raise ValueError("min_target_weight must be finite and non-negative")
    if cumulative_target_weight is not None and (
        cumulative_target_weight <= 0
        or cumulative_target_weight > 1.0
        or not math.isfinite(float(cumulative_target_weight))
    ):
        raise ValueError("cumulative_target_weight must be finite and in (0, 1]")

    original_weight_sum = sum(values)
    eligible = [
        index
        for index, value in enumerate(values)
        if min_target_weight is None or value >= float(min_target_weight)
    ]
    retained = eligible
    if cumulative_target_weight is not None:
        if not eligible:
            raise ValueError("target pruning removed every holding")
        ordered = sorted(eligible, key=lambda index: (-values[index], index))
        running = 0.0
        retained_set: set[int] = set()
        crossing_index: int | None = None
        for index in ordered:
            running += values[index]
            if running <= float(cumulative_target_weight):
                retained_set.add(index)
            if crossing_index is None and running >= float(cumulative_target_weight):
                crossing_index = index
                break
        if crossing_index is not None:
            retained_set.add(crossing_index)
        else:
            retained_set.update(ordered)
        retained = [index for index in eligible if index in retained_set]

    if not retained:
        raise ValueError("target pruning removed every holding")
    retained_weight_sum = sum(values[index] for index in retained)
    output = [values[index] for index in retained]
    if renormalize_target_weights:
        output = [value * original_weight_sum / retained_weight_sum for value in output]
    output_weight_sum = sum(output)
    return TargetPruningResult(
        retained_indices=tuple(retained),
        output_weights=tuple(output),
        metadata={
            "enabled": bool(
                min_target_weight is not None
                or cumulative_target_weight is not None
                or renormalize_target_weights
            ),
            "min_target_weight": min_target_weight,
            "cumulative_target_weight": cumulative_target_weight,
            "renormalize_target_weights": renormalize_target_weights,
            "input_count": len(values),
            "input_weight_sum": original_weight_sum,
            "retained_count": len(retained),
            "retained_weight_sum_before_renormalization": retained_weight_sum,
            "dropped_count": len(values) - len(retained),
            "dropped_weight_sum": max(0.0, original_weight_sum - retained_weight_sum),
            "output_weight_sum": output_weight_sum,
            "cash_weight_from_pruning": max(0.0, original_weight_sum - output_weight_sum),
        },
    )


def normalize_execution_symbol(
    symbol: object,
    market: object | None = None,
) -> tuple[str, str]:
    """Normalize a symbol and market for execution-facing artifacts.

    Exchange suffixes are accepted on input. Chinese symbols are zero-padded
    to six digits, and Hong Kong numeric symbols are emitted without leading
    zeroes, matching broker-facing target formats.
    """

    text = str(symbol or "").strip().upper()
    if not text:
        raise ValueError("execution target symbol cannot be empty")

    requested_market = _normalize_market(str(market or "")) or None
    if requested_market is not None and requested_market not in KNOWN_MARKETS:
        raise ValueError(f"unsupported execution target market: {market!r}")

    for suffix, suffix_market in _EXECUTION_MARKET_SUFFIXES.items():
        if not text.endswith(suffix):
            continue
        if requested_market is not None and requested_market != suffix_market:
            raise ValueError(
                f"execution target symbol {text!r} conflicts with market {requested_market!r}"
            )
        base = text[: -len(suffix)]
        if suffix_market == "CN":
            canonical_suffix = {".XSHG": ".SH", ".XSHE": ".SZ"}.get(suffix, suffix)
            if base.isdigit():
                base = base.zfill(6)
            return f"{base}{canonical_suffix}", suffix_market
        if suffix_market == "HK" and base.isdigit():
            base = base.lstrip("0") or "0"
        return base, suffix_market

    if requested_market is None:
        raise ValueError(f"cannot infer execution target market for symbol {text!r}")
    if requested_market == "HK" and text.isdigit():
        text = text.lstrip("0") or "0"
    return text, requested_market


def _canonical_cn_symbol(base: str, suffix: str | None = None) -> str:
    base_text = str(base or "").upper().strip()
    suffix_text = str(suffix or "").upper().strip()
    if suffix_text in {"XSHG", "XSHE"}:
        suffix_text = CN_CANONICAL_SUFFIX[suffix_text]
    if suffix_text in {"SH", "SZ", "BJ"}:
        if base_text.isdigit():
            base_text = base_text.zfill(6)
        return f"{base_text}.{suffix_text}"
    return base_text


def _normalize_market(value: str) -> str:
    raw = str(value or "").upper().strip()
    return {"A_SHARE": "CN", "ASHARE": "CN", "CN_A": "CN"}.get(raw, raw)


def _split_symbol_market(
    symbol: str, market: str | None = None, *, default_market: str = "US"
) -> tuple[str, str]:
    raw_symbol = str(symbol or "").upper().strip()
    raw_market = _normalize_market(str(market or ""))

    if raw_market:
        if "." in raw_symbol:
            base, suffix = raw_symbol.rsplit(".", 1)
            if suffix in KNOWN_MARKETS:
                raw_symbol = base
            elif suffix in CN_SYMBOL_SUFFIXES and raw_market == "CN":
                raw_symbol = _canonical_cn_symbol(base, suffix)
        return raw_symbol, raw_market

    if "." in raw_symbol:
        base, suffix = raw_symbol.rsplit(".", 1)
        if suffix in KNOWN_MARKETS:
            return base, suffix
        if suffix in CN_SYMBOL_SUFFIXES:
            return _canonical_cn_symbol(base, suffix), "CN"

    return raw_symbol, _normalize_market(str(default_market or "US")) or "US"


@dataclass(slots=True)
class TargetEntry:
    """Canonical target entry."""

    symbol: str
    market: str
    target_weight: float | None = None
    target_quantity: float | None = None
    notes: str | None = None
    metadata: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        self.symbol, self.market = _split_symbol_market(self.symbol, self.market)
        if not self.symbol:
            raise ValueError("target symbol cannot be empty")
        if self.market not in KNOWN_MARKETS:
            raise ValueError(f"unsupported market: {self.market}")

        has_weight = self.target_weight is not None
        has_quantity = self.target_quantity is not None
        if has_weight == has_quantity:
            raise ValueError(
                "each target entry must define exactly one of target_weight or target_quantity"
            )

        if self.target_weight is not None:
            self.target_weight = float(self.target_weight)
            if self.target_weight < 0:
                raise ValueError("target_weight cannot be negative")

        if self.target_quantity is not None:
            self.target_quantity = float(self.target_quantity)
            if self.target_quantity < 0:
                raise ValueError("target_quantity cannot be negative")

        self.notes = self.notes or None
        self.metadata = dict(self.metadata or {})

    @property
    def key(self) -> str:
        return f"{self.symbol}.{self.market}"

    def to_payload(self) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "symbol": self.symbol,
            "market": self.market,
        }
        if self.target_weight is not None:
            payload["target_weight"] = self.target_weight
        if self.target_quantity is not None:
            payload["target_quantity"] = self.target_quantity
        if self.notes:
            payload["notes"] = self.notes
        if self.metadata:
            payload["metadata"] = self.metadata
        return payload


@dataclass(slots=True)
class Targets:
    """Canonical targets document."""

    targets: list[TargetEntry]
    asof: str | None = None
    source: str | None = None
    target_gross_exposure: float = 1.0
    notes: str | None = None
    schema_version: int = SCHEMA_VERSION

    def __post_init__(self) -> None:
        self.targets = list(self.targets or [])
        if not self.targets:
            raise ValueError("targets document must contain at least one target")
        self.target_gross_exposure = float(self.target_gross_exposure or 0.0)
        if self.target_gross_exposure < 0:
            raise ValueError("target_gross_exposure cannot be negative")
        self.notes = self.notes or None
        self.source = self.source or None
        self.asof = self.asof or None

    @property
    def tickers(self) -> list[str]:
        """Compatibility accessor returning base symbols."""

        return [target.symbol for target in self.targets]

    @property
    def weights(self) -> dict[str, float] | None:
        """Compatibility accessor for weight-based targets."""

        weighted = {
            target.key: float(target.target_weight)
            for target in self.targets
            if target.target_weight is not None
        }
        return weighted or None


def _entry_from_obj(
    obj: TargetEntry | dict[str, Any],
    *,
    default_market: str = "US",
) -> TargetEntry:
    if isinstance(obj, TargetEntry):
        return obj
    if not isinstance(obj, dict):
        raise TypeError(f"unsupported target entry type: {type(obj)!r}")
    symbol, market = _split_symbol_market(
        str(obj.get("symbol") or obj.get("ticker") or ""),
        obj.get("market"),
        default_market=default_market,
    )
    return TargetEntry(
        symbol=symbol,
        market=market,
        target_weight=obj.get("target_weight"),
        target_quantity=obj.get("target_quantity"),
        notes=obj.get("notes"),
        metadata=dict(obj.get("metadata") or {}),
    )


def _entries_from_ticker_list(
    tickers: list[str],
    *,
    weights: dict[str, float] | None = None,
    default_market: str = "US",
) -> list[TargetEntry]:
    cleaned: list[tuple[str, str, str]] = []
    for raw in tickers:
        symbol, market = _split_symbol_market(str(raw), default_market=default_market)
        if symbol:
            cleaned.append((str(raw), symbol, market))
    if not cleaned:
        raise ValueError("ticker list contained no valid symbols")

    if weights:
        entries: list[TargetEntry] = []
        for raw, symbol, market in cleaned:
            weight = None
            for key in (raw, symbol, f"{symbol}.{market}"):
                if key in weights:
                    weight = weights[key]
                    break
            if weight is None:
                raise ValueError("weights must define each target explicitly")
            entries.append(
                TargetEntry(
                    symbol=symbol,
                    market=market,
                    target_weight=float(weight),
                )
            )
        return entries

    equal_weight = 1.0 / len(cleaned)
    return [
        TargetEntry(symbol=symbol, market=market, target_weight=equal_weight)
        for _, symbol, market in cleaned
    ]


def write_targets_json(
    out_path: Path,
    tickers: list[str] | None = None,
    *,
    asof: str | None = None,
    source: str | None = "manual",
    weights: dict[str, float] | None = None,
    notes: str | None = None,
    targets: list[TargetEntry | dict[str, Any]] | None = None,
    target_gross_exposure: float = 1.0,
    default_market: str = "US",
) -> Path:
    """Write canonical targets JSON.

    Callers may either provide explicit ``targets`` entries or a ticker list
    plus optional weights. Ticker lists are normalized into the canonical
    ``targets`` array before writing and are not accepted by ``read_targets_json``.
    """

    if targets is not None:
        entries = [_entry_from_obj(target, default_market=default_market) for target in targets]
    else:
        entries = _entries_from_ticker_list(
            list(tickers or []),
            weights=weights,
            default_market=default_market,
        )

    payload: dict[str, Any] = {
        "asof": asof,
        "source": source,
        "target_gross_exposure": float(target_gross_exposure or 0.0),
        "targets": [entry.to_payload() for entry in entries],
    }
    if notes:
        payload["notes"] = notes

    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8")
    return out_path


def read_targets_json(
    path: Path,
    *,
    require_canonical: bool = False,
    default_market: str = "US",
) -> Targets:
    """Read canonical targets JSON and return structured data.

    The ``require_canonical`` argument is retained for compatibility with
    existing call sites. All reads now require a top-level ``targets`` array.
    """

    if not path.exists():
        raise FileNotFoundError(f"文件不存在: {path}")

    raw = json.loads(path.read_text(encoding="utf-8"))
    try:
        schema_version = int(raw.get("schema_version") or SCHEMA_VERSION)
    except (TypeError, ValueError):
        schema_version = SCHEMA_VERSION
    asof = raw.get("asof") or None
    source = raw.get("source") or None
    notes = raw.get("notes") or None
    target_gross_exposure = float(raw.get("target_gross_exposure", 1.0))

    if isinstance(raw.get("targets"), list):
        entries = [
            _entry_from_obj(item, default_market=default_market)
            for item in (raw.get("targets") or [])
        ]
        return Targets(
            targets=entries,
            asof=asof,
            source=source,
            target_gross_exposure=target_gross_exposure,
            notes=notes,
            schema_version=schema_version,
        )

    raise ValueError(
        "ticker-list targets are not canonical rebalance inputs; "
        "provide a targets JSON with a 'targets' array"
    )
