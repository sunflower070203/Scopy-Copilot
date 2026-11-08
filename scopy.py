"""A minimal stdio MCP client for the unmodified official Scopy bridge.

No generic call endpoint exists. Only literal read-only operations below can cross
this boundary, even if an LLM guesses a real upstream write tool name.
"""
import json
import os
from pathlib import Path
import queue
import subprocess
import threading
import time
from runtime_paths import APP_VERSION,bundle_root,bundled_bridge_path,is_frozen

ROOT = bundle_root()
READS = {
    "power_read": {"dac1_enabled", "dac1_value", "dac2_enabled"},
    "dio_read": {"dir", "gpi", "running"},
    "logic_read": {"sampleRate", "bufferSize"},
}
LISTS = {"scopy_list", "power_list", "dio_list", "logic_list", "pattern_list"}


def validate_read(name, args):
    if not isinstance(args, dict):
        raise ValueError("MCP 参数无效")
    if name in LISTS and not args:
        return
    if name == "scopy_call" and args in ({"method":"getDevicesName"}, {"method":"getTools"}):
        return
    if name not in READS or args.get("property") not in READS[name]:
        raise ValueError("真实设备只允许固定只读接口")
    allowed = {"property"}
    if name == "dio_read" and args["property"] in ("dir", "gpi"):
        allowed.add("channel")
        if type(args.get("channel")) is not int or not 0 <= args["channel"] <= 2:
            raise ValueError("只读取 DIO0–2")
    if set(args) - allowed or "property" not in args:
        raise ValueError("未知或不适用的 MCP 参数")


def summarize_metadata(metadata):
    objs = metadata.get("objects", {})
    return {"version":"Scopy v2.2.1", "m2k_objects": sorted(k for k in objs if k in ("power","dio","pattern","logic","osc")),
            "pattern_properties": [p["name"] for p in objs.get("pattern",{}).get("properties",[])],
            "logic_properties": [p["name"] for p in objs.get("logic",{}).get("properties",[])],
            "random_frequency_control":False, "raw_logic_export":False,
            "limitation":"正式版元数据未提供 Random 频率配置和原始逻辑波形导出；MVP 不实现实际采样闭环"}


class StdioSession:
    def __init__(self, python, timeout=12, cancelled=lambda:False, packaged=False):
        self.python, self.timeout = python, timeout
        self.proc = None
        self.messages = queue.Queue(maxsize=128)
        self.serial = 0
        self.deadline = time.monotonic()+35
        self.cancelled = cancelled
        self.packaged = packaged

    def command(self):
        if self.packaged:return [self.python]
        return [self.python,"-u","-c","from scopy_mcp_server.server import main; main()"]

    def __enter__(self):
        env = {k:v for k,v in os.environ.items() if "KEY" not in k.upper() and "TOKEN" not in k.upper() and "SECRET" not in k.upper()}
        if self.packaged:
            env.pop("PYTHONPATH",None)
            env["PYINSTALLER_RESET_ENVIRONMENT"]="1"
        else:
            env["PYTHONPATH"] = str(ROOT/"vendor"/"scopy-mcp-server")
        env["PYTHONIOENCODING"] = "utf-8"
        self.proc = subprocess.Popen(self.command(),
                                     stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL,
                                     env=env, cwd=ROOT, creationflags=getattr(subprocess,"CREATE_NO_WINDOW",0))
        threading.Thread(target=self._reader, daemon=True).start()
        try:
            self.rpc("initialize", {"protocolVersion":"2024-11-05", "capabilities":{},
                                    "clientInfo":{"name":"analog-lab-copilot-readonly","version":APP_VERSION}})
            self.send({"jsonrpc":"2.0", "method":"notifications/initialized"})
            return self
        except Exception:
            self.close()
            raise

    def _reader(self):
        try:
            while True:
                line = self.proc.stdout.readline(2_000_001)
                if not line:
                    break
                if len(line)>2_000_000:
                    break
                self.messages.put(json.loads(line), timeout=1)
        except (ValueError, OSError, queue.Full):
            pass
        finally:
            try:
                self.messages.put_nowait(None)
            except queue.Full:
                pass

    def send(self, message):
        self.proc.stdin.write((json.dumps(message)+"\n").encode("utf-8"))
        self.proc.stdin.flush()

    def rpc(self, method, params):
        if self.cancelled():
            raise InterruptedError("只读检查已取消")
        self.serial += 1
        request_id = self.serial
        self.send({"jsonrpc":"2.0", "id":request_id, "method":method, "params":params})
        deadline = min(time.monotonic()+self.timeout, self.deadline)
        while time.monotonic()<deadline:
            if self.cancelled():
                raise InterruptedError("只读检查已取消")
            try:
                message = self.messages.get(timeout=max(.001,min(.1,deadline-time.monotonic())))
            except queue.Empty:
                continue
            if message is None:
                raise ConnectionError("MCP 已断开")
            if message.get("id") == request_id:
                if "error" in message:
                    raise ConnectionError("MCP 返回错误")
                return message["result"]
        raise TimeoutError("MCP 超时")

    def read(self, name, arguments):
        validate_read(name, arguments)
        r = self.rpc("tools/call", {"name":name, "arguments":arguments})
        if r.get("isError"):
            raise ConnectionError("Scopy 只读调用失败")
        value = "\n".join(x.get("text","") for x in r.get("content",[]) if x.get("type")=="text")
        if not value or value.startswith(("No running", "Cannot connect", "Scopy error:", "Scopy did not", "Unknown ")) or value in ("undefined", "null"):
            raise ConnectionError("Scopy 不可用或未提供所需属性")
        return value[:2000]

    def close(self):
        if self.proc:
            self.proc.terminate()
            try:
                self.proc.wait(timeout=3)
            except subprocess.TimeoutExpired:
                self.proc.kill()
                self.proc.wait(timeout=3)
            self.proc.stdin.close()
            self.proc.stdout.close()
            self.proc = None

    def __exit__(self, *exc):
        self.close()


