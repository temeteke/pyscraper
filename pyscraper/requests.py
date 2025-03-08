from functools import cached_property
import logging
import requests

from pyscraper.utils import HEADERS

logger = logging.getLogger(__name__)


class RequestsMixin:
    @property
    def session(self):
        if not getattr(self, "_session", None):
            self._session = requests.Session()
            self._session.headers.update(HEADERS)
        return self._session

    @session.setter
    def session(self, session):
        if session:
            self._session = session
            # sessionのheadersにない項目はデフォルトのHEADERSを設定する
            for k, v in HEADERS.items():
                self._session.headers.setdefault(k, v)
        try:
            del self.response
        except AttributeError:
            pass

    @property
    def headers(self):
        return dict(self.session.headers)

    @headers.setter
    def headers(self, headers):
        self.session.headers.update(headers)
        try:
            del self.response
        except AttributeError:
            pass

    @property
    def cookies(self):
        return dict(self.session.cookies)

    @cookies.setter
    def cookies(self, cookies):
        for k, v in cookies.items():
            self.session.cookies.set(k, v)
        try:
            del self.response
        except AttributeError:
            pass

    @property
    def url(self):
        return self.response.url

    @url.setter
    def url(self, value):
        self._url = value
        try:
            del self.response
        except AttributeError:
            pass

    @property
    def encoding(self):
        return self.response.encoding

    @encoding.setter
    def encoding(self, value):
        self._encoding = value
        try:
            del self.response
        except AttributeError:
            pass

    @property
    def timeout(self):
        if not getattr(self, "_timeout", None):
            self._timeout = 10
        return self._timeout

    @timeout.setter
    def timeout(self, value):
        self._timeout = value

    @cached_property
    def response(self):
        logger.debug("Getting {}".format(self._url))
        logger.debug("Request Headers: " + str(self.session.headers))
        r = self.session.get(self._url, timeout=self.timeout)
        logger.debug("Response Headers: " + str(r.headers))
        if encoding := getattr(self, "_encoding", None):
            r.encoding = encoding
        return r

    @property
    def user_agent(self):
        return self.session.headers["User-Agent"]
