import contextlib
import functools
import json
import logging
import os
import re
from abc import ABC
from http.client import RemoteDisconnected
from http.cookiejar import MozillaCookieJar
from pathlib import Path
from urllib.parse import urlparse

import lxml.etree
import lxml.html
import selenium.common.exceptions
from retry import retry
from selenium import webdriver
from selenium.webdriver.common import proxy
from selenium.webdriver.common.action_chains import ActionChains
from selenium.webdriver.common.by import By
from selenium.webdriver.support import expected_conditions as EC
from selenium.webdriver.support.ui import WebDriverWait

from pyscraper.webpage import (
    WebPage,
    WebPageBrowserError,
    WebPageClickInterceptedError,
    WebPageElement,
    WebPageError,
    WebPageNoSuchElementError,
    WebPageStaleElementReferenceError,
    WebPageTimeoutError,
    _get_env_anycase,
    configure_no_proxy_for_remote,
    dump_html,
    iter_scroll_positions,
    merge_url_params,
    resolve_profile,
)

logger = logging.getLogger(__name__)


def _normalize_proxy_for_selenium(value):
    if not value:
        return value
    stripped = value.strip()
    if re.match(r"^https?://", stripped):
        result = urlparse(stripped).netloc
        return result
    return stripped


_RESERVED_CAPABILITY_KEYS = frozenset({"moz:firefoxOptions", "goog:chromeOptions", "proxy"})


def _filter_capabilities(capabilities):
    """Return supported capabilities and warn about excluded values.

    ``moz:firefoxOptions`` / ``goog:chromeOptions`` are rebuilt from the
    library's own settings, ``proxy`` is always configured from environment
    variables, and non-JSON values cannot be sent to a remote WebDriver.
    Reserved keys and non-JSON values are excluded from the session request.
    """
    supported = {}
    for key, value in (capabilities or {}).items():
        if key in _RESERVED_CAPABILITY_KEYS:
            logger.warning("Capability key %r is managed by the library and was ignored", key)
            continue
        try:
            json.dumps(value)
        except (TypeError, ValueError) as e:
            logger.warning(
                "Capability %r value is not JSON serializable and was ignored: %s",
                key,
                e,
            )
            continue
        supported[key] = value
    return supported


def _proxy_from_env():
    """Build Firefox's browser proxy before adding the Grid host to no_proxy."""
    http_proxy = _get_env_anycase("HTTP_PROXY")
    https_proxy = _get_env_anycase("HTTPS_PROXY")
    no_proxy = _get_env_anycase("NO_PROXY")

    if http_proxy or https_proxy or no_proxy:
        proxy_dict = {"proxyType": proxy.ProxyType.MANUAL}
        if http_proxy:
            proxy_dict["httpProxy"] = _normalize_proxy_for_selenium(http_proxy)
        if https_proxy:
            proxy_dict["sslProxy"] = _normalize_proxy_for_selenium(https_proxy)
        if no_proxy:
            proxy_dict["noProxy"] = no_proxy.split(",")
    else:
        proxy_dict = {"proxyType": proxy.ProxyType.DIRECT}
    return proxy.Proxy(proxy_dict)


def _translate_webdriver_error(e):
    """Translate a Selenium failure into the matching ``WebPage*`` error."""
    # Order matters: all branches below subclass WebDriverException.
    if isinstance(e, selenium.common.exceptions.NoSuchElementException):
        return WebPageNoSuchElementError(e)
    if isinstance(e, selenium.common.exceptions.TimeoutException):
        return WebPageTimeoutError(e)
    if isinstance(e, selenium.common.exceptions.ElementClickInterceptedException):
        return WebPageClickInterceptedError(e)
    if isinstance(e, selenium.common.exceptions.StaleElementReferenceException):
        return WebPageStaleElementReferenceError(e)
    return WebPageBrowserError(e)


