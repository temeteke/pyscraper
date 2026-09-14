"""Unit tests for servers/selenium_session_manager.py.

The Selenium session manager opens/closes browser sessions for the
gateway UI via the Grid REST API.
"""

import importlib.util
import io
import json
from pathlib import Path
from unittest.mock import patch

SM_PATH = Path(__file__).resolve().parent.parent / "servers" / "selenium_session_manager.py"


def _load_sm(monkeypatch, tmp_path, env=None):
    for key in (
        "SELENIUM_SESSION_MANAGER_PORT",
        "SELENIUM_HUB_URL",
        "SELENIUM_REQUEST_TIMEOUT",
    ):
        monkeypatch.delenv(key, raising=False)
    for key, value in (env or {}).items():
        monkeypatch.setenv(key, value)
    spec = importlib.util.spec_from_file_location("selenium_session_manager", SM_PATH)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    module._se_sessions.clear()
    return module


def _make_request(sm, method, path, payload=None):
    handler = sm._Handler.__new__(sm._Handler)
    handler.path = path
    body = json.dumps(payload).encode() if payload is not None else b""
    handler.rfile = io.BytesIO(body)
    handler.headers = {"Content-Length": str(len(body))}
    responses = []

    def fake_send_response(code):
        responses.append({"code": code, "headers": {}})

    handler.send_response = fake_send_response
    handler.send_header = lambda k, v: responses[-1]["headers"].update({k: v})
    handler.end_headers = lambda: None
    out = io.BytesIO()
    handler.wfile = out
    getattr(handler, f"do_{method}")()
    assert responses, "no response sent"
    return responses[-1]["code"], json.loads(out.getvalue() or b"{}")

