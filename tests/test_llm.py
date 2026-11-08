import json
import tempfile
import threading
import time
import unittest
from pathlib import Path
from unittest.mock import Mock

from controller import Controller
from llm import ModelSettings, Chat, completion_url


class ModelTests(unittest.TestCase):
    def test_model_can_request_real_readonly_probe(self):
        requests=[]
        with tempfile.TemporaryDirectory() as d:
            client=Mock()
            client.probe.return_value={"connected":True,"snapshot":{"vplus_enabled":"false"},"message":"read"}
            c=Controller(Path(d),hardware_client=client);s=ModelSettings();s.update({"api_key":"test-secret-key"})
            def transport(url,key,body):
                requests.append(body)
                if len(requests)==1:
                    return {"choices":[{"message":{"content":None,"tool_calls":[{"id":"probe1","type":"function","function":{"name":"check_scopy_readonly","arguments":"{}"}}]}}]}
                return {"choices":[{"message":{"content":"只读检查完成，未修改输出"}}]}
            answer=Chat(c,s,transport).reply("检查真实 Scopy 状态","api")
            self.assertIn("只读",answer["text"])
            receipt=json.loads(requests[1]["messages"][-1]["content"])
            self.assertTrue(receipt["read_only"])
            self.assertFalse(receipt["cached"])
            self.assertEqual(receipt["source"],"hardware_probe")
            self.assertEqual(client.probe.call_count,1)
            names={x["function"]["name"] for x in requests[0]["tools"]}
            self.assertIn("check_scopy_readonly",names)
    def test_endpoint(self):
        self.assertEqual(completion_url("https://api.deepseek.com"), "https://api.deepseek.com/chat/completions")
        self.assertEqual(completion_url("https://example.com/v1/"), "https://example.com/v1/chat/completions")
        for u in ("http://example.com", "https://user:secret@example.com", "file:///tmp", "https://example.com/?key=secret"):
            with self.assertRaises(ValueError):
                completion_url(u)

    def test_key_not_returned_and_cleared_on_provider_change(self):
        s = ModelSettings()
        s.update({"api_key": "test-secret-key"})
        self.assertNotIn("test-secret-key", json.dumps(s.public()))
        self.assertTrue(s.public()["has_key"])
        s.update({"base_url": "https://example.com/v1"})
        self.assertFalse(s.public()["has_key"])

    def test_offline_guidance_and_simulation_tool(self):
        with tempfile.TemporaryDirectory() as d:
            c = Controller(Path(d))
            chat = Chat(c, ModelSettings())
            self.assertIn("3.3", chat.reply("接线", "offline")["text"])
            self.assertIn("模拟", chat.reply("运行模拟", "offline")["text"])
            self.assertEqual(c.last["summary"]["source"], "simulated")

    def test_missing_key_no_request(self):
        with tempfile.TemporaryDirectory() as d:
            chat = Chat(Controller(Path(d)), ModelSettings())
            with self.assertRaises(ValueError):
                chat.reply("你好", "api")

    def test_tool_loop_and_raw_data_not_sent(self):
        requests = []
        def transport(url, key, body):
            requests.append(body)
            if len(requests) == 1:
                return {"choices": [{"message": {"role":"assistant", "content":None,
                     "tool_calls":[{"id":"x", "type":"function", "function":{"name":"run_simulation", "arguments":"{}"}}]}}]}
            return {"choices": [{"message": {"role":"assistant", "content":"模拟判读完成"}}]}
        with tempfile.TemporaryDirectory() as d:
            s = ModelSettings(); s.update({"api_key":"test-secret-key"})
            chat = Chat(Controller(Path(d)), s, transport)
            self.assertEqual(chat.reply("运行模拟", "api")["text"], "模拟判读完成")
            tool = json.loads(requests[-1]["messages"][-1]["content"])
            self.assertEqual(tool["summary"]["source"], "simulated")
            self.assertNotIn("preview", tool)
            self.assertNotIn("test-secret-key", json.dumps(requests))

    def test_error_text_never_exposes_secret(self):
        def transport(*args):
            raise RuntimeError("provider echoed test-secret-key")
        with tempfile.TemporaryDirectory() as d:
            s = ModelSettings(); s.update({"api_key":"test-secret-key"})
            chat = Chat(Controller(Path(d)), s, transport)
            with self.assertRaisesRegex(ValueError, "API") as error:
                chat.reply("你好", "api")
            self.assertNotIn("test-secret-key", str(error.exception))

    def test_unknown_tool_denied_and_loop_bounded(self):
        calls = []
        def transport(url, key, body):
            calls.append(1)
            return {"choices":[{"message":{"role":"assistant", "content":None, "tool_calls":[
                {"id":str(len(calls)), "type":"function", "function":{"name":"power_write", "arguments":"{}"}}]}}]}
        with tempfile.TemporaryDirectory() as d:
            s = ModelSettings(); s.update({"api_key":"test-secret-key"})
            result = Chat(Controller(Path(d)), s, transport).reply("执行", "api")
            self.assertLessEqual(len(calls), 4)
            self.assertIn("上限", result["text"])

    def test_stop_cancels_late_model_response(self):
        with tempfile.TemporaryDirectory() as d:
            c = Controller(Path(d)); s = ModelSettings(); s.update({"api_key":"test-secret-key"})
            def transport(*args):
                c.stop()
                return {"choices":[{"message":{"role":"assistant", "content":"late"}}]}
            with self.assertRaises(InterruptedError):
                Chat(c, s, transport).reply("你好", "api")

    def test_malformed_tool_batch_has_no_side_effects(self):
        valid = {"id":"x", "type":"function", "function":{"name":"run_simulation", "arguments":"{}"}}
        invalid = {"type":"function", "function":{"name":"run_simulation", "arguments":"{}"}}
        for calls in ([invalid], [valid,invalid], [valid,valid], [{**valid,"type":"script"}]):
            with self.subTest(calls=calls), tempfile.TemporaryDirectory() as d:
                c=Controller(Path(d)); s=ModelSettings(); s.update({"api_key":"test-secret-key"})
                def transport(*args):
                    return {"choices":[{"message":{"role":"assistant","content":None,"tool_calls":calls}}]}
                with self.assertRaises(ValueError):
                    Chat(c,s,transport).reply("模拟", "api")
                self.assertTrue(c.last is None,"malformed tool calls must not create a capture")

    def test_reset_never_revives_old_request(self):
        with tempfile.TemporaryDirectory() as d:
            c=Controller(Path(d)); s=ModelSettings(); s.update({"api_key":"test-secret-key"})
            entered,release=threading.Event(),threading.Event()
            errors=[]
            def transport(*args):
                entered.set(); release.wait(2)
                return {"choices":[{"message":{"role":"assistant","content":"late-result"}}]}
            chat=Chat(c,s,transport)
            def run():
                try: chat.reply("你好","api")
                except Exception as error: errors.append(error)
            thread=threading.Thread(target=run); thread.start()
            self.assertTrue(entered.wait(2))
            c.stop(); c.reset(); release.set(); thread.join(2)
            self.assertEqual(len(errors),1)
            self.assertIsInstance(errors[0],InterruptedError)
            self.assertEqual(chat.history,[])

    def test_network_total_deadline_releases_chat(self):
        with tempfile.TemporaryDirectory() as d:
            c=Controller(Path(d)); s=ModelSettings(); s.update({"api_key":"test-secret-key"})
            release=threading.Event()
            def transport(*args):
                release.wait(3)
                return {"choices":[{"message":{"content":"late"}}]}
            chat=Chat(c,s,transport,request_timeout=.05)
            start=time.monotonic()
            try:
                with self.assertRaisesRegex(ValueError,"超时"):
                    chat.reply("你好","api")
                self.assertLess(time.monotonic()-start,1)
                self.assertFalse(chat.lock.locked())
            finally: release.set()

    def test_stop_between_response_check_and_final_commit(self):
        with tempfile.TemporaryDirectory() as d:
            c=Controller(Path(d)); s=ModelSettings(); s.update({"api_key":"test-secret-key"})
            class ResetDuringValidation(str):
                def strip(self):
                    c.stop(); c.reset()
                    return super().strip()
            def transport(*args):
                return {"choices":[{"message":{"role":"assistant","content":ResetDuringValidation("late")}}]}
            chat=Chat(c,s,transport)
            with self.assertRaises(InterruptedError):
                chat.reply("你好","api")
            self.assertEqual(chat.history,[])
