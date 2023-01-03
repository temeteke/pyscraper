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
import requests
from retry import retry
from selenium import webdriver
from selenium.webdriver.common import proxy
from selenium.webdriver.common.action_chains import ActionChains
from selenium.webdriver.common.by import By
from selenium.webdriver.support import expected_conditions as EC
from selenium.webdriver.support.ui import WebDriverWait

from .utils import RequestsMixin, debug

logger = logging.getLogger(__name__)


class WebPageError(Exception):
    pass


class WebPageNoSuchElementError(WebPageError):
    pass


class WebPageParser():
    def __init__(self, source, encoding=None):
        self.source = source
        self._encoding = encoding

    @property
    def html(self):
        # エンコードしていないcontentがあり、encodingが指定されていない場合、contentを処理する
        if hasattr(self, 'content') and not self._encoding:
            return lxml.html.fromstring(self.content)
        else:
            return lxml.html.fromstring(self.source)

    def get(self, xpath):
        return self.xpath(xpath)

    @debug(logger)
    def get_html(self, xpath):
        if hasattr(self, 'encoding'):
            return [lxml.html.tostring(x, method='html', encoding=self.encoding).decode().strip() for x in self.html.xpath(xpath)]
        else:
            return [lxml.html.tostring(x, method='html').decode().strip() for x in self.html.xpath(xpath)]

    @debug(logger)
    def get_innerhtml(self, xpath):
        htmls = []
        for element in self.html.xpath(xpath):
            html = ''
            if element.text:
                html += element.text
            for child in element.getchildren():
                if hasattr(self, 'encoding'):
                    html += lxml.html.tostring(child, encoding=self.encoding).decode()
                else:
                    html += lxml.html.tostring(child).decode()
            htmls.append(html.strip())
        return htmls

    @retry(WebPageNoSuchElementError, tries=10, delay=1, logger=logger)
    def get_with_retry(self, xpath):
        results = self.get(xpath)
        if results:
            return results
        else:
            raise WebPageNoSuchElementError

    @debug(logger)
    def xpath(self, xpath):
        return self.html.xpath(xpath)

    def dump(self, filestem=None):
        if not filestem:
            filestem = datetime.now().strftime('%Y%m%d_%H%M%S')

        filepath = Path(filestem + '.html')
        with filepath.open('w') as f:
            f.write(self.source)

        return filepath

    def __enter__(self):
        self.open()
        return self

    def __exit__(self, exc_type, exc_value, traceback):
        self.close()

    def open(self):
        pass

    def close(self):
        pass


class WebPage(WebPageParser, ABC):
    def __init__(self, url, params={}):
        parsed_url = urlparse(url)
        parsed_qs = parse_qs(parsed_url.query)
        parsed_qs.update(params)
        self._url = urlunparse(parsed_url._replace(query=urlencode(parsed_qs, doseq=True)))

    def __str__(self):
        return self.url

    def __eq__(self, other):
        if not isinstance(other, self.__class__):
            return NotImplemented
        return self.url == other.url

    @property
    @abstractmethod
    def url(self):
        pass

    @property
    @abstractmethod
    def source(self):
        pass


class WebPageRequests(RequestsMixin, WebPage):
    def __init__(self, url, params={}, session=None, headers={}, cookies={}, encoding=None):
        super().__init__(url, params)

        self.init_session(session, headers, cookies)

        self._encoding = encoding

    @cached_property
    @retry(requests.exceptions.ReadTimeout, tries=5, delay=1, backoff=2, jitter=(1, 5), logger=logger)
    def response(self):
        logger.debug("Getting {}".format(self._url))
        logger.debug("Request Headers: " + str(self.session.headers))
        r = self.session.get(self._url, timeout=10)
        logger.debug("Response Headers: " + str(r.headers))
        if self._encoding:
            r.encoding = self._encoding
        return r

    @cached_property
    def url(self):
        if 'response' in self.__dict__:
            return self.response.url
        else:
            return self._url

    @cached_property
    def content(self):
        return self.response.content

    @cached_property
    def source(self):
        return self.response.text

    @cached_property
    def encoding(self):
        return self.response.encoding


