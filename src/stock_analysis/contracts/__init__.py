"""Canonical contracts used by the execution engine."""

from .targets import (
    SCHEMA_VERSION,
    KNOWN_MARKETS,
    TargetEntry,
    Targets,
    read_targets_json,
    write_targets_json,
)

__all__ = [
    "KNOWN_MARKETS",
    "SCHEMA_VERSION",
    "TargetEntry",
    "Targets",
    "read_targets_json",
    "write_targets_json",
]
