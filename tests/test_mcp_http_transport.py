import json
import os
import socket
import subprocess
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path

import pytest

pytest.importorskip("chromadb")

ROOT = Path(__file__).resolve().parents[1]


def _free_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.bind(("127.0.0.1", 0))
        return sock.getsockname()[1]


def _wait_for_healthz(proc: subprocess.Popen, port: int, timeout: float = 20.0) -> None:
    deadline = time.monotonic() + timeout
    url = f"http://127.0.0.1:{port}/healthz"
    last_error = None

    while time.monotonic() < deadline:
        if proc.poll() is not None:
            stdout, stderr = proc.communicate(timeout=5)
            raise AssertionError(
                "HTTP server exited before /healthz became ready\n"
                f"returncode={proc.returncode}\n"
                f"stdout={stdout!r}\n"
                f"stderr={stderr!r}"
            )

        try:
            with urllib.request.urlopen(url, timeout=1) as resp:
                body = resp.read().decode("utf-8").strip()
                if resp.status == 200 and body == "ok":
                    return
        except Exception as exc:
            last_error = exc
            time.sleep(0.1)

    raise AssertionError(f"HTTP server did not become ready: {last_error!r}")


def _rpc(port: int, method: str, params: dict | None = None, req_id: int = 1):
    payload = {
        "jsonrpc": "2.0",
        "id": req_id,
        "method": method,
        "params": params or {},
    }
    request = urllib.request.Request(
        f"http://127.0.0.1:{port}/mcp",
        data=json.dumps(payload).encode("utf-8"),
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    with urllib.request.urlopen(request, timeout=10) as resp:
        body = resp.read().decode("utf-8")
        return resp.status, json.loads(body) if body else None


def _start_http_server(tmp_path, port: int):
    palace = tmp_path / "palace"
    palace.mkdir()

    env = os.environ.copy()
    env["MEMPALACE_EAGER_WARMUP"] = "0"
    env["MEMPALACE_MCP_IDLE_HOURS"] = "0"

    return subprocess.Popen(
        [
            sys.executable,
            "-m",
            "mempalace.mcp_server",
            "--transport",
            "http",
            "--host",
            "127.0.0.1",
            "--port",
            str(port),
            "--palace",
            str(palace),
        ],
        cwd=str(ROOT),
        env=env,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
    )


def _stop_process(proc: subprocess.Popen) -> tuple[str, str]:
    if proc.poll() is None:
        proc.terminate()

    try:
        return proc.communicate(timeout=20)
    except subprocess.TimeoutExpired:
        proc.kill()
        return proc.communicate(timeout=20)


def test_parse_args_defaults_to_stdio(monkeypatch):
    from mempalace import mcp_server

    monkeypatch.setattr(sys, "argv", ["mempalace-mcp"])

    args = mcp_server._parse_args()

    assert args.transport == "stdio"
    assert args.host == "127.0.0.1"
    assert args.port == 8765


def test_parse_args_accepts_http_transport(monkeypatch):
    from mempalace import mcp_server

    monkeypatch.setattr(
        sys,
        "argv",
        [
            "mempalace-mcp",
            "--transport",
            "http",
            "--host",
            "0.0.0.0",
            "--port",
            "9999",
        ],
    )

    args = mcp_server._parse_args()

    assert args.transport == "http"
    assert args.host == "0.0.0.0"
    assert args.port == 9999


def test_http_transport_serves_initialize_ping_and_repeated_tools_list(tmp_path):
    port = _free_port()
    proc = _start_http_server(tmp_path, port)

    try:
        _wait_for_healthz(proc, port)

        status, initialized = _rpc(
            port,
            "initialize",
            {"protocolVersion": "2025-11-25"},
            req_id=1,
        )
        assert status == 200
        assert initialized["result"]["protocolVersion"] == "2025-11-25"

        status, ping = _rpc(port, "ping", {}, req_id=2)
        assert status == 200
        assert ping["result"] == {}

        status, first = _rpc(port, "tools/list", {}, req_id=3)
        assert status == 200
        tools = first["result"]["tools"]
        assert len(tools) > 0
        assert all("name" in tool and "inputSchema" in tool for tool in tools)

        # Regression shape for #1801: repeated large tools/list frames should
        # keep succeeding in the same long-lived HTTP process.
        for req_id in range(4, 12):
            status, payload = _rpc(port, "tools/list", {}, req_id=req_id)
            assert status == 200
            assert payload["id"] == req_id
            assert payload["result"]["tools"] == tools

    finally:
        stdout, _stderr = _stop_process(proc)

    # HTTP transport must never emit JSON-RPC frames on stdout.
    assert stdout.strip() == ""


def test_http_transport_returns_parse_error_for_invalid_json(tmp_path):
    port = _free_port()
    proc = _start_http_server(tmp_path, port)

    try:
        _wait_for_healthz(proc, port)

        request = urllib.request.Request(
            f"http://127.0.0.1:{port}/mcp",
            data=b"not-json",
            headers={"Content-Type": "application/json"},
            method="POST",
        )

        with pytest.raises(urllib.error.HTTPError) as excinfo:
            urllib.request.urlopen(request, timeout=10)

        body = excinfo.value.read().decode("utf-8")
        payload = json.loads(body)

        assert excinfo.value.code == 400
        assert payload["error"]["code"] == -32700
        assert payload["error"]["message"] == "Parse error"

    finally:
        _stop_process(proc)


def test_http_transport_accepts_notifications_without_body(tmp_path):
    port = _free_port()
    proc = _start_http_server(tmp_path, port)

    try:
        _wait_for_healthz(proc, port)

        payload = {
            "jsonrpc": "2.0",
            "method": "notifications/initialized",
            "params": {},
        }
        request = urllib.request.Request(
            f"http://127.0.0.1:{port}/mcp",
            data=json.dumps(payload).encode("utf-8"),
            headers={"Content-Type": "application/json"},
            method="POST",
        )

        with urllib.request.urlopen(request, timeout=10) as resp:
            body = resp.read()

        assert resp.status == 202
        assert body == b""

    finally:
        _stop_process(proc)
