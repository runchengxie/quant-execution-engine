#!/usr/bin/env python3
from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parent.parent
AI_DIR = ROOT / "outputs" / "ai_pick"
PRELIM_DIR = ROOT / "outputs" / "preliminary"


def load_json(path: Path) -> Any:
    with path.open("r", encoding="utf-8") as f:
        return json.load(f)


def prelim_candidates_for(trade_date: str) -> set[str]:
    year = trade_date[:4]
    p = PRELIM_DIR / year / f"{trade_date}.json"
    if not p.exists():
        return set()
    data = load_json(p)
    rows = data.get("rows", [])
    return {
        str(r.get("ticker", "")).upper().strip()
        for r in rows
        if isinstance(r, dict) and r.get("ticker")
    }


def validate_ai_file(path: Path) -> list[str]:
    issues: list[str] = []
    try:
        data = load_json(path)
    except Exception as e:
        return [f"{path}: JSON parse error: {e}"]

    must = [
        "schema_version",
        "source",
        "trade_date",
        "data_cutoff_date",
        "universe",
        "model",
        "prompt_version",
        "params",
        "picks",
    ]
    for k in must:
        if k not in data:
            issues.append(f"{path}: missing key '{k}'")

    if data.get("source") != "ai_pick":
        issues.append(f"{path}: source should be 'ai_pick'")

    # file name consistency
    trade_date: str = str(data.get("trade_date", ""))
    if path.stem != trade_date:
        issues.append(
            f"{path}: file name/date mismatch (stem={path.stem} trade_date={trade_date})"
        )

    params: dict[str, Any] = (
        data.get("params", {}) if isinstance(data.get("params"), dict) else {}
    )
    top_n = params.get("top_n")
    raw_picks = data.get("picks", [])
    picks: list[dict[str, Any]] = raw_picks if isinstance(raw_picks, list) else []

    if not isinstance(top_n, int):
        issues.append(f"{path}: params.top_n must be int")

    if not isinstance(raw_picks, list) or len(picks) == 0:
        issues.append(f"{path}: picks must be non-empty list")
        return issues

    # Count
    if isinstance(top_n, int) and len(picks) != top_n:
        issues.append(f"{path}: picks length {len(picks)} != top_n {top_n}")

    # Ranks 1..N unique
    ranks_raw = [p.get("rank") for p in picks]
    if any(not isinstance(r, int) for r in ranks_raw):
        issues.append(f"{path}: invalid ranks (non-integer present)")
    else:
        ranks: list[int] = [int(r) for r in ranks_raw]  # type: ignore[arg-type]
        if sorted(ranks) != list(range(1, len(picks) + 1)):
            issues.append(f"{path}: ranks must be consecutive 1..N")

    # Tickers unique (normalized)
    tickers = [str(p.get("ticker", "")).upper().strip() for p in picks]
    if len(tickers) != len(set(tickers)):
        issues.append(f"{path}: duplicate tickers detected in picks")

    # Confidence: number within [0,1] (accept int 1..10 and normalize)
    for i, p in enumerate(picks, 1):
        conf = p.get("confidence")
        ok = False
        if isinstance(conf, (int, float)):
            # if given as 1..10, normalize and accept
            val = float(conf)
            if 1.0 <= val <= 10.0:
                ok = True
            elif 0.0 <= val <= 1.0:
                ok = True
        if not ok:
            issues.append(
                f"{path}: pick#{i} confidence should be float in [0,1] or int in [1,10], got {conf!r}"
            )

    # Mapping to preliminary candidates (if available)
    if trade_date:
        cands = prelim_candidates_for(trade_date)
        if not cands:
            issues.append(
                f"{path}: preliminary candidates not found for {trade_date} (skip mapping check)"
            )
        else:
            extra = sorted(set(tickers) - cands)
            if extra:
                issues.append(
                    f"{path}: {trade_date} picks not in preliminary candidates: {', '.join(extra)}"
                )

    return issues


def main() -> int:
    rc = 0
    ai_files = sorted(AI_DIR.glob("*/*.json"))
    prelim_files = sorted(PRELIM_DIR.glob("*/*.json"))

    ai_dates = {p.stem for p in ai_files}
    prelim_dates = {p.stem for p in prelim_files}

    # Completeness: for each prelim date, ai should exist
    missing = sorted(prelim_dates - ai_dates)
    if missing:
        print("[MISSING] ai_pick missing for dates:", ", ".join(missing))
        rc = 1

    # Validate each ai file
    for p in ai_files:
        issues = validate_ai_file(p)
        if issues:
            rc = 1
            for msg in issues:
                print("[ERROR]", msg)

    if rc == 0:
        print("All ai_pick JSONs look good.✅")
    return rc


if __name__ == "__main__":
    sys.exit(main())
