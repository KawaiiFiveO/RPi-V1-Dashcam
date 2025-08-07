import asyncio
import struct
import logging
import sys
from enum import IntEnum
from typing import List, Optional, Callable, Dict, Type

from bleak import BleakClient, BleakScanner
from bleak.backends.device import BLEDevice

# --- Constants ---

# Bluetooth Service and Characteristic UUIDs for V1connection LE
V1_SERVICE_UUID = "92A0AFF4-9E05-11E2-AA59-F23C91AEC05E"
V1_WRITE_CHAR_UUID = "92A0B6D4-9E05-11E2-AA59-F23C91AEC05E"
V1_NOTIFY_CHAR_UUID = "92A0B2CE-9E05-11E2-AA59-F23C91AEC05E"

# ESP (EScort Serial Protocol) framing and address bytes
ESP_SOF = 0xAA  # Start of Frame
ESP_EOF = 0xAB  # End of Frame
DEST_BASE = 0xD0  # Destination address base
ORIG_BASE = 0xE0  # Origin address base

# Minimum V1 firmware version required for custom sweep support
MIN_SWEEP_FW_VERSION = 3.8950


class DeviceId(IntEnum):
    """ESP Device identifiers."""
    CONCEALED_DISPLAY = 0x00
    REMOTE_AUDIO = 0x01
    SAVVY = 0x02
    V1CONNECTION = 0x06
    GENERAL_BROADCAST = 0x08
    VALENTINE_ONE_NO_CHECKSUM = 0x09
    VALENTINE_ONE = 0x0A
    VALENTINE_ONE_LEGACY = 0x98
    UNKNOWN_DEVICE = 0x99


class PacketId(IntEnum):
    """ESP Packet identifiers."""
    # Requests
    REQVERSION = 0x01
    REQALLSWEEPDEFINITIONS = 0x16
    REQMAXSWEEPINDEX = 0x19
    REQSTARTALERTDATA = 0x41
    REQSTOPALERTDATA = 0x42

    # Responses
    RESPVERSION = 0x02
    RESPSWEEPDEFINITION = 0x17
    RESPMAXSWEEPINDEX = 0x20
    RESPALERTDATA = 0x43

    # Infomational
    INFDISPLAYDATA = 0x31

    # Errors
    RESPUNSUPPORTEDPACKET = 0x64
    RESPREQUESTNOTPROCESSED = 0x65
    RESPDATAERROR = 0x67

    # Internal Use
    UNKNOWNPACKETTYPE = 0x100


# --- ESP Packet Classes ---

class ESPPacket:
    """Base class for all ESP packets, handling common header parsing."""

    def __init__(self, raw_data: bytes, v1_type: DeviceId):
        """
        Parses the common header of an ESP packet.

        Args:
            raw_data: The complete raw byte sequence of the packet.
            v1_type: The type of V1 device, used to determine checksum presence.
        """
        self.raw_data = raw_data
        self.v1_type = v1_type

        # Extract destination and origin IDs from the address bytes
        self.destination = DeviceId(raw_data[1] & 0x0F)
        self.origin = DeviceId(raw_data[2] & 0x0F)

        self.packet_id = PacketId(raw_data[3])
        payload_len = raw_data[4]

        # V1s with checksum support include the checksum byte in the payload length.
        # We must subtract one to get the actual payload data length.
        if self.v1_type == DeviceId.VALENTINE_ONE and payload_len > 0:
            payload_len -= 1

        self.payload = raw_data[5:5 + payload_len]

    def __repr__(self) -> str:
        """Provides a developer-friendly representation of the packet."""
        return (
            f"<{self.__class__.__name__} "
            f"Dst={self.destination.name}, Org={self.origin.name}, "
            f"Pay={self.payload.hex().upper()}>"
        )


