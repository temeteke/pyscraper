import unittest

import pytest

from pyscraper import (WebPageChrome, WebPageCurl, WebPageFirefox,
                       WebPageRequests)


@pytest.fixture
def url():
    return 'https://temeteke.github.io/pyscraper/tests/testdata/test.html'


class MixinTestWebPage:
    def test_get01(self, webpage):
        assert webpage.get("//h1/text()")[0] == "Header"

    def test_get_html01(self, webpage):
        assert webpage.get_html("//p") == [
            '<p>paragraph 1<a>link 1</a></p>',
            '<p>paragraph 2<a>link 2</a></p>'
        ]

    def test_get_innerhtml01(self, webpage):
        assert webpage.get_innerhtml("//p") == [
            'paragraph 1<a>link 1</a>',
            'paragraph 2<a>link 2</a>'
        ]

    def test_xpath01(self, webpage):
        assert webpage.xpath("//h1/text()")[0] == "Header"


class MixinTestWebPageSelenium:
    def test_dump01(self, webpage):
        files = webpage.dump()
        for f in files:
            assert f.exists()
            f.unlink()


class TestWebPageRequests(MixinTestWebPage):
    @pytest.fixture
    def webpage(self, url):
        with WebPageRequests(url) as wp:
            yield wp

    def test_eq01(self, webpage, url):
        assert webpage == WebPageRequests(url)
    
    def test_params01(self, url):
        assert WebPageRequests(url, params={'param1': 1}).url == url + '?param1=1'

    def test_dump01(self, webpage):
        f = webpage.dump()
        assert f.exists()
        f.unlink()


class TestWebPageFirefox(MixinTestWebPage, MixinTestWebPageSelenium):
    @pytest.fixture
    def webpage(self, url):
        with WebPageFirefox(url) as wp:
            yield wp


class TestWebPageChrome(MixinTestWebPage, MixinTestWebPageSelenium):
    @pytest.fixture
    def webpage(self, url):
        with WebPageChrome(url) as wp:
            yield wp


class TestWebPageCurl(MixinTestWebPage):
    @pytest.fixture
    def webpage(self, url):
        with WebPageCurl(url) as wp:
            yield wp
