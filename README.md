# M5 Embedded Linux Gateway

A small Linux gateway for M5 devices: MQTT in, SQLite storage, local HTTP health API out. It is designed to run first in WSL2 Ubuntu and later on a Raspberry Pi without changing the application code.

## Current milestone

The gateway subscribes to `devices/+/health`, validates JSON telemetry, stores it in SQLite, and exposes:

- `GET /health` — gateway and latest-message status
- `GET /devices` — devices seen and message counts

It does not modify the device, publish commands, or expose the database to the network.

## Run it in WSL2 Ubuntu

```bash
cd /mnt/d/m5-embedded-linux-gateway
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
export MQTT_HOST=192.168.1.156
export MQTT_PORT=1883
python gateway.py
```

In another terminal:

```bash
curl http://127.0.0.1:8081/health
curl http://127.0.0.1:8081/devices
```

The MQTT broker must already be running and reachable from WSL2. For the secure project, the next milestone will add TLS certificates through environment variables; certificates and passwords will never be committed.

## Checks

```bash
python -m unittest -v
```

The tests cover valid telemetry storage and rejection of payloads without a device ID. Future milestones will add TLS MQTT, offline buffering, reconnect behavior, Docker, systemd, and gateway-to-device commands.
