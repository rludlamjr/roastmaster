"""Test serial communication with the Kaleido roaster at 57600 baud.

Tries different flow control and DTR/RTS settings.
"""

import serial
import time

PORT = "/dev/ttyUSB0"
BAUD = 57600

configs = [
    {"dsrdtr": False, "rtscts": False, "dtr": None, "rts": None, "desc": "defaults (no flow control)"},
    {"dsrdtr": False, "rtscts": False, "dtr": True, "rts": True, "desc": "DTR=high, RTS=high"},
    {"dsrdtr": False, "rtscts": False, "dtr": False, "rts": False, "desc": "DTR=low, RTS=low"},
    {"dsrdtr": True, "rtscts": False, "dtr": None, "rts": None, "desc": "DSR/DTR flow control"},
    {"dsrdtr": False, "rtscts": True, "dtr": None, "rts": None, "desc": "RTS/CTS flow control"},
]

for cfg in configs:
    desc = cfg.pop("desc")
    dtr = cfg.pop("dtr")
    rts = cfg.pop("rts")
    print(f"\n=== {desc} ===")
    try:
        ser = serial.Serial(PORT, BAUD, timeout=2, **cfg)
        if dtr is not None:
            ser.dtr = dtr
        if rts is not None:
            ser.rts = rts
        time.sleep(1)
        ser.reset_input_buffer()

        # Listen passively
        print("  Listening 3 sec...")
        time.sleep(3)
        data = ser.read(ser.in_waiting or 1)
        if data:
            print(f"  PASSIVE: {data}")

        # Send PI command
        ser.write(b"PI\r\n")
        time.sleep(1)
        data = ser.read(ser.in_waiting or 1)
        if data:
            print(f"  PI response: {data}")
        else:
            print(f"  no response")

        ser.close()
        time.sleep(0.5)
    except Exception as e:
        print(f"  error: {e}")

print("\n--- Done ---")
