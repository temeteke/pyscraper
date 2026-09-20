# Architecture

Module responsibilities and key design decisions for PyScraper.
No line numbers, test counts, or coverage figures are listed here;
they rot after refactors. Use `pytest --collect-only -q` for the
current test inventory.

## Module responsibilities

```text
pyscraper/__init__.py      Public API (exports main classes)
pyscraper/webpage.py       Abstract WebPage base, parser mixin, element class
pyscraper/webpage_requests.py  requests-based backend
pyscraper/webpage_curl.py      curl-based backend
pyscraper/webpage_selenium.py  Selenium backend (Firefox/Chrome)
pyscraper/webpage_playwright.py Playwright backend (Chromium/Firefox/WebKit)
pyscraper/webfile.py       File downloads (range, progress, file I/O)
pyscraper/hlsfile.py       HLS playlists, segments, FFmpeg merging
pyscraper/requests.py      HTTP session/header management mixin
pyscraper/utils.py         CachedGenerator, LazyList, URL helpers
pyscraper/constants.py     Shared constants
```

### WebPage family

`WebPage` is the abstract base class (HTML fetching/parsing contract,
XPath/CSS selectors). Each backend subclasses it:

- `WebPageRequests` (`RequestsMixin`, `WebPage`) - plain HTTP via `requests`
- `WebPageCurl` (`WebPage`) - `curl` subprocess for restricted environments
- `WebPageSelenium` (`WebPage`, abstract) - Selenium WebDriver base with
  `profile=` / `node=` / `capabilities=` support; `WebPageFirefox` and
  `WebPageChrome` are thin browser-specific subclasses
- `WebPagePlaywright` (`WebPage`, abstract) - Playwright base with
  `profile=` / `user_data_dir=` (local persistent contexts) / `node=`
  (Hub routing) / `storage_state=` / `context_options=` support;
  `WebPagePlaywrightChromium` / `WebPagePlaywrightFirefox` /
  `WebPagePlaywrightWebKit` are thin browser-specific subclasses.
  Also provides `RequestEntry` / `CaptureSession` for network capture,
  and `save_storage_state()` for client-owned persistence.

All Selenium/Playwright browser classes are context managers; state
validation goes through `_ensure_open()`.

### File handling

- `RequestsMixin` owns the HTTP session, headers, cookies, and proxy handling.
- `WebFile` (`WebFileMixin`, `RequestsMixin`, `FileIOBase`) handles
  downloads with range requests, progress callbacks, and seek support.
- `HlsFile` (`HlsFileMixin`, `RequestsMixin`, `FileIOBase`) reuses the
  `WebFile` machinery for HLS segments (`HlsFileMixin` extends
  `WebFileMixin`); it is not a subclass of `WebFile`.
- `utils.py` provides `CachedGenerator` / `LazyList` for lazy evaluation
  of large element and segment collections.

## Design decisions

### Two-tier test classification

Unit tests (mocked, fast, offline) run by default; integration tests
(real network/browsers, slow) are opt-in via `@pytest.mark.integration`.
Rationale: fast feedback during development with production compatibility
verified before releases. See [testing.md](testing.md).

### Mock everything by default

Autouse fixtures in `tests/conftest.py` mock HTTP, FFmpeg, user-agent
generation, and curl for non-integration tests. Rationale: speed,
offline capability, and reproducibility.

### Grid/Hub routing via capabilities

- Selenium: the client forwards `node=` as the `pyscraper:node` Grid
  capability; nodes declare matching stereotypes so the distributor
  routes sessions to the node hosting the requested persistent profile.
- Playwright: `servers/playwright_hub.py` keeps a node registry and
  relays `launch-server` websocket connections; nodes are stateless and
  interchangeable, persistence is client-owned via `storage_state`, and
  the Hub is fail-closed (unknown requests are rejected, never
  misrouted). Selenium keeps node-owned profiles; the ownership models
  are deliberately separated.
- Rationale: fixed profiles live on specific nodes, so Selenium routing
  must be explicit rather than load-balanced; Playwright sessions are
  disposable, so the Hub stays a simple relay. See [operations.md](operations.md).

### Gateway and session managers

`gateway` (plain `nginx:alpine` + `gateway/` mounts) is the single
browser entry point: tile overview, single-browser views, raw noVNC
subpaths, and `/api/` proxies to the session managers.
`servers/playwright_session_manager.py` (open/close/save via the Hub
relay, one owner thread per session, `storage_state` load/save, plus the
`state-files` listing) and `servers/selenium_session_manager.py`
(open/close via the Grid REST API, no state restore) are
both FastAPI apps (Pydantic validation, `422` on invalid bodies,
auto-generated `/openapi.json` + `/docs`), local build only. The Hub
registry and the node's Python wrapper stay stdlib-only (the node image
also ships Playwright). State files live in the
`session-states` compose volume shared with the host. No auth (closed
compose network, local dev use).

### Trust boundary: closed network, trusted clients

The gateway stack assumes a closed compose network and trusted
clients. Consequences, decided deliberately and not to be re-litigated
in review without new threat information:

- Error details are returned verbatim (`str(exc)` in `{"detail"}`) and
  reflected validation input is Starlette's default (untruncated).
  No fixed-message substitution, no truncation helpers, no body-size
  cap on client requests.
- There is no `?force` escape hatch. Restarting the owning manager
  container only discards the in-memory handle; the Grid session or
  node-side browser is NOT released by that restart and must be cleaned
  up separately (see the recovery note in [operations.md](operations.md)).
- Prior reflection-hardening work (custom 422 handler, `_safe_str`,
  `_truncate_*`, 413 middleware, `?force`) was removed for this
  reason. Future review findings of the form "unbounded reflection"
  should be closed by pointing here unless the trust assumption
  changes.

### Version from Git tags

The version is resolved by setuptools-scm from `vX.Y.Z` tags at build
time and exposed as `pyscraper.__version__`; it is never written to
source files. See [development.md](development.md) for the release
procedure.
