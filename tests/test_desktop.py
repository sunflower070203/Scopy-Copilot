import tempfile
import time
import tkinter as tk
import unittest
from pathlib import Path
from unittest.mock import Mock,patch
from desktop_widgets import replace_text

from controller import Controller
from desktop import DesktopApp


class DesktopTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory()
        self.root=tk.Tk();self.root.withdraw()
        client=Mock();client.probe.return_value={"connected":True,"snapshot":{"vplus_enabled":"false","vplus_setting":"3.3"},"message":"真实只读测试"}
        self.controller=Controller(Path(self.tmp.name),hardware_client=client)
        self.app=DesktopApp(self.root,self.controller)
        self.root.update()

    def tearDown(self):
        self.app.close();self.tmp.cleanup()

    def wait_idle(self):
        deadline=time.monotonic()+5
        while self.app.busy and time.monotonic()<deadline:
            self.root.update();time.sleep(.01)
        self.assertFalse(self.app.busy)
        self.root.update()

    def test_native_window_collapse_and_topmost(self):
        self.assertFalse(self.app.collapsed)
        self.app.toggle_collapsed();self.root.update()
        self.assertTrue(self.app.collapsed)
        self.assertFalse(self.app.content.winfo_ismapped())
        self.app.toggle_collapsed();self.root.update()
        self.assertFalse(self.app.collapsed)
        self.app.pinned.set(False);self.app.apply_pin()
        self.assertFalse(self.root.attributes('-topmost'))

    def test_simulation_and_readonly_actions(self):
        self.app.run_simulation();self.wait_idle()
        self.assertEqual(self.controller.last["summary"]["verdict"],"PASS")
        self.app.check_hardware();self.wait_idle()
        self.assertTrue(self.controller.hardware["connected"])
        self.assertIn("3.3",self.app.hardware_text.get("1.0","end"))

    def test_password_dialog_does_not_echo_key(self):
        self.app.settings.update({"api_key":"test-secret-key"})
        dialog=self.app.open_settings();self.root.update()
        self.assertEqual(dialog.key.get(),"")
        self.assertEqual(dialog.key_entry.cget("show"),"●")
        dialog.clear_key()
        self.assertFalse(self.app.settings.public()["has_key"])
        dialog.close()

    def test_offline_chat_can_invoke_fresh_probe(self):
        self.app.chat_input.insert("1.0","检查真实 Scopy 状态")
        self.app.send();self.wait_idle()
        self.controller.hardware_client.probe.assert_called_once()
        self.assertIn("真实只读检查完成",self.app.transcript.get("1.0","end"))

    def test_stop_latches_ui_until_explicit_reset(self):
        self.app.stop();self.root.update()
        self.assertTrue(self.controller.stopped.is_set())
        self.app.reset();self.root.update()
        self.assertFalse(self.controller.stopped.is_set())

    def test_queued_job_cannot_execute_after_stop_reset(self):
        queued=[]
        class DeferredThread:
            def __init__(self,target,daemon):self.target=target
            def start(self):queued.append(self.target)
            def is_alive(self):return False
        with patch("desktop.threading.Thread",DeferredThread):
            self.app.check_hardware()
            self.app.stop();self.app.reset()
            queued[0]()
        self.wait_idle()
        self.controller.hardware_client.probe.assert_not_called()
        self.assertFalse(self.controller.hardware["connected"])
        self.assertFalse(self.app.busy)

    def test_identical_status_refresh_preserves_selection(self):
        replace_text(self.app.hardware_text,"status stays the same")
        self.app.hardware_text.tag_add("sel","1.0","1.6")
        replace_text(self.app.hardware_text,"status stays the same")
        self.assertTrue(self.app.hardware_text.tag_ranges("sel"))

    def test_composer_fits_default_window_height(self):
        self.root.deiconify();self.root.update()
        self.assertTrue(self.app.send_button.winfo_ismapped(),"send button must remain visible")
        bottom=self.app.send_button.winfo_rooty()+self.app.send_button.winfo_height()
        self.assertLessEqual(bottom,self.root.winfo_rooty()+self.root.winfo_height())
        self.root.withdraw()
