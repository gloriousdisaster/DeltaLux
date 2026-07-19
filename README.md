# DeltaLux

A Home Assistant integration for light groups with brightness offsets.

## Why?

You have multiple lights in a room and want them to dim together while maintaining their relative brightness. Your accent lights should stay 25% dimmer than the main lights.

DeltaLux lets you set a brightness offset for each light in a group. When you dim the group, the relationships persist automatically.

**Requires Home Assistant 2024.4 or newer.**

## Features

- Persistent brightness offsets between lights
- Per-light minimum and maximum brightness constraints
- Absolute or relative offset modes
- Full color support: color temperature (Kelvin), HS/RGB/RGBW/RGBWW/XY, and white mode
- Effects, flash, and transitions forwarded to member lights
- Supported color modes and effects aggregated from the members — mixed groups (e.g. a dimmer plus color bulbs) work correctly
- Master brightness survives restarts and off/on cycles
- Set up through the UI or YAML import, fully editable afterwards

## Installation

1. In your Home Assistant config directory, create the folder `custom_components/deltalux/`
2. Copy the contents of this repository into that folder
3. Restart Home Assistant
4. Go to Settings → Devices & Services → Add Integration
5. Search for "DeltaLux"

## Setup

### GUI

1. Choose **Setup with GUI**
2. Name your group and select the lights to include (at least 2)
3. Choose the offset type — absolute or relative
4. Set each light's offset (-100 to +100) and, if needed, its min/max brightness (1–100%)

### YAML

Choose **Import from YAML** and paste your config:

```yaml
name: Living Room
offset_type: absolute
lights:
  - entity_id: light.ceiling
    offset: 0
    min_brightness: 1
    max_brightness: 100
  - entity_id: light.floor_lamp
    offset: -20
    min_brightness: 5
    max_brightness: 100
  - entity_id: light.accent
    offset: -40
    min_brightness: 2
    max_brightness: 80
```

`offset` is required per light; `min_brightness` and `max_brightness` are optional (defaults 1 and 100).

Group names must be unique, and a DeltaLux group cannot contain another DeltaLux group.

### Editing a group

Go to Settings → Devices & Services → DeltaLux → **Configure**. Three options:

- **Add or remove lights** — change group membership; newly added lights get their own offset settings
- **Adjust brightness settings** — change the offset type and each light's offset and min/max
- **View/Edit as YAML** — edit the full configuration as YAML

## Offset Modes

**Absolute** (default): Offset in percentage points

- Master at 50%, offset -25 → light at 25%
- Master at 100%, offset -25 → light at 75%

**Relative**: Offset as a multiplier

- Master at 100%, offset -25 (0.75x) → light at 75%
- Master at 80%, offset -25 (0.75x) → light at 60%

Positive offsets make a light brighter than the master. In both modes the result is clamped to the light's min/max brightness.

## Min/Max

Set min/max to keep lights inside their useful range:

- Min at 5% prevents LED strips from flickering
- Max at 70% keeps accent lights from overpowering the room

## Behavior Notes

- The group is **on** if any member is on, and **unavailable** only if no members are available.
- Changing color or effect on an already-lit group does **not** touch member brightness — only an explicit brightness change (or turning the group on) recalculates offset levels.
- A member that is off when the group is turned on comes back at its offset level.
- Turning the group off keeps the master brightness, so the next turn-on restores every light to its previous level.
- Color state shown on the group mirrors a color-capable member, so a brightness-only bulb can't blank out the group's color attributes.
- The group entity exposes `master_brightness` and per-light `offsets` as state attributes for use in automations.

## License

MIT
