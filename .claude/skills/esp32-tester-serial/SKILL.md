---
name: esp32-tester-serial
description: Serial device discovery, reset, monitor, and flashing for the Universal ESP32 Tester. Triggers on "serial", "reset", "monitor", "device", "slot", "NVS", "erase", "flash", "esptool".
---

# ESP32 Serial & Device Discovery

Base URL: `http://192.168.0.87:8080`

## When to Use Serial (vs OTA / UDP logs)

### Serial Flashing (esptool) — use when:
- Device has **no firmware** (blank/bricked/first flash)
- Firmware **lacks OTA support**
- You need to **erase NVS** or flash a **bootloader/partition table**
- Device has **no WiFi connectivity**
- **Prerequisite:** slot state must be `idle` (device present, USB connected)
- **Blocks:** stops the RFC2217 proxy during flash; no serial monitor while flashing
- **Alternative:** if device already runs OTA-capable firmware and is on WiFi, use OTA instead (see esp32-tester-ota) — it's faster and doesn't block serial

### Serial Monitor — use when:
- You need **boot messages** (before WiFi is up)
- You need to **wait for a specific log line** (pattern matching with timeout)
- Device has **no WiFi** or UDP logging is not compiled in
- You want **crash/panic output** from the UART
- **Prerequisite:** slot must be `idle` and proxy must be `running`
- **Blocks:** sets slot state to `monitoring` — only one monitor session per slot at a time
- **Alternative:** if device is on WiFi and sends UDP logs, use esp32-tester-udplog instead — it's non-blocking, supports multiple devices, and doesn't tie up the serial port

## Endpoints

| Method | Path | Purpose |
|--------|------|---------|
| GET | `/api/devices` | List all slots with state, device node, RFC2217 URL |
| GET | `/api/info` | System info (host IP, hostname, slot counts) |
| POST | `/api/serial/reset` | Hardware reset via DTR/RTS pulse, returns boot output |
| POST | `/api/serial/monitor` | Read serial output with optional pattern matching |

## Step 1: Discover Devices

Always start here. Get slot labels, states, and RFC2217 URLs:

```bash
curl -s http://192.168.0.87:8080/api/devices | jq .
```

Response fields per slot: `label`, `state`, `url` (RFC2217), `present`, `running`.

## Serial Reset

Sends DTR/RTS pulse, captures boot output (up to 5s), restarts proxy automatically.

```bash
curl -X POST http://192.168.0.87:8080/api/serial/reset \
  -H 'Content-Type: application/json' \
  -d '{"slot": "slot-1"}'
```

Response: `{"ok": true, "output": ["line1", "line2", ...]}`

## Serial Monitor

Reads serial output via RFC2217 proxy (non-exclusive read). Optionally waits for a regex pattern.

```bash
# Wait up to 10s for a pattern match
curl -X POST http://192.168.0.87:8080/api/serial/monitor \
  -H 'Content-Type: application/json' \
  -d '{"slot": "slot-1", "pattern": "WiFi connected", "timeout": 10}'

# Just capture output for 5s (no pattern)
curl -X POST http://192.168.0.87:8080/api/serial/monitor \
  -H 'Content-Type: application/json' \
  -d '{"slot": "slot-1", "timeout": 5}'
```

Response: `{"ok": true, "matched": true, "line": "WiFi connected to MyAP", "output": [...]}`

## Serial Flashing (esptool over RFC2217)

Each slot exposes an RFC2217 URL from `/api/devices`. Use it with esptool directly:

```bash
# 1. Get the RFC2217 URL
SLOT_URL=$(curl -s http://192.168.0.87:8080/api/devices | jq -r '.slots[0].url')

# 2. Flash firmware
esptool.py --port "$SLOT_URL" --chip esp32c3 write_flash 0x0 firmware.bin

# 3. Erase NVS partition
esptool.py --port "$SLOT_URL" --chip esp32c3 erase_region 0x9000 0x6000
```

## Slot States

| State | Meaning | Can flash? | Can monitor? |
|-------|---------|------------|--------------|
| `absent` | No USB device | No | No |
| `idle` | Ready | Yes | Yes |
| `resetting` | Reset in progress | No | No |
| `monitoring` | Monitor active | No | No (wait for current to finish) |
| `flapping` | USB storm | No | No (wait 30s) |

## Common Workflows

1. **Flash a blank device:** `GET /api/devices` to find slot URL, then `esptool.py --port <url> write_flash ...`
2. **Reset and read boot log:** `POST /api/serial/reset` — returns boot output lines
3. **Wait for a specific message after reset:** reset first, then `POST /api/serial/monitor` with `pattern`
4. **Flash then verify boot:** flash via esptool, then `POST /api/serial/reset`, check output for expected boot messages

## Troubleshooting

| Problem | Fix |
|---------|-----|
| Slot shows `absent` | Check USB cable, re-seat device |
| "proxy not running" | Device may be flapping — check `state` field |
| Monitor timeout, no output | Baud rate is fixed at 115200; ensure device matches |
| `flapping` state | USB connection cycling — wait 30s for cooldown |
| esptool can't connect | Ensure slot is `idle`; may need to enter download mode via GPIO (see esp32-tester-gpio) |
