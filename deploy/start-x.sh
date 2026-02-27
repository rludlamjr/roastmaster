#!/bin/bash
# Start the CONAR 255 app inside a minimal X server
# Placeholders are filled in by setup-pi.sh
exec __HOME__/.local/bin/uv run --project __APP_DIR__ roastmaster --sim
