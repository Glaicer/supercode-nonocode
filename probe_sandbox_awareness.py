import base64
import http.server
import json
import os
import socket
import subprocess
import tempfile
import threading
import time
import urllib.parse
import urllib.request
from pathlib import Path

from launcher import opencode_bin

HERE = Path(__file__).resolve().parent
OPENCODE = opencode_bin()
PLUGIN_PATH = str(HERE / "sandbox-awareness")
TEMPORARY_ROOT = Path(tempfile.gettempdir()) / "opencode"
TEMPORARY_ROOT.mkdir(parents=True, exist_ok=True)

captured = []


class Provider(http.server.BaseHTTPRequestHandler):
    def log_message(self, *_args):
        pass

    def do_POST(self):
        body = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
        captured.append(body)
        self.send_response(200)
        self.send_header("Content-Type", "text/event-stream")
        self.end_headers()
        for delta in [{"role": "assistant", "content": "OK"}, {}]:
            chunk = {
                "id": "probe",
                "object": "chat.completion.chunk",
                "created": 0,
                "model": "probe",
                "choices": [
                    {
                        "index": 0,
                        "delta": delta,
                        "finish_reason": None if delta else "stop",
                    }
                ],
            }
            self.wfile.write(("data: " + json.dumps(chunk) + "\n\n").encode())
        self.wfile.write(b"data: [DONE]\n\n")


provider = http.server.ThreadingHTTPServer(("127.0.0.1", 0), Provider)
threading.Thread(target=provider.serve_forever, daemon=True).start()
try:
    for mode in ["sandboxed", "unsandboxed"]:
        captured.clear()
        with tempfile.TemporaryDirectory(
            prefix="sandbox-awareness-check-", dir=TEMPORARY_ROOT
        ) as directory:
            root = Path(directory)
            for path in [
                "home",
                "config/opencode",
                "data",
                "cache",
                "state",
                "project",
            ]:
                (root / path).mkdir(parents=True, exist_ok=True)
            config = {
                "plugins": [PLUGIN_PATH],
                "model": "proof-local/probe",
                "providers": {
                    "proof-local": {
                        "name": "Loopback",
                        "env": ["PROOF_KEY"],
                        "package": "@opencode/ai/providers/openai-compatible",
                        "settings": {
                            "baseURL": f"http://127.0.0.1:{provider.server_port}/v1"
                        },
                        "models": {
                            "probe": {
                                "name": "Probe",
                                "limit": {"context": 128000, "output": 4096},
                            }
                        },
                    }
                },
            }
            with socket.socket() as sock:
                sock.bind(("127.0.0.1", 0))
                port = sock.getsockname()[1]
            env = dict(os.environ)
            for key in [
                "OPENCODE_CONFIG",
                "OPENCODE_CONFIG_CONTENT",
                "OPENCODE_CLI_CONFIG_CONTENT",
            ]:
                env.pop(key, None)
            env.update(
                HOME=str(root / "home"),
                XDG_CONFIG_HOME=str(root / "config"),
                XDG_DATA_HOME=str(root / "data"),
                XDG_CACHE_HOME=str(root / "cache"),
                XDG_STATE_HOME=str(root / "state"),
                OPENCODE_CONFIG_DIR=str(root / "config/opencode"),
                OPENCODE_CONFIG_CONTENT=json.dumps(config),
                OPENCODE_DB=str(root / "check.db"),
                OPENCODE_SERVER_PASSWORD="probe-only",
                OPENCODE_SANDBOX_MODE=mode,
                PROOF_KEY="dummy-loopback",
            )
            with (root / "server.log").open("w") as log:
                child = subprocess.Popen(
                    [
                        OPENCODE,
                        "serve",
                        "--hostname",
                        "127.0.0.1",
                        "--port",
                        str(port),
                    ],
                    cwd=root / "project",
                    env=env,
                    stdout=log,
                    stderr=log,
                )
                try:

                    def api(method, route, body=None, port=port):
                        headers = {
                            "Authorization": "Basic "
                            + base64.b64encode(b"opencode:probe-only").decode(),
                            "Content-Type": "application/json",
                        }
                        data = None if body is None else json.dumps(body).encode()
                        req = urllib.request.Request(
                            f"http://127.0.0.1:{port}" + route,
                            data=data,
                            headers=headers,
                            method=method,
                        )
                        with urllib.request.urlopen(req, timeout=10) as response:
                            return json.load(response)

                    for _ in range(150):
                        if child.poll() is not None:
                            raise RuntimeError("probe server exited")
                        try:
                            api("GET", "/api/info")
                            break
                        except OSError:
                            time.sleep(0.1)
                    else:
                        raise TimeoutError("server startup")
                    session = api(
                        "POST",
                        "/api/session",
                        {
                            "location": {"directory": str(root / "project")},
                            "model": {"providerID": "proof-local", "id": "probe"},
                            "title": "Sandbox awareness check",
                        },
                    )["data"]["id"]
                    api("POST", f"/api/session/{session}/prompt", {"text": "Reply OK"})
                    for _ in range(150):
                        calls = [
                            body
                            for body in captured
                            if any(
                                message.get("role") == "user"
                                and "Reply OK" in json.dumps(message.get("content"))
                                for message in body.get("messages", [])
                            )
                        ]
                        if calls:
                            break
                        time.sleep(0.1)
                    assert calls, "no primary model request captured"
                    inventory = api(
                        "GET",
                        "/api/plugin?location[directory]="
                        + urllib.parse.quote(str(root / "project")),
                    )["data"]
                    plugin = next(
                        item
                        for item in inventory
                        if item.get("id") == "sandbox-awareness"
                    )
                    assert plugin["state"]["status"] == "active", plugin["state"]
                    assert PLUGIN_PATH in json.dumps(
                        plugin["source"], ensure_ascii=False
                    ), plugin["source"]
                    system = json.dumps(
                        [
                            message
                            for message in calls[0]["messages"]
                            if message["role"] == "system"
                        ]
                    )
                    assert ("OPENCODE_SANDBOX_MODE=sandboxed" in system) == (
                        mode == "sandboxed"
                    )
                    if mode == "sandboxed":
                        assert "question tool" in system
                    print(
                        "PASS: checkout plugin loaded via config registration; model system prompt correct for",
                        mode,
                    )
                finally:
                    child.terminate()
                    try:
                        child.wait(timeout=5)
                    except subprocess.TimeoutExpired:
                        child.kill()
                        child.wait()
finally:
    provider.shutdown()
    provider.server_close()
