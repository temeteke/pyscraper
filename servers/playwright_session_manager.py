"""Playwright session manager for the gateway UI.

A small HTTP API (FastAPI) that opens/closes Playwright browser
sessions so the gateway UI can operate browsers without running
pyscraper client code.

Sessions open via the Hub (``ws://`` relay) on a dedicated owner thread
per session (Playwright's sync API is bound to its creating thread),
support ``storage_state`` load/save, and are disposable: close releases
the node-side browser.

Endpoints (all JSON):

* ``GET /api/playwright/state-files`` -> ``{"state_files": [...]}``
  (server-side ``SESSION_STATE_DIR`` listing for UI dropdowns)
* ``POST /api/playwright/sessions`` {browser, node?, url?, storage_state?}
* ``POST /api/playwright/sessions/{id}/save`` {path}
* ``GET /api/playwright/sessions`` / ``DELETE /api/playwright/sessions/{id}``
* ``GET /openapi.json`` / ``GET /docs`` (auto-generated API reference)

Browsers are fixed names: ``playwright-chromium`` / ``playwright-firefox`` /
``playwright-webkit``. The request field is ``browser`` (renamed from
``target`` in v2.0.0; ``target`` is no longer accepted).

Validation errors are ``422`` with Starlette's default ``{"detail": ...}``
shape; unknown sessions are ``404``; worker/Hub failures are ``502``
(``{"detail": ..., "retryable": true}`` when a close may succeed on
retry). No body-size cap (closed network, trusted clients; see the
trust boundary note in docs/architecture.md). Explicitly handled errors
use the ``{"detail": ...}`` envelope; uncaught exceptions fall back to
Starlette's default plain-text ``500``. A malformed session entry is a
bug, so it returns ``500`` (never retryable). The Hub registry
is stdlib with its own ``{"error": ...}`` shape and is out of scope.

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
from pathlib import Path
from typing import Literal, Optional, Union

from fastapi import FastAPI
from fastapi.responses import JSONResponse
from pydantic import BaseModel, ConfigDict, field_validator


def _int_env(name, default):
    """Read an int env var, falling back to default with a warning.

    Duplicated across servers/*: each image COPYs a single file, so no
    shared helper module is used. Non-positive values also fall back
    (timeouts/ports must be positive).
    """
    try:
        result = int(os.environ.get(name, str(default)))
    except ValueError:
        print(
            f"[playwright-session-manager] invalid {name}, using {default}",
            file=sys.stderr,
            flush=True,
        )
        return default
    if result <= 0:
        print(
            f"[playwright-session-manager] invalid {name}, using {default}",
            file=sys.stderr,
            flush=True,
        )
        return default
    return result


PORT = _int_env("PLAYWRIGHT_SESSION_MANAGER_PORT", 8081)
if not 1 <= PORT <= 65535:
    print(
        "[playwright-session-manager] invalid PLAYWRIGHT_SESSION_MANAGER_PORT, using 8081",
        file=sys.stderr,
        flush=True,
    )
    PORT = 8081
PLAYWRIGHT_HUB_WS = os.environ.get("PLAYWRIGHT_HUB_WS", "ws://playwright-hub:4000/ws")
STATE_DIR = Path(os.environ.get("SESSION_STATE_DIR", "/data/sessions"))


PLAYWRIGHT_BROWSERS = {
    "playwright-chromium": "chromium",
    "playwright-firefox": "firefox",
    "playwright-webkit": "webkit",
}


_pw_sessions = {}  # id -> {"browser", "node", "worker"}
_LOCK = threading.Lock()


# Maximum wait for worker replies: open covers slow browser startup
# (webkit); close/save covers storage_state writes. Invalid env values
# fall back to defaults with a warning (see _int_env).
WORKER_TIMEOUT = _int_env("PLAYWRIGHT_WORKER_TIMEOUT", 120)
OPEN_TIMEOUT = _int_env("PLAYWRIGHT_OPEN_TIMEOUT", 60)


class _PlaywrightWorker(threading.Thread):
    """Dedicated thread owning one Playwright session.

    Playwright's sync API is bound to its creating thread; operating the
    session from an HTTP worker thread raises "cannot switch to a
    different thread". All playwright calls for a session therefore run
    on this worker via a request queue; HTTP handlers block on the reply.
    """

    def __init__(self, browser, node=None, url=None, storage_state=None):
        super().__init__(daemon=True)
        self._args = (browser, node, url, storage_state)
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
                print(
                    f"[playwright-session-manager] abandoned cleanup failed: {exc!r}",
                    file=sys.stderr,
                    flush=True,
                )
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
            raise TimeoutError(f"worker reply timed out after {WORKER_TIMEOUT}s") from None
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
    Path() and surface as 502 instead of 422). Leading/trailing
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
        raise ValueError(f"path escapes state dir: {value!r}") from None
    return str(p)


class _PlaywrightBackend:
    @staticmethod
    def open(browser, node=None, url=None, storage_state=None):
        from playwright.sync_api import sync_playwright

        browser_name = PLAYWRIGHT_BROWSERS[browser]
        options = {"browser": browser_name}
        if node:
            options["node"] = node
        pw = None
        playwright_browser = None
        try:
            pw = sync_playwright().start()
            browser_type = getattr(pw, browser_name)
            playwright_browser = browser_type.connect(
                PLAYWRIGHT_HUB_WS,
                headers={"x-playwright-launch-options": json.dumps(options)},
                timeout=OPEN_TIMEOUT * 1000,
            )
            kwargs = {}
            resolved = _resolve_state_path(storage_state)
            if resolved is not None:
                kwargs["storage_state"] = resolved
            context = playwright_browser.new_context(**kwargs)
            page = context.new_page()
            if url:
                page.goto(url, timeout=OPEN_TIMEOUT * 1000)
        except Exception:
            if playwright_browser is not None:
                try:
                    playwright_browser.close()
                except Exception as exc:  # noqa: BLE001 -- log, keep original
                    print(
                        f"[playwright-session-manager] browser cleanup failed: {exc!r}",
                        file=sys.stderr,
                        flush=True,
                    )
            if pw is not None:
                try:
                    pw.stop()
                except Exception as exc:  # noqa: BLE001 -- log, keep original
                    print(
                        f"[playwright-session-manager] pw cleanup failed: {exc!r}",
                        file=sys.stderr,
                        flush=True,
                    )
            raise
        return {
            "browser": browser,
            "node": node,
            "playwright_browser": playwright_browser,
            "context": context,
            "page": page,
            "pw": pw,
        }

    @staticmethod
    def save(session, path):
        resolved = _resolve_state_path(path)
        Path(resolved).parent.mkdir(parents=True, exist_ok=True)
        return session["context"].storage_state(path=resolved)

    @staticmethod
    def close(session):
        try:
            session["context"].close()
        finally:
            try:
                session["playwright_browser"].close()
            finally:
                session["pw"].stop()


def _nonempty_str(value, field_name):
    """Strip an optional string field, rejecting blank/non-string input.

    Duplicated across servers/*: each image COPYs a single file, so no
    shared helper module is used.
    """
    if value is None:
        return None
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{field_name} must be a non-empty string")
    return value.strip()


class OpenRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    browser: Literal["playwright-chromium", "playwright-firefox", "playwright-webkit"]
    node: Optional[str] = None
    url: Optional[str] = None
    storage_state: Optional[Union[str, dict]] = None

    @field_validator("node", "url")
    @classmethod
    def _strip_optional(cls, value, info):
        return _nonempty_str(value, info.field_name)

    @field_validator("storage_state")
    @classmethod
    def _check_storage_state(cls, value):
        if isinstance(value, str) and not value.strip():
            raise ValueError("storage_state must not be empty")
        if isinstance(value, dict) and not value:
            raise ValueError("storage_state must not be empty")
        # Eager path check so escapes are 422, not a worker-thread
        # failure surfaced as 502.
        _resolve_state_path(value)
        return value.strip() if isinstance(value, str) else value


class SaveRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    path: str

    @field_validator("path")
    @classmethod
    def _strip_path(cls, value):
        if not isinstance(value, str) or not value.strip():
            raise ValueError("path is required")
        return value.strip()


app = FastAPI(title="Playwright session manager")


@app.get("/api/playwright/state-files")
def state_files():
    return {"state_files": _state_files()}


@app.get("/api/playwright/sessions")
def list_sessions():
    with _LOCK:
        sessions = [
            {
                "id": sid,
                "browser": s.get("browser") if isinstance(s, dict) else None,
                "node": s.get("node") if isinstance(s, dict) else None,
            }
            for sid, s in _pw_sessions.items()
        ]
    return {"sessions": sessions}


@app.post("/api/playwright/sessions")
def open_session(body: OpenRequest):
    try:
        worker = _PlaywrightWorker(
            body.browser,
            node=body.node,
            url=body.url,
            storage_state=body.storage_state,
        )
    except Exception as exc:
        print(f"[playwright-session-manager] open failed: {exc!r}", file=sys.stderr, flush=True)
        return JSONResponse({"detail": str(exc)}, status_code=502)
    if worker.error is not None:
        print(
            f"[playwright-session-manager] open failed: {worker.error!r}",
            file=sys.stderr,
            flush=True,
        )
        return JSONResponse({"detail": str(worker.error)}, status_code=502)
    sid = uuid.uuid4().hex[:12]
    with _LOCK:
        _pw_sessions[sid] = {"browser": body.browser, "node": body.node, "worker": worker}
    return {
        "id": sid,
        "browser": body.browser,
        "node": body.node,
        "url": body.url,
    }


@app.post("/api/playwright/sessions/{sid}/save")
def save_session(sid: str, body: SaveRequest):
    with _LOCK:
        entry = _pw_sessions.get(sid)
    if entry is None:
        return JSONResponse({"detail": "unknown session"}, status_code=404)
    try:
        resolved = _resolve_state_path(body.path)
    except ValueError as exc:
        return JSONResponse({"detail": str(exc)}, status_code=422)
    # Pre-validate the entry shape instead of catching KeyError: a
    # malformed entry is a bug (500, not retryable), while worker
    # internals raising KeyError must stay 502. Duck-type the worker so
    # truthy non-workers (str, ...) and non-callables (dict values, ...)
    # land here instead of AttributeError/TypeError.
    worker = entry.get("worker") if isinstance(entry, dict) else None
    if not callable(getattr(worker, "save", None)):
        print(f"[playwright-session-manager] malformed entry {sid!r}", file=sys.stderr, flush=True)
        return JSONResponse({"detail": "malformed session entry"}, status_code=500)
    try:
        state = worker.save(resolved)
    except Exception as exc:
        print(
            f"[playwright-session-manager] save {sid!r} failed: {exc!r}",
            file=sys.stderr,
            flush=True,
        )
        return JSONResponse({"detail": str(exc)}, status_code=502)
    return {"id": sid, "path": resolved, "state": state}


@app.delete("/api/playwright/sessions/{sid}")
def close_session(sid: str):
    with _LOCK:
        entry = _pw_sessions.get(sid)
    if entry is None:
        return JSONResponse({"detail": "unknown session"}, status_code=404)
    # Pre-validate the entry shape instead of catching KeyError: a
    # malformed entry is a bug (500, not retryable), while worker
    # internals raising KeyError must stay 502. Duck-type the worker so
    # truthy non-workers (str, ...) and non-callables (dict values, ...)
    # land here instead of AttributeError/TypeError.
    worker = entry.get("worker") if isinstance(entry, dict) else None
    if not callable(getattr(worker, "close", None)):
        print(f"[playwright-session-manager] malformed entry {sid!r}", file=sys.stderr, flush=True)
        return JSONResponse({"detail": "malformed session entry"}, status_code=500)
    try:
        worker.close()
    except Exception as exc:
        print(
            f"[playwright-session-manager] close {sid!r} failed: {exc!r}",
            file=sys.stderr,
            flush=True,
        )
        return JSONResponse({"detail": str(exc), "retryable": True}, status_code=502)
    with _LOCK:
        _pw_sessions.pop(sid, None)
    return {"status": "ok"}


def main():
    import uvicorn

    STATE_DIR.mkdir(parents=True, exist_ok=True)
    print(
        f"[playwright-session-manager] listening on :{PORT} (state dir: {STATE_DIR})", flush=True
    )
    uvicorn.run(app, host="0.0.0.0", port=PORT)


if __name__ == "__main__":
    main()
