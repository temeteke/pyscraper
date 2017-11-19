import unittest
from pyscraper import WebFile, WebFileCached
import requests

import logging

logger = logging.getLogger('pyscraper')
logger.setLevel(logging.DEBUG)

fh = logging.FileHandler(filename='test_pyscraper.log')
fh.setFormatter(logging.Formatter("%(asctime)s %(name)s %(levelname)8s %(message)s"))
logger.addHandler(fh)

class TestWebFile(unittest.TestCase):
    URL = 'https://httpbin.org/range/1024'

    def _get_webfile(self, url):
        return WebFile(url)

    def setUp(self):
        self.content = requests.get(TestWebFile.URL).content
        self.wf = self._get_webfile(TestWebFile.URL)

    def test_read01(self):
        self.wf.seek(0)
        self.assertEqual(self.wf.read(), self.content)

    def test_read02(self):
        self.wf.seek(0)
        self.assertEqual(self.wf.read(128), self.content[:128])

    def test_read03(self):
        self.wf.seek(128)
        self.assertEqual(self.wf.read(), self.content[128:])

class TestWebFileCached(TestWebFile):
    def _get_webfile(self, URL):
        return WebFileCached(URL)
