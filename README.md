# PyScraper

PyScraper is a Python library for scraping web content and downloading files. It provides utilities for handling web requests, parsing web pages, and downloading files.

## Features

- Handle web requests with custom headers and cookies
- Parse and extract content from web pages using XPath
- Support for Selenium WebDriver for dynamic web pages
- Download HLS media files and merge segments
- Integration with Docker for easy setup and deployment

## Installation

To install PyScraper:

```sh
pip install pyscraper
```

## Usage

### WebPage Class

The `WebPage` class is designed to handle web page interactions. It provides methods for parsing HTML content, extracting elements using XPath, and handling cookies and headers.

Example usage:

```python
from pyscraper import WebPageRequests

with WebPageRequests("https://example.com") as web_page:
    for element in web_page.get("//a"):
        print(element.text)
```

```python
from pyscraper import WebPageFirefox

with WebPageFirefox("https://example.com") as web_page:
    for element in web_page.get("//a"):
        print(element.text)
```

#### Selenium Grid and Extension Capabilities

`WebPageFirefox` and `WebPageChrome` connect to a Selenium Grid when
`SELENIUM_FIREFOX_URL` / `SELENIUM_CHROME_URL` is set. Use the `node=`
argument to route a session to the Grid node that hosts a persistent
profile (the recommended way for fixed profiles):

```python
from pyscraper import WebPageFirefox

with WebPageFirefox(
    "https://example.com",
    node="firefox-profile",
) as web_page:
    for element in web_page.get("//a"):
        print(element.text)
```

The `node` value is forwarded as the `pyscraper:node` Grid capability so
the distributor routes the session to the matching node stereotype.

Any additional extension capability can also be passed via the
`capabilities` argument for custom Grid stereotypes:

```python
with WebPageFirefox(
    "https://example.com",
    capabilities={"profile:name": "fixed-profile"},
) as web_page:
    ...
```

`node` and `capabilities` are complementary: `node` is a shortcut for
`capabilities={"pyscraper:node": "…"}` and both are merged into the
session request. If both set the same key, `node` wins.

Notes:

- Capability keys that overlap with dedicated arguments/environment
  (`page_load_strategy`, `language`, `profile`) are overridden by those
  settings. Reserved option keys such as `moz:firefoxOptions` and
  `goog:chromeOptions` must not be passed. `proxy` cannot be set via
  `capabilities`; configure it with `HTTP_PROXY`, `HTTPS_PROXY`, `NO_PROXY`
  environment variables. Unsupported capabilities are logged as warnings.
- `profile` selects the browser profile directory (Firefox uses `-profile`,
  Chrome uses `--user-data-dir`). It takes precedence over the legacy
  `SELENIUM_FIREFOX_PROFILE` / `SELENIUM_CHROME_PROFILE` environment
  variables.
- `capabilities` and `node` are ignored during local (non-Grid) execution.

#### Playwright Browser

`WebPagePlaywrightChromium`, `WebPagePlaywrightFirefox`, and
`WebPagePlaywrightWebKit` wrap Playwright. A persistent browser profile is
selected with `profile=` (or its alias `user_data_dir=`); `profile` takes
precedence when both are given. Cookies and storage survive across sessions
because the browser is launched with `launch_persistent_context`.

```python
from pyscraper import WebPagePlaywrightChromium

with WebPagePlaywrightChromium(
    "https://example.com", profile="/path/to/profile"
) as web_page:
    for element in web_page.get("//a"):
        print(element.text)
```

Remote browsers via a Hub (two-port Hub: `4000` = websocket relay,
`4001` = HTTP node registry at `/register`/`/nodes`):

- Set `PLAYWRIGHT_CHROMIUM_URL=ws://playwright-hub:4000/ws` (and the
  `PLAYWRIGHT_FIREFOX_URL` / `PLAYWRIGHT_WEBKIT_URL` equivalents) to connect
  to the Playwright Hub (`scripts/playwright_hub.py`). The `ws` path suffix
  is required; the HTTP registry is on `:4001`. When `PLAYWRIGHT_*_URL` is
  not set the browser is launched locally (no Hub).
- The `node=` argument selects the node that hosts the requested persistent
  profile; the Hub relays the connection to that node. When `node` is not
  given the Hub prefers a node whose `browser` matches the client (so a
  Firefox client is not silently routed to a Chromium node).
- Chromium offers two nodes: `node="chromium"` (ephemeral, non-persistent) and
  `node="chromium-profile"` (persistent, backed by a mounted volume). Both are
  reachable over the Hub.
- **Remote persistent profiles are supported for Chromium only.** Firefox and
  WebKit remote nodes serve a non-persistent browser, so their profiles do not
  survive across sessions. This is a Playwright limitation: reusing a remote
  persistent context relies on `connect_over_cdp`, which is Chromium-only.
  Local `profile=`/`user_data_dir=` persistence works for all three browsers.

