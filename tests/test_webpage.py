import os

import pytest

from pyscraper.webpage import (
    WebPageChrome,
    WebPageCurl,
    WebPageFirefox,
    WebPageNoSuchElementError,
    WebPageRequests,
    WebPageTimeoutError,
)


@pytest.fixture
def url():
    return "https://temeteke.github.io/pyscraper/tests/testdata/test.html"


class MixinTestWebPage:
    def test_url_01(self, webpage, url):
        assert webpage.url == url

    def test_url_02(self, webpage):
        webpage.url = "https://temeteke.github.io/pyscraper/tests/testdata/test2.html"
        assert webpage.url == "https://temeteke.github.io/pyscraper/tests/testdata/test2.html"

    def test_encoding_01(self, webpage):
        assert webpage.encoding == "utf-8"

    def test_encoding_02(self, webpage):
        webpage.encoding = "euc-jp"
        assert webpage.encoding == "euc-jp"

    def test_get_01(self, webpage):
        assert webpage.get("//a[@id='link']")

    def test_get_02(self, webpage):
        assert webpage.get("//a[@id='link_']") == []

    def test_get_html_01(self, webpage):
        assert webpage.get("//p")[0].html == "<p>paragraph 1<a>link 1</a></p>"

    def test_get_inner_html_01(self, webpage):
        assert webpage.get("//p")[0].inner_html == "paragraph 1<a>link 1</a>"

    def test_get_text_01(self, webpage):
        assert webpage.get("//p")[0].text == "paragraph 1"

    def test_get_inner_text_01(self, webpage):
        assert webpage.get("//p")[0].inner_text == "paragraph 1link 1"

    def test_get_itertext_01(self, webpage):
        assert list(webpage.get("//p")[0].itertext()) == ["paragraph 1", "link 1"]

    def test_get_atrib_01(self, webpage):
        assert webpage.get("//a[@id='link']")[0].attrib["id"] == "link"

    def test_get_get_01(self, webpage):
        assert webpage.get("//body")[0].get("a[@id='link']")

    def test_get_get_text_01(self, webpage):
        assert webpage.get("//body")[0].get("a[@id='link']")[0].text == "test2"

    def test_get_xpath_01(self, webpage):
        assert webpage.get("//a[@id='link']")[0].xpath("@href") == ["test2.html"]

    def test_xpath_01(self, webpage):
        assert webpage.xpath("//h1/text()")[0] == "Header"


class MixinTestWebPageSelenium:
    def test_wait_01(self, webpage):
        webpage.wait("//h1")

    def test_get_timeout_01(self, webpage):
        assert webpage.get("//a[@id='link']", timeout=0)

    def test_get_timeout_02(self, webpage):
        assert webpage.get("//a[@id='link_']", timeout=0) == []

    def test_get_timeout_03(self, webpage):
        with pytest.raises(WebPageTimeoutError):
            webpage.get("//a[@id='link_']", timeout=1)

    def test_get_wait_01(self, webpage):
        webpage.get("//body")[0].wait("a[@id='link']")

    def test_get_click_01(self, webpage):
        webpage.get("//a[@id='link']")[0].click()
        assert webpage.url.endswith("test2.html")

    def test_get_click_timeout_01(self, webpage):
        webpage.get("//a[@id='link']")[0].click(timeout=0)

    def test_get_click_timeout_02(self, webpage):
        webpage.get("//a[@id='link']")[0].click(timeout=1)

    def test_get_mouse_over_01(self, webpage):
        webpage.get("//a[@id='link']")[0].mouse_over()

    def test_get_scroll_01(self, webpage):
        webpage.get("//a[@id='link']")[0].scroll()

    def test_get_switch_01(self, webpage):
        assert webpage.get("//title")[0].inner_text == "Title"
        with webpage.get("//iframe")[0].switch():
            assert webpage.get("//title")[0].inner_text == "Title 2"
        assert webpage.get("//title")[0].inner_text == "Title"

    def test_click_01(self, webpage):
        webpage.click("//a[@id='link']")
        assert webpage.url.endswith("test2.html")

    def test_click_02(self, webpage):
        with pytest.raises(WebPageNoSuchElementError):
            webpage.click("//a[@id='link_']")

    def test_go_01(self, webpage):
        webpage.go("https://temeteke.github.io/pyscraper/tests/testdata/test2.html")
        assert webpage.url == "https://temeteke.github.io/pyscraper/tests/testdata/test2.html"

    def test_go_02(self, webpage):
        webpage.go(
            "https://temeteke.github.io/pyscraper/tests/testdata/test2.html",
            params={"param": "value"},
        )
        assert (
            webpage.url
            == "https://temeteke.github.io/pyscraper/tests/testdata/test2.html?param=value"
        )

    def test_dump_01(self, webpage):
        files = webpage.dump()
        for f in files:
            assert f.exists()
            f.unlink()


