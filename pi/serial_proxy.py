#!/usr/bin/env python3
"""
Serial Proxy with Logging

A proxy that:
1. Connects to a serial device
2. Logs all traffic with timestamps
3. Provides RFC2217-compatible access for clients (esptool, pyserial)
4. Supports DTR/RTS for ESP32 bootloader reset

Usage:
    serial_proxy.py -p 4001 -l /var/log/serial/ /dev/ttyUSB0
"""

import argparse
import os
import sys
import time
import socket
import select
import threading
import signal
import serial
from datetime import datetime
from pathlib import Path

# RFC2217 constants
IAC = 255   # Interpret As Command
DONT = 254
DO = 253
WONT = 252
WILL = 251
SB = 250    # Subnegotiation Begin
SE = 240    # Subnegotiation End
COM_PORT_OPTION = 44

# RFC2217 subnegotiation commands
SET_BAUDRATE = 1
SET_DATASIZE = 2
SET_PARITY = 3
SET_STOPSIZE = 4
SET_CONTROL = 5
SET_LINESTATE_MASK = 10
SET_MODEMSTATE_MASK = 11
SET_DTR = 8
SET_RTS = 11

class SerialLogger:
    """Logs serial data with timestamps"""

    def __init__(self, log_dir, device_name, device_info=None):
        self.log_dir = Path(log_dir)
        self.log_dir.mkdir(parents=True, exist_ok=True)

        # Build descriptive name from device info
        if device_info:
            product = device_info.get('product', '').replace(' ', '_').replace('/', '_')[:20]
            serial = device_info.get('serial', '')[:10]
            if product and serial:
                self.device_name = f"{product}_{serial}"
            elif product:
                self.device_name = product
            elif serial:
                self.device_name = serial
            else:
                self.device_name = device_name.replace('/', '_').replace('dev_', '')
        else:
            self.device_name = device_name.replace('/', '_').replace('dev_', '')

        self.log_file = None
        self.current_date = None
        self._rotate_log()

    def _rotate_log(self):
        """Create new log file for current date"""
        today = datetime.now().strftime('%Y-%m-%d')
        if today != self.current_date:
            if self.log_file:
                self.log_file.close()
            self.current_date = today
            log_path = self.log_dir / f"{self.device_name}_{today}.log"
            self.log_file = open(log_path, 'a', buffering=1)  # Line buffered
            self.log(f"=== Log opened for {self.device_name} ===")

    def log(self, message, direction='INFO'):
        """Log a message with timestamp"""
        self._rotate_log()
        timestamp = datetime.now().strftime('%Y-%m-%d %H:%M:%S.%f')[:-3]
        self.log_file.write(f"[{timestamp}] [{direction}] {message}\n")

    def log_data(self, data, direction='RX'):
        """Log binary data, converting to readable format"""
        self._rotate_log()
        timestamp = datetime.now().strftime('%Y-%m-%d %H:%M:%S.%f')[:-3]

        # Try to decode as text, fall back to hex
        try:
            text = data.decode('utf-8', errors='replace')
            # Remove or escape control characters except newline
            printable = ''.join(c if c.isprintable() or c in '\n\r\t' else f'\\x{ord(c):02x}' for c in text)
            for line in printable.split('\n'):
                if line.strip():
                    self.log_file.write(f"[{timestamp}] [{direction}] {line.rstrip()}\n")
        except:
            # Fall back to hex dump
            hex_str = data.hex()
            self.log_file.write(f"[{timestamp}] [{direction}] HEX: {hex_str}\n")

    def close(self):
        if self.log_file:
            self.log("=== Log closed ===")
            self.log_file.close()


