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
from pyscraper import WebPageFirefox

with WebPageFirefox("https://example.com") as web_page:
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
`docker compose pull && docker compose up -d` runs the whole stack from
published images.
See [Operations Guide](docs/operations.md) for the image table, tag
semantics, `docker compose` usage, and console configuration.

## Documentation

- **[Operations Guide](docs/operations.md)** - Grid/Hub operation and Docker
- **[Testing Guide](docs/testing.md)** - Testing documentation
- **[Development Guide](docs/development.md)** - Development setup and guidelines
- **[Architecture](docs/architecture.md)** - Module responsibilities and design decisions
- **[Downloading Guide](docs/downloading.md)** - Temporary paths, overrides, and filename resolution
- **[Changelog](CHANGELOG.md)** - Release notes and breaking changes
