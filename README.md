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
gateway, see [Operations Guide](docs/operations.md).

### Downloading files

`WebFile` and `HlsFile` download to temporary paths and only move to the
final `filepath` once the transfer completes. The move uses `shutil.move`, so
it is a rename on the same filesystem and falls back to copy + delete across
filesystems (a failed cross-filesystem copy can leave a partial output file).

| Class | Temporary path | Default |
| --- | --- | --- |
| `WebFile.temp_file` | Partial download | `<filepath>.part` |
| `HlsFile.temp_file` | ffmpeg merge output | `.<filename>` (same directory as the output) |
| `HlsFile.temp_directory` | Segment/playlist scratch directory | `<directory>/<filestem>` |

`WebFile.download()` accepts `temp_file=`; `HlsFile.download()` accepts both
`temp_file=` and `temp_directory=` to override the temporary paths for that
call. Overrides are **local to the call**: they do not mutate the instance, so
`WebFile.temp_file` / `HlsFile.temp_directory` keep returning the defaults.
Relative overrides are resolved against the current working directory (not
`directory`); a `temp_file` parent directory is not created automatically,
while `HlsFile` creates the `temp_directory` (including parents). To clean up a
custom path, pass the same value to `unlink(temp_file=...)` /
`unlink(temp_directory=...)`; `unlink()` with no arguments removes the default
paths. A `temp_directory` that is empty, `.`, `..`, the current working
directory (or one of its ancestors), the filesystem root, the output file
itself, or one of its ancestors is rejected with `ValueError` (it would
otherwise be removed together with the output). Overrides are used literally
(no `~` expansion). Paths are compared as-is: case-sensitive on POSIX and
case-insensitive on Windows; case-insensitive POSIX filesystems (e.g. default
macOS APFS) are not distinguished. `WebFile.tempfile` is a deprecated alias for
`WebFile.temp_file`.

#### Content-Disposition filename resolution

`WebFile.get_filename()` resolves the output name in this order:

1. `filename*` (RFC 5987): `charset'language'percent-encoded`, decoded with the
   declared charset (UTF-8 when the charset is omitted).
2. `filename` (quoted or unquoted; `;`-separated trailing parameters are not
   consumed).
3. The URL basename.

Directory components (both `/` and `\`) are stripped, so `filename="C:\dir\a.mp4"`
yields `a.mp4`. Empty, whitespace-only, `.`, `..`, or values containing control
characters are rejected and fall back to the URL basename, as are malformed
`filename*` values (no `'` charset/language separator) and ones with an invalid
percent-encoding or an undecodable charset. `HlsFile` ignores
`Content-Disposition` (it uses the URL stem plus a fixed `.mp4` suffix).

> **Migrating to v2:** Playwright remote persistence moved from node-owned
> profiles (Chromium-only CDP) to client-owned `storage_state`
> (`storage_state=` / `save_storage_state()`, all browsers). The unimplemented
> `cookies_file` argument and the `node="chromium-profile"` Playwright service
> were removed (unrelated to the Selenium `chromium-profile` stereotype, which
> stays); use `node="chromium"` plus `storage_state` instead. `context_options`
> passes locale/timezone/viewport etc. through to context creation.
> `PLAYWRIGHT_*_URL` must be `ws://` (legacy CDP `http(s)://` is rejected).

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
on a weekly schedule, or manually via `workflow_dispatch`.
See [Operations Guide](docs/operations.md) for the image table, tag
semantics, and `docker compose` usage.

## Documentation

- **[Operations Guide](docs/operations.md)** - Grid/Hub operation and Docker
- **[Testing Guide](docs/testing.md)** - Testing documentation
- **[Development Guide](docs/development.md)** - Development setup and guidelines
- **[Architecture](docs/architecture.md)** - Module responsibilities and design decisions