### WebFile Class

The `WebFile` class is designed to handle file downloads from the web. It supports custom headers and cookies, and provides methods for reading and downloading file content.

Example usage:

```python
from pyscraper.webfile import WebFile

url = "https://example.com/file.txt"
with WebFile(url) as web_file:
    web_file.read()
```

```python
from pyscraper.webfile import WebFile

url = "https://example.com/file.txt"
web_file = WebFile(url)
web_file.download()
```

### HlsFile Class

The `HlsFile` class is designed to handle HLS (HTTP Live Streaming) media files. It provides methods for downloading and merging HLS segments, and supports custom headers and cookies.

Example usage:

```python
from pyscraper.hlsfile import HlsFile

url = "https://example.com/playlist.m3u8"
hls_file = HlsFile(url)
hls_file.download()
```

## Testing

PyScraper uses pytest with two types of tests:

```sh
# Unit tests only (fast, offline, default)
pytest tests/

# Integration tests (requires network, browsers)
pytest tests/ -m integration -v

# All tests
pytest tests/ -m "" -v
```

For detailed testing documentation, see [docs/testing.md](docs/testing.md).

## Docker

You can use Docker to set up the development environment and run the application. The repository includes a `docker-compose.yml` file for easy setup.

### Quick start (pull prebuilt images)

Prebuilt images are published to Docker Hub and GHCR by
`.github/workflows/docker.yml` on every `vX.Y.Z` tag (e.g. `v1.2.1`), on a
weekly schedule, or manually via `workflow_dispatch` (optional `version`
input, `X.Y.Z` only, e.g. `1.2.1`; empty means the pushed tag, or the latest
release tag otherwise). Always cut tags as `vX.Y.Z`: short forms like `v1.2`
still trigger the workflow but fail the version check. On tag pushes the
pushed tag itself is built, so back-pushing an old tag rebuilds that
version rather than the latest:

| Image | Docker Hub | GHCR |
|-------|------------|------|
| App | `temeteke/pyscraper` | `ghcr.io/temeteke/pyscraper` |
| Standalone | `temeteke/pyscraper-standalone` | `ghcr.io/temeteke/pyscraper-standalone` |
| Playwright Chromium | `temeteke/pyscraper-playwright-chromium` | `ghcr.io/temeteke/pyscraper-playwright-chromium` |
| Playwright Firefox | `temeteke/pyscraper-playwright-firefox` | `ghcr.io/temeteke/pyscraper-playwright-firefox` |
| Playwright WebKit (amd64 only) | `temeteke/pyscraper-playwright-webkit` | `ghcr.io/temeteke/pyscraper-playwright-webkit` |
| Playwright Hub | `temeteke/pyscraper-playwright-hub` | `ghcr.io/temeteke/pyscraper-playwright-hub` |

Each image is tagged `latest`, `X.Y.Z`, `X.Y.Z-YYYYMMDD`, and `X.Y`.
(`X.Y` is auto-derived from the release and cannot be given as a manual
`version` input; only `X.Y.Z` is accepted.)

Tag semantics:

- `latest`, `X.Y.Z`, and `X.Y` are mutable: the weekly schedule rebuilds
  them with the latest base images, so base-image security fixes are picked
  up without cutting a new release. To update base images outside the
  schedule, cut a new `vX.Y.Z` tag (a patch bump is enough, even with no code
  changes) or run the workflow manually.
- `X.Y.Z-YYYYMMDD` is an immutable snapshot of a single build. Use it when
  byte-level reproducibility matters. Note that weekly runs keep appending
  new snapshots, so old ones should be pruned periodically (GHCR retention
  rules or manual Docker Hub cleanup).

Notes:

- `docker-compose.yml` references the Docker Hub images, so no login is
  needed for public pulls. All services declare `image:`, so
  `docker compose pull` followed by `docker compose up -d` (without
  `--build`) runs the whole stack with no local build. `build:` sections
  are kept alongside for local development; note that
  `docker compose build` rebuilds (and retags) the same names locally.
- The WebKit image is `linux/amd64` only (Playwright WebKit has no official
  arm64 Linux support); `docker-compose.yml` pins `platform: linux/amd64`
  for that service.

```sh
# Fastest: pull from registry (no local build)
docker compose pull
docker compose up -d
```

### Build locally

```sh
docker compose build
docker compose up
```

## Documentation

- **[Testing Guide](docs/testing.md)** - Comprehensive testing documentation
- **[Development Guide](docs/development.md)** - Development setup and guidelines
- **[Codebase Analysis](docs/analysis/codebase.md)** - Detailed code analysis
- **[Module Structure](docs/analysis/modules.md)** - Project architecture

## Contributing

Contributions are welcome! Please read the [Development Guide](docs/development.md) for setup instructions and coding standards.