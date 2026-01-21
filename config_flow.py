"""Config flow for DeltaLux integration."""

from __future__ import annotations

import logging
from typing import Any

import voluptuous as vol
import yaml
from homeassistant import config_entries
from homeassistant.components.light import DOMAIN as LIGHT_DOMAIN
from homeassistant.const import CONF_ENTITY_ID, CONF_NAME
from homeassistant.core import HomeAssistant, callback
from homeassistant.data_entry_flow import FlowResult
from homeassistant.helpers import entity_registry as er
from homeassistant.helpers.selector import (
    EntitySelector,
    EntitySelectorConfig,
    NumberSelector,
    NumberSelectorConfig,
    NumberSelectorMode,
    SelectSelector,
    SelectSelectorConfig,
    SelectSelectorMode,
    TextSelector,
    TextSelectorConfig,
    TextSelectorType,
)

from .const import (
    CONF_LIGHTS,
    CONF_MAX_BRIGHTNESS,
    CONF_MIN_BRIGHTNESS,
    CONF_OFFSET,
    CONF_OFFSET_TYPE,
    DEFAULT_MAX_BRIGHTNESS,
    DEFAULT_MIN_BRIGHTNESS,
    DEFAULT_OFFSET,
    DEFAULT_OFFSET_TYPE,
    DOMAIN,
    OFFSET_TYPE_ABSOLUTE,
    OFFSET_TYPE_RELATIVE,
)

_LOGGER = logging.getLogger(__name__)


def config_to_yaml(config: dict[str, Any]) -> str:
    """Convert a config entry data dict to YAML string."""
    lines = []
    lines.append(f"name: {config.get(CONF_NAME, '')}")
    lines.append(f"offset_type: {config.get(CONF_OFFSET_TYPE, DEFAULT_OFFSET_TYPE)}")
    lines.append("lights:")

    for light in config.get(CONF_LIGHTS, []):
        entity_id = light.get(CONF_ENTITY_ID, "")
        offset = int(light.get(CONF_OFFSET, DEFAULT_OFFSET))
        min_br = int(light.get(CONF_MIN_BRIGHTNESS, DEFAULT_MIN_BRIGHTNESS))
        max_br = int(light.get(CONF_MAX_BRIGHTNESS, DEFAULT_MAX_BRIGHTNESS))
        lines.append(f"  - entity_id: {entity_id}")
        lines.append(f"    offset: {offset}")
        lines.append(f"    min_brightness: {min_br}")
        lines.append(f"    max_brightness: {max_br}")

    return "\n".join(lines)


def _validate_light_entry(
    light: Any, index: int
) -> tuple[dict[str, Any] | None, str | None]:
    """Validate a single light entry from YAML. Returns (config, error)."""
    if not isinstance(light, dict):
        return None, f"Light entry {index + 1} must be a dictionary"

    if "entity_id" not in light:
        return None, f"Light entry {index + 1} missing entity_id"

    entity_id = light["entity_id"]
    if not entity_id.startswith("light."):
        return None, f"Invalid entity_id: {entity_id} (must start with 'light.')"

    return {
        CONF_ENTITY_ID: entity_id,
        CONF_OFFSET: light.get("offset", DEFAULT_OFFSET),
        CONF_MIN_BRIGHTNESS: light.get("min_brightness", DEFAULT_MIN_BRIGHTNESS),
        CONF_MAX_BRIGHTNESS: light.get("max_brightness", DEFAULT_MAX_BRIGHTNESS),
    }, None


