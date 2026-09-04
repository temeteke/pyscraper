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
  `profile=` / `user_data_dir=` / `node=` support;
  `WebPagePlaywrightChromium` / `WebPagePlaywrightFirefox` /
  `WebPagePlaywrightWebKit` are thin browser-specific subclasses.
  Also provides `RequestEntry` / `CaptureSession` for network capture.

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
- Playwright: `scripts/playwright_hub.py` keeps a node registry and
  relays websocket connections; Chromium nodes use CDP for persistent
  contexts (Chromium-only Playwright limitation), other browsers use
  ephemeral `launch-server` sessions.
- Rationale: fixed profiles live on specific nodes, so routing must be
  explicit rather than load-balanced. See [operations.md](operations.md).

### Version from Git tags

The version is resolved by setuptools-scm from `vX.Y.Z` tags at build
time and exposed as `pyscraper.__version__`; it is never written to
source files. See [development.md](development.md) for the release
procedure.