class InfDisplayData(ESPPacket):
    """Parses and provides access to V1 display data from an infDisplayData packet."""

    # Mapping of 7-segment display byte codes to characters.
    SEVEN_SEG_MAP = {
        0x3f: "0", 0x06: "1", 0x5B: "2", 0x4F: "3", 0x66: "4", 0x6D: "5",
        0x7D: "6", 0x07: "7", 0x7F: "8", 0x6F: "9", 0x77: "A", 0x7C: "b",
        0x39: "C", 0x5E: "d", 0x79: "E", 0x71: "F", 0x38: "L", 0x1E: "J",
        0x58: "c", 0x3E: "U", 0x1C: "u"
    }

    def _seven_seg_to_char(self, byte_val: int) -> str:
        """Converts a 7-segment byte to its character representation."""
        # Mask with 0x7F to ignore the decimal point bit.
        return self.SEVEN_SEG_MAP.get(byte_val & 0x7F, " ")

    def get_bogey_counter_str(self) -> str:
        """Returns the two-character string from the bogey counter display."""
        return self._seven_seg_to_char(self.payload[0]) + self._seven_seg_to_char(self.payload[1])

    def get_num_leds(self) -> int:
        """Returns the number of lit LEDs in the signal strength meter (0-8)."""
        strength_byte = self.payload[2]
        # Count the number of set bits ('1's) in the byte's binary representation.
        return bin(strength_byte).count('1')
    
    # The following methods check bits in the payload to determine alert status.
    # An active alert requires bit 2 of payload[5] (System Status) to be set.
    # The specific band is indicated in payload[3] (Band Indication).
    
    def is_laser(self) -> bool:
        """Returns True if a Laser alert is active."""
        alert_active = self.payload[5] & 0b00000100
        band_is_laser = self.payload[3] & 0b00000001
        return bool(alert_active and band_is_laser)

    def is_ka(self) -> bool:
        """Returns True if a Ka-band alert is active."""
        alert_active = self.payload[5] & 0b00000100
        band_is_ka = self.payload[3] & 0b00000010
        return bool(alert_active and band_is_ka)

    def is_k(self) -> bool:
        """Returns True if a K-band alert is active."""
        alert_active = self.payload[5] & 0b00000100
        band_is_k = self.payload[3] & 0b00000100
        return bool(alert_active and band_is_k)

    def is_x(self) -> bool:
        """Returns True if an X-band alert is active."""
        alert_active = self.payload[5] & 0b00000100
        band_is_x = self.payload[3] & 0b00001000
        return bool(alert_active and band_is_x)

    def is_front(self) -> bool:
        """Returns True if the front arrow is lit."""
        return bool(self.payload[3] & 0b00100000)

    def is_side(self) -> bool:
        """Returns True if the side arrow is lit."""
        return bool(self.payload[3] & 0b01000000)

    def is_rear(self) -> bool:
        """Returns True if the rear arrow is lit."""
        return bool(self.payload[3] & 0b10000000)

    def is_ts_holdoff(self) -> bool:
        """Returns True if the V1 is in TS holdoff (cannot accept commands)."""
        return bool(self.payload[5] & 0b00000010)


class ResponseVersion(ESPPacket):
    """A response packet containing a firmware version string."""

    @property
    def version(self) -> str:
        """The firmware version as a string, stripped of null characters."""
        return self.payload.decode('ascii').strip('\x00')

    @property
    def version_as_float(self) -> float:
        """The firmware version as a float (e.g., 'V3.8950' -> 3.8950)."""
        try:
            return float(self.version[1:])
        except (ValueError, IndexError):
            return 0.0


class ResponseMaxSweepIndex(ESPPacket):
    """A response packet containing the maximum custom sweep index."""

    @property
    def max_sweep_index(self) -> int:
        """The highest index used for custom sweeps."""
        return self.payload[0]


class SweepDefinition:
    """Represents a single custom sweep definition."""

    def __init__(self, payload: bytes):
        """
        Parses the payload of a sweep definition packet.

        Args:
            payload: The payload bytes for a single sweep.
        """
        # First byte contains index (6 bits) and commit flag (1 bit)
        self.index = payload[0] & 0x3F
        self.commit = bool(payload[0] & 0x40)

        # Frequencies are 16-bit, big-endian unsigned integers (in MHz)
        self.upper_edge = struct.unpack('>H', payload[1:3])[0]
        self.lower_edge = struct.unpack('>H', payload[3:5])[0]

    def __repr__(self):
        """Provides a readable representation of the sweep."""
        return (
            f"<SweepDef Index={self.index} "
            f"Range={self.lower_edge}-{self.upper_edge}MHz "
            f"Commit={self.commit}>"
        )


class ResponseSweepDefinition(ESPPacket):
    """A response packet containing a single sweep definition."""

    @property
    def sweep_definition(self) -> SweepDefinition:
        """The parsed SweepDefinition object."""
        return SweepDefinition(self.payload)


