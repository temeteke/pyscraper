"""Unit tests for servers/playwright_session_manager.py.

The Playwright session manager opens/closes browser sessions for the
gateway UI via the Hub relay, with storage_state load/save
(FastAPI + TestClient).
"""

import importlib.util
import json
from pathlib import Path
from unittest.mock import MagicMock, patch

from fastapi.testclient import TestClient

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


def _client(sm):
    return TestClient(sm.app)


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
        r = _client(sm).get("/api/playwright/state-files")
        assert r.status_code == 200
        assert r.json() == {"state_files": ["s.json"]}


class TestPlaywrightSessions:
    def _mock_backend(self, sm, browser="playwright-chromium"):
        session = {
            "browser": browser,
            "node": None,
            "context": MagicMock(),
            "playwright_browser": MagicMock(),
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
        client = _client(sm)
        worker = self._mock_worker(sm, None)
        with patch.object(sm, "_PlaywrightWorker", return_value=worker) as m:
            r = client.post(
                "/api/playwright/sessions",
                json={
                    "browser": "playwright-chromium",
                    "node": "chromium",
                    "url": "https://example.com",
                },
            )
            assert r.status_code == 200
            m.assert_called_once_with(
                "playwright-chromium",
                node="chromium",
                url="https://example.com",
                storage_state=None,
            )
            sid = r.json()["id"]
        r = client.get("/api/playwright/sessions")
        assert r.status_code == 200
        assert r.json() == {
            "sessions": [
                {
                    "id": sid,
                    "browser": "playwright-chromium",
                    "node": "chromium",
                }
            ]
        }
        r = client.delete(f"/api/playwright/sessions/{sid}")
        assert r.status_code == 200
        worker.close.assert_called_once_with()

    def test_open_unknown_browser_422(self, monkeypatch, tmp_path):
        sm = _load_sm(monkeypatch, tmp_path)
        r = _client(sm).post("/api/playwright/sessions", json={"browser": "nope"})
        assert r.status_code == 422

    def test_open_unknown_field_422(self, monkeypatch, tmp_path):
        sm = _load_sm(monkeypatch, tmp_path)
        r = _client(sm).post(
            "/api/playwright/sessions",
            json={"browser": "playwright-chromium", "bogus": 1},
        )
        assert r.status_code == 422

    def test_open_escape_storage_state_422(self, monkeypatch, tmp_path):
        sm = _load_sm(monkeypatch, tmp_path)
        r = _client(sm).post(
            "/api/playwright/sessions",
            json={"browser": "playwright-chromium", "storage_state": "/etc/evil.json"},
        )
        assert r.status_code == 422
        assert "escapes state dir" in str(r.json()["detail"])

    def test_open_padded_escape_storage_state_422(self, monkeypatch, tmp_path):
        sm = _load_sm(monkeypatch, tmp_path)
        r = _client(sm).post(
            "/api/playwright/sessions",
            json={"browser": "playwright-chromium", "storage_state": "  ../outside.json  "},
        )
        assert r.status_code == 422
        assert "escapes state dir" in str(r.json()["detail"])

    def test_open_non_dict_json_422(self, monkeypatch, tmp_path):
        sm = _load_sm(monkeypatch, tmp_path)
        client = _client(sm)
        for raw in (b"[1,2]", b'"x"'):
            r = client.post(
                "/api/playwright/sessions",
                content=raw,
                headers={"Content-Type": "application/json"},
            )
            assert r.status_code == 422
            assert "detail" in r.json()

    def test_open_empty_dict_storage_state_422(self, monkeypatch, tmp_path):
        sm = _load_sm(monkeypatch, tmp_path)
        r = _client(sm).post(
            "/api/playwright/sessions",
            json={"browser": "playwright-chromium", "storage_state": {}},
        )
        assert r.status_code == 422

    def test_open_port_out_of_range_falls_back(self, monkeypatch, tmp_path):
        sm = _load_sm(monkeypatch, tmp_path, env={"PLAYWRIGHT_SESSION_MANAGER_PORT": "99999"})
        assert sm.PORT == 8081

    def test_open_non_string_storage_state_422(self, monkeypatch, tmp_path):
        sm = _load_sm(monkeypatch, tmp_path)
        for bad in (123, ["a.json"]):
            r = _client(sm).post(
                "/api/playwright/sessions",
                json={"browser": "playwright-chromium", "storage_state": bad},
            )
            assert r.status_code == 422

    def test_open_empty_storage_state_422(self, monkeypatch, tmp_path):
        sm = _load_sm(monkeypatch, tmp_path)
        r = _client(sm).post(
            "/api/playwright/sessions",
            json={"browser": "playwright-chromium", "storage_state": ""},
        )
        assert r.status_code == 422

    def test_open_non_string_node_422(self, monkeypatch, tmp_path):
        sm = _load_sm(monkeypatch, tmp_path)
        r = _client(sm).post(
            "/api/playwright/sessions",
            json={"browser": "playwright-chromium", "node": ["chromium"]},
        )
        assert r.status_code == 422
        assert "node" in str(r.json()["detail"])

    def test_open_non_string_url_422(self, monkeypatch, tmp_path):
        sm = _load_sm(monkeypatch, tmp_path)
        r = _client(sm).post(
            "/api/playwright/sessions",
            json={"browser": "playwright-chromium", "url": {"u": 1}},
        )
        assert r.status_code == 422
        assert "url" in str(r.json()["detail"])

    def test_open_blank_inputs_422(self, monkeypatch, tmp_path):
        sm = _load_sm(monkeypatch, tmp_path)
        for payload in (
            {"browser": "playwright-chromium", "node": "  "},
            {"browser": "playwright-chromium", "url": "  "},
            {"browser": "playwright-chromium", "storage_state": "  "},
        ):
            r = _client(sm).post("/api/playwright/sessions", json=payload)
            assert r.status_code == 422

    def test_save_blank_path_422(self, monkeypatch, tmp_path):
        sm = _load_sm(monkeypatch, tmp_path)
        client = _client(sm)
        worker = self._mock_worker(sm, None)
        with patch.object(sm, "_PlaywrightWorker", return_value=worker):
            r = client.post("/api/playwright/sessions", json={"browser": "playwright-webkit"})
            sid = r.json()["id"]
        r = client.post(f"/api/playwright/sessions/{sid}/save", json={"path": "  "})
        assert r.status_code == 422

    def test_save_strips_path(self, monkeypatch, tmp_path):
        sm = _load_sm(monkeypatch, tmp_path)
        client = _client(sm)
        worker = self._mock_worker(sm, None)
        with patch.object(sm, "_PlaywrightWorker", return_value=worker):
            r = client.post("/api/playwright/sessions", json={"browser": "playwright-firefox"})
            sid = r.json()["id"]
        r = client.post(f"/api/playwright/sessions/{sid}/save", json={"path": "  s.json  "})
        assert r.status_code == 200
        assert r.json()["path"] == str(tmp_path / "s.json")
        worker.save.assert_called_once_with(str(tmp_path / "s.json"))

    def test_open_backend_failure_502(self, monkeypatch, tmp_path, capsys):
        sm = _load_sm(monkeypatch, tmp_path)
        worker = MagicMock()
        worker.error = RuntimeError("hub down")
        with patch.object(sm, "_PlaywrightWorker", return_value=worker):
            r = _client(sm).post(
                "/api/playwright/sessions",
                json={"browser": "playwright-chromium"},
            )
            assert r.status_code == 502
            # Trusted clients on a closed network: the raw error is
            # returned (no fixed-message substitution).
            assert "hub down" in str(r.json()["detail"])
        assert "hub down" in capsys.readouterr().err

    def test_open_constructor_failure_502(self, monkeypatch, tmp_path, capsys):
        sm = _load_sm(monkeypatch, tmp_path)
        with patch.object(sm, "_PlaywrightWorker", side_effect=RuntimeError("hub down")):
            r = _client(sm).post(
                "/api/playwright/sessions",
                json={"browser": "playwright-chromium"},
            )
            assert r.status_code == 502
            # Same raw error on the constructor-raise path.
            assert "hub down" in str(r.json()["detail"])
        assert "hub down" in capsys.readouterr().err

    def test_close_runs_on_owner_thread(self, monkeypatch, tmp_path):
        """A worker created on one thread must serve close from another."""
        sm = _load_sm(monkeypatch, tmp_path)
        opened_threads = []
        closed_threads = []
        fake_session = {
            "browser": "playwright-chromium",
            "node": None,
            "playwright_browser": None,
            "context": None,
            "page": None,
            "pw": None,
        }

        def fake_open(*args, **kwargs):
            opened_threads.append(__import__("threading").current_thread())
            return fake_session

        def spy_close(session):
            closed_threads.append(__import__("threading").current_thread())

        with patch.object(sm._PlaywrightBackend, "open", side_effect=fake_open):
            with patch.object(sm._PlaywrightBackend, "close", side_effect=spy_close):
                with patch.object(sm._PlaywrightBackend, "save", return_value={"cookies": []}):
                    worker = sm._PlaywrightWorker("playwright-chromium")
                    assert worker.error is None
                    other = __import__("threading").Thread(target=worker.close)
                    other.start()
                    other.join()
        assert len(opened_threads) == 1
        assert closed_threads == opened_threads

    def test_save(self, monkeypatch, tmp_path):
        sm = _load_sm(monkeypatch, tmp_path)
        client = _client(sm)
        worker = self._mock_worker(sm, None)
        with patch.object(sm, "_PlaywrightWorker", return_value=worker):
            r = client.post("/api/playwright/sessions", json={"browser": "playwright-firefox"})
            sid = r.json()["id"]
        r = client.post(f"/api/playwright/sessions/{sid}/save", json={"path": "s.json"})
        assert r.status_code == 200
        assert r.json()["path"] == str(tmp_path / "s.json")
        assert r.json()["state"] == {"cookies": []}
        worker.save.assert_called_once_with(str(tmp_path / "s.json"))

    def test_save_failure_502(self, monkeypatch, tmp_path, capsys):
        sm = _load_sm(monkeypatch, tmp_path)
        client = _client(sm)
        worker = self._mock_worker(sm, None)
        worker.save.side_effect = RuntimeError("hub internal down")
        with patch.object(sm, "_PlaywrightWorker", return_value=worker):
            r = client.post("/api/playwright/sessions", json={"browser": "playwright-firefox"})
            sid = r.json()["id"]
        r = client.post(f"/api/playwright/sessions/{sid}/save", json={"path": "s.json"})
        assert r.status_code == 502
        assert "hub internal down" in str(r.json()["detail"])
        assert "hub internal down" in capsys.readouterr().err

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
        client = _client(sm)
        worker = self._mock_worker(sm, None)
        with patch.object(sm, "_PlaywrightWorker", return_value=worker) as m:
            r = client.post(
                "/api/playwright/sessions",
                json={
                    "browser": "playwright-chromium",
                    "node": "  chromium  ",
                    "url": "  https://example.com  ",
                },
            )
            assert r.status_code == 200
            m.assert_called_once_with(
                "playwright-chromium",
                node="chromium",
                url="https://example.com",
                storage_state=None,
            )
            assert r.json()["url"] == "https://example.com"

    def test_save_escape_rejected_422(self, monkeypatch, tmp_path):
        sm = _load_sm(monkeypatch, tmp_path)
        client = _client(sm)
        session = self._mock_backend(sm, "playwright-firefox")
        with patch.object(sm._PlaywrightBackend, "open", return_value=session):
            r = client.post("/api/playwright/sessions", json={"browser": "playwright-firefox"})
            sid = r.json()["id"]
        r = client.post(f"/api/playwright/sessions/{sid}/save", json={"path": "/etc/evil.json"})
        assert r.status_code == 422
        assert "escapes state dir" in str(r.json()["detail"])

    def test_save_dict_path_rejected_422(self, monkeypatch, tmp_path):
        sm = _load_sm(monkeypatch, tmp_path)
        client = _client(sm)
        worker = self._mock_worker(sm, None)
        with patch.object(sm, "_PlaywrightWorker", return_value=worker):
            r = client.post("/api/playwright/sessions", json={"browser": "playwright-firefox"})
            sid = r.json()["id"]
        r = client.post(f"/api/playwright/sessions/{sid}/save", json={"path": {"a": 1}})
        assert r.status_code == 422

    def test_call_timeout(self, monkeypatch, tmp_path):
        """A hung worker reply surfaces TimeoutError instead of blocking."""
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
        r = _client(sm).post("/api/playwright/sessions/xxx/save", json={"path": "s.json"})
        assert r.status_code == 404
        assert "detail" in r.json()

    def test_save_requires_path_422(self, monkeypatch, tmp_path):
        sm = _load_sm(monkeypatch, tmp_path)
        client = _client(sm)
        worker = self._mock_worker(sm, None)
        with patch.object(sm, "_PlaywrightWorker", return_value=worker):
            r = client.post("/api/playwright/sessions", json={"browser": "playwright-webkit"})
            sid = r.json()["id"]
        r = client.post(f"/api/playwright/sessions/{sid}/save", json={})
        assert r.status_code == 422
        assert "detail" in r.json()

    def test_close_unknown_session(self, monkeypatch, tmp_path):
        sm = _load_sm(monkeypatch, tmp_path)
        r = _client(sm).delete("/api/playwright/sessions/xxx")
        assert r.status_code == 404
        assert "detail" in r.json()

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
        client = _client(sm)
        session = self._mock_backend(sm, "playwright-chromium")
        with patch.object(sm._PlaywrightBackend, "open", return_value=session):
            r = client.post("/api/playwright/sessions", json={"browser": "playwright-chromium"})
            assert r.status_code == 200
            sid = r.json()["id"]
        with patch.object(sm._PlaywrightBackend, "close", side_effect=RuntimeError("hub down")):
            r = client.delete(f"/api/playwright/sessions/{sid}")
            assert r.status_code == 502
            assert r.json()["retryable"] is True
            assert "hub down" in str(r.json()["detail"])
        # Entry kept: retry succeeds.
        with patch.object(sm._PlaywrightBackend, "close", return_value=None):
            r = client.delete(f"/api/playwright/sessions/{sid}")
            assert r.status_code == 200
        r = client.get("/api/playwright/sessions")
        assert r.json() == {"sessions": []}

    def test_known_path_wrong_method_405(self, monkeypatch, tmp_path):
        sm = _load_sm(monkeypatch, tmp_path)
        r = _client(sm).post("/api/playwright/state-files", json={})
        assert r.status_code == 405
        assert "detail" in r.json()

    def test_unknown_path_404(self, monkeypatch, tmp_path):
        sm = _load_sm(monkeypatch, tmp_path)
        r = _client(sm).post("/api/nope", json={})
        assert r.status_code == 404
        assert "detail" in r.json()

    def test_trailing_slash_state_files(self, monkeypatch, tmp_path):
        # FastAPI redirects trailing-slash variants (307) to the
        # canonical path. The gateway nginx alias absorbs this anyway.
        from fastapi.testclient import TestClient as RawClient

        sm = _load_sm(monkeypatch, tmp_path)
        r = RawClient(sm.app, follow_redirects=False).get("/api/playwright/state-files/")
        assert r.status_code == 307
        assert r.headers["location"].endswith("/api/playwright/state-files")

    def test_close_failure_log_escapes_newline(self, monkeypatch, tmp_path, capsys):
        # Starlette strips raw newlines from path params, so call the
        # endpoint directly with an attacker-controlled id.
        sm = _load_sm(monkeypatch, tmp_path)
        worker = self._mock_worker(sm, None)
        worker.close.side_effect = RuntimeError("hub down")
        sm._pw_sessions["evil\ninjected"] = {"browser": "playwright-chromium", "worker": worker}
        resp = sm.close_session("evil\ninjected")
        assert resp.status_code == 502
        out = capsys.readouterr().err
        assert "evil\\ninjected" in out
        assert out.count("\n") == 1

    def test_close_malformed_entry_500(self, monkeypatch, tmp_path, capsys):
        # An entry missing the worker is a bug, not a worker failure:
        # 500 without retryable (never retryable 502).
        sm = _load_sm(monkeypatch, tmp_path)
        sm._pw_sessions["broken"] = {"browser": "playwright-chromium"}
        resp = sm.close_session("broken")
        assert resp.status_code == 500
        assert "retryable" not in json.loads(resp.body)
        assert "malformed entry 'broken'" in capsys.readouterr().err

    def test_close_non_worker_entry_500(self, monkeypatch, tmp_path):
        # A truthy non-worker must not slip through to AttributeError→502.
        sm = _load_sm(monkeypatch, tmp_path)
        sm._pw_sessions["fake"] = {"browser": "playwright-chromium", "worker": "oops"}
        resp = sm.close_session("fake")
        assert resp.status_code == 500
        assert "retryable" not in json.loads(resp.body)

    def test_close_non_dict_entry_500(self, monkeypatch, tmp_path):
        sm = _load_sm(monkeypatch, tmp_path)
        sm._pw_sessions["weird"] = ["oops"]
        assert sm.close_session("weird").status_code == 500
        assert sm.save_session("weird", sm.SaveRequest(path="s.json")).status_code == 500

    def test_save_malformed_entry_500(self, monkeypatch, tmp_path, capsys):
        sm = _load_sm(monkeypatch, tmp_path)
        sm._pw_sessions["broken"] = {"browser": "playwright-chromium"}
        resp = sm.save_session("broken", sm.SaveRequest(path="s.json"))
        assert resp.status_code == 500
        assert "retryable" not in json.loads(resp.body)
        assert "malformed entry 'broken'" in capsys.readouterr().err

    def test_list_tolerates_malformed_entry(self, monkeypatch, tmp_path):
        # One broken entry must not take down the whole listing.
        sm = _load_sm(monkeypatch, tmp_path)
        client = _client(sm)
        worker = self._mock_worker(sm, None)
        with patch.object(sm, "_PlaywrightWorker", return_value=worker):
            r = client.post("/api/playwright/sessions", json={"browser": "playwright-chromium"})
            assert r.status_code == 200
            sid = r.json()["id"]
        sm._pw_sessions["broken"] = {"browser": "playwright-chromium"}
        sm._pw_sessions["non-dict"] = ["oops"]
        r = client.get("/api/playwright/sessions")
        assert r.status_code == 200
        ids = {s["id"] for s in r.json()["sessions"]}
        assert {sid, "broken", "non-dict"} <= ids

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


class TestBrowserField:
    def _worker(self):
        worker = MagicMock()
        worker.error = None
        return worker

    def test_browser_field_is_canonical(self, monkeypatch, tmp_path):
        sm = _load_sm(monkeypatch, tmp_path)
        with patch.object(sm, "_PlaywrightWorker", return_value=self._worker()) as m:
            r = _client(sm).post("/api/playwright/sessions", json={"browser": "playwright-webkit"})
        assert r.status_code == 200
        m.assert_called_once_with("playwright-webkit", node=None, url=None, storage_state=None)
        body = r.json()
        assert body["browser"] == "playwright-webkit"
        assert "target" not in body

    def test_target_field_is_rejected_422(self, monkeypatch, tmp_path):
        # ``target`` was renamed to ``browser`` in v2.0.0 and is no longer
        # accepted (no deprecation alias).
        sm = _load_sm(monkeypatch, tmp_path)
        r = _client(sm).post("/api/playwright/sessions", json={"target": "playwright-chromium"})
        assert r.status_code == 422


class TestOpenAPI:
    def test_openapi_and_docs(self, monkeypatch, tmp_path):
        sm = _load_sm(monkeypatch, tmp_path)
        client = _client(sm)
        assert client.get("/openapi.json").status_code == 200
        assert client.get("/docs").status_code == 200