def _wrap_webdriver_errors(func):
    """Decorate a driver operation with ``WebPage*`` translation."""

    @functools.wraps(func)
    def wrapper(self, *args, **kwargs):
        self._ensure_open()
        try:
            return func(self, *args, **kwargs)
        except selenium.common.exceptions.WebDriverException as e:
            raise _translate_webdriver_error(e) from e

    return wrapper


def _wait_until(search_context, condition, timeout):
    """Wait for a Selenium condition, translating automation errors."""
    try:
        return WebDriverWait(search_context, timeout).until(condition)
    except selenium.common.exceptions.TimeoutException as e:
        raise WebPageTimeoutError(e) from e
    except selenium.common.exceptions.WebDriverException as e:
        raise _translate_webdriver_error(e) from e


class SeleniumWebPageElement(WebPageElement):
    def __init__(self, element):
        self.element = element

    @property
    def lxml_html(self):
        try:
            return lxml.html.fromstring(self.html)
        except selenium.common.exceptions.WebDriverException as e:
            raise _translate_webdriver_error(e) from e
        except lxml.etree.ParserError as e:
            raise WebPageError(e) from e

    @property
    def html(self):
        try:
            return self.element.get_attribute("outerHTML")
        except selenium.common.exceptions.WebDriverException as e:
            raise _translate_webdriver_error(e) from e

    @property
    def inner_html(self):
        try:
            return self.element.get_attribute("innerHTML")
        except selenium.common.exceptions.WebDriverException as e:
            raise _translate_webdriver_error(e) from e

    @property
    def inner_text(self):
        try:
            return self.element.get_attribute("innerText")
        except selenium.common.exceptions.WebDriverException as e:
            raise _translate_webdriver_error(e) from e

    def wait(self, xpath, timeout=10):
        _wait_until(self.element, EC.presence_of_element_located((By.XPATH, xpath)), timeout)

    def get(self, xpath, timeout=0):
        if timeout:
            self.wait(xpath, timeout)
        try:
            elements = self.element.find_elements(By.XPATH, xpath)
        except selenium.common.exceptions.WebDriverException as e:
            raise _translate_webdriver_error(e) from e
        return [SeleniumWebPageElement(element) for element in elements]

    def click(self, timeout=0):
        if timeout:
            _wait_until(self.element, EC.element_to_be_clickable(self.element), timeout)
        try:
            self.element.click()
        except selenium.common.exceptions.WebDriverException as e:
            raise _translate_webdriver_error(e) from e

    def mouse_over(self):
        try:
            actions = ActionChains(self.element.parent)
            actions.move_to_element(self.element)
            actions.perform()
        except selenium.common.exceptions.WebDriverException as e:
            raise _translate_webdriver_error(e) from e

    def scroll(self, block="start", inline="nearest"):
        try:
            self.element.parent.execute_script(
                f"arguments[0].scrollIntoView({{block: '{block}', inline: '{inline}'}});",
                self.element,
            )
        except selenium.common.exceptions.WebDriverException as e:
            raise _translate_webdriver_error(e) from e

    @contextlib.contextmanager
    def switch(self):
        try:
            self.element.parent.switch_to.frame(self.element)
        except selenium.common.exceptions.WebDriverException as e:
            raise _translate_webdriver_error(e) from e
        try:
            yield
        finally:
            try:
                self.element.parent.switch_to.parent_frame()
            except selenium.common.exceptions.WebDriverException as e:
                raise _translate_webdriver_error(e) from e


