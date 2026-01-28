#!/bin/bash
# Check USB/IP status - which devices are attached to VM
source /etc/usbip/vm.conf 2>/dev/null

echo "=== Pi USB Devices ==="
/usr/sbin/usbip list -l 2>/dev/null | grep -E "busid|^\s+\w"

if [ -n "$VM_HOST" ]; then
    echo ""
    echo "=== VM Attached ($VM_HOST) ==="
    ssh -o ConnectTimeout=5 -o BatchMode=yes "$VM_USER@$VM_HOST" \
        "sudo /usr/sbin/usbip port 2>/dev/null" 2>/dev/null || echo "Cannot reach VM"
fi
