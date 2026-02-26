---
name: idf-flash
description: Use when the user asks to "flash", "upload", "deploy", or "program" firmware to an ESP32 using ESP-IDF (not PlatformIO). Also use for "monitor" or "serial console" with ESP-IDF projects.
---

# ESP-IDF Flash

Flash firmware to ESP32 using ESP-IDF tools.

## Local Flash (USB)

```bash
source /opt/esp-idf/export.sh
idf.py -p /dev/ttyUSB0 flash           # Flash to specific port
idf.py -p /dev/ttyUSB0 monitor         # Open serial monitor
idf.py -p /dev/ttyUSB0 flash monitor   # Flash and monitor
```

## Remote Flash (RFC2217)

For flashing via RFC2217 serial over network, use the `esp32-workbench-serial-flashing` skill which has detailed RFC2217 instructions, device discovery, and troubleshooting.

Quick reference (check http://192.168.0.87:8080 for current slot-to-port assignments):
```bash
export ESPPORT='rfc2217://192.168.0.87:4001?ign_set_control'
source /opt/esp-idf/export.sh
idf.py flash monitor
```

## Build Commands

```bash
source /opt/esp-idf/export.sh
idf.py build                           # Build only
idf.py flash                           # Build (if needed) and flash
idf.py fullclean                       # Clean build directory
```

## Boot Mode

To put ESP32 in bootloader mode:
1. Hold **BOOT** button
2. Press **RESET** button
3. Release **RESET**, then **BOOT**

## Monitor Shortcuts

- `Ctrl+]` - Exit monitor
- `Ctrl+T` `Ctrl+H` - Show help
- `Ctrl+T` `Ctrl+R` - Reset target

## Troubleshooting

| Issue | Solution |
|-------|----------|
| Failed to connect | Enter boot mode (BOOT+RESET sequence) |
| No serial port found | Check USB cable, `ls /dev/ttyUSB*` |
| Permission denied | `sudo usermod -aG dialout $USER`, re-login |
