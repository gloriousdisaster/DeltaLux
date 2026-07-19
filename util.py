"""Pure helpers for DeltaLux (no Home Assistant imports, unit-testable)."""

from __future__ import annotations

from typing import Any

from .const import (
    CONF_MAX_BRIGHTNESS,
    CONF_MIN_BRIGHTNESS,
    CONF_OFFSET,
    DEFAULT_MAX_BRIGHTNESS,
    DEFAULT_MIN_BRIGHTNESS,
    DEFAULT_OFFSET,
    OFFSET_TYPE_RELATIVE,
)


def calculate_light_brightness(
    config: dict[str, Any], offset_type: str, master_brightness: int
) -> int:
    """Calculate a member light's brightness (0-255) from the master.

    Absolute mode: offset is percentage points added to the master level.
    Relative mode: offset shifts a multiplier, e.g. -25 -> 75% of master.
    The result is clamped to the light's min/max percent bounds.
    """
    offset = float(config.get(CONF_OFFSET, DEFAULT_OFFSET))
    min_pct = float(config.get(CONF_MIN_BRIGHTNESS, DEFAULT_MIN_BRIGHTNESS))
    max_pct = float(config.get(CONF_MAX_BRIGHTNESS, DEFAULT_MAX_BRIGHTNESS))

    if offset_type == OFFSET_TYPE_RELATIVE:
        target = round(master_brightness * (100 + offset) / 100)
    else:
        target = round(master_brightness + offset * 255 / 100)

    min_brightness = round(min_pct * 255 / 100)
    max_brightness = round(max_pct * 255 / 100)
    if min_brightness > max_brightness:
        min_brightness, max_brightness = max_brightness, min_brightness

    return max(min_brightness, min(max_brightness, target))