def yaml_to_config(yaml_string: str) -> tuple[dict[str, Any] | None, str | None]:
    """Parse YAML string to config dict. Returns (config, error_message)."""
    try:
        parsed = yaml.safe_load(yaml_string)
    except yaml.YAMLError as e:
        return None, f"Invalid YAML syntax: {e}"

    if not isinstance(parsed, dict):
        return None, "YAML must be a dictionary/mapping"

    if "name" not in parsed:
        return None, "Missing required field: name"

    if "lights" not in parsed:
        return None, "Missing required field: lights"

    if not isinstance(parsed["lights"], list):
        return None, "lights must be a list"

    if len(parsed["lights"]) < 2:
        return None, "At least 2 lights are required"

    # Build config structure
    lights_config = []
    for i, light in enumerate(parsed["lights"]):
        light_config, error = _validate_light_entry(light, i)
        if error:
            return None, error
        lights_config.append(light_config)

    return {
        CONF_NAME: parsed["name"],
        CONF_OFFSET_TYPE: parsed.get("offset_type", DEFAULT_OFFSET_TYPE),
        CONF_LIGHTS: lights_config,
    }, None


def get_light_entities(hass: HomeAssistant) -> list[str]:
    """Get list of light entity IDs, excluding offset light groups."""
    entity_reg = er.async_get(hass)

    lights = []
    for entity_id in hass.states.async_entity_ids(LIGHT_DOMAIN):
        # Exclude our own offset light groups to prevent recursion
        entry = entity_reg.async_get(entity_id)
        if entry and entry.platform == DOMAIN:
            continue
        lights.append(entity_id)

    return sorted(lights)


