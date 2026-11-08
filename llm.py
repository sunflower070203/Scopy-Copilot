"""OpenAI-compatible Chat Completions, with a small locally enforced tool registry."""
import copy
import json
import queue
import threading
import time
import urllib.error
import urllib.parse
import urllib.request

from experiment import GUIDE


def completion_url(base):
    if not isinstance(base, str) or len(base) > 500:
        raise ValueError("API 地址无效")
    base = base.strip().rstrip("/")
    u = urllib.parse.urlsplit(base)
    if u.scheme != "https" or not u.hostname or u.username or u.password or u.query or u.fragment:
        raise ValueError("API 地址必须为 HTTPS，且不含用户名、密钥、查询参数或片段")
    try:
        u.port
    except ValueError:
        raise ValueError("API 端口无效") from None
    return base if u.path.endswith("/chat/completions") else base+"/chat/completions"


class ModelSettings:
    def __init__(self):
        self.lock = threading.RLock()
        self.base_url = "https://api.deepseek.com"
        self.model = "deepseek-flash"
        self._key = ""

    def update(self, values):
        if not isinstance(values, dict) or set(values)-{"base_url","model","api_key","clear_key"}:
            raise ValueError("未知模型设置")
        with self.lock:
            base = values.get("base_url", self.base_url)
            completion_url(base)
            base = base.strip().rstrip("/")
            model = values.get("model", self.model)
            if not isinstance(model, str) or not model.strip() or len(model) > 150 or any(ord(c)<32 for c in model):
                raise ValueError("模型名无效")
            key = values.get("api_key", "")
            if not isinstance(key, str) or len(key)>1000 or any(ord(c)<33 or ord(c)>126 for c in key):
                raise ValueError("API Key 格式无效")
            if base != self.base_url or values.get("clear_key"):
                self._key = ""
            self.base_url, self.model = base, model.strip()
            if key:
                self._key = key
            return self.public()

    def public(self):
        with self.lock:
            return {"base_url": self.base_url, "model": self.model, "has_key": bool(self._key)}

    def snapshot(self):
        with self.lock:
            return self.base_url, self.model, self._key


class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        raise ValueError("API 重定向已拒绝，请设置最终地址")


def http_completion(url, key, body):
    req = urllib.request.Request(url, data=json.dumps(body).encode("utf-8"),
                                 headers={"Content-Type":"application/json", "Authorization":"Bearer "+key})
    with urllib.request.build_opener(NoRedirect()).open(req, timeout=25) as response:
        raw = response.read(2_000_001)
        if len(raw)>2_000_000:
            raise ValueError("API 响应过大")
        return json.loads(raw)


EMPTY = {"type":"object", "properties":{}, "additionalProperties":False}
TOOLS = [{"type":"function", "function":{"name":name, "description":description, "parameters":schema}}
         for name, description, schema in [
             ("get_experiment_guide", "读取 CD4007UBE 与门接线步骤，不能确认电气连通", EMPTY),
             ("get_status", "读取本地任务状态和最近一次真实只读检查；不能启动设备", EMPTY),
             ("check_scopy_readonly", "主动通过官方MCP检查当前已运行Scopy中的M2K真实只读属性；每次重新读取，带检查时间，不启动或连接设备，不改变供电和输出", EMPTY),
             ("get_result", "读取最近一次本地判读摘要；必须保留来源标记", EMPTY),
             ("run_simulation", "仅运行离线模拟并保存模拟证据，不接触硬件", {
                 "type":"object", "properties":{"config":{"type":"object", "properties":{
                     "frequency":{"type":"string", "description":"例如 100 Hz，范围 1–1000 Hz"},
                     "sample_rate":{"type":"string", "description":"例如 100 kS/s"},
                     "samples":{"type":"integer", "minimum":4, "maximum":200000}}, "additionalProperties":False}},
                 "additionalProperties":False})]]

SYSTEM = """你是中文模电实验助手，当前目标为 CD4007UBE 二输入与门。用简短、具体步骤帮助新手。
事实以本地工具返回为准。模拟通过仅代表软件流程，不是硬件验证；缺失覆盖不能说通过。
芯片电源为3.3V，14/2/11为正电源，7/9为地，1/5/13/10为N，4连8；A接3，B接6，Y在12。
所有真实写操作在当前版本禁用。不能运行任意脚本、使能输出、改固件、启动或重启设备。
照片不证明电气连通。指导接线前要求断电，真实启用输出须另行人工核实。
你可以运行明确标记的模拟、读步骤、缓存状态和结果摘要。原始波形由本地程序处理。
用户要求检查真实仪器、当前Scopy连接或电源/端口状态时，调用check_scopy_readonly获取新检查；get_status只有缓存，不能充当实时检查。
检查失败必须明确报告，不凭旧缓存判断设备安全。返回电源值为设定值，不是实测电压。不能编造实时电压或输出已关闭。"""


