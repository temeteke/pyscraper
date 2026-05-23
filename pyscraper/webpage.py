import logging
import os
from abc import ABC, abstractmethod
from datetime import datetime
from pathlib import Path
from urllib.parse import parse_qs, urlencode, urlparse, urlunparse

import lxml.html
from retry import retry


logger = logging.getLogger(__name__)


def _get_env_anycase(name):
    """Read environment variable with lowercase priority (Selenium convention).

    Selenium's ClientConfig.get_proxy_url reads lowercase first:

        os.environ.get("no_proxy", os.environ.get("NO_PROXY"))

    This helper applies the same convention to all proxy-related env vars.

    Args:
        name: Uppercase variable name (e.g. "HTTP_PROXY", "NO_PROXY")

    Returns:
        Value of the lowercase variant if set, otherwise uppercase, or None.
    """
    lower = name.lower()
    return os.environ.get(lower, os.environ.get(name))


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
        for child in list(self.lxml_html):
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
        for child in list(self.lxml_html):
            if child.text:
                text += child.text
            if child.tail:
                text += child.tail
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
            for child in list(element):
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
    def __init__(self, url, params: dict | None = None, encoding=None, params_encoding=None):
        self.encoding = encoding
        if not params:
            self.request_url = url
            return

        if not params_encoding:
            params_encoding = encoding
        parsed_url = urlparse(url)
        parsed_qs = parse_qs(parsed_url.query)
        parsed_qs.update(params)
        self.request_url = urlunparse(
            parsed_url._replace(query=urlencode(parsed_qs, doseq=True, encoding=params_encoding))
        )

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
