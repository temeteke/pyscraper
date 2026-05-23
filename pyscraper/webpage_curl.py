import logging
import subprocess
from functools import cached_property

from pyscraper.webpage import WebPage


logger = logging.getLogger(__name__)


class WebPageCurl(WebPage):
    @cached_property
    def html(self):
        return subprocess.run(
            ["curl", self.url], stdout=subprocess.PIPE, stderr=subprocess.DEVNULL
        ).stdout.decode()
