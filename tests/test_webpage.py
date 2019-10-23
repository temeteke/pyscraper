import unittest
from pyscraper import WebPageRequests, WebPageFirefox, WebPageChrome, WebPageCurl

class TestWebPageRequests(unittest.TestCase):
    URL = 'https://httpbin.org/html'

    @classmethod
    def setUpClass(cls):
        cls.wp = WebPageRequests(cls.URL)
        cls.wp.open()

    @classmethod
    def tearDownClass(cls):
        cls.wp.close()

    def test_read01(self):
        self.assertEqual("Herman Melville - Moby-Dick", self.wp.get("//h1/text()")[0])

class TestWebPageFirefox(TestWebPageRequests):
    @classmethod
    def setUpClass(cls):
        cls.wp = WebPageFirefox(cls.URL)
        cls.wp.open()

class TestWebPageChrome(TestWebPageRequests):
    @classmethod
    def setUpClass(cls):
        cls.wp = WebPageChrome(cls.URL)
        cls.wp.open()

class TestWebPageCurl(TestWebPageRequests):
    @classmethod
    def setUpClass(cls):
        cls.wp = WebPageCurl(cls.URL)
        cls.wp.open()
