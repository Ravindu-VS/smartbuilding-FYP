"""Bridge the ESP32-S3 BLE fallback transport into the local MQTT broker."""
from __future__ import annotations

import asyncio
import hashlib
import json
import logging
import math
import os
import subprocess
import threading
import time
from collections import deque
from typing import Optional

logger = logging.getLogger("ble_gateway")

ROOM_ID = "f2_office_a"
PREFIX = "sb/v1"
SERVICE_UUID = "7c6f0001-4f3b-4c1a-9b2d-8a8b2f010101"
FRAME_UUID = "7c6f0002-4f3b-4c1a-9b2d-8a8b2f010101"
DEVICE_NAME = "SB-Room101"
TELEMETRY_TOPIC = f"{PREFIX}/room/{ROOM_ID}/telemetry"
COMMAND_TOPIC = f"{PREFIX}/room/{ROOM_ID}/command"
ACK_TOPIC = f"{PREFIX}/room/{ROOM_ID}/ack"
STATUS_TOPIC = f"{PREFIX}/room/{ROOM_ID}/status"
BLE_STATUS_TOPIC = f"{PREFIX}/room/{ROOM_ID}/ble_status"

FRAME_DATA_SIZE = 16          # data bytes per frame at the default 23-byte ATT MTU
MAX_FRAME_DATA_SIZE = 240     # data bytes per frame after a larger MTU is negotiated (ESP32 offers 247)
FRAME_HEADER_SIZE = 4
MAX_MESSAGE_SIZE = 1024
MAX_FRAME_COUNT = MAX_MESSAGE_SIZE // FRAME_DATA_SIZE
BLE_TIMEOUT_S = 15.0
MQTT_STATUS_GRACE_S = 2.0
MQTT_QUEUE_SIZE = 32


def frame_data_size(mtu: Optional[int]) -> int:
    """Data bytes per frame for a negotiated ATT MTU (3 bytes ATT header, 4 bytes frame header)."""
    if not mtu or mtu <= 3 + FRAME_HEADER_SIZE + FRAME_DATA_SIZE:
        return FRAME_DATA_SIZE
    return min(MAX_FRAME_DATA_SIZE, mtu - 3 - FRAME_HEADER_SIZE)


def encode_frames(kind: str, sequence: int, payload: bytes, chunk: int = FRAME_DATA_SIZE) -> list[bytes]:
    """Split one message into ATT frames: a four-byte header and up to ``chunk`` data bytes."""
    if kind not in ("T", "A", "C"):
        raise ValueError(f"unsupported BLE frame kind: {kind!r}")
    if not 0 <= sequence <= 255:
        raise ValueError("BLE sequence must be in range 0..255")
    if not payload or len(payload) > MAX_MESSAGE_SIZE:
        raise ValueError(f"BLE message size must be in range 1..{MAX_MESSAGE_SIZE}")
    if not FRAME_DATA_SIZE <= chunk <= MAX_FRAME_DATA_SIZE:
        raise ValueError(f"BLE frame data size must be in range {FRAME_DATA_SIZE}..{MAX_FRAME_DATA_SIZE}")
    count = math.ceil(len(payload) / chunk)
    if count > MAX_FRAME_COUNT:
        raise ValueError("BLE message requires too many frames")
    return [
        bytes((ord(kind), sequence, index, count))
        + payload[index * chunk : (index + 1) * chunk]
        for index in range(count)
    ]


class BleFrameAssembler:
    """Reassemble ordered or out-of-order BLE notifications into complete messages."""

    def __init__(self, timeout_s: float = 10.0):
        self.timeout_s = timeout_s
        self._messages: dict[tuple[str, int], dict] = {}

    def feed(self, frame: bytes) -> Optional[tuple[str, bytes]]:
        if not FRAME_HEADER_SIZE < len(frame) <= FRAME_HEADER_SIZE + MAX_FRAME_DATA_SIZE:
            raise ValueError("invalid BLE frame length")
        kind, sequence, index, count = chr(frame[0]), frame[1], frame[2], frame[3]
        if kind not in ("T", "A") or count == 0 or count > MAX_FRAME_COUNT or index >= count:
            raise ValueError("invalid BLE frame header")

        now = time.monotonic()
        for key, message in list(self._messages.items()):
            if now - message["updated"] > self.timeout_s:
                del self._messages[key]

        key = (kind, sequence)
        message = self._messages.get(key)
        if message is None or message["count"] != count:
            message = {"count": count, "parts": {}, "updated": now}
            self._messages[key] = message
        message["parts"][index] = frame[FRAME_HEADER_SIZE:]
        message["updated"] = now

        if len(message["parts"]) != count:
            return None
        payload = b"".join(message["parts"][part] for part in range(count))
        del self._messages[key]
        if not payload or len(payload) > MAX_MESSAGE_SIZE:
            raise ValueError("reassembled BLE message has an invalid size")
        return kind, payload


