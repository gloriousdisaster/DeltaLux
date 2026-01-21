"""Constants for the DeltaLux integration."""

DOMAIN = "deltalux"

# Config keys
CONF_GROUP_NAME = "group_name"
CONF_LIGHTS = "lights"
CONF_ENTITY_ID = "entity_id"
CONF_OFFSET = "offset"
CONF_OFFSET_TYPE = "offset_type"
CONF_MIN_BRIGHTNESS = "min_brightness"
CONF_MAX_BRIGHTNESS = "max_brightness"

# Offset types
OFFSET_TYPE_ABSOLUTE = "absolute"  # e.g., -25 means 25% less than master
OFFSET_TYPE_RELATIVE = "relative"  # e.g., 0.75 means 75% of master

# Defaults
DEFAULT_OFFSET = 0
DEFAULT_OFFSET_TYPE = OFFSET_TYPE_ABSOLUTE
DEFAULT_MIN_BRIGHTNESS = 1
DEFAULT_MAX_BRIGHTNESS = 100

# Attributes
ATTR_MASTER_BRIGHTNESS = "master_brightness"
ATTR_OFFSETS = "offsets"
