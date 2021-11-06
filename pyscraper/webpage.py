import logging
from memoize import mproperty
from retry import retry
from abc import ABCMeta, abstractmethod
import requests
from selenium import webdriver
from selenium.common.exceptions import ElementNotInteractableException, NoSuchElementException, StaleElementReferenceException, ElementClickInterceptedException, InvalidCookieDomainException
from selenium.webdriver.common.desired_capabilities import DesiredCapabilities
from selenium.webdriver.common.action_chains import ActionChains
import lxml.html
from .utils import debug, HEADERS, RequestsMixin
from pathlib import Path
from http.client import RemoteDisconnected
import os
import subprocess
from http.cookiejar import MozillaCookieJar

logger = logging.getLogger(__name__)

class WebPageError(Exception):
    pass


class WebPageNoSuchElementError(WebPageError):
    pass


class WebPage(metaclass=ABCMeta):
    def __enter__(self):
        self.open()
        return self

    def __exit__(self, exc_type, exc_value, traceback):
        self.close()

    def open(self):
        pass

    def close(self):
        pass

    @property
    @abstractmethod
    def source(self):
        pass

    @property
    def html(self):
        # エンコードしていないcontentがあり、encodingが指定されていない場合、contentを処理する
        if hasattr(self, 'content') and not self._encoding:
            return lxml.html.fromstring(self.content)
        else:
            return lxml.html.fromstring(self.source)

    @debug
    def get(self, xpath):
        return self.xpath(xpath)

    @debug
    def get_html(self, xpath):
        if hasattr(self, 'encoding'):
            return [lxml.html.tostring(x, method='html', encoding=self.encoding).decode().strip() for x in self.html.xpath(xpath)]
        else:
            return [lxml.html.tostring(x, method='html').decode().strip() for x in self.html.xpath(xpath)]

    @debug
    def get_innerhtml(self, xpath):
        if hasattr(self, 'encoding'):
            return [lxml.html.tostring(x, method='text', encoding=self.encoding).decode().strip() for x in self.html.xpath(xpath)]
        else:
            return [lxml.html.tostring(x, method='text').decode().strip() for x in self.html.xpath(xpath)]

    @debug
    @retry(WebPageNoSuchElementError, tries=10, delay=1, logger=logger)
    def get_with_retry(self, xpath):
        results = self.get(xpath)
        if results:
            return results
        else:
            raise WebPageNoSuchElementError

    @debug
    def xpath(self, xpath):
        return self.html.xpath(xpath)

    def dump(self, filestem='dump'):
        with Path('{}.html'.format(filestem)).open('w') as f:
            f.write(self.source)


class WebPageRequests(RequestsMixin, WebPage):
    def __init__(self, url, session=None, headers={}, cookies={}, encoding=None):
        super().__init__()
        self._url = url

        self.init_session(session, headers, cookies)

        self._encoding = encoding

    @mproperty
    @retry(requests.exceptions.ReadTimeout, tries=5, delay=1, backoff=2, jitter=(1, 5), logger=logger)
    def response(self):
        logger.debug("Getting {}".format(self._url))
        logger.debug("Request Headers: " + str(self.session.headers))
        r = self.session.get(self._url, timeout=10)
        logger.debug("Response Headers: " + str(r.headers))
        if self._encoding:
            r.encoding = self._encoding
        return r

    @mproperty
    def url(self):
        return self.response.url

    @mproperty
    def content(self):
        return self.response.content

    @mproperty
    def source(self):
        return self.response.text

    @mproperty
    def encoding(self):
        return self.response.encoding


