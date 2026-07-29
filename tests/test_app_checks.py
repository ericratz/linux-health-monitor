"""
Tests for the app-level HTTP checks, including a real local server so the
request path (not just the parsing) is exercised.
"""
import json
import threading
from http.server import BaseHTTPRequestHandler, HTTPServer

import pytest

from agent import app_checks


def test_parse_endpoints_accepts_name_url_pairs():
    parsed = app_checks.parse_endpoints("a=http://x/health,b=http://y/slo")
    assert parsed == [("a", "http://x/health"), ("b", "http://y/slo")]


def test_parse_endpoints_accepts_json_object():
    raw = '{"node1": "http://192.168.71.251:8000/health"}'
    assert app_checks.parse_endpoints(raw) == [
        ("node1", "http://192.168.71.251:8000/health")
    ]


def test_parse_endpoints_names_a_bare_url_after_itself():
    assert app_checks.parse_endpoints("http://x/health") == [
        ("http://x/health", "http://x/health")
    ]


def test_parse_endpoints_tolerates_whitespace_and_empty_items():
    assert app_checks.parse_endpoints(" a=http://x , , b=http://y ") == [
        ("a", "http://x"), ("b", "http://y")
    ]


def test_parse_endpoints_empty_and_malformed():
    assert app_checks.parse_endpoints("") == []
    assert app_checks.parse_endpoints(None) == []
    assert app_checks.parse_endpoints("   ") == []
    #malformed JSON must not raise, just yield nothing
    assert app_checks.parse_endpoints('{"broken": ') == []
    assert app_checks.parse_endpoints('{"not": {"a": "dict of str"}}') == [
        ("not", "{'a': 'dict of str'}")
    ]


def test_unconfigured_feature_reports_itself_absent(monkeypatch):
    monkeypatch.delenv(app_checks.ENDPOINTS_ENV, raising=False)
    result = app_checks.get_app_checks()
    assert result["success"] is False
    assert result["data"] is None
    assert app_checks.ENDPOINTS_ENV in result["reason"]


def test_unreachable_endpoint_is_a_result_not_an_exception():
    #port 9 (discard) is reliably closed for TCP on a normal host
    check = app_checks.check_endpoint("down", "http://127.0.0.1:9/health", timeout=0.5)
    assert check["success"] is False
    assert "error" in check
    assert isinstance(check["latency_ms"], float)


def test_invalid_url_scheme_is_handled():
    check = app_checks.check_endpoint("bad", "not-a-url", timeout=0.5)
    assert check["success"] is False
    assert "error" in check


def test_timeout_is_read_from_env(monkeypatch):
    monkeypatch.setenv(app_checks.TIMEOUT_ENV, "7.5")
    assert app_checks._endpoint_timeout() == 7.5
    monkeypatch.setenv(app_checks.TIMEOUT_ENV, "not-a-number")
    assert app_checks._endpoint_timeout() == app_checks.DEFAULT_TIMEOUT


def test_attach_body_prefers_structured_json():
    result = {}
    app_checks._attach_body(result, '{"status": "ok"}')
    assert result["data"] == {"status": "ok"}
    assert "body" not in result


def test_attach_body_keeps_non_json_as_text():
    result = {}
    app_checks._attach_body(result, "plain text")
    assert result["body"] == "plain text"
    assert "data" not in result


def test_attach_body_truncates_an_oversized_response():
    result = {}
    app_checks._attach_body(result, "x" * (app_checks.MAX_BODY_CHARS + 500))
    assert result["truncated"] is True
    assert len(result["body"]) == app_checks.MAX_BODY_CHARS


class _Handler(BaseHTTPRequestHandler):
    def do_GET(self):
        if self.path == "/health":
            payload = json.dumps({"status": "ok", "node": "node1"}).encode()
            self.send_response(200)
        elif self.path == "/degraded":
            payload = json.dumps({"status": "degraded"}).encode()
            self.send_response(503)
        else:
            payload = b"not json"
            self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(payload)))
        self.end_headers()
        self.wfile.write(payload)

    def log_message(self, *args):
        pass


@pytest.fixture
def local_server():
    server = HTTPServer(("127.0.0.1", 0), _Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    yield f"http://127.0.0.1:{server.server_port}"
    server.shutdown()
    server.server_close()


def test_healthy_endpoint_returns_status_latency_and_body(local_server):
    check = app_checks.check_endpoint("health", f"{local_server}/health")
    assert check["success"] is True
    assert check["http_status"] == 200
    assert check["data"] == {"status": "ok", "node": "node1"}
    assert check["latency_ms"] >= 0


def test_error_status_still_captures_the_body(local_server):
    #a 503 with a JSON body is exactly what a degraded service returns
    check = app_checks.check_endpoint("degraded", f"{local_server}/degraded")
    assert check["success"] is False
    assert check["http_status"] == 503
    assert check["data"] == {"status": "degraded"}


def test_non_json_response_is_kept_raw(local_server):
    check = app_checks.check_endpoint("plain", f"{local_server}/other")
    assert check["success"] is True
    assert check["body"] == "not json"


def test_get_app_checks_counts_healthy_endpoints(monkeypatch, local_server):
    monkeypatch.setenv(
        app_checks.ENDPOINTS_ENV,
        f"up={local_server}/health,bad={local_server}/degraded,down=http://127.0.0.1:9/x",
    )
    monkeypatch.setenv(app_checks.TIMEOUT_ENV, "1")
    result = app_checks.get_app_checks()
    assert result["success"] is True
    assert result["count"] == 3
    assert result["healthy"] == 1
    assert [c["name"] for c in result["data"]] == ["up", "bad", "down"]
