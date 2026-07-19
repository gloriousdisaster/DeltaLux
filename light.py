"""Light platform for DeltaLux."""

from __future__ import annotations

import asyncio
import logging
from typing import Any

from homeassistant.components.light import (
    ATTR_BRIGHTNESS,
    ATTR_COLOR_MODE,
    ATTR_COLOR_TEMP_KELVIN,
    ATTR_EFFECT,
    ATTR_EFFECT_LIST,
    ATTR_FLASH,
    ATTR_HS_COLOR,
    ATTR_MAX_COLOR_TEMP_KELVIN,
    ATTR_MIN_COLOR_TEMP_KELVIN,
    ATTR_RGB_COLOR,
    ATTR_RGBW_COLOR,
    ATTR_RGBWW_COLOR,
    ATTR_SUPPORTED_COLOR_MODES,
    ATTR_TRANSITION,
    ATTR_WHITE,
    ATTR_XY_COLOR,
    DOMAIN as LIGHT_DOMAIN,
    ColorMode,
    LightEntity,
    LightEntityFeature,
)
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import (
    ATTR_ENTITY_ID,
    ATTR_SUPPORTED_FEATURES,
    CONF_ENTITY_ID,
    CONF_NAME,
    SERVICE_TURN_OFF,
    SERVICE_TURN_ON,
    STATE_ON,
    STATE_UNAVAILABLE,
    STATE_UNKNOWN,
)
from homeassistant.core import HomeAssistant, State, callback
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
    DEFAULT_MAX_KELVIN,
    DEFAULT_MIN_BRIGHTNESS,
    DEFAULT_MIN_KELVIN,
    DEFAULT_OFFSET,
    DEFAULT_OFFSET_TYPE,
)
from .util import calculate_light_brightness

_LOGGER = logging.getLogger(__name__)

# Turn-on parameters forwarded verbatim to member lights. HA's service layer
# filters/converts them per member, so unsupported params are handled there.
# NOTE: color temperature is kelvin-only — HA passes ATTR_COLOR_TEMP_KELVIN to
# entities; the mired ATTR_COLOR_TEMP was removed from core in 2025.
FORWARDED_ATTRS = (
    ATTR_COLOR_TEMP_KELVIN,
    ATTR_HS_COLOR,
    ATTR_RGB_COLOR,
    ATTR_RGBW_COLOR,
    ATTR_RGBWW_COLOR,
    ATTR_XY_COLOR,
    ATTR_WHITE,
    ATTR_EFFECT,
    ATTR_FLASH,
    ATTR_TRANSITION,
)

# Feature bits a group may advertise. Member states can carry legacy feature
# bits (SUPPORT_BRIGHTNESS etc.) that are invalid on modern LightEntity, so
# everything else is masked out.
_FEATURE_MASK = (
    LightEntityFeature.EFFECT | LightEntityFeature.FLASH | LightEntityFeature.TRANSITION
)

# Modes that are not real color modes and may not be combined with them.
_NON_COLOR_MODES = {ColorMode.ONOFF, ColorMode.BRIGHTNESS, ColorMode.UNKNOWN}


