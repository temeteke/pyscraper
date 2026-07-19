import contextlib
import logging
import os
import time
from abc import ABC
from datetime import datetime
from pathlib import Path
from urllib.parse import parse_qs, urlencode, urlparse, urlunparse
from dataclasses import dataclass

import lxml.html

from pyscraper.webpage import (
    WebPage,
    WebPageElement,
    WebPageError,
    WebPageNoSuchElementError,
    WebPageTimeoutError,
    _get_env_anycase,
)


logger = logging.getLogger(__name__)


@dataclass
class RequestEntry:
    """Record of a single HTTP request and its corresponding response.

    Attributes:
        url: Request URL
        method: HTTP method (GET, POST, etc.)
        status: HTTP status code (None before response is received)
        request_headers: Request headers
        response_headers: Response headers (None before response is received)
        resource_type: Resource type (document, xhr, media, fetch, etc.)
        timestamp: Time the request was captured (epoch seconds)
    """
    url: str
    method: str
    status: int | None
    request_headers: dict
    response_headers: dict | None
    resource_type: str
    timestamp: float


class PlaywrightWebPageElement(WebPageElement):
    def __init__(self, locator, page=None):
        self._locator = locator
        self._page = page

    @property
    def lxml_html(self):
        return lxml.html.fromstring(self.html)

    @property
    def html(self):
        return self._locator.evaluate("el => el.outerHTML")

    @property
    def inner_html(self):
        return self._locator.inner_html()

    @property
    def inner_text(self):
        return self._locator.inner_text()

    def wait(self, xpath, timeout=10):
        self._locator.page.wait_for_selector(f"xpath={xpath}", timeout=timeout * 1000)

    def get(self, xpath, timeout=0):
        if timeout:
            self.wait(xpath, timeout)
        popup_page = self._page or self._locator.page
        locators = self._locator.locator(f"xpath={xpath}").all()
        return [PlaywrightWebPageElement(loc, page=popup_page) for loc in locators]

    def click(self, timeout=0):
        kwargs = {}
        if timeout:
            kwargs["timeout"] = timeout * 1000
        self._locator.click(**kwargs)

    def mouse_over(self):
        self._locator.hover()

    def scroll(self, block="start", inline="nearest"):
        self._locator.scroll_into_view_if_needed()

    @contextlib.contextmanager
    def switch(self):
        handle = self._locator.element_handle()
        frame = handle.content_frame()
        if not frame:
            raise WebPageError("Element is not an iframe")
        original_page = self._page
        self._page = frame
        yield
        self._page = original_page


