#!/usr/bin/env python3
"""Collect lightweight maintainability metrics for the repository.

This script is now a thin wrapper around ``research-code-quality``. The
cross-repo-identical scan algorithm (file discovery, ast function-length
counting, C901 per-file-ignore counting) lives in that shared package; this
file keeps only quant-execution-engine's local concerns:

- ``DEFAULT_RATCHET_BUDGETS`` (frozen governance value, includes 2 C901 ignores)
- ``DEFAULT_ROOTS`` (adds ``project_tools``)
- the ``Metrics`` dataclass and CLI formatting (no ``command_run_functions_over_150``)

The scan uses plain ``rglob`` (``use_git=False``) to match the repo's prior
working-tree discovery, and includes the ``project_tools`` root.

Usage:
  python scripts/dev/maintainability_metrics.py           # human-readable text
  python scripts/dev/maintainability_metrics.py --json    # machine-readable JSON
  python scripts/dev/maintainability_metrics.py --ratchet # fail if budgets exceeded
"""

from __future__ import annotations

import argparse
import json
import sys
from collections.abc import Sequence
from dataclasses import asdict, dataclass
from pathlib import Path

from research_code_quality.scanner import (
    FileMetric,
    FunctionMetric,
    ScanResult,
    scan_repository,
)

REPO_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_ROOTS: tuple[str, ...] = ("src", "scripts", "tests", "project_tools")
DEFAULT_LIMIT = 10
PYPROJECT_PATH = Path("pyproject.toml")
DEFAULT_RATCHET_BUDGETS: dict[str, int] = {
    "long_lines_over_100": 0,
    "functions_over_100": 18,
    "functions_over_250": 2,
    "functions_over_500": 0,
    "c901_file_ignores": 2,
    "files_over_800": 3,
    "files_over_1200": 2,
    "tests_over_1000": 3,
}


@dataclass(frozen=True)
class Metrics:
    roots: list[str]
    python_files: int
    python_lines: int
    long_lines_over_100: int
    functions_over_100: int
    functions_over_250: int
    functions_over_500: int
    c901_file_ignores: int
    files_over_800: int
    files_over_1200: int
    tests_over_1000: int
    largest_files: list[FileMetric]
    largest_functions: list[FunctionMetric]

    def to_payload(self) -> dict[str, object]:
        payload = asdict(self)
        payload["thresholds"] = {
            "long_line_columns": 100,
            "large_function_lines": 100,
            "very_large_function_lines": 250,
            "huge_function_lines": 500,
            "large_file_lines": 800,
            "very_large_file_lines": 1200,
            "large_test_file_lines": 1000,
        }
        return payload


def check_ratchet_budgets(
    metrics: Metrics,
    budgets: dict[str, int] | None = None,
) -> dict[str, dict[str, int]]:
    if budgets is None:
        budgets = DEFAULT_RATCHET_BUDGETS
    failures: dict[str, dict[str, int]] = {}
    for name, budget in budgets.items():
        value = getattr(metrics, name)
        if value > budget:
            failures[name] = {"actual": value, "budget": budget}
    return failures


def collect_metrics(
    repo_root: Path = REPO_ROOT,
    roots: Sequence[str] = DEFAULT_ROOTS,
    limit: int = DEFAULT_LIMIT,
) -> Metrics:
    result: ScanResult = scan_repository(repo_root, roots, limit, use_git=False)
    return Metrics(
        roots=result.roots,
        python_files=result.python_files,
        python_lines=result.python_lines,
        long_lines_over_100=result.long_lines_over_100,
        functions_over_100=result.functions_over_100,
        functions_over_250=result.functions_over_250,
        functions_over_500=result.functions_over_500,
        c901_file_ignores=result.c901_file_ignores,
        files_over_800=result.files_over_800,
        files_over_1200=result.files_over_1200,
        tests_over_1000=result.tests_over_1000,
        largest_files=result.largest_files,
        largest_functions=result.largest_functions,
    )


def format_markdown(metrics: Metrics) -> str:
    lines = [
        "| Metric | Value |",
        "| --- | ---: |",
        f"| Python files | {metrics.python_files} |",
        f"| Python lines | {metrics.python_lines} |",
        f"| Lines over 100 chars | {metrics.long_lines_over_100} |",
        f"| Functions over 100 lines | {metrics.functions_over_100} |",
        f"| Functions over 250 lines | {metrics.functions_over_250} |",
        f"| Functions over 500 lines | {metrics.functions_over_500} |",
        f"| C901 file ignores | {metrics.c901_file_ignores} |",
        f"| Files over 800 lines | {metrics.files_over_800} |",
        f"| Files over 1200 lines | {metrics.files_over_1200} |",
        f"| Test files over 1000 lines | {metrics.tests_over_1000} |",
        "",
        "Largest functions:",
        "",
        "| Lines | Function | Path |",
        "| ---: | --- | --- |",
    ]
    for item in metrics.largest_functions:
        lines.append(f"| {item.lines} | `{item.name}` | `{item.path}:{item.start_line}` |")
    return "\n".join(lines)


def format_text(metrics: Metrics) -> str:
    rows = [
        ("python_files", metrics.python_files),
        ("python_lines", metrics.python_lines),
        ("long_lines_over_100", metrics.long_lines_over_100),
        ("functions_over_100", metrics.functions_over_100),
        ("functions_over_250", metrics.functions_over_250),
        ("functions_over_500", metrics.functions_over_500),
        ("c901_file_ignores", metrics.c901_file_ignores),
        ("files_over_800", metrics.files_over_800),
        ("files_over_1200", metrics.files_over_1200),
        ("tests_over_1000", metrics.tests_over_1000),
    ]
    lines = ["Maintainability metrics:"]
    lines.extend(f"- {name}: {value}" for name, value in rows)
    lines.append("")
    lines.append("Largest functions:")
    lines.extend(
        f"- {item.lines} lines {item.path}:{item.start_line} {item.name}"
        for item in metrics.largest_functions
    )
    return "\n".join(lines)


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Collect static maintainability metrics.",
    )
    parser.add_argument("--json", action="store_true", help="Machine-readable JSON output.")
    parser.add_argument("--markdown", action="store_true", help="Markdown table output.")
    parser.add_argument(
        "--limit",
        type=int,
        default=DEFAULT_LIMIT,
        help=f"Largest N files/functions (default: {DEFAULT_LIMIT}).",
    )
    parser.add_argument(
        "--root",
        type=Path,
        default=REPO_ROOT,
        help="Repository root. Defaults to the current checkout.",
    )
    parser.add_argument(
        "--scope",
        action="append",
        choices=DEFAULT_ROOTS,
        help="Root to include. May be repeated. Defaults to src, scripts, tests, project_tools.",
    )
    parser.add_argument(
        "--ratchet",
        action="store_true",
        help="Fail if metrics exceed ratchet budgets.",
    )
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    roots = tuple(args.scope or DEFAULT_ROOTS)
    metrics = collect_metrics(args.root.resolve(), roots, max(args.limit, 0))

    if args.json:
        json.dump(metrics.to_payload(), sys.stdout, indent=2, ensure_ascii=False)
        print()
    elif args.markdown:
        print(format_markdown(metrics))
    else:
        print(format_text(metrics))

    if args.ratchet:
        failures = check_ratchet_budgets(metrics)
        if failures:
            print("\nMaintainability ratchet exceeded:", file=sys.stderr)
            for name, values in sorted(failures.items()):
                print(
                    f"- {name}: {values['actual']} > {values['budget']}",
                    file=sys.stderr,
                )
            return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
