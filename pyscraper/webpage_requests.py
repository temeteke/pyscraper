import logging

import lxml.html
import requests

from pyscraper.requests import RequestsMixin
from pyscraper.webpage import (
    WebPage,
    WebPageConnectionError,
    WebPageError,
    WebPageTimeoutError,
)

logger = logging.getLogger(__name__)


class WebPageRequests(RequestsMixin, WebPage):
    def __init__(
        self,
        url,
        params: dict | None = None,
        encoding=None,
        headers: dict | None = None,
        cookies: dict | None = None,
        session=None,
        timeout=10,
    ):
        self.response = None

        super().__init__(url, params=params, encoding=encoding)

        self.request_headers = dict(headers) if headers else {}
        self.request_cookies = dict(cookies) if cookies else {}
        self.session = session
        self.timeout = timeout

    @property
    def url(self):
        if self.response is None:
            return self.request_url
        else:
            return self.response.url

    @url.setter
    def url(self, url):
        self.request_url = url

        if self.response is not None:
            self.close_response()
            self.open_response()

    @property
    def encoding(self):
        if self.response is None:
            return self.request_encoding
        else:
            return self.response.encoding

    @encoding.setter
    def encoding(self, value):
        self.request_encoding = value

        if self.response is not None:
            self.close_response()
            self.open_response()

    @property
    def html(self):
        if self.response is None:
            raise WebPageError("Response is not opened yet")

        return self.response.text

    @property
    def lxml_html(self):
        if self.response is None:
            raise WebPageError("Response is not opened yet")

        if not self.request_encoding:
            if html := self.response.content:
                return lxml.html.fromstring(html)

        return super().lxml_html

    def open_response(self):
        logger.debug("Getting {}".format(self.request_url))
        logger.debug("Request Headers: " + str(self.session.headers))

        # Order matters: ConnectionError/Timeout subclass RequestException.
        # Status errors are intentionally not raised here (no raise_for_status):
        # a non-2xx response is still a successful fetch at this layer.
        try:
            self.response = self.session.get(self.request_url, timeout=self.timeout)
        except requests.exceptions.ConnectionError as e:
            raise WebPageConnectionError(e) from e
        except requests.exceptions.Timeout as e:
            raise WebPageTimeoutError(e) from e
        except requests.exceptions.RequestException as e:
            raise WebPageError(e) from e

        logger.debug("Response Headers: " + str(self.response.headers))

        if encoding := getattr(self, "request_encoding", None):
            self.response.encoding = encoding

    def close_response(self):
        if self.response is not None:
            self.response.close()
            self.response = None

    def open(self):
        self.open_session()
        self.open_response()
        return self

    def close(self):
        self.close_response()
        self.close_session()
