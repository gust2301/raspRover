"""Validation and normalization helpers for persistent SLAM map names."""

from __future__ import annotations

import pathlib
import re
import unicodedata

_SAFE_MAP_NAME = re.compile(r"[A-Za-z0-9][A-Za-z0-9_.-]{0,63}")


def validate_map_name(requested_name: object) -> str | None:
    """Return an existing storage identifier only when it is already safe."""
    requested = str(requested_name).strip()
    name = pathlib.Path(requested).name
    if name != requested:
        return None
    lowered = name.lower()
    if lowered.endswith(".yaml") or lowered.endswith(".pgm"):
        name = name.rsplit(".", 1)[0]
    return name if _SAFE_MAP_NAME.fullmatch(name) else None


def normalize_map_name(requested_name: object) -> str | None:
    """Turn a human label into a safe, stable map storage identifier."""
    label = str(requested_name).strip()
    lowered = label.lower()
    if lowered.endswith(".yaml") or lowered.endswith(".pgm"):
        label = label.rsplit(".", 1)[0]
    ascii_label = unicodedata.normalize("NFKD", label).encode("ascii", "ignore").decode()
    normalized = re.sub(r"[^A-Za-z0-9]+", "-", ascii_label).strip("-").lower()[:64]
    return normalized if _SAFE_MAP_NAME.fullmatch(normalized) else None
