import contextlib
import logging
import os
import subprocess
from abc import ABC, abstractmethod
from datetime import datetime
from functools import cached_property
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

from pyscraper.requests import RequestsMixin


logger = logging.getLogger(__name__)


class WebPageError(Exception):
    pass


class WebPageTimeoutError(WebPageError):
    pass


class WebPageNoSuchElementError(WebPageError):
    pass


class WebPageElement:
    def __init__(self, element, encoding=None):
        self.lxml_html = element
        if encoding:
            self.encoding = encoding
        else:
            self.encoding = "utf-8"

    @property
    def html(self):
        return (
            lxml.html.tostring(self.lxml_html, method="html", encoding=self.encoding)
            .decode(encoding=self.encoding)
            .strip()
        )

    @property
    def inner_html(self):
        html = ""
        if self.lxml_html.text:
            html += self.lxml_html.text
        for child in self.lxml_html.getchildren():
            html += lxml.html.tostring(child, encoding=self.encoding).decode(
                encoding=self.encoding
            )
        return html.strip()

    @property
    def text(self):
        return self.lxml_html.text

    @property
    def inner_text(self):
        text = ""
        if self.lxml_html.text:
            text += self.lxml_html.text
        for child in self.lxml_html.getchildren():
            if child.text:
                text += child.text
        return text.strip()

    @property
    def attr(self):
        return self.attributes

    @property
    def attrib(self):
        return self.attributes

    @property
    def attributes(self):
        return self.lxml_html.attrib

    def get(self, xpath):
        return [WebPageElement(element, self.encoding) for element in self.lxml_html.xpath(xpath)]

    def xpath(self, xpath):
        return self.lxml_html.xpath(xpath)

    def itertext(self):
        return self.lxml_html.itertext()


class WebPageParserMixin(ABC):
    @property
    @abstractmethod
    def html(self):
        pass

    @property
    def encoding(self):
        if encoding := getattr(self, "request_encoding", None):
            return encoding
        else:
            return "utf-8"

    @encoding.setter
    def encoding(self, value):
        self.request_encoding = value

    @property
    def lxml_html(self):
        if not self.html:
            return

        return lxml.html.fromstring(self.html)

    def get(self, xpath):
        return [WebPageElement(element, encoding=self.encoding) for element in self.xpath(xpath)]

    def get_html(self, xpath):
        if self.lxml_html is None:
            return []

        return [
            lxml.html.tostring(x, method="html", encoding=self.encoding)
            .decode(self.encoding)
            .strip()
            for x in self.lxml_html.xpath(xpath)
        ]

    def get_innerhtml(self, xpath):
        if self.lxml_html is None:
            return []

        htmls = []
        for element in self.lxml_html.xpath(xpath):
            html = ""
            if element.text:
                html += element.text
            for child in element.getchildren():
                html += lxml.html.tostring(child, encoding=self.encoding).decode(self.encoding)
            htmls.append(html.strip())
        return htmls

    @retry(WebPageNoSuchElementError, tries=10, delay=1, logger=logger)
    def get_with_retry(self, xpath):
        results = self.get(xpath)
        if results:
            return results
        else:
            raise WebPageNoSuchElementError

    def xpath(self, xpath):
        if self.lxml_html is None:
            return []

        return self.lxml_html.xpath(xpath)

    def dump(self, filestem=None):
        if not filestem:
            filestem = datetime.now().strftime("%Y%m%d_%H%M%S")

        filepath = Path(filestem + ".html")
        with filepath.open("w") as f:
            f.write(self.html)

        return filepath


class WebPage(WebPageParserMixin):
    def __init__(self, url, params={}, encoding=None, params_encoding=None):
        if not params_encoding:
            params_encoding = encoding

        parsed_url = urlparse(url)
        parsed_qs = parse_qs(parsed_url.query)
        parsed_qs.update(params)
        self.request_url = urlunparse(
            parsed_url._replace(query=urlencode(parsed_qs, doseq=True, encoding=params_encoding))
        )
        self.encoding = encoding

    def __str__(self):
        return self.url

    def __eq__(self, other):
        if not isinstance(other, self.__class__):
            return NotImplemented
        return self.url == other.url

    @property
    def url(self):
        return self.request_url

    @url.setter
    def url(self, value):
        self.request_url = value

    def __enter__(self):
        self.open()
        return self

    def __exit__(self, exc_type, exc_value, traceback):
        self.close()

    def open(self):
        pass

    def close(self):
        pass


