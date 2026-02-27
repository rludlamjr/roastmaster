#!/bin/bash
# CONAR Model 255 — Raspberry Pi deployment setup
# Run this on the Pi after cloning the repo to ~/conar255
#
# Usage:  sudo bash ~/conar255/deploy/setup-pi.sh
#
set -euo pipefail

# Auto-detect the user who invoked sudo and their home directory
PI_USER="${SUDO_USER:-pi}"
PI_HOME=$(eval echo "~$PI_USER")
APP_DIR="$PI_HOME/conar255"
SERVICE_TEMPLATE="$APP_DIR/deploy/conar255.service"

if [ "$(id -u)" -ne 0 ]; then
    echo "ERROR: Run this script with sudo"
    exit 1
fi

if [ ! -f "$SERVICE_TEMPLATE" ]; then
    echo "ERROR: Service file not found at $SERVICE_TEMPLATE"
    echo "       Make sure the repo is cloned to ~/conar255"
    exit 1
fi

echo "=== CONAR 255 A.R.S. — Pi Setup ==="
echo "  User: $PI_USER"
echo "  Home: $PI_HOME"
echo "  App:  $APP_DIR"
echo ""

# 1. Ensure user is in the right groups
echo "[1/6] Adding $PI_USER to device groups..."
usermod -aG video,input,dialout,render "$PI_USER" 2>/dev/null || true

# 2. Install the systemd service (fill in user/path placeholders)
echo "[2/6] Installing systemd service..."
sed -e "s|__USER__|$PI_USER|g" \
    -e "s|__HOME__|$PI_HOME|g" \
    -e "s|__APP_DIR__|$APP_DIR|g" \
    "$SERVICE_TEMPLATE" > /etc/systemd/system/conar255.service
systemctl daemon-reload

# 3. Enable the service to start on boot
echo "[3/6] Enabling service for boot..."
systemctl enable conar255.service

# 4. Quiet the boot process — hide kernel/systemd text
echo "[4/6] Configuring quiet boot..."
CMDLINE="/boot/firmware/cmdline.txt"
if [ ! -f "$CMDLINE" ]; then
    CMDLINE="/boot/cmdline.txt"
fi

if [ -f "$CMDLINE" ]; then
    # Add quiet + splash options if not already present
    if ! grep -q "quiet" "$CMDLINE"; then
        sed -i 's/$/ quiet loglevel=0 vt.global_cursor_default=0/' "$CMDLINE"
        echo "  Updated $CMDLINE"
    else
        echo "  $CMDLINE already configured"
    fi
else
    echo "  WARNING: Could not find cmdline.txt"
fi

# 5. Disable unnecessary services to speed up boot
echo "[5/6] Disabling unnecessary services..."
DISABLE_SERVICES=(
    bluetooth
    hciuart
    avahi-daemon
    triggerhappy
    raspi-config
    ModemManager
)
for svc in "${DISABLE_SERVICES[@]}"; do
    if systemctl is-enabled "$svc" &>/dev/null; then
        systemctl disable "$svc" 2>/dev/null && echo "  Disabled $svc" || true
    fi
done

# 6. Disable console getty on tty1 (our app owns the screen)
echo "[6/6] Disabling console on tty1..."
systemctl disable getty@tty1 2>/dev/null || true

echo ""
echo "=== Setup complete ==="
echo ""
echo "Next steps:"
echo "  1. Make sure 'uv sync' has been run in $APP_DIR"
echo "  2. Test manually:  sudo systemctl start conar255"
echo "  3. Check logs:     journalctl -u conar255 -f"
echo "  4. Reboot to test: sudo reboot"
echo ""
echo "To undo (restore normal boot):"
echo "  sudo systemctl disable conar255"
echo "  sudo systemctl enable getty@tty1"
echo ""
