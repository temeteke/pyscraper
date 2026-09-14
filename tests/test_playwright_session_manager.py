"""Unit tests for servers/playwright_session_manager.py.

The Playwright session manager opens/closes browser sessions for the
gateway UI via the Hub relay, with storage_state load/save.
"""

import importlib.util
import io
import json
import threading
from pathlib import Path
from unittest.mock import MagicMock, patch

SM_PATH = Path(__file__).resolve().parent.parent / "servers" / "playwright_session_manager.py"


def _load_sm(monkeypatch, tmp_path, env=None):
    for key in (
        "PLAYWRIGHT_SESSION_MANAGER_PORT",
        "PLAYWRIGHT_HUB_WS",
        "SESSION_STATE_DIR",
        "PLAYWRIGHT_OPEN_TIMEOUT",
        "PLAYWRIGHT_WORKER_TIMEOUT",
    ):
        monkeypatch.delenv(key, raising=False)
    monkeypatch.setenv("SESSION_STATE_DIR", str(tmp_path))
    for key, value in (env or {}).items():
        monkeypatch.setenv(key, value)
    spec = importlib.util.spec_from_file_location("playwright_session_manager", SM_PATH)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    module._pw_sessions.clear()
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

class TestResolveStatePath:
    def test_none_and_dict_passthrough(self, monkeypatch, tmp_path):
        sm = _load_sm(monkeypatch, tmp_path)
        assert sm._resolve_state_path(None) is None
        d = {"cookies": []}
        assert sm._resolve_state_path(d) is d

    def test_relative_resolves_under_state_dir(self, monkeypatch, tmp_path):
        sm = _load_sm(monkeypatch, tmp_path)
        assert sm._resolve_state_path("a.json") == str(tmp_path / "a.json")

    def test_absolute_used_as_is(self, monkeypatch, tmp_path):
        sm = _load_sm(monkeypatch, tmp_path)
        inside = tmp_path / "sub" / "y.json"
        assert sm._resolve_state_path(str(inside)) == str(inside)

    def test_absolute_escape_rejected(self, monkeypatch, tmp_path):
        import pytest

        sm = _load_sm(monkeypatch, tmp_path)
        with pytest.raises(ValueError, match="escapes state dir"):
            sm._resolve_state_path("/etc/passwd")
        with pytest.raises(ValueError, match="escapes state dir"):
            sm._resolve_state_path("../outside.json")
        with pytest.raises(ValueError, match="escapes state dir"):
            sm._resolve_state_path(str(tmp_path / ".." / "outside.json"))

class TestStateFiles:
    def test_empty_dir(self, monkeypatch, tmp_path):
        sm = _load_sm(monkeypatch, tmp_path)
        assert sm._state_files() == []

    def test_lists_files_sorted(self, monkeypatch, tmp_path):
        (tmp_path / "b.json").write_text("{}")
        (tmp_path / "a.json").write_text("{}")
        (tmp_path / "subdir").mkdir()
        sm = _load_sm(monkeypatch, tmp_path)
        assert sm._state_files() == ["a.json", "b.json"]

    def test_get_state_files_endpoint(self, monkeypatch, tmp_path):
        (tmp_path / "s.json").write_text("{}")
        sm = _load_sm(monkeypatch, tmp_path)
        code, data = _make_request(sm, "GET", "/api/state-files")
        assert code == 200
        assert data == {"files": ["s.json"]}