class WebPageSelenium(WebPage, ABC):
    DEFAULT_URL = None

    def __init__(
        self,
        url=None,
        params: dict | None = None,
        encoding=None,
        cookies: dict | None = None,
        cookies_file=None,
        page_load_strategy=None,
        profile=None,
        user_data_dir: str | None = None,
        capabilities: dict | None = None,
        node: str | None = None,
    ):
        self.driver = None
        self.cookies = cookies or {}
        self.cookies_file = cookies_file
        self.page_load_strategy = page_load_strategy
        self.profile = resolve_profile(profile, user_data_dir)
        self.capabilities = dict(capabilities) if capabilities else None
        self.node = node
        if not url:
            url = self.DEFAULT_URL
        super().__init__(url, params=params, encoding=encoding)

    def _create_driver(self):
        raise NotImplementedError

    def _ensure_open(self):
        if self.driver is None:
            raise WebPageError("Driver is not opened yet")

    def _configure_no_proxy_for_remote(self, remote_url):
        configure_no_proxy_for_remote(remote_url)

    def _apply_dedicated_settings(self, options):
        if self.page_load_strategy:
            options.page_load_strategy = self.page_load_strategy

    def _init_remote_options(self, options):
        """Apply shared remote Grid settings to ``options``."""
        for key, value in _filter_capabilities(self.capabilities).items():
            options.set_capability(key, value)
        if self.node is not None:
            options.set_capability("pyscraper:node", self.node)
        self._apply_dedicated_settings(options)

    @property
    def url(self):
        if self.driver is None:
            return self.request_url
        try:
            return self.driver.current_url
        except selenium.common.exceptions.WebDriverException as e:
            raise _translate_webdriver_error(e) from e

    @url.setter
    def url(self, url):
        self.request_url = url

        if self.driver is not None:
            self.close()
            self.open()

    @property
    @retry(RemoteDisconnected, tries=5, delay=1, backoff=2, jitter=(1, 5), logger=logger)
    @_wrap_webdriver_errors
    def html(self):
        return self.driver.page_source

    @property
    def cookies(self):
        if self.driver is None:
            return self.request_cookies
        try:
            cookies = {}
            for cookie in self.driver.get_cookies():
                cookies[cookie["name"]] = cookie["value"]
            return cookies
        except selenium.common.exceptions.WebDriverException as e:
            raise _translate_webdriver_error(e) from e

    @cookies.setter
    def cookies(self, cookies):
        self.request_cookies = cookies

        if self.driver is not None:
            self.close()
            self.open()

    @property
    def user_agent(self):
        if self.driver is None:
            return None
        try:
            return self.driver.execute_script("return navigator.userAgent")
        except selenium.common.exceptions.WebDriverException as e:
            raise _translate_webdriver_error(e) from e

    def set_cookies_from_file(self, cookies_file):
        self._ensure_open()
        cookies = MozillaCookieJar(cookies_file)
        cookies.load()
        try:
            for cookie in cookies:
                self.driver.add_cookie(cookie.__dict__)
        except selenium.common.exceptions.WebDriverException as e:
            raise _translate_webdriver_error(e) from e

    def wait(self, xpath, timeout=10):
        self._ensure_open()
        _wait_until(self.driver, EC.presence_of_element_located((By.XPATH, xpath)), timeout)

    def get(self, xpath, timeout=0):
        self._ensure_open()
        if timeout:
            self.wait(xpath, timeout)
        try:
            elements = self.driver.find_elements(By.XPATH, xpath)
        except selenium.common.exceptions.WebDriverException as e:
            raise _translate_webdriver_error(e) from e
        return [SeleniumWebPageElement(element) for element in elements]

    def click(self, xpath, timeout=10):
        self._ensure_open()
        try:
            element = self.driver.find_element(By.XPATH, xpath)
            WebDriverWait(self.driver, timeout).until(EC.element_to_be_clickable(element)).click()
        except selenium.common.exceptions.WebDriverException as e:
            raise _translate_webdriver_error(e) from e

    @_wrap_webdriver_errors
    def move_to(self, xpath):
        actions = ActionChains(self.driver)
        actions.move_to_element(self.driver.find_element(By.XPATH, xpath))
        actions.perform()

    @_wrap_webdriver_errors
    def switch_to_frame(self, xpath):
        iframe = self.driver.find_element(By.XPATH, xpath)
        iframe_url = iframe.get_attribute("src")
        self.driver.switch_to.frame(iframe)
        return iframe_url

    @_wrap_webdriver_errors
    def go(self, url, params: dict | None = None):
        self.driver.get(merge_url_params(url, params))

    @_wrap_webdriver_errors
    def forward(self):
        self.driver.forward()

    @_wrap_webdriver_errors
    def back(self):
        self.driver.back()

    @_wrap_webdriver_errors
    def refresh(self):
        self.driver.refresh()

    @_wrap_webdriver_errors
    def execute_script(self, *args, **kwargs):
        return self.driver.execute_script(*args, **kwargs)

    @_wrap_webdriver_errors
    def execute_async_script(self, *args, **kwargs):
        return self.driver.execute_async_script(*args, **kwargs)

    @_wrap_webdriver_errors
    def dump(self, filestem=None):
        filepath = dump_html(self.html, filestem)
        files = [filepath]
        stem_path = filepath.with_suffix("")

        scroll_height = self.driver.execute_script("return document.body.scrollHeight")
        inner_height = self.driver.execute_script("return window.innerHeight")

        for scroll in iter_scroll_positions(scroll_height, inner_height):
            self.driver.execute_script(f"window.scrollTo(0, {scroll})")
            png_path = Path(f"{stem_path}_{scroll}.png")
            self.driver.save_screenshot(str(png_path))
            files.append(png_path)

        return files

    def open(self):
        logger.debug("Getting {}".format(self.request_url))
        try:
            self.driver = self._create_driver()
            self.driver.get(self.request_url)
            if self.request_cookies:
                for name, value in self.request_cookies.items():
                    self.driver.add_cookie({"name": name, "value": value})
                self.driver.get(self.request_url)
            if self.cookies_file:
                self.set_cookies_from_file(self.cookies_file)
                self.driver.get(self.request_url)
            return self
        except selenium.common.exceptions.WebDriverException as e:
            self._abort_open()
            raise _translate_webdriver_error(e) from e

    def _abort_open(self):
        """Release partial state after a failed ``open()`` without raising."""
        # close() itself can raise when the driver is half-initialized;
        # swallow that so the original failure keeps its traceback, and
        # always drop the handle so later calls see a closed page.
        try:
            self.close()
        except Exception:
            logger.debug("Failed to clean up after open() failure", exc_info=True)
        finally:
            self.driver = None

    def close(self):
        if self.driver is not None:
            self.driver.quit()
            self.driver = None


