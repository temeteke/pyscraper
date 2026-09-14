"""Playwright session manager for the gateway UI.

A small HTTP API (stdlib only, no web framework) that opens/closes
Playwright browser sessions so the gateway UI can operate browsers
without running pyscraper client code.

Sessions open via the Hub (``ws://`` relay) on a dedicated owner thread
per session (Playwright's sync API is bound to its creating thread),
support ``storage_state`` load/save, and are disposable: close releases
the node-side browser.

Endpoints (all JSON):

* ``GET /api/state-files`` -> ``{"files": [...]}`` (server-side
  ``SESSION_STATE_DIR`` listing for UI dropdowns)
* ``POST /api/playwright/sessions`` {target, node?, url?, storage_state?}
* ``POST /api/playwright/sessions/{id}/save`` {path}
* ``GET /api/playwright/sessions`` / ``DELETE /api/playwright/sessions/{id}``

Targets are fixed names: ``playwright-chromium`` / ``playwright-firefox`` /
``playwright-webkit``.

Environment:

* ``PLAYWRIGHT_SESSION_MANAGER_PORT`` (default ``8081``)
* ``PLAYWRIGHT_HUB_WS`` (default ``ws://playwright-hub:4000/ws``)
* ``SESSION_STATE_DIR`` (default ``/data/sessions``)
* ``PLAYWRIGHT_OPEN_TIMEOUT`` (default ``60``) bounds each open
  phase (Hub ``connect`` and ``page.goto``); the opener waits up to
  ``2 * OPEN_TIMEOUT + 10`` before giving up / ``PLAYWRIGHT_WORKER_TIMEOUT``
  (default ``120``, seconds for close/save worker replies)

No authentication (closed compose network, local dev use only).
"""


import json
import os
import queue
import sys
import threading
import uuid
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import urlparse


def _int_env(name, default):
    """Read an int env var, falling back to default with a warning.

    Duplicated across servers/*: each image COPYs a single file, so no
    shared helper module is used. Non-positive values also fall back
    (timeouts/ports must be positive).
    """
    try:
        result = int(os.environ.get(name, str(default)))
    except ValueError:
        print(f"[playwright-session-manager] invalid {name}, using {default}", flush=True)
        return default
    if result <= 0:
        print(f"[playwright-session-manager] invalid {name}, using {default}", flush=True)
        return default
    return result


PORT = _int_env("PLAYWRIGHT_SESSION_MANAGER_PORT", 8081)
if not 1 <= PORT <= 65535:
    print("[playwright-session-manager] invalid PLAYWRIGHT_SESSION_MANAGER_PORT, using 8081", flush=True)
    PORT = 8081
PLAYWRIGHT_HUB_WS = os.environ.get("PLAYWRIGHT_HUB_WS", "ws://playwright-hub:4000/ws")
STATE_DIR = Path(os.environ.get("SESSION_STATE_DIR", "/data/sessions"))


PLAYWRIGHT_TARGETS = {
    "playwright-chromium": "chromium",
    "playwright-firefox": "firefox",
    "playwright-webkit": "webkit",
}


_pw_sessions = {}  # id -> {"target", "worker", ...}
_LOCK = threading.Lock()


# Maximum wait for worker replies: open covers slow browser startup
# (webkit); close/save covers storage_state writes. Invalid env values
# fall back to defaults with a warning (see _int_env).
WORKER_TIMEOUT = _int_env("PLAYWRIGHT_WORKER_TIMEOUT", 120)
OPEN_TIMEOUT = _int_env("PLAYWRIGHT_OPEN_TIMEOUT", 60)

# Maximum request body accepted by the JSON endpoints (state dicts
# included). Larger payloads are rejected with 413.
MAX_BODY_BYTES = 1 << 20