class AlertData:
    """Represents data for a single alert from the V1's internal alert table."""

    def __init__(self, payload: bytes):
        """
        Parses the payload of an alert data packet.

        Args:
            payload: The payload bytes for a single alert.
        """
        # Byte 0: High nibble is index, low nibble is total count
        self.index = (payload[0] >> 4) & 0x0F
        self.count = payload[0] & 0x0F

        # Bytes 1-2: Frequency as a 16-bit, big-endian unsigned integer
        self.frequency = struct.unpack('>H', payload[1:3])[0]

        # Bytes 3-4: Signal strength for front and rear antennas
        self.front_strength = payload[3]
        self.rear_strength = payload[4]

        # Byte 6: Bit 7 indicates if this is the priority alert
        self.is_priority = bool(payload[6] & 0x80)

    def __repr__(self):
        """Provides a readable representation of the alert."""
        freq_ghz = self.frequency / 1000.0
        return (
            f"<AlertData #{self.index}/{self.count} "
            f"Freq={freq_ghz:.3f}GHz "
            f"Str(F/R)={self.front_strength:02X}/{self.rear_strength:02X} "
            f"Priority={self.is_priority}>"
        )


class ResponseAlertData(ESPPacket):
    """A response packet containing data for a single alert."""

    @property
    def alert_data(self) -> AlertData:
        """The parsed AlertData object."""
        return AlertData(self.payload)


class ResponseErrorPacket(ESPPacket):
    """Represents an error response from the V1."""

    @property
    def errored_packet_id(self) -> Optional[PacketId]:
        """The PacketId of the request that caused the error, if available."""
        try:
            return PacketId(self.payload[0])
        except (ValueError, IndexError):
            return None

    def __repr__(self):
        """Provides a readable representation of the error."""
        errored_pid_name = self.errored_packet_id.name if self.errored_packet_id else 'Unknown'
        return f"<{self.__class__.__name__} ErroredPID={errored_pid_name}>"


def packet_factory(raw_data: bytes, v1_type: DeviceId) -> Optional[ESPPacket]:
    """
    Creates a specific ESPPacket subclass based on the packet ID.

    Args:
        raw_data: The complete raw byte sequence of the packet.
        v1_type: The type of V1 device.

    Returns:
        An instance of an ESPPacket subclass, or a generic ESPPacket if the
        type is unknown, or None if the packet is malformed.
    """
    PACKET_TYPE_MAP: Dict[int, Type[ESPPacket]] = {
        PacketId.INFDISPLAYDATA: InfDisplayData,
        PacketId.RESPVERSION: ResponseVersion,
        PacketId.RESPMAXSWEEPINDEX: ResponseMaxSweepIndex,
        PacketId.RESPSWEEPDEFINITION: ResponseSweepDefinition,
        PacketId.RESPALERTDATA: ResponseAlertData,
        PacketId.RESPDATAERROR: ResponseErrorPacket,
        PacketId.RESPREQUESTNOTPROCESSED: ResponseErrorPacket,
        PacketId.RESPUNSUPPORTEDPACKET: ResponseErrorPacket,
    }

    try:
        packet_id = raw_data[3]
        packet_class = PACKET_TYPE_MAP.get(packet_id, ESPPacket)
        return packet_class(raw_data, v1_type)
    except (IndexError, ValueError):
        # Packet is too short or contains an invalid enum value
        logging.warning(f"Could not parse malformed packet: {raw_data.hex().upper()}")
        return None


# --- Console Display Class ---

