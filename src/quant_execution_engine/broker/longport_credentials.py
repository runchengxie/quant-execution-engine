"""Credential resolution helpers for LongPort backends."""

from __future__ import annotations

import os
import re
from dataclasses import dataclass
from pathlib import Path

from ..paths import PROJECT_ROOT


ENV_ASSIGNMENT_RE = re.compile(
    r"^\s*(?:export\s+)?(?P<name>[A-Za-z_][A-Za-z0-9_]*)\s*=\s*(?P<value>.+?)\s*$"
)


@dataclass(slots=True)
class LongPortCredentialBundle:
    """Resolved LongPort credentials for a concrete backend mode."""

    env_name: str
    app_key: str
    app_secret: str
    access_token: str
    token_var_name: str


@dataclass(slots=True)
class LongPortCredentialProbe:
    """Best-effort LongPort credential probe without raising on missing fields."""

    env_name: str
    app_key: str | None
    app_secret: str | None
    access_token: str | None
    token_var_name: str


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


def _looks_like_placeholder_secret(value: str | None) -> bool:
    normalized = str(value or "").strip()
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


def _iter_repo_local_env_files(project_root: Path) -> list[Path]:
    candidates: list[Path] = []
    for name in (".env", ".env.local"):
        path = project_root / name
        if path.is_file():
            candidates.append(path)
    return candidates


def _find_repo_local_env_value(
    names: tuple[str, ...],
    *,
    project_root: Path,
) -> str | None:
    for path in _iter_repo_local_env_files(project_root):
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
            if name not in names:
                continue
            value = _normalize_env_assignment_value(match.group("value"))
            if _looks_like_placeholder_secret(value):
                continue
            return value
    return None


def _resolve_secret(
    names: tuple[str, ...],
    *,
    project_root: Path,
) -> str | None:
    for name in names:
        value = os.getenv(name)
        if value and not _looks_like_placeholder_secret(value):
            return value
    return _find_repo_local_env_value(names, project_root=project_root)


def resolve_longport_credentials(
    env_name: str,
    *,
    project_root: Path | None = None,
) -> LongPortCredentialBundle:
    """Resolve LongPort credentials for real or paper mode.

    Environment variables take precedence unless they still contain obvious placeholder values.
    When placeholders are present, local `.env` / `.env.local` values are used as a fallback.
    """

    root = project_root or PROJECT_ROOT
    normalized_env = str(env_name or "real").strip().lower()
    if normalized_env not in {"real", "paper"}:
        raise ValueError(f"unsupported longport environment: {env_name}")

    probe = probe_longport_credentials(env_name, project_root=project_root)
    if not probe.app_key or not probe.app_secret:
        raise RuntimeError("缺少 LONGPORT_APP_KEY/SECRET。请通过系统环境变量或本地 .env 注入。")
    if not probe.access_token:
        raise RuntimeError(
            "缺少 "
            + probe.token_var_name
            + (
                "（或兼容 LONGBRIDGE_ACCESS_TOKEN_TEST）。"
                if probe.env_name == "paper"
                else "（或兼容 LONGPORT_ACCESS_TOKEN_REAL）。"
            )
        )

    return LongPortCredentialBundle(
        env_name=probe.env_name,
        app_key=probe.app_key,
        app_secret=probe.app_secret,
        access_token=probe.access_token,
        token_var_name=probe.token_var_name,
    )


def probe_longport_credentials(
    env_name: str,
    *,
    project_root: Path | None = None,
) -> LongPortCredentialProbe:
    """Best-effort probe for LongPort credentials."""

    root = project_root or PROJECT_ROOT
    normalized_env = str(env_name or "real").strip().lower()
    if normalized_env not in {"real", "paper"}:
        raise ValueError(f"unsupported longport environment: {env_name}")

    app_key = _resolve_secret(
        ("LONGPORT_APP_KEY", "LONGBRIDGE_APP_KEY"),
        project_root=root,
    )
    app_secret = _resolve_secret(
        ("LONGPORT_APP_SECRET", "LONGBRIDGE_APP_SECRET"),
        project_root=root,
    )

    if normalized_env == "paper":
        token_names = ("LONGPORT_ACCESS_TOKEN_TEST", "LONGBRIDGE_ACCESS_TOKEN_TEST")
        access_token = _resolve_secret(token_names, project_root=root)
        token_var_name = "LONGPORT_ACCESS_TOKEN_TEST"
    else:
        token_names = (
            "LONGPORT_ACCESS_TOKEN",
            "LONGPORT_ACCESS_TOKEN_REAL",
            "LONGBRIDGE_ACCESS_TOKEN",
            "LONGBRIDGE_ACCESS_TOKEN_REAL",
        )
        access_token = _resolve_secret(token_names, project_root=root)
        token_var_name = "LONGPORT_ACCESS_TOKEN"

    return LongPortCredentialProbe(
        env_name=normalized_env,
        app_key=app_key,
        app_secret=app_secret,
        access_token=access_token,
        token_var_name=token_var_name,
    )


__all__ = [
    "LongPortCredentialBundle",
    "LongPortCredentialProbe",
    "probe_longport_credentials",
    "resolve_longport_credentials",
]
