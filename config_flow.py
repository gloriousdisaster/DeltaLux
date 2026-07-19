"""Config flow for DeltaLux integration."""

from __future__ import annotations

import logging
from typing import Any

import voluptuous as vol
import yaml
from homeassistant import config_entries
from homeassistant.components.light import DOMAIN as LIGHT_DOMAIN
from homeassistant.config_entries import ConfigFlowResult
from homeassistant.const import CONF_ENTITY_ID, CONF_NAME
from homeassistant.core import HomeAssistant, callback
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

OFFSET_TYPE_OPTIONS = [
    {"value": OFFSET_TYPE_ABSOLUTE, "label": "Absolute (percentage points)"},
    {"value": OFFSET_TYPE_RELATIVE, "label": "Relative (multiplier)"},
]


def config_to_yaml(config: dict[str, Any]) -> str:
    """Convert a config entry data dict to a YAML string."""
    data = {
        "name": config.get(CONF_NAME, ""),
        "offset_type": config.get(CONF_OFFSET_TYPE, DEFAULT_OFFSET_TYPE),
        "lights": [
            {
                "entity_id": light.get(CONF_ENTITY_ID, ""),
                "offset": light.get(CONF_OFFSET, DEFAULT_OFFSET),
                "min_brightness": light.get(CONF_MIN_BRIGHTNESS, DEFAULT_MIN_BRIGHTNESS),
                "max_brightness": light.get(CONF_MAX_BRIGHTNESS, DEFAULT_MAX_BRIGHTNESS),
            }
            for light in config.get(CONF_LIGHTS, [])
        ],
    }
    return yaml.safe_dump(data, sort_keys=False, default_flow_style=False)


def _validate_light_entry(
    light: Any, index: int
) -> tuple[dict[str, Any] | None, str | None]:
    """Validate a single light entry from YAML. Returns (config, error)."""
    if not isinstance(light, dict):
        return None, f"Light entry {index + 1} must be a dictionary"

    entity_id = light.get("entity_id")
    if entity_id is None:
        return None, f"Light entry {index + 1} missing entity_id"
    if not isinstance(entity_id, str) or not entity_id.startswith("light."):
        return None, f"Invalid entity_id: {entity_id!r} (must start with 'light.')"

    offset = light.get("offset", DEFAULT_OFFSET)
    min_brightness = light.get("min_brightness", DEFAULT_MIN_BRIGHTNESS)
    max_brightness = light.get("max_brightness", DEFAULT_MAX_BRIGHTNESS)

    for field, value, low, high in (
        ("offset", offset, -100, 100),
        ("min_brightness", min_brightness, 1, 100),
        ("max_brightness", max_brightness, 1, 100),
    ):
        if isinstance(value, bool) or not isinstance(value, (int, float)):
            return None, f"{entity_id}: {field} must be a number"
        if not low <= value <= high:
            return None, f"{entity_id}: {field} must be between {low} and {high}"

    if min_brightness > max_brightness:
        return None, f"{entity_id}: min_brightness is greater than max_brightness"

    return {
        CONF_ENTITY_ID: entity_id,
        CONF_OFFSET: offset,
        CONF_MIN_BRIGHTNESS: min_brightness,
        CONF_MAX_BRIGHTNESS: max_brightness,
    }, None


def yaml_to_config(yaml_string: str) -> tuple[dict[str, Any] | None, str | None]:
    """Parse a YAML string to a config dict. Returns (config, error_message)."""
    try:
        parsed = yaml.safe_load(yaml_string)
    except yaml.YAMLError as e:
        return None, f"Invalid YAML syntax: {e}"

    if not isinstance(parsed, dict):
        return None, "YAML must be a dictionary/mapping"

    name = parsed.get("name")
    if not isinstance(name, str) or not name.strip():
        return None, "Missing required field: name"

    offset_type = parsed.get("offset_type", DEFAULT_OFFSET_TYPE)
    if offset_type not in (OFFSET_TYPE_ABSOLUTE, OFFSET_TYPE_RELATIVE):
        return None, (
            f"Invalid offset_type: {offset_type!r} "
            f"(must be '{OFFSET_TYPE_ABSOLUTE}' or '{OFFSET_TYPE_RELATIVE}')"
        )

    if "lights" not in parsed:
        return None, "Missing required field: lights"
    if not isinstance(parsed["lights"], list):
        return None, "lights must be a list"
    if len(parsed["lights"]) < 2:
        return None, "At least 2 lights are required"

    lights_config = []
    seen: set[str] = set()
    for i, light in enumerate(parsed["lights"]):
        light_config, error = _validate_light_entry(light, i)
        if error:
            return None, error
        if light_config[CONF_ENTITY_ID] in seen:
            return None, f"Duplicate light: {light_config[CONF_ENTITY_ID]}"
        seen.add(light_config[CONF_ENTITY_ID])
        lights_config.append(light_config)

    return {
        CONF_NAME: name.strip(),
        CONF_OFFSET_TYPE: offset_type,
        CONF_LIGHTS: lights_config,
    }, None


