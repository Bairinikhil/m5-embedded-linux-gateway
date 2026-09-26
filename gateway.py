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
MQTT_TLS = os.getenv('MQTT_TLS', '').lower() in {'1', 'true', 'yes', 'on'}
MQTT_TLS_CA = os.getenv('MQTT_TLS_CA', '')
MQTT_TLS_CERT = os.getenv('MQTT_TLS_CERT', '')
MQTT_TLS_KEY = os.getenv('MQTT_TLS_KEY', '')
HTTP_HOST = os.getenv('HTTP_HOST', '127.0.0.1')
HTTP_PORT = int(os.getenv('HTTP_PORT', '8081'))

db_lock = threading.Lock()
app = FastAPI(title='M5 Embedded Linux Gateway', version='0.1.0')


def init_db():
    db = sqlite3.connect(DB_PATH)
    try:
        db.execute('''CREATE TABLE IF NOT EXISTS telemetry (
          id INTEGER PRIMARY KEY AUTOINCREMENT,
          received_at TEXT NOT NULL,
          topic TEXT NOT NULL,
          device_id TEXT NOT NULL,
          payload_json TEXT NOT NULL
        )''')
        db.execute('CREATE INDEX IF NOT EXISTS idx_telemetry_device_time ON telemetry(device_id, received_at)')
        db.commit()
    finally:
        db.close()


def store_message(topic, payload):
    try:
        parsed = json.loads(payload.decode('utf-8'))
        device_id = str(parsed['device_id'])
    except (UnicodeDecodeError, json.JSONDecodeError, KeyError, TypeError):
        return False
    received_at = datetime.now(timezone.utc).isoformat()
    with db_lock:
        db = sqlite3.connect(DB_PATH)
        try:
            db.execute('INSERT INTO telemetry(received_at,topic,device_id,payload_json) VALUES(?,?,?,?)',
                       (received_at, topic, device_id, json.dumps(parsed, separators=(',', ':'))))
            db.commit()
        finally:
            db.close()
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


def configure_tls(client):
    paths = {'MQTT_TLS_CA': MQTT_TLS_CA, 'MQTT_TLS_CERT': MQTT_TLS_CERT, 'MQTT_TLS_KEY': MQTT_TLS_KEY}
    missing = [name for name, value in paths.items() if not value]
    if missing:
        raise RuntimeError(f'MQTT_TLS is enabled but missing: {", ".join(missing)}')
    missing_files = [f'{name}={value}' for name, value in paths.items() if not Path(value).is_file()]
    if missing_files:
        raise RuntimeError('MQTT TLS file not found: ' + ', '.join(missing_files))
    client.tls_set(ca_certs=MQTT_TLS_CA, certfile=MQTT_TLS_CERT, keyfile=MQTT_TLS_KEY)
    print('MQTT TLS enabled with certificate verification', flush=True)


def start_mqtt():
    client = mqtt.Client(mqtt.CallbackAPIVersion.VERSION2, client_id='m5-linux-gateway')
    if MQTT_TLS:
        configure_tls(client)
    client.on_connect = on_connect
    client.on_message = on_message
    client.connect(MQTT_HOST, MQTT_PORT, keepalive=30)
    client.loop_start()
    return client


@app.get('/health')
def health():
    with db_lock:
        db = sqlite3.connect(DB_PATH)
        try:
            count = db.execute('SELECT COUNT(*) FROM telemetry').fetchone()[0]
            latest = db.execute('SELECT device_id,received_at FROM telemetry ORDER BY id DESC LIMIT 1').fetchone()
        finally:
            db.close()
    return {'gateway': 'ok', 'messages': count,
            'latest_device': latest[0] if latest else None,
            'latest_received_at': latest[1] if latest else None}


@app.get('/devices')
def devices():
    with db_lock:
        db = sqlite3.connect(DB_PATH)
        try:
            rows = db.execute('''SELECT device_id, MAX(received_at), COUNT(*)
                                 FROM telemetry GROUP BY device_id ORDER BY device_id''').fetchall()
        finally:
            db.close()
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