class WebPagePlaywright(WebPage, ABC):
    def __init__(self, url, params: dict | None = None, encoding=None):
        self._playwright = None
        self._browser = None
        self._context = None
        self._page = None
        self._cookies = {}
        self._cookies_file = None
        super().__init__(url, params=params, encoding=encoding)

    def _ensure_open(self):
        if self._page is None:
            raise WebPageError("Page is not opened yet")

    @property
    def url(self):
        if self._page is None:
            return self.request_url
        return self._page.url

    @url.setter
    def url(self, url):
        self.request_url = url
        if self._page is not None:
            self.close()
            self.open()

    @property
    def html(self):
        self._ensure_open()
        return self._page.content()

    @property
    def cookies(self):
        if self._page is None:
            return self._cookies
        cookies = {}
        for c in self._context.cookies():
            cookies[c["name"]] = c["value"]
        return cookies

    @cookies.setter
    def cookies(self, cookies):
        self._cookies = cookies
        if self._page is not None:
            self.close()
            self.open()

    @property
    def user_agent(self):
        self._ensure_open()
        return self._page.evaluate("navigator.userAgent")

    def wait(self, xpath, timeout=10):
        self._ensure_open()
        self._page.wait_for_selector(f"xpath={xpath}", timeout=timeout * 1000)

    def get(self, xpath, timeout=0):
        self._ensure_open()
        if timeout:
            self.wait(xpath, timeout)
        locators = self._page.locator(f"xpath={xpath}").all()
        return [PlaywrightWebPageElement(loc, page=self._page) for loc in locators]

    def click(self, xpath, timeout=10):
        self._ensure_open()
        try:
            locator = self._page.locator(f"xpath={xpath}")
            locator.click(timeout=timeout * 1000)
        except Exception as e:
            raise WebPageNoSuchElementError from e

    def move_to(self, xpath):
        self._ensure_open()
        self._page.locator(f"xpath={xpath}").hover()

    def switch_to_frame(self, xpath):
        self._ensure_open()
        locator = self._page.locator(f"xpath={xpath}")
        src = locator.get_attribute("src")
        handle = locator.element_handle()
        frame = handle.content_frame()
        if not frame:
            raise WebPageError("Element is not an iframe")
        self._page = frame
        return src

    def go(self, url, params: dict | None = None):
        self._ensure_open()
        if params:
            parsed_url = urlparse(url)
            parsed_qs = parse_qs(parsed_url.query)
            parsed_qs.update(params)
            url = urlunparse(parsed_url._replace(query=urlencode(parsed_qs, doseq=True)))
        self._page.goto(url)

    def forward(self):
        self._ensure_open()
        self._page.go_forward()

    def back(self):
        self._ensure_open()
        self._page.go_back()

    def refresh(self):
        self._ensure_open()
        self._page.reload()

    def execute_script(self, script):
        self._ensure_open()
        return self._page.evaluate(script)

    def execute_async_script(self, script):
        self._ensure_open()
        return self._page.evaluate_async(script)

    def dump(self, filestem=None):
        self._ensure_open()
        if not filestem:
            filestem = datetime.now().strftime("%Y%m%d_%H%M%S")

        filepath = Path(filestem + ".html")
        with filepath.open("w") as f:
            f.write(self.html)
        files = [filepath]

        scroll_height = self._page.evaluate("document.body.scrollHeight")
        viewport = self._page.viewport_size
        inner_height = viewport["height"] if viewport else 0

        scroll = 0
        while scroll < scroll_height:
            self._page.evaluate(f"window.scrollTo(0, {scroll})")
            filepath = Path(filestem + f"_{scroll}.png")
            self._page.screenshot(path=str(filepath))
            files.append(filepath)
            scroll += inner_height

        return files

    def _setup_proxy_context(self):
        proxy_settings = {}
        http_proxy = _get_env_anycase("HTTP_PROXY")
        https_proxy = _get_env_anycase("HTTPS_PROXY")
        no_proxy = _get_env_anycase("NO_PROXY")

        if http_proxy:
            proxy_settings["server"] = http_proxy
        if https_proxy:
            proxy_settings["server"] = https_proxy
        if no_proxy:
            proxy_settings["bypass"] = no_proxy

        if proxy_settings:
            self._context = self._browser.new_context(proxy=proxy_settings)
        else:
            self._context = self._browser.new_context()

    def open(self):
        from playwright.sync_api import sync_playwright

        logger.debug("Getting {}".format(self.request_url))

        try:
            self._playwright = sync_playwright().start()
            self._start_browser()
            self._setup_proxy_context()
            self._page = self._context.new_page()
            self._page.goto(self.request_url)

            if self._cookies:
                cookie_list = [{"name": k, "value": v, "url": self.request_url} for k, v in self._cookies.items()]
                self._context.add_cookies(cookie_list)
                self._page.goto(self.request_url)

            return self
        except Exception as e:
            logger.error(e)
            self.close()
            raise

    def close(self):
        if self._context is not None:
            self._context.close()
            self._context = None
        if self._browser is not None:
            self._browser.close()
            self._browser = None
        if self._playwright is not None:
            self._playwright.stop()
            self._playwright = None

    def _start_browser(self):
        raise NotImplementedError

    def capture(self, filter_url=None):
        """Start a network request capture session.

    Args:
        filter_url: Function that takes a URL and returns True if the request
                   should be captured. If None, all requests are captured.

    Returns:
        A CaptureSession to be used as a context manager.
    """
        return CaptureSession(self, filter_url)


