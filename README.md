# PyScraper

PyScraper is a Python library for scraping web content and downloading files. It provides utilities for handling web requests, parsing web pages, and downloading files.

## Features

- Handle web requests with custom headers and cookies
- Parse and extract content from web pages using XPath
- Support for Selenium WebDriver for dynamic web pages
- Download HLS media files and merge segments
- Integration with Docker for easy setup and deployment

## Installation

To install PyScraper, clone the repository and install the dependencies:

```sh
git clone https://github.com/temeteke/pyscraper.git
cd pyscraper
pip install -r requirements.txt
```

## Usage

### WebPage Class

The `WebPage` class is designed to handle web page interactions. It provides methods for parsing HTML content, extracting elements using XPath, and handling cookies and headers.

Example usage:

```python
from pyscraper.webpage import WebPageRequests

web_page = WebPageRequests("https://example.com")
for element in web_page.get("//a"):
    print(element.text)
```

```python
from pyscraper.webpage import WebPageFirefox

with WebPageFirefox("https://example.com") as web_page:
    for element in web_page.get("//a"):
        print(element.text)
```

### WebFile Class

The `WebFile` class is designed to handle file downloads from the web. It supports custom headers and cookies, and provides methods for reading and downloading file content.

Example usage:

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

## Running Tests

To run the tests, use the following command:

```sh
pytest
```

## Docker

You can use Docker to set up the development environment and run the application. The repository includes a `docker-compose.yml` file for easy setup.

To build and run the Docker containers, use the following commands:

```sh
docker compose build
docker compose up
```