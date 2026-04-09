"""Project path helpers."""

from __future__ import annotations

from pathlib import Path


def get_project_root() -> Path:
    """Return repository root."""

    try:
        return Path(__file__).resolve().parents[2]
    except NameError:
        return Path.cwd()


PROJECT_ROOT = get_project_root()
OUTPUTS_DIR = PROJECT_ROOT / "outputs"
OUTPUTS_DIR.mkdir(parents=True, exist_ok=True)

__all__ = ["OUTPUTS_DIR", "PROJECT_ROOT", "get_project_root"]