class ScopyClient:
    def __init__(self, bridge_python=None):
        self.packaged = bridge_python is None and is_frozen()
        self.python = str(bridge_python or (bundled_bridge_path() if self.packaged else ROOT/".venv-scopy"/("Scripts/python.exe" if os.name=="nt" else "bin/python")))

    def inventory(self):
        with StdioSession(self.python,packaged=self.packaged) as session:
            tools = session.rpc("tools/list", {})["tools"]
            names = [t["name"] for t in tools]
            return {"tool_count":len(names), "m2k_tools":[n for n in names if n.startswith(("dio_","logic_","pattern_","power_"))]}

    def probe(self, cancelled=lambda:False):
        base = {"source":"hardware_probe", "connected":False, "outputs":"unknown", "write_enabled":False}
        if not Path(self.python).is_file():
            return {**base,"error_code":"bridge_missing", "message":"官方桥接尚未安装；离线演示可继续。见 README 的可选只读接入步骤。"}
        try:
            with StdioSession(self.python,cancelled=cancelled,packaged=self.packaged) as session:
                names = {t["name"] for t in session.rpc("tools/list", {})["tools"]}
                required = {"scopy_call", "power_read", "dio_read", "logic_read"}
                if not required <= names:
                    raise ConnectionError("缺少只读接口")
                devices = session.read("scopy_call", {"method":"getDevicesName"})
                if devices.strip() in ("[]", ""):
                    raise ConnectionError("没有已添加设备")
                snapshot = {}
                for name, args, label in (
                    ("power_read", {"property":"dac1_enabled"}, "vplus_enabled"),
                    ("power_read", {"property":"dac1_value"}, "vplus_setting"),
                    ("power_read", {"property":"dac2_enabled"}, "vminus_enabled"),
                    ("dio_read", {"property":"running"}, "dio_running"),
                    ("dio_read", {"property":"dir","channel":2}, "dio2_direction"),
                    ("dio_read", {"property":"gpi","channel":2}, "dio2_input"),
                    ("logic_read", {"property":"sampleRate"}, "logic_sample_rate"),
                    ("logic_read", {"property":"bufferSize"}, "logic_buffer_size")):
                    snapshot[label] = session.read(name,args)
                if snapshot["vplus_enabled"] not in ("true","false"):
                    raise ConnectionError("无法确认 M2K 实例")
                return {**base, "connected":True, "devices":devices, "snapshot":snapshot,
                        "message":"已读取 Scopy 的 M2K 属性；未采样，未写参数，未确认接线。电源值为设定值，不是实测电压。"}
        except InterruptedError:
            raise
        except TimeoutError:
            return {**base,"error_code":"timeout", "message":"官方MCP只读检查超时，未重试或更改输出；旧状态已失效。"}
        except Exception:
            return {**base,"error_code":"unavailable", "message":"只读连接未建立或已断开。请确认Scopy的MCP开关已启用、设备已连接；本程序未启动设备或恢复输出。"}
