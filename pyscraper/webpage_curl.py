import logging
import subprocess
from functools import cached_property

from pyscraper.webpage import WebPage

logger = logging.getLogger(__name__)


class WebPageCurl(WebPage):
    @cached_property
    def html(self):
        return subprocess.run(
            ["curl", self.url],
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            check=True,
        ).stdout.decode(self.encoding or "utf-8")

    @WebPage.url.setter
    def url(self, value):
        WebPage.url.fset(self, value)
        # Drop the cached curl result so a URL change refetches.
        self.__dict__.pop("html", None)
