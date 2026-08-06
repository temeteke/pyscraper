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
`SELENIUM_FIREFOX_URL` / `SELENIUM_CHROME_URL` is set. Any extension
capability can be passed via the `capabilities` argument so that Grid nodes
are matched by their stereotype (e.g., routing to a fixed-profile node):

```python
from pyscraper import WebPageFirefox

with WebPageFirefox(
    "https://example.com",
    capabilities={"profile:name": "fixed-profile"},
) as web_page:
    for element in web_page.get("//a"):
        print(element.text)
```

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
- `capabilities` is ignored during local (non-Grid) execution.

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

To build and run the Docker containers, use the following commands:

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