class _PlaywrightWorker(threading.Thread):
    """Dedicated thread owning one Playwright session.

    Playwright's sync API is bound to its creating thread; operating the
    session from an HTTP worker thread raises "cannot switch to a
    different thread". All playwright calls for a session therefore run
    on this worker via a request queue; HTTP handlers block on the reply.
    """

    def __init__(self, target, node=None, url=None, storage_state=None):
        super().__init__(daemon=True)
        self._args = (target, node, url, storage_state)
        self._requests = queue.Queue()
        self.session = None
        self.error = None
        self.abandoned = False
        self._ready = threading.Event()
        self.start()
        # Open spans two OPEN_TIMEOUT-bounded phases (connect + goto),
        # so wait for both plus headroom before giving up.
        open_wait = 2 * OPEN_TIMEOUT + 10
        if not self._ready.wait(timeout=open_wait):
            self.error = TimeoutError(f"open timed out after {open_wait}s")
            self.abandoned = True

    def run(self):
        try:
            self.session = _PlaywrightBackend.open(*self._args)
        except Exception as exc:  # noqa: BLE001 -- surfaced to the opener
            self.error = exc
        finally:
            self._ready.set()
        if self.session is None:
            return
        # TOCTOU note: the opener may set abandoned concurrently right
        # after the session check above. The window is microscopic (a
        # single attribute read) and the consequence is bounded -- the
        # worker thread stays alive as a daemon until process restart --
        # so no lock is taken here.
        if self.abandoned:
            # The opener already gave up (open timeout): nobody holds the
            # session id, so clean up the late success right away instead
            # of leaking the node-side browser. Best-effort only; close()
            # itself may hang, in which case this daemon thread is left
            # to process restart for reclamation.
            try:
                _PlaywrightBackend.close(self.session)
            except Exception as exc:  # noqa: BLE001 -- nothing left to report to
                print(f"[playwright-session-manager] abandoned cleanup failed: {exc!r}", flush=True)
            finally:
                self.session = None
            return
        while True:
            func, args, reply = self._requests.get()
            if func is None:  # shutdown sentinel after close
                return
            try:
                reply.put((True, func(*args)))
            except Exception as exc:  # noqa: BLE001 -- surfaced to the caller
                reply.put((False, exc))

    def call(self, func, *args):
        reply = queue.Queue(maxsize=1)
        self._requests.put((func, args, reply))
        try:
            ok, result = reply.get(timeout=WORKER_TIMEOUT)
        except queue.Empty:
            raise TimeoutError(f"worker reply timed out after {WORKER_TIMEOUT}s")
        if not ok:
            raise result
        return result

    def save(self, path):
        return self.call(_PlaywrightBackend.save, self.session, path)

    def close(self):
        # Sentinel is sent only on success: a failed close must leave the
        # worker alive so the caller can retry (the entry is kept too).
        self.call(_PlaywrightBackend.close, self.session)
        self._requests.put((None, (), None))


def _state_files():
    if not STATE_DIR.is_dir():
        return []
    return sorted(p.name for p in STATE_DIR.iterdir() if p.is_file())


def _resolve_state_path(value):
    """Resolve a storage_state value to a server-side path or dict.

    Dicts pass through; plain names resolve under STATE_DIR; absolute
    paths are used as-is. Anything escaping STATE_DIR is rejected.
    Non-string, non-dict values are rejected (they would TypeError in
    Path() and surface as 502 instead of 400). Leading/trailing
    whitespace is stripped here so every caller gets the canonical
    form (e.g. "  ../outside.json  " is rejected, not stored padded).
    """
    if value is None or isinstance(value, dict):
        return value
    if not isinstance(value, str):
        raise ValueError(f"path must be a string or dict: {value!r}")
    value = value.strip()
    p = Path(value)
    if not p.is_absolute():
        p = STATE_DIR / p
    try:
        p.resolve().relative_to(STATE_DIR.resolve())
    except ValueError:
        raise ValueError(f"path escapes state dir: {value!r}")
    return str(p)


class _PlaywrightBackend:
    @staticmethod
    def open(target, node=None, url=None, storage_state=None):
        from playwright.sync_api import sync_playwright

        browser_name = PLAYWRIGHT_TARGETS[target]
        options = {"browser": browser_name}
        if node:
            options["node"] = node
        pw = None
        browser = None
        try:
            pw = sync_playwright().start()
            browser_type = getattr(pw, browser_name)
            browser = browser_type.connect(
                PLAYWRIGHT_HUB_WS,
                headers={"x-playwright-launch-options": json.dumps(options)},
                timeout=OPEN_TIMEOUT * 1000,
            )
            kwargs = {}
            resolved = _resolve_state_path(storage_state)
            if resolved is not None:
                kwargs["storage_state"] = resolved
            context = browser.new_context(**kwargs)
            page = context.new_page()
            if url:
                page.goto(url, timeout=OPEN_TIMEOUT * 1000)
        except Exception:
            if browser is not None:
                try:
                    browser.close()
                except Exception as exc:  # noqa: BLE001 -- log, keep original
                    print(f"[playwright-session-manager] browser cleanup failed: {exc!r}", flush=True)
            if pw is not None:
                try:
                    pw.stop()
                except Exception as exc:  # noqa: BLE001 -- log, keep original
                    print(f"[playwright-session-manager] pw cleanup failed: {exc!r}", flush=True)
            raise
        return {"target": target, "browser": browser, "context": context, "page": page, "pw": pw}

    @staticmethod
    def save(session, path):
        resolved = _resolve_state_path(path)
        # Unreachable via HTTP (pre-validated to str), kept for direct callers.
        if isinstance(resolved, dict):
            raise ValueError("save path must be a file path, not a dict")
        Path(resolved).parent.mkdir(parents=True, exist_ok=True)
        return session["context"].storage_state(path=resolved)

    @staticmethod
    def close(session):
        try:
            session["context"].close()
        finally:
            try:
                session["browser"].close()
            finally:
                session["pw"].stop()


