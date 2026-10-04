import logging
import subprocess
from functools import cached_property

from pyscraper.webpage import WebPage, WebPageConnectionError, WebPageError

logger = logging.getLogger(__name__)


class WebPageCurl(WebPage):
    @cached_property
    def html(self):
        try:
            return subprocess.run(
                ["curl", self.url],
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                check=True,
            ).stdout.decode(self.encoding or "utf-8")
        except (subprocess.CalledProcessError, OSError) as e:
            raise WebPageConnectionError(e) from e
        except (UnicodeDecodeError, LookupError) as e:
            raise WebPageError(e) from e

    @WebPage.url.setter
    def url(self, value):
        WebPage.url.fset(self, value)
        # Drop the cached curl result so a URL change refetches.
        self.__dict__.pop("html", None)
