"""All state changes and tool execution are owned by this local controller."""
import csv
from datetime import datetime, timezone
import hashlib
import io
import json
from pathlib import Path
import threading
import uuid

from experiment import Config, GUIDE, analyze, simulate
from scopy import ScopyClient
from runtime_paths import APP_VERSION

VERSION = APP_VERSION


def stamp():
    return datetime.now(timezone.utc).isoformat()


class Controller:
    def __init__(self, data_dir, hardware_client=None):
        self.data_dir = Path(data_dir)
        self.lock = threading.RLock()
        self.operation_lock = threading.Lock()
        self.stopped = threading.Event()
        self.generation = 0
        self.last = None
        self.phase = "ready"
        self.active = None
        self.events = []
        self.hardware_client = hardware_client or ScopyClient()
        self.probe_lock = threading.Lock()
        self.hardware = {"connected": False, "message": "尚未执行只读检查", "source": "hardware_probe"}

    def event(self, kind, **fields):
        # Callers pass only bounded control metadata, never chat text, API bodies or credentials.
        with self.lock:
            item = {"time": stamp(), "event": kind, **fields}
            self.events.append(item)
            self.events = self.events[-100:]
            self.data_dir.mkdir(parents=True, exist_ok=True)
            with (self.data_dir/"events.jsonl").open("a", encoding="utf-8") as f:
                f.write(json.dumps(item, ensure_ascii=False)+"\n")

    def status(self):
        with self.lock:
            return {"version": VERSION, "phase": self.phase, "stopped": self.stopped.is_set(),
                    "mode": "simulation", "simulation_outputs_enabled": self.phase == "sampling",
                    "hardware_outputs": "unknown", "hardware_writes_enabled": False,
                    "hardware": self.hardware, "last": self.last, "events": list(self.events)}

    def stop(self):
        with self.lock:
            self.stopped.set()
            self.generation += 1
            if self.hardware.get("pending"):
                self.hardware = {"source":"hardware_probe","connected":False,"outputs":"unknown",
                                 "pending":False,"read_only":True,"message":"检查已取消，未更新真实状态"}
            if self.active:
                self.active.set()
            self.phase = "stopped"
            self.event("stop", hardware_stop_sent=False)
        return {"message": "已停止本地任务。未向设备发送停机指令；实际输出状态未知，请在 Scopy 关闭输出。"}

    def reset(self):
        with self.lock:
            if self.active is not None:
                raise ValueError("任务仍在取消中，请稍后再恢复")
            self.stopped.clear()
            self.phase = "ready"
            self.event("user_reset")
        return {"message": "本地演示已恢复，未恢复任何实际输出"}

    def check_turn(self, generation, cancelled):
        with self.lock:
            if cancelled.is_set() or self.stopped.is_set() or generation != self.generation:
                raise InterruptedError("本地任务已停止；旧任务不能通过恢复演示重新生效")

    def check_hardware(self, cancelled=None, generation=None):
        cancel = cancelled if cancelled is not None else threading.Event()
        with self.lock:
            if generation is None:
                generation = self.generation
            self.check_turn(generation,cancel)
        if not self.probe_lock.acquire(blocking=False):
            raise ValueError("真实只读检查正在进行，请稍后再试")
        try:
            with self.lock:
                self.check_turn(generation,cancel)
                self.hardware = {"source":"hardware_probe","connected":False,"outputs":"unknown",
                                 "pending":True,"read_only":True,"message":"正在执行新的真实只读检查"}
                self.event("hardware_probe_started")
            def is_cancelled():
                return cancel.is_set() or self.stopped.is_set() or generation != self.generation
            try:
                result = self.hardware_client.probe(cancelled=is_cancelled)
                if not isinstance(result,dict) or type(result.get("connected")) is not bool:
                    raise ValueError("invalid probe response")
            except InterruptedError:
                raise
            except Exception:
                result = {"connected":False,"error_code":"probe_failed","message":"真实只读检查失败；旧状态已失效，未重试或更改输出。"}
            with self.lock:
                self.check_turn(generation,cancel)
                result = {**result,"time":stamp(),"source":"hardware_probe","read_only":True,
                          "cached":False,"pending":False,"write_enabled":False,"outputs":"unknown"}
                self.hardware = result
                self.event("hardware_probe",connected=bool(result.get("connected")),source="hardware_probe")
                return result
        except InterruptedError:
            with self.lock:
                if generation == self.generation:
                    self.hardware = {"source":"hardware_probe","connected":False,"outputs":"unknown",
                                     "pending":False,"read_only":True,"message":"检查已取消，未更新真实状态"}
            raise
        finally:
            self.probe_lock.release()

    def run_simulation(self, values, fault="none", cancelled=None, generation=None):
        config = Config.parse(values)
        if not self.operation_lock.acquire(blocking=False):
            raise ValueError("已有模拟任务正在执行")
        cancel = cancelled if cancelled is not None else threading.Event()
        try:
            with self.lock:
                if generation is None:
                    generation = self.generation
                self.check_turn(generation,cancel)
                if self.stopped.is_set() or cancel.is_set():
                    raise InterruptedError("本地任务已停止，请手动恢复")
                self.active = cancel
                self.phase = "configured"
                # Simulator readback is deliberately separate from any physical-device claim.
                readback = Config.parse(config.json()).json()
                if readback != config.json():
                    raise ValueError("模拟配置回读不一致，拒绝输出")
                self.event("simulation_configured", config=config.json(), readback=readback)
                self.phase = "sampling"
            data = simulate(config, fault=fault, cancelled=lambda: cancel.is_set() or self.stopped.is_set() or generation != self.generation)
            summary = analyze(data)
            run_id = uuid.uuid4().hex
            result = {"id": run_id, "time": stamp(), "version": VERSION, "source": "simulated",
                      "config": config.json(), "readback": readback, "fault": fault, "seed": 17,
                      "summary": summary, "evidence_notice": "模拟数据，仅用于验证软件流程；未验证实际电路"}
            text = io.StringIO(newline="")
            writer = csv.writer(text)
            writer.writerow(["time_s", "A_DIO0", "B_DIO1", "Y_DIO2", "source"])
            writer.writerows((f"{i/config.sample_rate:.9f}", a, b, y, "simulated") for i, (a,b,y) in enumerate(zip(data.a,data.b,data.y)))
            payloads = {"raw.csv": text.getvalue().encode("utf-8"),
                        "result.json": json.dumps(result, ensure_ascii=False, indent=2).encode("utf-8")}
            with self.lock:
                self.check_turn(generation,cancel)
                if cancel.is_set() or self.stopped.is_set():
                    raise InterruptedError("任务已取消，结果未提交")
                folder = self.data_dir/"runs"/run_id
                folder.mkdir(parents=True)
                for name, payload in payloads.items():
                    (folder/name).write_bytes(payload)
                manifest = {"id": run_id, "source": "simulated", "time": result["time"],
                            "sha256": {name: hashlib.sha256(v).hexdigest() for name,v in payloads.items()}}
                (folder/"manifest.json").write_text(json.dumps(manifest, indent=2), encoding="utf-8")
                # Show the first 50 ms at native resolution, no decimation hiding transitions.
                m = min(config.samples, int(config.sample_rate*.05), 10000)
                result["preview"] = {"a": data.a[:m], "b": data.b[:m], "y": data.y[:m],
                                     "sample_rate": config.sample_rate, "points": m}
                self.last = result
                self.phase = "complete"
                self.event("simulation_saved", id=run_id, verdict=summary["verdict"], source="simulated")
            return result
        except InterruptedError:
            with self.lock:
                if generation == self.generation:
                    self.phase = "stopped" if self.stopped.is_set() else "ready"
            raise
        except Exception:
            with self.lock:
                if generation == self.generation and not self.stopped.is_set():
                    self.phase = "error"
            raise
        finally:
            with self.lock:
                self.active = None
            self.operation_lock.release()

    def dispatch(self, name, arguments, cancelled, generation=None):
        if not isinstance(arguments, dict):
            raise ValueError("工具参数必须为对象")
        if cancelled.is_set() or self.stopped.is_set():
            raise InterruptedError("本地任务已停止")
        if generation is not None:
            self.check_turn(generation,cancelled)
        if name == "run_simulation":
            if set(arguments) - {"config"}:
                raise ValueError("未知工具参数")
            result = self.run_simulation(arguments.get("config", {}), cancelled=cancelled, generation=generation)
            return {k:v for k,v in result.items() if k != "preview"}
        if arguments:
            raise ValueError("此工具不接受参数")
        if name == "check_scopy_readonly":
            return self.check_hardware(cancelled,generation)
        if name == "get_experiment_guide":
            return {"steps": GUIDE, "voltage": "3.3 V", "physical_writes": "disabled"}
        if name == "get_status":
            s = self.status()
            result = {k:s[k] for k in ("phase","stopped","hardware_outputs","hardware_writes_enabled")}
            result["hardware"] = {**s["hardware"],"cached":True}
            return result
        if name == "get_result":
            with self.lock:
                return {"summary": self.last["summary"] if self.last else None}
        raise ValueError("工具不在允许列表中；真实输出和任意脚本均不可执行")
