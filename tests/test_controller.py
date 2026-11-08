import hashlib
import json
import tempfile
import threading
import unittest
from unittest.mock import Mock
from pathlib import Path

from controller import Controller


class ControllerTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.c = Controller(Path(self.tmp.name))

    def tearDown(self):
        self.tmp.cleanup()

    def test_saved_evidence_and_readback(self):
        r = self.c.run_simulation({})
        folder = Path(self.tmp.name) / "runs" / r["id"]
        manifest = json.loads((folder / "manifest.json").read_text())
        self.assertEqual(r["summary"]["source"], "simulated")
        self.assertEqual(r["config"], r["readback"])
        for name, digest in manifest["sha256"].items():
            self.assertEqual(hashlib.sha256((folder/name).read_bytes()).hexdigest(), digest)
        self.assertEqual(len((folder/"raw.csv").read_text().splitlines()), 20001)
        self.assertFalse(self.c.status()["simulation_outputs_enabled"])

    def test_stop_latches_until_explicit_user_reset(self):
        self.c.stop()
        with self.assertRaises(InterruptedError):
            self.c.run_simulation({})
        with self.assertRaises(InterruptedError):
            self.c.dispatch("run_simulation", {}, threading.Event())
        self.c.reset()
        self.assertEqual(self.c.run_simulation({})["summary"]["verdict"], "PASS")

    def test_hardware_and_arbitrary_tools_never_executed(self):
        for name in ("run_script", "power_write", "start_scopy", "set_output", "__import__"):
            with self.subTest(name=name), self.assertRaises(ValueError):
                self.c.dispatch(name, {}, threading.Event())

    def test_cancelled_task_leaves_no_evidence(self):
        cancelled = threading.Event()
        cancelled.set()
        with self.assertRaises(InterruptedError):
            self.c.run_simulation({}, cancelled=cancelled)
        self.assertFalse((Path(self.tmp.name)/"runs").exists())

    def test_model_never_receives_raw_waveforms(self):
        r = self.c.dispatch("run_simulation", {}, threading.Event())
        self.assertIn("summary", r)
        self.assertNotIn("preview", r)
        self.assertNotIn("raw", r)

    def test_no_claim_of_physical_outputs_off(self):
        self.assertEqual(self.c.status()["hardware_outputs"], "unknown")

    def test_old_generation_cannot_overwrite_reset_state(self):
        old = self.c.generation
        self.c.stop(); self.c.reset()
        with self.assertRaises(InterruptedError):
            self.c.run_simulation({},generation=old)
        self.assertEqual(self.c.status()["phase"],"ready")
        self.assertFalse(self.c.status()["stopped"])

    def test_model_readonly_probe_is_fresh_and_marks_cache(self):
        client=Mock()
        client.probe.side_effect=[{"connected":True,"snapshot":{"vplus_enabled":"false"},"message":"read"},
                                  {"connected":False,"error_code":"disconnected","message":"lost"}]
        c=Controller(Path(self.tmp.name),hardware_client=client)
        r=c.dispatch("check_scopy_readonly",{},threading.Event())
        self.assertTrue(r["connected"])
        self.assertTrue(r["read_only"])
        self.assertFalse(r["cached"])
        self.assertIn("time",r)
        self.assertEqual(client.probe.call_count,1)
        cached=c.dispatch("get_status",{},threading.Event())
        self.assertTrue(cached["hardware"]["cached"])
        self.assertEqual(client.probe.call_count,1)
        r=c.dispatch("check_scopy_readonly",{},threading.Event())
        self.assertFalse(r["connected"])
        self.assertNotIn("snapshot",r)
        self.assertEqual(r["outputs"],"unknown")

    def test_probe_cancel_cannot_commit_after_reset(self):
        client=Mock()
        def probe(**kwargs):
            self.c.stop();self.c.reset()
            return {"connected":True,"snapshot":{"vplus_enabled":"true"}}
        client.probe.side_effect=probe
        self.c.hardware_client=client
        with self.assertRaises(InterruptedError):
            self.c.dispatch("check_scopy_readonly",{},threading.Event())
        self.assertFalse(self.c.hardware["connected"])
        self.assertFalse(self.c.hardware.get("pending",False))
        self.assertEqual(self.c.phase,"ready")

    def test_probe_rejects_model_supplied_mcp_arguments(self):
        client=Mock()
        c=Controller(Path(self.tmp.name),hardware_client=client)
        for args in ({"method":"runScript"},{"device_id":"0"},{"enable_power":True}):
            with self.assertRaises(ValueError):
                c.dispatch("check_scopy_readonly",args,threading.Event())
        client.probe.assert_not_called()

    def test_unexpected_probe_failure_does_not_leave_pending_snapshot(self):
        client=Mock();client.probe.side_effect=RuntimeError("untrusted diagnostic")
        c=Controller(Path(self.tmp.name),hardware_client=client)
        result=c.check_hardware()
        self.assertFalse(result["connected"])
        self.assertFalse(result["pending"])
        self.assertNotIn("untrusted diagnostic",str(result))
