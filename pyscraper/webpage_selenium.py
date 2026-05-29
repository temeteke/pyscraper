import contextlib
import logging
import os
import re
from abc import ABC
from datetime import datetime
from http.client import RemoteDisconnected
from http.cookiejar import MozillaCookieJar
from pathlib import Path
from urllib.parse import parse_qs, urlencode, urlparse, urlunparse

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
    WebPageElement,
    WebPageError,
    WebPageNoSuchElementError,
    WebPageTimeoutError,
    _get_env_anycase,
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


class SeleniumWebPageElement(WebPageElement):
    def __init__(self, element):
        self.element = element

    @property
    def lxml_html(self):
        return lxml.html.fromstring(self.html)

    @property
    def html(self):
        return self.element.get_attribute("outerHTML")

    @property
    def inner_html(self):
        return self.element.get_attribute("innerHTML")

    @property
    def inner_text(self):
        return self.element.get_attribute("innerText")

    def wait(self, xpath, timeout=10):
        try:
            WebDriverWait(self.element, timeout).until(
                EC.presence_of_element_located((By.XPATH, xpath))
            )
        except selenium.common.exceptions.TimeoutException as e:
            raise WebPageTimeoutError from e

    def get(self, xpath, timeout=0):
        if timeout:
            self.wait(xpath, timeout)
        return [
            SeleniumWebPageElement(element)
            for element in self.element.find_elements(By.XPATH, xpath)
        ]

    def click(self, timeout=0):
        if timeout:
            try:
                WebDriverWait(self.element, timeout).until(
                    EC.element_to_be_clickable(self.element)
                )
            except selenium.common.exceptions.TimeoutException as e:
                raise WebPageTimeoutError from e
        self.element.click()

    def mouse_over(self):
        actions = ActionChains(self.element.parent)
        actions.move_to_element(self.element)
        actions.perform()

    def scroll(self, block="start", inline="nearest"):
        self.element.parent.execute_script(
            f"arguments[0].scrollIntoView({{block: '{block}', inline: '{inline}'}});", self.element
        )

    @contextlib.contextmanager
    def switch(self):
        self.element.parent.switch_to.frame(self.element)
        yield
        self.element.parent.switch_to.parent_frame()


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
    ):
        self.driver = None
        self.cookies = cookies or {}
        self.cookies_file = cookies_file
        self.page_load_strategy = page_load_strategy
        if not url:
            url = self.DEFAULT_URL
        super().__init__(url, params=params, encoding=encoding)

    def _create_driver(self):
        raise NotImplementedError

    def _ensure_open(self):
        if self.driver is None:
            raise WebPageError("Driver is not opened yet")

    def _configure_no_proxy_for_remote(self, remote_url):
        netloc = urlparse(remote_url).netloc

        for key in ("no_proxy", "NO_PROXY"):
            if current := os.environ.get(key):
                if netloc not in current:
                    os.environ[key] = current + "," + netloc
            else:
                os.environ[key] = netloc

    @property
    def url(self):
        if self.driver is None:
            return self.request_url
        else:
            return self.driver.current_url

    @url.setter
    def url(self, url):
        self.request_url = url

        if self.driver is not None:
            self.close()
            self.open()

    @property
    @retry(RemoteDisconnected, tries=5, delay=1, backoff=2, jitter=(1, 5), logger=logger)
    def html(self):
        self._ensure_open()
        return self.driver.page_source

    @property
    def cookies(self):
        if self.driver is None:
            return self.request_cookies
        else:
            cookies = {}
            for cookie in self.driver.get_cookies():
                cookies[cookie["name"]] = cookie["value"]
            return cookies

    @cookies.setter
    def cookies(self, cookies):
        self.request_cookies = cookies

        if self.driver is not None:
            self.close()
            self.open()

    @property
    def user_agent(self):
        if self.driver is not None:
            return self.driver.execute_script("return navigator.userAgent")

    def set_cookies_from_file(self, cookies_file):
        self._ensure_open()
        cookies = MozillaCookieJar(cookies_file)
        cookies.load()
        for cookie in cookies:
            self.driver.add_cookie(cookie.__dict__)

    def wait(self, xpath, timeout=10):
        self._ensure_open()
        try:
            WebDriverWait(self.driver, timeout).until(
                EC.presence_of_element_located((By.XPATH, xpath))
            )
        except selenium.common.exceptions.TimeoutException as e:
            raise WebPageTimeoutError from e

    def get(self, xpath, timeout=0):
        self._ensure_open()
        if timeout:
            self.wait(xpath, timeout)
        return [
            SeleniumWebPageElement(element)
            for element in self.driver.find_elements(By.XPATH, xpath)
        ]

    def click(self, xpath, timeout=10):
        self._ensure_open()
        try:
            element = self.driver.find_element(By.XPATH, xpath)
            WebDriverWait(self.driver, timeout).until(EC.element_to_be_clickable(element)).click()
        except selenium.common.exceptions.NoSuchElementException as e:
            raise WebPageNoSuchElementError from e

    def move_to(self, xpath):
        self._ensure_open()
        actions = ActionChains(self.driver)
        actions.move_to_element(self.driver.find_element(By.XPATH, xpath))
        actions.perform()

    def switch_to_frame(self, xpath):
        self._ensure_open()
        iframe = self.driver.find_element(By.XPATH, xpath)
        iframe_url = iframe.get_attribute("src")
        self.driver.switch_to.frame(iframe)
        return iframe_url

    def go(self, url, params: dict | None = None):
        self._ensure_open()
        if params:
            parsed_url = urlparse(url)
            parsed_qs = parse_qs(parsed_url.query)
            parsed_qs.update(params)
            url = urlunparse(parsed_url._replace(query=urlencode(parsed_qs, doseq=True)))
        self.driver.get(url)

    def forward(self):
        self._ensure_open()
        self.driver.forward()

    def back(self):
        self._ensure_open()
        self.driver.back()

    def refresh(self):
        self._ensure_open()
        self.driver.refresh()

    def execute_script(self, *args, **kwargs):
        self._ensure_open()
        return self.driver.execute_script(*args, **kwargs)

    def execute_async_script(self, *args, **kwargs):
        self._ensure_open()
        return self.driver.execute_async_script(*args, **kwargs)

    def dump(self, filestem=None):
        self._ensure_open()
        if not filestem:
            filestem = datetime.now().strftime("%Y%m%d_%H%M%S")

        filepath = Path(filestem + ".html")
        with filepath.open("w") as f:
            f.write(self.html)
        files = [filepath]

        scroll_height = self.driver.execute_script("return document.body.scrollHeight")
        inner_height = self.driver.execute_script("return window.innerHeight")

        scroll = 0
        while scroll < scroll_height:
            self.driver.execute_script(f"window.scrollTo(0, {scroll})")
            filepath = Path(filestem + f"_{scroll}.png")
            self.driver.save_screenshot(str(filepath))
            files.append(filepath)
            scroll += inner_height

        return files

    def open(self):
        self.driver = self._create_driver()

        logger.debug("Getting {}".format(self.request_url))
        try:
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
            logger.error(e)
            self.close()
            raise

    def close(self):
        if self.driver is not None:
            self.driver.quit()
            self.driver = None


