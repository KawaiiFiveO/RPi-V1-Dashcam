# RPi-V1-Dashcam/controllers/v1_controller.py

import asyncio
import struct
import logging
from enum import IntEnum
from typing import List, Optional, Callable, Dict, Type

from bleak import BleakClient, BleakScanner
from bleak.backends.device import BLEDevice
from bleak.exc import BleakError

# Import shared application components
from shared_state import AppState, V1Data
import config

# -----------------------------------------------------------------------------
# --- ESP Protocol Definitions ---
# These classes and enums define the Escort Serial Protocol for the V1.
# -----------------------------------------------------------------------------

# ESP framing and address bytes
ESP_SOF = 0xAA
ESP_EOF = 0xAB
DEST_BASE = 0xD0
ORIG_BASE = 0xE0

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
    INFV1BUSY = 0x66
    RESPDATAERROR = 0x67

    # Internal Use
    UNKNOWNPACKETTYPE = 0x100

class ESPPacket:
    """Base class for all ESP packets, handling common header parsing."""
    def __init__(self, raw_data: bytes, v1_type: DeviceId):
        self.raw_data = raw_data
        self.v1_type = v1_type
        self.destination = DeviceId(raw_data[1] & 0x0F)
        self.origin = DeviceId(raw_data[2] & 0x0F)
        self.packet_id = PacketId(raw_data[3])
        payload_len = raw_data[4]
        if self.v1_type == DeviceId.VALENTINE_ONE and payload_len > 0:
            payload_len -= 1
        self.payload = raw_data[5:5 + payload_len]

    def __repr__(self) -> str:
        return f"<{self.__class__.__name__} Dst={self.destination.name}, Org={self.origin.name}, Pay={self.payload.hex().upper()}>"

class InfDisplayData(ESPPacket):
    """Parses and provides access to V1 display data."""
    def is_laser(self) -> bool:
        return bool((self.payload[5] & 0b00000100) and (self.payload[3] & 0b00000001))
    def is_ka(self) -> bool:
        return bool((self.payload[5] & 0b00000100) and (self.payload[3] & 0b00000010))
    def is_k(self) -> bool:
        return bool((self.payload[5] & 0b00000100) and (self.payload[3] & 0b00000100))
    def is_x(self) -> bool:
        return bool((self.payload[5] & 0b00000100) and (self.payload[3] & 0b00001000))
    def is_ts_holdoff(self) -> bool:
        return bool(self.payload[5] & 0b00000010)
    def get_mode(self) -> str:
        system_status = self.payload[5]
        if system_status & 0b00000001:
            return "All Bogeys"
        elif system_status & 0b00010000:
            return "Adv. Logic"
        else:
            return "Logic"

class AlertData:
    """Represents data for a single alert from the V1's internal alert table."""
    def __init__(self, payload: bytes):
        self.index = (payload[0] >> 4) & 0x0F
        self.count = payload[0] & 0x0F
        self.frequency = struct.unpack('>H', payload[1:3])[0]
        self.front_strength = payload[3]
        self.rear_strength = payload[4]
        self.is_priority = bool(payload[6] & 0x80)
    def __repr__(self):
        return f"<AlertData #{self.index}/{self.count} Freq={self.frequency/1000.0:.3f}GHz Prio={self.is_priority}>"

class ResponseAlertData(ESPPacket):
    @property
    def alert_data(self) -> AlertData:
        return AlertData(self.payload)

class ResponseVersion(ESPPacket):
    @property
    def version(self) -> str:
        return self.payload.decode('ascii').strip('\x00')

class ResponseMaxSweepIndex(ESPPacket):
    @property
    def max_sweep_index(self) -> int:
        return self.payload[0]

class SweepDefinition:
    def __init__(self, payload: bytes):
        self.index = payload[0] & 0x3F
        self.commit = bool(payload[0] & 0x40)
        self.upper_edge = struct.unpack('>H', payload[1:3])[0]
        self.lower_edge = struct.unpack('>H', payload[3:5])[0]
    def __repr__(self):
        return f"<SweepDef Index={self.index} Range={self.lower_edge}-{self.upper_edge}MHz Commit={self.commit}>"

class ResponseSweepDefinition(ESPPacket):
    @property
    def sweep_definition(self) -> SweepDefinition:
        return SweepDefinition(self.payload)

