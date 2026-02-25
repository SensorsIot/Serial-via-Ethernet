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

## Common Workflows

1. **Enter ESP32 download mode** (hold BOOT during reset):
   ```bash
   # Hold GPIO18 LOW (connected to ESP32 BOOT/GPIO0)
   curl -X POST http://192.168.0.87:8080/api/gpio/set \
     -H 'Content-Type: application/json' -d '{"pin": 18, "value": 0}'
   # Reset the device
   curl -X POST http://192.168.0.87:8080/api/serial/reset \
     -H 'Content-Type: application/json' -d '{"slot": "slot-1"}'
   # Release BOOT pin
   curl -X POST http://192.168.0.87:8080/api/gpio/set \
     -H 'Content-Type: application/json' -d '{"pin": 18, "value": "z"}'
   ```

2. **Simulate button press:**
   - Set pin LOW, wait, set pin to `"z"` to release

## Troubleshooting

| Problem | Fix |
|---------|-----|
| "pin not in allowed set" | Use only the BCM pins listed above |
| "value must be 0, 1, or 'z'" | Pin must be integer; value must be `0`, `1`, or `"z"` |
| Pin stays driven after test | Always release pins with `"z"` when done |
