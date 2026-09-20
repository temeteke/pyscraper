"""Unit tests for servers/playwright_node.py.

The node is stateless: launch-server config for any browser, headed for
noVNC, with proxy env reflected and endpoints rewritten to the advertised
host.
"""

import importlib.util
import os
from pathlib import Path

SERVER_PATH = Path(__file__).resolve().parent.parent / "servers" / "playwright_node.py"


def _load_server(monkeypatch, env=None):
    for key in (
        "PLAYWRIGHT_BROWSER",
        "PLAYWRIGHT_PORT",
        "PLAYWRIGHT_NODE_NAME",
        "PLAYWRIGHT_ADVERTISE_HOST",
        "PLAYWRIGHT_HUB_URL",
        "HTTPS_PROXY",
        "https_proxy",
        "HTTP_PROXY",
        "http_proxy",
        "NO_PROXY",
        "no_proxy",
    ):
        monkeypatch.delenv(key, raising=False)
    monkeypatch.setenv("PLAYWRIGHT_HUB_URL", "")
    for key, value in (env or {}).items():
        monkeypatch.setenv(key, value)
    spec = importlib.util.spec_from_file_location("playwright_node", SERVER_PATH)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class TestLaunchConfig:
    def test_defaults_stateless_headed(self, monkeypatch):
        server = _load_server(monkeypatch)
        config = server._launch_config()
        assert config["port"] == 3000
        assert config["host"] == "0.0.0.0"
        assert config["headless"] is False
        assert "proxy" not in config

    def test_chromium_automation_flags(self, monkeypatch):
        server = _load_server(monkeypatch, {"PLAYWRIGHT_BROWSER": "chromium"})
        config = server._launch_config()
        assert config["args"] == ["--disable-blink-features=AutomationControlled"]
        assert config["ignoreDefaultArgs"] == ["--enable-automation"]

    def test_firefox_has_no_chromium_flags(self, monkeypatch):
        server = _load_server(monkeypatch, {"PLAYWRIGHT_BROWSER": "firefox"})
        config = server._launch_config()
        assert "args" not in config
        assert "ignoreDefaultArgs" not in config

    def test_proxy_https_preferred(self, monkeypatch):
        server = _load_server(
            monkeypatch,
            {
                "HTTP_PROXY": "http://http-proxy:8080",
                "HTTPS_PROXY": "http://https-proxy:8080",
                "NO_PROXY": "localhost",
            },
        )
        config = server._launch_config()
        assert config["proxy"]["server"] == "http://https-proxy:8080"
        assert config["proxy"]["bypass"] == "localhost"

    def test_port_from_env(self, monkeypatch):
        server = _load_server(monkeypatch, {"PLAYWRIGHT_PORT": "3002"})
        assert server._launch_config()["port"] == 3002
        assert server.PORT == 3002


class TestRewriteEndpoint:
    def test_ws_endpoint_line(self, monkeypatch):
        server = _load_server(monkeypatch, {"PLAYWRIGHT_ADVERTISE_HOST": "pw-chromium"})
        out = server._rewrite_endpoint("WS_ENDPOINT=ws://0.0.0.0:3000/abc123")
        assert out == "ws://pw-chromium:3000/abc123"

    def test_bare_ws_line(self, monkeypatch):
        server = _load_server(monkeypatch, {"PLAYWRIGHT_ADVERTISE_HOST": "pw-firefox"})
        out = server._rewrite_endpoint("ws://127.0.0.1:3000/def456")
        assert out == "ws://pw-firefox:3000/def456"

    def test_missing_port_falls_back(self, monkeypatch):
        server = _load_server(
            monkeypatch,
            {"PLAYWRIGHT_ADVERTISE_HOST": "pw-webkit", "PLAYWRIGHT_PORT": "3000"},
        )
        out = server._rewrite_endpoint("ws://127.0.0.1/abc")
        assert out == "ws://pw-webkit:3000/abc"

    def test_bad_scheme_rejected(self, monkeypatch):
        import pytest

        server = _load_server(monkeypatch, {"PLAYWRIGHT_ADVERTISE_HOST": "pw-x"})
        with pytest.raises(ValueError, match="scheme"):
            server._rewrite_endpoint("http://127.0.0.1:3000/abc")

    def test_invalid_port_rejected(self, monkeypatch):
        import pytest

        server = _load_server(monkeypatch, {"PLAYWRIGHT_ADVERTISE_HOST": "pw-x"})
        with pytest.raises(ValueError, match="port"):
            server._rewrite_endpoint("ws://127.0.0.1:999999/abc")

    def test_invalid_port_env_fails_fast(self, monkeypatch):
        import pytest

        with pytest.raises(SystemExit, match="PLAYWRIGHT_PORT"):
            _load_server(monkeypatch, {"PLAYWRIGHT_PORT": "bogus"})

    def test_out_of_range_port_fails_fast(self, monkeypatch):
        import pytest

        for bad in ("0", "-1", "65536"):
            with pytest.raises(SystemExit, match="PLAYWRIGHT_PORT"):
                _load_server(monkeypatch, {"PLAYWRIGHT_PORT": bad})

    def test_launch_config_without_proxy(self, monkeypatch):
        server = _load_server(monkeypatch)
        assert "proxy" not in server._launch_config()