class WebPageFirefox(WebPageSelenium):
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
        language=None,
    ):
        super().__init__(
            url,
            params=params,
            encoding=encoding,
            cookies=cookies,
            cookies_file=cookies_file,
            page_load_strategy=page_load_strategy,
        )
        self.profile = profile
        self.language = language

    def _create_driver(self):
        options = webdriver.FirefoxOptions()

        if self.page_load_strategy:
            options.page_load_strategy = self.page_load_strategy

        if self.language:
            options.set_preference("intl.accept_languages", self.language)

        if url := os.environ.get("SELENIUM_FIREFOX_URL"):
            if profile := os.environ.get("SELENIUM_FIREFOX_PROFILE"):
                options.add_argument("-profile")
                options.add_argument(profile)

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
            options.proxy = proxy.Proxy(proxy_dict)

            self._configure_no_proxy_for_remote(url)

            return webdriver.Remote(command_executor=url, options=options)

        else:
            options.headless = True
            if self.profile:
                return webdriver.Firefox(
                    options=options, firefox_profile=webdriver.FirefoxProfile(self.profile)
                )
            return webdriver.Firefox(options=options)


class WebPageChrome(WebPageSelenium):
    DEFAULT_URL = "chrome://new-tab-page"

    def __init__(
        self,
        url=None,
        params: dict | None = None,
        encoding=None,
        cookies: dict | None = None,
        cookies_file=None,
        page_load_strategy=None,
    ):
        super().__init__(
            url,
            params=params,
            encoding=encoding,
            cookies=cookies,
            cookies_file=cookies_file,
            page_load_strategy=page_load_strategy,
        )

    def _create_driver(self):
        options = webdriver.ChromeOptions()
        if self.page_load_strategy:
            options.page_load_strategy = self.page_load_strategy

        if url := os.environ.get("SELENIUM_CHROME_URL"):
            options.add_argument("--start-maximized")
            if profile := os.environ.get("SELENIUM_CHROME_PROFILE"):
                options.add_argument(f"--user-data-dir={profile}")

            self._configure_no_proxy_for_remote(url)

            return webdriver.Remote(command_executor=url, options=options)
        else:
            options.headless = True
            options.add_argument("--no-sandbox")
            options.add_argument("--disable-gpu")
            return webdriver.Chrome(options=options)
