import logging
from functools import wraps
from memoize import mproperty
from abc import ABCMeta, abstractmethod
import lxml.html
import requests
from selenium import webdriver
from selenium.common.exceptions import ElementNotInteractableException, NoSuchElementException
from retry import retry
from pathlib import Path
import re
from tqdm import tqdm

logger = logging.getLogger(__name__)

HEADERS = {'Referer': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:56.0) Gecko/20100101 Firefox/56.0'}

def debug(f):
    @wraps(f)
    def wrapper(*args, **kwds):
        result = f(*args, **kwds)
        if args[1:]:
            logger.debug("{}('{}') -> {}".format('.'.join([args[0].__class__.__name__, f.__name__]), ','.join(args[1:]), result))
        else:
            logger.debug("{} -> {}".format(f.__name__, result))
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
    def response(self):
        r = self.session.get(self.url)
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


class WebFileDownloadError(Exception):
    pass

class WebFile():
    def __init__(self, url, session=None, headers={}, directory='.', filename=None):
        self.url = url

        if session:
            self.session = session
        else:
            self.session = requests.Session()

        self.session.headers.update(HEADERS)
        self.session.headers.update(headers)

        self.directory = Path(directory)
        if not self.directory.exists():
            self.directory.mkdir()

        if not filename:
            filename = url.split('/').pop()
        self._filename = re.sub(r'[/:\s\*]', '_', filename)

    @mproperty
    @debug
    def filename(self):
        logger.debug("Request Headers: " + str(self.session.headers))
        r = self.session.head(self.url, allow_redirects=True)
        logger.debug("Response Headers: " + str(r.headers))
        if 'Content-Disposition' in r.headers:
            return re.findall('filename="(.+)"', r.headers['Content-Disposition'])[0]
        else:
            return self._filename

    @mproperty
    @debug
    def filepath(self):
        return Path(self.directory, self.filename)

    @mproperty
    @debug
    def filepath_tmp(self):
        return Path(str(self.filepath) + '.part')

    def download(self):
        logger.info("Downloading {}".format(self.url))

        if self.filepath.exists():
            logger.warning("{} is already downloaded.".format(self.filepath))
            return

        try_maxcount = 10
        for i in range(1, try_maxcount+1):
            logger.debug("Trying to download ({}/{})".format(i, try_maxcount))

            if self.filepath_tmp.exists():
                downloaded_size = self.filepath_tmp.stat().st_size
                self.session.headers['Range'] = 'bytes={}-'.format(downloaded_size)
            else:
                downloaded_size = 0

            try:
                logger.debug("Request Headers: " + str(self.session.headers))
                r = self.session.get(self.url, stream=True)
                logger.debug("Response Headers: " + str(r.headers))
                r.raise_for_status()
            except requests.exceptions.HTTPError as e:
                logger.warning(e)
                if e.response.status_code == 416:
                    if self.filepath_tmp.exists():
                        logger.debug("Removing downloaded file.")
                        self.filepath_tmp.unlink()
                else:
                    wait_random(maxsec=30)
                continue
            except (requests.exceptions.ConnectionError, requests.exceptions.ChunkedEncodingError) as e:
                logger.warning(e)
                wait_random(maxsec=30)
                continue

            total_size = int(r.headers['Content-Length'])
            if 'Content-Range' in r.headers:
                total_size = int(r.headers['Content-Range'].split('/')[-1])
            if total_size == 0:
                raise WebFileDownloadError

            with tqdm(total=total_size, initial=downloaded_size, unit='B', unit_scale=True, dynamic_ncols=True, ascii=True) as pbar:
                with self.filepath_tmp.open('ab') as f:
                    for block in r.iter_content(1024):
                        f.write(block)
                        pbar.update(len(block))

            if self.filepath_tmp.stat().st_size == total_size:
                self.filepath_tmp.rename(self.filepath)
                return
            else:
                logger.warning("The size of the downloaded file is wrong.")
                wait_random(maxsec=30)
                continue

        raise WebFileDownloadError
