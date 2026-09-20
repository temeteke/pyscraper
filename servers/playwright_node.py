"""Playwright node server for pyscraper.

A stateless node: runs Playwright's ``launch-server`` (``ws://``) for any
browser (chromium/firefox/webkit) and advertises itself to the Hub. Nodes
are disposable and equivalent -- they hold no persistent profile. Session
persistence lives on the client via ``storage_state``.

Environment:

* ``PLAYWRIGHT_BROWSER`` (default ``chromium``)
* ``PLAYWRIGHT_PORT`` (default ``3000``)
* ``PLAYWRIGHT_NODE_NAME`` (default ``<browser>-node``)
* ``PLAYWRIGHT_ADVERTISE_HOST`` (default ``PLAYWRIGHT_NODE_NAME``)
* ``PLAYWRIGHT_HUB_URL`` (registry base URL; empty disables registration)
"""

import json
import os
import select
import subprocess
import sys
import tempfile
import time
import urllib.error
import urllib.request
from urllib.parse import urlparse, urlunparse

BROWSER = os.environ.get("PLAYWRIGHT_BROWSER", "chromium")

# How long to wait for launch-server to print its WS endpoint before
# giving up (a silent launch-server would otherwise hang node boot
# forever in a readline loop).
LAUNCH_WAIT_TIMEOUT = 60


def _int_env(name, default):
    """Read an int env var, failing fast with an explicit error.

    Ports must be valid TCP ports (1-65535).
    """
    try:
        result = int(os.environ.get(name, str(default)))
    except ValueError:
        raise SystemExit(f"[node] invalid {name}: must be an integer")
    if not 1 <= result <= 65535:
        raise SystemExit(f"[node] invalid {name}: must be 1-65535")
    return result


PORT = _int_env("PLAYWRIGHT_PORT", 3000)
NODE_NAME = os.environ.get("PLAYWRIGHT_NODE_NAME", f"{BROWSER}-node")
ADVERTISE_HOST = os.environ.get("PLAYWRIGHT_ADVERTISE_HOST", NODE_NAME)
HUB_URL = os.environ.get("PLAYWRIGHT_HUB_URL")


def _get_env_anycase(name):
    """Read environment variable with lowercase priority.

    Keep in sync with pyscraper/webpage.py::_get_env_anycase. Duplicated
    here so the node image needs only playwright (no pyscraper install).
    """
    lower = name.lower()
    return os.environ.get(lower, os.environ.get(name))


def _proxy_bypass_opener():
    """Build a urllib opener that bypasses the proxy for Hub registration.

    The opener disables proxies entirely (internal node <-> Hub traffic
    must never egress), so no NO_PROXY bookkeeping is needed here.
    """
    return urllib.request.build_opener(urllib.request.ProxyHandler({}))


def _post(path, payload, retries=5):
    if not HUB_URL:
        return
    request = urllib.request.Request(
        HUB_URL.rstrip("/") + path,
        data=json.dumps(payload).encode(),
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    opener = _proxy_bypass_opener()
    for attempt in range(retries):
        try:
            opener.open(request, timeout=5)
            return
        except urllib.error.URLError as exc:  # pragma: no cover - network best-effort
            if attempt == retries - 1:
                print(
                    f"[node] hub {path} failed after {retries} attempts: {exc!r}",
                    file=sys.stderr,
                    flush=True,
                )
            else:
                time.sleep(1 * (attempt + 1))


def _register(ws_endpoint):
    _post(
        "/register",
        {
            "name": NODE_NAME,
            "browser": BROWSER,
            "ws_endpoint": ws_endpoint,
        },
    )


def _unregister():
    _post("/unregister", {"name": NODE_NAME})


def _launch_config():
    """Build the launch-server --config JSON.

    Runs headed (``headless: False``) under Xvfb so noVNC can observe the
    browser. Proxy env (HTTPS_PROXY preferred, NO_PROXY as bypass) is
    reflected so node-side fetches use the same egress as client contexts.
    """
    config = {"port": PORT, "host": "0.0.0.0", "headless": False}
    if BROWSER == "chromium":
        config["args"] = ["--disable-blink-features=AutomationControlled"]
        config["ignoreDefaultArgs"] = ["--enable-automation"]
    server = _get_env_anycase("HTTPS_PROXY") or _get_env_anycase("HTTP_PROXY")
    bypass = _get_env_anycase("NO_PROXY")
    if server:
        proxy = {"server": server}
        if bypass:
            proxy["bypass"] = bypass
        config["proxy"] = proxy
    return config


def _rewrite_endpoint(reported):
    """Rewrite a launch-server endpoint to the advertised host.

    Handles both ``WS_ENDPOINT=<ws://...>`` lines and bare ``ws://`` lines.
    Falls back to the node PORT when the reported endpoint has no port.
    ADVERTISE_HOST is a compose service name (hostname only, not a
    literal IPv6 address).
    """
    reported = reported.strip()
    if reported.startswith("WS_ENDPOINT="):
        reported = reported.split("=", 1)[1].strip()
    parsed = urlparse(reported)
    if parsed.scheme not in ("ws", "wss"):
        raise ValueError(f"unexpected endpoint scheme: {reported!r}")
    try:
        port = parsed.port or PORT
    except ValueError:
        raise ValueError(f"invalid endpoint port: {reported!r}")
    return urlunparse(parsed._replace(netloc=f"{ADVERTISE_HOST}:{port}"))


def _plain_node():
    """Run Playwright's built-in launch-server (stateless remote browser).

    playwright 1.62 supports --config <json> for launch-server options (port, etc.);
    the config file must outlive the parent's file handle so the child can read
    it, hence mkstemp + atexit cleanup.
    """
    import atexit

    fd, config_path = tempfile.mkstemp(suffix=".json")
    try:
        with os.fdopen(fd, "w") as f:
            json.dump(_launch_config(), f)
    except BaseException:
        try:
            os.unlink(config_path)
        except OSError:
            pass
        raise
    atexit.register(lambda: os.path.exists(config_path) and os.unlink(config_path))
    cmd = [
        sys.executable,
        "-m",
        "playwright",
        "launch-server",
        "--browser",
        BROWSER,
        "--config",
        config_path,
    ]
    proc = subprocess.Popen(
        cmd,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
    )
    ws_endpoint = None
    try:
        deadline = time.monotonic() + LAUNCH_WAIT_TIMEOUT
        while ws_endpoint is None:
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                break
            ready, _, _ = select.select([proc.stdout], [], [], remaining)
            if not ready:
                break
            chunk = proc.stdout.readline()
            if not chunk:
                break  # EOF: launch-server exited without reporting
            print(f"[node] {chunk}", flush=True, end="")
            stripped = chunk.strip()
            if stripped.startswith(("WS_ENDPOINT=", "ws://")):
                ws_endpoint = _rewrite_endpoint(stripped)
    finally:
        if ws_endpoint is None:
            proc.terminate()
            try:
                proc.wait(timeout=5)
            except subprocess.TimeoutExpired:
                proc.kill()
            try:
                proc.stdout.close()
            except (OSError, ValueError):
                pass
            try:
                os.unlink(config_path)
            except OSError:
                pass
            raise RuntimeError("launch-server did not report WS_ENDPOINT")
    # config file is no longer needed after launch-server has started
    try:
        os.unlink(config_path)
    except OSError:
        pass
    _register(ws_endpoint)
    try:
        proc.wait()
    finally:
        _unregister()


def main():
    _plain_node()


if __name__ == "__main__":
    main()
