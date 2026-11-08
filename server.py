"""Loopback-only local web application. Run with Python 3.10+."""
import argparse
from datetime import datetime, timezone
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
from pathlib import Path
import re
import secrets
import threading
import urllib.parse
import webbrowser

from controller import Controller, VERSION
from experiment import GUIDE
from llm import Chat, ModelSettings
from scopy import ScopyClient, summarize_metadata
from runtime_paths import default_data_dir

ROOT = Path(__file__).resolve().parent


class Handler(BaseHTTPRequestHandler):
    server_version = "LabCopilot/0.2"

    def log_message(self, *args):
        pass  # Never log URLs, request bodies, credentials or external error text.

    def respond(self, code, data, content_type="application/json; charset=utf-8", filename=None):
        if not isinstance(data, bytes):
            data = json.dumps(data, ensure_ascii=False).encode("utf-8")
        self.send_response(code)
        self.send_header("Content-Type",content_type)
        self.send_header("Content-Length",str(len(data)))
        self.send_header("Cache-Control","no-store")
        self.send_header("X-Content-Type-Options","nosniff")
        self.send_header("Referrer-Policy","no-referrer")
        self.send_header("Content-Security-Policy", "default-src 'self'; script-src 'self'; style-src 'self'; connect-src 'self'; img-src 'self' data:; frame-ancestors 'none'; form-action 'self'; base-uri 'none'")
        if filename:
            self.send_header("Content-Disposition",f'attachment; filename="{filename}"')
        self.end_headers()
        try:
            self.wfile.write(data)
        except (BrokenPipeError,ConnectionResetError):
            pass

    def check(self, token=False):
        port = self.server.server_address[1]
        host = self.headers.get("Host", "")
        if host not in (f"127.0.0.1:{port}", f"localhost:{port}"):
            return False
        origin = self.headers.get("Origin")
        if origin and origin != f"http://{host}":
            return False
        if self.headers.get("Sec-Fetch-Site") == "cross-site":
            return False
        return not token or secrets.compare_digest(self.headers.get("X-Copilot-Token", ""), self.server.token)

    def do_GET(self):
        if not self.check():
            return self.respond(403,{"error":"拒绝非本机同源请求"})
        path = urllib.parse.urlsplit(self.path).path
        if path == "/api/bootstrap":
            metadata = ROOT/"vendor/scopy-mcp-server/scopy_mcp_server/scopy_api.json"
            capabilities = summarize_metadata(json.loads(metadata.read_text(encoding="utf-8"))) if metadata.exists() else summarize_metadata({})
            return self.respond(200,{"token":self.server.token, "guide":GUIDE, "settings":self.server.settings.public(),
                                     "state":self.server.controller.status(), "capabilities":capabilities})
        if path.startswith("/api/") and not self.check(token=True):
            return self.respond(403,{"error":"会话令牌无效，请刷新本地页面"})
        if path == "/api/state":
            return self.respond(200,self.server.controller.status())
        match = re.fullmatch(r"/api/files/([a-f0-9]{32})/(raw\.csv|result\.json|manifest\.json)",path)
        if match:
            file = self.server.controller.data_dir/"runs"/match[1]/match[2]
            if file.is_file():
                kind = "text/csv; charset=utf-8" if file.suffix==".csv" else "application/json; charset=utf-8"
                return self.respond(200,file.read_bytes(),kind,match[2])
        static = {"/":"index.html", "/index.html":"index.html", "/style.css":"style.css", "/app.js":"app.js"}
        if path in static:
            file = ROOT/"web"/static[path]
            if file.is_file():
                kind = {".html":"text/html; charset=utf-8", ".css":"text/css; charset=utf-8", ".js":"text/javascript; charset=utf-8"}[file.suffix]
                return self.respond(200,file.read_bytes(),kind)
        self.respond(404,{"error":"未找到页面或证据文件"})

    def do_POST(self):
        if not self.check(token=True):
            return self.reject_post(403,"拒绝非本机同源请求或无效令牌")
        if self.headers.get("Content-Type", "").split(";")[0] != "application/json":
            return self.reject_post(415,"请求需要 JSON 格式")
        try:
            size = int(self.headers.get("Content-Length",0))
            if not 0 < size <= 32768:
                return self.reject_post(413,"请求大小应为 1–32768 字节")
            self.connection.settimeout(5)
            body = json.loads(self.rfile.read(size))
            if not isinstance(body,dict):
                raise ValueError("参数必须为对象")
            c = self.server.controller
            path = urllib.parse.urlsplit(self.path).path
            if path == "/api/simulate":
                if set(body)-{"config","fault"}:
                    raise ValueError("未知模拟参数")
                result = c.run_simulation(body.get("config",{}), body.get("fault","none"))
            elif path == "/api/chat":
                if set(body)-{"text","mode"}:
                    raise ValueError("未知对话参数")
                result = self.server.chat.reply(body.get("text"),body.get("mode","offline"))
            elif path == "/api/settings":
                result = self.server.settings.update(body)
                c.event("settings_updated", key_configured=result["has_key"])
            elif path == "/api/stop":
                result = c.stop()
                self.server.chat.cancel()
            elif path == "/api/reset":
                result = c.reset()
            elif path == "/api/probe":
                if body:
                    raise ValueError("只读检查不接受自定义MCP参数")
                result = c.check_hardware()
            else:
                return self.respond(404,{"error":"未知接口"})
            self.respond(200,result)
        except InterruptedError as error:
            self.respond(409,{"error":str(error)})
        except (ValueError, TypeError, KeyError) as error:
            # Local validation messages contain no API key. JSON parse errors can quote
            # input, so use a fixed message for decoder failures.
            message = "JSON 参数无效" if isinstance(error,json.JSONDecodeError) else str(error)
            key = self.server.settings.snapshot()[2]
            self.respond(400,{"error":message.replace(key,"[已隐藏]") if key else message})
        except Exception:
            self.respond(500,{"error":"本地操作失败。未自动重试或恢复输出，请查看本地文件写入权限和连接状态。"})

    def reject_post(self, code, message):
        # Drain every bounded rejected body, including 403/415. Otherwise Windows
        # can reset a connection before the browser receives the rejection response.
        self.connection.settimeout(1)
        try:
            size = int(self.headers.get("Content-Length",0))
            if size > 0:
                self.rfile.read(min(size,65536))
        except (OSError, ValueError):
            pass
        return self.respond(code,{"error":message})


def make_server(port=8765, data_dir=None):
    server = ThreadingHTTPServer(("127.0.0.1",port),Handler)
    server.daemon_threads = True
    server.token = secrets.token_urlsafe(32)
    server.controller = Controller(data_dir or default_data_dir())
    server.settings = ModelSettings()
    server.chat = Chat(server.controller,server.settings)
    server.probe_lock = threading.Lock()
    return server


def main():
    parser = argparse.ArgumentParser(description="模电实验 Copilot 本地原型")
    parser.add_argument("--port",type=int,default=8765)
    parser.add_argument("--open",action="store_true")
    args = parser.parse_args()
    try:
        server = make_server(args.port)
    except OSError:
        raise SystemExit("本地端口不可用，请使用 --port 8766 选择其他端口") from None
    url = f"http://127.0.0.1:{server.server_address[1]}"
    print(f"Analog Lab Copilot v{VERSION} | {url} | simulated / hardware read-only",flush=True)
    if args.open:
        webbrowser.open(url)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        server.chat.cancel()
        server.controller.stop()
    finally:
        server.server_close()


if __name__ == "__main__":
    main()
