"""Unit tests for servers/playwright_hub.py.

The Hub is a stateless launch-server relay with fail-closed routing:
missing/invalid/unknown headers are rejected, never routed elsewhere.
"""

import asyncio
import importlib.util
import json
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

HUB_PATH = Path(__file__).resolve().parent.parent / "servers" / "playwright_hub.py"


def _load_hub(monkeypatch, env=None):
    """Load playwright_hub without executing the __main__ block."""
    for key in (
        "PLAYWRIGHT_HUB_PORT",
        "PLAYWRIGHT_NODE_CONNECT_TIMEOUT",
        "PLAYWRIGHT_HUB_NODE_TTL",
    ):
        monkeypatch.delenv(key, raising=False)
    monkeypatch.setenv("PLAYWRIGHT_HUB_PORT", "14000")
    for key, value in (env or {}).items():
        monkeypatch.setenv(key, value)
    spec = importlib.util.spec_from_file_location("playwright_hub", HUB_PATH)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@pytest.fixture
def hub(monkeypatch):
    module = _load_hub(monkeypatch)
    module.NODES.clear()
    now = module._now()
    module.NODES.update(
        {
            "chromium": {
                "browser": "chromium",
                "ws_endpoint": "ws://chromium:3000/abc",
                "last_seen": now,
            },
            "firefox": {
                "browser": "firefox",
                "ws_endpoint": "ws://firefox:3000/def",
                "last_seen": now,
            },
        }
    )
    return module


class TestSelectNode:
    def test_node_name_wins(self, hub):
        assert hub._select_node({"node": "firefox"})["browser"] == "firefox"

    def test_browser_match_without_node(self, hub):
        assert hub._select_node({"browser": "firefox"})["browser"] == "firefox"

    def test_missing_header_rejected(self, hub):
        assert hub._select_node(None) is None

    def test_invalid_json_rejected(self, hub):
        assert hub._select_node(None) is None

    def test_unknown_node_rejected(self, hub):
        assert hub._select_node({"node": "no-such-node"}) is None

    def test_unknown_browser_rejected_not_fallback(self, hub):
        # Fail-closed: no silent routing to another browser.
        assert hub._select_node({"browser": "webkit"}) is None

    def test_empty_options_rejected(self, hub):
        assert hub._select_node({}) is None

    def test_non_dict_rejected(self, hub):
        assert hub._select_node("chromium") is None

    def test_non_string_node_rejected(self, hub):
        assert hub._select_node({"node": ["chromium"]}) is None
        assert hub._select_node({"node": {"n": 1}}) is None
        assert hub._select_node({"node": 0}) is None

    def test_padded_name_resolves(self, hub):
        assert hub._select_node({"node": " chromium "})["browser"] == "chromium"

    def test_padded_browser_resolves(self, hub):
        assert hub._select_node({"browser": " firefox "})["browser"] == "firefox"


class TestRegistry:
    def test_register_shape(self, hub):
        # Public snapshots carry name/browser/ws_endpoint only: last_seen
        # is internal and never exposed to relay clients.
        assert set(hub._public_snapshot()["chromium"]) == {"browser", "ws_endpoint"}

    def test_register_records_last_seen(self, hub):
        before = hub._now()
        code = _make_registry_request(
            hub,
            "/register",
            {
                "name": "webkit",
                "browser": "webkit",
                "ws_endpoint": "ws://webkit:3000/x",
            },
        )
        assert code == 200
        assert before <= hub.NODES["webkit"]["last_seen"] <= hub._now()

    def test_relay_rejects_without_node(self, hub):
        # _relay closes with 1011 when selection fails; covered via _select_node.
        assert hub._select_node(json.loads('{"browser": "unknown"}')) is None


def _make_registry_request(hub, path, payload=None):
    import io

    handler = hub._RegistryHandler.__new__(hub._RegistryHandler)
    handler.path = path
    body = json.dumps(payload).encode() if payload is not None else b""
    handler.rfile = io.BytesIO(body)
    handler.headers = {"Content-Length": str(len(body))}
    responses = []

    def fake_send_response(code):
        responses.append({"code": code})

    handler.send_response = fake_send_response
    handler.send_header = lambda k, v: None
    handler.end_headers = lambda: None
    handler.wfile = io.BytesIO()
    handler.do_POST()
    assert responses, "no response sent"
    return responses[-1]["code"]