class V1ConsoleDisplay:
    """Manages rendering the V1 state to the console."""

    COLORS = {
        "red": "\033[91m", "green": "\033[92m", "yellow": "\033[93m",
        "blue": "\033[94m", "magenta": "\033[95m", "cyan": "\033[96m",
        "grey": "\033[90m", "reset": "\033[0m"
    }

    def __init__(self):
        """Initializes the display state."""
        self.priority_alert: Optional[AlertData] = None
        self.last_display_data: Optional[InfDisplayData] = None
        self.print_lock = asyncio.Lock()

    def _colorize(self, text: str, color: str, active: bool) -> str:
        """Applies color to text if active, otherwise makes it grey."""
        if active:
            return f"{self.COLORS[color]}{text}{self.COLORS['reset']}"
        return f"{self.COLORS['grey']}{text}{self.COLORS['reset']}"

    async def update_alerts(self, alerts: List[AlertData]):
        """
        Updates the priority alert info from a list of all current alerts.

        This method finds the priority alert (or defaults to the first) and
        triggers a re-render of the display.
        """
        async with self.print_lock:
            self.priority_alert = None
            if alerts:
                # Find the alert marked as priority by the V1.
                for alert in alerts:
                    if alert.is_priority:
                        self.priority_alert = alert
                        break
                # If no priority alert is found, default to the first in the list.
                if not self.priority_alert:
                    self.priority_alert = alerts[0]

            # Trigger a redraw with the new alert data, if we have display data.
            if self.last_display_data:
                await self._render(self.last_display_data)

    async def update(self, display_data: InfDisplayData):
        """
        Updates the display with new data from the V1.

        This is the main callback for `infDisplayData` packets.
        """
        async with self.print_lock:
            self.last_display_data = display_data
            await self._render(display_data)

    async def _render(self, display_data: InfDisplayData):
        """Constructs and prints the full display string to the console."""
        # Bogey Counter (e.g., "[ 1  ]")
        bogey_str = f"[{display_data.get_bogey_counter_str():^4}]"

        # Band Indicators (e.g., Laser Ka K X)
        bands_str = " ".join([
            self._colorize("Laser", "red", display_data.is_laser()),
            self._colorize("Ka", "green", display_data.is_ka()),
            self._colorize("K", "blue", display_data.is_k()),
            self._colorize("X", "magenta", display_data.is_x())
        ])

        # Directional Arrows (e.g., Front Side Rear)
        arrows_str = " ".join([
            self._colorize("Front", "yellow", display_data.is_front()),
            self._colorize("Side", "cyan", display_data.is_side()),
            self._colorize("Rear", "red", display_data.is_rear())
        ])

        # Signal Strength Bar (e.g., [████    ])
        num_leds = display_data.get_num_leds()
        signal_bar = '█' * num_leds + ' ' * (8 - num_leds)
        signal_str = f"Signal:[{signal_bar}]"

        # Priority Alert Information (if available)
        alert_info_str = ""
        if self.priority_alert:
            freq_ghz = self.priority_alert.frequency / 1000.0
            alert_info_str = (
                f" | Pri: {freq_ghz:.3f} GHz | "
                f"Str(F/R): {self.priority_alert.front_strength:02X}/"
                f"{self.priority_alert.rear_strength:02X}"
            )

        # Assemble the final string
        full_display = f"{bogey_str} | {bands_str} | {arrows_str} | {signal_str}{alert_info_str}"

        # Pad with spaces to clear any previous, longer line content
        padding = " " * (100 - len(full_display))
        full_display += padding

        # Use `sys.stdout` and carriage return `\r` to write over the current line
        sys.stdout.write(f"\r{full_display}")
        sys.stdout.flush()


# --- V1 BLE Client ---

