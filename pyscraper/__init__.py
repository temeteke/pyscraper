from .hlsfile import HlsFile, HlsFileError
from .constants import HEADERS
from .webfile import (
    WebFile,
    WebFileClientError,
    WebFileConnectionError,
    WebFileError,
    WebFileSeekError,
    WebFileServerError,
    WebFileTimeoutError,
)
from .webpage import (
    WebPageError,
    WebPageNoSuchElementError,
    WebPageTimeoutError,
)
from .webpage_curl import WebPageCurl
from .webpage_requests import WebPageRequests
from .webpage_playwright import (
    CaptureSession,
    RequestEntry,
    WebPagePlaywrightChromium,
    WebPagePlaywrightFirefox,
    WebPagePlaywrightWebKit,
)
from .webpage_selenium import WebPageChrome, WebPageFirefox

from importlib.metadata import version, PackageNotFoundError

try:
    __version__ = version("pyscraper")
except PackageNotFoundError:
    __version__ = "unknown"

__all__ = [
    "CaptureSession",
    "RequestEntry",
    "WebPageRequests",
    "WebPageFirefox",
    "WebPageChrome",
    "WebPageCurl",
    "WebPagePlaywrightChromium",
    "WebPagePlaywrightFirefox",
    "WebPagePlaywrightWebKit",
    "WebPageError",
    "WebPageTimeoutError",
    "WebPageNoSuchElementError",
    "WebFile",
    "WebFileError",
    "WebFileConnectionError",
    "WebFileTimeoutError",
    "WebFileClientError",
    "WebFileServerError",
    "WebFileSeekError",
    "HlsFile",
    "HlsFileError",
    "HEADERS",
    "__version__",
]
