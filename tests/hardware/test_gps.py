# test_gps.py
# Description: Verifies the NEO-6M GPS module is sending data over UART.
# It reads NMEA sentences, parses them, and prints location data.

import serial
import pynmea2

# The default serial port for GPIO on Raspberry Pi 4/3/Zero W
SERIAL_PORT = "/dev/serial0"
BAUD_RATE = 9600

print(f"Attempting to read GPS data from {SERIAL_PORT} at {BAUD_RATE} baud.")
print("This will run forever. Press Ctrl+C to exit.")
print("Waiting for GPS fix... (This may take several minutes with a clear sky view)")

try:
    # Open the serial port
    with serial.Serial(SERIAL_PORT, baudrate=BAUD_RATE, timeout=1) as ser:
        while True:
            try:
                # Read one line of data
                line = ser.readline().decode('ascii', errors='replace')
                
                # We are only interested in GPGGA sentences for this test
                if line.startswith('$GPGGA'):
                    msg = pynmea2.parse(line)
                    
                    # gps_qual: 0=No Fix, 1=GPS Fix, 2=DGPS Fix
                    fix_status = "No Fix"
                    if msg.gps_qual > 0:
                        fix_status = f"Fix ({msg.gps_qual})"

                    print(f"Status: {fix_status} | "
                          f"Lat: {msg.latitude:.6f} | "
                          f"Lon: {msg.longitude:.6f} | "
                          f"Sats: {msg.num_sats} | "
                          f"Alt: {msg.altitude} {msg.altitude_units}")

            except pynmea2.ParseError as e:
                # This can happen with incomplete or corrupted data
                print(f"Parse error: {e}")
            except Exception as e:
                print(f"An unexpected error occurred: {e}")

except serial.SerialException as e:
    print(f"Error opening serial port: {e}")
    print("Please ensure the serial port is enabled and not used by another process.")
except KeyboardInterrupt:
    print("\nExiting GPS test.")