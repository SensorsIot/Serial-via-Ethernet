# Serial Portal Setup Guide

Complete guide for setting up the Serial Portal on a Raspberry Pi Zero W — sharing USB serial devices over the network via RFC2217 and using the onboard WiFi radio as a test instrument.

---

## Architecture Overview

```
┌──────────────────────────────────────────────────────────────────────────┐
│                          Network (192.168.0.x)                           │
└──────────────────────────────────────────────────────────────────────────┘
       │  eth0 (USB Ethernet)                          │
       │                                               │
       ▼                                               ▼
┌─────────────────────────┐              ┌─────────────────────────────────┐
│  Serial Portal Pi       │              │  VM Host / Containers           │
│  192.168.0.87           │              │                                 │
│                         │              │  ┌─────────────────────┐        │
│  ┌───────────┐          │              │  │ Container A         │        │
│  │ SLOT1     │──────────┼─ :4001 ──────┼──│ rfc2217://:4001     │        │
│  └───────────┘          │              │  └─────────────────────┘        │
│  ┌───────────┐          │              │  ┌─────────────────────┐        │
│  │ SLOT2     │──────────┼─ :4002 ──────┼──│ Container B         │        │
│  └───────────┘          │              │  │ rfc2217://:4002     │        │
│  ┌───────────┐          │              │  └─────────────────────┘        │
│  │ SLOT3     │──────────┼─ :4003       │                                 │
│  └───────────┘          │              └─────────────────────────────────┘
│                         │
│  ┌───────────────────┐  │
│  │ WiFi Tester       │  │
│  │ wlan0 (onboard)   │  │
│  │  AP: 192.168.4.1  │  │
│  └───────────────────┘  │
│                         │
│  Web Portal ────────────┼─ :8080
└─────────────────────────┘
```

## How RFC2217 Works

RFC2217 is a Telnet protocol extension that allows serial port control over TCP/IP. The Pi runs an RFC2217 server per USB serial device, each on a fixed TCP port determined by which physical USB hub connector (slot) the device is plugged into.

**Benefits over USB/IP:**
- No kernel modules required
- No VM configuration needed
- Works through firewalls (just TCP)
- Native support in esptool, pyserial, PlatformIO

**Limitations:**
- Serial only (no USB HID, JTAG, etc.)
- One client per device at a time
- Slightly higher latency than local serial

---

## Part 1: Raspberry Pi Setup

### Prerequisites

```bash
# Update system
sudo apt update && sudo apt upgrade -y

# Install Python, curl, and WiFi tools
sudo apt install -y python3-pip curl hostapd dnsmasq iw wpasupplicant

# Install esptool (includes esp_rfc2217_server)
sudo pip3 install esptool --break-system-packages
```

### Install with install.sh

```bash
# Clone repository
git clone https://github.com/SensorsIot/USB-Serial-via-Ethernet.git
cd USB-Serial-via-Ethernet/pi

# Run installer
sudo bash install.sh
```

The installer copies:
- `portal.py` → `/usr/local/bin/rfc2217-portal`
- `wifi_controller.py` → `/usr/local/bin/wifi_controller.py`
- `serial_proxy.py` → `/usr/local/bin/serial_proxy.py`
- `scripts/rfc2217-udev-notify.sh` → `/usr/local/bin/rfc2217-udev-notify.sh`
- `scripts/wifi-lease-notify.sh` → `/usr/local/bin/wifi-lease-notify.sh`
- `udev/99-rfc2217-hotplug.rules` → `/etc/udev/rules.d/`
- `systemd/rfc2217-portal.service` → `/etc/systemd/system/`
- `config/slots.json` → `/etc/rfc2217/slots.json` (if not already present)

### Configure Slots

Each physical USB hub connector maps to a fixed TCP port. Use the learning tool to discover slot keys:

```bash
# Plug a device into the first hub connector, then run:
rfc2217-learn-slots

# Output:
# Detected device:
#   DEVNAME:  /dev/ttyACM0
#   ID_PATH:  platform-3f980000.usb-usb-0:1.1:1.0
#
# Add this to /etc/rfc2217/slots.json:
#   {"label": "SLOT1", "slot_key": "platform-3f980000.usb-usb-0:1.1:1.0", "tcp_port": 4001}
```

Edit `/etc/rfc2217/slots.json`:

```json
{
  "slots": [
    {"label": "SLOT1", "slot_key": "platform-3f980000.usb-usb-0:1.1:1.0", "tcp_port": 4001},
    {"label": "SLOT2", "slot_key": "platform-3f980000.usb-usb-0:1.3:1.0", "tcp_port": 4002},
    {"label": "SLOT3", "slot_key": "platform-3f980000.usb-usb-0:1.4:1.0", "tcp_port": 4003}
  ]
}
```

Restart the portal after editing:

```bash
sudo systemctl restart rfc2217-portal
```

### Verify Installation

