import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch


class GatewayTests(unittest.TestCase):
    def test_store_valid_message(self):
        with tempfile.TemporaryDirectory() as folder:
            import gateway
            with patch.object(gateway, 'DB_PATH', Path(folder) / 'test.db'):
                gateway.init_db()
                self.assertTrue(gateway.store_message(
                    'devices/m5-device-01/health',
                    json.dumps({'device_id': 'm5-device-01', 'uptime_s': 10}).encode()))
                db = gateway.sqlite3.connect(gateway.DB_PATH)
                try:
                    self.assertEqual(db.execute('SELECT COUNT(*) FROM telemetry').fetchone()[0], 1)
                finally:
                    db.close()

    def test_invalid_message_is_rejected(self):
        with tempfile.TemporaryDirectory() as folder:
            import gateway
            with patch.object(gateway, 'DB_PATH', Path(folder) / 'test.db'):
                gateway.init_db()
                self.assertFalse(gateway.store_message('devices/x/health', b'{"uptime_s": 10}'))


if __name__ == '__main__':
    unittest.main()
