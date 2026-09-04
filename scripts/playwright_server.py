"""Playwright node server for pyscraper.

A node owns a single browser profile and advertises itself to the Hub. The
client selects a node by name via the ``node`` argument; the Hub routes the
connection. The profile directory is owned by the node, so the client never
sends a path -- it only names the node.

Two browser backends:

* Chromium -- always serves the Chrome DevTools Protocol (CDP) so a remote
  client can attach with ``connect_over_cdp`` and reuse the default context
  (``browser.contexts[0]``). When ``PLAYWRIGHT_PROFILE`` is set the context is
  persistent (cookies/storage survive across sessions); otherwise an ephemeral
  temp directory is used (non-persistent but fully usable).
* Firefox / WebKit -- run Playwright's built-in ``launch-server`` which serves a
  throwaway remote browser over a websocket (no persistent profile over the
  remote protocol for these browsers).
"""

import asyncio
import json
import os
import subprocess
import sys
import tempfile
import urllib.error
import urllib.request
from urllib.parse import urlparse, urlunparse

import playwright.async_api as pw_async

BROWSER = os.environ.get("PLAYWRIGHT_BROWSER", "chromium")
PORT = int(os.environ.get("PLAYWRIGHT_PORT", "3000"))
CDP_PORT = int(os.environ.get("PLAYWRIGHT_CDP_PORT", "3001"))
NODE_NAME = os.environ.get("PLAYWRIGHT_NODE_NAME", f"{BROWSER}-node")
PROFILE = os.environ.get("PLAYWRIGHT_PROFILE")
ADVERTISE_HOST = os.environ.get("PLAYWRIGHT_ADVERTISE_HOST", NODE_NAME)
HUB_URL = os.environ.get("PLAYWRIGHT_HUB_URL")


def _post(path, payload, retries=5):
    if not HUB_URL:
        return
    request = urllib.request.Request(
        HUB_URL.rstrip("/") + path,
        data=json.dumps(payload).encode(),
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    for attempt in range(retries):
        try:
            urllib.request.urlopen(request, timeout=5)
            return
        except urllib.error.URLError as exc:  # pragma: no cover - network best-effort
            if attempt == retries - 1:
                print(f"[node] hub {path} failed after {retries} attempts: {exc}", flush=True)
            else:
                import time

                time.sleep(1 * (attempt + 1))


def _register(ws_endpoint):
    _post(
        "/register",
        {
            "name": NODE_NAME,
            "browser": BROWSER,
            "profile": PROFILE,
            "ws_endpoint": ws_endpoint,
        },
    )


def _unregister():
    _post("/unregister", {"name": NODE_NAME})


def _plain_node():
    """Run Playwright's built-in launch-server (non-persistent remote browser).

    playwright 1.62 supports --config <json> for launch-server options (port, etc.);
    the config file must outlive the parent's file handle so the child can read
    it, hence mkstemp + atexit cleanup.
    """
    import atexit

    fd, config_path = tempfile.mkstemp(suffix=".json")
    try:
        with os.fdopen(fd, "w") as f:
            json.dump({"port": PORT}, f)
    except BaseException:
        try:
            os.unlink(config_path)
        except OSError:
            pass
        raise
    atexit.register(lambda: os.path.exists(config_path) and os.unlink(config_path))
    cmd = [sys.executable, "-m", "playwright", "launch-server", "--browser", BROWSER, "--config", config_path]
    proc = subprocess.Popen(
        cmd,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
    )
    ws_endpoint = None
    try:
        for line in proc.stdout:
            print(f"[node] {line}", flush=True, end="")
            if line.startswith("WS_ENDPOINT="):
                reported = line.strip().split("=", 1)[1]
                parsed = urlparse(reported)
                ws_endpoint = urlunparse(
                    parsed._replace(netloc=f"{ADVERTISE_HOST}:{parsed.port}")
                )
                break
    finally:
        if ws_endpoint is None:
            proc.terminate()
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


async def _chromium_node(p):
    """Launch a (persistent or ephemeral) Chromium context and expose it over CDP."""
    user_data_dir = PROFILE or tempfile.mkdtemp(prefix="pw-profile-")
    context = await p.chromium.launch_persistent_context(
        user_data_dir=user_data_dir,
        headless=True,
        args=[
            "--remote-debugging-address=0.0.0.0",
            f"--remote-debugging-port={CDP_PORT}",
        ],
    )
    cdp_url = f"http://{ADVERTISE_HOST}:{CDP_PORT}"
    kind = "persistent" if PROFILE else "ephemeral"
    print(
        f"[node] chromium {kind} context ready (profile={user_data_dir}, cdp={cdp_url})",
        flush=True,
    )
    _register(cdp_url)
    try:
        while True:
            await asyncio.sleep(3600)
    finally:
        _unregister()
        await context.close()


async def main():
    if BROWSER == "chromium":
        async with pw_async.async_playwright() as p:
            await _chromium_node(p)
    else:
        _plain_node()


if __name__ == "__main__":
    asyncio.run(main())
