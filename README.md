# DeltaLux

A Home Assistant integration for light groups with brightness offsets.

## Why?

You have multiple lights in a room and want them to dim together while maintaining their relative brightness. Your accent lights should stay 25% dimmer than the main lights.

DeltaLux lets you set brightness offsets on mutliple lights. When you dim the group the relationships persist automatically.

## Features

- Persistent brightness offsets between lights
- Per-light min/max brightness constraints
- Absolute or relative offset modes
- Full color and color temperature support
- Config through the UI or YAML

## Installation

1. Copy the `deltalux` folder to `config/custom_components/`
2. Restart Home Assistant
3. Go to Settings → Devices & Services → Add Integration
4. Search for "DeltaLux"

## Setup

### GUI

1. Choose "Setup with GUI"
2. Name your group and select lights (need at least 2)
3. Set offsets for each light (-100 to +100)
4. Set min/max brightness if needed (prevents flickering or too-bright lights)
5. Choose offset type: absolute or relative

### YAML

Choose "Import from YAML" and paste your config:

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

To edit later, go to Settings → Devices & Services → DeltaLux → Configure.

## Offset Modes

**Absolute** (default): Offset in percentage points

- Master at 50%, offset -25 → light at 25%
- Master at 100%, offset -25 → light at 75%

**Relative**: Offset as multiplier

- Master at 100%, offset -25 (0.75x) → light at 75%
- Master at 80%, offset -25 (0.75x) → light at 60%

## Min/Max

Set min/max to prevent lights from going too dim or too bright:

- Min at 5% prevents LED strips from flickering
- Max at 70% keeps accent lights from overpowering the room

## License

MIT

## Contributing

Issues and PRs welcome.
