"""Test serial communication with the Kaleido roaster at multiple baud rates."""

import serial
import time

PORT = "/dev/ttyUSB0"

for baud in [115200, 9600, 19200, 38400, 57600]:
    print(f"--- Testing {baud} baud ---")
    try:
        ser = serial.Serial(PORT, baud, timeout=2)
        time.sleep(0.5)
        ser.reset_input_buffer()
        ser.write(b"PI\r\n")
        time.sleep(1)
        data = ser.read(ser.in_waiting or 1)
        if data:
            print(f"  GOT RESPONSE: {data}")
        else:
            print(f"  no response")
        ser.close()
        time.sleep(0.5)
    except Exception as e:
        print(f"  error: {e}")

print("--- Done ---")
