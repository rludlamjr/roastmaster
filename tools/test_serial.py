"""Test serial communication with the Kaleido roaster.

Tries multiple baud rates, command formats, and also just listens
for any data the roaster sends on its own.
"""

import serial
import time

PORT = "/dev/ttyUSB0"

# Different command formats to try
COMMANDS = [
    (b"PI\r\n", "PI with CRLF"),
    (b"PI\r", "PI with CR only"),
    (b"PI\n", "PI with LF only"),
    (b"RD\r\n", "RD with CRLF"),
    (b"RD,A0\r\n", "RD,A0 with CRLF"),
]

for baud in [115200, 9600, 19200, 38400, 57600]:
    print(f"\n=== {baud} baud ===")
    try:
        ser = serial.Serial(PORT, baud, timeout=2)
        time.sleep(0.5)
        ser.reset_input_buffer()

        # First just listen for 3 seconds (roaster may broadcast)
        print("  Listening for unsolicited data (3 sec)...")
        time.sleep(3)
        data = ser.read(ser.in_waiting or 1)
        if data:
            print(f"  RECEIVED (passive): {data}")
        else:
            print(f"  nothing received passively")

        # Try each command format
        for cmd, desc in COMMANDS:
            ser.reset_input_buffer()
            ser.write(cmd)
            time.sleep(1)
            data = ser.read(ser.in_waiting or 1)
            if data:
                print(f"  {desc} -> GOT RESPONSE: {data}")
            else:
                print(f"  {desc} -> no response")

        ser.close()
        time.sleep(0.5)
    except Exception as e:
        print(f"  error: {e}")

print("\n--- Done ---")
print("If all tests show no response, check:")
print("  1. Is the roaster powered on and past its startup screen?")
print("  2. Try unplugging and replugging the USB cable")
print("  3. Check: ls -la /dev/ttyUSB* /dev/ttyACM*")
