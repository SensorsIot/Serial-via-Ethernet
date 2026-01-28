# Proxmox VM Setup

## Prerequisites

```bash
sudo apt update
sudo apt install linux-image-amd64 usbip avahi-daemon
```

## Kernel Module

```bash
sudo modprobe vhci_hcd
echo "vhci_hcd" | sudo tee -a /etc/modules
```

## Installation

```bash
# Copy scripts
sudo cp scripts/* /usr/local/bin/
sudo chmod +x /usr/local/bin/*

# Install systemd service
sudo cp systemd/* /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl enable usb-boot-attach
```

## Sudoers Rule

Allow user to run usbip without password:

```bash
echo 'dev ALL=(root) NOPASSWD: /usr/sbin/usbip, /bin/fuser' | sudo tee /etc/sudoers.d/usbip
sudo chmod 440 /etc/sudoers.d/usbip
```

## Configuration

Create `/etc/usbip/pi.conf`:

```bash
sudo mkdir -p /etc/usbip
echo "DEFAULT_PI_HOST=<pi-ip-address>" | sudo tee /etc/usbip/pi.conf
```

## Verify

```bash
# Check attached devices
sudo usbip port

# Check serial devices
ls -la /dev/ttyUSB* /dev/ttyACM*
```
