#!/bin/bash
# Start the CONAR 255 app inside a minimal X server
# xinit runs as root for console access; drop to the app user here
# Placeholders are filled in by setup-pi.sh
exec sudo -u __USER__ __HOME__/.local/bin/uv run --project __APP_DIR__ roastmaster --sim --gpio
