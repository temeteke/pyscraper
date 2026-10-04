from importlib.metadata import PackageNotFoundError, version

from .constants import HEADERS
from .errors import PyscraperError
from .hlsfile import HlsFile, HlsFileError
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
    WebPageBrowserError,
    WebPageClickInterceptedError,
    WebPageConnectionError,
    WebPageError,
    WebPageNoSuchElementError,
    WebPageStaleElementReferenceError,
    WebPageTimeoutError,
    WebPageWebDriverError,
)
from .webpage_curl import WebPageCurl
from .webpage_playwright import (
    CaptureSession,
    RequestEntry,
    WebPagePlaywrightChromium,
    WebPagePlaywrightFirefox,
    WebPagePlaywrightWebKit,
)
from .webpage_requests import WebPageRequests
from .webpage_selenium import (
    WebPageChrome,
    WebPageFirefox,
    WebPageSeleniumChrome,
    WebPageSeleniumFirefox,
)

try:
    __version__ = version("pyscraper")
except PackageNotFoundError:
    __version__ = "unknown"

__all__ = [
    "CaptureSession",
    "RequestEntry",
    "WebPageRequests",
    "WebPageSeleniumFirefox",
    "WebPageSeleniumChrome",
    "WebPageFirefox",
    "WebPageChrome",
    "WebPageCurl",
    "WebPagePlaywrightChromium",
    "WebPagePlaywrightFirefox",
    "WebPagePlaywrightWebKit",
    "WebPageError",
    "WebPageTimeoutError",
    "WebPageNoSuchElementError",
    "WebPageClickInterceptedError",
    "WebPageStaleElementReferenceError",
    "WebPageBrowserError",
    "WebPageWebDriverError",
    "WebPageConnectionError",
    "PyscraperError",
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