class RFC2217Proxy:
    """RFC2217 proxy with logging"""

    def __init__(self, device, port, baudrate=115200, log_dir='/var/log/serial'):
        self.device = device
        self.port = port
        self.baudrate = baudrate
        self.serial = None
        self.server_socket = None
        self.client_socket = None
        self.running = False

        # Get device info for better log naming
        device_info = self._get_device_info(device)
        self.logger = SerialLogger(log_dir, os.path.basename(device), device_info)

    def _get_device_info(self, device):
        """Read device info from sysfs"""
        info = {}
        tty_name = os.path.basename(device)
        sysfs_path = f"/sys/class/tty/{tty_name}/device"

        if not os.path.exists(sysfs_path):
            return info

        try:
            device_path = os.path.realpath(sysfs_path)
            # Walk up to find USB device attributes
            for _ in range(5):
                device_path = os.path.dirname(device_path)
                product_file = os.path.join(device_path, 'product')
                if os.path.exists(product_file):
                    break

            for attr in ['product', 'serial', 'manufacturer']:
                attr_file = os.path.join(device_path, attr)
                if os.path.exists(attr_file):
                    try:
                        with open(attr_file) as f:
                            info[attr] = f.read().strip()
                    except:
                        pass
        except:
            pass

        return info

    def open_serial(self):
        """Open serial port"""
        self.serial = serial.Serial(
            self.device,
            baudrate=self.baudrate,
            timeout=0.1,
            write_timeout=1
        )
        self.logger.log(f"Opened {self.device} at {self.baudrate} baud")

    def close_serial(self):
        """Close serial port"""
        if self.serial and self.serial.is_open:
            self.serial.close()
            self.logger.log(f"Closed {self.device}")

    def start_server(self):
        """Start TCP server"""
        self.server_socket = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        self.server_socket.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        self.server_socket.bind(('0.0.0.0', self.port))
        self.server_socket.listen(1)
        self.server_socket.setblocking(False)
        self.logger.log(f"Listening on port {self.port}")
        print(f"Serial proxy for {self.device} listening on port {self.port}")

    def handle_rfc2217(self, data):
        """Handle RFC2217 commands from client"""
        i = 0
        output = bytearray()

        while i < len(data):
            if data[i] == IAC and i + 1 < len(data):
                cmd = data[i + 1]

                if cmd == IAC:
                    # Escaped IAC, pass through
                    output.append(IAC)
                    i += 2
                    continue

                if cmd == SB and i + 2 < len(data):
                    # Subnegotiation
                    if data[i + 2] == COM_PORT_OPTION:
                        # Find SE
                        se_idx = data.find(bytes([IAC, SE]), i + 3)
                        if se_idx != -1:
                            subcmd = data[i + 3] if i + 3 < se_idx else 0
                            subdata = data[i + 4:se_idx]
                            self._handle_com_port_option(subcmd, subdata)
                            i = se_idx + 2
                            continue
                    i += 2
                    continue

                if cmd in (DO, DONT, WILL, WONT):
                    # Telnet option negotiation
                    if i + 2 < len(data):
                        opt = data[i + 2]
                        if cmd == DO and opt == COM_PORT_OPTION:
                            # Client wants us to do COM-PORT
                            self._send_telnet(WILL, COM_PORT_OPTION)
                        elif cmd == WILL and opt == COM_PORT_OPTION:
                            # Client will do COM-PORT
                            self._send_telnet(DO, COM_PORT_OPTION)
                        i += 3
                        continue

                i += 2
            else:
                output.append(data[i])
                i += 1

        return bytes(output)

    def _handle_com_port_option(self, subcmd, data):
        """Handle COM-PORT-OPTION subnegotiation"""
        try:
            # Response command is subcmd + 100
            resp_cmd = subcmd + 100

            if subcmd == SET_BAUDRATE and len(data) >= 4:
                baudrate = int.from_bytes(data[:4], 'big')
                if baudrate > 0:
                    self.serial.baudrate = baudrate
                    self.logger.log(f"Baudrate changed to {baudrate}")
                # Send acknowledgment with actual baudrate
                self._send_com_port_option(resp_cmd, self.serial.baudrate.to_bytes(4, 'big'))

            elif subcmd == SET_DATASIZE and len(data) >= 1:
                datasize = data[0]
                if datasize >= 5 and datasize <= 8:
                    self.serial.bytesize = datasize
                    self.logger.log(f"Data size changed to {datasize}")
                self._send_com_port_option(resp_cmd, bytes([self.serial.bytesize]))

            elif subcmd == SET_PARITY and len(data) >= 1:
                parity_map = {1: 'N', 2: 'O', 3: 'E', 4: 'M', 5: 'S'}
                parity_rmap = {'N': 1, 'O': 2, 'E': 3, 'M': 4, 'S': 5}
                parity = parity_map.get(data[0], 'N')
                self.serial.parity = parity
                self.logger.log(f"Parity changed to {parity}")
                self._send_com_port_option(resp_cmd, bytes([parity_rmap.get(self.serial.parity, 1)]))

            elif subcmd == SET_STOPSIZE and len(data) >= 1:
                stopbits_map = {1: 1, 2: 2, 3: 1.5}
                stopbits_rmap = {1: 1, 1.5: 3, 2: 2}
                stopbits = stopbits_map.get(data[0], 1)
                self.serial.stopbits = stopbits
                self.logger.log(f"Stop bits changed to {stopbits}")
                self._send_com_port_option(resp_cmd, bytes([stopbits_rmap.get(int(self.serial.stopbits), 1)]))

            elif subcmd == SET_CONTROL and len(data) >= 1:
                control = data[0]
                # DTR control: 8=ON, 9=OFF
                if control == 8:
                    self.serial.dtr = True
                    self.logger.log("DTR ON")
                    self._send_com_port_option(resp_cmd, bytes([8]))
                elif control == 9:
                    self.serial.dtr = False
                    self.logger.log("DTR OFF")
                    self._send_com_port_option(resp_cmd, bytes([9]))
                # RTS control: 11=ON, 12=OFF
                elif control == 11:
                    self.serial.rts = True
                    self.logger.log("RTS ON")
                    self._send_com_port_option(resp_cmd, bytes([11]))
                elif control == 12:
                    self.serial.rts = False
                    self.logger.log("RTS OFF")
                    self._send_com_port_option(resp_cmd, bytes([12]))
                else:
                    # Echo back for other control requests
                    self._send_com_port_option(resp_cmd, bytes([control]))

            elif subcmd == SET_LINESTATE_MASK:
                # Acknowledge linestate mask
                self._send_com_port_option(resp_cmd, data if data else bytes([0]))

            elif subcmd == SET_MODEMSTATE_MASK:
                # Acknowledge modemstate mask
                self._send_com_port_option(resp_cmd, data if data else bytes([0]))

            else:
                # Unknown command, try to acknowledge anyway
                self._send_com_port_option(resp_cmd, data if data else bytes([0]))

        except Exception as e:
            self.logger.log(f"Error handling COM-PORT option: {e}")

    def _send_telnet(self, cmd, opt):
        """Send telnet command to client"""
        if self.client_socket:
            try:
                self.client_socket.send(bytes([IAC, cmd, opt]))
            except:
                pass

    def _send_com_port_option(self, subcmd, data):
        """Send COM-PORT-OPTION subnegotiation response"""
        if self.client_socket:
            try:
                msg = bytes([IAC, SB, COM_PORT_OPTION, subcmd]) + data + bytes([IAC, SE])
                self.client_socket.send(msg)
            except:
                pass

    def run(self):
        """Main loop"""
        self.running = True
        self.open_serial()
        self.start_server()

        try:
            while self.running:
                # Build list of sockets to monitor
                read_list = [self.server_socket]
                if self.serial and self.serial.is_open:
                    read_list.append(self.serial)
                if self.client_socket:
                    read_list.append(self.client_socket)

                try:
                    readable, _, _ = select.select(read_list, [], [], 0.1)
                except (ValueError, OSError):
                    continue

                for sock in readable:
                    if sock == self.server_socket:
                        # New client connection
                        try:
                            if self.client_socket:
                                self.client_socket.close()
                                self.logger.log("Previous client disconnected (new connection)")

                            self.client_socket, addr = self.server_socket.accept()
                            self.client_socket.setblocking(False)
                            self.logger.log(f"Client connected from {addr[0]}:{addr[1]}")
                        except:
                            pass

                    elif sock == self.client_socket:
                        # Data from client
                        try:
                            data = self.client_socket.recv(4096)
                            if data:
                                # Process RFC2217 commands, get raw data
                                raw_data = self.handle_rfc2217(data)
                                if raw_data:
                                    self.serial.write(raw_data)
                                    self.logger.log_data(raw_data, 'TX')
                            else:
                                # Client disconnected
                                self.logger.log("Client disconnected")
                                self.client_socket.close()
                                self.client_socket = None
                        except (ConnectionResetError, BrokenPipeError):
                            self.logger.log("Client connection reset")
                            self.client_socket.close()
                            self.client_socket = None
                        except BlockingIOError:
                            pass

                    elif sock == self.serial:
                        # Data from serial
                        try:
                            data = self.serial.read(self.serial.in_waiting or 1)
                            if data:
                                self.logger.log_data(data, 'RX')
                                if self.client_socket:
                                    try:
                                        self.client_socket.send(data)
                                    except:
                                        pass
                        except:
                            pass

                # Also check for serial data even if not in select
                if self.serial and self.serial.is_open and self.serial not in readable:
                    try:
                        if self.serial.in_waiting:
                            data = self.serial.read(self.serial.in_waiting)
                            if data:
                                self.logger.log_data(data, 'RX')
                                if self.client_socket:
                                    try:
                                        self.client_socket.send(data)
                                    except:
                                        pass
                    except:
                        pass

        except KeyboardInterrupt:
            pass
        finally:
            self.stop()

    def stop(self):
        """Stop the proxy"""
        self.running = False
        self.logger.log("Shutting down")

        if self.client_socket:
            try:
                self.client_socket.close()
            except:
                pass

        if self.server_socket:
            try:
                self.server_socket.close()
            except:
                pass

        self.close_serial()
        self.logger.close()


def main():
    parser = argparse.ArgumentParser(description='Serial proxy with logging')
    parser.add_argument('device', help='Serial device (e.g., /dev/ttyUSB0)')
    parser.add_argument('-p', '--port', type=int, default=4001, help='TCP port (default: 4001)')
    parser.add_argument('-b', '--baudrate', type=int, default=115200, help='Baud rate (default: 115200)')
    parser.add_argument('-l', '--log-dir', default='/var/log/serial', help='Log directory')
    args = parser.parse_args()

    proxy = RFC2217Proxy(
        device=args.device,
        port=args.port,
        baudrate=args.baudrate,
        log_dir=args.log_dir
    )

    def signal_handler(sig, frame):
        print("\nShutting down...")
        proxy.stop()
        sys.exit(0)

    signal.signal(signal.SIGINT, signal_handler)
    signal.signal(signal.SIGTERM, signal_handler)

    proxy.run()


if __name__ == '__main__':
    main()
