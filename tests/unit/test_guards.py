from pathlib import Path

import pytest

import quant_execution_engine.guards as guards


from quant_execution_engine.guards import validate_live_execution_guard


pytestmark = pytest.mark.unit


def test_live_execution_guard_allows_repo_local_shared_key_and_secret(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    (tmp_path / ".env").write_text(
        "\n".join(
            [
                'LONGPORT_APP_KEY="repo_app_key"',
                'LONGPORT_APP_SECRET="repo_app_secret"',
            ]
        ),
        encoding="utf-8",
    )
    monkeypatch.setenv("QEXEC_ENABLE_LIVE", "1")

    message = validate_live_execution_guard(
        env_name="real",
        dry_run=False,
        project_root=tmp_path,
    )

    assert message is None


def test_live_execution_guard_rejects_repo_local_real_access_token(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    (tmp_path / ".env").write_text(
        'LONGPORT_ACCESS_TOKEN="repo_real_token"',
        encoding="utf-8",
    )
    monkeypatch.setenv("QEXEC_ENABLE_LIVE", "1")

    message = validate_live_execution_guard(
        env_name="real",
        dry_run=False,
        project_root=tmp_path,
    )

    assert message is not None
    assert "live access tokens" in message
    assert ".env (LONGPORT_ACCESS_TOKEN)" in message


def test_live_execution_guard_accepts_enable_flag_from_user_private_env(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    user_env = tmp_path / "longport-live.env"
    user_env.write_text('export QEXEC_ENABLE_LIVE="1"\n', encoding="utf-8")
    monkeypatch.delenv("QEXEC_ENABLE_LIVE", raising=False)
    monkeypatch.setattr(guards, "DEFAULT_USER_LIVE_ENV_PATH", user_env)

    message = validate_live_execution_guard(
        env_name="real",
        dry_run=False,
        project_root=tmp_path,
    )

    assert message is None