def get_own_group_entities(hass: HomeAssistant) -> list[str]:
    """Return the entity_ids of all DeltaLux groups (to prevent nesting)."""
    entity_reg = er.async_get(hass)
    return [
        entry.entity_id
        for entry in entity_reg.entities.values()
        if entry.platform == DOMAIN
    ]


def build_field_labels(hass: HomeAssistant, entity_ids: list[str]) -> dict[str, str]:
    """Map entity_id -> unique form-field label.

    Friendly names are used for readability; when two lights share a friendly
    name the entity_id is appended so the form fields can't collide.
    """
    names: dict[str, str] = {}
    for entity_id in entity_ids:
        state = hass.states.get(entity_id)
        names[entity_id] = (
            state.attributes.get("friendly_name") or entity_id if state else entity_id
        )

    counts: dict[str, int] = {}
    for name in names.values():
        counts[name] = counts.get(name, 0) + 1

    return {
        entity_id: name if counts[name] == 1 else f"{name} ({entity_id})"
        for entity_id, name in names.items()
    }


def light_settings_schema(
    labels: dict[str, str], defaults: dict[str, dict[str, Any]]
) -> dict:
    """Build offset/min/max form fields for each light."""
    pct_field = NumberSelector(
        NumberSelectorConfig(
            min=1, max=100, step=1, mode=NumberSelectorMode.BOX, unit_of_measurement="%"
        )
    )
    offset_field = NumberSelector(
        NumberSelectorConfig(
            min=-100,
            max=100,
            step=1,
            mode=NumberSelectorMode.BOX,
            unit_of_measurement="%",
        )
    )

    schema_dict: dict = {}
    for entity_id, label in labels.items():
        current = defaults.get(entity_id, {})
        schema_dict[
            vol.Required(
                f"{label} Offset", default=current.get(CONF_OFFSET, DEFAULT_OFFSET)
            )
        ] = offset_field
        schema_dict[
            vol.Required(
                f"{label} Min",
                default=current.get(CONF_MIN_BRIGHTNESS, DEFAULT_MIN_BRIGHTNESS),
            )
        ] = pct_field
        schema_dict[
            vol.Required(
                f"{label} Max",
                default=current.get(CONF_MAX_BRIGHTNESS, DEFAULT_MAX_BRIGHTNESS),
            )
        ] = pct_field
    return schema_dict


def parse_light_settings(
    user_input: dict[str, Any], label: str, fallback: dict[str, Any]
) -> dict[str, Any]:
    """Read one light's offset/min/max from submitted form values."""
    return {
        CONF_OFFSET: user_input.get(
            f"{label} Offset", fallback.get(CONF_OFFSET, DEFAULT_OFFSET)
        ),
        CONF_MIN_BRIGHTNESS: user_input.get(
            f"{label} Min", fallback.get(CONF_MIN_BRIGHTNESS, DEFAULT_MIN_BRIGHTNESS)
        ),
        CONF_MAX_BRIGHTNESS: user_input.get(
            f"{label} Max", fallback.get(CONF_MAX_BRIGHTNESS, DEFAULT_MAX_BRIGHTNESS)
        ),
    }


def _yaml_schema(default: str) -> vol.Schema:
    """Schema for the YAML editor forms."""
    return vol.Schema(
        {
            vol.Required("yaml_config", default=default): TextSelector(
                TextSelectorConfig(type=TextSelectorType.TEXT, multiline=True)
            ),
        }
    )


