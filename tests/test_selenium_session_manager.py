"""Unit tests for servers/selenium_session_manager.py.

The Selenium session manager opens/closes browser sessions for the
console UI via the Grid REST API (FastAPI + TestClient).
"""

import importlib.util
import json
from pathlib import Path
from unittest.mock import patch

from fastapi.testclient import TestClient

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


def _client(sm):
    return TestClient(sm.app)


class TestSeleniumSessions:
    def test_open_and_list_and_close(self, monkeypatch, tmp_path):
        sm = _load_sm(monkeypatch, tmp_path)
        client = _client(sm)
        session = {"browser": "selenium-chrome", "node": None, "session_id": "abc"}
        with patch.object(sm._SeleniumBackend, "open", return_value=session) as m:
            r = client.post(
                "/api/selenium/sessions",
                json={"browser": "selenium-chrome", "node": "chromium-profile"},
            )
            assert r.status_code == 200
            m.assert_called_once_with("selenium-chrome", node="chromium-profile", url=None)
            sid = r.json()["id"]
        r = client.get("/api/selenium/sessions")
        assert r.status_code == 200
        sessions = r.json()["sessions"]
        assert len(sessions) == 1
        assert sessions[0]["id"] == sid
        assert sessions[0]["browser"] == "selenium-chrome"
        assert "target" not in sessions[0]
        with patch.object(sm._SeleniumBackend, "close") as m:
            r = client.delete(f"/api/selenium/sessions/{sid}")
            assert r.status_code == 200
            m.assert_called_once_with(session)

    def test_open_unknown_browser_422(self, monkeypatch, tmp_path):
        sm = _load_sm(monkeypatch, tmp_path)
        r = _client(sm).post("/api/selenium/sessions", json={"browser": "nope"})
        assert r.status_code == 422

    def test_open_unknown_field_422(self, monkeypatch, tmp_path):
        sm = _load_sm(monkeypatch, tmp_path)
        r = _client(sm).post(
            "/api/selenium/sessions",
            json={"browser": "selenium-chrome", "bogus": 1},
        )
        assert r.status_code == 422

    def test_open_context_options_422(self, monkeypatch, tmp_path):
        # context_options is playwright-only; the selenium manager rejects it.
        sm = _load_sm(monkeypatch, tmp_path)
        r = _client(sm).post(
            "/api/selenium/sessions",
            json={"browser": "selenium-chrome", "context_options": {"locale": "ja-JP"}},
        )
        assert r.status_code == 422

    def test_open_non_string_node_422(self, monkeypatch, tmp_path):
        sm = _load_sm(monkeypatch, tmp_path)
        r = _client(sm).post(
            "/api/selenium/sessions",
            json={"browser": "selenium-chrome", "node": ["x"]},
        )
        assert r.status_code == 422
        assert "node" in str(r.json()["detail"])

    def test_open_bad_url_422(self, monkeypatch, tmp_path):
        sm = _load_sm(monkeypatch, tmp_path)
        for url in ({"u": 1}, "", "  "):
            r = _client(sm).post(
                "/api/selenium/sessions",
                json={"browser": "selenium-chrome", "url": url},
            )
            assert r.status_code == 422
            assert "url" in str(r.json()["detail"])

    def test_open_blank_node_422(self, monkeypatch, tmp_path):
        sm = _load_sm(monkeypatch, tmp_path)
        r = _client(sm).post(
            "/api/selenium/sessions",
            json={"browser": "selenium-chrome", "node": "  "},
        )
        assert r.status_code == 422
        assert "node" in str(r.json()["detail"])

    def test_open_accepts_w3c_value_session_id(self, monkeypatch, tmp_path):
        """Grid 4.x answers {"value": {"sessionId": ...}} (W3C shape)."""
        sm = _load_sm(monkeypatch, tmp_path)
        client = _client(sm)
        created = {"value": {"sessionId": "w3c-id", "capabilities": {}}}
        with patch.object(sm._SeleniumBackend, "_request", return_value=created) as m:
            r = client.post("/api/selenium/sessions", json={"browser": "selenium-firefox"})
            assert r.status_code == 200
            # create + maximize; no url follow-up without url
            assert m.call_count == 2
            assert m.call_args_list[1] == (
                ("POST", "/session/w3c-id/window/maximize", {}),
                {},
            )
        r = client.get("/api/selenium/sessions")
        assert r.status_code == 200
        assert r.json()["sessions"][0]["browser"] == "selenium-firefox"

    def test_open_maximizes_before_navigate(self, monkeypatch, tmp_path):
        sm = _load_sm(monkeypatch, tmp_path)
        calls = []

        def fake_request(method, path, payload=None):
            calls.append((method, path, payload))
            return {"sessionId": "abc"}

        with patch.object(sm._SeleniumBackend, "_request", side_effect=fake_request):
            r = _client(sm).post(
                "/api/selenium/sessions",
                json={"browser": "selenium-chrome", "url": "https://example.com"},
            )
            assert r.status_code == 200
        assert calls == [
            ("POST", "/session", {"capabilities": {"alwaysMatch": {"browserName": "chrome"}}}),
            ("POST", "/session/abc/window/maximize", {}),
            ("POST", "/session/abc/url", {"url": "https://example.com"}),
        ]

    def test_open_maximize_failure_continues(self, monkeypatch, tmp_path, capsys):
        # Maximize is best effort: a rejecting driver must not destroy the
        # session. Navigation still runs and no compensating close happens.
        sm = _load_sm(monkeypatch, tmp_path)
        calls = []

        def fake_request(method, path, payload=None):
            calls.append((method, path))
            if path.endswith("/window/maximize"):
                raise RuntimeError("maximize failed")
            return {"sessionId": "abc"}

        with patch.object(sm._SeleniumBackend, "_request", side_effect=fake_request):
            r = _client(sm).post(
                "/api/selenium/sessions",
                json={"browser": "selenium-chrome", "url": "https://example.com"},
            )
            assert r.status_code == 200
            assert "maximize failed" in capsys.readouterr().err
        assert ("POST", "/session/abc/url") in calls
        assert not any(method == "DELETE" for method, _ in calls)

    def test_open_backend_failure_502(self, monkeypatch, tmp_path, capsys):
        sm = _load_sm(monkeypatch, tmp_path)
        with patch.object(
            sm._SeleniumBackend, "open", side_effect=RuntimeError("grid internal down")
        ):
            r = _client(sm).post("/api/selenium/sessions", json={"browser": "selenium-chrome"})
            assert r.status_code == 502
            assert "grid internal down" in str(r.json()["detail"])
        assert "grid internal down" in capsys.readouterr().err

    def test_open_rejects_malformed_session_id(self, monkeypatch, tmp_path, capsys):
        sm = _load_sm(monkeypatch, tmp_path)
        with patch.object(sm._SeleniumBackend, "_request", return_value={"sessionId": "../evil"}):
            r = _client(sm).post("/api/selenium/sessions", json={"browser": "selenium-chrome"})
            assert r.status_code == 502
            # Trusted clients: the raw Grid reply is surfaced verbatim.
            assert "Grid did not return a sessionId" in str(r.json()["detail"])
            assert "../evil" in str(r.json()["detail"])
        out = capsys.readouterr().err
        assert "../evil" in out

    def test_request_timeout_env(self, monkeypatch, tmp_path):
        sm = _load_sm(monkeypatch, tmp_path, env={"SELENIUM_REQUEST_TIMEOUT": "5"})
        assert sm.REQUEST_TIMEOUT == 5
        sm = _load_sm(monkeypatch, tmp_path)
        assert sm.REQUEST_TIMEOUT == 30

    def test_invalid_json_422(self, monkeypatch, tmp_path):
        sm = _load_sm(monkeypatch, tmp_path)
        r = _client(sm).post(
            "/api/selenium/sessions",
            content=b"{broken",
            headers={"Content-Type": "application/json"},
        )
        assert r.status_code == 422
        assert "detail" in r.json()

    def test_not_found(self, monkeypatch, tmp_path):
        sm = _load_sm(monkeypatch, tmp_path)
        r = _client(sm).get("/api/nope")
        assert r.status_code == 404
        assert "detail" in r.json()

    def test_close_failure_retryable(self, monkeypatch, tmp_path):
        sm = _load_sm(monkeypatch, tmp_path)
        client = _client(sm)
        session = {"browser": "selenium-chrome", "node": None, "session_id": "abc"}
        with patch.object(sm._SeleniumBackend, "open", return_value=session):
            r = client.post("/api/selenium/sessions", json={"browser": "selenium-chrome"})
            assert r.status_code == 200
            sid = r.json()["id"]
        with patch.object(sm._SeleniumBackend, "close", side_effect=RuntimeError("grid down")):
            r = client.delete(f"/api/selenium/sessions/{sid}")
            assert r.status_code == 502
            assert r.json()["retryable"] is True
            assert "grid down" in str(r.json()["detail"])
        with patch.object(sm._SeleniumBackend, "close", return_value=None):
            r = client.delete(f"/api/selenium/sessions/{sid}")
            assert r.status_code == 200

    def test_close_gone_session_404(self, monkeypatch, tmp_path, capsys):
        import urllib.error

        sm = _load_sm(monkeypatch, tmp_path)
        client = _client(sm)
        session = {"browser": "selenium-chrome", "node": None, "session_id": "abc"}
        with patch.object(sm._SeleniumBackend, "open", return_value=session):
            r = client.post("/api/selenium/sessions", json={"browser": "selenium-chrome"})
            assert r.status_code == 200
            sid = r.json()["id"]
        err = urllib.error.HTTPError("http://grid/session/abc", 404, "Not Found", {}, None)
        with patch.object(sm._SeleniumBackend, "_request", side_effect=err):
            r = client.delete(f"/api/selenium/sessions/{sid}")
            assert r.status_code == 404
        # The gone log names the manager id and the Grid id for cleanup.
        err_out = capsys.readouterr().err
        assert sid in err_out
        assert "'abc'" in err_out
        r = client.get("/api/selenium/sessions")
        assert r.json() == {"sessions": []}

    def test_close_body_message_404(self, monkeypatch, tmp_path):
        import io
        import urllib.error

        sm = _load_sm(monkeypatch, tmp_path)
        client = _client(sm)
        session = {"browser": "selenium-chrome", "node": None, "session_id": "abc"}
        with patch.object(sm._SeleniumBackend, "open", return_value=session):
            r = client.post("/api/selenium/sessions", json={"browser": "selenium-chrome"})
            assert r.status_code == 200
            sid = r.json()["id"]
        body = b'{"value": {"message": "no such session: abc"}}'
        err = urllib.error.HTTPError(
            "http://grid/session/abc",
            400,
            "Bad Request",
            {},
            io.BytesIO(body),
        )
        with patch.object(sm._SeleniumBackend, "_request", side_effect=err):
            r = client.delete(f"/api/selenium/sessions/{sid}")
            assert r.status_code == 404
        r = client.get("/api/selenium/sessions")
        assert r.json() == {"sessions": []}

    def test_open_strips_inputs(self, monkeypatch, tmp_path):
        sm = _load_sm(monkeypatch, tmp_path)
        session = {"browser": "selenium-chrome", "node": None, "session_id": "abc"}
        with patch.object(sm._SeleniumBackend, "open", return_value=session) as m:
            r = _client(sm).post(
                "/api/selenium/sessions",
                json={
                    "browser": "selenium-chrome",
                    "node": "  chromium-profile  ",
                    "url": "  https://example.com  ",
                },
            )
            assert r.status_code == 200
            m.assert_called_once_with(
                "selenium-chrome", node="chromium-profile", url="https://example.com"
            )
            assert r.json()["url"] == "https://example.com"

    def test_open_non_dict_json_422(self, monkeypatch, tmp_path):
        sm = _load_sm(monkeypatch, tmp_path)
        r = _client(sm).post(
            "/api/selenium/sessions",
            content=b"[1,2]",
            headers={"Content-Type": "application/json"},
        )
        assert r.status_code == 422

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
        assert seen["n"] == sm.GRID_READ_CAP

    def test_known_path_wrong_method_405(self, monkeypatch, tmp_path):
        sm = _load_sm(monkeypatch, tmp_path)
        r = _client(sm).post("/api/selenium/sessions/xxx", json={})
        assert r.status_code == 405
        assert "detail" in r.json()

    def test_unknown_path_404(self, monkeypatch, tmp_path):
        sm = _load_sm(monkeypatch, tmp_path)
        r = _client(sm).post("/api/nope", json={})
        assert r.status_code == 404
        assert "detail" in r.json()

    def test_close_failure_log_escapes_newline(self, monkeypatch, tmp_path, capsys):
        # Starlette strips raw newlines from path params, so call the
        # endpoint directly with an attacker-controlled id.
        sm = _load_sm(monkeypatch, tmp_path)
        session = {"browser": "selenium-chrome", "node": None, "session_id": "abc"}
        sm._se_sessions["evil\ninjected"] = session
        with patch.object(sm._SeleniumBackend, "close", side_effect=RuntimeError("grid down")):
            resp = sm.close_session("evil\ninjected")
            assert resp.status_code == 502
        out = capsys.readouterr().err
        assert "evil\\ninjected" in out
        assert out.count("\n") == 1

    def test_close_malformed_entry_500(self, monkeypatch, tmp_path, capsys):
        # An entry missing session_id is a bug, not a gone session:
        # 500 without retryable (never 404, never retryable 502).
        sm = _load_sm(monkeypatch, tmp_path)
        sm._se_sessions["broken"] = {"browser": "selenium-chrome", "node": None}
        resp = sm.close_session("broken")
        assert resp.status_code == 500
        assert "retryable" not in json.loads(resp.body)
        assert "malformed entry 'broken'" in capsys.readouterr().err

    def test_close_non_string_session_id_500(self, monkeypatch, tmp_path):
        # A non-string id must not reach the Grid (would 502 there).
        sm = _load_sm(monkeypatch, tmp_path)
        sm._se_sessions["bad"] = {"browser": "selenium-chrome", "session_id": 123}
        resp = sm.close_session("bad")
        assert resp.status_code == 500
        assert "retryable" not in json.loads(resp.body)

    def test_close_non_dict_entry_500(self, monkeypatch, tmp_path):
        sm = _load_sm(monkeypatch, tmp_path)
        sm._se_sessions["weird"] = ["oops"]
        resp = sm.close_session("weird")
        assert resp.status_code == 500
        assert "retryable" not in json.loads(resp.body)

    def test_list_tolerates_malformed_entry(self, monkeypatch, tmp_path):
        # One broken entry must not take down the whole listing.
        sm = _load_sm(monkeypatch, tmp_path)
        client = _client(sm)
        session = {"browser": "selenium-chrome", "node": None, "session_id": "abc"}
        with patch.object(sm._SeleniumBackend, "open", return_value=session):
            r = client.post("/api/selenium/sessions", json={"browser": "selenium-chrome"})
            assert r.status_code == 200
            sid = r.json()["id"]
        sm._se_sessions["broken"] = {"browser": "selenium-chrome", "node": None}
        sm._se_sessions["non-dict"] = ["oops"]
        r = client.get("/api/selenium/sessions")
        assert r.status_code == 200
        ids = {s["id"] for s in r.json()["sessions"]}
        assert {sid, "broken", "non-dict"} <= ids


