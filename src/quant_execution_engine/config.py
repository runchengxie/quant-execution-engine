"""Minimal execution-engine configuration loader."""

from __future__ import annotations

from typing import Any

from .logging import get_logger
from .paths import PROJECT_ROOT

logger = get_logger(__name__)

try:
    import yaml
except ImportError:
    yaml = None


def load_cfg() -> dict[str, Any]:
    """Load config/config.yaml when present."""

    candidates = [
        PROJECT_ROOT / "config" / "config.yaml",
        PROJECT_ROOT / "config.yaml",
    ]
    config_path = next((path for path in candidates if path.exists()), None)
    if config_path is None:
        return {}

    if yaml is None:
        raise ImportError(
            "PyYAML is required to read config.yaml. Install it with: pip install PyYAML"
        )

    try:
        with open(config_path, encoding="utf-8") as fh:
            data = yaml.safe_load(fh) or {}
        return data if isinstance(data, dict) else {}
    except Exception as exc:
        logger.warning("Failed to load config.yaml: %s. Using empty configuration.", exc)
        return {}
