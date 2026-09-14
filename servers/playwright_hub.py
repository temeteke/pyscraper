"""Playwright Hub for pyscraper.

A launch-server relay + name registry. The Hub is stateless: nodes run
Playwright's ``launch-server`` (``ws://``) as disposable, equivalent workers
with no CDP endpoint and no persistent profile files. The client keeps
persistence via ``storage_state`` instead.

Clients connect to the Hub's websocket port and send the
``x-playwright-launch-options`` header containing ``browser`` (and optionally
``node``). The Hub relays the raw Playwright protocol connection to the
selected node's ``ws://`` endpoint.

Fail-closed routing: a missing header, invalid JSON, an unknown ``node``,
or no node matching the requested ``browser`` closes the connection with
``1011 "no node available"`` instead of silently falling back to another
browser. Either side disconnecting closes the peer (no half-open relays).

Environment:

* ``PLAYWRIGHT_HUB_PORT`` (default ``4000``; registry on ``PORT+1``)
* ``PLAYWRIGHT_NODE_CONNECT_TIMEOUT`` (default ``10``, seconds)
"""

import asyncio
import json
import os
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import urlparse

import websockets


def _int_env(name, default):
    """Read an int env var, falling back to default with a warning.

    Duplicated across servers/*: each image COPYs a single file, so no
    shared helper module is used. Non-positive values also fall back
    (timeouts/ports must be positive).
    """
    try:
        result = int(os.environ.get(name, str(default)))
    except ValueError:
        print(f"[hub] invalid {name}, using {default}", flush=True)
        return default
    if result <= 0:
        print(f"[hub] invalid {name}, using {default}", flush=True)
        return default
    return result


PORT = _int_env("PLAYWRIGHT_HUB_PORT", 4000)
# REG_PORT derives as PORT+1, so cap at 65534 to keep both bindable.
if not 1 <= PORT <= 65534:
    print(f"[hub] invalid PLAYWRIGHT_HUB_PORT, using 4000", flush=True)
    PORT = 4000
REG_PORT = PORT + 1
NODES = {}  # name -> {"browser": ..., "ws_endpoint": ...}
_LOCK = threading.Lock()

# Timeout for the outbound node websocket dial.
NODE_CONNECT_TIMEOUT = _int_env("PLAYWRIGHT_NODE_CONNECT_TIMEOUT", 10)

# Maximum registry request body.
MAX_BODY_BYTES = 1 << 20


def _select_node(options):
    """Select a node, or None when the request must be rejected.

    Priority: explicit ``node`` name first (taken as-is, even if its
    browser differs from the client's -- the name is the explicit routing
    request), then a node whose ``browser`` matches. Anything else
    (missing header, invalid JSON, unknown node, unknown browser) is
    fail-closed: return None so the caller refuses the connection.
    """
    if not isinstance(options, dict):
        return None
    with _LOCK:
        snapshot = dict(NODES)
    name = options.get("node")
    if name is not None:
        if not isinstance(name, str):
            return None
        return snapshot.get(name.strip())
    browser = options.get("browser")
    if not isinstance(browser, str) or not browser.strip():
        return None
    wanted = browser.strip()
    for node in snapshot.values():
        if node.get("browser") == wanted:
            return node
    return None


async def _pipe(src, dst):
    try:
        async for message in src:
            await dst.send(message)
    except Exception:
        pass