class Chat:
    def __init__(self, controller, settings, transport=http_completion, request_timeout=25):
        self.controller, self.settings, self.transport = controller, settings, transport
        self.lock = threading.Lock()
        self.pending = None
        self.history = []
        self.request_timeout = request_timeout
        self.network_slots = threading.BoundedSemaphore(2)

    def cancel(self):
        if self.pending:
            self.pending.set()

    def request(self, url, key, body, generation, cancel, turn_deadline):
        if not self.network_slots.acquire(blocking=False):
            raise ValueError("先前远端请求尚未退出，请稍后再试")
        result = queue.Queue(maxsize=1)
        def worker():
            try:
                value = self.transport(url,key,body)
                result.put((True,value))
            except Exception:
                result.put((False,None))
            finally:
                self.network_slots.release()
        # Only this caller may dispatch or update state. A late network worker has
        # no controller reference and can only place a response in its private queue.
        threading.Thread(target=worker,daemon=True).start()
        deadline = min(time.monotonic()+self.request_timeout,turn_deadline)
        while True:
            self.controller.check_turn(generation,cancel)
            remaining = deadline-time.monotonic()
            if remaining <= 0:
                raise TimeoutError("API 请求总超时")
            try:
                ok,value = result.get(timeout=min(.05,remaining))
                if not ok:
                    raise ValueError("API 请求失败")
                return value
            except queue.Empty:
                pass

    def reply(self, text, mode, generation=None, cancelled=None):
        if not isinstance(text, str) or not text.strip() or len(text)>4000:
            raise ValueError("消息应为 1–4000 个字符")
        if mode not in ("offline", "api"):
            raise ValueError("未知对话模式")
        if not self.lock.acquire(blocking=False):
            raise ValueError("正在回复上一条消息")
        cancel = cancelled if cancelled is not None else threading.Event()
        self.pending = cancel
        try:
            with self.controller.lock:
                if generation is None:
                    generation = self.controller.generation
                self.controller.check_turn(generation,cancel)
            if mode == "offline":
                result = self.offline(text, cancel, generation)
                self.controller.check_turn(generation,cancel)
                return result
            base, model, key = self.settings.snapshot()
            if not key:
                raise ValueError("请在本机模型设置中输入 API Key，或先使用离线演示")
            messages = [{"role":"system", "content":SYSTEM}] + copy.deepcopy(self.history[-12:]) + [{"role":"user","content":text}]
            tool_count = 0
            seen_call_ids = set()
            turn_deadline = time.monotonic()+60
            for step in range(4):
                self.controller.check_turn(generation,cancel)
                body = {"model":model, "messages":copy.deepcopy(messages), "tools":TOOLS,
                        "stream":False, "max_tokens":1600}
                if urllib.parse.urlsplit(base).hostname == "api.deepseek.com":
                    body["thinking"] = {"type":"disabled"}
                try:
                    response = self.request(completion_url(base), key, body, generation, cancel, turn_deadline)
                    msg = response["choices"][0]["message"]
                    if not isinstance(msg, dict):
                        raise ValueError()
                except InterruptedError:
                    raise
                except TimeoutError:
                    self.controller.event("api_failed", step=step, retried=False)
                    raise ValueError("API 请求总超时，已释放本地对话；未重试。远端请求可能仍在完成，但其迟到结果不能执行工具。") from None
                except Exception:
                    self.controller.event("api_failed", step=step, retried=False)
                    raise ValueError("API 请求失败或响应无效；请检查地址、模型、密钥及网络。未自动重试，未返回服务商错误正文。") from None
                self.controller.check_turn(generation,cancel)
                calls = msg.get("tool_calls")
                if not calls:
                    answer = msg.get("content")
                    if not isinstance(answer, str) or not answer.strip():
                        raise ValueError("API 未返回有效文字")
                    answer = answer[:24000].replace(key, "[密钥已隐藏]")
                    # Keep only complete user/assistant exchanges, never partial tool histories.
                    with self.controller.lock:
                        self.controller.check_turn(generation,cancel)
                        self.history = (self.history + [{"role":"user","content":text}, {"role":"assistant","content":answer}])[-12:]
                        self.controller.event("api_reply", rounds=step+1)
                        return {"text":answer, "source":"external_llm", "model":model}
                if not isinstance(calls,list) or len(calls)>4:
                    raise ValueError("工具请求数量无效")
                # Validate the whole batch before any local side effect is possible.
                prepared = []
                batch_ids = set()
                for call in calls:
                    if not isinstance(call,dict) or call.get("type") != "function":
                        raise ValueError("API 工具回执格式无效")
                    cid, fn = call.get("id"), call.get("function")
                    if not isinstance(cid,str) or not 1 <= len(cid) <= 200 or cid in seen_call_ids or cid in batch_ids or not isinstance(fn,dict):
                        raise ValueError("API 工具回执标识无效或重复")
                    name, encoded = fn.get("name"), fn.get("arguments")
                    if not isinstance(name,str) or not 1 <= len(name) <= 100 or not isinstance(encoded,str) or len(encoded)>8192:
                        raise ValueError("API 工具参数格式无效")
                    try:
                        args = json.loads(encoded)
                    except ValueError:
                        raise ValueError("API 工具参数不是有效 JSON") from None
                    if not isinstance(args,dict):
                        raise ValueError("API 工具参数必须为对象")
                    batch_ids.add(cid)
                    prepared.append((cid,name,args))
                seen_call_ids.update(batch_ids)
                messages.append({"role":"assistant", "content":msg.get("content"), "tool_calls":calls})
                for cid,name,args in prepared:
                    tool_count += 1
                    if tool_count>8:
                        return {"text":"已达到工具调用上限，请缩小请求范围", "source":"local_guard"}
                    try:
                        result = self.controller.dispatch(name, args, cancel, generation)
                        self.controller.event("model_tool", name=name)
                    except InterruptedError:
                        raise
                    except (KeyError, TypeError, ValueError):
                        result = {"error":"本地控制层已拒绝未知工具、越权操作或无效参数"}
                        self.controller.event("model_tool_denied")
                    messages.append({"role":"tool", "tool_call_id":cid, "content":json.dumps(result,ensure_ascii=False)})
            return {"text":"已达到模型处理轮数上限，请查看本地结果或缩小请求范围", "source":"local_guard"}
        finally:
            self.pending = None
            self.lock.release()

    def offline(self, text, cancelled, generation):
        if any(word in text for word in ("检查真实", "检查Scopy", "检查 Scopy", "读取仪器", "检查仪器")):
            r = self.controller.dispatch("check_scopy_readonly",{},cancelled,generation)
            answer = ("真实只读检查完成。" if r.get("connected") else "真实只读检查未完成。") + r.get("message","")
            if r.get("snapshot"):
                answer += "\n"+json.dumps(r["snapshot"],ensure_ascii=False,indent=2)
            answer += "\n未写入参数、供电或输出；检查时间："+r["time"]
        elif any(word in text for word in ("运行模拟", "开始模拟", "跑通", "演示一遍")):
            r = self.controller.dispatch("run_simulation", {}, cancelled,generation)
            s = r["summary"]
            answer = f"已完成离线模拟：{s['samples']} 点，输入覆盖 {s['coverage']}/4，稳态错误 {s['errors']} 点。数据和判读已保存。这是模拟证据，未验证实际电路。"
        elif any(word in text for word in ("上电","打开电源","开启输出","运行脚本")):
            answer = "当前原型只开放模拟和真实只读检查，不能启用实际电源或输出。接线完成后需人工核对供电 3.3 V、共地及 DIO2 仅输入。"
        elif any(word in text for word in ("结果","判读")):
            s = self.controller.dispatch("get_result", {}, cancelled,generation)["summary"]
            answer = (f"最近记录来源为 {s['source']}，判读 {s['verdict']}，覆盖 {s['coverage']}/4，错误 {s['errors']} 点。" if s else "还没有记录。可点击「运行模拟并判读」。")
        else:
            answer = "离线助手提供固定教程与本地模拟；自由问答需要在本机设置 API。\n\n" + "\n\n".join(f"{i+1}. {x['title']}：{x['text']}" for i,x in enumerate(GUIDE))
        self.controller.event("offline_reply")
        return {"text":answer, "source":"offline_rules", "model":None}
