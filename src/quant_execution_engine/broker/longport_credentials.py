"""Credential resolution helpers for LongPort backends."""

from __future__ import annotations

import os
import re
from dataclasses import dataclass
from pathlib import Path

from ..paths import PROJECT_ROOT

DEFAULT_LONGPORT_USER_ENV_PATH = Path.home() / ".config" / "qexec" / "longport-live.env"

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
    app_key_source: str | None = None
    app_secret_source: str | None = None
    access_token_source: str | None = None


@dataclass(slots=True)
class LongPortCredentialProbe:
    """Best-effort LongPort credential probe without raising on missing fields."""

    env_name: str
    app_key: str | None
    app_secret: str | None
    access_token: str | None
    token_var_name: str
    app_key_source: str | None = None
    app_secret_source: str | None = None
    access_token_source: str | None = None


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


def _iter_user_env_files(user_env_path: Path | None) -> list[Path]:
    path = user_env_path or DEFAULT_LONGPORT_USER_ENV_PATH
    if path.is_file():
        return [path]
    return []


def _read_value_from_files(
    names: tuple[str, ...],
    *,
    paths: list[Path],
    source_kind: str,
    project_root: Path,
) -> tuple[str | None, str | None]:
    for path in paths:
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
            return value, _format_source_label(
                source_kind=source_kind,
                path=path,
                env_name=name,
                project_root=project_root,
            )
    return None, None


def _format_source_label(
    *,
    source_kind: str,
    path: Path,
    env_name: str,
    project_root: Path,
) -> str:
    if source_kind == "repo":
        try:
            path_label = str(path.relative_to(project_root))
        except ValueError:
            path_label = str(path)
        return f"repo-local {path_label} ({env_name})"
    home = Path.home()
    try:
        path_label = "~/" + str(path.relative_to(home))
    except ValueError:
        path_label = str(path)
    return f"user-private {path_label} ({env_name})"


def _resolve_secret(
    names: tuple[str, ...],
    *,
    project_root: Path,
    user_env_path: Path | None,
    search_order: tuple[str, ...],
) -> tuple[str | None, str | None]:
    for source_kind in search_order:
        if source_kind == "env":
            for name in names:
                value = os.getenv(name)
                if value and not _looks_like_placeholder_secret(value):
                    return value, f"process env ({name})"
            continue
        if source_kind == "repo":
            resolved, source = _read_value_from_files(
                names,
                paths=_iter_repo_local_env_files(project_root),
                source_kind="repo",
                project_root=project_root,
            )
        elif source_kind == "user":
            resolved, source = _read_value_from_files(
                names,
                paths=_iter_user_env_files(user_env_path),
                source_kind="user",
                project_root=project_root,
            )
        else:
            raise ValueError(f"unsupported secret fallback source: {source_kind}")
        if resolved:
            return resolved, source
    return None, None


def resolve_longport_credentials(
    env_name: str,
    *,
    project_root: Path | None = None,
    user_env_path: Path | None = None,
) -> LongPortCredentialBundle:
    """Resolve LongPort credentials for real or paper mode.

    Environment variables take precedence unless they still contain obvious placeholder values.
    When placeholders are present, local `.env` / `.env.local` values are used as a fallback.
    """

    root = project_root or PROJECT_ROOT
    normalized_env = str(env_name or "real").strip().lower()
    if normalized_env not in {"real", "paper"}:
        raise ValueError(f"unsupported longport environment: {env_name}")

    probe = probe_longport_credentials(
        env_name,
        project_root=project_root,
        user_env_path=user_env_path,
    )
    if not probe.app_key or not probe.app_secret:
        if probe.env_name == "paper":
            raise RuntimeError(
                "缺少 LONGPORT_APP_KEY/SECRET。请通过系统环境变量、本地 .env 或用户级私有 env 注入。"
            )
        raise RuntimeError(
            "缺少 LONGPORT_APP_KEY/SECRET。请通过系统环境变量或用户级私有 env 注入。"
        )
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
        app_key_source=probe.app_key_source,
        app_secret_source=probe.app_secret_source,
        access_token_source=probe.access_token_source,
    )


def probe_longport_credentials(
    env_name: str,
    *,
    project_root: Path | None = None,
    user_env_path: Path | None = None,
) -> LongPortCredentialProbe:
    """Best-effort probe for LongPort credentials."""

    root = project_root or PROJECT_ROOT
    normalized_env = str(env_name or "real").strip().lower()
    if normalized_env not in {"real", "paper"}:
        raise ValueError(f"unsupported longport environment: {env_name}")

    app_search_order = ("env", "repo", "user") if normalized_env == "paper" else (
        "user",
        "env",
    )
    token_search_order = ("env", "repo", "user") if normalized_env == "paper" else (
        "user",
        "env",
    )

    app_key, app_key_source = _resolve_secret(
        ("LONGPORT_APP_KEY", "LONGBRIDGE_APP_KEY"),
        project_root=root,
        user_env_path=user_env_path,
        search_order=app_search_order,
    )
    app_secret, app_secret_source = _resolve_secret(
        ("LONGPORT_APP_SECRET", "LONGBRIDGE_APP_SECRET"),
        project_root=root,
        user_env_path=user_env_path,
        search_order=app_search_order,
    )

    if normalized_env == "paper":
        token_names = ("LONGPORT_ACCESS_TOKEN_TEST", "LONGBRIDGE_ACCESS_TOKEN_TEST")
        access_token, access_token_source = _resolve_secret(
            token_names,
            project_root=root,
            user_env_path=user_env_path,
            search_order=token_search_order,
        )
        token_var_name = "LONGPORT_ACCESS_TOKEN_TEST"
    else:
        token_names = (
            "LONGPORT_ACCESS_TOKEN",
            "LONGPORT_ACCESS_TOKEN_REAL",
            "LONGBRIDGE_ACCESS_TOKEN",
            "LONGBRIDGE_ACCESS_TOKEN_REAL",
        )
        access_token, access_token_source = _resolve_secret(
            token_names,
            project_root=root,
            user_env_path=user_env_path,
            search_order=token_search_order,
        )
        token_var_name = "LONGPORT_ACCESS_TOKEN"

    return LongPortCredentialProbe(
        env_name=normalized_env,
        app_key=app_key,
        app_secret=app_secret,
        access_token=access_token,
        token_var_name=token_var_name,
        app_key_source=app_key_source,
        app_secret_source=app_secret_source,
        access_token_source=access_token_source,
    )


def resolve_longport_runtime_value(
    names: tuple[str, ...],
    *,
    env_name: str,
    default: str = "",
    project_root: Path | None = None,
    user_env_path: Path | None = None,
) -> tuple[str, str | None]:
    root = project_root or PROJECT_ROOT
    normalized_env = str(env_name or "real").strip().lower()
    if normalized_env not in {"real", "paper"}:
        raise ValueError(f"unsupported longport environment: {env_name}")

    search_order = ("env", "repo", "user") if normalized_env == "paper" else (
        "user",
        "env",
    )
    value, source = _resolve_secret(
        names,
        project_root=root,
        user_env_path=user_env_path,
        search_order=search_order,
    )
    return str(value or default), source


__all__ = [
    "DEFAULT_LONGPORT_USER_ENV_PATH",
    "LongPortCredentialBundle",
    "LongPortCredentialProbe",
    "probe_longport_credentials",
    "resolve_longport_credentials",
    "resolve_longport_runtime_value",
]
