# Serial-via-Ethernet Functional Specification Document

## 1. Overview

### 1.1 Purpose
Expose USB serial devices (ESP32, Arduino) from a Raspberry Pi to network clients using RFC2217 protocol, with event-driven device management, slot-based port assignment, and serial traffic logging.

### 1.2 System Architecture

```
┌─────────────────────────────────────────────────────────────────────┐
│                         Network (192.168.0.x)                        │
└─────────────────────────────────────────────────────────────────────┘
         │                              │
         │                              │
         ▼                              ▼
┌─────────────────┐           ┌─────────────────────────────┐
│  Serial Pi      │           │  VM Host (192.168.0.160)    │
│  192.168.0.87   │           │                             │
│                 │           │  ┌─────────────────────┐    │
│  ┌───────────┐  │           │  │ Container A         │    │
│  │ SLOT1     │──┼─ :4001 ───┼──│ rfc2217://:4001     │    │
│  └───────────┘  │           │  └─────────────────────┘    │
│  ┌───────────┐  │           │  ┌─────────────────────┐    │
│  │ SLOT2     │──┼─ :4002 ───┼──│ Container B         │    │
│  └───────────┘  │           │  │ rfc2217://:4002     │    │
│  ┌───────────┐  │           │  └─────────────────────┘    │
│  │ SLOT3     │──┼─ :4003    │                             │
│  └───────────┘  │           │                             │
│                 │           │                             │
│  Web Portal ────┼─ :8080    │                             │
└─────────────────┘           └─────────────────────────────┘
```

### 1.3 Hardware

| Component | Details |
|-----------|---------|
| Raspberry Pi Zero | 192.168.0.87 (Serial Pi) |
| USB Hub | 3-port hub connected to single USB port |
| Devices | ESP32, Arduino, or any USB serial device |

### 1.4 Components

| Component | Location | Purpose |
|-----------|----------|---------|
| rfc2217-portal (portal.py) | /usr/local/bin/rfc2217-portal | Web UI, API, process supervisor, hotplug handler |
| esp_rfc2217_server.py | /usr/local/bin/esp_rfc2217_server.py | RFC2217 server from esptool (preferred, stable) |
| serial_proxy.py | /usr/local/bin/serial_proxy.py | RFC2217 server with logging (fallback) |
| rfc2217-udev-notify.sh | /usr/local/bin/rfc2217-udev-notify.sh | Shell script: posts udev events to portal API |
| rfc2217-learn-slots | /usr/local/bin/rfc2217-learn-slots | Slot configuration helper |
| 99-rfc2217-hotplug.rules | /etc/udev/rules.d/ | udev rules for hotplug |
| slots.json | /etc/rfc2217/slots.json | Slot-to-port mapping |

---

## 2. Definitions

### 2.1 Entities

| Entity | Description |
|--------|-------------|
| **Slot** | Represents one physical connector position on the USB hub |
| **slot_key** | Stable identifier for physical port topology (derived from udev `ID_PATH`) |
| **devnode** | Current tty device path (e.g., `/dev/ttyACM0`) - may change on reconnect |
| **proxy** | RFC2217 server process for a local serial device (`esp_rfc2217_server.py` preferred, `serial_proxy.py` fallback) |
| **seq** (sequence) | Global monotonically increasing counter, incremented on every hotplug event |

### 2.2 Key Principle: Slot-Based Identity

**The system keys on physical connector position, NOT on:**
- `/dev/ttyACMx` (changes on reconnect)
- Device serial number (two identical boards would conflict)
- VID/PID/model (not unique)

**The system keys on:**
- `slot_key` = udev `ID_PATH` (identifies physical USB port topology)

This ensures:
- Same physical connector → same TCP port (always)
- Device can be swapped → same TCP port
- Two identical boards → different TCP ports (different slots)

---

## 3. Functional Requirements

### 3.1 Event-Driven Hotplug (FR-001)