class SeleniumMixin():
    @property
    def webdriver(self):
        return webdriver

    @property
    def url(self):
        if hasattr(self, 'driver'):
            return self.driver.current_url
        else:
            return self._url

    @property
    @retry(RemoteDisconnected, tries=5, delay=1, backoff=2, jitter=(1, 5), logger=logger)
    def source(self):
        return self.driver.page_source

    @property
    @debug(logger)
    def cookies(self):
        cookies = {}
        for cookie in self.driver.get_cookies():
            cookies[cookie['name']] = cookie['value']
        return cookies

    def set_cookies_from_file(self, cookies_file):
        cookies = MozillaCookieJar(cookies_file)
        cookies.load()
        for cookie in cookies:
            self.driver.add_cookie(cookie.__dict__)

    @debug(logger)
    def click(self, xpath, timeout=10):
        element = self.driver.find_element(By.XPATH, xpath)
        self.driver.execute_script("arguments[0].scrollIntoView();", element)
        WebDriverWait(self.driver, timeout).until(EC.element_to_be_clickable(element)).click()

    @debug(logger)
    def move_to(self, xpath):
        actions = ActionChains(self.driver)
        actions.move_to_element(self.driver.find_element(By.XPATH, xpath))
        actions.perform()

    @debug(logger)
    def switch_to_frame(self, xpath):
        iframe = self.driver.find_element(By.XPATH, xpath)
        iframe_url = iframe.get_attribute('src')
        self.driver.switch_to.frame(iframe)
        return iframe_url

    @debug(logger)
    def go(self, url, params={}):
        parsed_url = urlparse(url)
        parsed_qs = parse_qs(parsed_url.query)
        parsed_qs.update(params)
        self.driver.get(urlunparse(parsed_url._replace(query=urlencode(parsed_qs, doseq=True))))

    def forward(self):
        self.driver.forward()

    def back(self):
        self.driver.back()

    def refresh(self):
        self.driver.refresh()

    @debug(logger)
    def execute_script(self, script, *args):
        return self.driver.execute_script(script, *args)

    @debug(logger)
    def execute_async_script(self, script, *args):
        print(args)
        return self.driver.execute_async_script(script, *args)

    def dump(self, filestem=None):
        if not filestem:
            filestem = datetime.now().strftime('%Y%m%d_%H%M%S')

        filepath = Path(filestem + '.html')
        with filepath.open('w') as f:
            f.write(self.source)
        files = [filepath]

        scroll_height = self.driver.execute_script("return document.body.scrollHeight")
        inner_height = self.driver.execute_script("return window.innerHeight")

        scroll = 0
        while scroll < scroll_height:
            self.driver.execute_script(f"window.scrollTo(0, {scroll})")
            filepath = Path(filestem + f'_{scroll}.png')
            self.driver.save_screenshot(str(filepath))
            files.append(filepath)
            scroll += inner_height

        return files


class WebPageFirefox(SeleniumMixin, WebPage):
    def __init__(self, url, params={}, cookies_file=None, profile=None):
        super().__init__(url, params)
        self._cookies_file = cookies_file
        self._profile = profile

    def open(self):
        if url := os.environ.get('SELENIUM_FIREFOX_URL'):
            options = webdriver.FirefoxOptions()
            if profile := os.environ.get('SELENIUM_FIREFOX_PROFILE'):
                options.add_argument('-profile')
                options.add_argument(profile)

            # get proxy settings from environment variables
            http_proxy = os.environ.get('HTTP_PROXY')
            https_proxy = os.environ.get('HTTPS_PROXY')
            no_proxy = os.environ.get('NO_PROXY')

            # set proxy option for Firefox
            if http_proxy or https_proxy or no_proxy:
                proxy_dict = {
                    'proxyType': proxy.ProxyType.MANUAL
                }
                if http_proxy:
                    proxy_dict['httpProxy'] = http_proxy
                if https_proxy:
                    proxy_dict['sslProxy'] = https_proxy
                if no_proxy:
                    proxy_dict['noProxy'] = no_proxy
            else:
                proxy_dict = {
                    'proxyType': proxy.ProxyType.DIRECT
                }
            options.proxy = proxy.Proxy(proxy_dict)

            # set NO_PROXY not to use proxy for accessing selenium
            if not no_proxy:
                os.environ['NO_PROXY'] = url
            elif url not in no_proxy:
                os.environ['NO_PROXY'] += ';' + url

            self.driver = self.webdriver.Remote(command_executor=url, options=options)

        else:
            options = self.webdriver.firefox.options.Options()
            options.headless = True
            if self._profile:
                self.driver = self.webdriver.Firefox(options=options, firefox_profile=self.webdriver.FirefoxProfile(self._profile))
            else:
                self.driver = self.webdriver.Firefox(options=options)

        logger.debug("Getting {}".format(self._url))
        self.driver.get(self._url)

        if self._cookies_file:
            self.set_cookies_from_file(self._cookies_file)
            self.driver.get(self._url)

        return self

    def close(self):
        self.driver.quit()


class WebPageChrome(SeleniumMixin, WebPage):
    def __init__(self, url, params={}, cookies_file=None):
        super().__init__(url, params)
        self._cookies_file = cookies_file

    def open(self):
        if url := os.environ.get('SELENIUM_CHROME_URL'):
            # set NO_PROXY not to use proxy for accessing selenium
            no_proxy = os.environ.get('NO_PROXY')
            if not no_proxy:
                os.environ['NO_PROXY'] = url
            elif url not in no_proxy:
                os.environ['NO_PROXY'] += ';' + url

            self.driver = self.webdriver.Remote(command_executor=url, options=webdriver.ChromeOptions())
        else:
            options = self.webdriver.chrome.options.Options()
            options.headless = True
            options.add_argument('--no-sandbox')
            options.add_argument('--disable-gpu')
            self.driver = self.webdriver.Chrome(options=options)

        logger.debug("Getting {}".format(self._url))
        self.driver.get(self._url)
        if self._cookies_file:
            self.set_cookies_from_file(self._cookies_file)
            self.driver.get(self._url)
        return self

    def close(self):
        self.driver.quit()


class WebPageCurl(WebPage):
    @property
    def url(self):
        return self._url

    @cached_property
    def source(self):
        return subprocess.run(['curl', self.url], stdout=subprocess.PIPE, stderr=subprocess.DEVNULL).stdout.decode()
