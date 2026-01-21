"""Light platform for DeltaLux."""

from __future__ import annotations

import logging
from typing import Any

from homeassistant.components.light import (
    ATTR_BRIGHTNESS,
    ATTR_COLOR_MODE,
    ATTR_COLOR_TEMP,
    ATTR_HS_COLOR,
    ATTR_RGB_COLOR,
    ATTR_RGBW_COLOR,
    ATTR_RGBWW_COLOR,
    ATTR_SUPPORTED_COLOR_MODES,
    ATTR_TRANSITION,
    ATTR_XY_COLOR,
    ColorMode,
    LightEntity,
    LightEntityFeature,
)
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import (
    ATTR_ENTITY_ID,
    CONF_ENTITY_ID,
    CONF_NAME,
    SERVICE_TURN_OFF,
    SERVICE_TURN_ON,
    STATE_ON,
    STATE_UNAVAILABLE,
    STATE_UNKNOWN,
)
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.event import async_track_state_change_event
from homeassistant.helpers.restore_state import RestoreEntity

from .const import (
    ATTR_MASTER_BRIGHTNESS,
    ATTR_OFFSETS,
    CONF_LIGHTS,
    CONF_MAX_BRIGHTNESS,
    CONF_MIN_BRIGHTNESS,
    CONF_OFFSET,
    CONF_OFFSET_TYPE,
    DEFAULT_MAX_BRIGHTNESS,
    DEFAULT_MIN_BRIGHTNESS,
    DEFAULT_OFFSET,
    DEFAULT_OFFSET_TYPE,
    OFFSET_TYPE_RELATIVE,
)

_LOGGER = logging.getLogger(__name__)

# Color attributes to forward
COLOR_ATTRS = [
    ATTR_HS_COLOR,
    ATTR_COLOR_TEMP,
    ATTR_RGB_COLOR,
    ATTR_RGBW_COLOR,
    ATTR_RGBWW_COLOR,
    ATTR_XY_COLOR,
]