class TestPlaywrightSessions:
    def _mock_backend(self, sm, target="playwright-chromium"):
        session = {
            "target": target,
            "context": MagicMock(),
            "browser": MagicMock(),
            "pw": MagicMock(),
        }
        session["context"].storage_state.return_value = {"cookies": []}
        return session

    def _mock_worker(self, sm, session):
        worker = MagicMock()
        worker.error = None
        worker.save.return_value = {"cookies": []}
        return worker

    def test_open_and_list_and_close(self, monkeypatch, tmp_path):
        sm = _load_sm(monkeypatch, tmp_path)
        worker = self._mock_worker(sm, None)
        with patch.object(sm, "_PlaywrightWorker", return_value=worker) as m:
            code, data = _make_request(sm, "POST",
                "/api/playwright/sessions",
                {"target": "playwright-chromium", "node": "chromium", "url": "https://example.com"},
            )
            assert code == 200
            m.assert_called_once_with(
                "playwright-chromium",
                node="chromium",
                url="https://example.com",
                storage_state=None,
            )
            sid = data["id"]
        code, data = _make_request(sm, "GET", "/api/playwright/sessions")
        assert code == 200
        assert data == {"sessions": [{"id": sid, "target": "playwright-chromium"}]}
        code, data = _make_request(sm, "DELETE", f"/api/playwright/sessions/{sid}")
        assert code == 200
        worker.close.assert_called_once_with()

    def test_open_unknown_target(self, monkeypatch, tmp_path):
        sm = _load_sm(monkeypatch, tmp_path)
        code, data = _make_request(sm, "POST", "/api/playwright/sessions", {"target": "nope"}
        )
        assert code == 400
        assert "unknown target" in data["error"]

    def test_open_escape_storage_state_400(self, monkeypatch, tmp_path):
        sm = _load_sm(monkeypatch, tmp_path)
        code, data = _make_request(sm, "POST",
            "/api/playwright/sessions",
            {"target": "playwright-chromium", "storage_state": "/etc/evil.json"},
        )
        assert code == 400
        assert "escapes state dir" in data["error"]

    def test_open_padded_escape_storage_state_400(self, monkeypatch, tmp_path):
        sm = _load_sm(monkeypatch, tmp_path)
        code, data = _make_request(sm, "POST",
            "/api/playwright/sessions",
            {"target": "playwright-chromium", "storage_state": "  ../outside.json  "},
        )
        assert code == 400
        assert "escapes state dir" in data["error"]

    def test_open_non_dict_json_400(self, monkeypatch, tmp_path):
        import io

        sm = _load_sm(monkeypatch, tmp_path)
        for raw in (b"[1,2]", b'"x"'):
            handler = sm._Handler.__new__(sm._Handler)
            handler.path = "/api/playwright/sessions"
            handler.rfile = io.BytesIO(raw)
            handler.headers = {"Content-Length": str(len(raw))}
            codes = []
            handler.send_response = lambda c: codes.append(c)
            handler.send_header = lambda k, v: None
            handler.end_headers = lambda: None
            handler.wfile = io.BytesIO()
            handler.do_POST()
            assert codes == [400]

    def test_open_empty_dict_storage_state_400(self, monkeypatch, tmp_path):
        sm = _load_sm(monkeypatch, tmp_path)
        code, data = _make_request(sm, "POST",
            "/api/playwright/sessions",
            {"target": "playwright-chromium", "storage_state": {}},
        )
        assert code == 400

    def test_open_port_out_of_range_falls_back(self, monkeypatch, tmp_path):
        sm = _load_sm(monkeypatch, tmp_path, env={"PLAYWRIGHT_SESSION_MANAGER_PORT": "99999"})
        assert sm.PORT == 8081

    def test_open_non_string_storage_state_400(self, monkeypatch, tmp_path):
        sm = _load_sm(monkeypatch, tmp_path)
        for bad in (123, ["a.json"]):
            code, data = _make_request(sm, "POST",
                "/api/playwright/sessions",
                {"target": "playwright-chromium", "storage_state": bad},
            )
            assert code == 400
            assert "string or dict" in data["error"]

    def test_open_empty_storage_state_400(self, monkeypatch, tmp_path):
        sm = _load_sm(monkeypatch, tmp_path)
        code, data = _make_request(sm, "POST",
            "/api/playwright/sessions",
            {"target": "playwright-chromium", "storage_state": ""},
        )
        assert code == 400

    def test_open_non_string_node_400(self, monkeypatch, tmp_path):
        sm = _load_sm(monkeypatch, tmp_path)
        code, data = _make_request(sm, "POST",
            "/api/playwright/sessions",
            {"target": "playwright-chromium", "node": ["chromium"]},
        )
        assert code == 400
        assert "node" in data["error"]

    def test_open_non_string_url_400(self, monkeypatch, tmp_path):
        sm = _load_sm(monkeypatch, tmp_path)
        code, data = _make_request(sm, "POST",
            "/api/playwright/sessions",
            {"target": "playwright-chromium", "url": {"u": 1}},
        )
        assert code == 400
        assert "url" in data["error"]

    def test_open_blank_inputs_400(self, monkeypatch, tmp_path):
        sm = _load_sm(monkeypatch, tmp_path)
        for payload in (
            {"target": "playwright-chromium", "node": "  "},
            {"target": "playwright-chromium", "url": "  "},
            {"target": "playwright-chromium", "storage_state": "  "},
        ):
            code, _ = _make_request(sm, "POST", "/api/playwright/sessions", payload)
            assert code == 400

    def test_save_blank_path_400(self, monkeypatch, tmp_path):
        sm = _load_sm(monkeypatch, tmp_path)
        worker = self._mock_worker(sm, None)
        with patch.object(sm, "_PlaywrightWorker", return_value=worker):
            _, opened = _make_request(sm, "POST", "/api/playwright/sessions", {"target": "playwright-webkit"}
            )
        code, _ = _make_request(sm, "POST", f"/api/playwright/sessions/{opened['id']}/save", {"path": "  "}
        )
        assert code == 400

    def test_save_strips_path(self, monkeypatch, tmp_path):
        sm = _load_sm(monkeypatch, tmp_path)
        worker = self._mock_worker(sm, None)
        with patch.object(sm, "_PlaywrightWorker", return_value=worker):
            _, opened = _make_request(sm, "POST", "/api/playwright/sessions", {"target": "playwright-firefox"}
            )
        code, data = _make_request(sm, "POST", f"/api/playwright/sessions/{opened['id']}/save", {"path": "  s.json  "}
        )
        assert code == 200
        assert data["path"] == str(tmp_path / "s.json")
        worker.save.assert_called_once_with(str(tmp_path / "s.json"))

    def test_open_backend_failure_502(self, monkeypatch, tmp_path):
        sm = _load_sm(monkeypatch, tmp_path)
        worker = MagicMock()
        worker.error = RuntimeError("hub down")
        with patch.object(sm, "_PlaywrightWorker", return_value=worker):
            code, data = _make_request(sm, "POST",
                "/api/playwright/sessions",
                {"target": "playwright-chromium"},
            )
            assert code == 502
            assert data["error"] == "hub down"

    def test_close_runs_on_owner_thread(self, monkeypatch, tmp_path):
        """A worker created on one thread must serve close from another."""
        sm = _load_sm(monkeypatch, tmp_path)
        opened_threads = []
        closed_threads = []
        real_open = sm._PlaywrightBackend.open

        def spy_open(*args, **kwargs):
            opened_threads.append(__import__("threading").current_thread())
            return real_open(*args, **kwargs)

        def spy_close(session):
            closed_threads.append(__import__("threading").current_thread())

        with patch.object(sm._PlaywrightBackend, "open", side_effect=spy_open):
            with patch.object(sm._PlaywrightBackend, "close", side_effect=spy_close):
                with patch.object(
                    sm._PlaywrightBackend, "save", return_value={"cookies": []}
                ):
                    worker = sm._PlaywrightWorker("playwright-chromium")
                    assert worker.error is None
                    other = __import__("threading").Thread(
                        target=worker.close
                    )
                    other.start()
                    other.join()
        assert len(opened_threads) == 1
        assert closed_threads == opened_threads

    def test_save(self, monkeypatch, tmp_path):
        sm = _load_sm(monkeypatch, tmp_path)
        worker = self._mock_worker(sm, None)
        with patch.object(sm, "_PlaywrightWorker", return_value=worker):
            _, opened = _make_request(sm, "POST", "/api/playwright/sessions", {"target": "playwright-firefox"}
            )
        code, data = _make_request(sm, "POST", f"/api/playwright/sessions/{opened['id']}/save", {"path": "s.json"}
        )
        assert code == 200
        assert data["path"] == str(tmp_path / "s.json")
        assert data["state"] == {"cookies": []}
        worker.save.assert_called_once_with(str(tmp_path / "s.json"))

    def test_open_connect_uses_open_timeout(self, monkeypatch, tmp_path):
        import sys
        import types
        from unittest.mock import MagicMock

        sm = _load_sm(monkeypatch, tmp_path, env={"PLAYWRIGHT_OPEN_TIMEOUT": "7"})
        browser_type = MagicMock()
        pw = MagicMock()
        pw.chromium = browser_type
        fake_factory = MagicMock()
        fake_factory.return_value.start.return_value = pw
        fake_api = types.ModuleType("playwright.sync_api")
        fake_api.sync_playwright = fake_factory
        monkeypatch.setitem(sys.modules, "playwright.sync_api", fake_api)
        sm._PlaywrightBackend.open("playwright-chromium")
        _, kwargs = browser_type.connect.call_args
        assert kwargs["timeout"] == 7000

    def test_open_closes_browser_on_context_failure(self, monkeypatch, tmp_path):
        import sys
        import types
        from unittest.mock import MagicMock

        sm = _load_sm(monkeypatch, tmp_path)
        browser = MagicMock()
        browser.new_context.side_effect = RuntimeError("bad state")
        browser_type = MagicMock()
        browser_type.connect.return_value = browser
        pw = MagicMock()
        pw.chromium = browser_type
        fake_factory = MagicMock()
        fake_factory.return_value.start.return_value = pw
        fake_api = types.ModuleType("playwright.sync_api")
        fake_api.sync_playwright = fake_factory
        monkeypatch.setitem(sys.modules, "playwright.sync_api", fake_api)
        try:
            sm._PlaywrightBackend.open("playwright-chromium")
        except RuntimeError:
            pass
        else:
            raise AssertionError("expected RuntimeError")
        browser.close.assert_called_once_with()
        pw.stop.assert_called_once_with()

    def test_open_strips_inputs(self, monkeypatch, tmp_path):
        sm = _load_sm(monkeypatch, tmp_path)
        worker = self._mock_worker(sm, None)
        with patch.object(sm, "_PlaywrightWorker", return_value=worker) as m:
            code, data = _make_request(sm, "POST",
                "/api/playwright/sessions",
                {"target": "playwright-chromium", "node": "  chromium  ", "url": "  https://example.com  "},
            )
            assert code == 200
            m.assert_called_once_with(
                "playwright-chromium",
                node="chromium",
                url="https://example.com",
                storage_state=None,
            )
            assert data["url"] == "https://example.com"

    def test_save_escape_rejected(self, monkeypatch, tmp_path):
        sm = _load_sm(monkeypatch, tmp_path)
        session = self._mock_backend(sm, "playwright-firefox")
        with patch.object(sm._PlaywrightBackend, "open", return_value=session):
            _, opened = _make_request(sm, "POST", "/api/playwright/sessions", {"target": "playwright-firefox"}
            )
        code, data = _make_request(
            sm, "POST", f"/api/playwright/sessions/{opened['id']}/save", {"path": "/etc/evil.json"}
        )
        assert code == 400
        assert "escapes state dir" in data["error"]

    def test_save_dict_path_rejected(self, monkeypatch, tmp_path):
        sm = _load_sm(monkeypatch, tmp_path)
        worker = self._mock_worker(sm, None)
        with patch.object(sm, "_PlaywrightWorker", return_value=worker):
            _, opened = _make_request(sm, "POST", "/api/playwright/sessions", {"target": "playwright-firefox"}
            )
        code, data = _make_request(
            sm, "POST", f"/api/playwright/sessions/{opened['id']}/save", {"path": {"a": 1}}
        )
        assert code == 400

    def test_call_timeout(self, monkeypatch, tmp_path):
        """A hung worker reply surfaces TimeoutError instead of blocking."""
        import queue

        sm = _load_sm(monkeypatch, tmp_path, env={"PLAYWRIGHT_WORKER_TIMEOUT": "1"})
        session = self._mock_backend(sm)
        with patch.object(sm._PlaywrightBackend, "open", return_value=session):
            worker = sm._PlaywrightWorker("playwright-chromium")
        assert worker.error is None
        with patch.object(
            sm._PlaywrightBackend, "close", side_effect=lambda s: __import__("time").sleep(5)
        ):
            try:
                worker.close()
            except TimeoutError as exc:
                assert "timed out" in str(exc)
            else:
                raise AssertionError("expected TimeoutError")
            finally:
                worker._requests.put((None, (), None))
                worker.join(timeout=10)

    def test_save_unknown_session(self, monkeypatch, tmp_path):
        sm = _load_sm(monkeypatch, tmp_path)
        code, data = _make_request(sm, "POST", "/api/playwright/sessions/xxx/save", {"path": "s.json"}
        )
        assert code == 404

    def test_save_requires_path(self, monkeypatch, tmp_path):
        sm = _load_sm(monkeypatch, tmp_path)
        worker = self._mock_worker(sm, None)
        with patch.object(sm, "_PlaywrightWorker", return_value=worker):
            _, opened = _make_request(sm, "POST", "/api/playwright/sessions", {"target": "playwright-webkit"}
            )
        code, _ = _make_request(sm, "POST", f"/api/playwright/sessions/{opened['id']}/save", {}
        )
        assert code == 400

    def test_close_unknown_session(self, monkeypatch, tmp_path):
        sm = _load_sm(monkeypatch, tmp_path)
        code, data = _make_request(sm, "DELETE", "/api/playwright/sessions/xxx"
        )
        assert code == 404

    def test_abandoned_late_success_cleaned_up(self, monkeypatch, tmp_path):
        """Open timeout marks the worker abandoned; a late success must be closed."""
        import threading

        # Wait is 2*OPEN+10: OPEN=1 gives 12s; slow_open must exceed it.
        sm = _load_sm(monkeypatch, tmp_path, env={"PLAYWRIGHT_OPEN_TIMEOUT": "1"})
        release = threading.Event()
        session = self._mock_backend(sm)

        def slow_open(*args, **kwargs):
            release.wait(timeout=30)
            return session

        closed = []
        with patch.object(sm._PlaywrightBackend, "open", side_effect=slow_open):
            with patch.object(
                sm._PlaywrightBackend, "close", side_effect=lambda s: closed.append(s)
            ):
                worker = sm._PlaywrightWorker("playwright-chromium")
                assert isinstance(worker.error, TimeoutError)
                assert "after 12s" in str(worker.error)
                assert worker.abandoned is True
                release.set()
                worker.join(timeout=10)
        assert closed == [session]
        assert worker.session is None

    def test_close_failure_retryable(self, monkeypatch, tmp_path):
        sm = _load_sm(monkeypatch, tmp_path)
        session = self._mock_backend(sm, "playwright-chromium")
        with patch.object(sm._PlaywrightBackend, "open", return_value=session):
            code, opened = _make_request(
                sm, "POST", "/api/playwright/sessions", {"target": "playwright-chromium"}
            )
            assert code == 200
        with patch.object(
            sm._PlaywrightBackend, "close", side_effect=RuntimeError("hub down")
        ):
            code, data = _make_request(sm, "DELETE", f"/api/playwright/sessions/{opened['id']}")
            assert code == 502
            assert data["retryable"] is True
        # Entry kept: retry succeeds.
        with patch.object(sm._PlaywrightBackend, "close", return_value=None):
            code, _ = _make_request(sm, "DELETE", f"/api/playwright/sessions/{opened['id']}")
            assert code == 200
        code, data = _make_request(sm, "GET", "/api/playwright/sessions")
        assert data == {"sessions": []}

    def test_body_too_large_413(self, monkeypatch, tmp_path):
        sm = _load_sm(monkeypatch, tmp_path)
        handler = sm._Handler.__new__(sm._Handler)
        handler.path = "/api/playwright/sessions"
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
        handler.path = "/api/playwright/sessions"
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
        handler.path = "/api/playwright/sessions"
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
        worker = self._mock_worker(sm, None)
        worker.close.side_effect = RuntimeError("hub down")
        sm._pw_sessions["evil\ninjected"] = {"target": "playwright-chromium", "worker": worker}
        with patch.object(
            sm._Handler, "_route",
            return_value=("DELETE", "playwright", ["evil\ninjected"]),
        ):
            code, data = _make_request(sm, "DELETE", "/api/playwright/sessions/evil")
        assert code == 502
        assert data["retryable"] is True
        out = capsys.readouterr().out
        assert "evil\\ninjected" in out
        assert out.count("\n") == 1

    def test_invalid_int_env_falls_back(self, monkeypatch, tmp_path):
        sm = _load_sm(
            monkeypatch,
            tmp_path,
            env={"PLAYWRIGHT_OPEN_TIMEOUT": "bogus", "PLAYWRIGHT_WORKER_TIMEOUT": "bogus"},
        )
        assert sm.OPEN_TIMEOUT == 60
        assert sm.WORKER_TIMEOUT == 120

    def test_non_positive_int_env_falls_back(self, monkeypatch, tmp_path):
        sm = _load_sm(
            monkeypatch,
            tmp_path,
            env={"PLAYWRIGHT_OPEN_TIMEOUT": "-5", "PLAYWRIGHT_WORKER_TIMEOUT": "0"},
        )
        assert sm.OPEN_TIMEOUT == 60
        assert sm.WORKER_TIMEOUT == 120
