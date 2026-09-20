"""Selenium session manager for the gateway UI.

A small HTTP API (FastAPI) that opens/closes Selenium browser sessions
so the gateway UI can operate browsers without running pyscraper client
code.

Sessions open via the Grid REST API (``/wd/hub/session``) with an
optional ``pyscraper:node`` stereotype, keep the session id server-side,
and close deletes the Grid session.

Endpoints (all JSON):

* ``POST /api/selenium/sessions`` {target, node?, url?}
* ``GET /api/selenium/sessions`` / ``DELETE /api/selenium/sessions/{id}``
* ``GET /openapi.json`` / ``GET /docs`` (auto-generated API reference)

Targets are fixed names: ``selenium-chrome`` / ``selenium-firefox``.

Validation errors are ``422`` with Starlette's default ``{"detail": ...}``
shape; unknown sessions are ``404``; Grid failures are ``502``
(``{"detail": ..., "retryable": true}`` when a close may succeed on
retry). No body-size cap (closed network, trusted clients; see the
trust boundary note in docs/architecture.md). Explicitly handled errors
use the ``{"detail": ...}`` envelope; uncaught exceptions fall back to
Starlette's default plain-text ``500``. A malformed session entry is a
bug, so it returns ``500`` (never retryable).

Environment:

* ``SELENIUM_SESSION_MANAGER_PORT`` (default ``8082``)
* ``SELENIUM_HUB_URL`` (default ``http://selenium-hub:4444/wd/hub``)
* ``SELENIUM_REQUEST_TIMEOUT`` (default ``30``, seconds per Grid call)

No authentication (closed compose network, local dev use only).
"""

import json
import os
import re
import sys
import threading
import urllib.error
import urllib.request
import uuid
from typing import Literal, Optional

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
            f"[selenium-session-manager] invalid {name}, using {default}",
            file=sys.stderr,
            flush=True,
        )
        return default
    if result <= 0:
        print(
            f"[selenium-session-manager] invalid {name}, using {default}",
            file=sys.stderr,
            flush=True,
        )
        return default
    return result


PORT = _int_env("SELENIUM_SESSION_MANAGER_PORT", 8082)
if not 1 <= PORT <= 65535:
    print(
        "[selenium-session-manager] invalid SELENIUM_SESSION_MANAGER_PORT, using 8082",
        file=sys.stderr,
        flush=True,
    )
    PORT = 8082
SELENIUM_HUB_URL = os.environ.get("SELENIUM_HUB_URL", "http://selenium-hub:4444/wd/hub")
# Timeout for every Grid REST round-trip (session create/url/close).
REQUEST_TIMEOUT = _int_env("SELENIUM_REQUEST_TIMEOUT", 30)


SELENIUM_TARGETS = {
    "selenium-chrome": "chrome",
    "selenium-firefox": "firefox",
}


_se_sessions = {}  # id -> {"target", "session_id"}
_LOCK = threading.Lock()

# Cap on Grid response reads: a rogue endpoint must not OOM us.
# (Client body limits were removed; closed network, trusted clients.)
GRID_READ_CAP = 1 << 20


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

    target: Literal["selenium-chrome", "selenium-firefox"]
    node: Optional[str] = None
    url: Optional[str] = None

    @field_validator("node", "url")
    @classmethod
    def _strip_optional(cls, value, info):
        return _nonempty_str(value, info.field_name)


app = FastAPI(title="Selenium session manager")


# Raised only when the Grid reports the session gone (404 / "no such
# session"): the entry is dropped and the caller gets 404. Deliberately
# NOT a KeyError subclass: a malformed entry (missing session_id) must
# surface as a bug (500), never be mistaken for a gone session.
class _GoneFromGrid(Exception):
    pass