```bash
# Check portal is running
sudo systemctl status rfc2217-portal

# Check web portal
curl http://localhost:8080/api/info

# List slot status
curl http://localhost:8080/api/devices

# Check RFC2217 servers
ss -tlnp | grep 400
```

---

## Part 2: Client Setup

### No VM Configuration Required

RFC2217 uses standard TCP connections. Containers and VMs connect directly to the Pi — no special configuration needed.

**Requirements:**
- Client can reach the Pi's IP address
- Ports 4001–4003 and 8080 are not blocked

### Install Dependencies

```bash
# Python with pyserial
pip3 install pyserial

# Optional: esptool for flashing
pip3 install esptool
```

---

## Part 3: Connecting to Devices

### Slot API

Query slot status:

```bash
curl http://192.168.0.87:8080/api/devices
```

Response:

```json
{
  "slots": [
    {
      "label": "SLOT1",
      "slot_key": "platform-...-usb-0:1.1:1.0",
      "tcp_port": 4001,
      "present": true,
      "running": true,
      "devnode": "/dev/ttyACM0",
      "url": "rfc2217://192.168.0.87:4001"
    }
  ],
  "host_ip": "192.168.0.87",
  "hostname": "192.168.0.87"
}
```

### Connect from Python

```python
import serial

# Connect to SLOT1
ser = serial.serial_for_url("rfc2217://192.168.0.87:4001", baudrate=115200, timeout=1)
print(f"Connected")

while True:
    line = ser.readline()
    if line:
        print(line.decode('utf-8', errors='replace').strip())
```

### Flash with esptool

```bash
# Read chip info
esptool --port 'rfc2217://192.168.0.87:4001?ign_set_control' chip_id

# Flash firmware
esptool --port 'rfc2217://192.168.0.87:4001?ign_set_control' \
    write_flash 0x0 firmware.bin

# If timeout errors, use --no-stub
esptool --no-stub --port 'rfc2217://192.168.0.87:4001?ign_set_control' \
    write_flash 0x0 firmware.bin
```

### PlatformIO

```ini
; platformio.ini
[env:esp32]
platform = espressif32
board = esp32dev
framework = arduino

upload_port = rfc2217://192.168.0.87:4001?ign_set_control
monitor_port = rfc2217://192.168.0.87:4001?ign_set_control
monitor_speed = 115200
```

### ESP-IDF

```bash
export ESPPORT='rfc2217://192.168.0.87:4001?ign_set_control'
idf.py flash monitor
```

### Create Local /dev/tty with socat

If your tool requires a local device path:

```bash
# Install socat
apt install -y socat

# Create virtual serial port
socat pty,link=/dev/ttyESP32,raw,echo=0 tcp:192.168.0.87:4001 &

# Now use /dev/ttyESP32
cat /dev/ttyESP32
```

---

## Part 4: WiFi Tester

The Pi's onboard wlan0 radio doubles as a WiFi test instrument. See the
[WiFi Tester HTTP Manual](WiFi-Tester-HTTP-Manual.md) for full API details.

### Operating Modes

| Mode | wlan0 | WiFi Tester |
|------|-------|-------------|
| WiFi-Testing (default) | Test instrument | Active |
| Serial Interface | Joins WiFi for LAN | Disabled |

Switch via web UI toggle or API:

```bash
# Switch to serial-interface mode (wlan0 joins WiFi)
curl -X POST http://192.168.0.87:8080/api/wifi/mode \
  -H 'Content-Type: application/json' \
  -d '{"mode": "serial-interface", "ssid": "MyWiFi", "pass": "password"}'

# Switch back to wifi-testing mode
curl -X POST http://192.168.0.87:8080/api/wifi/mode \
  -H 'Content-Type: application/json' \
  -d '{"mode": "wifi-testing"}'
```

### Start a SoftAP

```bash
curl -X POST http://192.168.0.87:8080/api/wifi/ap_start \
  -H 'Content-Type: application/json' \
  -d '{"ssid": "TestNetwork", "pass": "password123", "channel": 6}'
```

The AP runs at `192.168.4.1/24` with DHCP range `.2`–`.20`.

### Scan for Networks

```bash
curl http://192.168.0.87:8080/api/wifi/scan
```

### Run WiFi Tests

```bash
cd pytest
pip install pytest

# Basic tests (no DUT needed)
pytest test_instrument.py --wt-url http://192.168.0.87:8080

# Full tests (requires a WiFi device connected to the AP)
pytest test_instrument.py --wt-url http://192.168.0.87:8080 --run-dut
```

---

## Part 5: Serial Logging

All serial traffic is logged when using `serial_proxy.py` (the fallback proxy).

### Log Location

Logs are stored on the Pi at `/var/log/serial/`.

### Log Format

```
[2026-02-03 19:32:00.154] [RX] ESP32 boot message here...
[2026-02-03 19:32:00.258] [INFO] Baudrate changed to 115200
[2026-02-03 19:32:00.711] [TX] Data sent to ESP32...
```

- **[RX]** — Data received from device
- **[TX]** — Data sent to device
- **[INFO]** — Protocol events (baudrate changes, connections)