class TestRegisterValidation:
    def test_register_ok(self, hub):
        code = _make_registry_request(
            hub,
            "/register",
            {
                "name": "webkit",
                "browser": "webkit",
                "ws_endpoint": "ws://webkit:3000/x",
            },
        )
        assert code == 200
        assert hub.NODES["webkit"]["browser"] == "webkit"

    def test_register_missing_name_400(self, hub):
        code = _make_registry_request(
            hub,
            "/register",
            {
                "browser": "chromium",
                "ws_endpoint": "ws://x:3000/y",
            },
        )
        assert code == 400

    def test_read_json_rejects_bad_length(self, hub):
        import io

        handler = hub._RegistryHandler.__new__(hub._RegistryHandler)
        handler.rfile = io.BytesIO(b"{}")
        # Non-integer and negative Content-Length are rejected (None ->
        # 400 upstream); a missing header is treated as an empty object.
        for value in ("abc", "-5"):
            handler.headers = {"Content-Length": value}
            assert handler._read_json() is None
        handler.headers = {}
        assert handler._read_json() == {}

    def test_register_bad_scheme_400(self, hub):
        code = _make_registry_request(
            hub,
            "/register",
            {
                "name": "evil",
                "browser": "chromium",
                "ws_endpoint": "http://evil:3000/",
            },
        )
        assert code == 400
        assert "evil" not in hub.NODES

    def test_register_non_string_400(self, hub):
        code = _make_registry_request(
            hub,
            "/register",
            {
                "name": 123,
                "browser": "chromium",
                "ws_endpoint": "ws://x:3000/y",
            },
        )
        assert code == 400
        assert 123 not in hub.NODES

    def test_register_blank_name_400(self, hub):
        code = _make_registry_request(
            hub,
            "/register",
            {
                "name": "   ",
                "browser": "chromium",
                "ws_endpoint": "ws://x:3000/y",
            },
        )
        assert code == 400
        assert "   " not in hub.NODES

    def test_register_strips_name(self, hub):
        code = _make_registry_request(
            hub,
            "/register",
            {
                "name": " padded ",
                "browser": "chromium",
                "ws_endpoint": "ws://x:3000/y",
            },
        )
        assert code == 200
        assert "padded" in hub.NODES
        assert " padded " not in hub.NODES

    def test_register_strips_endpoint(self, hub):
        code = _make_registry_request(
            hub,
            "/register",
            {
                "name": "sp",
                "browser": "chromium",
                "ws_endpoint": "ws://x:3000/y  ",
            },
        )
        assert code == 200
        assert hub.NODES["sp"]["ws_endpoint"] == "ws://x:3000/y"

    def test_register_blank_browser_400(self, hub):
        code = _make_registry_request(
            hub,
            "/register",
            {
                "name": "x",
                "browser": "   ",
                "ws_endpoint": "ws://x:3000/y",
            },
        )
        assert code == 400

    def test_unregister_stripped_name(self, hub):
        hub.NODES["temp"] = {
            "browser": "chromium",
            "ws_endpoint": "ws://x:3000/y",
            "last_seen": hub._now(),
        }
        code = _make_registry_request(hub, "/unregister", {"name": " temp "})
        assert code == 200
        assert "temp" not in hub.NODES

    def test_unregister_non_string_400(self, hub):
        code = _make_registry_request(hub, "/unregister", {"name": ["chromium"]})
        assert code == 400
        assert "chromium" in hub.NODES  # untouched

    def test_unregister_missing_name_400(self, hub):
        code = _make_registry_request(hub, "/unregister", {})
        assert code == 400

    def test_register_query_and_trailing_slash_ok(self, hub):
        for path in ("/register?x=1", "/register/"):
            code = _make_registry_request(
                hub,
                path,
                {
                    "name": "q",
                    "browser": "chromium",
                    "ws_endpoint": "ws://x:3000/y",
                },
            )
            assert code == 200
        assert hub.NODES["q"]["browser"] == "chromium"

    def test_register_newline_name_logged_escaped(self, hub, capsys):
        code = _make_registry_request(
            hub,
            "/register",
            {
                "name": "evil\ninjected",
                "browser": "chromium",
                "ws_endpoint": "ws://x:3000/y",
            },
        )
        assert code == 200
        out = capsys.readouterr().out
        assert "evil\\ninjected" in out
        assert out.count("\n") == 1