class V1BleakClient:
    """Handles BLE communication with a V1connection LE device."""

    def __init__(self):
        """Initializes the BLE client and its state."""
        self.client: Optional[BleakClient] = None
        self.v1_type: DeviceId = DeviceId.UNKNOWN_DEVICE
        self.firmware_version: float = 0.0

        # Concurrency controls for managing requests and responses
        self.request_lock = asyncio.Lock()
        self.pending_responses: Dict[PacketId, asyncio.Queue] = {}

        # Event to pause sending commands during V1's "Traffic Sensor" holdoff
        self.can_send_event = asyncio.Event()
        self.can_send_event.set()  # Allow sending by default

        # Callbacks for processing different types of data
        self.display_callback: Optional[Callable[[InfDisplayData], None]] = None
        self.alert_callback: Optional[Callable[[List[AlertData]], None]] = None
        self.packet_callback: Optional[Callable[[ESPPacket], None]] = None

        # Buffer for reassembling multi-packet alert data
        self._alert_buffer: Dict[int, AlertData] = {}

    async def scan(self) -> List[BLEDevice]:
        """Scans for nearby V1connection LE devices."""
        print("Scanning for V1 devices...")
        try:
            return list(await BleakScanner.discover(
                service_uuids=[V1_SERVICE_UUID],
                timeout=5.0
            ))
        except Exception as e:
            print(f"Error: Could not scan. {e}")
            return []

    async def connect(self, device: BLEDevice) -> bool:
        """Connects to the specified BLE device and starts notifications."""
        print(f"Connecting to {device.name} ({device.address})...")
        self.client = BleakClient(device)
        try:
            await self.client.connect()
            await self.client.start_notify(V1_NOTIFY_CHAR_UUID, self._notification_handler)
            print("Successfully connected.")
            # Assume checksum support on initial connection. This may be revised later.
            self.v1_type = DeviceId.VALENTINE_ONE
            return True
        except Exception as e:
            print(f"Failed to connect: {e}")
            self.client = None
            return False

    async def disconnect(self):
        """Disconnects from the BLE device if connected."""
        if self.client and self.client.is_connected:
            print("Disconnecting...")
            await self.client.disconnect()
        self.client = None
        print("Disconnected.")

    def _notification_handler(self, sender: int, data: bytearray):
        """
        Callback for incoming BLE notifications from the V1.

        This method parses, validates, and dispatches incoming ESP packets.
        """
        logging.debug(f"RECV RAW: {data.hex().upper()}")

        # Basic validation: check for Start of Frame and End of Frame bytes
        if not (data.startswith(b'\xaa') and data.endswith(b'\xab')):
            logging.warning("Received malformed frame (no SOF/EOF).")
            return

        # Ignore packets originating from V1connection itself
        origin_id = DeviceId(data[2] & 0x0F)
        if origin_id == DeviceId.V1CONNECTION:
            return

        # Dynamically determine the V1 type based on its packets
        if origin_id in [DeviceId.VALENTINE_ONE, DeviceId.VALENTINE_ONE_NO_CHECKSUM]:
            self.v1_type = origin_id

        # If the V1 supports checksums, validate it.
        # The checksum is the sum of all bytes before it, modulo 256.
        if self.v1_type == DeviceId.VALENTINE_ONE:
            expected_checksum = sum(data[:-2]) & 0xFF
            received_checksum = data[-2]
            if received_checksum != expected_checksum:
                logging.warning(f"Checksum mismatch! Got {received_checksum}, expected {expected_checksum}.")
                return

        # Use the factory to create a specific packet object
        packet = packet_factory(bytes(data), self.v1_type)
        if not packet:
            return

        # --- Dispatch the parsed packet ---

        if self.packet_callback:
            asyncio.create_task(self.packet_callback(packet))

        # Handle specific packet types for core functionality
        if isinstance(packet, InfDisplayData):
            # The V1 cannot process commands during "Traffic Sensor" holdoff.
            # We use an event to pause outgoing requests until it's clear.
            if packet.is_ts_holdoff():
                self.can_send_event.clear()
            else:
                self.can_send_event.set()

            if self.display_callback:
                asyncio.create_task(self.display_callback(packet))

        elif isinstance(packet, ResponseAlertData):
            self._process_alert_data(packet.alert_data)

        # If this packet is a response to a pending request, put it in the queue.
        if packet.packet_id in self.pending_responses:
            self.pending_responses[packet.packet_id].put_nowait(packet)

    def _process_alert_data(self, alert: AlertData):
        """
        Buffers and reassembles multi-packet alert data streams.

        Alert data is sent as one packet per alert in the V1's table. This
        method collects them until the full set is received, then calls the
        alert callback.
        """
        # A count of 0 indicates the end of the alert stream.
        if alert.count == 0:
            self._alert_buffer.clear()
            if self.alert_callback:
                asyncio.create_task(self.alert_callback([]))
            return

        # If the total count changes, it's a new alert set. Clear the old buffer.
        if self._alert_buffer:
            first_buffered_alert = self._alert_buffer[list(self._alert_buffer.keys())[0]]
            if first_buffered_alert.count != alert.count:
                self._alert_buffer.clear()

        # Add the new alert to the buffer, keyed by its index.
        self._alert_buffer[alert.index] = alert

        # If we have received the expected number of alerts, process them.
        if len(self._alert_buffer) == alert.count:
            # Sort alerts by index to ensure correct order.
            sorted_alerts = [self._alert_buffer[i] for i in sorted(self._alert_buffer.keys())]
            if self.alert_callback:
                asyncio.create_task(self.alert_callback(sorted_alerts))
            # Clear the buffer for the next set.
            self._alert_buffer.clear()

    async def _send_request(self, pid: PacketId, dest: DeviceId, payload: Optional[bytes] = None):
        """Constructs and sends an ESP packet to the V1."""
        if not (self.client and self.client.is_connected):
            raise ConnectionError("Not connected to a device.")

        # Wait if the V1 is in holdoff mode.
        await self.can_send_event.wait()

        origin = DeviceId.V1CONNECTION
        payload = payload or b''
        use_checksum = (self.v1_type == DeviceId.VALENTINE_ONE)

        # The payload length field includes the checksum byte if one is used.
        payload_len = len(payload)
        if use_checksum:
            payload_len += 1

        # Construct the packet header
        packet = bytearray([
            ESP_SOF,
            DEST_BASE | dest.value,
            ORIG_BASE | origin.value,
            pid.value,
            payload_len
        ])
        packet.extend(payload)

        # Append checksum if required
        if use_checksum:
            checksum = sum(packet) & 0xFF
            packet.append(checksum)

        # Append End of Frame
        packet.append(ESP_EOF)

        logging.debug(f"SEND: {packet.hex().upper()}")
        await self.client.write_gatt_char(V1_WRITE_CHAR_UUID, packet)

    async def _request_and_wait(
        self,
        req_pid: PacketId,
        resp_pid: PacketId,
        dest: DeviceId,
        payload: Optional[bytes] = None,
        timeout: float = 5.0
    ) -> Optional[ESPPacket]:
        """
        Sends a request and waits for a specific response packet.

        This is a thread-safe way to handle request/response interactions.
        """
        async with self.request_lock:
            # Create a queue to receive the response.
            response_queue = asyncio.Queue(maxsize=1)
            self.pending_responses[resp_pid] = response_queue

            try:
                await self._send_request(req_pid, dest, payload)
                return await asyncio.wait_for(response_queue.get(), timeout=timeout)
            except asyncio.TimeoutError:
                print(f"\nTimeout waiting for response to {req_pid.name}")
                return None
            finally:
                # Clean up the pending response queue
                if resp_pid in self.pending_responses:
                    del self.pending_responses[resp_pid]

    async def request_version(self, dev_id: DeviceId = DeviceId.VALENTINE_ONE) -> Optional[str]:
        """Requests the firmware version from a device."""
        response = await self._request_and_wait(
            PacketId.REQVERSION,
            PacketId.RESPVERSION,
            dev_id
        )
        if isinstance(response, ResponseVersion):
            self.firmware_version = response.version_as_float
            return response.version
        return None

    async def request_sweeps(self) -> Optional[List[SweepDefinition]]:
        """Requests all custom sweep definitions from the V1."""
        if self.firmware_version == 0.0:
            print("Unknown firmware version. Please run the 'ver' command first.")
            return None
        if self.firmware_version < MIN_SWEEP_FW_VERSION:
            print(f"Sweeps not supported on V{self.firmware_version:.4f}. "
                  f"Requires V{MIN_SWEEP_FW_VERSION:.4f}+.")
            return None

        async with self.request_lock:
            # First, find out how many sweeps are defined.
            max_idx_resp = await self._request_and_wait(
                PacketId.REQMAXSWEEPINDEX,
                PacketId.RESPMAXSWEEPINDEX,
                DeviceId.VALENTINE_ONE
            )
            if not isinstance(max_idx_resp, ResponseMaxSweepIndex):
                return None

            num_sweeps = max_idx_resp.max_sweep_index + 1
            print(f"V1 supports {num_sweeps} sweeps. Reading definitions...")

            # Prepare a queue to collect all incoming sweep definition packets.
            sweep_queue = asyncio.Queue()
            self.pending_responses[PacketId.RESPSWEEPDEFINITION] = sweep_queue
            sweeps = []

            try:
                # Send a single request to get all sweep definitions.
                await self._send_request(PacketId.REQALLSWEEPDEFINITIONS, DeviceId.VALENTINE_ONE)

                # Wait for and collect the expected number of responses.
                for _ in range(num_sweeps):
                    response = await asyncio.wait_for(sweep_queue.get(), timeout=5.0)
                    if isinstance(response, ResponseSweepDefinition):
                        sweeps.append(response.sweep_definition)

                # Sort by index for a clean display.
                sweeps.sort(key=lambda s: s.index)
                return sweeps
            except asyncio.TimeoutError:
                print("Timeout while collecting sweep definitions.")
                return None
            finally:
                # Clean up the pending response queue.
                if PacketId.RESPSWEEPDEFINITION in self.pending_responses:
                    del self.pending_responses[PacketId.RESPSWEEPDEFINITION]

    async def start_alert_data(self):
        """Requests the V1 to start streaming its alert table data."""
        await self._send_request(PacketId.REQSTARTALERTDATA, DeviceId.VALENTINE_ONE)

    async def stop_alert_data(self):
        """Requests the V1 to stop streaming its alert table data."""
        await self._send_request(PacketId.REQSTOPALERTDATA, DeviceId.VALENTINE_ONE)