class TestPlainNodeLaunchWait:
    def _fake_proc(self, stdout):
        from unittest.mock import MagicMock

        proc = MagicMock()
        proc.stdout = stdout
        return proc

    def test_reports_endpoint(self, monkeypatch):
        import os
        from unittest.mock import patch

        server = _load_server(monkeypatch, {"PLAYWRIGHT_ADVERTISE_HOST": "pw-chromium-node"})
        r, w = os.pipe()
        os.write(w, b"WS_ENDPOINT=ws://0.0.0.0:3000/abc\n")
        os.close(w)
        registered = []
        monkeypatch.setattr(server, "_register", registered.append)
        monkeypatch.setattr(server, "_unregister", lambda: None)
        with open(r, "r") as stdout:
            with patch.object(server.subprocess, "Popen", return_value=self._fake_proc(stdout)):
                server._plain_node()
        assert registered == ["ws://pw-chromium-node:3000/abc"]

    def test_silent_launch_server_times_out(self, monkeypatch):
        import os
        import pytest
        from unittest.mock import patch

        server = _load_server(monkeypatch)
        monkeypatch.setattr(server, "LAUNCH_WAIT_TIMEOUT", 1)
        r, w = os.pipe()  # writer held open: no data, no EOF -> select must time out
        try:
            proc = self._fake_proc(os.fdopen(r, "r"))
            monkeypatch.setattr(server, "_register", lambda *a: None)
            monkeypatch.setattr(server, "_unregister", lambda: None)
            with patch.object(server.subprocess, "Popen", return_value=proc):
                with pytest.raises(RuntimeError, match="did not report WS_ENDPOINT"):
                    server._plain_node()
            proc.terminate.assert_called_once_with()
            proc.wait.assert_called_once_with(timeout=5)
        finally:
            os.close(w)

    def test_stubborn_launch_server_killed(self, monkeypatch):
        import os
        import pytest
        from unittest.mock import patch

        server = _load_server(monkeypatch)
        monkeypatch.setattr(server, "LAUNCH_WAIT_TIMEOUT", 1)
        r, w = os.pipe()
        try:
            proc = self._fake_proc(os.fdopen(r, "r"))
            proc.wait.side_effect = server.subprocess.TimeoutExpired("cmd", 5)
            monkeypatch.setattr(server, "_register", lambda *a: None)
            monkeypatch.setattr(server, "_unregister", lambda: None)
            with patch.object(server.subprocess, "Popen", return_value=proc):
                with pytest.raises(RuntimeError, match="did not report WS_ENDPOINT"):
                    server._plain_node()
            proc.kill.assert_called_once_with()
        finally:
            os.close(w)


class TestEnvDefaults:
    def test_node_name_default(self, monkeypatch):
        server = _load_server(monkeypatch, {"PLAYWRIGHT_BROWSER": "webkit"})
        assert server.NODE_NAME == "webkit-node"

    def test_no_profile_or_cdp_settings(self, monkeypatch):
        server = _load_server(monkeypatch)
        assert not hasattr(server, "PROFILE")
        assert not hasattr(server, "CDP_PORT")
        assert "PLAYWRIGHT_PROFILE" not in os.environ


class TestNodeSelfContained:
    def test_no_pyscraper_import(self):
        # The node image ships only playwright: importing pyscraper would
        # pull fake_useragent/lxml/etc. and crash at container boot.
        source = SERVER_PATH.read_text()
        assert "from pyscraper" not in source
        assert "import pyscraper" not in source

    def test_no_pyscraper_copy_in_dockerfile(self):
        node_docker = (
            Path(__file__).resolve().parent.parent / "Dockerfile.playwright-node"
        ).read_text()
        assert "COPY pyscraper" not in node_docker

    def test_loads_without_pyscraper_installed(self, monkeypatch, tmp_path):
        # Simulate the node image: playwright_node.py alone on sys.path,
        # with any pyscraper package hidden.
        import shutil
        import sys

        target = tmp_path / "playwright_node.py"
        shutil.copy(SERVER_PATH, target)
        monkeypatch.syspath_prepend(str(tmp_path))
        hidden = {
            k: v for k, v in sys.modules.items() if k == "pyscraper" or k.startswith("pyscraper.")
        }
        for k in hidden:
            del sys.modules[k]
        try:
            assert "pyscraper" not in sys.modules
            spec = importlib.util.spec_from_file_location("pw_server_isolated", target)
            module = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(module)
            assert module._get_env_anycase("HTTP_PROXY") is None
            assert "pyscraper" not in sys.modules
        finally:
            sys.modules.update(hidden)

    def test_helper_matches_client(self, monkeypatch):
        # The vendored helper must behave like the client original.
        from pyscraper.webpage import _get_env_anycase as client_helper

        server = _load_server(monkeypatch)
        for key, value in (("HTTP_PROXY", "http://proxy:8080"), ("NO_PROXY", "localhost")):
            monkeypatch.setenv(key, value)
            monkeypatch.setenv(key.lower(), value + "-lower")
            assert server._get_env_anycase(key) == client_helper(key)
            monkeypatch.delenv(key.lower())
            assert server._get_env_anycase(key) == client_helper(key)