class WebPagePlaywrightChromium(WebPagePlaywright):
    def __init__(
        self, url=None, params: dict | None = None, cookies: dict | None = None, cookies_file=None
    ):
        if not url:
            url = "about:blank"
        super().__init__(url, params=params)
        self._cookies = cookies or {}
        self._cookies_file = cookies_file

    def _start_browser(self):
        if remote_url := os.environ.get("PLAYWRIGHT_CHROMIUM_URL"):
            if remote_url.startswith("http://") or remote_url.startswith("https://"):
                self._browser = self._playwright.chromium.connect_over_cdp(remote_url)
            else:
                self._browser = self._playwright.chromium.connect(remote_url)
        else:
            self._browser = self._playwright.chromium.launch(headless=True)


class WebPagePlaywrightFirefox(WebPagePlaywright):
    def __init__(
        self, url=None, params: dict | None = None, cookies: dict | None = None, cookies_file=None
    ):
        if not url:
            url = "about:blank"
        super().__init__(url, params=params)
        self._cookies = cookies or {}
        self._cookies_file = cookies_file

    def _start_browser(self):
        if remote_url := os.environ.get("PLAYWRIGHT_FIREFOX_URL"):
            if remote_url.startswith("http://") or remote_url.startswith("https://"):
                self._browser = self._playwright.firefox.connect_over_cdp(remote_url)
            else:
                self._browser = self._playwright.firefox.connect(remote_url)
        else:
            self._browser = self._playwright.firefox.launch(headless=True)


class WebPagePlaywrightWebKit(WebPagePlaywright):
    def __init__(
        self, url=None, params: dict | None = None, cookies: dict | None = None, cookies_file=None
    ):
        if not url:
            url = "about:blank"
        super().__init__(url, params=params)
        self._cookies = cookies or {}
        self._cookies_file = cookies_file

    def _start_browser(self):
        if remote_url := os.environ.get("PLAYWRIGHT_WEBKIT_URL"):
            if remote_url.startswith("http://") or remote_url.startswith("https://"):
                self._browser = self._playwright.webkit.connect_over_cdp(remote_url)
            else:
                self._browser = self._playwright.webkit.connect(remote_url)
        else:
            self._browser = self._playwright.webkit.launch(headless=True)


class CaptureSession:
    """Capture network requests from a Playwright page within a scope.

    Use as a context manager. All network requests that occur inside the
    ``with`` block are captured and accessible via ``requests``.

    Call ``stop()`` or exit the ``with`` block to remove event listeners.
    The captured ``requests`` list is preserved after stopping.

    Examples::

        cap = CaptureSession(page)
        with cap:
            page.goto("https://example.com")
        for req in cap.requests:
            print(req.url, req.status)
    """

    def __init__(self, wp, filter_url=None):
        self._wp = wp
        self._filter_url = filter_url
        self.requests: list[RequestEntry] = []
        self._request_map: dict = {}
        self._attached = False
        self._stopped = False

    def _attach(self):
        if self._attached or self._stopped:
            return
        self._attached = True
        page = self._wp._page
        if page is None:
            logger.debug("CaptureSession: page is not opened yet, listeners deferred")
            return
        self._req_handler = self._on_request
        self._res_handler = self._on_response
        page.on("request", self._req_handler)
        page.on("response", self._res_handler)

    def stop(self):
        """Stop capturing and remove event listeners.

        Idempotent — safe to call multiple times.
        The ``requests`` list is preserved after stopping.
        """
        if self._stopped:
            return
        self._stopped = True
        page = self._wp._page
        if page is not None and self._attached:
            req_h = getattr(self, "_req_handler", None)
            res_h = getattr(self, "_res_handler", None)
            if req_h:
                page.remove_listener("request", req_h)
            if res_h:
                page.remove_listener("response", res_h)
        self._request_map.clear()

    def __enter__(self):
        self._attach()
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        self.stop()

    def _on_request(self, request):
        if self._filter_url is not None and not self._filter_url(request.url):
            return
        entry = RequestEntry(
            url=request.url,
            method=request.method,
            status=None,
            request_headers=dict(request.headers),
            response_headers=None,
            resource_type=request.resource_type,
            timestamp=time.time(),
        )
        self.requests.append(entry)
        self._request_map[request] = entry

    def _on_response(self, response):
        entry = self._request_map.pop(response.request, None)
        if entry is None:
            return
        entry.status = response.status
        entry.response_headers = dict(response.headers)