# --- Command Line Interface Class ---

class CommandLineInterface:
    """Handles user input and executes commands."""

    def __init__(self, v1_client: V1BleakClient, console_display: V1ConsoleDisplay):
        """
        Initializes the CLI.

        Args:
            v1_client: The active V1 bleak client instance.
            console_display: The active console display instance.
        """
        self.v1_client = v1_client
        self.console_display = console_display

    async def run(self, exit_event: asyncio.Event):
        """The main loop for reading and processing user commands."""
        loop = asyncio.get_running_loop()
        while not exit_event.is_set():
            try:
                # Run the blocking `input()` in a separate thread to avoid
                # blocking the asyncio event loop.
                cmd = await loop.run_in_executor(
                    None, lambda: input("> ").strip().lower()
                )

                # Acquire the print lock to prevent display updates from
                # interfering with command output.
                async with self.console_display.print_lock:
                    # Use ANSI escape codes to move cursor up and clear the line
                    # where the user typed their command, for a cleaner look.
                    sys.stdout.write("\033[A\033[K")
                    print(f"> {cmd}")  # Echo the command

                    if cmd == "ver":
                        version = await self.v1_client.request_version()
                        if version:
                            print(f"Firmware Version: {version}")
                    elif cmd == "sweeps":
                        sweeps = await self.v1_client.request_sweeps()
                        if sweeps:
                            print("--- Custom Sweeps ---")
                            for sweep in sweeps:
                                print(sweep)
                            print("---------------------")
                    elif cmd == "alerts_on":
                        await self.v1_client.start_alert_data()
                        print("Alert data stream enabled.")
                    elif cmd == "alerts_off":
                        await self.v1_client.stop_alert_data()
                        print("Alert data stream disabled.")
                    elif cmd == "exit":
                        exit_event.set()
                    elif cmd: # If command is not empty
                        print(f"Unknown command: '{cmd}'. "
                              "Available: ver, sweeps, alerts_on, alerts_off, exit")

                # Reprint the prompt for the next command if not exiting.
                if not exit_event.is_set():
                    print(">", end="", flush=True)

            except Exception as e:
                print(f"\nError in command loop: {e}")


