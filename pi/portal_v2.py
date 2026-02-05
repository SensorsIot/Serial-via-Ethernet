#!/usr/bin/env python3
"""
RFC2217 Portal v2 - Slot-based device management

Event-driven architecture with:
- Slot-based identity (physical USB port, not device serial)
- Generation tracking for race condition handling
- Idempotent APIs with per-slot locking
- Process supervision for serial_proxy instances
"""

import os
import sys
import json
import time
import signal
import socket
import hashlib
import logging
import threading
import subprocess
import http.server
import fcntl
from pathlib import Path
from typing import Dict, Optional, Any

# Configuration
CONFIG_FILE = os.environ.get('RFC2217_CONFIG', '/etc/rfc2217/slots.json')
LOCK_DIR = '/run/rfc2217/locks'
LOG_DIR = '/var/log/serial'
HTTP_PORT = 8080
PROXY_PATHS = [
    '/usr/local/bin/serial_proxy.py',
    '/usr/local/bin/serial-proxy',
    '/usr/local/bin/esp_rfc2217_server.py'
]

# Logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s [%(levelname)s] %(message)s',
    handlers=[logging.StreamHandler()]
)
log = logging.getLogger('portal')


class SlotState:
    """State for a single slot."""
    def __init__(self, label: str, slot_key: str, tcp_port: int):
        self.label = label
        self.slot_key = slot_key
        self.tcp_port = tcp_port
        self.running = False
        self.pid: Optional[int] = None
        self.devnode: Optional[str] = None
        self.last_gen = 0
        self.last_error: Optional[str] = None
        self.lock = threading.Lock()