**Unplug Flow:**
1. udev emits `remove` event for the serial device
2. udev rule invokes `rfc2217-udev-notify.sh` via `systemd-run --no-block`
3. Notify script sends `POST /api/hotplug` with `{action: "remove", devnode, id_path, devpath}`
4. Portal determines `slot_key` from `id_path` (or `devpath` fallback)
5. Portal increments global `seq_counter`, records event metadata on the slot
6. Portal stops the `serial_proxy` process for that slot (idempotent)
7. Slot state becomes `running=false`, `present=false`

**Plug Flow:**
1. udev emits `add` event for the serial device
2. udev rule invokes `rfc2217-udev-notify.sh` via `systemd-run --no-block`
3. Notify script sends `POST /api/hotplug` with `{action: "add", devnode, id_path, devpath}`
4. Portal determines `slot_key` from `id_path` (or `devpath` fallback)
5. Portal increments global `seq_counter`, records event metadata on the slot
6. Portal spawns a background thread that acquires the slot lock, waits for the device to settle, then starts `serial_proxy` bound to `devnode` on the configured TCP port
7. Slot state becomes `running=true`, `present=true`

### 3.2 Slot Configuration (FR-002)

**Required Behavior:**
- Static configuration maps `slot_key` → `{label, tcp_port}`
- Configuration file: `/etc/rfc2217/slots.json`
- Learning tool helps discover `slot_key` values for each physical connector

**Configuration Format:**
```json
{
  "slots": [
    {"label": "SLOT1", "slot_key": "platform-3f980000.usb-usb-0:1.1:1.0", "tcp_port": 4001},
    {"label": "SLOT2", "slot_key": "platform-3f980000.usb-usb-0:1.3:1.0", "tcp_port": 4002},
    {"label": "SLOT3", "slot_key": "platform-3f980000.usb-usb-0:1.4:1.0", "tcp_port": 4003}
  ]
}
```

### 3.3 Device Discovery API (FR-003)

**API Endpoints:**

| Endpoint | Method | Description |
|----------|--------|-------------|
| /api/devices | GET | List all slots with status |
| /api/hotplug | POST | Receive udev hotplug event (add/remove) |
| /api/start | POST | Manually start proxy for slot |
| /api/stop | POST | Manually stop proxy for slot |
| /api/info | GET | Get Pi IP and system info |

**Request Format (POST /api/hotplug):**
```json
{
  "action": "add",
  "devnode": "/dev/ttyACM0",
  "id_path": "platform-fd500000.pcie-pci-0000:01:00.0-usb-0:1.3:1.0",
  "devpath": "/devices/platform/scb/fd500000.pcie/.../ttyACM0"
}
```

**Request Format (POST /api/start):**
```json
{
  "slot_key": "platform-fd500000.pcie-pci-0000:01:00.0-usb-0:1.3:1.0",
  "devnode": "/dev/ttyACM0"
}
```

**Request Format (POST /api/stop):**
```json
{
  "slot_key": "platform-fd500000.pcie-pci-0000:01:00.0-usb-0:1.3:1.0"
}
```

**Response Format (GET /api/devices):**
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
      "pid": 1234,
      "url": "rfc2217://192.168.0.87:4001",
      "seq": 5,
      "last_action": "add",
      "last_event_ts": "2026-02-05T12:34:56+00:00",
      "last_error": null
    },
    {
      "label": "SLOT2",
      "slot_key": "platform-...-usb-0:1.2:1.0",
      "tcp_port": 4002,
      "present": false,
      "running": false,
      "devnode": null,
      "pid": null,
      "url": "rfc2217://192.168.0.87:4002",
      "seq": 0,
      "last_action": null,
      "last_event_ts": null,
      "last_error": null
    }
  ],
  "host_ip": "192.168.0.87"
}
```

### 3.4 Serial Traffic Logging (FR-004)

**Required Behavior:**
- All serial traffic logged with timestamps
- Log files in `/var/log/serial/`
- Log format: `[timestamp] [direction] data`

### 3.5 Web Portal (FR-005)

**Required Behavior:**
- Display all 3 slots (always visible, even if empty)
- Show slot status (running/stopped)
- Show current devnode when running
- Start/stop individual slots
- Copy RFC2217 URL to clipboard
- Display connection examples

---

## 4. Technical Specifications

### 4.1 Slot Key Derivation

```python
def get_slot_key(udev_env):
    """Derive slot_key from udev environment variables."""
    # Preferred: ID_PATH (stable across reboots)
    if 'ID_PATH' in udev_env and udev_env['ID_PATH']:
        return udev_env['ID_PATH']

    # Fallback: DEVPATH (less stable but usable)
    if 'DEVPATH' in udev_env:
        return udev_env['DEVPATH']

    raise ValueError("Cannot determine slot_key: no ID_PATH or DEVPATH")