class _Handler(BaseHTTPRequestHandler):
    server_version = "PlaywrightSessionManager/1.0"

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
        raw = self.rfile.read(max(length, 0)) or b"{}"
        try:
            return json.loads(raw)
        except (ValueError, json.JSONDecodeError):
            return None

    def _route(self, method):
        parsed = urlparse(self.path)
        parts = [p for p in parsed.path.split("/") if p]
        # ["api", <family>, "sessions", ...]
        if len(parts) >= 3 and parts[0] == "api" and parts[2] == "sessions":
            return method, parts[1], parts[3:]
        if parts == ["api", "state-files"] and method == "GET":
            return method, "state-files", []
        return None, None, None

    def do_GET(self):
        method, family, rest = self._route("GET")
        if family == "state-files":
            self._send_json({"files": _state_files()})
        elif family == "playwright" and not rest:
            with _LOCK:
                self._send_json(
                    {
                        "sessions": [
                            {"id": sid, "target": s["target"]} for sid, s in _pw_sessions.items()
                        ]
                    }
                )
        else:
            self._send_json({"error": "not found"}, status=404)

    def do_POST(self):
        method, family, rest = self._route("POST")
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
        if family == "playwright" and not rest:
            self._open_playwright(payload)
        elif family == "playwright" and len(rest) == 2 and rest[1] == "save":
            self._save_playwright(rest[0], payload)
        else:
            self._send_json({"error": "not found"}, status=404)

    def do_DELETE(self):
        method, family, rest = self._route("DELETE")
        if family == "playwright" and len(rest) == 1:
            with _LOCK:
                entry = _pw_sessions.get(rest[0])
            if entry is None:
                self._send_json({"error": "unknown session"}, status=404)
                return
            try:
                entry["worker"].close()
            except Exception as exc:
                print(f"[playwright-session-manager] close {rest[0]!r} failed: {exc!r}", flush=True)
                self._send_json({"error": str(exc), "retryable": True}, status=502)
                return
            with _LOCK:
                _pw_sessions.pop(rest[0], None)
            self._send_json({"status": "ok"})
        else:
            self._send_json({"error": "not found"}, status=404)


    def _open_playwright(self, payload):
        target = payload.get("target")
        if target not in PLAYWRIGHT_TARGETS:
            self._send_json({"error": f"unknown target: {target!r}"}, status=400)
            return
        node = payload.get("node")
        if node is not None and not (isinstance(node, str) and node.strip()):
            self._send_json({"error": "node must be a non-empty string"}, status=400)
            return
        url = payload.get("url")
        if url is not None and not (isinstance(url, str) and url.strip()):
            self._send_json({"error": "url must be a non-empty string"}, status=400)
            return
        storage_state = payload.get("storage_state")
        if isinstance(storage_state, str) and not storage_state.strip():
            self._send_json({"error": "storage_state must not be empty"}, status=400)
            return
        if isinstance(storage_state, dict) and not storage_state:
            self._send_json({"error": "storage_state must not be empty"}, status=400)
            return
        # Strip first, then validate: Hub lookup is whitespace-insensitive
        # and the backend must receive the canonical form. _resolve_state_path
        # strips internally, so strip here too for the pre-validation call.
        if isinstance(node, str):
            node = node.strip()
        if isinstance(url, str):
            url = url.strip()
        if isinstance(storage_state, str):
            storage_state = storage_state.strip()
        # Validate storage_state up front so path errors are 400, not a
        # worker-thread failure surfaced as 502.
        try:
            _resolve_state_path(storage_state)
        except ValueError as exc:
            self._send_json({"error": str(exc)}, status=400)
            return
        try:
            worker = _PlaywrightWorker(
                target,
                node=node,
                url=url,
                storage_state=storage_state,
            )
        except Exception as exc:
            self._send_json({"error": str(exc)}, status=502)
            return
        if worker.error is not None:
            self._send_json({"error": str(worker.error)}, status=502)
            return
        sid = uuid.uuid4().hex[:12]
        with _LOCK:
            _pw_sessions[sid] = {"target": target, "worker": worker}
        self._send_json({"id": sid, "target": target, "url": url})


    def _save_playwright(self, sid, payload):
        with _LOCK:
            entry = _pw_sessions.get(sid)
        if entry is None:
            self._send_json({"error": "unknown session"}, status=404)
            return
        path = payload.get("path")
        if not isinstance(path, str) or not path.strip():
            self._send_json({"error": "path is required"}, status=400)
            return
        path = path.strip()
        try:
            resolved = _resolve_state_path(path)
        except ValueError as exc:
            self._send_json({"error": str(exc)}, status=400)
            return
        try:
            state = entry["worker"].save(resolved)
        except Exception as exc:
            self._send_json({"error": str(exc)}, status=502)
            return
        self._send_json({"id": sid, "path": resolved, "state": state})


    def log_message(self, fmt, *args):
        sys.stderr.write(f"[playwright-session-manager] {fmt % args}\n")


def main():
    STATE_DIR.mkdir(parents=True, exist_ok=True)
    server = ThreadingHTTPServer(("0.0.0.0", PORT), _Handler)
    print(f"[playwright-session-manager] listening on :{PORT} (state dir: {STATE_DIR})", flush=True)
    server.serve_forever()


if __name__ == "__main__":
    main()

