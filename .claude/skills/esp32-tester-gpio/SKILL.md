---
name: esp32-tester-gpio
description: GPIO pin control on the Raspberry Pi tester for driving ESP32 boot modes and buttons. Triggers on "GPIO", "pin", "boot mode", "button", "hardware reset".
---

# ESP32 GPIO Control

Base URL: `http://192.168.0.87:8080`

## Endpoints

| Method | Path | Purpose |
|--------|------|---------|
| POST | `/api/gpio/set` | Drive a pin: 0 (low), 1 (high), or "z" (hi-Z/release) |
| GET | `/api/gpio/status` | Read state of all driven pins |

## Allowed BCM Pins

`5, 6, 12, 13, 16, 17, 18, 19, 20, 21, 22, 23, 24, 25, 26, 27`

## Examples

```bash
# Drive GPIO18 LOW (e.g., hold BOOT button)
curl -X POST http://192.168.0.87:8080/api/gpio/set \
  -H 'Content-Type: application/json' \
  -d '{"pin": 18, "value": 0}'

# Drive GPIO18 HIGH
curl -X POST http://192.168.0.87:8080/api/gpio/set \
  -H 'Content-Type: application/json' \
  -d '{"pin": 18, "value": 1}'

# Release GPIO18 (hi-Z)
curl -X POST http://192.168.0.87:8080/api/gpio/set \
  -H 'Content-Type: application/json' \
  -d '{"pin": 18, "value": "z"}'

# Read all driven pin states
curl http://192.168.0.87:8080/api/gpio/status
```

## CRITICAL: Always Use HIGH (1) to Release Pins

**Never use hi-Z (`"z"`) to release EN or BOOT pins.** Hi-Z leaves the pin
floating, which can cause the Pi to crash or hang (the Pi Zero W's dwc_otg USB
controller is sensitive to floating GPIO lines connected to ESP32 EN/BOOT).

- **Release = drive HIGH (`1`)**, not hi-Z
- Only use `"z"` after the full sequence is complete and you want to fully disconnect

## Common Workflows

1. **Enter ESP32 download mode** (hold BOOT during reset):
   ```bash
   # 1. Hold BOOT (GPIO18) LOW
   curl -X POST http://192.168.0.87:8080/api/gpio/set \
     -H 'Content-Type: application/json' -d '{"pin": 18, "value": 0}'
   sleep 1
   # 2. Pull EN (GPIO17) LOW — assert reset
   curl -X POST http://192.168.0.87:8080/api/gpio/set \
     -H 'Content-Type: application/json' -d '{"pin": 17, "value": 0}'
   sleep 0.2
   # 3. Release EN HIGH — ESP32 exits reset, samples BOOT=LOW → download mode
   curl -X POST http://192.168.0.87:8080/api/gpio/set \
     -H 'Content-Type: application/json' -d '{"pin": 17, "value": 1}'
   sleep 0.5
   # 4. Release BOOT HIGH
   curl -X POST http://192.168.0.87:8080/api/gpio/set \
     -H 'Content-Type: application/json' -d '{"pin": 18, "value": 1}'
   # 5. (Optional) Release to hi-Z after sequence is stable
   curl -X POST http://192.168.0.87:8080/api/gpio/set \
     -H 'Content-Type: application/json' -d '{"pin": 17, "value": "z"}'
   curl -X POST http://192.168.0.87:8080/api/gpio/set \
     -H 'Content-Type: application/json' -d '{"pin": 18, "value": "z"}'
   ```

2. **Normal reset** (without entering download mode):
   ```bash
   # Pull EN LOW, wait, release HIGH
   curl -X POST http://192.168.0.87:8080/api/gpio/set \
     -H 'Content-Type: application/json' -d '{"pin": 17, "value": 0}'
   sleep 0.2
   curl -X POST http://192.168.0.87:8080/api/gpio/set \
     -H 'Content-Type: application/json' -d '{"pin": 17, "value": 1}'
   ```

3. **Simulate button press:**
   - Set pin LOW, wait, set pin HIGH (`1`) to release

## Note: Dual-USB Hub Boards

Some ESP32-S3 dev boards have an onboard USB hub with a built-in auto-download circuit that connects GPIO0/EN to DTR/RTS on the USB-Serial/JTAG interface. For these boards, **external Pi GPIO wiring for reset and boot mode is not needed** — DTR/RTS on the JTAG slot handles it via `POST /api/serial/reset` on the JTAG slot. See esp32-tester-serial for identifying dual-USB boards.