class OffsetLightGroupConfigFlow(config_entries.ConfigFlow, domain=DOMAIN):
    """Handle a config flow for Offset Light Group."""

    VERSION = 1

    def __init__(self) -> None:
        """Initialize the config flow."""
        self._data: dict[str, Any] = {}
        self._selected_lights: list[str] = []

    async def async_step_user(
        self, user_input: dict[str, Any] | None = None
    ) -> FlowResult:
        """Handle the initial step - choose setup mode."""
        if user_input is not None:
            mode = user_input.get("setup_mode", "gui")
            if mode == "yaml":
                return await self.async_step_yaml()
            return await self.async_step_gui()

        return self.async_show_form(
            step_id="user",
            data_schema=vol.Schema(
                {
                    vol.Required("setup_mode", default="gui"): SelectSelector(
                        SelectSelectorConfig(
                            options=[
                                {"value": "gui", "label": "Setup with GUI"},
                                {"value": "yaml", "label": "Import from YAML"},
                            ],
                            mode=SelectSelectorMode.LIST,
                        )
                    ),
                }
            ),
        )

    async def async_step_yaml(
        self, user_input: dict[str, Any] | None = None
    ) -> FlowResult:
        """Handle YAML import."""
        errors: dict[str, str] = {}
        error_detail = ""

        if user_input is not None:
            yaml_input = user_input.get("yaml_config", "")

            config, error = yaml_to_config(yaml_input)

            if error:
                errors["yaml_config"] = "invalid_yaml"
                error_detail = f"**Error:** {error}"
                return self.async_show_form(
                    step_id="yaml",
                    data_schema=vol.Schema(
                        {
                            vol.Required(
                                "yaml_config", default=yaml_input
                            ): TextSelector(
                                TextSelectorConfig(
                                    type=TextSelectorType.TEXT,
                                    multiline=True,
                                )
                            ),
                        }
                    ),
                    errors=errors,
                    description_placeholders={
                        "error_detail": error_detail,
                    },
                )

            # Check for duplicate names
            existing_names = [
                entry.data.get(CONF_NAME, "").lower()
                for entry in self._async_current_entries()
            ]
            if config[CONF_NAME].lower() in existing_names:
                errors["yaml_config"] = "name_exists"
                group_name = config[CONF_NAME]
                error_detail = f"**Error:** A group named '{group_name}' already exists"
                return self.async_show_form(
                    step_id="yaml",
                    data_schema=vol.Schema(
                        {
                            vol.Required(
                                "yaml_config", default=yaml_input
                            ): TextSelector(
                                TextSelectorConfig(
                                    type=TextSelectorType.TEXT,
                                    multiline=True,
                                )
                            ),
                        }
                    ),
                    errors=errors,
                    description_placeholders={
                        "error_detail": error_detail,
                    },
                )

            # Create the config entry
            return self.async_create_entry(
                title=config[CONF_NAME],
                data=config,
            )

        return self.async_show_form(
            step_id="yaml",
            data_schema=vol.Schema(
                {
                    vol.Required("yaml_config", default=""): TextSelector(
                        TextSelectorConfig(
                            type=TextSelectorType.TEXT,
                            multiline=True,
                        )
                    ),
                }
            ),
            errors=errors,
            description_placeholders={
                "error_detail": "",
            },
        )

    async def async_step_gui(
        self, user_input: dict[str, Any] | None = None
    ) -> FlowResult:
        """Handle the GUI setup step - name and light selection."""
        errors: dict[str, str] = {}

        if user_input is not None:
            self._data[CONF_NAME] = user_input[CONF_NAME]
            self._selected_lights = user_input[CONF_ENTITY_ID]

            if len(self._selected_lights) < 2:
                errors["base"] = "need_two_lights"
            else:
                # Check for duplicate names
                existing_names = [
                    entry.data.get(CONF_NAME, "").lower()
                    for entry in self._async_current_entries()
                ]
                if user_input[CONF_NAME].lower() in existing_names:
                    errors[CONF_NAME] = "name_exists"
                else:
                    # Move to offset configuration
                    return await self.async_step_offsets()

        # Get available lights
        available_lights = get_light_entities(self.hass)

        data_schema = vol.Schema(
            {
                vol.Required(CONF_NAME): str,
                vol.Required(CONF_ENTITY_ID): EntitySelector(
                    EntitySelectorConfig(
                        domain=LIGHT_DOMAIN,
                        multiple=True,
                    )
                ),
            }
        )

        return self.async_show_form(
            step_id="gui",
            data_schema=data_schema,
            errors=errors,
            description_placeholders={
                "light_count": str(len(available_lights)),
            },
        )

    async def async_step_offsets(
        self, user_input: dict[str, Any] | None = None
    ) -> FlowResult:
        """Handle offset configuration for each light."""
        errors: dict[str, str] = {}

        if user_input is not None:
            # Build the lights config with offsets and min/max
            lights_config = []
            for entity_id in self._selected_lights:
                # Get friendly name to match form field
                state = self.hass.states.get(entity_id)
                if state:
                    friendly_name = state.attributes.get("friendly_name", entity_id)
                else:
                    friendly_name = entity_id

                offset_key = f"{friendly_name} Offset"
                min_key = f"{friendly_name} Min"
                max_key = f"{friendly_name} Max"
                offset = user_input.get(offset_key, DEFAULT_OFFSET)
                min_bright = user_input.get(min_key, DEFAULT_MIN_BRIGHTNESS)
                max_bright = user_input.get(max_key, DEFAULT_MAX_BRIGHTNESS)

                lights_config.append(
                    {
                        CONF_ENTITY_ID: entity_id,
                        CONF_OFFSET: offset,
                        CONF_MIN_BRIGHTNESS: min_bright,
                        CONF_MAX_BRIGHTNESS: max_bright,
                    }
                )

            self._data[CONF_LIGHTS] = lights_config
            offset_type = user_input.get(CONF_OFFSET_TYPE, DEFAULT_OFFSET_TYPE)
            self._data[CONF_OFFSET_TYPE] = offset_type

            # Create the config entry
            return self.async_create_entry(
                title=self._data[CONF_NAME],
                data=self._data,
            )

        # Build dynamic schema with offset field for each light
        offset_type_options = [
            {"value": OFFSET_TYPE_ABSOLUTE, "label": "Absolute (percentage points)"},
            {"value": OFFSET_TYPE_RELATIVE, "label": "Relative (multiplier)"},
        ]
        schema_dict = {
            vol.Required(CONF_OFFSET_TYPE, default=DEFAULT_OFFSET_TYPE): SelectSelector(
                SelectSelectorConfig(
                    options=offset_type_options,
                    mode=SelectSelectorMode.DROPDOWN,
                )
            ),
        }

        # Add offset, min, max fields for each selected light using friendly names
        for _, entity_id in enumerate(self._selected_lights):
            # Get friendly name if available
            state = self.hass.states.get(entity_id)
            if state:
                friendly_name = state.attributes.get("friendly_name", entity_id)
            else:
                friendly_name = entity_id

            # Offset field
            schema_dict[
                vol.Required(f"{friendly_name} Offset", default=DEFAULT_OFFSET)
            ] = NumberSelector(
                NumberSelectorConfig(
                    min=-100,
                    max=100,
                    step=1,
                    mode=NumberSelectorMode.BOX,
                    unit_of_measurement="%",
                )
            )

            # Min brightness field
            schema_dict[
                vol.Required(f"{friendly_name} Min", default=DEFAULT_MIN_BRIGHTNESS)
            ] = NumberSelector(
                NumberSelectorConfig(
                    min=1,
                    max=100,
                    step=1,
                    mode=NumberSelectorMode.BOX,
                    unit_of_measurement="%",
                )
            )

            # Max brightness field
            schema_dict[
                vol.Required(f"{friendly_name} Max", default=DEFAULT_MAX_BRIGHTNESS)
            ] = NumberSelector(
                NumberSelectorConfig(
                    min=1,
                    max=100,
                    step=1,
                    mode=NumberSelectorMode.BOX,
                    unit_of_measurement="%",
                )
            )

        return self.async_show_form(
            step_id="offsets",
            data_schema=vol.Schema(schema_dict),
            errors=errors,
            description_placeholders={
                "light_list": ", ".join(self._selected_lights),
            },
        )

    @staticmethod
    @callback
    def async_get_options_flow(
        config_entry: config_entries.ConfigEntry,
    ) -> config_entries.OptionsFlow:
        """Create the options flow."""
        return OffsetLightGroupOptionsFlow(config_entry)