def _make_client_ws(header=None):
    ws = MagicMock()
    ws.request_headers = {"x-playwright-launch-options": header} if header else {}
    ws.close = AsyncMock()
    return ws


class TestRelay:
    def _run(self, hub, client_ws):
        return asyncio.run(hub._relay(client_ws))

    def test_relay_missing_header_1011(self, hub):
        ws = _make_client_ws()
        self._run(hub, ws)
        ws.close.assert_called_once_with(1011, "no node available")

    def test_relay_reject_disconnected_client(self, hub):
        from websockets.exceptions import ConnectionClosed

        ws = _make_client_ws(json.dumps({"node": "no-such-node"}))
        ws.close.side_effect = ConnectionClosed(None, None)
        self._run(hub, ws)  # must not raise
        ws.close.assert_called_once_with(1011, "no node available")

    def test_relay_invalid_json_1011(self, hub):
        ws = _make_client_ws("{not-json")
        self._run(hub, ws)
        ws.close.assert_called_once_with(1011, "no node available")

    def test_relay_unknown_node_1011(self, hub):
        ws = _make_client_ws(json.dumps({"node": "no-such-node"}))
        self._run(hub, ws)
        ws.close.assert_called_once_with(1011, "no node available")

    def test_relay_unknown_browser_1011(self, hub):
        ws = _make_client_ws(json.dumps({"browser": "webkit"}))
        self._run(hub, ws)
        ws.close.assert_called_once_with(1011, "no node available")

    def test_relay_non_string_node_1011(self, hub):
        ws = _make_client_ws(json.dumps({"node": ["chromium"]}))
        self._run(hub, ws)
        ws.close.assert_called_once_with(1011, "no node available")

    def test_relay_explicit_node_taken_as_is(self, hub):
        # Explicit node= wins even across browsers (routing request).
        node = hub._select_node({"node": "firefox", "browser": "chromium"})
        assert node["browser"] == "firefox"

    def test_relay_bad_endpoint_scheme_1011(self, hub):
        hub.NODES["broken"] = {
            "browser": "chromium",
            "ws_endpoint": "http://x:3000/",
            "last_seen": hub._now(),
        }
        ws = _make_client_ws(json.dumps({"node": "broken"}))
        self._run(hub, ws)
        ws.close.assert_called_once_with(1011, "node endpoint unavailable")

    def test_relay_dead_node_1011(self, hub):
        ws = _make_client_ws(json.dumps({"browser": "chromium"}))
        with patch.object(hub.websockets, "connect", side_effect=OSError("refused")) as m:
            self._run(hub, ws)
        ws.close.assert_called_once_with(1011, "node endpoint unavailable")
        assert m.call_args.kwargs.get("open_timeout") == hub.NODE_CONNECT_TIMEOUT

    def test_relay_double_close_suppressed(self, hub):
        from unittest.mock import AsyncMock

        from websockets.exceptions import ConnectionClosed

        ws = _make_client_ws(json.dumps({"browser": "chromium"}))
        node_ws = AsyncMock()
        closed = ConnectionClosed(None, None)
        node_ws.close.side_effect = closed
        ws.close.side_effect = closed

        async def _connect(*args, **kwargs):
            return node_ws

        async def _noop(src, dst):
            return None

        with patch.object(hub.websockets, "connect", side_effect=_connect):
            with patch.object(hub, "_pipe", side_effect=_noop):
                self._run(hub, ws)  # must not raise

    def test_relay_connect_timeout_1011(self, hub):
        ws = _make_client_ws(json.dumps({"browser": "chromium"}))
        with patch.object(hub.websockets, "connect", side_effect=TimeoutError("slow")):
            self._run(hub, ws)
        ws.close.assert_called_once_with(1011, "node endpoint unavailable")

    def test_relay_connect_failure_logs_escaped(self, hub, capsys):
        hub.NODES["evil"] = {
            "browser": "chromium",
            "ws_endpoint": "ws://x:3000/a\nb",
            "last_seen": hub._now(),
        }
        ws = _make_client_ws(json.dumps({"node": "evil"}))
        with patch.object(hub.websockets, "connect", side_effect=OSError("refused")):
            self._run(hub, ws)
        ws.close.assert_called_once_with(1011, "node endpoint unavailable")
        out = capsys.readouterr().err
        assert "a\\nb" in out
        assert out.count("\n") == 1

    def test_connect_timeout_default(self, monkeypatch):
        module = _load_hub(monkeypatch)
        assert module.NODE_CONNECT_TIMEOUT == 10

    def test_connect_timeout_env(self, monkeypatch):
        module = _load_hub(monkeypatch, env={"PLAYWRIGHT_NODE_CONNECT_TIMEOUT": "3"})
        assert module.NODE_CONNECT_TIMEOUT == 3

    def test_out_of_range_port_falls_back(self, monkeypatch):
        module = _load_hub(monkeypatch, env={"PLAYWRIGHT_HUB_PORT": "99999"})
        assert module.PORT == 4000

    def test_max_port_falls_back(self, monkeypatch):
        # REG_PORT derives as PORT+1, so 65535 is rejected too.
        module = _load_hub(monkeypatch, env={"PLAYWRIGHT_HUB_PORT": "65535"})
        assert module.PORT == 4000
        assert module.REG_PORT == 4001

    def test_nodes_include_names(self, hub):
        import io

        handler = hub._RegistryHandler.__new__(hub._RegistryHandler)
        handler.path = "/nodes"
        codes = []
        handler.send_response = lambda c: codes.append(c)
        handler.send_header = lambda k, v: None
        handler.end_headers = lambda: None
        out = io.BytesIO()
        handler.wfile = out
        handler.do_GET()
        assert codes == [200]
        names = {n["name"] for n in json.loads(out.getvalue())["nodes"]}
        assert names == {"chromium", "firefox"}

    def test_health_and_nodes_query_and_trailing_slash_ok(self, hub):
        import io

        for path in ("/health?x=1", "/health/", "/nodes?x=1", "/nodes/"):
            handler = hub._RegistryHandler.__new__(hub._RegistryHandler)
            handler.path = path
            codes = []
            handler.send_response = lambda c, codes=codes: codes.append(c)
            handler.send_header = lambda k, v: None
            handler.end_headers = lambda: None
            handler.wfile = io.BytesIO()
            handler.do_GET()
            assert codes == [200], path


