import unittest
from pyscraper import WebPageRequests, WebPageFirefox, WebPageChrome, WebPageCurl
from pathlib import Path


class TestWebPageRequests(unittest.TestCase):
    URL = 'https://temeteke.github.io/pyscraper/tests/testdata/test.html'

    @classmethod
    def setUpClass(cls):
        cls.wp = WebPageRequests(cls.URL)
        cls.wp.open()

    @classmethod
    def tearDownClass(cls):
        cls.wp.close()

    def test_get01(self):
        self.assertEqual("Header", self.wp.get("//h1/text()")[0])

#   def test_get_html01(self):
#       self.assertEqual([
#           '<p>paragraph 1</p>',
#           '<p>paragraph 2</p>'
#       ], self.wp.get_html("//p"))

    def test_get_innerhtml01(self):
        self.assertEqual([
            'paragraph 1',
            'paragraph 2'
        ], self.wp.get_innerhtml("//p"))

    def test_xpath01(self):
        self.assertEqual("Header", self.wp.xpath("//h1/text()")[0])

    def test_dump01(self):
        self.wp.dump('dump')
        self.assertTrue(Path('dump.html').exists())
        Path('dump.html').unlink()


class TestWebPageFirefox(TestWebPageRequests):
    @classmethod
    def setUpClass(cls):
        cls.wp = WebPageFirefox(cls.URL)
        cls.wp.open()

    def test_dump01(self):
        self.wp.dump('dump')
        self.assertTrue(Path('dump.html').exists())
        self.assertTrue(Path('dump_0.png').exists())
        Path('dump.html').unlink()
        for x in Path('.').glob('dump_*.png'):
            x.unlink()


class TestWebPageChrome(TestWebPageFirefox):
    @classmethod
    def setUpClass(cls):
        cls.wp = WebPageChrome(cls.URL)
        cls.wp.open()


class TestWebPageCurl(TestWebPageRequests):
    @classmethod
    def setUpClass(cls):
        cls.wp = WebPageCurl(cls.URL)
        cls.wp.open()
