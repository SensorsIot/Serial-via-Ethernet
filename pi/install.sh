#!/bin/bash
# Install RFC2217 Portal v3 on Raspberry Pi
set -e

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"

echo "=== Installing RFC2217 Portal v3 ==="

# Create directories
echo "Creating directories..."
sudo mkdir -p /etc/rfc2217
sudo mkdir -p /var/log/serial

# Install Python scripts
echo "Installing scripts..."
sudo cp "$SCRIPT_DIR/portal.py" /usr/local/bin/rfc2217-portal
sudo cp "$SCRIPT_DIR/serial_proxy.py" /usr/local/bin/serial_proxy.py
sudo cp "$SCRIPT_DIR/rfc2217-learn-slots" /usr/local/bin/rfc2217-learn-slots

sudo chmod +x /usr/local/bin/rfc2217-portal
sudo chmod +x /usr/local/bin/serial_proxy.py
sudo chmod +x /usr/local/bin/rfc2217-learn-slots

# Install udev notify script
echo "Installing udev notify script..."
sudo cp "$SCRIPT_DIR/scripts/rfc2217-udev-notify.sh" /usr/local/bin/rfc2217-udev-notify.sh
sudo chmod +x /usr/local/bin/rfc2217-udev-notify.sh

# Install config (don't overwrite existing)
if [ ! -f /etc/rfc2217/slots.json ]; then
    echo "Installing default config..."
    sudo cp "$SCRIPT_DIR/config/slots.json" /etc/rfc2217/slots.json
else
    echo "Config already exists, skipping..."
fi

# Install systemd services
echo "Installing systemd services..."
sudo cp "$SCRIPT_DIR/systemd/rfc2217-portal.service" /etc/systemd/system/

# Install udev rules
echo "Installing udev rules..."
sudo cp "$SCRIPT_DIR/udev/99-rfc2217-hotplug.rules" /etc/udev/rules.d/

# Reload systemd and udev
echo "Reloading systemd and udev..."
sudo systemctl daemon-reload
sudo udevadm control --reload-rules

# Enable and start portal service
echo "Enabling portal service..."
sudo systemctl enable rfc2217-portal
sudo systemctl restart rfc2217-portal

echo ""
echo "=== Installation complete ==="
echo ""
echo "Portal running at: http://$(hostname -I | awk '{print $1}'):8080"
echo ""
echo "To discover slot keys, plug in devices and run:"
echo "  rfc2217-learn-slots"
echo ""
echo "Then edit /etc/rfc2217/slots.json with your slot configuration."
