"""Selenium session manager for the console UI.

A small HTTP API (FastAPI) that opens/closes Selenium browser sessions
so the console UI can operate browsers without running pyscraper client
code.

Sessions open via the Grid REST API (``/wd/hub/session``) with an
optional ``pyscraper:node`` stereotype, keep the session id server-side,
and close deletes the Grid session.

Endpoints (all JSON):

* ``POST /api/selenium/sessions`` {browser, node?, url?}
* ``GET /api/selenium/sessions`` / ``DELETE /api/selenium/sessions/{id}``
* ``GET /openapi.json`` / ``GET /docs`` (auto-generated API reference)

Browsers are fixed names: ``selenium-chrome`` / ``selenium-firefox``. The
request field is ``browser`` (renamed from ``target`` in v2.0.0; ``target``
is no longer accepted).

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
* ``SELENIUM_NODE_CHROME_OPTIONS`` (default unset: legacy behavior; JSON
  object mapping node name to ``{"args": [...], "excludeSwitches": [...]}``
  injected as ``goog:chromeOptions`` for ``selenium-chrome`` sessions on
  that node only)
* ``SELENIUM_NODE_FIREFOX_OPTIONS`` (default unset: legacy behavior; JSON
  object mapping node name to ``{"args": [...], "prefs": {...}}``
  injected as ``moz:firefoxOptions`` for ``selenium-firefox`` sessions on
  that node only)

No authentication (closed compose network, local dev use only).
"""

import json
import math
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

# Node name pattern shared with the console registry (console/generate.jq).
_NODE_NAME_RE = re.compile(r"^[A-Za-z0-9._-]+$")

# Browser-driven proxy must never touch Grid control traffic (session
# create/maximize/navigate/close): urllib honours HTTP(S)_PROXY env by
# default, so Grid calls go through a proxy-bypassing opener. This mirrors
# servers/playwright_node.py::_proxy_bypass_opener for Hub registration.
_NO_PROXY_OPENER = urllib.request.build_opener(urllib.request.ProxyHandler({}))


def _fail(message):
    """Abort startup with a clear error for invalid node options."""
    print(
        f"[selenium-session-manager] invalid node options: {message}", file=sys.stderr, flush=True
    )
    raise SystemExit(1)


def _parse_str_list(value, where, prefix=None):
    """Validate a list of non-empty strings, optionally sharing a prefix."""
    if not isinstance(value, list):
        _fail(f"{where} must be a list of strings")
    seen = set()
    result = []
    for item in value:
        if not isinstance(item, str) or not item.strip():
            _fail(f"{where} must be a list of non-empty strings")
        # Never echo the entry value: it may carry proxy credentials.
        if prefix is not None and not item.startswith(prefix):
            _fail(f"{where} entry must start with {prefix!r}")
        if item not in seen:
            seen.add(item)
            result.append(item)
    return result


def _parse_prefs(value, where):
    """Validate a Firefox prefs mapping (finite primitives only)."""
    if not isinstance(value, dict):
        _fail(f"{where} must be a mapping")
    result = {}
    for key, item in value.items():
        if not isinstance(key, str) or not key.strip():
            _fail(f"{where} keys must be non-empty strings")
        if isinstance(item, bool):
            pass
        elif isinstance(item, int):
            pass
        elif isinstance(item, float):
            if not math.isfinite(item):
                _fail(f"{where} floats must be finite")
        elif not isinstance(item, str):
            _fail(f"{where} values must be a string, number, or boolean")
        result[key] = item
    return result


def _parse_node_options(env_name, allowed_keys, arg_prefix):
    """Parse a node -> launch options JSON mapping env var.

    Returns ``{}`` when unset/blank (legacy behavior). Any structural
    problem aborts startup via ``SystemExit`` instead of silently
    falling back, so a typo never runs with half-applied flags.
    """
    raw = os.environ.get(env_name, "")
    if not raw.strip():
        return {}

    def _reject_constant(token):
        _fail(f"{env_name} must not contain {token}")

    try:
        parsed = json.loads(raw, parse_constant=_reject_constant)
    except ValueError as exc:
        _fail(f"{env_name} is not valid JSON: {exc}")
    if not isinstance(parsed, dict):
        _fail(f"{env_name} must be a JSON object mapping node name to options")
    result = {}
    for node, options in parsed.items():
        where = f"{env_name}[{node!r}]"
        if not isinstance(node, str) or not node.strip() or not _NODE_NAME_RE.fullmatch(node):
            _fail(f"{env_name} keys must match ^[A-Za-z0-9._-]+$ (got {node!r})")
        if not isinstance(options, dict):
            _fail(f"{where} must be a mapping")
        unknown = sorted(set(options) - set(allowed_keys))
        if unknown:
            _fail(
                f"{where} has unknown keys: {', '.join(unknown)} "
                f"(allowed: {', '.join(allowed_keys)})"
            )
        entry = {}
        if "args" in allowed_keys:
            args = _parse_str_list(options.get("args", []), f"{where}.args", arg_prefix)
            for arg in args:
                if arg == "--user-data-dir" or arg.startswith("--user-data-dir="):
                    _fail(
                        f"{where}.args must not set --user-data-dir "
                        "(fixed profiles are owned by the node volume and routing)"
                    )
                # -profile takes a path and -P takes a profile name; both
                # (-profile= and -P= forms included) would escape the fixed
                # profile. The check also runs for Chrome maps (harmless:
                # Chrome has no -profile flag) to keep one shared code path.
                if arg in ("-profile", "-P", "--profile") or arg.startswith(
                    ("-profile=", "-P=", "--profile=")
                ):
                    _fail(
                        f"{where}.args must not select a profile "
                        "(fixed profiles are owned by the node volume and routing)"
                    )
            entry["args"] = args
        if "excludeSwitches" in allowed_keys:
            entry["excludeSwitches"] = _parse_str_list(
                options.get("excludeSwitches", []), f"{where}.excludeSwitches"
            )
        if "prefs" in allowed_keys:
            entry["prefs"] = _parse_prefs(options.get("prefs", {}), f"{where}.prefs")
        if not any(entry.values()):
            continue
        result[node] = entry
    return result


