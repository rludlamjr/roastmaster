"""Test serial communication with the Kaleido roaster.

Sends commands in the correct Kaleido protocol format: {[TAG]}\n
Tests 57600 baud (Kaleido default) with 8N1 serial settings.
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
        ser = serial.Serial(PORT, BAUD, timeout=2, parity=serial.PARITY_NONE, **cfg)
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

        # Send PI command in Kaleido protocol format
        cmd = b"{[PI]}\n"
        print(f"  Sending: {cmd}")
        ser.write(cmd)
        time.sleep(1)
        data = ser.read(ser.in_waiting or 1)
        if data:
            print(f"  PI response: {data}")
        else:
            print("  no response to PI")

        # Try RD A0 command
        cmd = b"{[RD A0]}\n"
        print(f"  Sending: {cmd}")
        ser.write(cmd)
        time.sleep(1)
        data = ser.read(ser.in_waiting or 1)
        if data:
            print(f"  RD response: {data}")
        else:
            print("  no response to RD")

        ser.close()
        time.sleep(0.5)
    except Exception as e:
        print(f"  error: {e}")

print("\n--- Done ---")