```

### 4.2 Sequence Counter

The portal owns a single global monotonic `seq_counter` in memory (no files on disk).
Every hotplug event increments the counter and stamps the affected slot:

```python
# Module-level state (in portal.py)
seq_counter: int = 0

# Inside _handle_hotplug:
seq_counter += 1
slot["seq"] = seq_counter
slot["last_action"] = action       # "add" or "remove"
slot["last_event_ts"] = datetime.now(timezone.utc).isoformat()
```

The sequence number provides a total ordering of events for diagnostics.
Because the portal processes hotplug requests serially per slot (via per-slot locks),
stale-event races are prevented by locking rather than by comparing counters.

### 4.3 API Idempotency

**POST /api/start semantics:**
- If slot running with same devnode: return OK (no restart)
- If slot running with different devnode: restart cleanly
- If slot not running: start
- Never fails if already in desired state

**POST /api/stop semantics:**
- If slot not running: return OK
- If running: stop
- Never fails if already in desired state

### 4.4 Per-Slot Locking

Portal serializes operations per slot using in-memory `threading.Lock` objects:

```python
# Each slot dict holds its own lock (created at config load time)
slot["_lock"] = threading.Lock()

# Usage (e.g., inside hotplug add handler):
with slot["_lock"]:
    stop_proxy(slot)   # stop old proxy if running
    start_proxy(slot)  # start new proxy
```

No file-based locks or `/run/rfc2217/locks/` directory is used.

### 4.5 Device Settle Checks

The portal's `start_proxy` function performs settle checks inline (no separate
handler). It polls the device node before launching `serial_proxy`:

```python
def wait_for_device(devnode, timeout=5.0):
    """Wait for device to be usable (called inside portal)."""
    deadline = time.time() + timeout
    while time.time() < deadline:
        if os.path.exists(devnode):
            try:
                fd = os.open(devnode, os.O_RDWR | os.O_NONBLOCK)
                os.close(fd)
                return True
            except OSError:
                pass
        time.sleep(0.1)
    return False
```

If the device does not settle within the timeout, the slot's `last_error` is set
and the proxy is not started.

### 4.6 udev Rules

```
# /etc/udev/rules.d/99-rfc2217-hotplug.rules
# Notify portal of USB serial add/remove events.
# systemd-run escapes udev's PrivateNetwork sandbox so curl can reach localhost.

ACTION=="add", SUBSYSTEM=="tty", KERNEL=="ttyACM*", RUN+="/usr/bin/systemd-run --no-block /usr/local/bin/rfc2217-udev-notify.sh %E{ACTION} %E{DEVNAME} %E{ID_PATH} %E{DEVPATH}"
ACTION=="remove", SUBSYSTEM=="tty", KERNEL=="ttyACM*", RUN+="/usr/bin/systemd-run --no-block /usr/local/bin/rfc2217-udev-notify.sh %E{ACTION} %E{DEVNAME} %E{ID_PATH} %E{DEVPATH}"
ACTION=="add", SUBSYSTEM=="tty", KERNEL=="ttyUSB*", RUN+="/usr/bin/systemd-run --no-block /usr/local/bin/rfc2217-udev-notify.sh %E{ACTION} %E{DEVNAME} %E{ID_PATH} %E{DEVPATH}"
ACTION=="remove", SUBSYSTEM=="tty", KERNEL=="ttyUSB*", RUN+="/usr/bin/systemd-run --no-block /usr/local/bin/rfc2217-udev-notify.sh %E{ACTION} %E{DEVNAME} %E{ID_PATH} %E{DEVPATH}"
```

The notify script is a thin shell wrapper that posts a JSON payload to the portal:

```bash
#!/bin/bash
# /usr/local/bin/rfc2217-udev-notify.sh
# Args: ACTION DEVNAME ID_PATH DEVPATH