class TestWebPageRequests(MixinTestWebPage):
    @pytest.fixture
    def webpage(self, url):
        with WebPageRequests(url) as wp:
            yield wp

    def test_eq_01(self, webpage, url):
        assert webpage == WebPageRequests(url)

    def test_params_01(self, url):
        assert WebPageRequests(url, params={"param1": 1}).url == url + "?param1=1"

    def test_dump_01(self, webpage):
        f = webpage.dump()
        assert f.exists()
        f.unlink()

    def test_url_redirect(self):
        assert (
            WebPageRequests("https://httpbin.org/redirect-to?url=https%3A%2F%2Fhttpbin.org").url
            == "https://httpbin.org"
        )

    def test_headers(self):
        assert (
            WebPageRequests("https://httpbin.org/headers", headers={"test": "test"}).headers[
                "test"
            ]
            == "test"
        )

    def test_cookies(self):
        assert (
            WebPageRequests("https://httpbin.org/cookies", cookies={"test": "test"}).cookies[
                "test"
            ]
            == "test"
        )


class TestWebPageFirefox(MixinTestWebPage, MixinTestWebPageSelenium):
    @pytest.fixture
    def webpage(self, url):
        with WebPageFirefox(url) as wp:
            yield wp

    def test_proxy_01(self, url):
        os.environ["HTTP_PROXY"] = "proxy_url"
        os.environ["HTTPS_PROXY"] = "proxy_url"
        os.environ["NO_PROXY"] = "no_proxy_01"
        with WebPageFirefox(url):
            pass
        del os.environ["HTTP_PROXY"]
        del os.environ["HTTPS_PROXY"]
        del os.environ["NO_PROXY"]

    def test_proxy_02(self, url):
        os.environ["HTTP_PROXY"] = "proxy_url"
        os.environ["HTTPS_PROXY"] = "proxy_url"
        os.environ["NO_PROXY"] = "no_proxy_01,no_proxy_02"
        with WebPageFirefox(url):
            pass
        del os.environ["HTTP_PROXY"]
        del os.environ["HTTPS_PROXY"]
        del os.environ["NO_PROXY"]


class TestWebPageChrome(MixinTestWebPage, MixinTestWebPageSelenium):
    @pytest.fixture
    def webpage(self, url):
        with WebPageChrome(url) as wp:
            yield wp

    def test_proxy_01(self, url):
        os.environ["HTTP_PROXY"] = "proxy_url"
        os.environ["HTTPS_PROXY"] = "proxy_url"
        os.environ["NO_PROXY"] = "no_proxy_01"
        with WebPageChrome(url):
            pass
        del os.environ["HTTP_PROXY"]
        del os.environ["HTTPS_PROXY"]
        del os.environ["NO_PROXY"]

    def test_proxy_02(self, url):
        os.environ["HTTP_PROXY"] = "proxy_url"
        os.environ["HTTPS_PROXY"] = "proxy_url"
        os.environ["NO_PROXY"] = "no_proxy_01,no_proxy_02"
        with WebPageChrome(url):
            pass
        del os.environ["HTTP_PROXY"]
        del os.environ["HTTPS_PROXY"]
        del os.environ["NO_PROXY"]


class TestWebPageCurl(MixinTestWebPage):
    @pytest.fixture
    def webpage(self, url):
        with WebPageCurl(url) as wp:
            yield wp
