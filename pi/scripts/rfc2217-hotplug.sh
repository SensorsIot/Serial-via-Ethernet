#!/bin/bash
# Handle USB serial device hotplug events
# Called by udev rules when devices are added/removed

ACTION="$1"
DEVNAME="$2"
PORTAL_URL="http://localhost:8080"

log() {
    logger -t "rfc2217-hotplug" "$1"
}

case "$ACTION" in
    add)
        log "Device added: $DEVNAME"
        # Wait for device to be ready
        sleep 1
        # Start RFC2217 server via portal API
        curl -s -X POST "$PORTAL_URL/api/start" \
            -H "Content-Type: application/json" \
            -d "{\"tty\": \"$DEVNAME\"}" > /dev/null 2>&1
        ;;
    remove)
        log "Device removed: $DEVNAME"
        # Server will exit automatically when device disappears
        # Optionally notify portal to clean up
        curl -s -X POST "$PORTAL_URL/api/stop" \
            -H "Content-Type: application/json" \
            -d "{\"tty\": \"$DEVNAME\"}" > /dev/null 2>&1
        ;;
esac