class OffsetLightGroupConfigFlow(config_entries.ConfigFlow, domain=DOMAIN):
    """Handle a config flow for Offset Light Group."""

    VERSION = 1

    def __init__(self) -> None:
        """Initialize the config flow."""
        self._data: dict[str, Any] = {}
        self._selected_lights: list[str] = []

    def _existing_names(self) -> list[str]:
        """Lowercased names of already configured groups."""
        return [
            entry.data.get(CONF_NAME, "").lower()
            for entry in self._async_current_entries()
        ]

    async def async_step_user(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Handle the initial step - choose setup mode."""
        if user_input is not None:
            if user_input.get("setup_mode", "gui") == "yaml":
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
    ) -> ConfigFlowResult:
        """Handle YAML import."""
        if user_input is not None:
            yaml_input = user_input.get("yaml_config", "")
            config, error = yaml_to_config(yaml_input)

            if config is not None and error is None:
                own_groups = set(get_own_group_entities(self.hass))
                nested = [
                    light[CONF_ENTITY_ID]
                    for light in config[CONF_LIGHTS]
                    if light[CONF_ENTITY_ID] in own_groups
                ]
                if nested:
                    error = (
                        "A DeltaLux group cannot contain another DeltaLux group: "
                        + ", ".join(nested)
                    )

            if error:
                return self.async_show_form(
                    step_id="yaml",
                    data_schema=_yaml_schema(yaml_input),
                    errors={"yaml_config": "invalid_yaml"},
                    description_placeholders={"error_detail": f"**Error:** {error}"},
                )

            if config[CONF_NAME].lower() in self._existing_names():
                return self.async_show_form(
                    step_id="yaml",
                    data_schema=_yaml_schema(yaml_input),
                    errors={"yaml_config": "name_exists"},
                    description_placeholders={
                        "error_detail": (
                            f"**Error:** A group named '{config[CONF_NAME]}' "
                            "already exists"
                        ),
                    },
                )

            return self.async_create_entry(title=config[CONF_NAME], data=config)

        return self.async_show_form(
            step_id="yaml",
            data_schema=_yaml_schema(""),
            description_placeholders={"error_detail": ""},
        )

    async def async_step_gui(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Handle the GUI setup step - name and light selection."""
        errors: dict[str, str] = {}
        own_groups = get_own_group_entities(self.hass)

        if user_input is not None:
            self._data[CONF_NAME] = user_input[CONF_NAME]
            self._selected_lights = user_input[CONF_ENTITY_ID]

            if len(self._selected_lights) < 2:
                errors["base"] = "need_two_lights"
            elif any(eid in own_groups for eid in self._selected_lights):
                errors["base"] = "group_in_group"
            elif user_input[CONF_NAME].lower() in self._existing_names():
                errors[CONF_NAME] = "name_exists"
            else:
                return await self.async_step_offsets()

        data_schema = vol.Schema(
            {
                vol.Required(CONF_NAME): str,
                vol.Required(CONF_ENTITY_ID): EntitySelector(
                    EntitySelectorConfig(
                        domain=LIGHT_DOMAIN,
                        multiple=True,
                        exclude_entities=own_groups,
                    )
                ),
            }
        )

        return self.async_show_form(
            step_id="gui",
            data_schema=data_schema,
            errors=errors,
            description_placeholders={
                "light_count": str(len(get_light_entities(self.hass))),
            },
        )

    async def async_step_offsets(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Handle offset configuration for each light."""
        errors: dict[str, str] = {}
        labels = build_field_labels(self.hass, self._selected_lights)
        defaults: dict[str, dict[str, Any]] = {}

        if user_input is not None:
            lights_config = []
            for entity_id in self._selected_lights:
                settings = parse_light_settings(user_input, labels[entity_id], {})
                defaults[entity_id] = settings
                if settings[CONF_MIN_BRIGHTNESS] > settings[CONF_MAX_BRIGHTNESS]:
                    errors["base"] = "min_above_max"
                lights_config.append({CONF_ENTITY_ID: entity_id, **settings})

            if not errors:
                self._data[CONF_LIGHTS] = lights_config
                self._data[CONF_OFFSET_TYPE] = user_input.get(
                    CONF_OFFSET_TYPE, DEFAULT_OFFSET_TYPE
                )
                return self.async_create_entry(
                    title=self._data[CONF_NAME], data=self._data
                )

        schema_dict: dict = {
            vol.Required(CONF_OFFSET_TYPE, default=DEFAULT_OFFSET_TYPE): SelectSelector(
                SelectSelectorConfig(
                    options=OFFSET_TYPE_OPTIONS,
                    mode=SelectSelectorMode.DROPDOWN,
                )
            ),
            **light_settings_schema(labels, defaults),
        }

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
        config_entry: config_entries.ConfigEntry,  # noqa: ARG004
    ) -> config_entries.OptionsFlow:
        """Create the options flow."""
        return OffsetLightGroupOptionsFlow()


def get_light_entities(hass: HomeAssistant) -> list[str]:
    """Get list of light entity IDs, excluding offset light groups."""
    own_groups = set(get_own_group_entities(hass))
    return sorted(
        entity_id
        for entity_id in hass.states.async_entity_ids(LIGHT_DOMAIN)
        if entity_id not in own_groups
    )


class OffsetLightGroupOptionsFlow(config_entries.OptionsFlow):
    """Handle options flow for Offset Light Group."""

    def __init__(self) -> None:
        """Initialize options flow."""
        self._selected_lights: list[str] = []
        self._added_lights: list[str] = []

    async def async_step_init(
        self, _user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """First step - choose what to configure."""
        return self.async_show_menu(
            step_id="init",
            menu_options=["manage_lights", "adjust_offsets", "edit_yaml"],
            description_placeholders={
                "name": self.config_entry.title,
            },
        )

    async def async_step_manage_lights(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Manage which lights are in the group."""
        errors: dict[str, str] = {}
        own_groups = get_own_group_entities(self.hass)

        current_lights = [
            light[CONF_ENTITY_ID]
            for light in self.config_entry.data.get(CONF_LIGHTS, [])
        ]

        if user_input is not None:
            new_lights = user_input.get(CONF_ENTITY_ID, [])

            if len(new_lights) < 2:
                errors["base"] = "need_two_lights"
            elif any(eid in own_groups for eid in new_lights):
                errors["base"] = "group_in_group"
            else:
                self._selected_lights = new_lights
                self._added_lights = [
                    eid for eid in new_lights if eid not in current_lights
                ]

                if self._added_lights:
                    return await self.async_step_new_light_offsets()
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
                            exclude_entities=own_groups,
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
    ) -> ConfigFlowResult:
        """Configure offsets for newly added lights."""
        errors: dict[str, str] = {}
        labels = build_field_labels(self.hass, self._added_lights)

        if user_input is not None:
            entity_configs = {}
            for entity_id in self._added_lights:
                settings = parse_light_settings(user_input, labels[entity_id], {})
                if settings[CONF_MIN_BRIGHTNESS] > settings[CONF_MAX_BRIGHTNESS]:
                    errors["base"] = "min_above_max"
                entity_configs[entity_id] = settings

            if not errors:
                return await self._async_save_light_changes(entity_configs)

        return self.async_show_form(
            step_id="new_light_offsets",
            data_schema=vol.Schema(light_settings_schema(labels, {})),
            errors=errors,
            description_placeholders={
                "new_lights": ", ".join(labels.values()),
            },
        )

    async def _async_save_light_changes(
        self, new_entity_configs: dict[str, dict[str, Any]] | None = None
    ) -> ConfigFlowResult:
        """Save the updated light configuration.

        Args:
            new_entity_configs: Dict of entity_id -> config for new lights
        """
        new_entity_configs = new_entity_configs or {}

        existing_configs = {
            light[CONF_ENTITY_ID]: light
            for light in self.config_entry.data.get(CONF_LIGHTS, [])
        }

        lights_config = []
        for entity_id in self._selected_lights:
            if entity_id in existing_configs:
                lights_config.append(existing_configs[entity_id])
            else:
                cfg = new_entity_configs.get(entity_id, {})
                lights_config.append(
                    {
                        CONF_ENTITY_ID: entity_id,
                        CONF_OFFSET: cfg.get(CONF_OFFSET, DEFAULT_OFFSET),
                        CONF_MIN_BRIGHTNESS: cfg.get(
                            CONF_MIN_BRIGHTNESS, DEFAULT_MIN_BRIGHTNESS
                        ),
                        CONF_MAX_BRIGHTNESS: cfg.get(
                            CONF_MAX_BRIGHTNESS, DEFAULT_MAX_BRIGHTNESS
                        ),
                    }
                )

        self.hass.config_entries.async_update_entry(
            self.config_entry,
            data={**self.config_entry.data, CONF_LIGHTS: lights_config},
        )

        return self.async_create_entry(title="", data={})

    async def async_step_adjust_offsets(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Adjust offsets for existing lights."""
        errors: dict[str, str] = {}
        current_lights = self.config_entry.data.get(CONF_LIGHTS, [])
        entity_ids = [light[CONF_ENTITY_ID] for light in current_lights]
        labels = build_field_labels(self.hass, entity_ids)
        defaults = {
            light[CONF_ENTITY_ID]: light for light in current_lights
        }

        if user_input is not None:
            lights_config = []
            for light in current_lights:
                entity_id = light[CONF_ENTITY_ID]
                settings = parse_light_settings(user_input, labels[entity_id], light)
                defaults[entity_id] = settings
                if settings[CONF_MIN_BRIGHTNESS] > settings[CONF_MAX_BRIGHTNESS]:
                    errors["base"] = "min_above_max"
                lights_config.append({CONF_ENTITY_ID: entity_id, **settings})

            if not errors:
                self.hass.config_entries.async_update_entry(
                    self.config_entry,
                    data={
                        **self.config_entry.data,
                        CONF_LIGHTS: lights_config,
                        CONF_OFFSET_TYPE: user_input.get(
                            CONF_OFFSET_TYPE, DEFAULT_OFFSET_TYPE
                        ),
                    },
                )
                return self.async_create_entry(title="", data={})

        current_offset_type = self.config_entry.data.get(
            CONF_OFFSET_TYPE, DEFAULT_OFFSET_TYPE
        )
        schema_dict: dict = {
            vol.Required(CONF_OFFSET_TYPE, default=current_offset_type): SelectSelector(
                SelectSelectorConfig(
                    options=OFFSET_TYPE_OPTIONS,
                    mode=SelectSelectorMode.DROPDOWN,
                )
            ),
            **light_settings_schema(labels, defaults),
        }

        return self.async_show_form(
            step_id="adjust_offsets",
            data_schema=vol.Schema(schema_dict),
            errors=errors,
        )

    async def async_step_edit_yaml(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Edit the configuration as YAML."""
        if user_input is not None:
            yaml_input = user_input.get("yaml_config", "")
            config, error = yaml_to_config(yaml_input)
            errors: dict[str, str] = {}
            error_detail = ""

            if config is not None and error is None:
                own_groups = set(get_own_group_entities(self.hass))
                nested = [
                    light[CONF_ENTITY_ID]
                    for light in config[CONF_LIGHTS]
                    if light[CONF_ENTITY_ID] in own_groups
                ]
                if nested:
                    error = (
                        "A DeltaLux group cannot contain another DeltaLux group: "
                        + ", ".join(nested)
                    )

            if error:
                errors["yaml_config"] = "invalid_yaml"
                error_detail = f"**Error:** {error}"
            else:
                existing_names = {
                    entry.data.get(CONF_NAME, "").lower(): entry.entry_id
                    for entry in self.hass.config_entries.async_entries(DOMAIN)
                }
                new_name_lower = config[CONF_NAME].lower()

                # Allow keeping same name, but not taking another entry's name
                if (
                    new_name_lower in existing_names
                    and existing_names[new_name_lower] != self.config_entry.entry_id
                ):
                    errors["yaml_config"] = "name_exists"
                    error_detail = (
                        f"**Error:** Group '{config[CONF_NAME]}' already exists"
                    )
                else:
                    self.hass.config_entries.async_update_entry(
                        self.config_entry,
                        title=config[CONF_NAME],
                        data=config,
                    )
                    return self.async_create_entry(title="", data={})

            return self.async_show_form(
                step_id="edit_yaml",
                data_schema=_yaml_schema(yaml_input),
                errors=errors,
                description_placeholders={
                    "name": self.config_entry.title,
                    "error_detail": error_detail,
                },
            )

        return self.async_show_form(
            step_id="edit_yaml",
            data_schema=_yaml_schema(config_to_yaml(self.config_entry.data)),
            description_placeholders={
                "name": self.config_entry.title,
                "error_detail": "",
            },
        )