class Portal:
    """Main portal class managing slots and processes."""

    def __init__(self, config_file: str):
        self.config_file = config_file
        self.slots: Dict[str, SlotState] = {}
        self.slots_by_label: Dict[str, SlotState] = {}
        self.host_ip = self._get_host_ip()
        self._load_config()
        os.makedirs(LOCK_DIR, exist_ok=True)
        os.makedirs(LOG_DIR, exist_ok=True)

    def _get_host_ip(self) -> str:
        """Get host IP address."""
        try:
            s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
            s.connect(('8.8.8.8', 80))
            ip = s.getsockname()[0]
            s.close()
            return ip
        except:
            return '127.0.0.1'

    def _load_config(self):
        """Load slot configuration from file."""
        try:
            with open(self.config_file, 'r') as f:
                config = json.load(f)

            for slot_cfg in config.get('slots', []):
                label = slot_cfg['label']
                slot_key = slot_cfg['slot_key']
                tcp_port = slot_cfg['tcp_port']

                slot = SlotState(label, slot_key, tcp_port)
                self.slots[slot_key] = slot
                self.slots_by_label[label] = slot

            log.info(f"Loaded {len(self.slots)} slots from {self.config_file}")
        except FileNotFoundError:
            log.warning(f"Config file not found: {self.config_file}")
        except Exception as e:
            log.error(f"Error loading config: {e}")

    def _slot_key_hash(self, slot_key: str) -> str:
        """Hash slot_key for filenames."""
        return hashlib.sha256(slot_key.encode()).hexdigest()[:16]

    def _get_lock_path(self, slot_key: str) -> str:
        """Get lock file path for slot."""
        return os.path.join(LOCK_DIR, f"{self._slot_key_hash(slot_key)}.lock")

    def _find_proxy_executable(self) -> Optional[str]:
        """Find available serial proxy executable."""
        for path in PROXY_PATHS:
            if os.path.exists(path):
                return path
        return None

    def _is_process_alive(self, pid: int) -> bool:
        """Check if process is alive."""
        try:
            os.kill(pid, 0)
            return True
        except OSError:
            return False

    def _is_port_listening(self, port: int) -> bool:
        """Check if port is listening."""
        try:
            s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            s.settimeout(1)
            result = s.connect_ex(('127.0.0.1', port))
            s.close()
            return result == 0
        except:
            return False

    def _stop_process(self, pid: int, timeout: float = 5.0):
        """Stop a process gracefully, then forcefully."""
        try:
            os.kill(pid, signal.SIGTERM)
            deadline = time.time() + timeout
            while time.time() < deadline:
                if not self._is_process_alive(pid):
                    return True
                time.sleep(0.1)
            # Force kill
            os.kill(pid, signal.SIGKILL)
            time.sleep(0.5)
            return not self._is_process_alive(pid)
        except OSError:
            return True

    def _wait_for_device(self, devnode: str, timeout: float = 5.0) -> bool:
        """Wait for device to be usable (settle check)."""
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

    def _start_proxy(self, slot: SlotState, devnode: str) -> tuple[bool, str]:
        """Start serial_proxy for a slot."""
        proxy_exe = self._find_proxy_executable()
        if not proxy_exe:
            return False, "No serial proxy executable found"

        # Settle check - wait for device to be usable
        if not self._wait_for_device(devnode):
            return False, f"Device {devnode} not ready after settle timeout"

        # Build command
        log_file = os.path.join(LOG_DIR, f"{slot.label}.log")
        cmd = ['python3', proxy_exe, '-p', str(slot.tcp_port)]

        # Add logging if supported
        if 'serial_proxy' in proxy_exe:
            cmd.extend(['-l', LOG_DIR])

        cmd.append(devnode)

        try:
            proc = subprocess.Popen(
                cmd,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                start_new_session=True
            )

            # Wait briefly and check if it started
            time.sleep(0.5)
            if proc.poll() is not None:
                return False, f"Proxy exited immediately with code {proc.returncode}"

            # Verify port is listening
            for _ in range(20):  # Wait up to 2 seconds
                if self._is_port_listening(slot.tcp_port):
                    return True, str(proc.pid)
                time.sleep(0.1)

            # Port not listening, kill process
            self._stop_process(proc.pid)
            return False, "Proxy started but port not listening"

        except Exception as e:
            return False, str(e)

    def start(self, slot_key: str, devnode: str) -> Dict[str, Any]:
        """Start serial proxy for a slot (API handler). Portal manages generation."""
        if slot_key not in self.slots:
            log.warning(f"Unknown slot_key: {slot_key}")
            return {'success': False, 'error': 'Unknown slot_key', 'slot_key': slot_key}

        slot = self.slots[slot_key]

        with slot.lock:
            # Increment generation (portal owns this)
            slot.last_gen += 1
            current_gen = slot.last_gen

            # If already running with same devnode and healthy, no action needed
            if slot.running and slot.pid and slot.devnode == devnode:
                if self._is_process_alive(slot.pid) and self._is_port_listening(slot.tcp_port):
                    log.info(f"{slot.label}: Already running on {devnode}")
                    return {'success': True, 'running': True, 'restarted': False, 'port': slot.tcp_port}

            # Stop existing proxy if running
            if slot.running and slot.pid:
                log.info(f"{slot.label}: Stopping existing proxy (pid {slot.pid})")
                self._stop_process(slot.pid)
                slot.running = False
                slot.pid = None

            # Start new proxy (includes settle check)
            log.info(f"{slot.label}: Starting proxy for {devnode} on port {slot.tcp_port}")
            success, result = self._start_proxy(slot, devnode)

            if success:
                slot.running = True
                slot.pid = int(result)
                slot.devnode = devnode
                slot.last_error = None
                log.info(f"{slot.label}: Started (pid {slot.pid})")
                return {'success': True, 'running': True, 'restarted': True, 'port': slot.tcp_port, 'pid': slot.pid}
            else:
                slot.running = False
                slot.pid = None
                slot.devnode = None
                slot.last_error = result
                log.error(f"{slot.label}: Failed to start: {result}")
                return {'success': False, 'error': result}

    def stop(self, slot_key: str) -> Dict[str, Any]:
        """Stop serial proxy for a slot (API handler). Portal manages generation."""
        if slot_key not in self.slots:
            log.warning(f"Unknown slot_key: {slot_key}")
            return {'success': False, 'error': 'Unknown slot_key', 'slot_key': slot_key}

        slot = self.slots[slot_key]

        with slot.lock:
            # Increment generation
            slot.last_gen += 1

            # If not running, nothing to do
            if not slot.running or not slot.pid:
                log.info(f"{slot.label}: Already stopped")
                return {'success': True, 'running': False}

            # Stop the proxy
            log.info(f"{slot.label}: Stopping proxy (pid {slot.pid})")
            self._stop_process(slot.pid)

            slot.running = False
            slot.pid = None
            slot.devnode = None
            slot.last_error = None

            return {'success': True, 'running': False}

    def get_devices(self) -> Dict[str, Any]:
        """Get status of all slots."""
        slots_info = []
        for slot in self.slots.values():
            # Refresh health status
            if slot.running and slot.pid:
                if not self._is_process_alive(slot.pid):
                    slot.running = False
                    slot.pid = None
                    slot.last_error = "Process died"

            slots_info.append({
                'label': slot.label,
                'slot_key': slot.slot_key,
                'tcp_port': slot.tcp_port,
                'running': slot.running,
                'devnode': slot.devnode,
                'pid': slot.pid,
                'url': f"rfc2217://{self.host_ip}:{slot.tcp_port}" if slot.running else None,
                'last_gen': slot.last_gen,
                'last_error': slot.last_error
            })

        return {'slots': slots_info, 'host_ip': self.host_ip}

    def get_info(self) -> Dict[str, Any]:
        """Get system info."""
        return {
            'host_ip': self.host_ip,
            'config_file': self.config_file,
            'slots_configured': len(self.slots),
            'slots_running': sum(1 for s in self.slots.values() if s.running)
        }


