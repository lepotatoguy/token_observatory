"""Exercise the real CLI and WSGI server against isolated synthetic records."""
import json
import os
from pathlib import Path
import re
import socket
import subprocess
import sys
import time
import urllib.error
import urllib.request

from backend import launcher
from backend.models.snapshot import UsageSnapshot


ROOT = Path(__file__).resolve().parents[2]
LOCAL = urllib.request.build_opener(urllib.request.ProxyHandler({}))


def free_ports():
    with socket.socket() as one, socket.socket() as two:
        one.bind(("127.0.0.1", 0))
        two.bind(("127.0.0.1", 0))
        return one.getsockname()[1], two.getsockname()[1]


def test_real_servers_keep_usage_and_stop_by_port(tmp_path):
    ports = free_ports()
    codex, claude = tmp_path / "codex", tmp_path / "claude"
    (codex / "sessions").mkdir(parents=True)
    logs = claude / "projects/synthetic"
    logs.mkdir(parents=True)
    (logs / "session.jsonl").write_text(json.dumps({"type": "assistant", "timestamp": "2026-11-03T12:00:00Z",
        "sessionId": "synthetic", "message": {"id": "synthetic-response", "model": "test-model",
        "usage": {"input_tokens": 10, "output_tokens": 5}}}) + "\n")
    (tmp_path / "providers.json").write_text(json.dumps({"setup_done": True, "enabled": {
        provider: False for provider in ["claude", "codex", "minimax", "ollama", "lmstudio", "llamacpp"]}}))
    env = dict(os.environ, HOME=str(tmp_path), XDG_DATA_HOME=str(tmp_path / "data"),
               MINIMAX_DATA_DIR=str(tmp_path / "minimax"), MAVIS_DATA_DIR=str(tmp_path / "minimax"),
               TOKEN_OBSERVATORY_LIVE_CHECKS="0", TOKEN_OBSERVATORY_UPDATE_CHECKS="0",
               TOKEN_OBSERVATORY_PRICE_UPDATES="0", TOKEN_OBSERVATORY_DATA_DIR=str(tmp_path / "history"))
    base_command = [sys.executable, str(ROOT / "launcher.py")]
    common = ["--data-dir", str(tmp_path / "history"), "--codex-home", str(codex), "--claude-home", str(claude)]
    processes = []
    try:
        for port in ports:
            process = subprocess.Popen(base_command + ["--serve", "--port", str(port)] + common,
                                       env=env, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            processes.append(process)
            deadline = time.monotonic() + launcher.STARTUP_SECONDS
            while True:
                try:
                    with LOCAL.open(f"http://127.0.0.1:{port}/api/health", timeout=1) as response:
                        assert json.load(response) == {"app": "token-observatory", "version": 2}
                        assert response.headers["Cache-Control"] == "no-store"
                    break
                except OSError:
                    assert process.poll() is None, (tmp_path / "service.log").read_text()
                    assert time.monotonic() < deadline, (tmp_path / "service.log").read_text()
                    time.sleep(0.05)
                    time.sleep(.05)
        for port in ports:
            url = f"http://127.0.0.1:{port}"
            with LOCAL.open(url + "/api/usage", timeout=3) as response:
                raw = json.load(response)
            snapshot = UsageSnapshot.model_validate(raw)
            assert snapshot.providers.enabled == []
            assert len(snapshot.sessions) == 1
            assert snapshot.sessions[0].totals.total == 15
            with LOCAL.open(url + "/", timeout=3) as response:
                html = response.read().decode()
            script = re.search(r'<script[^>]+src="([^"]+)"', html)
            assert script, "Production index must load its compiled application"
            with LOCAL.open(url + script.group(1), timeout=3) as response:
                assert response.status == 200
        first = subprocess.run(base_command + ["--stop", "--port", str(ports[0])] + common,
                               env=env, capture_output=True, text=True, timeout=10)
        assert first.returncode == 0, first.stderr
        processes[0].wait(timeout=10)
        with LOCAL.open(f"http://127.0.0.1:{ports[1]}/api/health", timeout=3) as response:
            assert response.status == 200
        second = subprocess.run(base_command + ["--stop", "--port", str(ports[1])],
                                env=env, capture_output=True, text=True, timeout=10)
        assert second.returncode == 0, second.stderr
        processes[1].wait(timeout=10)
        assert not list(tmp_path.glob("collector*.pid"))
    finally:
        for process in processes:
            if process.poll() is None:
                process.terminate()
                process.wait(timeout=10)