async def async_setup_entry(
    hass: HomeAssistant,  # noqa: ARG001
    config_entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up the Offset Light Group from a config entry."""
    config = config_entry.data

    name = config[CONF_NAME]
    lights_config = config.get(CONF_LIGHTS, [])
    offset_type = config.get(CONF_OFFSET_TYPE, DEFAULT_OFFSET_TYPE)

    # Build entity config dict with offset, min, max
    entities_config = {}
    for light in lights_config:
        entity_id = light[CONF_ENTITY_ID]
        entities_config[entity_id] = {
            CONF_OFFSET: light.get(CONF_OFFSET, DEFAULT_OFFSET),
            CONF_MIN_BRIGHTNESS: light.get(CONF_MIN_BRIGHTNESS, DEFAULT_MIN_BRIGHTNESS),
            CONF_MAX_BRIGHTNESS: light.get(CONF_MAX_BRIGHTNESS, DEFAULT_MAX_BRIGHTNESS),
        }

    async_add_entities(
        [
            OffsetLightGroup(
                unique_id=config_entry.entry_id,
                name=name,
                entities_config=entities_config,
                offset_type=offset_type,
            )
        ]
    )


class OffsetLightGroup(LightEntity, RestoreEntity):
    """Representation of an Offset Light Group."""

    _attr_has_entity_name = False
    _attr_should_poll = False

    def __init__(
        self,
        unique_id: str,
        name: str,
        entities_config: dict[str, dict[str, Any]],
        offset_type: str,
    ) -> None:
        """Initialize the light group.

        Args:
            unique_id: Unique identifier for this entity
            name: Friendly name for the group
            entities_config: Dict of entity_id -> config with offset, min, max
            offset_type: 'absolute' or 'relative'
        """
        self._attr_unique_id = unique_id
        self._attr_name = name
        self._entities_config = entities_config
        self._offset_type = offset_type

        # State
        self._is_on = False
        self._master_brightness: int = 128  # Stored master brightness (0-255)
        self._brightness: int = 128
        self._color_mode: ColorMode | None = None
        self._hs_color: tuple[float, float] | None = None
        self._color_temp: int | None = None
        self._rgb_color: tuple[int, int, int] | None = None
        self._rgbw_color: tuple[int, int, int, int] | None = None
        self._rgbww_color: tuple[int, int, int, int, int] | None = None
        self._xy_color: tuple[float, float] | None = None
        self._supported_color_modes: set[ColorMode] = set()
        self._supported_features = LightEntityFeature(0)

        # Track if we're currently applying changes (prevent feedback loops)
        self._applying_state = False

    @property
    def is_on(self) -> bool:
        """Return True if entity is on."""
        return self._is_on

    @property
    def brightness(self) -> int | None:
        """Return the brightness of this light."""
        return self._master_brightness if self._is_on else None

    @property
    def color_mode(self) -> ColorMode | None:
        """Return the color mode of the light."""
        return self._color_mode

    @property
    def hs_color(self) -> tuple[float, float] | None:
        """Return the hue and saturation color value."""
        return self._hs_color

    @property
    def color_temp(self) -> int | None:
        """Return the CT color value in mireds."""
        return self._color_temp

    @property
    def rgb_color(self) -> tuple[int, int, int] | None:
        """Return the rgb color value."""
        return self._rgb_color

    @property
    def rgbw_color(self) -> tuple[int, int, int, int] | None:
        """Return the rgbw color value."""
        return self._rgbw_color

    @property
    def rgbww_color(self) -> tuple[int, int, int, int, int] | None:
        """Return the rgbww color value."""
        return self._rgbww_color

    @property
    def xy_color(self) -> tuple[float, float] | None:
        """Return the xy color value."""
        return self._xy_color

    @property
    def supported_color_modes(self) -> set[ColorMode] | None:
        """Flag supported color modes."""
        return self._supported_color_modes or {ColorMode.BRIGHTNESS}

    @property
    def supported_features(self) -> LightEntityFeature:
        """Flag supported features."""
        return self._supported_features

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        """Return entity specific state attributes."""
        # Build offsets dict for backward compatibility
        offsets = {
            entity_id: config.get(CONF_OFFSET, DEFAULT_OFFSET)
            for entity_id, config in self._entities_config.items()
        }
        return {
            ATTR_ENTITY_ID: list(self._entities_config.keys()),
            ATTR_MASTER_BRIGHTNESS: self._master_brightness,
            ATTR_OFFSETS: offsets,
        }

    def _calculate_light_brightness(
        self, entity_id: str, master_brightness: int
    ) -> int:
        """Calculate brightness for a light based on offset and min/max."""
        config = self._entities_config.get(entity_id, {})
        offset = config.get(CONF_OFFSET, DEFAULT_OFFSET)
        min_brightness_pct = config.get(CONF_MIN_BRIGHTNESS, DEFAULT_MIN_BRIGHTNESS)
        max_brightness_pct = config.get(CONF_MAX_BRIGHTNESS, DEFAULT_MAX_BRIGHTNESS)

        # Convert min/max from percentage (1-100) to 0-255 scale
        min_brightness = int((min_brightness_pct / 100) * 255)
        max_brightness = int((max_brightness_pct / 100) * 255)

        if self._offset_type == OFFSET_TYPE_RELATIVE:
            # Relative mode: offset is a multiplier (e.g., 0.75 = 75% of master)
            # But we store as percentage, so -25 means 75% of master
            multiplier = (100 + offset) / 100
            target = int(master_brightness * multiplier)
        else:
            # Absolute mode: offset is percentage points
            # Convert master from 0-255 to 0-100, apply offset, convert back
            master_pct = (master_brightness / 255) * 100
            target_pct = master_pct + offset
            target = int((target_pct / 100) * 255)

        # Clamp to valid range using per-light min/max
        return max(min_brightness, min(max_brightness, target))

    async def async_added_to_hass(self) -> None:
        """Register callbacks and restore state."""
        await super().async_added_to_hass()

        # Restore previous state
        if (last_state := await self.async_get_last_state()) is not None:
            self._is_on = last_state.state == STATE_ON
            # Try to restore brightness from our attribute first, then standard
            brightness = last_state.attributes.get(ATTR_MASTER_BRIGHTNESS)
            if brightness is None:
                brightness = last_state.attributes.get(ATTR_BRIGHTNESS)
            if brightness is not None:
                self._master_brightness = brightness

        # Track state changes of member lights
        @callback
        def async_state_changed_listener(_event) -> None:
            """Handle child updates."""
            if self._applying_state:
                return
            self._update_state_from_members()
            self.async_write_ha_state()

        self.async_on_remove(
            async_track_state_change_event(
                self.hass,
                list(self._entities_config.keys()),
                async_state_changed_listener,
            )
        )

        # Initial state update
        self._update_state_from_members()

    @callback
    def _update_state_from_members(self) -> None:
        """Update group state from member light states."""
        on_states = []
        brightness_values = []
        color_modes: set[ColorMode] = set()
        features = LightEntityFeature(0)

        for entity_id in self._entities_config:
            state = self.hass.states.get(entity_id)
            if state is None or state.state in (STATE_UNAVAILABLE, STATE_UNKNOWN):
                continue

            if state.state == STATE_ON:
                on_states.append(entity_id)
                if brightness := state.attributes.get(ATTR_BRIGHTNESS):
                    brightness_values.append(brightness)

            # Collect supported color modes (convert strings to ColorMode enum)
            if modes := state.attributes.get(ATTR_SUPPORTED_COLOR_MODES):
                for mode in modes:
                    try:
                        color_modes.add(ColorMode(mode))
                    except ValueError:
                        _LOGGER.debug("Unknown color mode: %s", mode)

            # Collect supported features
            if entity_features := state.attributes.get("supported_features"):
                features |= LightEntityFeature(entity_features)

        self._is_on = len(on_states) > 0
        self._supported_color_modes = (
            color_modes if color_modes else {ColorMode.BRIGHTNESS}
        )
        self._supported_features = features

        # Update color attributes from first "on" light (they should match)
        if on_states:
            first_on = self.hass.states.get(on_states[0])
            if first_on:
                # Convert color_mode string to ColorMode enum
                if cm := first_on.attributes.get(ATTR_COLOR_MODE):
                    try:
                        self._color_mode = ColorMode(cm)
                    except ValueError:
                        self._color_mode = None
                else:
                    self._color_mode = None
                self._hs_color = first_on.attributes.get(ATTR_HS_COLOR)
                self._color_temp = first_on.attributes.get(ATTR_COLOR_TEMP)
                self._rgb_color = first_on.attributes.get(ATTR_RGB_COLOR)
                self._rgbw_color = first_on.attributes.get(ATTR_RGBW_COLOR)
                self._rgbww_color = first_on.attributes.get(ATTR_RGBWW_COLOR)
                self._xy_color = first_on.attributes.get(ATTR_XY_COLOR)

    def _store_color_from_kwargs(self, kwargs: dict[str, Any]) -> None:
        """Store color attributes from kwargs to local state."""
        if ATTR_HS_COLOR in kwargs:
            self._hs_color = kwargs[ATTR_HS_COLOR]
            self._color_mode = ColorMode.HS
        if ATTR_RGB_COLOR in kwargs:
            self._rgb_color = kwargs[ATTR_RGB_COLOR]
            self._color_mode = ColorMode.RGB
        if ATTR_RGBW_COLOR in kwargs:
            self._rgbw_color = kwargs[ATTR_RGBW_COLOR]
            self._color_mode = ColorMode.RGBW
        if ATTR_RGBWW_COLOR in kwargs:
            self._rgbww_color = kwargs[ATTR_RGBWW_COLOR]
            self._color_mode = ColorMode.RGBWW
        if ATTR_XY_COLOR in kwargs:
            self._xy_color = kwargs[ATTR_XY_COLOR]
            self._color_mode = ColorMode.XY
        if ATTR_COLOR_TEMP in kwargs:
            self._color_temp = kwargs[ATTR_COLOR_TEMP]
            self._color_mode = ColorMode.COLOR_TEMP

    async def async_turn_on(self, **kwargs: Any) -> None:
        """Turn on the light group."""
        self._applying_state = True

        try:
            # Handle brightness
            if ATTR_BRIGHTNESS in kwargs:
                self._master_brightness = kwargs[ATTR_BRIGHTNESS]

            # Store color attributes locally so group state reflects the color
            self._store_color_from_kwargs(kwargs)

            # Build service data for each light
            for entity_id in self._entities_config:
                service_data: dict[str, Any] = {ATTR_ENTITY_ID: entity_id}

                # Calculate this light's brightness
                service_data[ATTR_BRIGHTNESS] = self._calculate_light_brightness(
                    entity_id, self._master_brightness
                )

                # Forward color attributes if provided
                for attr in COLOR_ATTRS:
                    if attr in kwargs:
                        service_data[attr] = kwargs[attr]

                # Forward transition
                if ATTR_TRANSITION in kwargs:
                    service_data[ATTR_TRANSITION] = kwargs[ATTR_TRANSITION]

                await self.hass.services.async_call(
                    "light",
                    SERVICE_TURN_ON,
                    service_data,
                    blocking=True,
                )

            self._is_on = True
            self.async_write_ha_state()

        finally:
            self._applying_state = False

    async def async_turn_off(self, **kwargs: Any) -> None:
        """Turn off the light group."""
        self._applying_state = True

        try:
            service_data: dict[str, Any] = {
                ATTR_ENTITY_ID: list(self._entities_config.keys())
            }

            # Forward transition
            if ATTR_TRANSITION in kwargs:
                service_data[ATTR_TRANSITION] = kwargs[ATTR_TRANSITION]

            await self.hass.services.async_call(
                "light",
                SERVICE_TURN_OFF,
                service_data,
                blocking=True,
            )

            self._is_on = False
            # Note: We keep _master_brightness so it's restored on next turn_on
            self.async_write_ha_state()

        finally:
            self._applying_state = False