async def async_setup_entry(
    hass: HomeAssistant,  # noqa: ARG001
    config_entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up the Offset Light Group from a config entry."""
    config = config_entry.data

    entities_config = {
        light[CONF_ENTITY_ID]: {
            CONF_OFFSET: light.get(CONF_OFFSET, DEFAULT_OFFSET),
            CONF_MIN_BRIGHTNESS: light.get(CONF_MIN_BRIGHTNESS, DEFAULT_MIN_BRIGHTNESS),
            CONF_MAX_BRIGHTNESS: light.get(CONF_MAX_BRIGHTNESS, DEFAULT_MAX_BRIGHTNESS),
        }
        for light in config.get(CONF_LIGHTS, [])
    }

    async_add_entities(
        [
            OffsetLightGroup(
                unique_id=config_entry.entry_id,
                name=config[CONF_NAME],
                entities_config=entities_config,
                offset_type=config.get(CONF_OFFSET_TYPE, DEFAULT_OFFSET_TYPE),
            )
        ]
    )


class OffsetLightGroup(LightEntity, RestoreEntity):
    """A light group whose members keep a brightness offset from the master."""

    _attr_has_entity_name = False
    _attr_should_poll = False
    _attr_icon = "mdi:lightbulb-group"

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

        self._is_on = False
        self._attr_available = False
        self._master_brightness: int = 128  # Stored master brightness (0-255)
        self._color_mode: ColorMode | None = None
        self._hs_color: tuple[float, float] | None = None
        self._color_temp_kelvin: int | None = None
        self._min_color_temp_kelvin: int = DEFAULT_MIN_KELVIN
        self._max_color_temp_kelvin: int = DEFAULT_MAX_KELVIN
        self._rgb_color: tuple[int, int, int] | None = None
        self._rgbw_color: tuple[int, int, int, int] | None = None
        self._rgbww_color: tuple[int, int, int, int, int] | None = None
        self._xy_color: tuple[float, float] | None = None
        self._effect: str | None = None
        self._effect_list: list[str] | None = None
        self._supported_color_modes: set[ColorMode] = {ColorMode.BRIGHTNESS}
        self._supported_features = LightEntityFeature(0)

    @property
    def is_on(self) -> bool:
        """Return True if entity is on."""
        return self._is_on

    @property
    def brightness(self) -> int | None:
        """Return the master brightness of the group."""
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
    def color_temp_kelvin(self) -> int | None:
        """Return the color temperature in Kelvin."""
        return self._color_temp_kelvin

    @property
    def min_color_temp_kelvin(self) -> int:
        """Return the coldest supported color temperature in Kelvin."""
        return self._min_color_temp_kelvin

    @property
    def max_color_temp_kelvin(self) -> int:
        """Return the warmest supported color temperature in Kelvin."""
        return self._max_color_temp_kelvin

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
    def effect(self) -> str | None:
        """Return the current effect."""
        return self._effect

    @property
    def effect_list(self) -> list[str] | None:
        """Return the list of supported effects."""
        return self._effect_list

    @property
    def supported_color_modes(self) -> set[ColorMode]:
        """Flag supported color modes."""
        return self._supported_color_modes

    @property
    def supported_features(self) -> LightEntityFeature:
        """Flag supported features."""
        return self._supported_features

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        """Return entity specific state attributes."""
        offsets = {
            entity_id: config.get(CONF_OFFSET, DEFAULT_OFFSET)
            for entity_id, config in self._entities_config.items()
        }
        return {
            ATTR_ENTITY_ID: list(self._entities_config),
            ATTR_MASTER_BRIGHTNESS: self._master_brightness,
            ATTR_OFFSETS: offsets,
        }

    async def async_added_to_hass(self) -> None:
        """Register callbacks and restore state."""
        await super().async_added_to_hass()

        if (last_state := await self.async_get_last_state()) is not None:
            brightness = last_state.attributes.get(
                ATTR_MASTER_BRIGHTNESS
            ) or last_state.attributes.get(ATTR_BRIGHTNESS)
            if brightness is not None:
                self._master_brightness = int(round(brightness))

        @callback
        def async_state_changed_listener(_event) -> None:
            """Handle member updates."""
            if self._update_state_from_members():
                self.async_write_ha_state()

        self.async_on_remove(
            async_track_state_change_event(
                self.hass,
                list(self._entities_config),
                async_state_changed_listener,
            )
        )

        self._update_state_from_members()

    @callback
    def _update_state_from_members(self) -> bool:
        """Recompute group state from member states. Returns True if changed."""
        before = self._state_snapshot()

        states = [
            state
            for entity_id in self._entities_config
            if (state := self.hass.states.get(entity_id)) is not None
            and state.state not in (STATE_UNAVAILABLE, STATE_UNKNOWN)
        ]
        on_states = [state for state in states if state.state == STATE_ON]

        self._attr_available = bool(states)
        self._is_on = bool(on_states)

        color_modes: set[ColorMode] = set()
        features = LightEntityFeature(0)
        effects: set[str] = set()
        min_kelvins: list[int] = []
        max_kelvins: list[int] = []

        for state in states:
            for mode in state.attributes.get(ATTR_SUPPORTED_COLOR_MODES) or ():
                try:
                    color_modes.add(ColorMode(mode))
                except ValueError:
                    _LOGGER.debug("Unknown color mode: %s", mode)

            raw_features = state.attributes.get(ATTR_SUPPORTED_FEATURES) or 0
            features |= LightEntityFeature(int(raw_features) & int(_FEATURE_MASK))

            if effect_list := state.attributes.get(ATTR_EFFECT_LIST):
                effects.update(effect_list)
            if min_k := state.attributes.get(ATTR_MIN_COLOR_TEMP_KELVIN):
                min_kelvins.append(min_k)
            if max_k := state.attributes.get(ATTR_MAX_COLOR_TEMP_KELVIN):
                max_kelvins.append(max_k)

        # BRIGHTNESS/ONOFF may not be combined with real color modes, so when
        # members are mixed (e.g. a dimmer plus color bulbs), only the real
        # color modes are advertised; brightness support is implied by them.
        real_color_modes = color_modes - _NON_COLOR_MODES
        if real_color_modes:
            self._supported_color_modes = real_color_modes
        elif ColorMode.BRIGHTNESS in color_modes:
            self._supported_color_modes = {ColorMode.BRIGHTNESS}
        elif ColorMode.ONOFF in color_modes:
            self._supported_color_modes = {ColorMode.ONOFF}
        else:
            self._supported_color_modes = {ColorMode.BRIGHTNESS}

        self._supported_features = features
        self._effect_list = sorted(effects) if effects else None
        self._min_color_temp_kelvin = min(min_kelvins) if min_kelvins else DEFAULT_MIN_KELVIN
        self._max_color_temp_kelvin = max(max_kelvins) if max_kelvins else DEFAULT_MAX_KELVIN

        if on_states:
            self._update_color_state_from_member(self._pick_color_source(on_states))

        return self._state_snapshot() != before

    @staticmethod
    def _pick_color_source(on_states: list[State]) -> State:
        """Pick the member whose color state the group mirrors.

        Prefer a member reporting a real color mode so a brightness-only bulb
        can't blank out the group's color attributes.
        """
        for state in on_states:
            if state.attributes.get(ATTR_COLOR_MODE) not in _NON_COLOR_MODES:
                return state
        return on_states[0]

    @callback
    def _update_color_state_from_member(self, state: State) -> None:
        """Mirror color attributes from a member state."""
        attrs = state.attributes
        try:
            color_mode = ColorMode(attrs[ATTR_COLOR_MODE])
        except (KeyError, ValueError):
            color_mode = None
        # Never report a color mode the group doesn't advertise (HA rejects it)
        if color_mode not in self._supported_color_modes:
            color_mode = next(iter(self._supported_color_modes))
        self._color_mode = color_mode
        self._hs_color = attrs.get(ATTR_HS_COLOR)
        self._color_temp_kelvin = attrs.get(ATTR_COLOR_TEMP_KELVIN)
        self._rgb_color = attrs.get(ATTR_RGB_COLOR)
        self._rgbw_color = attrs.get(ATTR_RGBW_COLOR)
        self._rgbww_color = attrs.get(ATTR_RGBWW_COLOR)
        self._xy_color = attrs.get(ATTR_XY_COLOR)
        self._effect = attrs.get(ATTR_EFFECT)

    def _state_snapshot(self) -> tuple:
        """Snapshot of all externally visible state, for change detection."""
        return (
            self._is_on,
            self._attr_available,
            self._color_mode,
            self._hs_color,
            self._color_temp_kelvin,
            self._min_color_temp_kelvin,
            self._max_color_temp_kelvin,
            self._rgb_color,
            self._rgbw_color,
            self._rgbww_color,
            self._xy_color,
            self._effect,
            tuple(self._effect_list) if self._effect_list else None,
            tuple(sorted(self._supported_color_modes)),
            self._supported_features,
        )

    @callback
    def _store_color_from_kwargs(self, kwargs: dict[str, Any]) -> None:
        """Optimistically reflect a color change until members report back."""
        mode_for_attr = {
            ATTR_HS_COLOR: ColorMode.HS,
            ATTR_RGB_COLOR: ColorMode.RGB,
            ATTR_RGBW_COLOR: ColorMode.RGBW,
            ATTR_RGBWW_COLOR: ColorMode.RGBWW,
            ATTR_XY_COLOR: ColorMode.XY,
            ATTR_COLOR_TEMP_KELVIN: ColorMode.COLOR_TEMP,
        }
        for attr, mode in mode_for_attr.items():
            if attr not in kwargs:
                continue
            setattr(self, f"_{attr}", kwargs[attr])
            if mode in self._supported_color_modes:
                self._color_mode = mode
        if ATTR_EFFECT in kwargs:
            self._effect = kwargs[ATTR_EFFECT]

    async def async_turn_on(self, **kwargs: Any) -> None:
        """Turn on the light group."""
        if ATTR_BRIGHTNESS in kwargs:
            self._master_brightness = int(round(kwargs[ATTR_BRIGHTNESS]))

        explicit_brightness = ATTR_BRIGHTNESS in kwargs
        group_was_on = self._is_on

        common: dict[str, Any] = {
            attr: kwargs[attr] for attr in FORWARDED_ATTRS if attr in kwargs
        }

        calls: list[dict[str, Any]] = []
        for entity_id in self._entities_config:
            member = self.hass.states.get(entity_id)
            member_on = member is not None and member.state == STATE_ON
            service_data: dict[str, Any] = {ATTR_ENTITY_ID: entity_id, **common}

            # Send a calculated brightness when it was explicitly changed, when
            # the group itself is being switched on, or when this member is off
            # and needs to come back at its offset level. A pure color/effect
            # change on an already-on member must not stomp its brightness.
            if explicit_brightness or not group_was_on or not member_on:
                service_data[ATTR_BRIGHTNESS] = calculate_light_brightness(
                    self._entities_config[entity_id],
                    self._offset_type,
                    self._master_brightness,
                )
            calls.append(service_data)

        results = await asyncio.gather(
            *(
                self.hass.services.async_call(
                    LIGHT_DOMAIN,
                    SERVICE_TURN_ON,
                    service_data,
                    blocking=True,
                    context=self._context,
                )
                for service_data in calls
            ),
            return_exceptions=True,
        )

        any_ok = False
        for service_data, result in zip(calls, results):
            if isinstance(result, Exception):
                _LOGGER.warning(
                    "Failed to turn on %s: %s", service_data[ATTR_ENTITY_ID], result
                )
            else:
                any_ok = True

        if any_ok:
            self._is_on = True
            self._store_color_from_kwargs(kwargs)
        self.async_write_ha_state()

    async def async_turn_off(self, **kwargs: Any) -> None:
        """Turn off the light group."""
        service_data: dict[str, Any] = {ATTR_ENTITY_ID: list(self._entities_config)}
        if ATTR_TRANSITION in kwargs:
            service_data[ATTR_TRANSITION] = kwargs[ATTR_TRANSITION]

        try:
            await self.hass.services.async_call(
                LIGHT_DOMAIN,
                SERVICE_TURN_OFF,
                service_data,
                blocking=True,
                context=self._context,
            )
        except Exception as err:  # noqa: BLE001 - keep group state honest
            _LOGGER.warning("Failed to turn off %s: %s", self.entity_id, err)
            return

        # _master_brightness is kept so it's restored on next turn_on
        self._is_on = False
        self.async_write_ha_state()
