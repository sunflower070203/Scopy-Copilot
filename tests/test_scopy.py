import json
import io
import time
import unittest
from unittest.mock import Mock, patch
from scopy import READS, ROOT, validate_read, summarize_metadata, ScopyClient, StdioSession


class ReadOnlyTests(unittest.TestCase):
    def test_fixed_read_arguments(self):
        validate_read("power_read", {"property":"dac1_enabled"})
        validate_read("dio_read", {"property":"gpi", "channel":2})
        validate_read("scopy_call", {"method":"getDevicesName"})

    def test_arbitrary_calls_and_channels_denied(self):
        for name,args in (("power_write", {"property":"dac1_enabled","value":"true"}),
                          ("scopy_call", {"method":"runScript","arg1":"x"}),
                          ("dio_read", {"property":"gpi","channel":"2];evil()"}),
                          ("power_read", {"property":"dac1_enabled", "channel":0}),
                          ("start_scopy", {}), ("connect_device", {"device_id":"0"})):
            with self.subTest(name=name), self.assertRaises(ValueError):
                validate_read(name,args)

    def test_missing_bridge_is_explicitly_not_connected(self):
        r = ScopyClient(bridge_python="missing-python").probe()
        self.assertFalse(r["connected"])
        self.assertEqual(r["outputs"], "unknown")

    def test_metadata_does_not_invent_sampling_export(self):
        summary = summarize_metadata({"objects":{"pattern":{"properties":[{"name":"enabledChannels"}]}, "logic":{"properties":[{"name":"sample_rate"}]}}})
        self.assertFalse(summary["random_frequency_control"])
        self.assertFalse(summary["raw_logic_export"])

    def test_whitelist_matches_official_version_metadata(self):
        path = ROOT/"vendor/scopy-mcp-server/scopy_mcp_server/scopy_api.json"
        if not path.is_file():
            self.skipTest("optional official bridge not installed")
        objects = json.loads(path.read_text(encoding="utf-8"))["objects"]
        for tool, props in READS.items():
            actual = {p["name"] for p in objects[tool.removesuffix("_read")]["properties"]}
            self.assertLessEqual(props,actual)

    def test_stdio_initialize_and_disconnect_error(self):
        response = [{"jsonrpc":"2.0","id":1,"result":{"protocolVersion":"2024-11-05"}},
                    {"jsonrpc":"2.0","id":2,"result":{"content":[{"type":"text","text":"No running Scopy instance found."}]}}]
        process=Mock()
        process.stdin=io.BytesIO()
        process.stdout=io.BytesIO(b"".join((json.dumps(x)+"\n").encode() for x in response))
        with patch("scopy.subprocess.Popen",return_value=process):
            with StdioSession("fake") as session:
                with self.assertRaises(ConnectionError):
                    session.read("power_read",{"property":"dac1_enabled"})
                sent=[json.loads(x) for x in process.stdin.getvalue().splitlines()]
                self.assertEqual([x["method"] for x in sent],["initialize","notifications/initialized","tools/call"])
                self.assertEqual(sent[-1]["params"]["name"],"power_read")
        process.terminate.assert_called_once()

    def test_stdio_timeout_and_eof_do_not_retry(self):
        for eof in (True,False):
            session=StdioSession("fake",timeout=.02)
            session.proc=Mock(stdin=io.BytesIO())
            if eof:session.messages.put(None)
            with self.assertRaises(ConnectionError if eof else TimeoutError):
                session.rpc("tools/list",{})
            self.assertEqual(len(session.proc.stdin.getvalue().splitlines()),1)

    def test_probe_disconnect_and_timeout_invalidate_state(self):
        for error in (ConnectionError(),TimeoutError()):
            session=Mock()
            session.rpc.return_value={"tools":[{"name":x} for x in ("scopy_call","power_read","dio_read","logic_read")]}
            session.read.side_effect=error
            context=Mock();context.__enter__=Mock(return_value=session);context.__exit__=Mock(return_value=False)
            with patch("scopy.StdioSession",return_value=context):
                result=ScopyClient(bridge_python=__file__).probe()
            self.assertFalse(result["connected"])
            self.assertEqual(result["outputs"],"unknown")
            self.assertEqual(session.read.call_count,1)

    def test_cancel_before_rpc_never_sends_command(self):
        session=StdioSession("fake",cancelled=lambda:True)
        session.proc=Mock(stdin=io.BytesIO())
        with self.assertRaises(InterruptedError):session.rpc("tools/list",{})
        self.assertEqual(session.proc.stdin.getvalue(),b"")
