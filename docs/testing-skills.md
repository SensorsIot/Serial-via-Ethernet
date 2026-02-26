# Testing Workbench Skills

The `test-firmware/` directory contains a generic ESP-IDF firmware that exercises
all workbench infrastructure without any project-specific logic. Use it to
validate that workbench skills work correctly after making changes to the
workbench software or skills.

## Building

Requires ESP-IDF v5.x (tested with 5.1+).

```bash
cd test-firmware
idf.py set-target esp32s3    # or esp32, esp32c3
idf.py build
```

The binary lands at `build/wb-test-firmware.bin`.

## Flashing

Upload to the workbench and flash via RFC2217:

```bash
# Upload binary for OTA (optional, needed for OTA test)
curl -F "file=@build/wb-test-firmware.bin" \
     "http://192.168.0.87:8080/api/firmware/upload?project=test-firmware&filename=wb-test-firmware.bin"

# Flash via serial
esptool.py --port rfc2217://192.168.0.87:4001?ign_set_control \
           --chip esp32s3 --baud 460800 \
           write_flash @flash_args
```

Or use the `esp32-workbench-serial-flashing` skill.

## What the Firmware Does

| Module | What it exercises |
|--------|-------------------|
| `udp_log.c` | UDP log forwarding to `192.168.0.87:5555` |
| `wifi_prov.c` | SoftAP captive portal (`WB-Test-Setup`), STA mode with stored creds |
| `ble_nus.c` | BLE advertisement as `WB-Test`, NUS service |
| `ota_update.c` | HTTP OTA from workbench firmware server |
| `http_server.c` | `/status`, `/ota`, `/wifi-reset` endpoints |
| `nvs_store.c` | WiFi credential persistence in NVS (`wb_test` namespace) |
| Heartbeat task | Periodic log line confirming firmware is alive |

## Skill Validation Matrix

Each workbench skill maps to specific test steps using the firmware:

| Skill | Test steps | What confirms it works |
|-------|-----------|----------------------|
| `esp32-workbench-serial-flashing` | Flash the firmware via RFC2217 | Serial monitor shows `"=== Workbench Test Firmware"` after reboot |
| `esp32-workbench-logging` | Start serial monitor; check UDP logs | Serial shows boot output; `GET /api/udplog` returns heartbeat lines |
| `esp32-workbench-wifi` | Run `enter-portal` with device in AP mode | Serial shows `"STA got IP"`, device joins workbench network |
| `esp32-workbench-ble` | Scan for `WB-Test`, connect, discover services | BLE scan finds device; NUS service UUID appears in characteristics |
| `esp32-workbench-ota` | Upload binary, trigger OTA via HTTP `/ota` | Serial shows `"OTA succeeded"`, device reboots with new firmware |
| `esp32-workbench-gpio` | Toggle EN pin to reset device | Serial monitor shows fresh boot output |
| `esp32-workbench-mqtt` | Start broker, verify device can reach `192.168.4.1:1883` | (Firmware doesn't use MQTT; test broker start/stop independently) |
| `esp32-workbench-test` | Run full validation walkthrough below | All steps pass |

## Validation Walkthrough

Run through these steps in order after flashing. Each step builds on the
previous one.

### 1. Serial flashing and boot

1. Flash `wb-test-firmware.bin` via the serial flashing skill
2. Start serial monitor
3. Confirm output contains:
   - `"=== Workbench Test Firmware v0.1.0 ==="`
   - `"NVS initialized"`
   - `"UDP logging -> 192.168.0.87:5555"`
   - `"No WiFi credentials, starting AP provisioning"`
   - `"AP mode: SSID='WB-Test-Setup'"`
   - `"BLE NUS initialized"`
   - `"Init complete, running event-driven"`

### 2. WiFi provisioning

1. Confirm device is in AP mode (serial shows `"AP mode"`)
2. Run `enter-portal` with:
   - `portal_ssid`: `WB-Test-Setup`
   - `ssid`: workbench AP SSID
   - `password`: workbench AP password
3. Confirm serial shows:
   - `"Credentials saved, rebooting"`
   - `"STA mode, connecting to '<ssid>'"`
   - `"STA got IP"`

### 3. UDP logging

1. After WiFi is connected, check UDP logs:
   ```bash
   curl -s http://192.168.0.87:8080/api/udplog | head -20
   ```
2. Confirm heartbeat lines appear: `"heartbeat N | wifi=1 ble=0"`

### 4. HTTP endpoints

1. Get device IP from serial output or workbench scan
2. Via HTTP relay:
   ```bash
   curl -s -X POST http://192.168.0.87:8080/api/wifi/http \
        -H "Content-Type: application/json" \
        -d '{"method":"GET","url":"http://<device-ip>/status"}'
   ```
3. Confirm JSON response contains `project`, `version`, `wifi_connected: true`

### 5. BLE

1. Scan for BLE devices:
   ```bash
   curl -s -X POST http://192.168.0.87:8080/api/ble/scan \
        -H "Content-Type: application/json" \
        -d '{"duration": 5}'
   ```
2. Confirm `WB-Test` appears in scan results
3. Connect and discover services — NUS UUID `6e400001-b5a3-f393-e0a9-e50e24dcca9e` should be present

### 6. OTA update

1. Ensure firmware binary is uploaded to workbench (see Flashing section)
2. Trigger OTA via HTTP:
   ```bash
   curl -s -X POST http://192.168.0.87:8080/api/wifi/http \
        -H "Content-Type: application/json" \
        -d '{"method":"POST","url":"http://<device-ip>/ota"}'
   ```
3. Monitor serial for `"OTA succeeded, rebooting..."`
4. Confirm device reboots and shows boot banner again

### 7. WiFi reset

1. Via HTTP:
   ```bash
   curl -s -X POST http://192.168.0.87:8080/api/wifi/http \
        -H "Content-Type: application/json" \
        -d '{"method":"POST","url":"http://<device-ip>/wifi-reset"}'
   ```
2. Confirm serial shows `"WiFi credentials erased"` then reboot into AP mode

### 8. GPIO reset

1. Toggle EN pin LOW then HIGH via GPIO skill
2. Confirm serial shows fresh boot output

## Adding Test Coverage

When modifying a workbench skill:

1. Add a row to the **Skill Validation Matrix** if the skill isn't already covered
2. Add a step to the **Validation Walkthrough** if it requires a new test sequence
3. Flash the test firmware and run through the affected steps to confirm the
   skill still works