curl -m 2 -s -X POST http://127.0.0.1:8080/api/hotplug \
  -H 'Content-Type: application/json' \
  -d "{\"action\":\"$1\",\"devnode\":\"$2\",\"id_path\":\"${3:-}\",\"devpath\":\"$4\"}" \
  || true
```

### 4.7 systemd Service (Portal)

The portal runs as a long-lived systemd service. There is no separate
`rfc2217-hotplug@.service` template; udev events are delivered to the portal
via `systemd-run` and the notify script (see 4.6).

```ini
# /etc/systemd/system/rfc2217-portal.service
[Unit]
Description=RFC2217 Portal
After=network.target

[Service]
ExecStart=/usr/bin/python3 /usr/local/bin/rfc2217-portal
Restart=on-failure
StandardOutput=journal
StandardError=journal

[Install]
WantedBy=multi-user.target
```

### 4.8 Network Ports

| Port | Service |
|------|---------|
| 8080 | Web portal and API |
| 4001 | SLOT1 RFC2217 |
| 4002 | SLOT2 RFC2217 |
| 4003 | SLOT3 RFC2217 |

---

## 5. Non-Functional Requirements

### 5.1 Must Tolerate

| Scenario | How Handled |
|----------|-------------|
| `/dev/ttyACM0` → `/dev/ttyACM1` renaming | slot_key unchanged (based on physical port) |
| Duplicate udev events | API idempotency, per-slot locking |
| "Remove after add" races (USB reset) | Per-slot locking serializes operations; sequence counter aids diagnostics |
| Two identical boards | Different slot_keys (different physical connectors) |
| Hub/Pi reboot | Static config preserves port assignments |

### 5.2 Determinism

- Same physical connector → same TCP port (always)
- Configuration survives reboots
- No dynamic port assignment

### 5.3 Reliability

- Portal API must be idempotent
- Actions serialized per slot (locking)
- Stale events prevented via per-slot locking; sequence counter for observability

---

## 6. Slot Learning Workflow

### 6.1 Tool: rfc2217-learn-slots

```bash
$ rfc2217-learn-slots
Plug a device into the USB hub connector you want to identify...

Detected device:
  DEVNAME:  /dev/ttyACM0
  ID_PATH:  platform-fd500000.pcie-pci-0000:01:00.0-usb-0:1.3:1.0
  DEVPATH:  /devices/platform/scb/fd500000.pcie/.../ttyACM0
  BY-PATH:  /dev/serial/by-path/platform-fd500000.pcie-pci-0000:01:00.0-usb-0:1.3:1.0

Add this to /etc/rfc2217/slots.json:
  {"label": "SLOT?", "slot_key": "platform-fd500000.pcie-pci-0000:01:00.0-usb-0:1.3:1.0", "tcp_port": 400?}
