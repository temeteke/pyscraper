"""Playwright session manager for the console UI.

A small HTTP API (FastAPI) that opens/closes Playwright browser
sessions so the console UI can operate browsers without running
pyscraper client code.

Sessions open via the Hub (``ws://`` relay) on a dedicated owner thread
per session (Playwright's sync API is bound to its creating thread),
support ``storage_state`` load/save, and are disposable: close releases
the node-side browser.

Endpoints (all JSON):

* ``GET /api/playwright/states`` -> ``{"states": [{"id": ...}]}``
  (``id`` is the stem of a ``SESSION_STATE_DIR/{id}.json`` file)
* ``PUT /api/playwright/states/{id}`` {session_id} -> create/overwrite
  ``SESSION_STATE_DIR/{id}.json`` from that session
* ``DELETE /api/playwright/states/{id}`` -> remove the state file
* ``POST /api/playwright/sessions`` {browser, node?, url?, state_id?,
  context_options?} (``context_options`` mirrors the console registry
  allowlist; ``storage_state`` and ``proxy`` are rejected; when no
  viewport/device_scale_factor/is_mobile is given Chromium opens with
  the native window size (``no_viewport``) and Firefox/WebKit open with
  an explicit reduced-height default viewport (see ``_default_viewport``)
  so a headed browser fills the VNC desktop at any configured size)
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
import re
import stat
import sys
import threading
import uuid
from pathlib import Path
from typing import Literal, Optional

from fastapi import FastAPI
from fastapi.responses import JSONResponse
from pydantic import BaseModel, ConfigDict, Field, field_validator


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
# Absolute so an id resolves to the same file regardless of the process
# cwd; a relative SESSION_STATE_DIR would otherwise be re-applied by the
# backend resolver (STATE_DIR/<id>.json joined to STATE_DIR again).
STATE_DIR = Path(os.environ.get("SESSION_STATE_DIR", "/data/sessions")).absolute()

# State ids are resource names, not file names: they map to
# ``SESSION_STATE_DIR/{id}.json``. The pattern structurally prevents path
# traversal (no separators, no dots), so resolution stays inside STATE_DIR.
STATE_ID_RE = re.compile(r"^[a-z0-9-]+$")


PLAYWRIGHT_BROWSERS = {
    "playwright-chromium": "chromium",
    "playwright-firefox": "firefox",
    "playwright-webkit": "webkit",
}

# Browser chrome heights measured as outer-minus-viewport on the headed
# nodes at 1280x720 (Firefox 1280x805, WebKit 1280x758): both engines
# resize each page window to fit the viewport plus chrome, while launch
# flags only size the startup window (Firefox) or don't exist (WebKit)
# and the no-viewport fallbacks are smaller than the desktop.
_FIREFOX_CHROME_HEIGHT = 85
_WEBKIT_CHROME_HEIGHT = 38


def _screen_size():
    """Desktop geometry shared with the nodes' Xvfb.

    Same names and defaults as the nodes (``PLAYWRIGHT_SCREEN_WIDTH`` /
    ``PLAYWRIGHT_SCREEN_HEIGHT``, default ``1280`` / ``720``); invalid
    values fall back with a warning (manager convention -- the nodes
    fail fast instead). Keep the manager value in sync with the nodes
    (see compose.yaml): a mismatch leaves browser windows smaller or
    larger than the VNC desktop. Read once at import: like the other
    manager settings it applies on restart.
    """
    return (
        _int_env("PLAYWRIGHT_SCREEN_WIDTH", 1280),
        _int_env("PLAYWRIGHT_SCREEN_HEIGHT", 720),
    )


SCREEN_WIDTH, SCREEN_HEIGHT = _screen_size()


def _default_viewport(browser):
    """Viewport that lands the outer window exactly on the desktop.

    Returns None for Chromium (the native window size via ``no_viewport``
    follows any desktop). Firefox/WebKit windows are resized to fit the
    viewport plus browser chrome, so the height is reduced accordingly.
    Degenerate desktops (shorter than the chrome) clamp to 1px, which
    stays schema-valid.
    """
    if browser == "playwright-firefox":
        return {"width": SCREEN_WIDTH, "height": max(SCREEN_HEIGHT - _FIREFOX_CHROME_HEIGHT, 1)}
    if browser == "playwright-webkit":
        return {"width": SCREEN_WIDTH, "height": max(SCREEN_HEIGHT - _WEBKIT_CHROME_HEIGHT, 1)}
    return None


_pw_sessions = {}  # id -> {"browser", "node", "worker"}
_LOCK = threading.Lock()

# Cached fd for STATE_DIR (see _state_dir_fd); None until first use.
_STATE_DIR_FD = None
_STATE_DIR_FD_LOCK = threading.Lock()


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

    def __init__(self, browser, node=None, url=None, storage_state=None, context_options=None):
        super().__init__(daemon=True)
        self._args = (browser, node, url, storage_state, context_options)
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

    def save(self):
        return self.call(_PlaywrightBackend.save, self.session)

    def close(self):
        # Sentinel is sent only on success: a failed close must leave the
        # worker alive so the caller can retry (the entry is kept too).
        self.call(_PlaywrightBackend.close, self.session)
        self._requests.put((None, (), None))


def _state_dir_fd():
    """Open (once) and cache a file descriptor for STATE_DIR.

    Pinning the directory inode means every later ID operation uses
    ``dir_fd``: a rename/symlink swap of STATE_DIR itself cannot redirect
    a read, write, or unlink to another directory.
    """
    global _STATE_DIR_FD
    with _STATE_DIR_FD_LOCK:
        if _STATE_DIR_FD is None:
            _STATE_DIR_FD = os.open(STATE_DIR, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
        return _STATE_DIR_FD


def _state_ids():
    """List manageable state ids (``.json`` stems matching STATE_ID_RE).

    Only canonical ids are advertised: a legacy file with an
    unmanageable name (spaces, uppercase) or a symlink cannot be
    addressed through the id API, so it must not appear in the listing.
    """
    if not STATE_DIR.is_dir():
        return []
    return sorted(
        p.stem
        for p in STATE_DIR.iterdir()
        if p.is_file()
        and not p.is_symlink()
        and p.suffix == ".json"
        and len(p.stem) <= 63
        and STATE_ID_RE.fullmatch(p.stem)
    )


def _resolve_state_id(value):
    """Resolve a state id to its absolute ``SESSION_STATE_DIR/{id}.json``.

    The id is validated verbatim (no whitespace normalization): a padded
    or newline-bearing value is a malformed id. Raises ``ValueError`` for
    anything that is not a canonical id, and for a symlink: the id API
    only manages regular files, so a link can never redirect a read or a
    write outside the state dir (a symlink swap is then a hard error, not
    a boundary escape).
    """
    if not isinstance(value, str) or not STATE_ID_RE.fullmatch(value):
        raise ValueError(f"invalid state id: {value!r} (want ^[a-z0-9-]+$)")
    if len(value) > 63:
        raise ValueError(f"state id too long: {value!r} (max 63)")
    path = STATE_DIR / f"{value}.json"
    if path.is_symlink():
        raise ValueError(f"state id is a symlink: {value!r}")
    return path


def _read_state_id(path):
    """Read a state file as a JSON object, pinned to the state dir.

    The name is opened relative to the cached dir fd with ``O_NOFOLLOW``
    and the descriptor is ``fstat``-checked to be a regular file, so a
    symlink swap or a FIFO cannot redirect or block the read. The result
    must be a JSON object (dict); anything else is rejected so the caller
    never silently opens a context without the requested state.
    """
    fd = os.open(
        path.name,
        os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK,
        dir_fd=_state_dir_fd(),
    )
    try:
        if not stat.S_ISREG(os.fstat(fd).st_mode):
            raise ValueError(f"state is not a regular file: {path.name!r}")
    except BaseException:
        os.close(fd)
        raise
    with os.fdopen(fd, "r", encoding="utf-8") as handle:
        state = json.load(handle)
    if not isinstance(state, dict):
        raise ValueError(f"state must be a JSON object: {path.name!r}")
    return state


def _write_state_id(path, state):
    """Atomically write ``state`` to ``path`` under the pinned state dir.

    A sibling temp file is created with the target's existing mode (or the
    umask default for a new file) and ``os.replace``d into place, so the
    write is atomic, never follows a symlink, and preserves permissions.
    """
    dir_fd = _state_dir_fd()
    name = path.name
    mode = 0o666
    try:
        existing = os.stat(name, dir_fd=dir_fd, follow_symlinks=False)
    except FileNotFoundError:
        pass
    else:
        if stat.S_ISREG(existing.st_mode):
            mode = stat.S_IMODE(existing.st_mode)
    tmp = f".state-{uuid.uuid4().hex}.tmp"
    fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_EXCL, mode, dir_fd=dir_fd)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            json.dump(state, handle)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(tmp, name, src_dir_fd=dir_fd, dst_dir_fd=dir_fd)
    except BaseException:
        try:
            os.unlink(tmp, dir_fd=dir_fd)
        except OSError:
            pass
        raise
    try:
        os.fsync(dir_fd)
    except OSError:
        pass


def _delete_state_id(path):
    """Remove a regular state file under the pinned state dir.

    A symlink or other non-regular entry is rejected (``ValueError``); a
    missing file raises ``FileNotFoundError``.
    """
    dir_fd = _state_dir_fd()
    existing = os.stat(path.name, dir_fd=dir_fd, follow_symlinks=False)
    if not stat.S_ISREG(existing.st_mode):
        raise ValueError(f"state is not a regular file: {path.name!r}")
    os.unlink(path.name, dir_fd=dir_fd)


def _collect_state(sid):
    """Return session ``sid``'s storage state dict, or a ``JSONResponse``.

    The dict is produced on the session's owner thread; the caller writes
    it, so the filesystem operation is not tied to that thread.
    """
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
    if not callable(getattr(worker, "save", None)):
        print(f"[playwright-session-manager] malformed entry {sid!r}", file=sys.stderr, flush=True)
        return JSONResponse({"detail": "malformed session entry"}, status_code=500)
    try:
        return worker.save()
    except Exception as exc:
        print(
            f"[playwright-session-manager] save {sid!r} failed: {exc!r}",
            file=sys.stderr,
            flush=True,
        )
        return JSONResponse({"detail": str(exc)}, status_code=502)


class _PlaywrightBackend:
    @staticmethod
    def open(browser, node=None, url=None, storage_state=None, context_options=None):
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
            kwargs = dict(context_options or {})
            if storage_state is not None:
                kwargs["storage_state"] = storage_state
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
    def save(session):
        # Collect the state dict on the owner thread; the caller persists it
        # (atomic, symlink-safe write), so no path is opened here.
        return session["context"].storage_state()

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


class Viewport(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)

    width: int = Field(gt=0)
    height: int = Field(gt=0)


class ContextOptions(BaseModel):
    """Playwright ``new_context`` options accepted from the console UI.

    Mirrors the console registry allowlist (console/generate.jq):
    ``storage_state`` and ``proxy`` are deliberately not context options,
    and unknown keys are rejected (``extra="forbid"``). Strict types keep
    stringly-typed values (``"yes"``, ``"2"``) out.
    """

    model_config = ConfigDict(extra="forbid", strict=True)

    locale: Optional[str] = None
    timezone_id: Optional[str] = None
    viewport: Optional[Viewport] = None
    user_agent: Optional[str] = None
    color_scheme: Optional[Literal["light", "dark", "no-preference"]] = None
    device_scale_factor: Optional[float] = Field(default=None, gt=0)
    has_touch: Optional[bool] = None
    is_mobile: Optional[bool] = None
    extra_http_headers: Optional[dict[str, str]] = None


class OpenRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    browser: Literal["playwright-chromium", "playwright-firefox", "playwright-webkit"]
    node: Optional[str] = None
    url: Optional[str] = None
    # Field constraints mirror _resolve_state_id and surface in the
    # OpenAPI schema (pattern + maxLength) so generated docs match runtime.
    state_id: Optional[str] = Field(default=None, pattern=r"^[a-z0-9-]+$", max_length=63)
    context_options: Optional[ContextOptions] = None

    @field_validator("node", "url")
    @classmethod
    def _strip_optional(cls, value, info):
        return _nonempty_str(value, info.field_name)

    @field_validator("state_id")
    @classmethod
    def _check_state_id(cls, value):
        if value is None:
            return None
        # Validate verbatim: unlike the legacy path fields, an id is not
        # whitespace-normalized, so " a" / "a\n" are malformed (422).
        if not isinstance(value, str) or not STATE_ID_RE.fullmatch(value) or len(value) > 63:
            raise ValueError("invalid state_id (want ^[a-z0-9-]+$, max 63)")
        return value


class SaveStateRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    session_id: str

    @field_validator("session_id")
    @classmethod
    def _strip_session_id(cls, value):
        if not isinstance(value, str) or not value.strip():
            raise ValueError("session_id is required")
        return value.strip()


app = FastAPI(title="Playwright session manager")


@app.get("/api/playwright/states")
def list_states():
    return {"states": [{"id": state_id} for state_id in _state_ids()]}


@app.put("/api/playwright/states/{state_id:path}")
def put_state(state_id: str, body: SaveStateRequest):
    try:
        path = _resolve_state_id(state_id)
    except ValueError as exc:
        return JSONResponse({"detail": str(exc)}, status_code=422)
    state = _collect_state(body.session_id)
    if isinstance(state, JSONResponse):
        return state
    try:
        _write_state_id(path, state)
    except OSError as exc:
        print(
            f"[playwright-session-manager] write state {state_id!r} failed: {exc!r}",
            file=sys.stderr,
            flush=True,
        )
        return JSONResponse({"detail": str(exc)}, status_code=502)
    return {"id": state_id, "session_id": body.session_id}


@app.delete("/api/playwright/states/{state_id:path}")
def delete_state(state_id: str):
    try:
        path = _resolve_state_id(state_id)
    except ValueError as exc:
        return JSONResponse({"detail": str(exc)}, status_code=422)
    try:
        _delete_state_id(path)
    except FileNotFoundError:
        return JSONResponse({"detail": "unknown state"}, status_code=404)
    except ValueError as exc:
        return JSONResponse({"detail": str(exc)}, status_code=422)
    except OSError as exc:
        print(
            f"[playwright-session-manager] delete state {state_id!r} failed: {exc!r}",
            file=sys.stderr,
            flush=True,
        )
        return JSONResponse({"detail": str(exc)}, status_code=502)
    return {"status": "ok"}


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
    if body.state_id is not None:
        # Resolve the id and read the state ourselves (pinned dir fd,
        # O_NOFOLLOW, fstat-checked) and hand Playwright a dict: the path
        # is never re-opened later, so a concurrent symlink swap cannot
        # redirect the read and a non-object file is rejected.
        try:
            path = _resolve_state_id(body.state_id)
        except ValueError as exc:
            # The field validator already enforces this; keep the 422
            # contract even if the two definitions ever drift.
            return JSONResponse({"detail": str(exc)}, status_code=422)
        try:
            storage_state = _read_state_id(path)
        except FileNotFoundError:
            return JSONResponse({"detail": "unknown state"}, status_code=404)
        except (OSError, ValueError) as exc:
            return JSONResponse({"detail": f"invalid state file: {exc}"}, status_code=422)
    else:
        storage_state = None
    resolved_options = (
        body.context_options.model_dump(exclude_none=True)
        if body.context_options is not None
        else {}
    )
    if not any(
        key in resolved_options for key in ("viewport", "device_scale_factor", "is_mobile")
    ):
        # The injection is only valid without viewport/
        # device_scale_factor/is_mobile (the server rejects those
        # combinations), so an explicitly emulated session keeps the
        # legacy behavior.
        if body.browser == "playwright-chromium":
            # Native window size: without this Playwright applies its 720p
            # default viewport and resizes the headed window to fit it
            # (1288x805 on Linux), leaving the rest of the VNC desktop black.
            resolved_options["no_viewport"] = True
        else:
            # Firefox/WebKit windows are resized to fit the viewport plus
            # browser chrome (see _default_viewport): an explicit
            # reduced-height viewport lands the outer window exactly on
            # the desktop at any configured size.
            resolved_options["viewport"] = _default_viewport(body.browser)
    try:
        worker = _PlaywrightWorker(
            body.browser,
            node=body.node,
            url=body.url,
            storage_state=storage_state,
            context_options=resolved_options,
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
