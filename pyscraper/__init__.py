import logging
from functools import wraps
from abc import ABCMeta, abstractmethod
import lxml.html
import requests
from selenium import webdriver
from selenium.common.exceptions import ElementNotInteractableException, NoSuchElementException

logger = logging.getLogger(__name__)

def debug(f):
    @wraps(f)
    def wrapper(*args, **kwds):
        logger.debug("{}".format(f.__name__))
        result = f(*args, **kwds)
        if result:
            logger.debug("-> {}".format(result))
        return result
    return wrapper

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
    def __init__(self, url):
        super().__init__()
        self.url = url
        self.response = requests.get(self.url)

    @property
    def source(self):
        return self.response.text


class WebPageSelenium(WebPage):
    @property
    def url(self):
        return self.webdriver.current_url

    @property
    def source(self):
        return self.webdriver.page_source

    @debug
    @retry(WebPageNoSuchElementError, tries=10, delay=1, logger=logger)
    def get(self, xpath):
        results = self.html.xpath(xpath)
        if results:
            return results
        else:
            raise WebPageNoSuchElementError

    @debug
    @retry((ElementNotInteractableException, NoSuchElementException), tries=10, delay=1, logger=logger)
    def click(self, xpath):
        self.webdriver.find_element_by_xpath(xpath).click()

    @debug
    @retry((ElementNotInteractableException, NoSuchElementException), tries=10, delay=1, logger=logger)
    def move_to(self, xpath):
        actions = ActionChains(self.webdriver)
        actions.move_to_element(self.webdriver.find_element_by_xpath(xpath))
        actions.perform()

    @debug
    @retry((ElementNotInteractableException, NoSuchElementException), tries=10, delay=1, logger=logger)
    def switch_to_frame(self, xpath):
        iframe = self.webdriver.find_element_by_xpath(xpath)
        iframe_url = iframe.get_attribute('src')
        self.webdriver.switch_to_frame(iframe)
        return iframe_url

class WebPagePhantomJS(WebPageSelenium):
    def __init__(self, url):
        super().__init__()
        self.__url = url

    def __enter__(self):
        self.webdriver = webdriver.PhantomJS()
        self.webdriver.get(self.__url)
        return self

    def __exit__(self, exc_type, exc_value, traceback):
        self.webdriver.quit()

class WebPageFirefox(WebPageSelenium):
    def __init__(self, url):
        super().__init__()
        self.__url = url

    def __enter__(self):
        self.display = pyvirtualdisplay.Display()
        self.display.start()
        firefox_capabilities = DesiredCapabilities.FIREFOX
        firefox_capabilities['marionette'] = True
        self.webdriver = webdriver.Firefox(capabilities=firefox_capabilities)
        self.webdriver.get(self.__url)
        return self

    def __exit__(self, exc_type, exc_value, traceback):
        self.webdriver.quit()
        self.display.stop()
