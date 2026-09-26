"""Small MQTT-to-SQLite gateway with a local HTTP health API."""
import json
import os
import sqlite3
import threading
from datetime import datetime, timezone
from pathlib import Path

import paho.mqtt.client as mqtt
from fastapi import FastAPI

DB_PATH = Path(os.getenv('GATEWAY_DB', 'gateway.db'))
MQTT_HOST = os.getenv('MQTT_HOST', '127.0.0.1')
MQTT_PORT = int(os.getenv('MQTT_PORT', '1883'))
MQTT_TOPIC = os.getenv('MQTT_TOPIC', 'devices/+/health')
HTTP_HOST = os.getenv('HTTP_HOST', '127.0.0.1')
HTTP_PORT = int(os.getenv('HTTP_PORT', '8081'))

db_lock = threading.Lock()
app = FastAPI(title='M5 Embedded Linux Gateway', version='0.1.0')


def init_db():
    with sqlite3.connect(DB_PATH) as db:
        db.execute('''CREATE TABLE IF NOT EXISTS telemetry (
          id INTEGER PRIMARY KEY AUTOINCREMENT,
          received_at TEXT NOT NULL,
          topic TEXT NOT NULL,
          device_id TEXT NOT NULL,
          payload_json TEXT NOT NULL
        )''')
        db.execute('CREATE INDEX IF NOT EXISTS idx_telemetry_device_time ON telemetry(device_id, received_at)')


def store_message(topic, payload):
    try:
        parsed = json.loads(payload.decode('utf-8'))
        device_id = str(parsed['device_id'])
    except (UnicodeDecodeError, json.JSONDecodeError, KeyError, TypeError):
        return False
    received_at = datetime.now(timezone.utc).isoformat()
    with db_lock, sqlite3.connect(DB_PATH) as db:
        db.execute('INSERT INTO telemetry(received_at,topic,device_id,payload_json) VALUES(?,?,?,?)',
                   (received_at, topic, device_id, json.dumps(parsed, separators=(',', ':'))))
    return True


def on_connect(client, userdata, flags, reason_code, properties=None):
    print(f'MQTT connected: {reason_code}', flush=True)
    client.subscribe(MQTT_TOPIC, qos=1)
    print(f'Subscribed: {MQTT_TOPIC}', flush=True)


def on_message(client, userdata, message):
    if store_message(message.topic, message.payload):
        print(f'Stored {message.topic}', flush=True)
    else:
        print(f'Ignored invalid telemetry: {message.topic}', flush=True)


def start_mqtt():
    client = mqtt.Client(mqtt.CallbackAPIVersion.VERSION2, client_id='m5-linux-gateway')
    client.on_connect = on_connect
    client.on_message = on_message
    client.connect(MQTT_HOST, MQTT_PORT, keepalive=30)
    client.loop_start()
    return client


@app.get('/health')
def health():
    with db_lock, sqlite3.connect(DB_PATH) as db:
        count = db.execute('SELECT COUNT(*) FROM telemetry').fetchone()[0]
        latest = db.execute('SELECT device_id,received_at FROM telemetry ORDER BY id DESC LIMIT 1').fetchone()
    return {'gateway': 'ok', 'messages': count,
            'latest_device': latest[0] if latest else None,
            'latest_received_at': latest[1] if latest else None}


@app.get('/devices')
def devices():
    with db_lock, sqlite3.connect(DB_PATH) as db:
        rows = db.execute('''SELECT device_id, MAX(received_at), COUNT(*)
                             FROM telemetry GROUP BY device_id ORDER BY device_id''').fetchall()
    return [{'device_id': row[0], 'last_seen': row[1], 'messages': row[2]} for row in rows]


def main():
    import uvicorn
    init_db()
    mqtt_client = start_mqtt()
    try:
        uvicorn.run(app, host=HTTP_HOST, port=HTTP_PORT)
    finally:
        mqtt_client.loop_stop()
        mqtt_client.disconnect()


if __name__ == '__main__':
    main()
