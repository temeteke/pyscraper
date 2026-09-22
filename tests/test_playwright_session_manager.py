"""Unit tests for servers/playwright_session_manager.py.

The Playwright session manager opens/closes browser sessions for the
gateway UI via the Hub relay, with storage_state load/save
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

    def test_open_state_id_and_storage_state_422(self, monkeypatch, tmp_path):
        (tmp_path / "s.json").write_text("{}")
        sm = _load_sm(monkeypatch, tmp_path)
        r = _client(sm).post(
            "/api/playwright/sessions",
            json={
                "browser": "playwright-firefox",
                "state_id": "s",
                "storage_state": "s.json",
            },
        )
        assert r.status_code == 422

    def test_open_state_id_and_dict_storage_state_422(self, monkeypatch, tmp_path):
        (tmp_path / "s.json").write_text("{}")
        sm = _load_sm(monkeypatch, tmp_path)
        r = _client(sm).post(
            "/api/playwright/sessions",
            json={
                "browser": "playwright-firefox",
                "state_id": "s",
                "storage_state": {"cookies": []},
            },
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
        worker.save.assert_called_once_with()
        assert json.loads((tmp_path / "s.json").read_text()) == {"cookies": []}

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
        worker.save.assert_called_once_with()
        assert json.loads((tmp_path / "s.json").read_text()) == {"cookies": []}

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

    def test_save_unknown_session_beats_bad_path(self, monkeypatch, tmp_path):
        # v2.0.0 precedence: unknown session is 404 even if the path also
        # escapes the state dir.
        sm = _load_sm(monkeypatch, tmp_path)
        r = _client(sm).post("/api/playwright/sessions/xxx/save", json={"path": "/etc/evil.json"})
        assert r.status_code == 404

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