class BleGateway:
    """Connect to the ESP32 when it advertises, bridging its data to/from Mosquitto."""

    def __init__(self, host: Optional[str] = None, port: Optional[int] = None,
                 redundant: Optional[bool] = None):
        self.host = host or os.environ.get("MQTT_HOST", "127.0.0.1")
        # Redundant mode (default): every command is also written over BLE while the BLE link is up,
        # not only after the board reports MQTT offline. On a congested Wi-Fi the board's TCP link can
        # stall while it still counts as connected; the board de-duplicates by command msg_id.
        self.redundant = (os.environ.get("BLE_REDUNDANT", "1") == "1") if redundant is None else redundant
        self.port = int(port or os.environ.get("MQTT_PORT", "1883"))
        self.username = os.environ.get("MQTT_USERNAME") or None
        self.password = os.environ.get("MQTT_PASSWORD") or None
        self.tls = os.environ.get("MQTT_TLS", "0") == "1"
        self.client_id = f"edge-ble-{os.getpid()}"
        self.client = None
        self._stop = threading.Event()
        self._thread: Optional[threading.Thread] = None
        self._loop: Optional[asyncio.AbstractEventLoop] = None
        self._ble_client = None
        self._ble_connected = False
        self._board_mqtt_online: Optional[bool] = None
        self._mqtt_connected = False
        self._mqtt_connected_at: Optional[float] = None
        self._published_ble_status: Optional[str] = None
        self._last_ble_frame: Optional[float] = None
        self._last_error: Optional[str] = None
        self._lock = threading.Lock()
        self._pending_mqtt: deque[tuple[str, bytes]] = deque(maxlen=MQTT_QUEUE_SIZE)
        self._assembler = BleFrameAssembler()
        self._tx_sequence = 0
        self._mtu: Optional[int] = None
        self._recent_messages: dict[tuple, float] = {}   # (kind, seq, digest) -> time completed
        self._recent_frames: deque = deque(maxlen=24)     # frame headers, for diagnosing the link
        self._stats = {"telemetry": 0, "acks": 0, "commands": 0, "dropped": 0, "reconnects": 0,
                       "invalid_frames": 0, "duplicate_messages": 0, "stale_disconnects": 0}

    def start(self) -> None:
        try:
            from bleak import BleakClient, BleakScanner
            from bleak.exc import BleakError
            import paho.mqtt.client as mqtt
        except ImportError as exc:
            raise RuntimeError("BLE is enabled but bleak or paho-mqtt is missing; install requirements/edge.txt") from exc

        self._BleakClient = BleakClient
        self._BleakScanner = BleakScanner
        self._BleakError = BleakError

        client = mqtt.Client(mqtt.CallbackAPIVersion.VERSION2, client_id=self.client_id, clean_session=True)
        if self.username:
            client.username_pw_set(self.username, self.password)
        if self.tls:
            client.tls_set()
        client.will_set(BLE_STATUS_TOPIC, '{"state":"offline"}', qos=1, retain=True)
        client.reconnect_delay_set(min_delay=1, max_delay=30)
        client.on_connect = self._on_mqtt_connect
        client.on_disconnect = self._on_mqtt_disconnect
        client.on_message = self._on_mqtt_message
        self.client = client
        client.connect_async(self.host, self.port, keepalive=30)
        client.loop_start()
        self._thread = threading.Thread(target=self._run_thread, daemon=True, name="BleGateway")
        self._thread.start()
        logger.info("BLE gateway scanning for %s; MQTT broker %s:%d", DEVICE_NAME, self.host, self.port)

    def stop(self) -> None:
        self._stop.set()
        thread = self._thread
        if thread is not None:
            thread.join(timeout=12)
            if thread.is_alive():
                logger.error("BLE gateway did not stop within 12 seconds")
        if self.client is not None:
            self.client.disconnect()
            self.client.loop_stop()
        self._ble_connected = False

    def status(self) -> dict:
        with self._lock:
            return {
                "enabled": True,
                "connected": self._ble_connected,
                "mqtt_connected": self._mqtt_connected,
                "board_mqtt_online": self._board_mqtt_online,
                "board_mqtt_status_known": self._board_mqtt_online is not None,
                "device": DEVICE_NAME,
                "broker": f"{self.host}:{self.port}",
                "mtu": self._mtu,
                "frame_data_size": frame_data_size(self._mtu),
                "last_ble_frame_age_s": None if self._last_ble_frame is None else
                    round(max(0.0, time.monotonic() - self._last_ble_frame), 2),
                "last_error": self._last_error,
                "stats": dict(self._stats),
                "recent_frames": list(self._recent_frames),
            }

    def _run_thread(self) -> None:
        asyncio.run(self._run())

    @staticmethod
    def stale_connections(listing: str) -> list[str]:
        """Addresses of DEVICE_NAME in `bluetoothctl devices Connected` output."""
        found = []
        for line in listing.splitlines():
            parts = line.strip().split(" ", 2)
            if len(parts) == 3 and parts[0] == "Device" and parts[2].strip() == DEVICE_NAME:
                found.append(parts[1])
        return found

    def _drop_stale_connection(self) -> None:
        """A board still connected at the BlueZ level (left over from a previous gateway process, e.g.
        after `systemctl restart`) does not advertise, so scanning never finds it. Disconnect it so it
        advertises again; the next scan then connects normally."""
        try:
            listing = subprocess.run(["bluetoothctl", "devices", "Connected"], capture_output=True,
                                     text=True, timeout=10).stdout
            for address in self.stale_connections(listing):
                logger.warning("BLE: %s is still connected from an earlier session; disconnecting it", address)
                subprocess.run(["bluetoothctl", "disconnect", address], capture_output=True, text=True,
                               timeout=15)
                self._stats["stale_disconnects"] += 1
        except (OSError, subprocess.SubprocessError) as exc:
            logger.warning("BLE: could not check for a stale connection: %s", exc)

    async def _run(self) -> None:
        self._loop = asyncio.get_running_loop()
        misses = 0
        while not self._stop.is_set():
            try:
                devices = await self._BleakScanner.discover(timeout=4.0, service_uuids=[SERVICE_UUID])
                device = next((item for item in devices if item.name == DEVICE_NAME), None)
                if device is None:
                    misses += 1
                    if misses % 3 == 0:
                        await asyncio.get_running_loop().run_in_executor(None, self._drop_stale_connection)
                    continue
                misses = 0
                await self._connect_device(device)
            except (self._BleakError, OSError, asyncio.TimeoutError) as exc:
                self._last_error = f"{type(exc).__name__}: {exc}"
                logger.warning("BLE scan/connect failed: %s", self._last_error)
                self._stats["reconnects"] += 1
                self._stop.wait(2.0)

    async def _connect_device(self, device) -> None:
        loop = asyncio.get_running_loop()
        disconnected = asyncio.Event()
        client = self._BleakClient(
            device,
            pair=True,
            timeout=10.0,
            disconnected_callback=lambda _: loop.call_soon_threadsafe(disconnected.set),
        )
        self._ble_client = client
        self._assembler = BleFrameAssembler()
        try:
            await client.connect()
            await client.start_notify(FRAME_UUID, self._on_notification)
            self._mtu = self._negotiated_mtu(client)
            self._ble_connected = True
            self._last_ble_frame = time.monotonic()
            self._last_error = None
            self._publish_ble_status("online")
            logger.info("BLE connected to %s", DEVICE_NAME)

            while client.is_connected and not disconnected.is_set() and not self._stop.is_set():
                if self._last_ble_frame is not None and time.monotonic() - self._last_ble_frame > BLE_TIMEOUT_S:
                    self._publish_ble_status("offline")
                await asyncio.sleep(1.0)
        finally:
            was_connected = self._ble_connected
            self._ble_connected = False
            self._ble_client = None
            self._mtu = None
            if was_connected:
                self._publish_ble_status("offline")
                logger.info("BLE disconnected from %s", DEVICE_NAME)
            if client.is_connected:
                await client.disconnect()

    @staticmethod
    def _negotiated_mtu(client) -> Optional[int]:
        """ATT MTU of the connection. BlueZ exchanges the MTU itself after connecting and (BlueZ 5.62+)
        reports it on the characteristic; until then 23 applies and commands use 16-byte frames."""
        try:
            char = client.services.get_characteristic(FRAME_UUID)
            return int(char.max_write_without_response_size) + 3 if char is not None else None
        except Exception:  # noqa: BLE001 - older BlueZ/bleak: keep the safe default
            return None

    def _is_duplicate(self, kind: str, sequence: int, payload: bytes) -> bool:
        """The same complete message (kind, sequence, content) seen again within 10 s is a duplicate
        delivery and is not forwarded twice."""
        now = time.monotonic()
        for key, seen in list(self._recent_messages.items()):
            if now - seen > 10.0:
                del self._recent_messages[key]
        key = (kind, sequence, hashlib.blake2s(payload, digest_size=8).hexdigest())
        if key in self._recent_messages:
            return True
        self._recent_messages[key] = now
        return False

    def _on_notification(self, _characteristic, data: bytearray) -> None:
        frame = bytes(data)
        if len(frame) >= FRAME_HEADER_SIZE:
            self._recent_frames.append([round(time.monotonic(), 3), chr(frame[0]) if 32 <= frame[0] < 127 else frame[0],
                                        frame[1], frame[2], frame[3], len(frame)])
        try:
            complete = self._assembler.feed(frame)
        except ValueError as exc:
            self._stats["invalid_frames"] += 1
            self._last_error = str(exc)
            logger.warning("Invalid BLE frame: %s", exc)
            return
        if complete is None:
            return
        kind, payload = complete
        self._last_ble_frame = time.monotonic()
        if self._is_duplicate(kind, frame[1], payload):
            self._stats["duplicate_messages"] += 1
            return
        self._publish_ble_status("online")

        try:
            message = json.loads(payload.decode("utf-8"))
        except (UnicodeDecodeError, ValueError) as exc:
            self._last_error = f"invalid BLE JSON: {exc}"
            logger.warning("%s", self._last_error)
            return

        if not isinstance(message, dict):
            self._last_error = "BLE message is not a JSON object"
            logger.warning("%s", self._last_error)
            return
        if kind == "T":
            if message.get("room_id") != ROOM_ID or message.get("schema") != "sb.telemetry/1":
                self._last_error = "BLE telemetry has an unexpected room or schema"
                logger.warning("%s", self._last_error)
                return
            self._publish_mqtt(TELEMETRY_TOPIC, payload)
            self._stats["telemetry"] += 1
        elif kind == "A":
            if message.get("schema") != "sb.ack/1" or not isinstance(message.get("msg_id"), str):
                self._last_error = "BLE acknowledgement has an invalid schema or message id"
                logger.warning("%s", self._last_error)
                return
            self._publish_mqtt(ACK_TOPIC, payload)
            self._stats["acks"] += 1

    def _on_mqtt_connect(self, client, _userdata, _flags, reason_code, _properties=None) -> None:
        if getattr(reason_code, "is_failure", False):
            self._last_error = f"MQTT connect refused: {reason_code}"
            logger.error("BLE gateway MQTT connect refused: %s", reason_code)
            return
        with self._lock:
            self._mqtt_connected = True
            self._mqtt_connected_at = time.monotonic()
        client.subscribe([(COMMAND_TOPIC, 1), (STATUS_TOPIC, 1)])
        self._flush_pending()
        if self._ble_connected:
            self._published_ble_status = None
            self._publish_ble_status("online")
        logger.info("BLE gateway connected to MQTT %s:%d", self.host, self.port)

    def _on_mqtt_disconnect(self, _client, _userdata, _flags, reason_code, _properties=None) -> None:
        with self._lock:
            self._mqtt_connected = False
            self._mqtt_connected_at = None
            self._board_mqtt_online = None
        if not self._stop.is_set():
            logger.warning("BLE gateway MQTT disconnected (%s); reconnecting", reason_code)

    def _on_mqtt_message(self, _client, _userdata, message) -> None:
        if message.topic == STATUS_TOPIC:
            try:
                state = json.loads(message.payload.decode("utf-8")).get("state")
            except (UnicodeDecodeError, ValueError, AttributeError):
                return
            if state not in ("online", "offline"):
                return
            with self._lock:
                self._board_mqtt_online = state == "online"
                self._published_ble_status = None
                ble_connected = self._ble_connected
            if state == "offline" and ble_connected:
                self._publish_ble_status("online")
            return

        if message.topic != COMMAND_TOPIC:
            return
        if not self._should_forward_ble_command():
            return
        try:
            command = json.loads(message.payload.decode("utf-8"))
            if not isinstance(command, dict) or command.get("schema") != "sb.command/1":
                raise ValueError("unexpected command schema")
            payload = message.payload
            if len(payload) > MAX_MESSAGE_SIZE:
                raise ValueError("command exceeds BLE message limit")
        except (UnicodeDecodeError, ValueError) as exc:
            self._last_error = f"invalid MQTT command for BLE: {exc}"
            logger.warning("%s", self._last_error)
            return

        loop = self._loop
        client = self._ble_client
        if loop is None or client is None or not client.is_connected:
            return
        self._mtu = self._negotiated_mtu(client) or self._mtu
        self._tx_sequence = (self._tx_sequence + 1) & 0xFF
        future = asyncio.run_coroutine_threadsafe(
            self._write_command(client, self._tx_sequence, payload), loop
        )
        future.add_done_callback(self._command_written)

    def _should_forward_ble_command(self) -> bool:
        with self._lock:
            if not self._mqtt_connected or not self._ble_connected:
                return False
            if self.redundant:
                return True
            if self._board_mqtt_online is True:
                return False
            if self._board_mqtt_online is False:
                return True
            connected_at = self._mqtt_connected_at
        return connected_at is not None and time.monotonic() - connected_at >= MQTT_STATUS_GRACE_S

    async def _write_command(self, client, sequence: int, payload: bytes) -> None:
        for frame in encode_frames("C", sequence, payload, frame_data_size(self._mtu)):
            await client.write_gatt_char(FRAME_UUID, frame, response=True)

    def _command_written(self, future) -> None:
        try:
            future.result()
            self._stats["commands"] += 1
        except (self._BleakError, OSError, asyncio.TimeoutError) as exc:
            self._last_error = f"BLE command write failed: {type(exc).__name__}: {exc}"
            logger.error("%s", self._last_error)

    def _publish_ble_status(self, state: str) -> None:
        with self._lock:
            board_online = self._board_mqtt_online
            mqtt_online = self._mqtt_connected
            if self._published_ble_status == state:
                return
            self._published_ble_status = state
        if not board_online and mqtt_online and self.client is not None:
            self.client.publish(BLE_STATUS_TOPIC, json.dumps({"state": state}), qos=1, retain=True)

    def _publish_mqtt(self, topic: str, payload: bytes) -> None:
        with self._lock:
            mqtt_online = self._mqtt_connected
            if not mqtt_online:
                if len(self._pending_mqtt) == self._pending_mqtt.maxlen:
                    self._stats["dropped"] += 1
                self._pending_mqtt.append((topic, payload))
                return
        info = self.client.publish(topic, payload, qos=1)
        if info.rc != 0:
            with self._lock:
                if len(self._pending_mqtt) == self._pending_mqtt.maxlen:
                    self._stats["dropped"] += 1
                self._pending_mqtt.append((topic, payload))

    def _flush_pending(self) -> None:
        with self._lock:
            pending = list(self._pending_mqtt)
            self._pending_mqtt.clear()
        for index, (topic, payload) in enumerate(pending):
            info = self.client.publish(topic, payload, qos=1)
            if info.rc != 0:
                with self._lock:
                    for item in reversed(pending[index:]):
                        if len(self._pending_mqtt) == self._pending_mqtt.maxlen:
                            self._pending_mqtt.pop()
                            self._stats["dropped"] += 1
                        self._pending_mqtt.appendleft(item)
                break


def mqtt_topic(kind: str) -> str:
    """Return one of this room's MQTT topics for tests and diagnostics."""
    if kind == "telemetry":
        return TELEMETRY_TOPIC
    if kind == "command":
        return COMMAND_TOPIC
    if kind == "ack":
        return ACK_TOPIC
    if kind == "status":
        return STATUS_TOPIC
    raise ValueError(f"unsupported MQTT topic kind: {kind!r}")
