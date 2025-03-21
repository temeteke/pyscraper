from functools import cached_property
from fake_useragent import UserAgent
import logging
import requests


logger = logging.getLogger(__name__)

user_agent = UserAgent(platforms="desktop")


class RequestsMixin:
    @property
    def session(self):
        if not getattr(self, "_session", None):
            self._session = requests.Session()
            self._session.headers["User-Agent"] = user_agent.random
        return self._session

    @session.setter
    def session(self, session):
        if session:
            self._session = session
            if not session.headers.get("User-Agent"):
                self._session.headers["User-Agent"] = user_agent.random
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
        try:
            return self.response_url
        except requests.exceptions.RequestException as e:
            logger.error(e)
            return self.request_url

    @url.setter
    def url(self, value):
        self.request_url = value
        try:
            del self.response
        except AttributeError:
            pass

    @property
    def response_url(self):
        return self.response.url

    @property
    def encoding(self):
        try:
            return self.response_encoding
        except requests.exceptions.RequestException as e:
            logger.error(e)
            return self.request_encoding

    @encoding.setter
    def encoding(self, value):
        self.request_encoding = value
        try:
            del self.response
        except AttributeError:
            pass

    @property
    def response_encoding(self):
        return self.response.encoding

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
        logger.debug("Getting {}".format(self.request_url))
        logger.debug("Request Headers: " + str(self.session.headers))
        r = self.session.get(self.request_url, timeout=self.timeout)
        logger.debug("Response Headers: " + str(r.headers))
        if encoding := getattr(self, "request_encoding", None):
            r.encoding = encoding
        return r

    @property
    def user_agent(self):
        return self.session.headers["User-Agent"]
