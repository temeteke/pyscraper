"""Unit tests for servers/playwright_session_manager.py.

The Playwright session manager opens/closes browser sessions for the
console UI via the Hub relay, with storage_state load/save
(FastAPI + TestClient).
"""

import importlib.util
import json
import os
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest
from fastapi.testclient import TestClient

SM_PATH = Path(__file__).resolve().parent.parent / "servers" / "playwright_session_manager.py"


def _load_sm(monkeypatch, tmp_path, env=None):
    for key in (
        "PLAYWRIGHT_SESSION_MANAGER_PORT",
        "PLAYWRIGHT_HUB_WS",
        "SESSION_STATE_DIR",
        "PLAYWRIGHT_OPEN_TIMEOUT",
        "PLAYWRIGHT_WORKER_TIMEOUT",
        "PLAYWRIGHT_SCREEN_WIDTH",
        "PLAYWRIGHT_SCREEN_HEIGHT",
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


class TestStateResources:
    """The id-based state resource API (v2.1.0)."""

    def _mock_worker(self):
        worker = MagicMock()
        worker.error = None
        worker.save.return_value = {"cookies": []}
        return worker

    def _open(self, sm, worker, browser="playwright-firefox"):
        with patch.object(sm, "_PlaywrightWorker", return_value=worker):
            r = _client(sm).post("/api/playwright/sessions", json={"browser": browser})
        assert r.status_code == 200
        return r.json()["id"]

    def test_list_states_endpoint(self, monkeypatch, tmp_path):
        (tmp_path / "a.json").write_text("{}")
        (tmp_path / "b.json").write_text("{}")
        (tmp_path / "not-json.txt").write_text("{}")
        (tmp_path / "Bad.json").write_text("{}")
        (tmp_path / "sub").mkdir()
        (tmp_path / "sub" / "c.json").write_text("{}")
        sm = _load_sm(monkeypatch, tmp_path)
        r = _client(sm).get("/api/playwright/states")
        assert r.status_code == 200
        assert r.json() == {"states": [{"id": "a"}, {"id": "b"}]}

    def test_list_states_empty(self, monkeypatch, tmp_path):
        sm = _load_sm(monkeypatch, tmp_path)
        r = _client(sm).get("/api/playwright/states")
        assert r.status_code == 200
        assert r.json() == {"states": []}

    def test_list_states_excludes_overlong_stem(self, monkeypatch, tmp_path):
        (tmp_path / ("a" * 64 + ".json")).write_text("{}")
        (tmp_path / ("b" * 63 + ".json")).write_text("{}")
        sm = _load_sm(monkeypatch, tmp_path)
        r = _client(sm).get("/api/playwright/states")
        assert r.json() == {"states": [{"id": "b" * 63}]}

    def test_resolve_state_id_rejects_whitespace(self, monkeypatch, tmp_path):
        sm = _load_sm(monkeypatch, tmp_path)
        for bad in [" a", "a ", "a\n", "a\t", "A", "a_b", "a.b", "a" * 64]:
            with pytest.raises(ValueError):
                sm._resolve_state_id(bad)

    def test_relative_state_dir_round_trip(self, monkeypatch, tmp_path):
        # A relative SESSION_STATE_DIR must resolve to one absolute file,
        # not STATE_DIR/states/<id>.json (double application).
        monkeypatch.chdir(tmp_path)
        sm = _load_sm(monkeypatch, tmp_path, env={"SESSION_STATE_DIR": "states"})
        assert sm.STATE_DIR == tmp_path / "states"
        (tmp_path / "states").mkdir()
        client = _client(sm)
        worker = self._mock_worker()
        sid = self._open(sm, worker)
        r = client.put("/api/playwright/states/rel", json={"session_id": sid})
        assert r.status_code == 200
        assert (tmp_path / "states" / "rel.json").exists()
        assert not (tmp_path / "states" / "states").exists()
        assert client.get("/api/playwright/states").json() == {"states": [{"id": "rel"}]}

    def test_backend_save_returns_dict(self, monkeypatch, tmp_path):
        sm = _load_sm(monkeypatch, tmp_path)
        context = MagicMock()
        context.storage_state.return_value = {"cookies": [{"name": "x"}]}
        assert sm._PlaywrightBackend.save({"context": context}) == {"cookies": [{"name": "x"}]}
        context.storage_state.assert_called_once_with()

    def test_write_state_id_preserves_existing_mode(self, monkeypatch, tmp_path):
        target = tmp_path / "m.json"
        target.write_text("{}")
        os.chmod(target, 0o640)
        sm = _load_sm(monkeypatch, tmp_path)
        sm._write_state_id(target, {"cookies": []})
        assert json.loads(target.read_text()) == {"cookies": []}
        assert (target.stat().st_mode & 0o777) == 0o640

    def test_write_state_id_new_file_uses_umask(self, monkeypatch, tmp_path):
        sm = _load_sm(monkeypatch, tmp_path)
        path = tmp_path / "fresh.json"
        current = os.umask(0o022)
        os.umask(current)
        sm._write_state_id(path, {"cookies": []})
        assert (path.stat().st_mode & 0o777) == (0o666 & ~current)

    def test_read_state_id_requires_json_object(self, monkeypatch, tmp_path):
        sm = _load_sm(monkeypatch, tmp_path)
        for payload in ("null", '"x"', "[1, 2]"):
            target = tmp_path / "value.json"
            target.write_text(payload)
            with pytest.raises(ValueError):
                sm._read_state_id(target)

    def test_read_state_id_rejects_non_regular(self, monkeypatch, tmp_path):
        sm = _load_sm(monkeypatch, tmp_path)
        fifo = tmp_path / "fifo.json"
        os.mkfifo(fifo)
        with pytest.raises(ValueError):
            sm._read_state_id(fifo)

    def test_delete_state_id_rejects_non_regular(self, monkeypatch, tmp_path):
        (tmp_path / "target.json").write_text("{}")
        (tmp_path / "link.json").symlink_to(tmp_path / "target.json")
        sm = _load_sm(monkeypatch, tmp_path)
        with pytest.raises(ValueError):
            sm._delete_state_id(tmp_path / "link.json")
        assert (tmp_path / "link.json").is_symlink()
        assert (tmp_path / "target.json").exists()

    def test_external_symlink_excluded_and_rejected(self, monkeypatch, tmp_path):
        outside = tmp_path.parent / f"{tmp_path.name}-outside.json"
        outside.write_text("{}")
        (tmp_path / "evil.json").symlink_to(outside)
        sm = _load_sm(monkeypatch, tmp_path)
        client = _client(sm)
        assert client.get("/api/playwright/states").json() == {"states": []}
        assert client.delete("/api/playwright/states/evil").status_code == 422
        assert (
            client.put("/api/playwright/states/evil", json={"session_id": "x"}).status_code == 422
        )
        r = client.post(
            "/api/playwright/sessions",
            json={"browser": "playwright-firefox", "state_id": "evil"},
        )
        assert r.status_code == 422

    def test_internal_symlink_excluded_and_rejected(self, monkeypatch, tmp_path):
        real = tmp_path / "real.json"
        real.write_text("{}")
        (tmp_path / "link.json").symlink_to(real)
        sm = _load_sm(monkeypatch, tmp_path)
        client = _client(sm)
        ids = {s["id"] for s in client.get("/api/playwright/states").json()["states"]}
        assert ids == {"real"}
        assert client.delete("/api/playwright/states/link").status_code == 422
        r = client.post(
            "/api/playwright/sessions",
            json={"browser": "playwright-firefox", "state_id": "link"},
        )
        assert r.status_code == 422
        # The link is left untouched, and so is its target.
        assert (tmp_path / "link.json").is_symlink()
        assert real.exists()

    def test_dangling_symlink_excluded_and_rejected(self, monkeypatch, tmp_path):
        (tmp_path / "dangling.json").symlink_to(tmp_path / "missing.json")
        sm = _load_sm(monkeypatch, tmp_path)
        client = _client(sm)
        assert client.get("/api/playwright/states").json() == {"states": []}
        r = client.post(
            "/api/playwright/sessions",
            json={"browser": "playwright-firefox", "state_id": "dangling"},
        )
        assert r.status_code == 422

    @pytest.mark.parametrize("method", ["put", "delete"])
    def test_state_id_with_slash_422(self, monkeypatch, tmp_path, method):
        # ``{state_id:path}`` routes the raw value to the handler so the id
        # validator (not a route miss) decides the status.
        sm = _load_sm(monkeypatch, tmp_path)
        client = _client(sm)
        if method == "put":
            r = client.put("/api/playwright/states/a/b", json={"session_id": "x"})
        else:
            r = client.delete("/api/playwright/states/a/b")
        assert r.status_code == 422

    def test_delete_race_missing_file_404(self, monkeypatch, tmp_path):
        (tmp_path / "gone.json").write_text("{}")
        sm = _load_sm(monkeypatch, tmp_path)
        with patch.object(os, "unlink", side_effect=FileNotFoundError):
            r = _client(sm).delete("/api/playwright/states/gone")
        assert r.status_code == 404

    def test_put_state_accepts_max_length_id(self, monkeypatch, tmp_path):
        sm = _load_sm(monkeypatch, tmp_path)
        client = _client(sm)
        worker = self._mock_worker()
        sid = self._open(sm, worker)
        state_id = "a" * 63
        r = client.put(f"/api/playwright/states/{state_id}", json={"session_id": sid})
        assert r.status_code == 200
        worker.save.assert_called_once_with()
        assert json.loads((tmp_path / f"{state_id}.json").read_text()) == {"cookies": []}

    def test_put_state_overwrites_existing(self, monkeypatch, tmp_path):
        target = tmp_path / "existing.json"
        target.write_text("old")
        sm = _load_sm(monkeypatch, tmp_path)
        client = _client(sm)
        worker = self._mock_worker()
        worker.save.return_value = {"cookies": [{"name": "new"}]}
        sid = self._open(sm, worker)
        r = client.put("/api/playwright/states/existing", json={"session_id": sid})
        assert r.status_code == 200
        assert json.loads(target.read_text()) == {"cookies": [{"name": "new"}]}

    def test_put_state_saves_via_worker(self, monkeypatch, tmp_path):
        sm = _load_sm(monkeypatch, tmp_path)
        client = _client(sm)
        worker = self._mock_worker()
        sid = self._open(sm, worker)
        r = client.put("/api/playwright/states/mystate", json={"session_id": sid})
        assert r.status_code == 200
        assert r.json() == {"id": "mystate", "session_id": sid}
        worker.save.assert_called_once_with()
        assert json.loads((tmp_path / "mystate.json").read_text()) == {"cookies": []}

    def test_put_then_list_round_trip(self, monkeypatch, tmp_path):
        sm = _load_sm(monkeypatch, tmp_path)
        client = _client(sm)
        worker = self._mock_worker()
        sid = self._open(sm, worker)
        r = client.put("/api/playwright/states/round", json={"session_id": sid})
        assert r.status_code == 200
        assert client.get("/api/playwright/states").json() == {"states": [{"id": "round"}]}

    def test_delete_then_list_round_trip(self, monkeypatch, tmp_path):
        (tmp_path / "temp.json").write_text("{}")
        sm = _load_sm(monkeypatch, tmp_path)
        client = _client(sm)
        assert client.delete("/api/playwright/states/temp").status_code == 200
        assert client.get("/api/playwright/states").json() == {"states": []}

    def test_put_state_unknown_session_404(self, monkeypatch, tmp_path):
        sm = _load_sm(monkeypatch, tmp_path)
        r = _client(sm).put("/api/playwright/states/mystate", json={"session_id": "nope"})
        assert r.status_code == 404
        assert "detail" in r.json()

    @pytest.mark.parametrize("bad", ["Upper", "a_b", "a.b", "a" * 64])
    def test_put_state_invalid_id_422(self, monkeypatch, tmp_path, bad):
        sm = _load_sm(monkeypatch, tmp_path)
        r = _client(sm).put(f"/api/playwright/states/{bad}", json={"session_id": "x"})
        assert r.status_code == 422

    def test_put_state_requires_session_id_422(self, monkeypatch, tmp_path):
        sm = _load_sm(monkeypatch, tmp_path)
        r = _client(sm).put("/api/playwright/states/mystate", json={})
        assert r.status_code == 422

    def test_delete_state_removes_file(self, monkeypatch, tmp_path):
        (tmp_path / "gone.json").write_text("{}")
        sm = _load_sm(monkeypatch, tmp_path)
        r = _client(sm).delete("/api/playwright/states/gone")
        assert r.status_code == 200
        assert r.json() == {"status": "ok"}
        assert not (tmp_path / "gone.json").exists()

    def test_delete_unknown_state_404(self, monkeypatch, tmp_path):
        sm = _load_sm(monkeypatch, tmp_path)
        r = _client(sm).delete("/api/playwright/states/missing")
        assert r.status_code == 404
        assert "detail" in r.json()

    @pytest.mark.parametrize("bad", ["Upper", "a_b", "a" * 64])
    def test_delete_invalid_id_422(self, monkeypatch, tmp_path, bad):
        sm = _load_sm(monkeypatch, tmp_path)
        r = _client(sm).delete(f"/api/playwright/states/{bad}")
        assert r.status_code == 422

    def test_open_with_state_id(self, monkeypatch, tmp_path):
        (tmp_path / "s.json").write_text(json.dumps({"cookies": [{"name": "x"}]}))
        sm = _load_sm(monkeypatch, tmp_path)
        worker = self._mock_worker()
        with patch.object(sm, "_PlaywrightWorker", return_value=worker) as m:
            r = _client(sm).post(
                "/api/playwright/sessions",
                json={"browser": "playwright-firefox", "state_id": "s"},
            )
        assert r.status_code == 200
        # The API reads the state and passes a dict: Playwright never
        # re-opens the path (no symlink swap window).
        m.assert_called_once_with(
            "playwright-firefox",
            node=None,
            url=None,
            storage_state={"cookies": [{"name": "x"}]},
            context_options={"viewport": {"width": 1280, "height": 635}},
        )

    @pytest.mark.parametrize("payload", ["not json", "null", '"x"', "[1, 2]"])
    def test_open_state_id_malformed_file_422(self, monkeypatch, tmp_path, payload):
        (tmp_path / "bad.json").write_text(payload)
        sm = _load_sm(monkeypatch, tmp_path)
        r = _client(sm).post(
            "/api/playwright/sessions",
            json={"browser": "playwright-firefox", "state_id": "bad"},
        )
        assert r.status_code == 422

    def test_open_state_id_missing_404(self, monkeypatch, tmp_path):
        sm = _load_sm(monkeypatch, tmp_path)
        r = _client(sm).post(
            "/api/playwright/sessions",
            json={"browser": "playwright-firefox", "state_id": "missing"},
        )
        assert r.status_code == 404

    @pytest.mark.parametrize(
        "value",
        ["s.json", {"cookies": []}, "/etc/evil.json", "", 123],
    )
    def test_open_storage_state_field_removed_422(self, monkeypatch, tmp_path, value):
        # The path/dict storage_state open field was removed in v3.0.0;
        # loading is id-only (state_id).
        (tmp_path / "s.json").write_text("{}")
        sm = _load_sm(monkeypatch, tmp_path)
        r = _client(sm).post(
            "/api/playwright/sessions",
            json={"browser": "playwright-firefox", "storage_state": value},
        )
        assert r.status_code == 422

    @pytest.mark.parametrize("bad", ["..", "a/b", "a.b", "a\nb"])
    def test_open_traversal_like_state_id_422(self, monkeypatch, tmp_path, bad):
        sm = _load_sm(monkeypatch, tmp_path)
        r = _client(sm).post(
            "/api/playwright/sessions",
            json={"browser": "playwright-firefox", "state_id": bad},
        )
        assert r.status_code == 422

    @pytest.mark.parametrize("bad", ["Upper", "a_b", "a" * 64, " a", "a ", "a\n", "a\t"])
    def test_open_invalid_state_id_422(self, monkeypatch, tmp_path, bad):
        sm = _load_sm(monkeypatch, tmp_path)
        r = _client(sm).post(
            "/api/playwright/sessions",
            json={"browser": "playwright-firefox", "state_id": bad},
        )
        assert r.status_code == 422


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
                context_options={"no_viewport": True},
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

    def test_open_with_context_options(self, monkeypatch, tmp_path):
        sm = _load_sm(monkeypatch, tmp_path)
        options = {
            "locale": "ja-JP",
            "timezone_id": "Asia/Tokyo",
            "viewport": {"width": 1440, "height": 900},
            "user_agent": "pyscraper-test",
            "color_scheme": "dark",
            "device_scale_factor": 1.5,
            "has_touch": True,
            "is_mobile": False,
            "extra_http_headers": {"X-Test": "1"},
        }
        worker = self._mock_worker(sm, None)
        with patch.object(sm, "_PlaywrightWorker", return_value=worker) as m:
            r = _client(sm).post(
                "/api/playwright/sessions",
                json={"browser": "playwright-firefox", "context_options": options},
            )
        assert r.status_code == 200
        # None-valued keys are dropped so Playwright keeps its defaults.
        m.assert_called_once_with(
            "playwright-firefox",
            node=None,
            url=None,
            storage_state=None,
            context_options=options,
        )

    def test_open_context_options_drops_unset_keys(self, monkeypatch, tmp_path):
        sm = _load_sm(monkeypatch, tmp_path)
        worker = self._mock_worker(sm, None)
        with patch.object(sm, "_PlaywrightWorker", return_value=worker) as m:
            r = _client(sm).post(
                "/api/playwright/sessions",
                json={"browser": "playwright-firefox", "context_options": {"locale": "ja-JP"}},
            )
        assert r.status_code == 200
        m.assert_called_once_with(
            "playwright-firefox",
            node=None,
            url=None,
            storage_state=None,
            context_options={"locale": "ja-JP", "viewport": {"width": 1280, "height": 635}},
        )

    def test_open_native_window_by_default(self, monkeypatch, tmp_path):
        # No viewport/device_scale_factor/is_mobile: the session opens with
        # the native window size instead of Playwright's 720p default, so a
        # headed browser fills the VNC desktop.
        sm = _load_sm(monkeypatch, tmp_path)
        worker = self._mock_worker(sm, None)
        with patch.object(sm, "_PlaywrightWorker", return_value=worker) as m:
            r = _client(sm).post(
                "/api/playwright/sessions", json={"browser": "playwright-chromium"}
            )
        assert r.status_code == 200
        m.assert_called_once_with(
            "playwright-chromium",
            node=None,
            url=None,
            storage_state=None,
            context_options={"no_viewport": True},
        )

    @pytest.mark.parametrize(
        "options",
        [
            {"viewport": {"width": 800, "height": 600}},
            {"device_scale_factor": 2.0},
            {"is_mobile": True},
        ],
    )
    def test_open_emulated_session_skips_native_flag(self, monkeypatch, tmp_path, options):
        # device_scale_factor/is_mobile are rejected server-side together
        # with no_viewport, and an explicit viewport resizes the window by
        # design: none of them get the flag.
        sm = _load_sm(monkeypatch, tmp_path)
        worker = self._mock_worker(sm, None)
        with patch.object(sm, "_PlaywrightWorker", return_value=worker) as m:
            r = _client(sm).post(
                "/api/playwright/sessions",
                json={"browser": "playwright-chromium", "context_options": options},
            )
        assert r.status_code == 200
        assert "no_viewport" not in m.call_args.kwargs["context_options"]
        assert m.call_args.kwargs["context_options"] == options

    def test_open_firefox_gets_default_viewport(self, monkeypatch, tmp_path):
        # Firefox/Juggler per-page windows ignore the launch -width/-height
        # (those only size the startup window), and its no-viewport
        # fallback is the small default window. Firefox therefore gets an
        # explicit reduced-height viewport so the outer window lands on
        # the 1280x720 desktop instead of leaving black padding.
        sm = _load_sm(monkeypatch, tmp_path)
        worker = self._mock_worker(sm, None)
        with patch.object(sm, "_PlaywrightWorker", return_value=worker) as m:
            r = _client(sm).post(
                "/api/playwright/sessions", json={"browser": "playwright-firefox"}
            )
        assert r.status_code == 200
        m.assert_called_once_with(
            "playwright-firefox",
            node=None,
            url=None,
            storage_state=None,
            context_options={"viewport": {"width": 1280, "height": 635}},
        )
        assert m.call_args.kwargs["context_options"]["viewport"] == sm._default_viewport(
            "playwright-firefox"
        )
        assert "no_viewport" not in m.call_args.kwargs["context_options"]

    def test_open_webkit_gets_default_viewport(self, monkeypatch, tmp_path):
        # WebKit/MiniBrowser per-page windows likewise ignore launch flags
        # (none exist) and follow the session viewport: the measured
        # 1280x758 outer window for the legacy default overflows the
        # 1280x720 desktop, so WebKit gets the same reduced-height
        # treatment as Firefox.
        sm = _load_sm(monkeypatch, tmp_path)
        worker = self._mock_worker(sm, None)
        with patch.object(sm, "_PlaywrightWorker", return_value=worker) as m:
            r = _client(sm).post("/api/playwright/sessions", json={"browser": "playwright-webkit"})
        assert r.status_code == 200
        m.assert_called_once_with(
            "playwright-webkit",
            node=None,
            url=None,
            storage_state=None,
            context_options={"viewport": {"width": 1280, "height": 682}},
        )
        assert "no_viewport" not in m.call_args.kwargs["context_options"]

    @pytest.mark.parametrize(
        "browser, expected",
        [
            ("playwright-firefox", {"width": 1920, "height": 995}),
            ("playwright-webkit", {"width": 1920, "height": 1042}),
        ],
    )
    def test_open_default_viewport_follows_screen_env(
        self, monkeypatch, tmp_path, browser, expected
    ):
        # A custom desktop (mirrored on the manager) sizes every
        # browser window; Chromium still uses the native size instead.
        sm = _load_sm(
            monkeypatch,
            tmp_path,
            env={"PLAYWRIGHT_SCREEN_WIDTH": "1920", "PLAYWRIGHT_SCREEN_HEIGHT": "1080"},
        )
        worker = self._mock_worker(sm, None)
        with patch.object(sm, "_PlaywrightWorker", return_value=worker) as m:
            r = _client(sm).post("/api/playwright/sessions", json={"browser": browser})
        assert r.status_code == 200
        assert m.call_args.kwargs["context_options"] == {"viewport": expected}

    @pytest.mark.parametrize(
        "env",
        [
            {"PLAYWRIGHT_SCREEN_WIDTH": "bogus"},
            {"PLAYWRIGHT_SCREEN_HEIGHT": "0"},
        ],
    )
    def test_open_default_viewport_falls_back_on_invalid_screen_env(
        self, monkeypatch, tmp_path, env
    ):
        # Invalid screen values fall back to 1280x720 with a warning
        # (manager convention), so sessions still open filled.
        sm = _load_sm(monkeypatch, tmp_path, env=env)
        worker = self._mock_worker(sm, None)
        with patch.object(sm, "_PlaywrightWorker", return_value=worker) as m:
            r = _client(sm).post(
                "/api/playwright/sessions", json={"browser": "playwright-firefox"}
            )
        assert r.status_code == 200
        assert m.call_args.kwargs["context_options"] == {
            "viewport": {"width": 1280, "height": 635}
        }

    def test_open_webkit_viewport_passes_through(self, monkeypatch, tmp_path):
        sm = _load_sm(monkeypatch, tmp_path)
        worker = self._mock_worker(sm, None)
        options = {"viewport": {"width": 1280, "height": 720}}
        with patch.object(sm, "_PlaywrightWorker", return_value=worker) as m:
            r = _client(sm).post(
                "/api/playwright/sessions",
                json={"browser": "playwright-webkit", "context_options": options},
            )
        assert r.status_code == 200
        m.assert_called_once_with(
            "playwright-webkit",
            node=None,
            url=None,
            storage_state=None,
            context_options=options,
        )

    @pytest.mark.parametrize(
        "options",
        [
            {"storage_state": {"cookies": []}},
            {"proxy": {"server": "http://x"}},
            {"bogus": 1},
            {"locale": 1},
            {"color_scheme": "auto"},
            {"device_scale_factor": 0},
            {"device_scale_factor": "2"},
            {"has_touch": "yes"},
            {"is_mobile": "yes"},
            {"viewport": {"width": 0, "height": 1}},
            {"viewport": {"width": 1.5, "height": 1}},
            {"viewport": {"width": 1}},
            {"viewport": {"width": 1, "height": 1, "x": 1}},
            {"extra_http_headers": {"X": 1}},
        ],
    )
    def test_open_bad_context_options_422(self, monkeypatch, tmp_path, options):
        sm = _load_sm(monkeypatch, tmp_path)
        r = _client(sm).post(
            "/api/playwright/sessions",
            json={"browser": "playwright-chromium", "context_options": options},
        )
        assert r.status_code == 422

    def test_open_context_options_passed_to_new_context(self, monkeypatch, tmp_path):
        import sys
        import types

        sm = _load_sm(monkeypatch, tmp_path)
        browser = MagicMock()
        browser_type = MagicMock()
        browser_type.connect.return_value = browser
        pw = MagicMock()
        pw.chromium = browser_type
        fake_factory = MagicMock()
        fake_factory.return_value.start.return_value = pw
        fake_api = types.ModuleType("playwright.sync_api")
        fake_api.sync_playwright = fake_factory
        monkeypatch.setitem(sys.modules, "playwright.sync_api", fake_api)
        options = {"locale": "ja-JP", "viewport": {"width": 800, "height": 600}}
        sm._PlaywrightBackend.open(
            "playwright-chromium",
            storage_state={"cookies": []},
            context_options=options,
        )
        browser.new_context.assert_called_once_with(
            locale="ja-JP",
            viewport={"width": 800, "height": 600},
            storage_state={"cookies": []},
        )

    def test_open_native_flag_passed_to_new_context(self, monkeypatch, tmp_path):
        import sys
        import types

        sm = _load_sm(monkeypatch, tmp_path)
        browser = MagicMock()
        browser_type = MagicMock()
        browser_type.connect.return_value = browser
        pw = MagicMock()
        pw.chromium = browser_type
        fake_factory = MagicMock()
        fake_factory.return_value.start.return_value = pw
        fake_api = types.ModuleType("playwright.sync_api")
        fake_api.sync_playwright = fake_factory
        monkeypatch.setitem(sys.modules, "playwright.sync_api", fake_api)
        sm._PlaywrightBackend.open(
            "playwright-chromium",
            context_options={"locale": "ja-JP", "no_viewport": True},
        )
        browser.new_context.assert_called_once_with(
            locale="ja-JP",
            no_viewport=True,
        )

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

    def test_open_port_out_of_range_falls_back(self, monkeypatch, tmp_path):
        sm = _load_sm(monkeypatch, tmp_path, env={"PLAYWRIGHT_SESSION_MANAGER_PORT": "99999"})
        assert sm.PORT == 8081

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
        ):
            r = _client(sm).post("/api/playwright/sessions", json=payload)
            assert r.status_code == 422

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
                context_options={"no_viewport": True},
            )
            assert r.json()["url"] == "https://example.com"

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
        r = _client(sm).post("/api/playwright/states", json={})
        assert r.status_code == 405
        assert "detail" in r.json()

    def test_unknown_path_404(self, monkeypatch, tmp_path):
        sm = _load_sm(monkeypatch, tmp_path)
        r = _client(sm).post("/api/nope", json={})
        assert r.status_code == 404
        assert "detail" in r.json()

    def test_removed_state_files_path_404(self, monkeypatch, tmp_path):
        sm = _load_sm(monkeypatch, tmp_path)
        r = _client(sm).get("/api/playwright/state-files")
        assert r.status_code == 404

    def test_removed_save_path_404(self, monkeypatch, tmp_path):
        sm = _load_sm(monkeypatch, tmp_path)
        r = _client(sm).post("/api/playwright/sessions/xxx/save", json={"path": "s.json"})
        assert r.status_code == 404

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
        m.assert_called_once_with(
            "playwright-webkit",
            node=None,
            url=None,
            storage_state=None,
            context_options={"viewport": {"width": 1280, "height": 682}},
        )
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

    def test_openapi_state_id_constraints(self, monkeypatch, tmp_path):
        sm = _load_sm(monkeypatch, tmp_path)
        spec = _client(sm).get("/openapi.json").json()
        schema = spec["components"]["schemas"]["OpenRequest"]["properties"]["state_id"]
        string_type = next(
            (part for part in schema["anyOf"] if part.get("type") == "string"), None
        )
        assert string_type is not None
        assert string_type["pattern"] == "^[a-z0-9-]+$"
        assert string_type["maxLength"] == 63