### View Logs

```bash
# Live tail on Pi
tail -f /var/log/serial/*.log

# Portal logs
journalctl -u rfc2217-portal -f
```

---

## Part 6: Troubleshooting

### Pi Side

**Portal not starting:**
```bash
sudo systemctl status rfc2217-portal
sudo journalctl -u rfc2217-portal -f
```

**Device not detected:**
```bash
ls -la /dev/ttyUSB* /dev/ttyACM*
dmesg | tail -20
```

**Hotplug events not reaching portal:**

udev runs scripts in a network-isolated sandbox (`PrivateNetwork=yes`).
The udev rules use `systemd-run --no-block` to escape this sandbox.
If you write custom udev rules, wrap your script with `systemd-run`.

**Check listening ports:**
```bash
ss -tlnp | grep -E '400|8080'
```

### Client Side

**Connection refused:**
```bash
# Check network connectivity
ping 192.168.0.87
curl http://192.168.0.87:8080/api/devices
```

**Timeout during flash:**
- Use `--no-stub` flag with esptool
- Check network latency: `ping 192.168.0.87`

**Port busy:**
- Only one client can connect per slot at a time
- Close the other connection first

### Common Issues

| Issue | Cause | Solution |
|-------|-------|----------|
| Connection refused | Proxy not running | Check portal at :8080; verify device is plugged in |
| Timeout during flash | Network latency | Use `esptool --no-stub` for reliability |
| Port busy | Another client connected | Close other connection first |
| Hotplug not working | udev sandbox | Verify rules use `systemd-run --no-block` |
| Device not detected | USB issue | Run `dmesg \| tail` on the Pi |
| Wrong slot after replug | Normal | slot_key ensures same port; devnode may change |

---

## Part 7: Network Requirements

| Port | Direction | Purpose |
|------|-----------|---------|
| 8080 | Client → Pi | Web portal and REST API |
| 4001–4003 | Client → Pi | RFC2217 serial connections |
| 192.168.4.x | WiFi devices → Pi | WiFi AP subnet (when AP active) |

### Firewall Rules (if needed)

```bash
# On Pi
sudo ufw allow 8080/tcp
sudo ufw allow 4001:4003/tcp
```

---

## Part 8: Security Considerations

- RFC2217 has **no authentication** — anyone who can reach the port can connect
- Keep on a trusted network or use VPN/firewall
- Portal runs as root for device access
- Consider SSH tunnel for remote access:

```bash
# On client, create tunnel
ssh -L 4001:localhost:4001 -L 8080:localhost:8080 pi@192.168.0.87

# Then connect to localhost
curl http://localhost:8080/api/devices
```

---

## Part 9: Files Reference

### Pi Files

| Path | Purpose |
|------|---------|
| `/usr/local/bin/rfc2217-portal` | Portal: web UI, API, proxy supervisor, WiFi API |
| `/usr/local/bin/wifi_controller.py` | WiFi instrument backend |
| `/usr/local/bin/esp_rfc2217_server.py` | RFC2217 server from esptool (preferred) |
| `/usr/local/bin/serial_proxy.py` | RFC2217 proxy with logging (fallback) |
| `/usr/local/bin/rfc2217-udev-notify.sh` | udev event forwarder |
| `/usr/local/bin/wifi-lease-notify.sh` | dnsmasq DHCP lease forwarder |
| `/usr/local/bin/rfc2217-learn-slots` | Slot discovery tool |
| `/etc/rfc2217/slots.json` | Slot configuration |
| `/etc/udev/rules.d/99-rfc2217-hotplug.rules` | udev rules |
| `/etc/systemd/system/rfc2217-portal.service` | systemd unit |
| `/var/log/serial/` | Serial traffic logs |

### Key Concepts

- **Slot** — a physical USB hub connector, identified by `slot_key` (udev `ID_PATH`)
- **Same connector = same TCP port**, regardless of device or devnode name
- **Two modes** — WiFi-Testing (default, wlan0 = instrument) and Serial Interface (wlan0 = LAN)

---

## Quick Reference

**Check status:**
```bash
curl http://192.168.0.87:8080/api/devices
curl http://192.168.0.87:8080/api/info
```

**Connect from Python:**
```python
import serial
ser = serial.serial_for_url("rfc2217://192.168.0.87:4001", baudrate=115200)
```

**Flash with esptool:**
```bash
esptool --port 'rfc2217://192.168.0.87:4001?ign_set_control' write_flash 0x0 fw.bin
```

**WiFi tester:**
```bash
# Start AP
curl -X POST http://192.168.0.87:8080/api/wifi/ap_start \
  -H 'Content-Type: application/json' -d '{"ssid":"Test","pass":"pass1234"}'

# Scan
curl http://192.168.0.87:8080/api/wifi/scan

# Check mode
curl http://192.168.0.87:8080/api/wifi/mode
```

**Web portal:** Open `http://192.168.0.87:8080` in a browser.