NODE_CHROME_OPTIONS = _parse_node_options(
    "SELENIUM_NODE_CHROME_OPTIONS", ("args", "excludeSwitches"), "--"
)
NODE_FIREFOX_OPTIONS = _parse_node_options("SELENIUM_NODE_FIREFOX_OPTIONS", ("args", "prefs"), "-")


SELENIUM_BROWSERS = {
    "selenium-chrome": "chrome",
    "selenium-firefox": "firefox",
}


_se_sessions = {}  # id -> {"browser", "node", "session_id"}
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

    browser: Literal["selenium-chrome", "selenium-firefox"]
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


def _chrome_options_for(node):
    """Return the configured goog:chromeOptions for a node, or None."""
    if not node:
        return None
    entry = NODE_CHROME_OPTIONS.get(node)
    if not entry:
        return None
    options = {}
    if entry.get("args"):
        options["args"] = list(entry["args"])
    if entry.get("excludeSwitches"):
        options["excludeSwitches"] = list(entry["excludeSwitches"])
    return options or None


def _firefox_options_for(node):
    """Return the configured moz:firefoxOptions for a node, or None."""
    if not node:
        return None
    entry = NODE_FIREFOX_OPTIONS.get(node)
    if not entry:
        return None
    options = {}
    if entry.get("args"):
        options["args"] = list(entry["args"])
    if entry.get("prefs"):
        options["prefs"] = dict(entry["prefs"])
    return options or None


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
        with _NO_PROXY_OPENER.open(request, timeout=REQUEST_TIMEOUT) as resp:
            # Grid status/session replies are small JSON; cap the read so
            # a rogue endpoint cannot OOM us. Truncation surfaces as a
            # json error below, i.e. a 502 like any other Grid failure.
            return json.loads(resp.read(GRID_READ_CAP) or b"{}")

    @classmethod
    def open(cls, browser, node=None, url=None):
        browser_name = SELENIUM_BROWSERS[browser]
        capabilities = {"browserName": browser_name}
        if node:
            capabilities["pyscraper:node"] = node
        if browser == "selenium-chrome":
            chrome_options = _chrome_options_for(node)
            if chrome_options:
                capabilities["goog:chromeOptions"] = chrome_options
        elif browser == "selenium-firefox":
            firefox_options = _firefox_options_for(node)
            if firefox_options:
                capabilities["moz:firefoxOptions"] = firefox_options
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
            # Fill the node desktop so noVNC shows a full window: the Grid
            # session opens at the driver default size otherwise. Best
            # effort: some drivers reject maximize (e.g. WM-less setups),
            # and the session is still usable unmaximized, so a failure
            # only warns instead of aborting the open.
            # NOTE: an empty JSON object, not an empty body: the Grid
            # rejects body-less parameterless commands with 400.
            cls._request("POST", f"/session/{session_id}/window/maximize", {})
        except Exception as exc:  # noqa: BLE001 -- log, keep the session
            print(
                f"[selenium-session-manager] maximize {session_id!r} failed: {exc!r} "
                "(continuing unmaximized)",
                file=sys.stderr,
                flush=True,
            )
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
        return {"browser": browser, "node": node, "session_id": session_id}

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
                "browser": s.get("browser") if isinstance(s, dict) else None,
                "node": s.get("node") if isinstance(s, dict) else None,
            }
            for sid, s in _se_sessions.items()
        ]
    return {"sessions": sessions}


@app.post("/api/selenium/sessions")
def open_session(body: OpenRequest):
    try:
        session = _SeleniumBackend.open(body.browser, node=body.node, url=body.url)
    except Exception as exc:
        print(f"[selenium-session-manager] open failed: {exc!r}", file=sys.stderr, flush=True)
        return JSONResponse({"detail": str(exc)}, status_code=502)
    sid = uuid.uuid4().hex[:12]
    with _LOCK:
        _se_sessions[sid] = session
    return {
        "id": sid,
        "browser": body.browser,
        "node": body.node,
        "url": body.url,
    }


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