## GPIO Control Probe — Auto-Detecting Board Capabilities

Not all boards have EN/BOOT pins wired to Pi GPIOs. Run this probe once per board to determine if GPIO control is available.

### Probe Procedure

```bash
# Step 1: Try GPIO-based download mode entry
# 1a. Hold BOOT low
curl -X POST http://192.168.0.87:8080/api/gpio/set \
  -H 'Content-Type: application/json' -d '{"pin": 18, "value": 0}'
sleep 1
# 1b. Pull EN low (assert reset)
curl -X POST http://192.168.0.87:8080/api/gpio/set \
  -H 'Content-Type: application/json' -d '{"pin": 17, "value": 0}'
sleep 0.2
# 1c. Release EN HIGH (not hi-Z!) — ESP exits reset, samples BOOT
curl -X POST http://192.168.0.87:8080/api/gpio/set \
  -H 'Content-Type: application/json' -d '{"pin": 17, "value": 1}'
sleep 0.5
# 1d. Release BOOT HIGH
curl -X POST http://192.168.0.87:8080/api/gpio/set \
  -H 'Content-Type: application/json' -d '{"pin": 18, "value": 1}'
# 1e. Release to hi-Z (safe now that sequence is complete)
curl -X POST http://192.168.0.87:8080/api/gpio/set \
  -H 'Content-Type: application/json' -d '{"pin": 17, "value": "z"}'
curl -X POST http://192.168.0.87:8080/api/gpio/set \
  -H 'Content-Type: application/json' -d '{"pin": 18, "value": "z"}'

# 1f. Monitor for boot output (USB disconnect/reconnect = GPIO works)
curl -X POST http://192.168.0.87:8080/api/serial/monitor \
  -H 'Content-Type: application/json' \
  -d '{"slot": "<slot>", "pattern": "boot:", "timeout": 3}'

# Step 2: If GPIO had no effect, try USB DTR/RTS reset
curl -X POST http://192.168.0.87:8080/api/serial/reset \
  -H 'Content-Type: application/json' -d '{"slot": "<slot>"}'
```

**IMPORTANT:** Always release EN and BOOT by driving HIGH (`1`) first, then
optionally to hi-Z (`"z"`). Releasing directly to hi-Z leaves pins floating
and can crash the Pi (dwc_otg USB controller sensitivity).

### Interpreting Results

| GPIO probe output | USB reset output | Board type |
|-------------------|-----------------|------------|
| `boot:0x23` (DOWNLOAD) | — | **GPIO-controlled** — Pi GPIOs wired to EN/BOOT |
| No output / normal boot | Hardware reset output (`rst:0x15`) | **USB-controlled** — no GPIO wiring, use DTR/RTS |
| No output | No output | No control — check wiring or wrong slot |

### Caveats
- **Firmware crash loops** (`rst:0xc`) mask GPIO resets — continuous panic reboots make it impossible to distinguish a GPIO-triggered reset from a crash-triggered one. For reliable probing, first break the crash loop with `esptool.py --before=usb_reset erase_flash` (works even during crash loops on native USB devices — see esp32-tester-serial), then re-run the probe on the clean device.
- **Dual-USB hub boards** always respond to USB DTR/RTS on the JTAG slot; GPIO probe will show no effect.
- Probe only needs to run once per physical board.

## Troubleshooting

| Problem | Fix |
|---------|-----|
| "pin not in allowed set" | Use only the BCM pins listed above |
| "value must be 0, 1, or 'z'" | Pin must be integer; value must be `0`, `1`, or `"z"` |
| Pin stays driven after test | Release pins with HIGH (`1`) first, then `"z"` when stable |
| **Pi crashes during GPIO reset** | **Never release EN/BOOT directly to hi-Z.** Always drive HIGH first, then optionally hi-Z. Floating pins crash the Pi's dwc_otg USB controller. |
| GPIO reset not needed | Board may have onboard auto-download circuit (dual-USB hub board) — use DTR/RTS via JTAG slot instead |
| Probe shows crash loop output | Board is rebooting from firmware panic, not from GPIO. Erase flash first for clean probe. |
