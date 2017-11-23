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

    @classmethod
    def _get_webfile(cls, url):
        return WebFile(url)

    @classmethod
    def setUpClass(cls):
        logger.debug('setUpClass')
        cls.content = requests.get(cls.URL).content
        cls.wf = cls._get_webfile(cls.URL)

    def test_read01(self):
        logger.debug('test_read01')
        self.wf.seek(0)
        self.assertEqual(self.content[:128], self.wf.read(128))

    def test_read02(self):
        logger.debug('test_read02')
        self.wf.seek(512)
        self.assertEqual(self.content[512:640], self.wf.read(128))

    def test_read03(self):
        logger.debug('test_read03')
        self.wf.seek(576)
        self.assertEqual(self.content[576:704], self.wf.read(128))

    def test_read04(self):
        logger.debug('test_read04')
        self.wf.seek(256)
        self.assertEqual(self.content[256:], self.wf.read())

class TestWebFileCached(TestWebFile):
    @classmethod
    def _get_webfile(cls, url):
        return WebFileCached(url)

class TestWebFileCached2(TestWebFileCached):
    def test_read05(self):
        logger.debug('test_read05')
        self.wf.seek(128)
        self.assertEqual(self.content[128:256], self.wf.read(128))
