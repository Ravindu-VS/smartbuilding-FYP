import time

import pytest

from raspberry_pi.ble_gateway import (
    MAX_FRAME_COUNT,
    MQTT_STATUS_GRACE_S,
    BleFrameAssembler,
    BleGateway,
    encode_frames,
)


def test_ble_frames_reassemble_out_of_order_at_message_limit():
    payload = bytes(range(256)) * 4
    frames = encode_frames("T", 255, payload)
    assembler = BleFrameAssembler()

    complete = None
    for frame in reversed(frames):
        complete = assembler.feed(frame) or complete

    assert len(frames) == 64
    assert complete == ("T", payload)


@pytest.mark.parametrize(
    "kind,sequence,payload",
    [
        ("X", 0, b"data"),
        ("T", 256, b"data"),
        ("T", 0, b""),
        ("T", 0, b"x" * 1025),
    ],
)
def test_ble_frame_encoder_rejects_invalid_messages(kind, sequence, payload):
    with pytest.raises(ValueError):
        encode_frames(kind, sequence, payload)


def test_ble_assembler_rejects_invalid_frame_header():
    assembler = BleFrameAssembler()

    with pytest.raises(ValueError, match="invalid BLE frame header"):
        assembler.feed(b"T\x01\x01\x01x")


def test_ble_assembler_rejects_frame_count_above_message_limit():
    frame = bytes((ord("T"), 1, 0, MAX_FRAME_COUNT + 1)) + b"x"

    with pytest.raises(ValueError, match="invalid BLE frame header"):
        BleFrameAssembler().feed(frame)


def test_ble_command_fallback_waits_for_direct_mqtt_status():
    gateway = BleGateway(redundant=False)
    gateway._mqtt_connected = True
    gateway._ble_connected = True
    gateway._mqtt_connected_at = time.monotonic()

    assert not gateway._should_forward_ble_command()

    gateway._mqtt_connected_at -= MQTT_STATUS_GRACE_S + 0.1

    assert gateway._should_forward_ble_command()

    gateway._board_mqtt_online = True
    assert not gateway._should_forward_ble_command()

    gateway._board_mqtt_online = False
    assert gateway._should_forward_ble_command()


def test_redundant_mode_forwards_every_command_while_ble_is_up():
    gateway = BleGateway(redundant=True)
    gateway._mqtt_connected = True
    gateway._ble_connected = False
    assert not gateway._should_forward_ble_command()
    gateway._ble_connected = True
    gateway._board_mqtt_online = True
    assert gateway._should_forward_ble_command()


def test_mqtt_queue_requeues_failed_and_unsent_messages_in_order():
    class FakeClient:
        def __init__(self):
            self.results = [0, 1]
            self.published = []

        def publish(self, topic, payload, qos):
            self.published.append((topic, payload, qos))
            return type("PublishResult", (), {"rc": self.results.pop(0)})()

    gateway = BleGateway()
    gateway.client = FakeClient()
    gateway._pending_mqtt.extend([("t/1", b"one"), ("t/2", b"two"), ("t/3", b"three")])

    gateway._flush_pending()

    assert gateway.client.published == [("t/1", b"one", 1), ("t/2", b"two", 1)]
    assert list(gateway._pending_mqtt) == [("t/2", b"two"), ("t/3", b"three")]


def test_frames_use_negotiated_mtu_and_reassemble():
    from raspberry_pi.ble_gateway import MAX_FRAME_DATA_SIZE, frame_data_size

    payload = bytes(range(256)) * 3 + b"tail"
    chunk = frame_data_size(247)
    frames = encode_frames("T", 7, payload, chunk)
    assembler = BleFrameAssembler()
    complete = None
    for frame in frames:
        complete = assembler.feed(frame) or complete

    assert chunk == MAX_FRAME_DATA_SIZE == 240
    assert len(frames) == 4 and max(len(f) for f in frames) == 244
    assert complete == ("T", payload)


def test_frame_size_falls_back_to_default_mtu():
    from raspberry_pi.ble_gateway import FRAME_DATA_SIZE, frame_data_size

    assert frame_data_size(None) == frame_data_size(23) == FRAME_DATA_SIZE
    assert frame_data_size(100) == 93
    assert frame_data_size(517) == 240


def test_assembler_rejects_frames_longer_than_the_largest_mtu_frame():
    with pytest.raises(ValueError, match="invalid BLE frame length"):
        BleFrameAssembler().feed(b"T\x01\x00\x01" + b"x" * 241)


def test_encoder_rejects_chunk_outside_supported_range():
    with pytest.raises(ValueError):
        encode_frames("C", 1, b"data", 15)
    with pytest.raises(ValueError):
        encode_frames("C", 1, b"data", 241)


def test_gateway_forwards_a_repeated_delivery_only_once():
    from raspberry_pi.ble_gateway import BleGateway

    gw = BleGateway()
    published = []
    gw._publish_mqtt = lambda topic, payload: published.append(topic)
    gw._publish_ble_status = lambda state: None
    ack = b'{"schema":"sb.ack/1","msg_id":"m1","status":"applied"}'
    frame = encode_frames("A", 9, ack, 240)[0]
    for _ in range(5):
        gw._on_notification(None, bytearray(frame))
    gw._on_notification(None, bytearray(encode_frames("A", 10, ack, 240)[0]))   # a new sequence is a new message

    assert published.count("sb/v1/room/f2_office_a/ack") == 2
    assert gw.status()["stats"]["duplicate_messages"] == 4
    assert gw.status()["recent_frames"][-1][1:5] == ["A", 10, 0, 1]


def test_stale_connection_listing_is_parsed():
    listing = "Device 24:58:7C:DE:86:29 SB-Room101\nDevice AA:BB:CC:DD:EE:FF Headphones\n"
    assert BleGateway.stale_connections(listing) == ["24:58:7C:DE:86:29"]
    assert BleGateway.stale_connections("") == []
