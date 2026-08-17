"""Project path helpers."""

from __future__ import annotations

import os
from pathlib import Path


def get_project_root() -> Path:
    """Return repository root."""

    try:
        return Path(__file__).resolve().parents[2]
    except NameError:
        return Path.cwd()


def outputs_dir() -> Path:
    """Return the active outputs directory.

    ``QEXEC_OUTPUTS_DIR`` redirects audit logs, execution state, and evidence
    artifacts into an isolated run directory. Offline evidence harnesses use it
    to keep reproducible runs self-contained and restartable from that directory.
    """

    override = os.getenv("QEXEC_OUTPUTS_DIR")
    if override:
        return Path(override).expanduser().resolve()
    return PROJECT_ROOT / "outputs"


PROJECT_ROOT = get_project_root()
OUTPUTS_DIR = outputs_dir()
OUTPUTS_DIR.mkdir(parents=True, exist_ok=True)

__all__ = ["OUTPUTS_DIR", "PROJECT_ROOT", "get_project_root", "outputs_dir"]