class SeleniumMixin():
    @property
    def webdriver(self):
        return webdriver

    @property
    def url(self):
        return self.driver.current_url

    @property
    @retry(RemoteDisconnected, tries=5, delay=1, backoff=2, jitter=(1, 5), logger=logger)
    def source(self):
        return self.driver.page_source

    @property
    @debug
    def cookies(self):
        cookies = {}
        for cookie in self.driver.get_cookies():
            cookies[cookie['name']] = cookie['value']
        return cookies

    def set_cookies_from_file(self, cookies_file):
        cookies = MozillaCookieJar(cookies_file)
        cookies.load()
        for cookie in cookies:
            try:
                self.driver.add_cookie(cookie.__dict__)
            except InvalidCookieDomainException:
                pass

    @debug
    @retry(WebPageNoSuchElementError, tries=10, delay=1, logger=logger)
    def click(self, xpath):
        try:
            self.driver.find_element_by_xpath(xpath).click()
        except (ElementNotInteractableException, NoSuchElementException, StaleElementReferenceException, ElementClickInterceptedException) as e:
            raise WebPageNoSuchElementError(e)

    @debug
    @retry(WebPageNoSuchElementError, tries=10, delay=1, logger=logger)
    def move_to(self, xpath):
        try:
            actions = ActionChains(self.driver)
            actions.move_to_element(self.driver.find_element_by_xpath(xpath))
            actions.perform()
        except (ElementNotInteractableException, NoSuchElementException):
            raise WebPageNoSuchElementError

    @debug
    @retry(WebPageNoSuchElementError, tries=10, delay=1, logger=logger)
    def switch_to_frame(self, xpath):
        try:
            iframe = self.driver.find_element_by_xpath(xpath)
            iframe_url = iframe.get_attribute('src')
            self.driver.switch_to.frame(iframe)
            return iframe_url
        except (ElementNotInteractableException, NoSuchElementException):
            raise WebPageNoSuchElementError

    @debug
    def go(self, url):
        self.driver.get(url)

    def forward(self):
        self.driver.forward()

    def back(self):
        self.driver.back()

    def execute_script(self, script, *args):
        return self.driver.execute_script(script, *args)

    def execute_async_script(self, script, *args):
        print(args)
        return self.driver.execute_async_script(script, *args)

    def dump(self, filestem='dump'):
        with Path('{}.html'.format(filestem)).open('w') as f:
            f.write(self.source)

        scroll_height = self.driver.execute_script("return document.body.scrollHeight")
        inner_height = self.driver.execute_script("return window.innerHeight")

        scroll = 0
        while scroll < scroll_height:
            self.driver.execute_script(f"window.scrollTo(0, {scroll})")
            self.driver.save_screenshot(filestem+f'_{scroll}.png')
            scroll += inner_height


class WebPagePhantomJS(SeleniumMixin, WebPage):
    def __init__(self, url):
        super().__init__()
        self._url = url

    def open(self):
        self.driver = self.webdriver.PhantomJS()
        logger.debug("Getting {}".format(self._url))
        self.driver.get(self._url)
        return self

    def close(self):
        self.driver.quit()


class WebPageFirefox(SeleniumMixin, WebPage):
    def __init__(self, url, cookies_file=None, profile=None):
        super().__init__()
        self._url = url
        self._cookies_file = cookies_file
        self._profile = profile

    def open(self):
        options = self.webdriver.firefox.options.Options()
        options.headless = True

        if self._profile:
            self.driver = self.webdriver.Firefox(options=options, service_log_path=os.path.devnull, firefox_profile=self.webdriver.FirefoxProfile(self._profile))
        else:
            self.driver = self.webdriver.Firefox(options=options, service_log_path=os.path.devnull)

        logger.debug("Getting {}".format(self._url))
        self.driver.get(self._url)

        if self._cookies_file:
            self.set_cookies_from_file(self._cookies_file)
            self.driver.get(self._url)

        return self

    def close(self):
        self.driver.quit()


class WebPageChrome(SeleniumMixin, WebPage):
    def __init__(self, url, cookies_file=None):
        super().__init__()
        self._url = url
        self._cookies_file = cookies_file

    def open(self):
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
    def __init__(self, url):
        super().__init__()
        self.url = url

    @mproperty
    def source(self):
        return subprocess.run(['curl', self.url], stdout=subprocess.PIPE, stderr=subprocess.DEVNULL).stdout.decode()
