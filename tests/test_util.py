"""Tests for the pure brightness math."""

import pytest

from deltalux.const import (
    CONF_MAX_BRIGHTNESS,
    CONF_MIN_BRIGHTNESS,
    CONF_OFFSET,
    OFFSET_TYPE_ABSOLUTE,
    OFFSET_TYPE_RELATIVE,
)
from deltalux.util import calculate_light_brightness


@pytest.mark.parametrize(
    ("config", "offset_type", "master", "expected"),
    [
        # Passthrough with no offset
        ({CONF_OFFSET: 0}, OFFSET_TYPE_ABSOLUTE, 128, 128),
        # Absolute: 100% master, -25 points -> 75% -> 191
        ({CONF_OFFSET: -25}, OFFSET_TYPE_ABSOLUTE, 255, 191),
        # Absolute with per-light max cap (25% -> 64)
        (
            {CONF_OFFSET: -25.0, CONF_MAX_BRIGHTNESS: 25.0},
            OFFSET_TYPE_ABSOLUTE,
            161,
            64,
        ),
        # Absolute negative overflow clamps to default min (1% -> 3)
        ({CONF_OFFSET: -100}, OFFSET_TYPE_ABSOLUTE, 128, 3),
        # Absolute positive overflow clamps to default max (100% -> 255)
        ({CONF_OFFSET: 100}, OFFSET_TYPE_ABSOLUTE, 200, 255),
        # Relative: -25 -> 75% of master
        ({CONF_OFFSET: -25}, OFFSET_TYPE_RELATIVE, 200, 150),
        # Relative: +50 -> 1.5x clamps to 255
        ({CONF_OFFSET: 50}, OFFSET_TYPE_RELATIVE, 200, 255),
        # Relative: -100 -> 0x clamps to min
        ({CONF_OFFSET: -100}, OFFSET_TYPE_RELATIVE, 200, 3),
        # Custom min floor respected
        ({CONF_OFFSET: -50, CONF_MIN_BRIGHTNESS: 20}, OFFSET_TYPE_ABSOLUTE, 60, 51),
        # min > max misconfiguration is swapped instead of crashing
        (
            {CONF_OFFSET: 0, CONF_MIN_BRIGHTNESS: 20, CONF_MAX_BRIGHTNESS: 10},
            OFFSET_TYPE_ABSOLUTE,
            128,
            51,
        ),
        # Float offsets (config entries store floats) work
        ({CONF_OFFSET: -30.0, CONF_MAX_BRIGHTNESS: 70.0}, OFFSET_TYPE_ABSOLUTE, 161, 84),
    ],
)
def test_calculate_light_brightness(config, offset_type, master, expected):
    assert calculate_light_brightness(config, offset_type, master) == expected


def test_unknown_offset_type_falls_back_to_absolute():
    assert (
        calculate_light_brightness({CONF_OFFSET: 0}, "bogus", 128)
        == calculate_light_brightness({CONF_OFFSET: 0}, OFFSET_TYPE_ABSOLUTE, 128)
    )