class WebPageSeleniumFirefox(WebPageSelenium):
    """Web page access via Selenium WebDriver for Firefox.

    When ``SELENIUM_FIREFOX_URL`` is set, a remote WebDriver session is
    created against the Selenium Grid and any ``capabilities`` are included
    in the session request so Grid nodes can be matched by stereotype.

    ``capabilities`` is an arbitrary dict of extension capabilities. Keys
    that overlap with the dedicated arguments/environment (``page_load_strategy``,
    ``language``, ``profile``) are overridden by those settings. Reserved option
    keys such as ``moz:firefoxOptions`` are not supported and must not be passed.
    ``proxy`` cannot be set via ``capabilities``; configure it with the
    ``HTTP_PROXY`` / ``HTTPS_PROXY`` / ``NO_PROXY`` environment variables.
    Unsupported capabilities are logged as warnings. The ``profile`` argument
    (or its alias ``user_data_dir``) takes precedence over the legacy
    ``SELENIUM_FIREFOX_PROFILE`` environment variable. The ``node`` argument
    is forwarded as the ``pyscraper:node`` capability so a Selenium Grid can
    route the session to the node that hosts the matching persistent profile.
    """

    DEFAULT_URL = "about:home"

    def __init__(
        self,
        url=None,
        params: dict | None = None,
        encoding=None,
        cookies: dict | None = None,
        cookies_file=None,
        page_load_strategy=None,
        profile=None,
        user_data_dir: str | None = None,
        language=None,
        capabilities: dict | None = None,
        node: str | None = None,
    ):
        super().__init__(
            url,
            params=params,
            encoding=encoding,
            cookies=cookies,
            cookies_file=cookies_file,
            page_load_strategy=page_load_strategy,
            profile=profile,
            user_data_dir=user_data_dir,
            capabilities=capabilities,
            node=node,
        )
        self.language = language

    def _apply_dedicated_settings(self, options):
        super()._apply_dedicated_settings(options)

        if self.language:
            options.set_preference("intl.accept_languages", self.language)

    def _configure_remote_options(self, options):
        self._init_remote_options(options)
        profile = self.profile or os.environ.get("SELENIUM_FIREFOX_PROFILE")
        if profile:
            options.add_argument("-profile")
            options.add_argument(profile)
        options.proxy = _proxy_from_env()

    def _create_local_driver(self, options):
        self._apply_dedicated_settings(options)
        options.add_argument("-headless")
        if self.profile:
            # Preserve the legacy constructor fallback for older Selenium.
            try:
                options.profile = webdriver.FirefoxProfile(self.profile)
            except Exception:
                return webdriver.Firefox(
                    options=options,
                    firefox_profile=webdriver.FirefoxProfile(self.profile),
                )
        return webdriver.Firefox(options=options)

    def _create_driver(self):
        options = webdriver.FirefoxOptions()
        if url := os.environ.get("SELENIUM_FIREFOX_URL"):
            self._configure_remote_options(options)
            self._configure_no_proxy_for_remote(url)
            return webdriver.Remote(command_executor=url, options=options)
        return self._create_local_driver(options)