def packet_factory(raw_data: bytes, v1_type: DeviceId) -> Optional[ESPPacket]:
    """Creates a specific ESPPacket subclass based on the packet ID."""
    PACKET_TYPE_MAP: Dict[int, Type[ESPPacket]] = {
        PacketId.INFDISPLAYDATA: InfDisplayData,
        PacketId.RESPALERTDATA: ResponseAlertData,
        PacketId.RESPVERSION: ResponseVersion,
        PacketId.RESPMAXSWEEPINDEX: ResponseMaxSweepIndex,
        PacketId.RESPSWEEPDEFINITION: ResponseSweepDefinition,
    }
    try:
        packet_id_val = raw_data[3]
        if packet_id_val not in PacketId._value2member_map_:
            return ESPPacket(raw_data, v1_type) # Return base packet for unknown IDs
        packet_id = PacketId(packet_id_val)
        packet_class = PACKET_TYPE_MAP.get(packet_id, ESPPacket)
        return packet_class(raw_data, v1_type)
    except (IndexError, ValueError):
        logging.warning(f"Could not parse malformed packet: {raw_data.hex().upper()}")
        return None

# -----------------------------------------------------------------------------
# --- V1 BLE Client ---
# This class handles the low-level BLE communication.
# -----------------------------------------------------------------------------
class V1BleakClient:
    def __init__(self):
        self.client: Optional[BleakClient] = None
        self.v1_type: DeviceId = DeviceId.UNKNOWN_DEVICE
        self.can_send_event = asyncio.Event()
        self.can_send_event.set()
        self.display_callback: Optional[Callable[[InfDisplayData], None]] = None
        self.alert_callback: Optional[Callable[[List[AlertData]], None]] = None
        self._alert_buffer: Dict[int, AlertData] = {}
        self.request_lock = asyncio.Lock()
        self.pending_responses: Dict[PacketId, asyncio.Queue] = {}

    async def scan(self) -> Optional[BLEDevice]:
        print("V1CLIENT: Scanning for V1 devices...")
        try:
            device = await BleakScanner.find_device_by_filter(
                lambda d, ad: ad.service_uuids and config.V1_SERVICE_UUID.lower() in ad.service_uuids,
                timeout=10.0
            )
            return device
        except Exception as e:
            print(f"V1CLIENT: Error during BLE scan: {e}")
            return None

    async def connect(self, device: BLEDevice) -> bool:
        print(f"V1CLIENT: Connecting to {device.name} ({device.address})...")
        self.client = BleakClient(device)
        try:
            await self.client.connect()
            await self.client.start_notify(config.V1_NOTIFY_CHAR_UUID, self._notification_handler)
            print("V1CLIENT: Successfully connected and subscribed to notifications.")
            self.v1_type = DeviceId.VALENTINE_ONE
            return True
        except Exception as e:
            print(f"V1CLIENT: Failed to connect: {e}")
            self.client = None
            return False

    async def disconnect(self):
        if self.client and self.client.is_connected:
            print("V1CLIENT: Disconnecting...")
            await self.client.disconnect()
        self.client = None

    def _notification_handler(self, sender: int, data: bytearray):
        if not (data.startswith(b'\xaa') and data.endswith(b'\xab')):
            return
        origin_id = DeviceId(data[2] & 0x0F)
        if origin_id == DeviceId.V1CONNECTION:
            return
        if origin_id in [DeviceId.VALENTINE_ONE, DeviceId.VALENTINE_ONE_NO_CHECKSUM]:
            self.v1_type = origin_id
        if self.v1_type == DeviceId.VALENTINE_ONE:
            expected_checksum = sum(data[:-2]) & 0xFF
            if data[-2] != expected_checksum:
                logging.warning("V1 checksum mismatch!")
                return
        packet = packet_factory(bytes(data), self.v1_type)
        if not packet:
            return
        if isinstance(packet, InfDisplayData):
            self.can_send_event.set() if not packet.is_ts_holdoff() else self.can_send_event.clear()
            if self.display_callback:
                asyncio.create_task(self.display_callback(packet))
        elif isinstance(packet, ResponseAlertData):
            self._process_alert_data(packet.alert_data)
        if packet.packet_id in self.pending_responses:
            self.pending_responses[packet.packet_id].put_nowait(packet)

    def _process_alert_data(self, alert: AlertData):
        if alert.count == 0:
            self._alert_buffer.clear()
            if self.alert_callback:
                asyncio.create_task(self.alert_callback([]))
            return
        if self._alert_buffer and self._alert_buffer[list(self._alert_buffer.keys())[0]].count != alert.count:
            self._alert_buffer.clear()
        self._alert_buffer[alert.index] = alert
        if len(self._alert_buffer) == alert.count:
            sorted_alerts = [self._alert_buffer[i] for i in sorted(self._alert_buffer.keys())]
            if self.alert_callback:
                asyncio.create_task(self.alert_callback(sorted_alerts))
            self._alert_buffer.clear()

    async def _send_request(self, pid: PacketId, dest: DeviceId, payload: Optional[bytes] = None):
        if not (self.client and self.client.is_connected):
            raise ConnectionError("Not connected to a device.")
        await self.can_send_event.wait()
        payload = payload or b''
        use_checksum = (self.v1_type == DeviceId.VALENTINE_ONE)
        payload_len = len(payload) + 1 if use_checksum else len(payload)
        packet = bytearray([ESP_SOF, DEST_BASE | dest.value, ORIG_BASE | DeviceId.V1CONNECTION.value, pid.value, payload_len])
        packet.extend(payload)
        if use_checksum:
            packet.append(sum(packet) & 0xFF)
        packet.append(ESP_EOF)
        await self.client.write_gatt_char(config.V1_WRITE_CHAR_UUID, packet)

    async def _request_and_wait(self, req_pid, resp_pid, dest, payload=None, timeout=5.0):
        async with self.request_lock:
            response_queue = asyncio.Queue(maxsize=1)
            self.pending_responses[resp_pid] = response_queue
            try:
                await self._send_request(req_pid, dest, payload)
                response = await asyncio.wait_for(response_queue.get(), timeout=timeout)
                return response
            except asyncio.TimeoutError:
                print(f"V1CLIENT: Timeout waiting for response to {req_pid.name}")
                return None
            finally:
                if resp_pid in self.pending_responses:
                    del self.pending_responses[resp_pid]

    async def request_version(self) -> Optional[str]:
        response = await self._request_and_wait(PacketId.REQVERSION, PacketId.RESPVERSION, DeviceId.VALENTINE_ONE)
        if isinstance(response, ResponseVersion):
            return response.version
        return None

    async def request_sweeps(self) -> Optional[List[SweepDefinition]]:
        max_idx_resp = await self._request_and_wait(PacketId.REQMAXSWEEPINDEX, PacketId.RESPMAXSWEEPINDEX, DeviceId.VALENTINE_ONE)
        if not isinstance(max_idx_resp, ResponseMaxSweepIndex):
            print("V1CLIENT: Failed to get max sweep index.")
            return None
        num_sweeps = max_idx_resp.max_sweep_index + 1
        if num_sweeps == 0:
            return []
        sweep_queue = asyncio.Queue()
        self.pending_responses[PacketId.RESPSWEEPDEFINITION] = sweep_queue
        sweeps: Dict[int, SweepDefinition] = {}
        try:
            await self._send_request(PacketId.REQALLSWEEPDEFINITIONS, DeviceId.VALENTINE_ONE)
            async with asyncio.timeout(10.0):
                while len(sweeps) < num_sweeps:
                    response = await sweep_queue.get()
                    if isinstance(response, ResponseSweepDefinition):
                        sweep_def = response.sweep_definition
                        if sweep_def.index not in sweeps:
                            sweeps[sweep_def.index] = sweep_def
            sorted_sweeps = [sweeps[i] for i in sorted(sweeps.keys())]
            return sorted_sweeps
        except TimeoutError:
            print(f"V1CLIENT: Timeout collecting sweep definitions.")
            return None
        finally:
            if PacketId.RESPSWEEPDEFINITION in self.pending_responses:
                del self.pending_responses[PacketId.RESPSWEEPDEFINITION]

    async def start_alert_data(self):
        await self._send_request(PacketId.REQSTARTALERTDATA, DeviceId.VALENTINE_ONE)