class TestSeleniumSessions:
    def test_open_and_list_and_close(self, monkeypatch, tmp_path):
        sm = _load_sm(monkeypatch, tmp_path)
        session = {"target": "selenium-chrome", "session_id": "abc"}
        with patch.object(sm._SeleniumBackend, "open", return_value=session) as m:
            code, data = _make_request(sm, "POST",
                "/api/selenium/sessions",
                {"target": "selenium-chrome", "node": "chromium-profile"},
            )
            assert code == 200
            m.assert_called_once_with(
                "selenium-chrome", node="chromium-profile", url=None
            )
            sid = data["id"]
        code, data = _make_request(sm, "GET", "/api/selenium/sessions")
        assert code == 200
        assert data == {"sessions": [{"id": sid, "target": "selenium-chrome"}]}
        with patch.object(sm._SeleniumBackend, "close") as m:
            code, _ = _make_request(sm, "DELETE", f"/api/selenium/sessions/{sid}")
            assert code == 200
            m.assert_called_once_with(session)

    def test_open_unknown_target(self, monkeypatch, tmp_path):
        sm = _load_sm(monkeypatch, tmp_path)
        code, data = _make_request(sm, "POST", "/api/selenium/sessions", {"target": "nope"}
        )
        assert code == 400

    def test_open_non_string_node_400(self, monkeypatch, tmp_path):
        sm = _load_sm(monkeypatch, tmp_path)
        code, data = _make_request(sm, "POST",
            "/api/selenium/sessions",
            {"target": "selenium-chrome", "node": ["x"]},
        )
        assert code == 400
        assert "node" in data["error"]

    def test_open_bad_url_400(self, monkeypatch, tmp_path):
        sm = _load_sm(monkeypatch, tmp_path)
        for url in ({"u": 1}, "", "  "):
            code, data = _make_request(sm, "POST",
                "/api/selenium/sessions",
                {"target": "selenium-chrome", "url": url},
            )
            assert code == 400
            assert "url" in data["error"]

    def test_open_blank_node_400(self, monkeypatch, tmp_path):
        sm = _load_sm(monkeypatch, tmp_path)
        code, data = _make_request(sm, "POST",
            "/api/selenium/sessions",
            {"target": "selenium-chrome", "node": "  "},
        )
        assert code == 400
        assert "node" in data["error"]

    def test_open_accepts_w3c_value_session_id(self, monkeypatch, tmp_path):
        """Grid 4.x answers {"value": {"sessionId": ...}} (W3C shape)."""
        sm = _load_sm(monkeypatch, tmp_path)
        created = {"value": {"sessionId": "w3c-id", "capabilities": {}}}
        with patch.object(
            sm._SeleniumBackend, "_request", return_value=created
        ) as m:
            code, data = _make_request(
                sm, "POST", "/api/selenium/sessions", {"target": "selenium-firefox"}
            )
            assert code == 200
            assert m.call_count == 1  # no url follow-up without url
        code, data = _make_request(sm, "GET", "/api/selenium/sessions")
        assert code == 200
        assert data["sessions"][0]["target"] == "selenium-firefox"

    def test_open_rejects_malformed_session_id(self, monkeypatch, tmp_path):
        sm = _load_sm(monkeypatch, tmp_path)
        with patch.object(
            sm._SeleniumBackend, "_request", return_value={"sessionId": "../evil"}
        ):
            code, data = _make_request(
                sm, "POST", "/api/selenium/sessions", {"target": "selenium-chrome"}
            )
            assert code == 502
            assert "sessionId" in data["error"]
            assert len(data["error"]) <= 600  # truncated, no full Grid dump

    def test_request_timeout_env(self, monkeypatch, tmp_path):
        sm = _load_sm(monkeypatch, tmp_path, env={"SELENIUM_REQUEST_TIMEOUT": "5"})
        assert sm.REQUEST_TIMEOUT == 5
        sm = _load_sm(monkeypatch, tmp_path)
        assert sm.REQUEST_TIMEOUT == 30

    def test_invalid_json_400(self, monkeypatch, tmp_path):
        sm = _load_sm(monkeypatch, tmp_path)
        handler = sm._Handler.__new__(sm._Handler)
        handler.path = "/api/selenium/sessions"
        handler.rfile = io.BytesIO(b"{broken")
        handler.headers = {"Content-Length": "7"}
        codes = []
        handler.send_response = lambda c: codes.append(c)
        handler.send_header = lambda k, v: None
        handler.end_headers = lambda: None
        handler.wfile = io.BytesIO()
        handler.do_POST()
        assert codes == [400]

    def test_not_found(self, monkeypatch, tmp_path):
        sm = _load_sm(monkeypatch, tmp_path)
        code, _ = _make_request(sm, "GET", "/api/nope")
        assert code == 404

    def test_close_failure_retryable(self, monkeypatch, tmp_path):
        sm = _load_sm(monkeypatch, tmp_path)
        session = {"target": "selenium-chrome", "session_id": "abc"}
        with patch.object(sm._SeleniumBackend, "open", return_value=session):
            code, opened = _make_request(
                sm, "POST", "/api/selenium/sessions", {"target": "selenium-chrome"}
            )
            assert code == 200
        with patch.object(
            sm._SeleniumBackend, "close", side_effect=RuntimeError("grid down")
        ):
            code, data = _make_request(sm, "DELETE", f"/api/selenium/sessions/{opened['id']}")
            assert code == 502
            assert data["retryable"] is True
        with patch.object(sm._SeleniumBackend, "close", return_value=None):
            code, _ = _make_request(sm, "DELETE", f"/api/selenium/sessions/{opened['id']}")
            assert code == 200

    def test_close_gone_session_404(self, monkeypatch, tmp_path):
        import urllib.error

        sm = _load_sm(monkeypatch, tmp_path)
        session = {"target": "selenium-chrome", "session_id": "abc"}
        with patch.object(sm._SeleniumBackend, "open", return_value=session):
            code, opened = _make_request(
                sm, "POST", "/api/selenium/sessions", {"target": "selenium-chrome"}
            )
            assert code == 200
        err = urllib.error.HTTPError(
            "http://grid/session/abc", 404, "Not Found", {}, None
        )
        with patch.object(sm._SeleniumBackend, "_request", side_effect=err):
            code, data = _make_request(sm, "DELETE", f"/api/selenium/sessions/{opened['id']}")
            assert code == 404
        code, data = _make_request(sm, "GET", "/api/selenium/sessions")
        assert data == {"sessions": []}

    def test_close_body_message_404(self, monkeypatch, tmp_path):
        import io
        import urllib.error

        sm = _load_sm(monkeypatch, tmp_path)
        session = {"target": "selenium-chrome", "session_id": "abc"}
        with patch.object(sm._SeleniumBackend, "open", return_value=session):
            code, opened = _make_request(
                sm, "POST", "/api/selenium/sessions", {"target": "selenium-chrome"}
            )
            assert code == 200
        body = b'{"value": {"message": "no such session: abc"}}'
        err = urllib.error.HTTPError(
            "http://grid/session/abc", 400, "Bad Request",
            {}, io.BytesIO(body),
        )
        with patch.object(sm._SeleniumBackend, "_request", side_effect=err):
            code, _ = _make_request(sm, "DELETE", f"/api/selenium/sessions/{opened['id']}")
            assert code == 404
        code, data = _make_request(sm, "GET", "/api/selenium/sessions")
        assert data == {"sessions": []}

    def test_open_strips_inputs(self, monkeypatch, tmp_path):
        sm = _load_sm(monkeypatch, tmp_path)
        session = {"target": "selenium-chrome", "session_id": "abc"}
        with patch.object(sm._SeleniumBackend, "open", return_value=session) as m:
            code, data = _make_request(sm, "POST",
                "/api/selenium/sessions",
                {"target": "selenium-chrome", "node": "  chromium-profile  ", "url": "  https://example.com  "},
            )
            assert code == 200
            m.assert_called_once_with(
                "selenium-chrome", node="chromium-profile", url="https://example.com"
            )
            assert data["url"] == "https://example.com"

    def test_open_non_dict_json_400(self, monkeypatch, tmp_path):
        sm = _load_sm(monkeypatch, tmp_path)
        handler = sm._Handler.__new__(sm._Handler)
        handler.path = "/api/selenium/sessions"
        handler.rfile = io.BytesIO(b"[1,2]")
        handler.headers = {"Content-Length": "5"}
        codes = []
        handler.send_response = lambda c: codes.append(c)
        handler.send_header = lambda k, v: None
        handler.end_headers = lambda: None
        handler.wfile = io.BytesIO()
        handler.do_POST()
        assert codes == [400]

    def test_open_port_out_of_range_falls_back(self, monkeypatch, tmp_path):
        sm = _load_sm(monkeypatch, tmp_path, env={"SELENIUM_SESSION_MANAGER_PORT": "99999"})
        assert sm.PORT == 8082

    def test_request_read_capped(self, monkeypatch, tmp_path):
        import urllib.request

        sm = _load_sm(monkeypatch, tmp_path)
        seen = {}

        class FakeResp:
            def __init__(self, body):
                self._body = body
            def read(self, n=-1):
                seen["n"] = n
                return self._body[:n] if n is not None and n >= 0 else self._body
            def __enter__(self):
                return self
            def __exit__(self, *a):
                return False

        body = b'{"sessionId": "abc-123"}'
        with patch.object(urllib.request, "urlopen", return_value=FakeResp(body)):
            out = sm._SeleniumBackend._request("GET", "/status")
        assert out == {"sessionId": "abc-123"}
        assert seen["n"] == sm.MAX_BODY_BYTES

    def test_body_too_large_413(self, monkeypatch, tmp_path):
        sm = _load_sm(monkeypatch, tmp_path)
        handler = sm._Handler.__new__(sm._Handler)
        handler.path = "/api/selenium/sessions"
        handler.rfile = io.BytesIO(b"{}")
        handler.headers = {"Content-Length": str(sm.MAX_BODY_BYTES + 1)}
        codes = []
        handler.send_response = lambda c: codes.append(c)
        handler.send_header = lambda k, v: None
        handler.end_headers = lambda: None
        handler.wfile = io.BytesIO()
        handler.do_POST()
        assert codes == [413]

    def test_bad_content_length_400(self, monkeypatch, tmp_path):
        sm = _load_sm(monkeypatch, tmp_path)
        handler = sm._Handler.__new__(sm._Handler)
        handler.path = "/api/selenium/sessions"
        handler.rfile = io.BytesIO(b"{}")
        handler.headers = {"Content-Length": "abc"}
        codes = []
        handler.send_response = lambda c: codes.append(c)
        handler.send_header = lambda k, v: None
        handler.end_headers = lambda: None
        handler.wfile = io.BytesIO()
        handler.do_POST()
        assert codes == [400]

    def test_negative_content_length_400(self, monkeypatch, tmp_path):
        sm = _load_sm(monkeypatch, tmp_path)
        handler = sm._Handler.__new__(sm._Handler)
        handler.path = "/api/selenium/sessions"
        handler.rfile = io.BytesIO(b"{}")
        handler.headers = {"Content-Length": "-5"}
        codes = []
        handler.send_response = lambda c: codes.append(c)
        handler.send_header = lambda k, v: None
        handler.end_headers = lambda: None
        handler.wfile = io.BytesIO()
        handler.do_POST()
        assert codes == [400]

    def test_close_failure_log_escapes_newline(self, monkeypatch, tmp_path, capsys):
        # urlparse strips raw newlines from the path, so stub _route to
        # deliver an attacker-controlled id straight to the log line.
        sm = _load_sm(monkeypatch, tmp_path)
        session = {"target": "selenium-chrome", "session_id": "abc"}
        sm._se_sessions["evil\ninjected"] = session
        with patch.object(
            sm._Handler, "_route",
            return_value=("DELETE", "selenium", ["evil\ninjected"]),
        ):
            with patch.object(
                sm._SeleniumBackend, "close", side_effect=RuntimeError("grid down")
            ):
                code, data = _make_request(sm, "DELETE", "/api/selenium/sessions/evil")
                assert code == 502
                assert data["retryable"] is True
        out = capsys.readouterr().out
        assert "evil\\ninjected" in out
        assert out.count("\n") == 1
