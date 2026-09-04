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

## Before committing

```sh
pytest tests/ -v
```

All unit tests must pass. Docs-only changes need no test run, but keep
`docker compose config --quiet` green when touching compose files.
