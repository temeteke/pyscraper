"""Playwright Hub for pyscraper.

A protocol relay + name registry. Clients connect to the Hub's websocket port
and send the ``x-playwright-launch-options`` header containing a ``node`` key.
The Hub looks the node up in its registry and relays the raw protocol connection
to that node's endpoint:

* Chromium persistent nodes advertise an HTTP CDP endpoint; the Hub resolves it
  to a websocket via ``/json/version`` and relays the Chrome DevTools Protocol.
* Firefox/WebKit (and plain Chromium) nodes advertise a ``ws://`` endpoint from
  Playwright's ``launch-server``; the Hub relays the Playwright protocol.

Either side disconnecting closes the peer (no half-open relays).
"""

import asyncio
import json
import os
import threading
import urllib.error
import urllib.request
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import urlparse

import websockets

PORT = int(os.environ.get("PLAYWRIGHT_HUB_PORT", "4000"))
REG_PORT = PORT + 1
NODES = {}  # name -> {"browser": ..., "profile": ..., "ws_endpoint": ...}
_LOCK = threading.Lock()


def _select_node(options):
    if not options:
        return next(iter(NODES.values()), None)
    name = options.get("node")
    if name:
        return NODES.get(name)
    # No node specified: prefer a node whose browser matches the client
    # request (available via x-playwright-launch-options "browser" header).
    # This avoids silently routing e.g. a Firefox client to a Chromium node
    # when both are registered.
    browser = options.get("browser")
    if browser:
        for node in NODES.values():
            if node.get("browser") == browser:
                return node
        # No matching browser — fall back to any node with a warning so
        # the mismatch is visible in Hub logs rather than silent.
        print(
            f"[hub] warning: no node with browser={browser!r}; "
            f"falling back to {next(iter(NODES), None)!r}",
            flush=True,
        )
    return next(iter(NODES.values()), None)


async def _resolve_ws(ws_endpoint):
    if ws_endpoint.startswith(("ws://", "wss://")):
        return ws_endpoint

    def _fetch():
        with urllib.request.urlopen(
            ws_endpoint.rstrip("/") + "/json/version", timeout=5
        ) as resp:
            return json.loads(resp.read())["webSocketDebuggerUrl"]

    try:
        debugger_ws = await asyncio.to_thread(_fetch)
    except (urllib.error.URLError, ValueError, KeyError):
        return None
    if not debugger_ws:
        return None
    # Chromium reports localhost/0.0.0.0; rewrite to the node's reachable host.
    target = urlparse(debugger_ws)
    return urlparse(ws_endpoint)._replace(
        scheme=target.scheme, path=target.path, query=target.query
    ).geturl()


async def _pipe(src, dst):
    try:
        async for message in src:
            await dst.send(message)
    except websockets.ConnectionClosed:
        pass
    except OSError:
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
        await client_ws.close(1011, "no node available")
        return
    target = await _resolve_ws(node["ws_endpoint"])
    if not target:
        await client_ws.close(1011, "node endpoint unavailable")
        return
    node_ws = await websockets.connect(target)
    try:
        task_client = asyncio.create_task(_pipe(client_ws, node_ws))
        task_node = asyncio.create_task(_pipe(node_ws, client_ws))
        await asyncio.wait(
            {task_client, task_node}, return_when=asyncio.FIRST_COMPLETED
        )
        for task in (task_client, task_node):
            task.cancel()
    finally:
        await node_ws.close()
        await client_ws.close()


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

    def do_GET(self):
        if self.path == "/health":
            self._send_json({"status": "ok"})
        elif self.path == "/nodes":
            with _LOCK:
                self._send_json({"nodes": list(NODES.values())})
        else:
            self._send_json({"error": "not found"}, status=404)

    def do_POST(self):
        length = int(self.headers.get("Content-Length", "0"))
        payload = json.loads(self.rfile.read(length) or b"{}")
        if self.path == "/register":
            with _LOCK:
                NODES[payload.get("name")] = {
                    "browser": payload.get("browser"),
                    "profile": payload.get("profile"),
                    "ws_endpoint": payload.get("ws_endpoint"),
                }
            print(f"[hub] registered node {payload.get('name')}", flush=True)
            self._send_json({"status": "ok"})
        elif self.path == "/unregister":
            with _LOCK:
                NODES.pop(payload.get("name"), None)
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
