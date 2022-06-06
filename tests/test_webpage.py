import unittest

from pyscraper import (WebPageChrome, WebPageCurl, WebPageFirefox,
                       WebPageRequests)


class MixinTestWebPage:
    URL = 'https://temeteke.github.io/pyscraper/tests/testdata/test.html'

    @classmethod
    def setUpClass(cls):
        cls.webpage = cls.webpage_class(cls.URL)
        cls.webpage.open()

    @classmethod
    def tearDownClass(cls):
        cls.webpage.close()

    def test_eq01(self):
        self.assertEqual(self.webpage, self.webpage_class(self.URL))

    def test_get01(self):
        self.assertEqual("Header", self.webpage.get("//h1/text()")[0])

    def test_get_html01(self):
        self.assertEqual([
            '<p>paragraph 1<a>link 1</a></p>',
            '<p>paragraph 2<a>link 2</a></p>'
        ], self.webpage.get_html("//p"))

    def test_get_innerhtml01(self):
        self.assertEqual([
            'paragraph 1<a>link 1</a>',
            'paragraph 2<a>link 2</a>'
        ], self.webpage.get_innerhtml("//p"))

    def test_xpath01(self):
        self.assertEqual("Header", self.webpage.xpath("//h1/text()")[0])


class MixinTestWebPageSelenium:
    def test_dump01(self):
        files = self.webpage.dump()
        for f in files:
            self.assertTrue(f.exists())
            f.unlink()


class TestWebPageRequests(MixinTestWebPage, unittest.TestCase):
    webpage_class = WebPageRequests

    def test_dump01(self):
        f = self.webpage.dump()
        self.assertTrue(f.exists())
        f.unlink()


class TestWebPageFirefox(MixinTestWebPage, MixinTestWebPageSelenium, unittest.TestCase):
    webpage_class = WebPageFirefox


class TestWebPageChrome(MixinTestWebPage, MixinTestWebPageSelenium, unittest.TestCase):
    webpage_class = WebPageChrome


class TestWebPageCurl(MixinTestWebPage, unittest.TestCase):
    webpage_class = WebPageCurl
