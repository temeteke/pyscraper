# PyScraper

PyScraper is a Python library for scraping web content and downloading files. It provides utilities for handling web requests, parsing web pages, and downloading files.

## Features

- Handle web requests with custom headers and cookies
- Parse and extract content from web pages using XPath
- Support for Selenium WebDriver for dynamic web pages
- Support for Playwright (Chromium/Firefox/WebKit) for dynamic web pages
- Download HLS media files and merge segments
- Integration with Docker for easy setup and deployment

## Installation

To install PyScraper:

```sh
pip install pyscraper
```

## Usage

```python
from pyscraper import WebPageRequests

with WebPageRequests("https://example.com") as web_page:
    for element in web_page.get("//a"):
        print(element.text)
```

```python
from pyscraper import WebPageSeleniumFirefox

with WebPageSeleniumFirefox("https://example.com") as web_page:
    for element in web_page.get("//a"):
        print(element.text)
```

```python
from pyscraper import WebPagePlaywrightChromium

with WebPagePlaywrightChromium("https://example.com") as web_page:
    for element in web_page.get("//a"):
        print(element.text)
```

For Grid/Hub routing (`node=`), profiles vs `storage_state`, and the browser
console, see [Operations Guide](docs/operations.md).

`WebPageChrome` and `WebPageFirefox` remain available as backward-compatible
aliases of `WebPageSeleniumChrome` and `WebPageSeleniumFirefox`, respectively.

### Downloading files

`WebFile` and `HlsFile` download to a temporary path and move the result to the
final `filepath` when the transfer completes. See the
[Downloading Guide](docs/downloading.md) for temporary path defaults, per-call
overrides, cleanup, and `Content-Disposition` filename resolution.

## Testing

```sh
# Unit tests only (fast, offline, default)
pytest tests/

# Integration tests (requires network, browsers)
pytest tests/ -m integration -v
```

For details, see [Testing Guide](docs/testing.md). To check the current
test inventory, use `pytest --collect-only -q` (test counts are
intentionally not hardcoded in docs).

## Docker

Prebuilt images are published to Docker Hub and GHCR on `vX.Y.Z` tag
pushes (the workflow matches `v[0-9]*`; always cut full `vX.Y.Z` tags),
on a weekly schedule, or manually via `workflow_dispatch`. This includes
the browser console and both session managers, so
`make pull && make up` runs the whole stack from published images
and exposes the browser console through the local Traefik instance.
See [Operations Guide](docs/operations.md) for the image table, tag
semantics, Compose/Traefik usage, and console configuration.

`make up` starts the stack without forcing a rebuild; Compose builds an image
only when it is missing. Run `make build up` after changing source.
`make restart` only restarts existing containers and does not
apply `.env`, Compose, or image changes. Use `make pull` to refresh the published
images.

Run Compose lifecycle targets (`up`, `down`, `restart`, `build`) on the Docker
host. The Dev Container keeps Docker access for reference targets (`ps`,
`ps-all`, `logs`, `config`, `pull`) and integration-test inspection, but
starting or managing the stack from inside the container is not supported.
`guard-host` enforces this for the Make targets. The normal stack and the Dev
Container share the `pyscraper` Compose project, so run one at a time.

Manage an existing Dev Container from the host with `make devcontainer-logs`,
`devcontainer-stop`, `devcontainer-down`, and `devcontainer-config`. `make down`
removes the services in the normal Compose files; the Dev Container `workspace`
can remain. `make devcontainer-down` removes all containers and networks in the
shared project. Close the Dev Container first. Starting it with plain Compose
bypasses Dev Container features and lifecycle commands such as
`postCreateCommand`; use VS Code's **Reopen in Container** /
**Rebuild Container**.

## Documentation

- **[Operations Guide](docs/operations.md)** - Grid/Hub operation and Docker
- **[Testing Guide](docs/testing.md)** - Testing documentation
- **[Development Guide](docs/development.md)** - Development setup and guidelines
- **[Architecture](docs/architecture.md)** - Module responsibilities and design decisions
- **[Downloading Guide](docs/downloading.md)** - Temporary paths, overrides, and filename resolution
- **[Changelog](CHANGELOG.md)** - Release notes and breaking changes