async def main():
    """Main entry point for the application."""
    logging.basicConfig(level=logging.INFO)

    # Instantiate the core components
    console_display = V1ConsoleDisplay()
    v1_client = V1BleakClient()

    # Wire up the callbacks
    v1_client.display_callback = console_display.update
    v1_client.alert_callback = console_display.update_alerts

    # --- Device Discovery and Selection ---
    devices = await v1_client.scan()
    if not devices:
        print("No V1 devices found. Exiting.")
        return

    print("\nFound devices:")
    for i, device in enumerate(devices):
        print(f"  {i}: {device.name} ({device.address})")

    try:
        choice = int(input("Select a device: "))
        selected_device = devices[choice]
    except (ValueError, IndexError):
        print("Invalid choice. Exiting.")
        return

    # --- Connection and Main Loop ---
    if not await v1_client.connect(selected_device):
        return

    cli = CommandLineInterface(v1_client, console_display)
    exit_event = asyncio.Event()

    # Run the command interface in a separate, concurrent task.
    command_task = asyncio.create_task(cli.run(exit_event))

    print("\nReal-time display started. Type commands and press Enter.")
    print(">", end="", flush=True)

    try:
        # Wait until the exit event is set (e.g., by the 'exit' command).
        await exit_event.wait()
    except asyncio.CancelledError:
        pass  # Gracefully handle task cancellation on shutdown.
    finally:
        print("\nShutting down...")
        command_task.cancel()
        await v1_client.disconnect()
        print()


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        # Handle Ctrl+C gracefully.
        print("\nExiting.")