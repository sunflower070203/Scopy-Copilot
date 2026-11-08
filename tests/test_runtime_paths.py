import os
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

from runtime_paths import bundle_root,default_data_dir,bundled_bridge_path
from scopy import ScopyClient,StdioSession


class RuntimeTests(unittest.TestCase):
    def test_frozen_data_lives_in_user_directory(self):
        with tempfile.TemporaryDirectory() as temp:
            with patch.object(sys,"frozen",True,create=True),patch.dict(os.environ,{"LOCALAPPDATA":temp}):
                self.assertEqual(default_data_dir(),Path(temp)/"ScopyCopilot"/"data")

    def test_frozen_bridge_is_next_to_main_app(self):
        with patch.object(sys,"frozen",True,create=True),patch.object(sys,"executable",str(Path("C:/portable app/Scopy-Copilot.exe"))):
            expected=Path(sys.executable).parent/"bridge"/"Scopy-MCP-Bridge.exe"
            self.assertEqual(bundled_bridge_path(),expected)
            client=ScopyClient()
            self.assertTrue(client.packaged)
            self.assertEqual(Path(client.python),expected)
            self.assertEqual(StdioSession(client.python,packaged=True).command(),[str(expected)])

    def test_explicit_python_keeps_source_bridge_command(self):
        client=ScopyClient(bridge_python="dev-python")
        self.assertFalse(client.packaged)
        command=StdioSession(client.python).command()
        self.assertEqual(command[:3],["dev-python","-u","-c"])

    def test_resources_are_separate_from_userdata(self):
        with tempfile.TemporaryDirectory() as temp:
            with patch.object(sys,"_MEIPASS",str(Path(temp)/"resources"),create=True),patch.object(sys,"frozen",True,create=True),patch.dict(os.environ,{"LOCALAPPDATA":temp}):
                self.assertEqual(bundle_root(),Path(temp)/"resources")
                self.assertNotEqual(default_data_dir().parent,bundle_root())