class OffsetLightGroupOptionsFlow(config_entries.OptionsFlow):
    """Handle options flow for Offset Light Group."""

    def __init__(self, config_entry: config_entries.ConfigEntry) -> None:
        """Initialize options flow."""
        self._config_entry = config_entry
        self._selected_lights: list[str] = []
        self._removed_lights: list[str] = []
        self._added_lights: list[str] = []
        self._action: str = ""

    def _get_friendly_name(self, entity_id: str) -> str:
        """Get the friendly name for an entity."""
        state = self.hass.states.get(entity_id)
        if state and state.attributes.get("friendly_name"):
            return state.attributes["friendly_name"]
        return entity_id

    async def async_step_init(
        self, _user_input: dict[str, Any] | None = None
    ) -> FlowResult:
        """First step - choose what to configure."""
        return self.async_show_menu(
            step_id="init",
            menu_options=["manage_lights", "adjust_offsets", "edit_yaml"],
            description_placeholders={
                "name": self._config_entry.title,
            },
        )

    async def async_step_manage_lights(
        self, user_input: dict[str, Any] | None = None
    ) -> FlowResult:
        """Manage which lights are in the group."""
        errors: dict[str, str] = {}

        # Get current lights in the group
        current_lights = [
            light[CONF_ENTITY_ID]
            for light in self._config_entry.data.get(CONF_LIGHTS, [])
        ]

        if user_input is not None:
            new_lights = user_input.get(CONF_ENTITY_ID, [])

            if len(new_lights) < 2:
                errors["base"] = "need_two_lights"
            else:
                # Determine which lights were added vs kept
                self._selected_lights = new_lights
                self._removed_lights = [
                    eid for eid in current_lights if eid not in new_lights
                ]
                self._added_lights = [
                    eid for eid in new_lights if eid not in current_lights
                ]

                # If new lights were added, go to offset configuration for them
                if self._added_lights:
                    return await self.async_step_new_light_offsets()
                # No new lights, just save updated list (preserving existing offsets)
                return await self._async_save_light_changes()

        return self.async_show_form(
            step_id="manage_lights",
            data_schema=vol.Schema(
                {
                    vol.Required(
                        CONF_ENTITY_ID, default=current_lights
                    ): EntitySelector(
                        EntitySelectorConfig(
                            domain=LIGHT_DOMAIN,
                            multiple=True,
                        )
                    ),
                }
            ),
            errors=errors,
            description_placeholders={
                "current_count": str(len(current_lights)),
            },
        )

    async def async_step_new_light_offsets(
        self, user_input: dict[str, Any] | None = None
    ) -> FlowResult:
        """Configure offsets for newly added lights."""
        errors: dict[str, str] = {}

        if user_input is not None:
            # Convert friendly names back to entity_id -> config mapping
            entity_configs = {}
            for entity_id in self._added_lights:
                friendly_name = self._get_friendly_name(entity_id)
                offset_key = f"{friendly_name} Offset"
                min_key = f"{friendly_name} Min"
                max_key = f"{friendly_name} Max"
                entity_configs[entity_id] = {
                    CONF_OFFSET: user_input.get(offset_key, DEFAULT_OFFSET),
                    CONF_MIN_BRIGHTNESS: user_input.get(
                        min_key, DEFAULT_MIN_BRIGHTNESS
                    ),
                    CONF_MAX_BRIGHTNESS: user_input.get(
                        max_key, DEFAULT_MAX_BRIGHTNESS
                    ),
                }
            # Save all changes including new light offsets
            return await self._async_save_light_changes(entity_configs)

        # Build schema for new lights only using friendly names
        schema_dict = {}

        for entity_id in self._added_lights:
            friendly_name = self._get_friendly_name(entity_id)

            # Offset field
            schema_dict[
                vol.Required(f"{friendly_name} Offset", default=DEFAULT_OFFSET)
            ] = NumberSelector(
                NumberSelectorConfig(
                    min=-100,
                    max=100,
                    step=1,
                    mode=NumberSelectorMode.BOX,
                    unit_of_measurement="%",
                )
            )

            # Min brightness field
            schema_dict[
                vol.Required(f"{friendly_name} Min", default=DEFAULT_MIN_BRIGHTNESS)
            ] = NumberSelector(
                NumberSelectorConfig(
                    min=1,
                    max=100,
                    step=1,
                    mode=NumberSelectorMode.BOX,
                    unit_of_measurement="%",
                )
            )

            # Max brightness field
            schema_dict[
                vol.Required(f"{friendly_name} Max", default=DEFAULT_MAX_BRIGHTNESS)
            ] = NumberSelector(
                NumberSelectorConfig(
                    min=1,
                    max=100,
                    step=1,
                    mode=NumberSelectorMode.BOX,
                    unit_of_measurement="%",
                )
            )

        new_light_names = [self._get_friendly_name(e) for e in self._added_lights]
        return self.async_show_form(
            step_id="new_light_offsets",
            data_schema=vol.Schema(schema_dict),
            errors=errors,
            description_placeholders={
                "new_lights": ", ".join(new_light_names),
            },
        )

    async def _async_save_light_changes(
        self, new_entity_configs: dict[str, dict[str, Any]] | None = None
    ) -> FlowResult:
        """Save the updated light configuration.

        Args:
            new_entity_configs: Dict of entity_id -> config for new lights
        """
        new_entity_configs = new_entity_configs or {}

        # Get existing light configs (to preserve settings for kept lights)
        existing_configs = {
            light[CONF_ENTITY_ID]: light
            for light in self._config_entry.data.get(CONF_LIGHTS, [])
        }

        # Build new lights config
        lights_config = []
        for entity_id in self._selected_lights:
            if entity_id in existing_configs:
                # Keep existing config for lights that weren't removed
                lights_config.append(existing_configs[entity_id])
            else:
                # New light - get config from the mapping
                cfg = new_entity_configs.get(entity_id, {})
                min_br = cfg.get(CONF_MIN_BRIGHTNESS, DEFAULT_MIN_BRIGHTNESS)
                max_br = cfg.get(CONF_MAX_BRIGHTNESS, DEFAULT_MAX_BRIGHTNESS)
                lights_config.append(
                    {
                        CONF_ENTITY_ID: entity_id,
                        CONF_OFFSET: cfg.get(CONF_OFFSET, DEFAULT_OFFSET),
                        CONF_MIN_BRIGHTNESS: min_br,
                        CONF_MAX_BRIGHTNESS: max_br,
                    }
                )

        # Update the config entry
        new_data = {
            **self._config_entry.data,
            CONF_LIGHTS: lights_config,
        }

        self.hass.config_entries.async_update_entry(
            self._config_entry,
            data=new_data,
        )

        return self.async_create_entry(title="", data={})

    async def async_step_adjust_offsets(
        self, user_input: dict[str, Any] | None = None
    ) -> FlowResult:
        """Adjust offsets for existing lights."""
        errors: dict[str, str] = {}

        if user_input is not None:
            # Rebuild lights config with new offsets and min/max
            lights_config = []
            for light in self._config_entry.data.get(CONF_LIGHTS, []):
                entity_id = light[CONF_ENTITY_ID]
                friendly_name = self._get_friendly_name(entity_id)

                # Build keys for form fields
                offset_key = f"{friendly_name} Offset"
                min_key = f"{friendly_name} Min"
                max_key = f"{friendly_name} Max"

                # Get values with fallback to existing config
                default_offset = light.get(CONF_OFFSET, DEFAULT_OFFSET)
                default_min = light.get(CONF_MIN_BRIGHTNESS, DEFAULT_MIN_BRIGHTNESS)
                default_max = light.get(CONF_MAX_BRIGHTNESS, DEFAULT_MAX_BRIGHTNESS)

                offset = user_input.get(offset_key, default_offset)
                min_bright = user_input.get(min_key, default_min)
                max_bright = user_input.get(max_key, default_max)

                lights_config.append(
                    {
                        CONF_ENTITY_ID: entity_id,
                        CONF_OFFSET: offset,
                        CONF_MIN_BRIGHTNESS: min_bright,
                        CONF_MAX_BRIGHTNESS: max_bright,
                    }
                )

            # Update the config entry data
            offset_type = user_input.get(CONF_OFFSET_TYPE, DEFAULT_OFFSET_TYPE)
            new_data = {
                **self._config_entry.data,
                CONF_LIGHTS: lights_config,
                CONF_OFFSET_TYPE: offset_type,
            }

            self.hass.config_entries.async_update_entry(
                self._config_entry,
                data=new_data,
            )

            return self.async_create_entry(title="", data={})

        # Build schema with current values
        current_offset_type = self._config_entry.data.get(
            CONF_OFFSET_TYPE, DEFAULT_OFFSET_TYPE
        )

        offset_type_options = [
            {"value": OFFSET_TYPE_ABSOLUTE, "label": "Absolute (percentage points)"},
            {"value": OFFSET_TYPE_RELATIVE, "label": "Relative (multiplier)"},
        ]
        schema_dict = {
            vol.Required(CONF_OFFSET_TYPE, default=current_offset_type): SelectSelector(
                SelectSelectorConfig(
                    options=offset_type_options,
                    mode=SelectSelectorMode.DROPDOWN,
                )
            ),
        }

        # Add offset, min, max fields for each light with current values
        for light in self._config_entry.data.get(CONF_LIGHTS, []):
            entity_id = light[CONF_ENTITY_ID]
            current_offset = light.get(CONF_OFFSET, DEFAULT_OFFSET)
            current_min = light.get(CONF_MIN_BRIGHTNESS, DEFAULT_MIN_BRIGHTNESS)
            current_max = light.get(CONF_MAX_BRIGHTNESS, DEFAULT_MAX_BRIGHTNESS)

            friendly_name = self._get_friendly_name(entity_id)

            # Offset field
            schema_dict[
                vol.Required(f"{friendly_name} Offset", default=current_offset)
            ] = NumberSelector(
                NumberSelectorConfig(
                    min=-100,
                    max=100,
                    step=1,
                    mode=NumberSelectorMode.BOX,
                    unit_of_measurement="%",
                )
            )

            # Min brightness field
            schema_dict[vol.Required(f"{friendly_name} Min", default=current_min)] = (
                NumberSelector(
                    NumberSelectorConfig(
                        min=1,
                        max=100,
                        step=1,
                        mode=NumberSelectorMode.BOX,
                        unit_of_measurement="%",
                    )
                )
            )

            # Max brightness field
            schema_dict[vol.Required(f"{friendly_name} Max", default=current_max)] = (
                NumberSelector(
                    NumberSelectorConfig(
                        min=1,
                        max=100,
                        step=1,
                        mode=NumberSelectorMode.BOX,
                        unit_of_measurement="%",
                    )
                )
            )

        return self.async_show_form(
            step_id="adjust_offsets",
            data_schema=vol.Schema(schema_dict),
            errors=errors,
        )

    async def async_step_edit_yaml(
        self, user_input: dict[str, Any] | None = None
    ) -> FlowResult:
        """Edit the configuration as YAML."""
        errors: dict[str, str] = {}
        error_detail = ""

        # Get current config as YAML
        current_yaml = config_to_yaml(self._config_entry.data)

        if user_input is not None:
            yaml_input = user_input.get("yaml_config", "")

            config, error = yaml_to_config(yaml_input)

            if error:
                errors["yaml_config"] = "invalid_yaml"
                error_detail = f"**Error:** {error}"
            else:
                # Validate name isn't taken by another entry
                existing_names = {
                    entry.data.get(CONF_NAME, "").lower(): entry.entry_id
                    for entry in self.hass.config_entries.async_entries(DOMAIN)
                }
                new_name_lower = config[CONF_NAME].lower()

                # Allow keeping same name, but not taking another entry's name
                if (
                    new_name_lower in existing_names
                    and existing_names[new_name_lower] != self._config_entry.entry_id
                ):
                    errors["yaml_config"] = "name_exists"
                    group_name = config[CONF_NAME]
                    error_detail = f"**Error:** Group '{group_name}' already exists"
                else:
                    # Update the config entry
                    self.hass.config_entries.async_update_entry(
                        self._config_entry,
                        title=config[CONF_NAME],
                        data=config,
                    )
                    return self.async_create_entry(title="", data={})

            # Show form again with the user's input preserved
            return self.async_show_form(
                step_id="edit_yaml",
                data_schema=vol.Schema(
                    {
                        vol.Required("yaml_config", default=yaml_input): TextSelector(
                            TextSelectorConfig(
                                type=TextSelectorType.TEXT,
                                multiline=True,
                            )
                        ),
                    }
                ),
                errors=errors,
                description_placeholders={
                    "name": self._config_entry.title,
                    "error_detail": error_detail,
                },
            )

        return self.async_show_form(
            step_id="edit_yaml",
            data_schema=vol.Schema(
                {
                    vol.Required("yaml_config", default=current_yaml): TextSelector(
                        TextSelectorConfig(
                            type=TextSelectorType.TEXT,
                            multiline=True,
                        )
                    ),
                }
            ),
            errors=errors,
            description_placeholders={
                "name": self._config_entry.title,
                "error_detail": "",
            },
        )
