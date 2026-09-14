import contextlib
import json
import logging
import os
import time
import warnings
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


def _resolve_user_data_dir(profile, user_data_dir):
    """Resolve the effective browser profile directory.

    ``profile`` is the canonical argument (mirrors WebPageSelenium);
    ``user_data_dir`` is an alias for it. When both are given, ``profile``
    takes precedence and a warning is emitted.
    """
    if user_data_dir is not None and profile is not None:
        warnings.warn(
            "profile takes precedence over user_data_dir; user_data_dir is ignored",
            UserWarning,
            stacklevel=2,
        )
    return profile if profile is not None else user_data_dir


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
    def __init__(
        self,
        url,
        params: dict | None = None,
        encoding=None,
        profile: str | None = None,
        user_data_dir: str | None = None,
        node: str | None = None,
        storage_state: str | os.PathLike | dict | None = None,
        context_options: dict | None = None,
    ):
        self._playwright = None
        self._browser = None
        self._context = None
        self._page = None
        self._cookies = {}
        self._user_data_dir = _resolve_user_data_dir(profile, user_data_dir)
        self.profile = profile
        self.node = node
        self._storage_state = storage_state
        self._context_options = dict(context_options or {})
        self._persistent = False
        super().__init__(url, params=params, encoding=encoding)

    def _launch_options_header(self) -> dict:
        """Build the ``x-playwright-launch-options`` header for the Hub.

        Includes ``browser`` so the Hub can select a same-browser node when
        ``node`` is not specified, and ``node`` for explicit routing to a
        named node. The Hub is fail-closed: missing or unknown values are
        rejected instead of falling back to another browser.
        """
        options = {"headless": self._headless, "browser": self._browser_name}
        if self.node is not None:
            options["node"] = self.node
        return options

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

    def _configure_no_proxy_for_remote(self, remote_url):
        netloc = urlparse(remote_url).netloc

        for key in ("no_proxy", "NO_PROXY"):
            if current := os.environ.get(key):
                if netloc not in current.split(","):
                    os.environ[key] = current + "," + netloc
            else:
                os.environ[key] = netloc

    def _proxy_settings(self) -> dict:
        # HTTPS_PROXY takes precedence over HTTP_PROXY, matching the original
        # (pre-refactor) precedence in _setup_proxy_context.
        server = _get_env_anycase("HTTPS_PROXY") or _get_env_anycase("HTTP_PROXY")
        bypass = _get_env_anycase("NO_PROXY")
        settings: dict = {}
        if server:
            settings["server"] = server
        if bypass:
            settings["bypass"] = bypass
        return settings

    def _setup_proxy_context(self):
        if self._context is not None:
            return
        kwargs = dict(self._context_options)
        if proxy := self._proxy_settings():
            kwargs["proxy"] = proxy
        if self._storage_state is not None:
            kwargs["storage_state"] = self._storage_state
        self._context = self._browser.new_context(**kwargs)

    def save_storage_state(self, path: str | os.PathLike | None = None) -> dict | None:
        """Save the current browser context's storage state.

        Follows the Playwright convention: when ``path`` is omitted the
        storage state dict is returned; when given, Playwright writes its
        JSON to the path and the dict is still returned. The internal
        context itself is never exposed.
        """
        self._ensure_open()
        return self._context.storage_state(path=path)

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
                cookie_list = [
                    {"name": k, "value": v, "url": self.request_url}
                    for k, v in self._cookies.items()
                ]
                self._context.add_cookies(cookie_list)
                self._page.goto(self.request_url)

            return self
        except Exception as e:
            logger.error(e)
            self.close()
            raise

    def close(self):
        # Ownership model: a local persistent context
        # (launch_persistent_context) owns its browser via context.browser,
        # so browser.close() is redundant after context.close(). For
        # non-persistent local and remote (stateless launch-server) sessions
        # the browser must be closed explicitly to release the node-side
        # browser process.
        if self._context is not None:
            self._context.close()
            self._context = None
        if self._browser is not None and not self._persistent:
            self._browser.close()
            self._browser = None
        self._page = None
        self._persistent = False
        if self._playwright is not None:
            self._playwright.stop()
            self._playwright = None

    def _start_browser(self):
        browser = getattr(self._playwright, self._browser_name)
        if remote_url := os.environ.get(f"PLAYWRIGHT_{self._browser_name.upper()}_URL"):
            if remote_url.startswith(("http://", "https://")):
                raise WebPageError(
                    f"PLAYWRIGHT_{self._browser_name.upper()}_URL must be a ws:// "
                    "launch-server URL (CDP over http/https was removed in v2.0.0)"
                )
            if self._user_data_dir is not None:
                warnings.warn(
                    "user_data_dir is ignored for remote connections; "
                    "use storage_state= for remote persistence",
                    UserWarning,
                    stacklevel=2,
                )
            self._configure_no_proxy_for_remote(remote_url)
            options = self._launch_options_header()
            self._browser = browser.connect(
                remote_url,
                headers={"x-playwright-launch-options": json.dumps(options)},
            )
        elif self._user_data_dir is not None:
            if self._storage_state is not None:
                warnings.warn(
                    "storage_state is ignored for persistent contexts "
                    "(profile/user_data_dir); use save_storage_state instead",
                    UserWarning,
                    stacklevel=2,
                )
            proxy_settings = self._proxy_settings()
            self._context = browser.launch_persistent_context(
                user_data_dir=self._user_data_dir,
                headless=self._headless,
                proxy=proxy_settings or None,
            )
            self._browser = self._context.browser
            self._persistent = True
        else:
            self._browser = browser.launch(headless=self._headless)

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
    _browser_name = "chromium"

    def __init__(
        self,
        url=None,
        params: dict | None = None,
        cookies: dict | None = None,
        headless: bool = True,
        profile: str | None = None,
        user_data_dir: str | None = None,
        node: str | None = None,
        storage_state: str | os.PathLike | dict | None = None,
        context_options: dict | None = None,
    ):
        if not url:
            url = "about:blank"
        super().__init__(
            url,
            params=params,
            profile=profile,
            user_data_dir=user_data_dir,
            node=node,
            storage_state=storage_state,
            context_options=context_options,
        )
        self._cookies = cookies or {}
        self._headless = headless


class WebPagePlaywrightFirefox(WebPagePlaywright):
    _browser_name = "firefox"

    def __init__(
        self,
        url=None,
        params: dict | None = None,
        cookies: dict | None = None,
        headless: bool = True,
        profile: str | None = None,
        user_data_dir: str | None = None,
        node: str | None = None,
        storage_state: str | os.PathLike | dict | None = None,
        context_options: dict | None = None,
    ):
        if not url:
            url = "about:blank"
        super().__init__(
            url,
            params=params,
            profile=profile,
            user_data_dir=user_data_dir,
            node=node,
            storage_state=storage_state,
            context_options=context_options,
        )
        self._cookies = cookies or {}
        self._headless = headless


class WebPagePlaywrightWebKit(WebPagePlaywright):
    _browser_name = "webkit"

    def __init__(
        self,
        url=None,
        params: dict | None = None,
        cookies: dict | None = None,
        headless: bool = True,
        profile: str | None = None,
        user_data_dir: str | None = None,
        node: str | None = None,
        storage_state: str | os.PathLike | dict | None = None,
        context_options: dict | None = None,
    ):
        if not url:
            url = "about:blank"
        super().__init__(
            url,
            params=params,
            profile=profile,
            user_data_dir=user_data_dir,
            node=node,
            storage_state=storage_state,
            context_options=context_options,
        )
        self._cookies = cookies or {}
        self._headless = headless


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
