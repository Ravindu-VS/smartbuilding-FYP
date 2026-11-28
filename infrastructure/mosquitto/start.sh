#!/bin/sh
# Creates the password file from the environment, then starts Mosquitto (which drops to the mosquitto user).
set -eu
PASSWD=/mosquitto/data/passwd
: > "$PASSWD"
add() {   # add <user> <password>
  [ -n "$2" ] || { echo "start.sh: password for MQTT user '$1' is empty" >&2; exit 1; }
  mosquitto_passwd -b "$PASSWD" "$1" "$2"
}
add edge   "${MQTT_EDGE_PASSWORD:-}"
add device "${MQTT_DEVICE_PASSWORD:-}"
add ingest "${MQTT_INGEST_PASSWORD:-}"
chown mosquitto:mosquitto "$PASSWD" /mosquitto/data
chmod 0600 "$PASSWD"
exec mosquitto -c /mosquitto/config/mosquitto.conf