class TestBrowserField:
    def _session(self):
        return {"browser": "selenium-chrome", "node": None, "session_id": "abc"}

    def test_browser_field_is_canonical(self, monkeypatch, tmp_path):
        sm = _load_sm(monkeypatch, tmp_path)
        with patch.object(sm._SeleniumBackend, "open", return_value=self._session()) as m:
            r = _client(sm).post("/api/selenium/sessions", json={"browser": "selenium-firefox"})
        assert r.status_code == 200
        m.assert_called_once_with("selenium-firefox", node=None, url=None)
        assert r.json()["browser"] == "selenium-firefox"
        assert "target" not in r.json()

    def test_target_field_is_rejected_422(self, monkeypatch, tmp_path):
        # ``target`` was renamed to ``browser`` in v2.0.0 and is no longer
        # accepted (no deprecation alias).
        sm = _load_sm(monkeypatch, tmp_path)
        r = _client(sm).post("/api/selenium/sessions", json={"target": "selenium-chrome"})
        assert r.status_code == 422


class TestOpenAPI:
    def test_openapi_and_docs(self, monkeypatch, tmp_path):
        sm = _load_sm(monkeypatch, tmp_path)
        client = _client(sm)
        assert client.get("/openapi.json").status_code == 200
        assert client.get("/docs").status_code == 200