class WebPageRequests(RequestsMixin, WebPage):
    def __init__(
        self, url, params={}, session=None, headers={}, cookies={}, encoding=None, timeout=10
    ):
        super().__init__(url, params=params, encoding=encoding)

        self.session = session
        self.headers = headers
        self.cookies = cookies
        self.timeout = timeout

    @property
    def html(self):
        return self.response.text

    @property
    def lxml_html(self):
        # encodingが指定されていなかった場合、デコード前のcontentを処理する
        if not self.request_encoding:
            if html := self.response.content:
                return lxml.html.fromstring(html)

        return super().lxml_html

    def open(self):
        self.session

    def close(self):
        self.session.close()


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
    @property
    @abstractmethod
    def driver(self):
        pass

    @property
    def url(self):
        return self.driver.current_url

    @url.setter
    def url(self, url):
        self.go(url)

    @property
    @retry(RemoteDisconnected, tries=5, delay=1, backoff=2, jitter=(1, 5), logger=logger)
    def html(self):
        return self.driver.page_source

    @property
    def cookies(self):
        cookies = {}
        for cookie in self.driver.get_cookies():
            cookies[cookie["name"]] = cookie["value"]
        return cookies

    @cookies.setter
    def cookies(self, cookies):
        self.request_cookies = cookies

    @property
    def user_agent(self):
        return self.driver.execute_script("return navigator.userAgent")

    def set_cookies_from_file(self, cookies_file):
        cookies = MozillaCookieJar(cookies_file)
        cookies.load()
        for cookie in cookies:
            self.driver.add_cookie(cookie.__dict__)

    def wait(self, xpath, timeout=10):
        try:
            WebDriverWait(self.driver, timeout).until(
                EC.presence_of_element_located((By.XPATH, xpath))
            )
        except selenium.common.exceptions.TimeoutException as e:
            raise WebPageTimeoutError from e

    def get(self, xpath, timeout=0):
        if timeout:
            self.wait(xpath, timeout)
        return [
            SeleniumWebPageElement(element)
            for element in self.driver.find_elements(By.XPATH, xpath)
        ]

    def click(self, xpath, timeout=10):
        try:
            element = self.driver.find_element(By.XPATH, xpath)
            # self.driver.execute_script("arguments[0].scrollIntoView();", element)
            WebDriverWait(self.driver, timeout).until(EC.element_to_be_clickable(element)).click()
        except selenium.common.exceptions.NoSuchElementException as e:
            raise WebPageNoSuchElementError from e

    def move_to(self, xpath):
        actions = ActionChains(self.driver)
        actions.move_to_element(self.driver.find_element(By.XPATH, xpath))
        actions.perform()

    def switch_to_frame(self, xpath):
        iframe = self.driver.find_element(By.XPATH, xpath)
        iframe_url = iframe.get_attribute("src")
        self.driver.switch_to.frame(iframe)
        return iframe_url

    def go(self, url, params={}):
        if params:
            parsed_url = urlparse(url)
            parsed_qs = parse_qs(parsed_url.query)
            parsed_qs.update(params)
            url = urlunparse(parsed_url._replace(query=urlencode(parsed_qs, doseq=True)))
        self.driver.get(url)

    def forward(self):
        self.driver.forward()

    def back(self):
        self.driver.back()

    def refresh(self):
        self.driver.refresh()

    def execute_script(self, *args, **kwargs):
        return self.driver.execute_script(*args, **kwargs)

    def execute_async_script(self, *args, **kwargs):
        return self.driver.execute_async_script(*args, **kwargs)

    def dump(self, filestem=None):
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
        logger.debug("Getting {}".format(self.request_url))
        self.driver.get(self.request_url)

        if self.request_cookies:
            for name, value in self.request_cookies.items():
                self.driver.add_cookie({"name": name, "value": value})
            self.driver.get(self.request_url)
        if self.cookies_file:
            self.set_cookies_from_file(self.cookies_file)
            self.driver.get(self.request_url)

        return self

    def close(self):
        self.driver.quit()


