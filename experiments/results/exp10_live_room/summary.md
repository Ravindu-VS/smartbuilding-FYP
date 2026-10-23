# Experiment 10 - Live-room integration (test harness)

Test harness: HTTP test payload and raspberry_pi/mqtt_device_sim.py over a local MQTT broker (amqtt). **Physical verification with the ESP32-S3 board: not performed in this environment (no board attached).**

| check | result |
|---|---|
| no board: room 101 shown as never connected | PASS |
| HTTP reading accepted and a decision returned | PASS |
| room 101 connected, values shown exactly | PASS |
| test-sender data labelled synthetic, not measured | PASS |
| edge connected to the MQTT broker | PASS |
| device harness ran | PASS |
| 36 unique readings accepted, 4 duplicates dropped | PASS |
| out-of-range values dropped and reported | PASS |
| every command acknowledged | PASS |
| readings stored with provenance synthetic (harness) | PASS |
| no harness reading stored as room101_measured | PASS |
| MQTT status endpoint reports the bridge | PASS |
| silent board -> room shown as lost, no values | PASS |

Bridge statistics: {"received": 40, "accepted": 36, "rejected": 0, "duplicates": 4, "commands_sent": 36, "acks": 36, "ack_timeouts": 0, "reconnects": 0, "field_problems": 3}

Store: {"readings": 37, "decisions": 37, "events": 1, "predictions": 0, "commands": 36, "room_snapshots": 0}
