import http.client
import json
import tempfile
import threading
import unittest
from pathlib import Path

from server import make_server


class ServerTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.server = make_server(0, Path(self.tmp.name))
        self.port = self.server.server_address[1]
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()

    def tearDown(self):
        self.server.shutdown()
        self.server.server_close()
        self.thread.join()
        self.tmp.cleanup()

    def request(self, method, path, body=None, headers=None):
        connection = http.client.HTTPConnection("127.0.0.1", self.port, timeout=5)
        h = {"Content-Type":"application/json", "X-Copilot-Token":self.server.token}
        h.update(headers or {})
        connection.request(method, path, body=json.dumps(body) if body is not None else None, headers=h)
        response = connection.getresponse()
        status, raw = response.status, response.read()
        connection.close()
        return status, raw

    def test_simulation_and_download(self):
        status, raw = self.request("POST", "/api/simulate", {"config":{}})
        self.assertEqual(status, 200)
        result = json.loads(raw)
        self.assertEqual(result["summary"]["verdict"], "PASS")
        code, csv = self.request("GET", f"/api/files/{result['id']}/raw.csv")
        self.assertEqual(code,200)
        self.assertIn(b"simulated",csv)

    def test_cross_origin_and_wrong_host_rejected(self):
        for headers in ({"Origin":"https://evil.example"}, {"Host":"evil.example"}, {"X-Copilot-Token":"wrong"})*5:
            status,_ = self.request("POST", "/api/simulate", {"config":{}},headers)
            self.assertEqual(status,403)

    def test_unknown_and_traversal_paths_rejected(self):
        for path in ("/api/files/../server.py", "/server.py", "/vendor/scopy-mcp-server/server.py"):
            self.assertEqual(self.request("GET",path)[0],404)

    def test_key_never_returned_or_saved(self):
        status, raw = self.request("POST", "/api/settings", {"api_key":"test-secret-key"})
        self.assertEqual(status,200)
        self.assertNotIn(b"test-secret-key",raw)
        self.assertNotIn(b"test-secret-key",self.request("GET","/api/bootstrap")[1])
        for p in Path(self.tmp.name).rglob("*"):
            if p.is_file():
                self.assertNotIn(b"test-secret-key",p.read_bytes())

    def test_stop_and_manual_reset(self):
        self.request("POST","/api/stop",{})
        self.assertEqual(self.request("POST","/api/simulate",{"config":{}})[0],409)
        self.request("POST","/api/reset",{})
        self.assertEqual(self.request("POST","/api/simulate",{"config":{}})[0],200)

    def test_invalid_config_clear_error(self):
        code,raw = self.request("POST","/api/simulate",{"config":{"voltage":5}})
        self.assertEqual(code,400)
        self.assertIn("3.3",raw.decode())

    def test_oversize_body_rejected(self):
        self.assertEqual(self.request("POST","/api/chat",{"text":"x"*40000})[0],413)