async def _relay(client_ws):
    header = client_ws.request_headers.get("x-playwright-launch-options")
    options = None
    if header:
        try:
            options = json.loads(header)
        except (ValueError, json.JSONDecodeError):
            options = None
    node = _select_node(options)
    if not node:
        try:
            await client_ws.close(1011, "no node available")
        except Exception:
            pass
        return
    target = node.get("ws_endpoint")
    if not target or not target.startswith(("ws://", "wss://")):
        try:
            await client_ws.close(1011, "node endpoint unavailable")
        except Exception:
            pass
        return
    node_ws = None
    try:
        node_ws = await websockets.connect(target, open_timeout=NODE_CONNECT_TIMEOUT)
    except Exception as exc:  # noqa: BLE001 -- fail-closed: any dial failure rejects the client
        print(f"[hub] node connect failed ({target!r}): {exc!r}", flush=True)
        try:
            await client_ws.close(1011, "node endpoint unavailable")
        except Exception:
            pass
        return
    try:
        task_client = asyncio.create_task(_pipe(client_ws, node_ws))
        task_node = asyncio.create_task(_pipe(node_ws, client_ws))
        await asyncio.wait({task_client, task_node}, return_when=asyncio.FIRST_COMPLETED)
        for task in (task_client, task_node):
            task.cancel()
    finally:
        for ws in (node_ws, client_ws):
            try:
                await ws.close()
            except Exception:
                pass


async def _ws_main():
    async with websockets.serve(_relay, "0.0.0.0", PORT):
        print(f"[hub] relay listening on :{PORT}", flush=True)
        await asyncio.Future()


class _RegistryHandler(BaseHTTPRequestHandler):
    def _send_json(self, obj, status=200):
        body = json.dumps(obj).encode()
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _read_json(self):
        try:
            length = int(self.headers.get("Content-Length", "0"))
        except (TypeError, ValueError):
            return "bad-length"
        if length < 0:
            return "bad-length"
        if length > MAX_BODY_BYTES:
            return "too-large"
        try:
            return json.loads(self.rfile.read(max(length, 0)) or b"{}")
        except (ValueError, json.JSONDecodeError):
            return None

    def do_GET(self):
        # Normalize the path (strip query/trailing slash) like the
        # session managers do; exact-match on self.path would 404
        # "/health?x=1" or "/nodes/".
        path = urlparse(self.path).path.rstrip("/") or "/"
        if path == "/health":
            self._send_json({"status": "ok"})
        elif path == "/nodes":
            with _LOCK:
                self._send_json(
                    {"nodes": [{"name": k, **v} for k, v in NODES.items()]}
                )
        else:
            self._send_json({"error": "not found"}, status=404)

    def do_POST(self):
        payload = self._read_json()
        if payload == "bad-length":
            self._send_json({"error": "invalid Content-Length"}, status=400)
            return
        if payload == "too-large":
            self._send_json({"error": "request body too large"}, status=413)
            return
        if payload is None or not isinstance(payload, dict):
            self._send_json({"error": "invalid json"}, status=400)
            return
        path = urlparse(self.path).path.rstrip("/") or "/"
        if path == "/register":
            name = payload.get("name")
            browser = payload.get("browser")
            ws_endpoint = payload.get("ws_endpoint")
            if not (isinstance(name, str) and name.strip()) or not (isinstance(browser, str) and browser.strip()):
                self._send_json({"error": "name and browser are required"}, status=400)
                return
            if not isinstance(ws_endpoint, str) or not ws_endpoint.strip().startswith(("ws://", "wss://")):
                self._send_json({"error": "ws_endpoint must be a ws(s) URL"}, status=400)
                return
            name = name.strip()
            browser = browser.strip()
            ws_endpoint = ws_endpoint.strip()
            with _LOCK:
                NODES[name] = {
                    "browser": browser,
                    "ws_endpoint": ws_endpoint,
                }
            print(f"[hub] registered node {name!r}", flush=True)
            self._send_json({"status": "ok"})
        elif path == "/unregister":
            name = payload.get("name")
            if not (isinstance(name, str) and name.strip()):
                self._send_json({"error": "name is required"}, status=400)
                return
            with _LOCK:
                NODES.pop(name.strip(), None)
            self._send_json({"status": "ok"})
        else:
            self._send_json({"error": "not found"}, status=404)

    def log_message(self, *args):  # silence default logging
        pass


def _run_registry():
    server = ThreadingHTTPServer(("0.0.0.0", REG_PORT), _RegistryHandler)
    print(f"[hub] registry listening on :{REG_PORT}", flush=True)
    server.serve_forever()


if __name__ == "__main__":
    threading.Thread(target=_run_registry, daemon=True).start()
    asyncio.run(_ws_main())
