#!/bin/bash
# Notify VM of all USB devices on Pi boot
source /etc/usbip/vm.conf 2>/dev/null || exit 0

sleep 5  # Wait for network and devices to settle

# Bind all devices first
/usr/local/bin/usbip-bind-all.sh

# Notify VM of each bound device
for busid in $(/usr/sbin/usbip list -l 2>/dev/null | grep -oP "busid\s+\K[0-9]+-[0-9]+(\.[0-9]+)*"); do
    # Skip ethernet adapters
    if /usr/sbin/usbip list -l 2>/dev/null | grep -A1 "$busid" | grep -qi "ethernet"; then
        continue
    fi
    /usr/local/bin/notify-vm.sh boot "$busid" &
done
wait