```

### 6.2 Initial Setup Procedure

1. Start with empty slots.json
2. Plug device into first hub connector
3. Run `rfc2217-learn-slots`, note the `ID_PATH`
4. Add to config as SLOT1 with tcp_port 4001
5. Repeat for each hub connector
6. Restart portal service

---

## 7. Edge Cases

| Case | Behavior |
|------|----------|
| Two identical boards | Works - different slot_keys (different physical connectors) |
| Device re-enumeration (USB reset) | Per-slot locking serializes add/remove; background thread restart is safe |
| Duplicate events | Idempotency prevents flapping |
| Unknown slot_key | Portal tracks the slot (present, seq) but does not start a proxy; logged for diagnostics |
| Hub topology changed | Must re-learn and update config |
| Device not ready | Settle checks with timeout, then fail |

---

## 8. Test Cases

### TC-001: Plug into SLOT3
1. Ensure portal running, SLOT3 configured for port 4003
2. Plug ESP32 into physical connector mapped to SLOT3
3. Within 5 seconds: `GET /api/devices`
4. **Pass:** SLOT3 shows `running=true`, `devnode` set, `tcp_port=4003`

### TC-002: Unplug from SLOT3
1. Have device running in SLOT3
2. Unplug device
3. Within 2 seconds: `GET /api/devices`
4. **Pass:** SLOT3 shows `running=false`, `devnode=null`

### TC-003: Replug into SLOT3
1. Unplug device from SLOT3
2. Replug into same physical connector
3. **Pass:** SLOT3 `running=true`, same `tcp_port=4003`, devnode may differ

### TC-004: Two Identical Boards
1. Plug identical ESP32 into SLOT1
2. Plug identical ESP32 into SLOT2
3. **Pass:** Both running on different TCP ports (4001, 4002)

### TC-005: USB Reset Race
1. Have device running in SLOT1
2. Force USB reset (quick unplug/replug)
3. **Pass:** No "stuck stopped" state; per-slot locking serializes the events

### TC-006: Devnode Renaming
1. Plug device into SLOT1 as `/dev/ttyACM0`
2. Unplug
3. Plug different device (gets `/dev/ttyACM0`)
4. Replug original device (now `/dev/ttyACM1`)
5. **Pass:** Original device still on SLOT1's port (4001)

### TC-007: Boot Persistence
1. Configure slots, plug devices
2. Reboot Pi
3. **Pass:** Same slots get same ports after boot

### TC-008: Unknown Slot
1. Plug device into unconfigured hub connector
2. **Pass:** Portal logs "unknown slot_key", no crash

---

## 9. Implementation Tasks

- [x] **TASK-001:** Create slot-based configuration loader
- [x] **TASK-002:** Implement sequence counter in portal
- [x] **TASK-003:** Implement per-slot locking in portal (threading.Lock)
- [x] **TASK-004:** Implement POST /api/hotplug endpoint in portal
- [x] **TASK-005:** Implement device settle checks in portal start_proxy
- [x] **TASK-006:** Create rfc2217-udev-notify.sh script
- [x] **TASK-007:** Create 99-rfc2217-hotplug.rules (systemd-run based)
- [x] **TASK-008:** Create rfc2217-learn-slots tool
- [ ] **TASK-009:** Update web UI to show slot-based view
- [ ] **TASK-010:** Test all test cases
- [ ] **TASK-011:** Deploy to Serial Pi (192.168.0.87)

---

## 10. Deliverables

| Deliverable | Description |
|-------------|-------------|
| `portal.py` (`rfc2217-portal`) | HTTP server with slot management, process supervision, hotplug handling |
| `esp_rfc2217_server.py` | RFC2217 server from esptool (preferred — stable, supports flashing and monitoring) |
| `serial_proxy.py` | RFC2217 proxy with serial traffic logging (fallback) |
| `rfc2217-udev-notify.sh` | Shell script: posts udev events to portal API via curl |
| `rfc2217-learn-slots` | CLI tool to discover slot_key for physical connectors |
| `99-rfc2217-hotplug.rules` | udev rules using systemd-run to invoke notify script |
| `rfc2217-portal.service` | systemd unit for the portal |
| `slots.json` | Slot configuration file |

---

## 11. Revision History

| Version | Date | Author | Changes |
|---------|------|--------|---------|
| 1.0 | 2026-02-05 | Claude | Initial FSD |
| 1.1 | 2026-02-05 | Claude | Implemented serial-based port assignment |
| 1.2 | 2026-02-05 | Claude | Testing complete for serial-based approach |
| 2.0 | 2026-02-05 | Claude | Major rewrite: event-driven slot-based architecture |
| 3.0 | 2026-02-05 | Claude | Portal v3: portal handles hotplug directly via POST /api/hotplug; removed separate hotplug handler binary and systemd template; in-memory seq counter and threading.Lock per slot; udev rules use systemd-run with rfc2217-udev-notify.sh |
