import os
import pytest
import requests

from pyscraper import (WebPageChrome, WebPageCurl, WebPageFirefox,
                       WebPageRequests)
from pyscraper.webpage import WebPageParser


@pytest.fixture
def url():
    return 'https://temeteke.github.io/pyscraper/tests/testdata/test.html'


class TestWebPageParser:
    @pytest.fixture
    def source(self, url):
        return requests.get(url).text

    @pytest.fixture
    def webpage(self, source):
        return WebPageParser(source=source)

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


class MixinTestWebPage:
    def test_get01(self, webpage):
        assert webpage.get("//h1/text()")[0] == "Header"


class MixinTestWebPageSelenium:
    def test_click01(self, webpage):
        webpage.click("//a[@id='link']")
        assert webpage.url.endswith('test2.html')

    def test_go01(self, webpage):
        webpage.go("https://temeteke.github.io/pyscraper/tests/testdata/test2.html")
        assert webpage.url == "https://temeteke.github.io/pyscraper/tests/testdata/test2.html"

    def test_go02(self, webpage):
        webpage.go("https://temeteke.github.io/pyscraper/tests/testdata/test2.html", params={'param': 'value'})
        assert webpage.url == "https://temeteke.github.io/pyscraper/tests/testdata/test2.html?param=value"

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

    def test_proxy_01(self, url):
        os.environ['HTTP_PROXY'] = 'proxy_url'
        os.environ['HTTPS_PROXY'] = 'proxy_url'
        os.environ['NO_PROXY'] = 'no_proxy_01'
        with WebPageFirefox(url):
            pass
        del os.environ['HTTP_PROXY']
        del os.environ['HTTPS_PROXY']
        del os.environ['NO_PROXY']

    def test_proxy_02(self, url):
        os.environ['HTTP_PROXY'] = 'proxy_url'
        os.environ['HTTPS_PROXY'] = 'proxy_url'
        os.environ['NO_PROXY'] = 'no_proxy_01,no_proxy_02'
        with WebPageFirefox(url):
            pass
        del os.environ['HTTP_PROXY']
        del os.environ['HTTPS_PROXY']
        del os.environ['NO_PROXY']


class TestWebPageChrome(MixinTestWebPage, MixinTestWebPageSelenium):
    @pytest.fixture
    def webpage(self, url):
        with WebPageChrome(url) as wp:
            yield wp

    def test_proxy_01(self, url):
        os.environ['HTTP_PROXY'] = 'proxy_url'
        os.environ['HTTPS_PROXY'] = 'proxy_url'
        os.environ['NO_PROXY'] = 'no_proxy_01'
        with WebPageChrome(url):
            pass
        del os.environ['HTTP_PROXY']
        del os.environ['HTTPS_PROXY']
        del os.environ['NO_PROXY']

    def test_proxy_02(self, url):
        os.environ['HTTP_PROXY'] = 'proxy_url'
        os.environ['HTTPS_PROXY'] = 'proxy_url'
        os.environ['NO_PROXY'] = 'no_proxy_01,no_proxy_02'
        with WebPageChrome(url):
            pass
        del os.environ['HTTP_PROXY']
        del os.environ['HTTPS_PROXY']
        del os.environ['NO_PROXY']


class TestWebPageCurl(MixinTestWebPage):
    @pytest.fixture
    def webpage(self, url):
        with WebPageCurl(url) as wp:
            yield wp