class _SeleniumBackend:
    @staticmethod
    def _request(method, path, payload=None):
        data = json.dumps(payload).encode() if payload is not None else None
        request = urllib.request.Request(
            SELENIUM_HUB_URL.rstrip("/") + path,
            data=data,
            headers={"Content-Type": "application/json"},
            method=method,
        )
        with urllib.request.urlopen(request, timeout=REQUEST_TIMEOUT) as resp:
            # Grid status/session replies are small JSON; cap the read so
            # a rogue endpoint cannot OOM us. Truncation surfaces as a
            # json error below, i.e. a 502 like any other Grid failure.
            return json.loads(resp.read(GRID_READ_CAP) or b"{}")

    @classmethod
    def open(cls, target, node=None, url=None):
        browser_name = SELENIUM_TARGETS[target]
        capabilities = {"browserName": browser_name}
        if node:
            capabilities["pyscraper:node"] = node
        created = cls._request("POST", "/session", {"capabilities": {"alwaysMatch": capabilities}})
        # Grid 4.x answers in W3C shape: {"value": {"sessionId": ...}}.
        session_id = created.get("sessionId")
        if not session_id:
            value = created.get("value")
            if isinstance(value, dict):
                session_id = value.get("sessionId")
        if not isinstance(session_id, str) or not re.fullmatch(r"[A-Za-z0-9-]+", session_id):
            print(
                f"[selenium-session-manager] bad sessionId: {created!r}",
                file=sys.stderr,
                flush=True,
            )
            raise RuntimeError(f"Grid did not return a sessionId: {created!r}")
        try:
            if url:
                cls._request("POST", f"/session/{session_id}/url", {"url": url})
        except Exception:
            try:
                cls._request("DELETE", f"/session/{session_id}")
            except Exception as exc:  # noqa: BLE001 -- log, keep original
                print(
                    f"[selenium-session-manager] compensating close failed: {exc!r}",
                    file=sys.stderr,
                    flush=True,
                )
            raise
        return {"target": target, "session_id": session_id}

    @classmethod
    def close(cls, session):
        # close_session pre-validates; a missing id here is a bug, so
        # fail loudly instead of sending a bogus DELETE to the Grid.
        session_id = session.get("session_id") if isinstance(session, dict) else None
        if not isinstance(session_id, str):
            raise RuntimeError("close called with malformed session entry")
        try:
            cls._request("DELETE", f"/session/{session_id}")
        except urllib.error.HTTPError as exc:
            # Grid already forgot the session (restart/eviction): drop the
            # entry instead of keeping a permanently retry-failing handle.
            # The message lives in the response body, not str(exc).
            try:
                body = exc.read().decode(errors="ignore")
            except Exception:
                body = ""
            if exc.code == 404 or "no such session" in (str(exc) + body).lower():
                reason = f"code={exc.code} body={body[:200]!r}"
                gone_id = session.get("session_id") if isinstance(session, dict) else None
                raise _GoneFromGrid(gone_id, reason) from exc
            raise


@app.get("/api/selenium/sessions")
def list_sessions():
    with _LOCK:
        sessions = [
            {
                "id": sid,
                "target": s.get("target") if isinstance(s, dict) else None,
            }
            for sid, s in _se_sessions.items()
        ]
    return {"sessions": sessions}


@app.post("/api/selenium/sessions")
def open_session(body: OpenRequest):
    try:
        session = _SeleniumBackend.open(body.target, node=body.node, url=body.url)
    except Exception as exc:
        print(f"[selenium-session-manager] open failed: {exc!r}", file=sys.stderr, flush=True)
        return JSONResponse({"detail": str(exc)}, status_code=502)
    sid = uuid.uuid4().hex[:12]
    with _LOCK:
        _se_sessions[sid] = session
    return {"id": sid, "target": body.target, "url": body.url}


@app.delete("/api/selenium/sessions/{sid}")
def close_session(sid: str):
    with _LOCK:
        session = _se_sessions.get(sid)
    if session is None:
        return JSONResponse({"detail": "unknown session"}, status_code=404)
    # Pre-validate the entry shape instead of catching KeyError: a
    # malformed entry is a bug (500, not retryable), while Grid
    # internals raising KeyError must stay 502. Non-dict entries,
    # missing session_id, and non-string ids all land here; the id
    # format mirrors the open-time check so close never sends a bogus
    # id to the Grid.
    session_id = session.get("session_id") if isinstance(session, dict) else None
    if not isinstance(session_id, str) or not re.fullmatch(r"[A-Za-z0-9-]+", session_id):
        print(f"[selenium-session-manager] malformed entry {sid!r}", file=sys.stderr, flush=True)
        return JSONResponse({"detail": "malformed session entry"}, status_code=500)
    try:
        _SeleniumBackend.close(session)
    except _GoneFromGrid as exc:
        grid_id = exc.args[0] if exc.args else None
        reason = exc.args[1] if len(exc.args) > 1 else ""
        print(
            f"[selenium-session-manager] session gone {sid!r} (grid {grid_id!r} {reason})",
            file=sys.stderr,
            flush=True,
        )
        with _LOCK:
            _se_sessions.pop(sid, None)
        return JSONResponse({"detail": "session already gone"}, status_code=404)
    except Exception as exc:
        print(
            f"[selenium-session-manager] close {sid!r} failed: {exc!r}",
            file=sys.stderr,
            flush=True,
        )
        return JSONResponse({"detail": str(exc), "retryable": True}, status_code=502)
    with _LOCK:
        _se_sessions.pop(sid, None)
    return {"status": "ok"}


def main():
    import uvicorn

    print(f"[selenium-session-manager] listening on :{PORT}", flush=True)
    uvicorn.run(app, host="0.0.0.0", port=PORT)


if __name__ == "__main__":
    main()
