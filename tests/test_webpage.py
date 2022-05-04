import unittest

from pyscraper import (WebPageChrome, WebPageCurl, WebPageFirefox,
                       WebPageRequests)


class TestWebPageMxin():
    URL = 'https://temeteke.github.io/pyscraper/tests/testdata/test.html'

    def test_get01(self):
        self.assertEqual("Header", self.wp.get("//h1/text()")[0])

    def test_get_html01(self):
        self.assertEqual([
            '<p>paragraph 1<a>link 1</a></p>',
            '<p>paragraph 2<a>link 2</a></p>'
        ], self.wp.get_html("//p"))

    def test_get_innerhtml01(self):
        self.assertEqual([
            'paragraph 1<a>link 1</a>',
            'paragraph 2<a>link 2</a>'
        ], self.wp.get_innerhtml("//p"))

    def test_xpath01(self):
        self.assertEqual("Header", self.wp.xpath("//h1/text()")[0])


class TestWebPageSeleniumMxin():
    def test_dump01(self):
        files = self.wp.dump()
        for f in files:
            self.assertTrue(f.exists())
            f.unlink()


class TestWebPageRequests(TestWebPageMxin, unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.wp = WebPageRequests(cls.URL)
        cls.wp.open()

    @classmethod
    def tearDownClass(cls):
        cls.wp.close()

    def test_dump01(self):
        f = self.wp.dump()
        self.assertTrue(f.exists())
        f.unlink()


class TestWebPageFirefox(TestWebPageMxin, TestWebPageSeleniumMxin, unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.wp = WebPageFirefox(cls.URL)
        cls.wp.open()

    @classmethod
    def tearDownClass(cls):
        cls.wp.close()


class TestWebPageChrome(TestWebPageMxin, TestWebPageSeleniumMxin, unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.wp = WebPageChrome(cls.URL)
        cls.wp.open()

    @classmethod
    def tearDownClass(cls):
        cls.wp.close()


class TestWebPageCurl(TestWebPageMxin, unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.wp = WebPageCurl(cls.URL)
        cls.wp.open()

    @classmethod
    def tearDownClass(cls):
        cls.wp.close()
