"""Selenium session manager for the gateway UI.

A small HTTP API (stdlib only, no web framework) that opens/closes
Selenium browser sessions so the gateway UI can operate browsers without
running pyscraper client code.

Sessions open via the Grid REST API (``/wd/hub/session``) with an
optional ``pyscraper:node`` stereotype, keep the session id server-side,
and close deletes the Grid session.

Endpoints (all JSON):

* ``POST /api/selenium/sessions`` {target, node?, url?}
* ``GET /api/selenium/sessions`` / ``DELETE /api/selenium/sessions/{id}``

Targets are fixed names: ``selenium-chrome`` / ``selenium-firefox``.

Environment:

* ``SELENIUM_SESSION_MANAGER_PORT`` (default ``8082``)
* ``SELENIUM_HUB_URL`` (default ``http://selenium-hub:4444/wd/hub``)
* ``SELENIUM_REQUEST_TIMEOUT`` (default ``30``, seconds per Grid call)

No authentication (closed compose network, local dev use only).
"""


import json
import os
import sys
import threading
import uuid
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
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
        print(f"[selenium-session-manager] invalid {name}, using {default}", flush=True)
        return default
    if result <= 0:
        print(f"[selenium-session-manager] invalid {name}, using {default}", flush=True)
        return default
    return result


PORT = _int_env("SELENIUM_SESSION_MANAGER_PORT", 8082)
if not 1 <= PORT <= 65535:
    print("[selenium-session-manager] invalid SELENIUM_SESSION_MANAGER_PORT, using 8082", flush=True)
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

# Maximum request body accepted by the JSON endpoints.
MAX_BODY_BYTES = 1 << 20


class _SeleniumBackend:
    @staticmethod
    def _request(method, path, payload=None):
        import urllib.request

        data = json.dumps(payload).encode() if payload is not None else None
        request = urllib.request.Request(
            SELENIUM_HUB_URL.rstrip("/") + path,
            data=data,
            headers={"Content-Type": "application/json"},
            method=method,
        )
        with urllib.request.urlopen(request, timeout=REQUEST_TIMEOUT) as resp:
            return json.loads(resp.read(MAX_BODY_BYTES) or b"{}")

    @classmethod
    def open(cls, target, node=None, url=None):
        import re

        browser_name = SELENIUM_TARGETS[target]
        capabilities = {"browserName": browser_name}
        if node:
            capabilities["pyscraper:node"] = node
        created = cls._request(
            "POST", "/session", {"capabilities": {"alwaysMatch": capabilities}}
        )
        # Grid 4.x answers in W3C shape: {"value": {"sessionId": ...}}.
        session_id = created.get("sessionId")
        if not session_id:
            value = created.get("value")
            if isinstance(value, dict):
                session_id = value.get("sessionId")
        if not isinstance(session_id, str) or not re.fullmatch(r"[A-Za-z0-9-]+", session_id):
            detail = str(created)
            print(f"[selenium-session-manager] bad sessionId: {detail[:2000]!r}", flush=True)
            raise RuntimeError(f"Grid did not return a sessionId: {detail[:500]}")
        try:
            if url:
                cls._request("POST", f"/session/{session_id}/url", {"url": url})
        except Exception:
            try:
                cls._request("DELETE", f"/session/{session_id}")
            except Exception as exc:  # noqa: BLE001 -- log, keep original
                print(f"[selenium-session-manager] compensating close failed: {exc!r}", flush=True)
            raise
        return {"target": target, "session_id": session_id}

    @classmethod
    def close(cls, session):
        import urllib.error

        try:
            cls._request("DELETE", f"/session/{session['session_id']}")
        except urllib.error.HTTPError as exc:
            # Grid already forgot the session (restart/eviction): drop the
            # entry instead of keeping a permanently retry-failing handle.
            # The message lives in the response body, not str(exc).
            try:
                body = exc.read().decode(errors="ignore")
            except Exception:
                body = ""
            if exc.code == 404 or "no such session" in (str(exc) + body).lower():
                raise KeyError(session["session_id"])
            raise


class _Handler(BaseHTTPRequestHandler):
    server_version = "SeleniumSessionManager/1.0"

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
        return None, None, None

    def do_GET(self):
        method, family, rest = self._route("GET")
        if family == "selenium" and not rest:
            with _LOCK:
                self._send_json(
                    {
                        "sessions": [
                            {"id": sid, "target": s["target"]} for sid, s in _se_sessions.items()
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
        if family == "selenium" and not rest:
            self._open_selenium(payload)
        else:
            self._send_json({"error": "not found"}, status=404)

    def do_DELETE(self):
        method, family, rest = self._route("DELETE")
        if family == "selenium" and len(rest) == 1:
            with _LOCK:
                session = _se_sessions.get(rest[0])
            if session is None:
                self._send_json({"error": "unknown session"}, status=404)
                return
            try:
                _SeleniumBackend.close(session)
            except KeyError:
                with _LOCK:
                    _se_sessions.pop(rest[0], None)
                self._send_json({"error": "session already gone"}, status=404)
                return
            except Exception as exc:
                print(f"[selenium-session-manager] close {rest[0]!r} failed: {exc!r}", flush=True)
                self._send_json({"error": str(exc), "retryable": True}, status=502)
                return
            with _LOCK:
                _se_sessions.pop(rest[0], None)
            self._send_json({"status": "ok"})
        else:
            self._send_json({"error": "not found"}, status=404)


    def _open_selenium(self, payload):
        target = payload.get("target")
        if target not in SELENIUM_TARGETS:
            self._send_json({"error": f"unknown target: {target!r}"}, status=400)
            return
        node = payload.get("node")
        if node is not None and not (isinstance(node, str) and node.strip()):
            self._send_json({"error": "node must be a non-empty string"}, status=400)
            return
        url = payload.get("url")
        if url is not None and (not isinstance(url, str) or not url.strip()):
            self._send_json({"error": "url must be a non-empty string"}, status=400)
            return
        # Pass stripped values: the Grid matches stereotypes exactly.
        if isinstance(node, str):
            node = node.strip()
        if isinstance(url, str):
            url = url.strip()
        try:
            session = _SeleniumBackend.open(
                target,
                node=node,
                url=url,
            )
        except Exception as exc:
            self._send_json({"error": str(exc)}, status=502)
            return
        sid = uuid.uuid4().hex[:12]
        with _LOCK:
            _se_sessions[sid] = session
        self._send_json({"id": sid, "target": target, "url": url})


    def log_message(self, fmt, *args):
        sys.stderr.write(f"[selenium-session-manager] {fmt % args}\n")


def main():
    server = ThreadingHTTPServer(("0.0.0.0", PORT), _Handler)
    print(f"[selenium-session-manager] listening on :{PORT}", flush=True)
    server.serve_forever()


if __name__ == "__main__":
    main()

