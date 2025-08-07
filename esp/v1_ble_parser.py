# v1_ble_parser.py
# Description: Scans, connects, and then continuously parses and displays
# the real-time status from a Valentine One using a structured class-based approach.

import asyncio
from bleak import BleakScanner, BleakClient
from bleak.exc import BleakError

# --- Bluetooth UUIDs ---
V1_LE_SERVICE_UUID = "92A0AFF4-9E05-11E2-AA59-F23C91AEC05E"
NOTIFY_CHAR_UUID = "92A0B2CE-9E05-11E2-AA59-F23C91AEC05E"
WRITE_CHAR_UUID = "92A0B6D4-9E05-11E2-AA59-F23C91AEC05E"

# --- ESP Packet Classes ---

class ESPPacket:
    """Base class for all ESP packets. Handles parsing the common header."""
    def __init__(self, raw_data: bytes):
        self.raw_data = raw_data
        self.is_valid = self._validate()

    def _validate(self):
        """Basic validation for packet structure."""
        if len(self.raw_data) < 6: return False
        if self.raw_data[0] != 0xAA or self.raw_data[-1] != 0xAB: return False
        return True

    @property
    def destination_id(self) -> int:
        return self.raw_data[1] & 0x0F

    @property
    def origin_id(self) -> int:
        return self.raw_data[2] & 0x0F

    @property
    def packet_id(self) -> int:
        return self.raw_data[3]

    @property
    def payload_length(self) -> int:
        return self.raw_data[4]

    @property
    def payload(self) -> bytes:
        # Checksum packets have payload length that includes the checksum byte
        if self.is_checksum_v1():
            # Payload is between header (5 bytes) and checksum+EOF (2 bytes)
            return self.raw_data[5:-2]
        else:
            # Payload is between header (5 bytes) and EOF (1 byte)
            return self.raw_data[5:-1]

    def is_checksum_v1(self) -> bool:
        """Determines if the packet is from a checksum-enabled V1."""
        return self.origin_id == 0x0A

    def is_checksum_valid(self) -> bool:
        """Validates the checksum if the packet is from a checksum V1."""
        if not self.is_checksum_v1():
            return True # Non-checksum packets are considered valid
        
        if len(self.raw_data) < 7: return False # Not long enough for checksum
        
        # Sum all bytes except the last two (checksum and EOF)
        calculated_sum = sum(self.raw_data[:-2]) & 0xFF
        received_checksum = self.raw_data[-2]
        
        return calculated_sum == received_checksum

    def __str__(self):
        return f"Packet(ID=0x{self.packet_id:02X}, Dest=0x{self.destination_id:02X}, Origin=0x{self.origin_id:02X})"

class InfDisplayData(ESPPacket):
    """Parses the infDisplayData packet (ID 0x31)."""
    
    # Constants for payload indices
    _BOGEY_COUNTER_1_IDX = 0
    _AUX_0_IDX = 5
    _BAND_ARROW_1_IDX = 3

    def __init__(self, raw_data: bytes):
        super().__init__(raw_data)
        # Further validation specific to this packet type
        if self.packet_id != 0x31:
            self.is_valid = False

    @property
    def aux0(self) -> int:
        return self.payload[self._AUX_0_IDX]

    def is_system_status_active(self) -> bool:
        return (self.aux0 & 0x04) != 0

    def has_active_alerts(self) -> bool:
        band_arrow_byte = self.payload[self._BAND_ARROW_1_IDX]
        # An alert is active if any arrow is lit
        is_front = (band_arrow_byte & 0x20) != 0
        is_side = (band_arrow_byte & 0x40) != 0
        is_rear = (band_arrow_byte & 0x80) != 0
        return self.is_system_status_active() and (is_front or is_side or is_rear)

    def get_mode(self) -> str:
        if self.has_active_alerts():
            return "Alerting"
        
        bogey_counter_byte = self.payload[self._BOGEY_COUNTER_1_IDX] & 0x7F
        modes = {
            0x77: "All Bogeys", 0x39: "Custom (C)", 0x3E: "Euro (U)",
            0x18: "Logic (l)", 0x1C: "Euro (u)", 0x58: "Custom (c)",
            0x38: "Adv. Logic (L)"
        }
        return modes.get(bogey_counter_byte, "Unknown")

    def __str__(self):
        """Provides a user-friendly summary of the V1's state."""
        if not self.is_valid:
            return "Invalid InfDisplayData Packet"
        
        status = f"V1 Status | Mode: {self.get_mode():<12} | "
        status += f"Alerts: {'YES' if self.has_active_alerts() else 'No'} | "
        status += f"System: {'Active' if self.is_system_status_active() else 'Inactive'}"
        return status

# --- Packet Factory ---
def packet_factory(raw_data: bytes) -> ESPPacket:
    """
    Takes raw bytes and returns the appropriate specialized ESPPacket object.
    """
    if len(raw_data) < 4:
        return ESPPacket(raw_data) # Return a base packet for invalid data
        
    packet_id = raw_data[3]
    
    if packet_id == 0x31:
        return InfDisplayData(raw_data)
    # Add more 'elif' conditions here for other packet types like respVersion, etc.
    else:
        # For any other packet, just return the base class for now
        return ESPPacket(raw_data)

# --- Main Application Logic ---

def notification_handler(sender, data: bytearray):
    """Callback that receives data, parses it, and prints the result."""
    packet = packet_factory(bytes(data))
    
    if packet.is_valid and packet.is_checksum_valid():
        # The __str__ method of the specific class (e.g., InfDisplayData) is called here.
        print(packet)
    else:
        print(f"Invalid or Corrupt Packet Received: {data.hex().upper()}")

async def scan_for_v1():
    """Scans for a V1 BLE device and returns it."""
    print("Scanning for Valentine One...")
    devices = await BleakScanner.discover(
        service_uuids=[V1_LE_SERVICE_UUID], timeout=10.0
    )
    if devices:
        device = devices[0]
        print(f"--- V1 Found! Address: {device.address} ---")
    else:
        print("Scan finished. No V1 device found.")
    return device

async def run_v1_session(device):
    """Connects and listens for packets indefinitely."""
    print(f"\nConnecting to {device.address}...")
    async with BleakClient(device) as client:
        print("Connected! Subscribing to notifications...")
        await client.start_notify(NOTIFY_CHAR_UUID, notification_handler)
        
        print("Listening for V1 data... (Press Ctrl+C to stop)")
        # Keep the connection alive forever until the user stops the script
        while True:
            await asyncio.sleep(1)

async def main():
    """Main function to orchestrate the entire process."""
    v1_device = await scan_for_v1()
    if v1_device:
        await run_v1_session(v1_device)
    print("\nScript finished.")

if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        print("\nProgram stopped by user.")
    except BleakError as e:
        print(f"A Bluetooth error occurred: {e}")