def _get_json(hub, path):
    import io

    handler = hub._RegistryHandler.__new__(hub._RegistryHandler)
    handler.path = path
    codes = []
    handler.send_response = lambda c: codes.append(c)
    handler.send_header = lambda k, v: None
    handler.end_headers = lambda: None
    out = io.BytesIO()
    handler.wfile = out
    handler.do_GET()
    assert codes == [200]
    return json.loads(out.getvalue())


class TestNodeTTL:
    def _register(self, hub, name="webkit", **overrides):
        payload = {
            "name": name,
            "browser": "webkit",
            "ws_endpoint": "ws://webkit:3000/x",
        }
        payload.update(overrides)
        assert _make_registry_request(hub, "/register", payload) == 200

    def test_defaults(self, monkeypatch):
        module = _load_hub(monkeypatch)
        assert module.NODE_TTL == 30

    def test_valid_ttl_env(self, monkeypatch):
        module = _load_hub(monkeypatch, env={"PLAYWRIGHT_HUB_NODE_TTL": "5"})
        assert module.NODE_TTL == 5

    def test_invalid_ttl_falls_back(self, monkeypatch, capsys):
        for bad in ("bogus", "0", "-5"):
            module = _load_hub(monkeypatch, env={"PLAYWRIGHT_HUB_NODE_TTL": bad})
            assert module.NODE_TTL == 30
        assert "invalid PLAYWRIGHT_HUB_NODE_TTL" in capsys.readouterr().err

    def test_stale_node_excluded_from_selection(self, hub):
        self._register(hub)
        hub.NODES["webkit"]["last_seen"] = hub._now() - hub.NODE_TTL - 1
        assert hub._select_node({"browser": "webkit"}) is None

    def test_stale_node_pruned_from_nodes_listing(self, hub):
        self._register(hub)
        hub.NODES["webkit"]["last_seen"] = hub._now() - hub.NODE_TTL - 1
        names = {n["name"] for n in _get_json(hub, "/nodes")["nodes"]}
        assert names == {"chromium", "firefox"}
        assert "webkit" not in hub.NODES

    def test_stale_node_excluded_from_health(self, hub):
        body = _get_json(hub, "/health")
        assert body == {
            "status": "ok",
            "nodes": 2,
            "browsers": {"chromium": 1, "firefox": 1},
        }
        hub.NODES["chromium"]["last_seen"] = hub._now() - hub.NODE_TTL - 1
        body = _get_json(hub, "/health")
        assert body == {"status": "ok", "nodes": 1, "browsers": {"firefox": 1}}

    def test_boundary_not_pruned_without_advance(self, hub, monkeypatch):
        # Entries exactly at the TTL boundary survive until time advances.
        # Anchor all reads to a fixed clock: real monotonic time would
        # make the exact-boundary probe flaky (float overshoot past TTL).
        self._register(hub)
        now = hub.NODES["webkit"]["last_seen"]
        monkeypatch.setattr(hub, "_now", lambda: now)
        assert hub._select_node({"browser": "webkit"}) is not None
        monkeypatch.setattr(hub, "_now", lambda: now + hub.NODE_TTL)
        assert hub._select_node({"browser": "webkit"}) is not None
        assert "webkit" in hub.NODES
        monkeypatch.setattr(hub, "_now", lambda: now + hub.NODE_TTL + 1)
        assert hub._select_node({"browser": "webkit"}) is None

    def test_reregister_revives_stale_node(self, hub):
        self._register(hub)
        hub.NODES["webkit"]["last_seen"] = hub._now() - hub.NODE_TTL - 1
        assert hub._select_node({"browser": "webkit"}) is None
        self._register(hub, ws_endpoint="ws://webkit:3000/y")
        node = hub._select_node({"browser": "webkit"})
        assert node["ws_endpoint"] == "ws://webkit:3000/y"

    def test_reregister_updates_endpoint(self, hub):
        self._register(hub)
        self._register(hub, ws_endpoint="ws://webkit:3000/rotated")
        assert hub.NODES["webkit"]["ws_endpoint"] == "ws://webkit:3000/rotated"

    def test_legacy_entry_without_last_seen_stamped_then_expires(self, hub, monkeypatch):
        # Entries predating last_seen (e.g. in-memory state across a hot
        # reload) are kept on first sight but stamped, so TTL applies
        # from then on instead of living forever.
        hub.NODES["legacy"] = {"browser": "webkit", "ws_endpoint": "ws://x:3000/y"}
        first = hub._now()
        assert hub._select_node({"node": "legacy"}) is not None
        stamped = hub.NODES["legacy"]["last_seen"]
        assert first <= stamped <= hub._now()
        monkeypatch.setattr(hub, "_now", lambda: stamped + hub.NODE_TTL + 1)
        assert hub._select_node({"node": "legacy"}) is None

    def test_nodes_wire_hides_last_seen(self, hub):
        self._register(hub)
        nodes = _get_json(hub, "/nodes")["nodes"]
        assert nodes
        assert all(set(n) == {"name", "browser", "ws_endpoint"} for n in nodes)

    def test_prune_logs_after_lock_release(self, hub, capsys):
        # Pruning reports stale nodes without holding _LOCK during I/O.
        self._register(hub)
        capsys.readouterr()  # drain the /register log above
        hub.NODES["webkit"]["last_seen"] = hub._now() - hub.NODE_TTL - 1
        assert hub._LOCK.acquire(blocking=False)
        try:
            expired = hub._prune_expired()
        finally:
            hub._LOCK.release()
        assert expired == ["webkit"]
        assert capsys.readouterr().out == ""  # no logging while locked

    def test_select_prunes_dead_browser(self, hub):
        hub.NODES["chromium"]["last_seen"] = hub._now() - hub.NODE_TTL - 1
        assert hub._select_node({"browser": "chromium"}) is None
        assert "chromium" not in hub.NODES