# -----------------------------------------------------------------------------
# --- V1 Controller ---
# This is the main class for this module. It runs in a dedicated thread,
# manages the V1BleakClient, and updates the shared AppState.
# -----------------------------------------------------------------------------
class V1Controller:
    def __init__(self, state: AppState):
        self.state = state
        self.v1_client = V1BleakClient()
        self.v1_client.alert_callback = self._handle_alerts
        self.v1_client.display_callback = self._handle_display_data
        self.loop: Optional[asyncio.AbstractEventLoop] = None
        self.main_task: Optional[asyncio.Task] = None

    def _get_band_from_freq(self, freq_mhz: int) -> str:
        if 10500 <= freq_mhz <= 10550:
            return "X"
        if 24050 <= freq_mhz <= 24250:
            return "K"
        if 33400 <= freq_mhz <= 36000:
            return "Ka"
        if freq_mhz == 0:
            return "Laser"
        return "Unknown"

    async def _handle_alerts(self, alerts: List[AlertData]):
        """Callback to process alert data and update the shared state."""
        priority_alert = next((a for a in alerts if a.is_priority), None)

        if priority_alert:
            freq_ghz = priority_alert.frequency / 1000.0
            band = self._get_band_from_freq(priority_alert.frequency)
            # Use the new atomic update method
            self.state.update_v1_alert_data(in_alert=True, band=band, freq=freq_ghz)
        else:
            # Use the new atomic update method to clear the alert
            self.state.update_v1_alert_data(in_alert=False, band="N/A", freq=0.0)

    async def _handle_display_data(self, display_data: InfDisplayData):
        """Callback to process general display data, like V1 mode."""
        # Use the new atomic update method
        self.state.update_v1_mode(display_data.get_mode())
        
        if display_data.is_laser():
            # Use the new atomic update method for laser alerts
            self.state.update_v1_laser_alert()

    async def _perform_startup_checks(self):
        """Requests version and sweep info from the V1 as a self-test."""
        print("V1CONTROLLER: Performing startup checks...")
        version = await self.v1_client.request_version()
        if version:
            print(f"V1CONTROLLER: Firmware Version: {version}")
        else:
            print("V1CONTROLLER: Failed to get firmware version.")
        sweeps = await self.v1_client.request_sweeps()
        if sweeps is not None:
            print(f"V1CONTROLLER: Found {len(sweeps)} custom sweep definitions.")
            for sweep in sweeps:
                print(f"  - {sweep}")
        else:
            print("V1CONTROLLER: Failed to get sweep definitions.")

    async def run_async(self):
        """The asynchronous core of the controller."""
        try:
            while self.state.get_app_running():
                device = await self.v1_client.scan()
                if not device:
                    print("V1CONTROLLER: No V1 device found. Retrying in 15 seconds...")
                    await asyncio.sleep(15)
                    continue
                try:
                    if await self.v1_client.connect(device):
                        # --- FIX IS HERE: Use the new atomic method ---
                        self.state.set_v1_connection_status(True)
                        
                        await self._perform_startup_checks()
                        await self.v1_client.start_alert_data()
                        
                        while self.state.get_app_running() and self.v1_client.client.is_connected:
                            await asyncio.sleep(1)
                except BleakError as e:
                    print(f"V1CONTROLLER: A Bluetooth error occurred: {e}")
                finally:
                    print("V1CONTROLLER: Cleaning up connection...")
                    await self.v1_client.disconnect()
                    
                    # --- FIX IS HERE: Use the new atomic method ---
                    # This will also reset the other V1 fields correctly.
                    self.state.set_v1_connection_status(False)
                    
                    if self.state.get_app_running():
                        print("V1CONTROLLER: Connection lost. Will attempt to reconnect...")
                        await asyncio.sleep(5)
        except asyncio.CancelledError:
            print("V1CONTROLLER: Async task cancelled.")
        finally:
            if self.v1_client.client and self.v1_client.client.is_connected:
                await self.v1_client.disconnect()
            print("V1CONTROLLER: Async task finished.")

    def run(self):
        """The main entry point for the V1 controller thread."""
        self.loop = asyncio.new_event_loop()
        asyncio.set_event_loop(self.loop)
        self.main_task = self.loop.create_task(self.run_async())
        try:
            self.loop.run_until_complete(self.main_task)
        except Exception as e:
            print(f"V1CONTROLLER: An error occurred in the async runner: {e}")
        finally:
            self.loop.close()
            print("V1CONTROLLER: Event loop closed.")

    # --- NEW SHUTDOWN METHOD ---
    def shutdown(self):
        """Thread-safe method to shut down the asyncio task."""
        print("V1CONTROLLER: Shutdown signaled.")
        if self.loop and self.main_task:
            # call_soon_threadsafe is required to interact with a loop from another thread
            self.loop.call_soon_threadsafe(self.main_task.cancel)