class WebPageFirefox(WebPageSelenium):
    def __init__(
        self,
        url=None,
        params={},
        cookies={},
        cookies_file=None,
        profile=None,
        page_load_strategy=None,
        language=None,
    ):
        if not url:
            url = "about:home"
        super().__init__(url, params=params)
        self.cookies = cookies
        self.cookies_file = cookies_file
        self.profile = profile
        self.page_load_strategy = page_load_strategy
        self.language = language

    @cached_property
    def driver(self):
        options = webdriver.FirefoxOptions()

        if self.page_load_strategy:
            options.page_load_strategy = self.page_load_strategy

        if self.language:
            options.set_preference("intl.accept_languages", self.language)

        if url := os.environ.get("SELENIUM_FIREFOX_URL"):
            if profile := os.environ.get("SELENIUM_FIREFOX_PROFILE"):
                options.add_argument("-profile")
                options.add_argument(profile)

            # get proxy settings from environment variables
            http_proxy = os.environ.get("HTTP_PROXY")
            https_proxy = os.environ.get("HTTPS_PROXY")
            no_proxy = os.environ.get("NO_PROXY")

            # set proxy option for Firefox
            if http_proxy or https_proxy or no_proxy:
                proxy_dict = {"proxyType": proxy.ProxyType.MANUAL}
                if http_proxy:
                    proxy_dict["httpProxy"] = http_proxy
                if https_proxy:
                    proxy_dict["sslProxy"] = https_proxy
                if no_proxy:
                    proxy_dict["noProxy"] = no_proxy.split(",")
            else:
                proxy_dict = {"proxyType": proxy.ProxyType.DIRECT}
            options.proxy = proxy.Proxy(proxy_dict)

            # set NO_PROXY not to use proxy for accessing selenium
            netloc = urlparse(url).netloc
            if not no_proxy:
                os.environ["NO_PROXY"] = netloc
            elif netloc not in no_proxy:
                os.environ["NO_PROXY"] += "," + netloc

            return webdriver.Remote(command_executor=url, options=options)

        else:
            options.headless = True
            if self.profile:
                return webdriver.Firefox(
                    options=options, firefox_profile=webdriver.FirefoxProfile(self.profile)
                )
            else:
                return webdriver.Firefox(options=options)


class WebPageChrome(WebPageSelenium):
    def __init__(
        self, url=None, params={}, cookies={}, cookies_file=None, page_load_strategy=None
    ):
        if not url:
            url = "chrome://new-tab-page"
        super().__init__(url, params=params)
        self.cookies = cookies
        self.cookies_file = cookies_file
        self.page_load_strategy = page_load_strategy

    @cached_property
    def driver(self):
        options = webdriver.ChromeOptions()
        if self.page_load_strategy:
            options.page_load_strategy = self.page_load_strategy

        if url := os.environ.get("SELENIUM_CHROME_URL"):
            options.add_argument("--start-maximized")
            if profile := os.environ.get("SELENIUM_CHROME_PROFILE"):
                options.add_argument(f"--user-data-dir={profile}")

            # set NO_PROXY not to use proxy for accessing selenium
            no_proxy = os.environ.get("NO_PROXY")
            netloc = urlparse(url).netloc
            if not no_proxy:
                os.environ["NO_PROXY"] = netloc
            elif netloc not in no_proxy:
                os.environ["NO_PROXY"] += "," + netloc

            return webdriver.Remote(command_executor=url, options=options)
        else:
            options.headless = True
            options.add_argument("--no-sandbox")
            options.add_argument("--disable-gpu")
            return webdriver.Chrome(options=options)


class WebPageCurl(WebPage):
    @cached_property
    def html(self):
        return subprocess.run(
            ["curl", self.url], stdout=subprocess.PIPE, stderr=subprocess.DEVNULL
        ).stdout.decode()
