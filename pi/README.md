# Raspberry Pi Setup

## Prerequisites

```bash
sudo apt update && sudo apt install -y python3-pip curl

# Install esptool (includes esp_rfc2217_server)
sudo pip3 install esptool --break-system-packages
```

## Installation

```bash
# Install portal and serial proxy
sudo cp portal.py /usr/local/bin/rfc2217-portal
sudo cp serial_proxy.py /usr/local/bin/serial-proxy
sudo chmod +x /usr/local/bin/rfc2217-portal /usr/local/bin/serial-proxy

# Install hotplug script (for auto-start on device plug)
sudo cp scripts/rfc2217-hotplug.sh /usr/local/bin/rfc2217-hotplug
sudo chmod +x /usr/local/bin/rfc2217-hotplug

# Install udev rules
sudo cp udev/99-rfc2217.rules /etc/udev/rules.d/
sudo udevadm control --reload-rules

# Create log directory
sudo mkdir -p /var/log/serial
sudo chmod 755 /var/log/serial

# Install systemd service
sudo cp systemd/rfc2217-portal.service /etc/systemd/system/

# Enable and start
sudo systemctl daemon-reload
sudo systemctl enable --now rfc2217-portal
```

## How It Works

1. **On boot:** Portal starts and auto-starts serial proxies for all connected devices
2. **On device plug:** udev rule triggers hotplug script → starts serial proxy
3. **On device unplug:** Proxy automatically stops (device gone)
4. **Continuous logging:** All serial traffic is logged with timestamps

## Serial Logging

All serial traffic is automatically logged to `/var/log/serial/`:

```bash
# View live logs
tail -f /var/log/serial/*.log

# List log files
ls -la /var/log/serial/
```

**Log file naming:** `{Product}_{Serial}_{Date}.log`
```
FT232R_USB_UART_A5069RR4_2026-02-03.log
```

**Log format:**
```
[2026-02-03 19:32:00.154] [RX] Data received from device
[2026-02-03 19:32:00.711] [TX] Data sent to device
[2026-02-03 19:32:00.826] [INFO] Baudrate changed to 115200
```

**View logs via API:**
```bash
# List all logs
curl http://localhost:8080/api/logs

# Get last 100 lines
curl "http://localhost:8080/api/logs/FILENAME.log?lines=100"
```

## Configuration

Device-port mappings are stored in `/etc/rfc2217/devices.conf`:

```
# RFC2217 device-port assignments
/dev/ttyUSB0=4001
/dev/ttyUSB1=4002
```

This file is managed automatically by the portal.

## Web Portal

Access at **http://\<pi-ip\>:8080**

Features:
- View connected serial devices
- Start/Stop RFC2217 servers per device
- Auto-assigns ports (4001, 4002, ...)
- Copy connection URLs

## Manual Server Control

```bash
# Start server for a device
esp_rfc2217_server.py -p 4001 /dev/ttyUSB0

# Check running servers
pgrep -a -f esp_rfc2217_server

# Stop all servers
pkill -f esp_rfc2217_server
```

## Stable Device Names

For consistent port assignments across reboots, use `/dev/serial/by-id/`:

```bash
ls -la /dev/serial/by-id/
```

Example output:
```
usb-Silicon_Labs_CP2102_USB_to_UART_Bridge_0001-if00-port0 -> ../../ttyUSB0
usb-1a86_USB_Single_Serial_58DD029450-if00 -> ../../ttyUSB1
```

## Troubleshooting

### esp_rfc2217_server not found

```bash
# Check if installed
which esp_rfc2217_server.py

# If not found, reinstall
sudo pip3 install --force-reinstall esptool --break-system-packages
```

### Portal not starting

```bash
# Check status
sudo systemctl status rfc2217-portal

# View logs
sudo journalctl -u rfc2217-portal -f
```

### Device not detected

```bash
# List USB devices
ls -la /dev/ttyUSB* /dev/ttyACM*

# Check kernel messages
dmesg | grep -i usb | tail -20
```

### Server not auto-starting on plug

```bash
# Check udev rules are loaded
sudo udevadm control --reload-rules

# Test manually
sudo /usr/local/bin/rfc2217-hotplug add /dev/ttyUSB0

# Check logs
journalctl -t rfc2217-hotplug
```

### Check listening ports

```bash
ss -tlnp | grep 400
```