class WebPageSeleniumChrome(WebPageSelenium):
    """Web page access via Selenium WebDriver for Chrome.

    When ``SELENIUM_CHROME_URL`` is set, a remote WebDriver session is
    created against the Selenium Grid and any ``capabilities`` are included
    in the session request so Grid nodes can be matched by stereotype.

    ``capabilities`` is an arbitrary dict of extension capabilities. Keys
    that overlap with the dedicated arguments/environment (``page_load_strategy``,
    ``profile``) are overridden by those settings. Reserved option keys
    such as ``goog:chromeOptions`` are not supported and must not be passed.
    ``proxy`` cannot be set via ``capabilities``; configure it with the
    ``HTTP_PROXY`` / ``HTTPS_PROXY`` / ``NO_PROXY`` environment variables.
    Unsupported capabilities are logged as warnings. The ``profile`` argument
    (or its alias ``user_data_dir``) takes precedence over the legacy
    ``SELENIUM_CHROME_PROFILE`` environment variable. The ``node`` argument is
    forwarded as the ``pyscraper:node`` capability for Grid node routing.
    """

    DEFAULT_URL = "chrome://new-tab-page"

    def __init__(
        self,
        url=None,
        params: dict | None = None,
        encoding=None,
        cookies: dict | None = None,
        cookies_file=None,
        page_load_strategy=None,
        profile=None,
        user_data_dir: str | None = None,
        capabilities: dict | None = None,
        node: str | None = None,
    ):
        super().__init__(
            url,
            params=params,
            encoding=encoding,
            cookies=cookies,
            cookies_file=cookies_file,
            page_load_strategy=page_load_strategy,
            profile=profile,
            user_data_dir=user_data_dir,
            capabilities=capabilities,
            node=node,
        )

    def _create_driver(self):
        options = webdriver.ChromeOptions()

        if url := os.environ.get("SELENIUM_CHROME_URL"):
            self._init_remote_options(options)

            options.add_argument("--start-maximized")
            profile = self.profile or os.environ.get("SELENIUM_CHROME_PROFILE")
            if profile:
                options.add_argument(f"--user-data-dir={profile}")

            self._configure_no_proxy_for_remote(url)

            return webdriver.Remote(command_executor=url, options=options)
        else:
            self._apply_dedicated_settings(options)
            options.add_argument("--headless=new")
            options.add_argument("--no-sandbox")
            options.add_argument("--disable-gpu")
            if self.profile:
                options.add_argument(f"--user-data-dir={self.profile}")
            return webdriver.Chrome(options=options)


# Backward-compatible aliases for the original Selenium class names.
WebPageChrome = WebPageSeleniumChrome
WebPageFirefox = WebPageSeleniumFirefox
