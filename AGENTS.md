# Agent Guide for PyScraper

PyScraper is a Python library for web scraping and file downloading with support for
HTTP requests (`requests`), browser automation (Selenium, Playwright), `curl`, and
HLS video downloads.

## Iron rules

1. **Unit tests are the default.** Run `pytest tests/` (fast, offline, mocked).
   Integration tests (`-m integration`) need network/browsers and are opt-in.
2. **Never hardcode test counts, line counts, or coverage numbers in docs.**
   They rot. Point at `pytest --collect-only -q` instead.
3. **Never hardcode file line numbers in docs.** They rot after refactors.
4. **Check `tests/conftest.py` before touching mocks.** Autouse fixtures mock
   HTTP/FFmpeg/user-agent/curl unless the test is marked `integration`.
5. **Use `@pytest.mark.integration` for network-dependent tests.**
6. **Keep docs in English.** Do not mix in other languages.

## Pointers

- **Testing strategy**: `docs/testing.md`
- **Grid/Hub operation, Docker images**: `docs/operations.md`
- **Setup, TDD flow, release**: `docs/development.md`
- **Module responsibilities, design decisions**: `docs/architecture.md`
- **Mock infrastructure**: `tests/conftest.py`
- **Pytest config/markers**: `pyproject.toml`

## Common commands

```sh
pytest tests/                    # unit only (default)
pytest tests/ -m integration -v  # integration only
pytest tests/ -m "" -v           # all
pytest tests/test_webfile.py -v  # single file
pytest --collect-only -q         # test inventory
docker compose config --quiet    # validate compose files
```

## Environment variables

- `INTEGRATION_TEST=1` - Force integration tests (alternative to `-m integration`)
- `SELENIUM_FIREFOX_URL`, `SELENIUM_CHROME_URL` - Selenium Grid URLs
- `PLAYWRIGHT_CHROMIUM_URL`, `PLAYWRIGHT_FIREFOX_URL`, `PLAYWRIGHT_WEBKIT_URL` - Playwright Hub URLs
- `SELENIUM_FIREFOX_PROFILE`, `SELENIUM_CHROME_PROFILE` - Legacy profile dirs (prefer `profile=`)
- `HTTP_PROXY`, `HTTPS_PROXY`, `NO_PROXY` - Proxy configuration

## Playwright v2 model (breaking since v2.0.0)

- Nodes are stateless `launch-server` workers (single `Dockerfile.playwright-node`
  + `PLAYWRIGHT_BROWSER` build-arg); no CDP, no node-owned profiles.
- Persistence is client-owned: `storage_state=` / `save_storage_state()`
  (all browsers). Selenium keeps node-owned profiles (`node=` routes to the
  profile host); never mix the two ownership models.
- Hub is fail-closed: missing/invalid/unknown launch headers are rejected
  (`1011 "no node available"`), never routed to another browser.
- Gateway at `http://localhost:8080/` (plain `nginx:alpine` +
  `gateway/` mounts, no dedicated image): `/` tile overview plus
  `/view.html?browser=<target>` single views, raw noVNC at `/playwright-chromium/`,
  `/playwright-firefox/`, `/playwright-webkit/` (Playwright) plus
  `/selenium-chrome/`, `/selenium-firefox/` (Selenium nodes), and `/api/`
  proxied to the session managers (`playwright-session-manager` on :8081
  for sessions/save/state-files, `selenium-session-manager` on :8082 for
  sessions; both local build only).
- `playwright` client/node protocol pinned in `setup.cfg`,
  `Dockerfile.playwright-node`, and `Dockerfile.playwright-session-manager`;
  keep in sync. The Hub's `websockets>=12.0,<14.0` pin lives in
  `Dockerfile.playwright-hub` and in the `setup.cfg` `gateway` extra
  (used by the Hub tests); keep the two in sync (legacy websockets API).
- Both session managers are FastAPI apps (Pydantic validation, Starlette
  default `{"detail": ...}` errors, auto-generated `/openapi.json` + `/docs`).
  Gateway pins live in `setup.cfg` (`gateway` extra) and both
  session-manager Dockerfiles (`ARG FASTAPI_VERSION` /
  `ARG UVICORN_VERSION`); keep them in sync (no pin test exists, so
  update all three together). `.github/workflows/tests.yml` installs
  `.[gateway]`, so it picks the `setup.cfg` pins up without its own
  literals. Note: `httpx` is test-only and lives in `setup.cfg` alone
  (not shipped in images).

## Before committing

```sh
pytest tests/ -v
```

All unit tests must pass. Docs-only changes need no test run, but keep
`docker compose config --quiet` green when touching compose files.
