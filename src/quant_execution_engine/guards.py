"""Execution safety guards shared by CLI and tooling."""

from __future__ import annotations

import os
import re
from pathlib import Path

from .paths import PROJECT_ROOT

LIVE_ENABLE_ENV_VAR = "QEXEC_ENABLE_LIVE"
LIVE_SECRET_ENV_NAMES = frozenset(
    {
        "LONGPORT_APP_KEY",
        "LONGPORT_APP_SECRET",
        "LONGPORT_ACCESS_TOKEN",
        "LONGPORT_ACCESS_TOKEN_REAL",
        "LONGBRIDGE_APP_KEY",
        "LONGBRIDGE_APP_SECRET",
        "LONGBRIDGE_ACCESS_TOKEN",
        "LONGBRIDGE_ACCESS_TOKEN_REAL",
    }
)
ENV_ASSIGNMENT_RE = re.compile(
    r"^\s*(?:export\s+)?(?P<name>[A-Za-z_][A-Za-z0-9_]*)\s*=\s*(?P<value>.+?)\s*$"
)


def is_truthy(value: str | None) -> bool:
    return str(value or "").strip().lower() in {"1", "true", "yes", "y", "on"}


def _normalize_env_assignment_value(raw: str) -> str:
    value = raw.strip()
    if not value:
        return ""
    if value[0] in {"'", '"'}:
        quote = value[0]
        end = value.find(quote, 1)
        if end != -1:
            return value[1:end].strip()
        return value[1:].strip()
    return value.split("#", 1)[0].strip().strip("'").strip('"').strip()


def _looks_like_placeholder_secret(value: str) -> bool:
    normalized = value.strip()
    lowered = normalized.lower()
    if not lowered:
        return True
    if normalized.startswith(("$", "${", "$(", "`")):
        return True
    if lowered.startswith("your_") and lowered.endswith("_here"):
        return True
    return lowered in {
        "changeme",
        "example",
        "placeholder",
        "replace_me",
        "replace-this",
        "replace_this",
    }


def iter_repo_local_env_files(project_root: Path) -> list[Path]:
    candidates: set[Path] = set()
    for pattern in (".env", ".env.*", ".envrc", ".envrc.*"):
        candidates.update(project_root.glob(pattern))

    files: list[Path] = []
    for path in sorted(candidates):
        if not path.is_file():
            continue
        if path.name.endswith((".example", ".sample", ".template")):
            continue
        files.append(path)
    return files


def find_repo_local_live_secret_sources(
    project_root: Path | None = None,
) -> list[tuple[Path, str]]:
    root = project_root or PROJECT_ROOT
    findings: list[tuple[Path, str]] = []
    for path in iter_repo_local_env_files(root):
        try:
            text = path.read_text(encoding="utf-8")
        except OSError:
            continue
        for raw_line in text.splitlines():
            line = raw_line.strip()
            if not line or line.startswith("#"):
                continue
            match = ENV_ASSIGNMENT_RE.match(raw_line)
            if match is None:
                continue
            name = match.group("name")
            if name not in LIVE_SECRET_ENV_NAMES:
                continue
            value = _normalize_env_assignment_value(match.group("value"))
            if _looks_like_placeholder_secret(value):
                continue
            findings.append((path, name))
    return findings


def format_live_secret_findings(
    findings: list[tuple[Path, str]],
    project_root: Path | None = None,
) -> str:
    root = project_root or PROJECT_ROOT
    grouped: dict[Path, set[str]] = {}
    for path, env_name in findings:
        grouped.setdefault(path, set()).add(env_name)
    parts = []
    for path in sorted(grouped):
        label = str(path.relative_to(root))
        names = ", ".join(sorted(grouped[path]))
        parts.append(f"{label} ({names})")
    return ", ".join(parts)


def validate_live_execution_guard(
    *,
    env_name: str,
    dry_run: bool,
    project_root: Path | None = None,
) -> str | None:
    if dry_run or env_name == "paper":
        return None
    if not is_truthy(os.getenv(LIVE_ENABLE_ENV_VAR)):
        return (
            f"real broker live execution requires {LIVE_ENABLE_ENV_VAR}=1. "
            "Paper execution paths are unaffected."
        )

    root = project_root or PROJECT_ROOT
    findings = find_repo_local_live_secret_sources(root)
    if not findings:
        return None
    locations = format_live_secret_findings(findings, root)
    return (
        "refusing live execution because repo-local env files contain LongPort live "
        f"credentials: {locations}. Move live secrets to system environment variables "
        "or an external secret manager, then retry."
    )
