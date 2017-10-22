import logging
from memoize import mproperty
from retry import retry
from abc import ABCMeta, abstractmethod
import requests
from selenium import webdriver
from selenium.common.exceptions import ElementNotInteractableException, NoSuchElementException
from selenium.webdriver.common.desired_capabilities import DesiredCapabilities
from selenium.webdriver.common.action_chains import ActionChains
import pyvirtualdisplay
import lxml.html
from .utils import debug, HEADERS

logger = logging.getLogger(__name__)

class WebPageNoSuchElementError(Exception):
    pass

class WebPage(metaclass=ABCMeta):
    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc_value, traceback):
        pass

    @property
    @abstractmethod
    def source(self):
        pass

    @property
    def html(self):
        return lxml.html.fromstring(self.source)

    @debug
    def get(self, xpath):
        return self.html.xpath(xpath)

    def dump(self, filename='dump.html'):
        with open(filename, 'w') as f:
            f.write(self.source)

class WebPageRequests(WebPage):
    def __init__(self, url, session=None, headers={}):
        super().__init__()
        self.url = url

        if session:
            self.session = session
        else:
            self.session = requests.Session()

        self.session.headers.update(HEADERS)
        self.session.headers.update(headers)

    @mproperty
    @retry(requests.exceptions.ReadTimeout, tries=5, delay=1, backoff=2, jitter=(1, 5), logger=logger)
    def response(self):
        r = self.session.get(self.url, timeout=10)
        logger.debug("Response Headers: " + str(r.headers))
        return r

    @mproperty
    def source(self):
        return self.response.text


class WebPageSelenium(WebPage):
    @property
    def url(self):
        return self.webdriver.current_url

    @property
    def source(self):
        return self.webdriver.page_source

    @property
    @debug
    def cookies(self):
        cookies = {}
        for cookie in self.webdriver.get_cookies():
            cookies[cookie['name']] = cookie['value']
        return cookies

    @debug
    @retry(WebPageNoSuchElementError, tries=10, delay=1, logger=logger)
    def get(self, xpath):
        results = self.html.xpath(xpath)
        if results:
            return results
        else:
            raise WebPageNoSuchElementError

    @debug
    @retry(WebPageNoSuchElementError, tries=10, delay=1, logger=logger)
    def click(self, xpath):
        try:
            self.webdriver.find_element_by_xpath(xpath).click()
        except (ElementNotInteractableException, NoSuchElementException) as e:
            raise WebPageNoSuchElementError(e)

    @debug
    @retry(WebPageNoSuchElementError, tries=10, delay=1, logger=logger)
    def move_to(self, xpath):
        try:
            actions = ActionChains(self.webdriver)
            actions.move_to_element(self.webdriver.find_element_by_xpath(xpath))
            actions.perform()
        except (ElementNotInteractableException, NoSuchElementException):
            raise WebPageNoSuchElementError

    @debug
    @retry(WebPageNoSuchElementError, tries=10, delay=1, logger=logger)
    def switch_to_frame(self, xpath):
        try:
            iframe = self.webdriver.find_element_by_xpath(xpath)
            iframe_url = iframe.get_attribute('src')
            self.webdriver.switch_to_frame(iframe)
            return iframe_url
        except (ElementNotInteractableException, NoSuchElementException):
            raise WebPageNoSuchElementError

class WebPagePhantomJS(WebPageSelenium):
    def __init__(self, url):
        super().__init__()
        self._url = url

    def __enter__(self):
        self.webdriver = webdriver.PhantomJS()
        self.webdriver.get(self._url)
        return self

    def __exit__(self, exc_type, exc_value, traceback):
        self.webdriver.quit()

class WebPageFirefox(WebPageSelenium):
    def __init__(self, url):
        super().__init__()
        self._url = url

    def __enter__(self):
        self.display = pyvirtualdisplay.Display()
        self.display.start()
        firefox_capabilities = DesiredCapabilities.FIREFOX
        firefox_capabilities['marionette'] = True
        self.webdriver = webdriver.Firefox(capabilities=firefox_capabilities)
        self.webdriver.get(self._url)
        return self

    def __exit__(self, exc_type, exc_value, traceback):
        self.webdriver.quit()
        self.display.stop()