# Global portal instance
portal: Optional[Portal] = None


class RequestHandler(http.server.BaseHTTPRequestHandler):
    """HTTP request handler for portal API."""

    def log_message(self, format, *args):
        log.info(f"{self.address_string()} - {format % args}")

    def send_json(self, data: Dict, status: int = 200):
        """Send JSON response."""
        body = json.dumps(data, indent=2).encode('utf-8')
        self.send_response(status)
        self.send_header('Content-Type', 'application/json')
        self.send_header('Content-Length', len(body))
        self.send_header('Access-Control-Allow-Origin', '*')
        self.end_headers()
        self.wfile.write(body)

    def read_json(self) -> Optional[Dict]:
        """Read JSON from request body."""
        try:
            length = int(self.headers.get('Content-Length', 0))
            if length == 0:
                return {}
            body = self.rfile.read(length)
            return json.loads(body.decode('utf-8'))
        except:
            return None

    def do_OPTIONS(self):
        """Handle CORS preflight."""
        self.send_response(200)
        self.send_header('Access-Control-Allow-Origin', '*')
        self.send_header('Access-Control-Allow-Methods', 'GET, POST, OPTIONS')
        self.send_header('Access-Control-Allow-Headers', 'Content-Type')
        self.end_headers()

    def do_GET(self):
        """Handle GET requests."""
        if self.path == '/api/devices':
            self.send_json(portal.get_devices())
        elif self.path == '/api/info':
            self.send_json(portal.get_info())
        elif self.path == '/' or self.path == '/index.html':
            self.serve_ui()
        else:
            self.send_json({'error': 'Not found'}, 404)

    def do_POST(self):
        """Handle POST requests."""
        data = self.read_json()
        if data is None:
            self.send_json({'error': 'Invalid JSON'}, 400)
            return

        if self.path == '/api/start':
            slot_key = data.get('slot_key')
            devnode = data.get('devnode')

            if not slot_key or not devnode:
                self.send_json({'error': 'Missing slot_key or devnode'}, 400)
                return

            result = portal.start(slot_key, devnode)
            status = 200 if result.get('success') else 400
            self.send_json(result, status)

        elif self.path == '/api/stop':
            slot_key = data.get('slot_key')

            if not slot_key:
                self.send_json({'error': 'Missing slot_key'}, 400)
                return

            result = portal.stop(slot_key)
            status = 200 if result.get('success') else 400
            self.send_json(result, status)

        elif self.path == '/api/hotplug':
            # Single endpoint for udev events - portal handles logic
            action = data.get('action')
            devnode = data.get('devnode')
            slot_key = data.get('id_path')

            if not action or not slot_key:
                self.send_json({'error': 'Missing action or id_path'}, 400)
                return

            if action == 'add':
                if not devnode:
                    self.send_json({'error': 'Missing devnode for add'}, 400)
                    return
                result = portal.start(slot_key, devnode)
            elif action == 'remove':
                result = portal.stop(slot_key)
            else:
                self.send_json({'error': f'Unknown action: {action}'}, 400)
                return

            self.send_json(result)

        else:
            self.send_json({'error': 'Not found'}, 404)

    def serve_ui(self):
        """Serve the web UI."""
        html = '''<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>RFC2217 Serial Portal</title>
    <style>
        * { box-sizing: border-box; margin: 0; padding: 0; }
        body {
            font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif;
            background: #1a1a2e;
            color: #eee;
            min-height: 100vh;
            padding: 20px;
        }
        h1 {
            text-align: center;
            margin-bottom: 30px;
            color: #00d4ff;
        }
        .slots {
            display: grid;
            grid-template-columns: repeat(auto-fit, minmax(300px, 1fr));
            gap: 20px;
            max-width: 1000px;
            margin: 0 auto;
        }
        .slot {
            background: #16213e;
            border-radius: 12px;
            padding: 20px;
            border: 2px solid #0f3460;
            transition: all 0.3s;
        }
        .slot.running {
            border-color: #00d4ff;
            box-shadow: 0 0 20px rgba(0, 212, 255, 0.2);
        }
        .slot-header {
            display: flex;
            justify-content: space-between;
            align-items: center;
            margin-bottom: 15px;
        }
        .slot-label {
            font-size: 1.4em;
            font-weight: bold;
        }
        .status {
            padding: 4px 12px;
            border-radius: 20px;
            font-size: 0.85em;
            font-weight: bold;
        }
        .status.running {
            background: #00d4ff;
            color: #1a1a2e;
        }
        .status.stopped {
            background: #444;
            color: #888;
        }
        .slot-info {
            font-size: 0.9em;
            color: #aaa;
            margin-bottom: 15px;
        }
        .slot-info div {
            margin: 5px 0;
        }
        .slot-info span {
            color: #00d4ff;
            font-family: monospace;
        }
        .url-box {
            background: #0f3460;
            padding: 10px;
            border-radius: 8px;
            font-family: monospace;
            font-size: 0.9em;
            word-break: break-all;
            cursor: pointer;
            transition: background 0.2s;
        }
        .url-box:hover {
            background: #1a4a7a;
        }
        .url-box.empty {
            color: #666;
            cursor: default;
        }
        .copied {
            background: #00d4ff !important;
            color: #1a1a2e !important;
        }
        .error {
            color: #ff6b6b;
            font-size: 0.85em;
            margin-top: 10px;
        }
        .refresh-info {
            text-align: center;
            color: #666;
            margin-top: 30px;
            font-size: 0.85em;
        }
    </style>
</head>
<body>
    <h1>RFC2217 Serial Portal</h1>
    <div class="slots" id="slots"></div>
    <div class="refresh-info">Auto-refresh every 2 seconds</div>

    <script>
        async function fetchDevices() {
            try {
                const resp = await fetch('/api/devices');
                const data = await resp.json();
                renderSlots(data.slots);
            } catch (e) {
                console.error('Error fetching devices:', e);
            }
        }

        function renderSlots(slots) {
            const container = document.getElementById('slots');
            container.innerHTML = slots.map(slot => `
                <div class="slot ${slot.running ? 'running' : ''}">
                    <div class="slot-header">
                        <div class="slot-label">${slot.label}</div>
                        <div class="status ${slot.running ? 'running' : 'stopped'}">
                            ${slot.running ? 'RUNNING' : 'STOPPED'}
                        </div>
                    </div>
                    <div class="slot-info">
                        <div>Port: <span>${slot.tcp_port}</span></div>
                        <div>Device: <span>${slot.devnode || 'None'}</span></div>
                        ${slot.pid ? `<div>PID: <span>${slot.pid}</span></div>` : ''}
                    </div>
                    <div class="url-box ${slot.running ? '' : 'empty'}"
                         onclick="${slot.running ? `copyUrl('${slot.url}', this)` : ''}">
                        ${slot.running ? slot.url : 'No device connected'}
                    </div>
                    ${slot.last_error ? `<div class="error">Error: ${slot.last_error}</div>` : ''}
                </div>
            `).join('');
        }

        function copyUrl(url, el) {
            navigator.clipboard.writeText(url);
            el.classList.add('copied');
            el.textContent = 'Copied!';
            setTimeout(() => {
                el.classList.remove('copied');
                el.textContent = url;
            }, 1000);
        }

        fetchDevices();
        setInterval(fetchDevices, 2000);
    </script>
</body>
</html>'''
        body = html.encode('utf-8')
        self.send_response(200)
        self.send_header('Content-Type', 'text/html')
        self.send_header('Content-Length', len(body))
        self.end_headers()
        self.wfile.write(body)


def main():
    global portal

    config_file = sys.argv[1] if len(sys.argv) > 1 else CONFIG_FILE
    portal = Portal(config_file)

    server = http.server.HTTPServer(('0.0.0.0', HTTP_PORT), RequestHandler)
    log.info(f"Portal started on http://0.0.0.0:{HTTP_PORT}")
    log.info(f"Host IP: {portal.host_ip}")

    try:
        server.serve_forever()
    except KeyboardInterrupt:
        log.info("Shutting down...")
        server.shutdown()


if __name__ == '__main__':
    main()
