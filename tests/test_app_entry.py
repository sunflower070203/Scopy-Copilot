import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from app_entry import run_self_test


class EntryTests(unittest.TestCase):
    def test_packaged_self_test_is_offline_and_saves_evidence(self):
        with tempfile.TemporaryDirectory() as folder,patch("app_entry.default_data_dir",return_value=Path(folder)):
            with patch("app_entry.ScopyClient") as client:
                client.return_value.inventory.return_value={"tool_count":103,"m2k_tools":["power_read"]}
                report=run_self_test()
                self.assertEqual(report["simulation"]["verdict"],"PASS")
                self.assertFalse(report["external_api_called"])
                self.assertEqual(report["hardware_write_calls"],0)
                self.assertTrue(report["tk_created"])
                self.assertTrue((Path(folder)/"self-test.json").is_file())
                client.return_value.probe.assert_not_called()
