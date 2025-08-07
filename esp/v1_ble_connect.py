# v1_ble_connect.py
# Description: A complete script to automatically scan for, connect to,
# discover the bus type (checksum/non-checksum), and interact with a
# Valentine One Gen2 or V1connection LE.

import asyncio
from bleak import BleakScanner, BleakClient
from bleak.exc import BleakError

# These UUIDs are critical for communication.
V1_LE_SERVICE_UUID = "92A0AFF4-9E05-11E2-AA59-F23C91AEC05E"
NOTIFY_CHAR_UUID = "92A0B2CE-9E05-11E2-AA59-F23C91AEC05E"
WRITE_CHAR_UUID = "92A0B6D4-9E05-11E2-AA59-F23C91AEC05E"

# --- Global state variables ---
v1_device_id = None
discovery_complete = asyncio.Event()

def notification_handler(sender, data: bytearray):
    """Callback for received data. This is where we discover the V1's identity."""
    global v1_device_id
    
    if not discovery_complete.is_set():
        # Packet structure: SOF, DI, OI, PI, PL, ...
        if len(data) < 4:
            return # Not a valid ESP packet
            
        packet_id = data[3]
        if packet_id == 0x31: # infDisplayData
            originator_byte = data[2]
            device_id = originator_byte & 0x0F
            
            if device_id in [0x09, 0x0A]: # It's a V1 Gen1
                v1_device_id = device_id
                print(f"\n--- V1 Bus Type Discovered ---")
                print(f"  Received infDisplayData from Originator: 0x{originator_byte:02X}")
                print(f"  V1 Device ID is: 0x{v1_device_id:02X}")
                print(f"  Mode: {'NON-CHECKSUM' if v1_device_id == 0x09 else 'CHECKSUM'}")
                print(f"------------------------------")
                discovery_complete.set()
    else:
        print(f"<- RX: {data.hex().upper()}")

async def scan_for_v1():
    """Scans for a V1 BLE device and returns the first one found."""
    print("Scanning for Valentine One LE / Gen2 for 10 seconds...")

    devices = await BleakScanner.discover(
        service_uuids=[V1_LE_SERVICE_UUID], timeout=10.0
    )
    
    if devices:
        device = devices[0]
        print(f"--- V1 Found! ---")
        print(f"  Name:    {device.name or 'N/A'}")
        print(f"  Address: {device.address}")
        print(f"-----------------")
        return device
    else:
        print("\nScan finished. No Valentine One device found.")
        print("Please ensure it's powered on and in range.")
        return None

async def run_v1_session(device):
    """Connects, discovers bus type, sends a command, and listens."""
    print(f"\nAttempting to connect to {device.address}...")
    
    async with BleakClient(device) as client:
        if not client.is_connected:
            print(f"Failed to connect to {device.address}")
            return

        print(f"Successfully connected to {device.name or device.address}!")
        
        # Reset the discovery event for this new session
        discovery_complete.clear()
        
        await client.start_notify(NOTIFY_CHAR_UUID, notification_handler)
        print("Subscribed to notifications. Listening to determine bus type...")
        
        try:
            await asyncio.wait_for(discovery_complete.wait(), timeout=5.0)
        except asyncio.TimeoutError:
            print("Discovery failed: Did not receive infDisplayData from V1.")
            return

        print("Listening for responses for 20 seconds...")
        await asyncio.sleep(20)

async def main():
    """Main function to orchestrate the entire process."""
    v1_device = await scan_for_v1()
    if v1_device:
        try:
            await run_v1_session(v1_device)
        except BleakError as e:
            print(f"A Bluetooth error occurred: {e}")
        except Exception as e:
            print(f"An unexpected error occurred: {e}")
    
    print("\nScript finished.")

if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        print("\nProgram stopped by user.")