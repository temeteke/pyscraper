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
    def test_url_01(self, web_page_instance, url):
        assert web_page_instance.url == url

    def test_url_02(self, web_page_instance):
        web_page_instance.url = "https://temeteke.github.io/pyscraper/tests/testdata/test2.html"
        assert (
            web_page_instance.url
            == "https://temeteke.github.io/pyscraper/tests/testdata/test2.html"
        )

    def test_encoding_01(self, web_page_instance):
        assert web_page_instance.encoding == "utf-8"

    def test_encoding_02(self, web_page_instance):
        web_page_instance.encoding = "euc-jp"
        assert web_page_instance.encoding == "euc-jp"

    def test_get_01(self, web_page_instance):
        assert web_page_instance.get("//a[@id='link']")

    def test_get_02(self, web_page_instance):
        assert web_page_instance.get("//a[@id='link_']") == []

    def test_get_html_01(self, web_page_instance):
        assert web_page_instance.get("//p")[0].html == "<p>paragraph 1<a>link 1</a></p>"

    def test_get_inner_html_01(self, web_page_instance):
        assert web_page_instance.get("//p")[0].inner_html == "paragraph 1<a>link 1</a>"

    def test_get_text_01(self, web_page_instance):
        assert web_page_instance.get("//p")[0].text == "paragraph 1"

    def test_get_inner_text_01(self, web_page_instance):
        assert web_page_instance.get("//p")[0].inner_text == "paragraph 1link 1"

    def test_get_itertext_01(self, web_page_instance):
        assert list(web_page_instance.get("//p")[0].itertext()) == ["paragraph 1", "link 1"]

    def test_get_atrib_01(self, web_page_instance):
        assert web_page_instance.get("//a[@id='link']")[0].attrib["id"] == "link"

    def test_get_get_01(self, web_page_instance):
        assert web_page_instance.get("//body")[0].get("a[@id='link']")

    def test_get_get_text_01(self, web_page_instance):
        assert web_page_instance.get("//body")[0].get("a[@id='link']")[0].text == "test2"

    def test_get_xpath_01(self, web_page_instance):
        assert web_page_instance.get("//a[@id='link']")[0].xpath("@href") == ["test2.html"]

    def test_xpath_01(self, web_page_instance):
        assert web_page_instance.xpath("//h1/text()")[0] == "Header"


class MixinTestWebPageOpenClose:
    def test_url_close(self, web_page_class):
        assert (
            web_page_class("https://httpbin.org/redirect-to?url=https%3A%2F%2Fhttpbin.org%2F").url
            == "https://httpbin.org/redirect-to?url=https%3A%2F%2Fhttpbin.org%2F"
        )

    def test_url_open(self, web_page_class):
        with web_page_class(
            "https://httpbin.org/redirect-to?url=https%3A%2F%2Fhttpbin.org%2F"
        ) as wp:
            assert wp.url == "https://httpbin.org/"

    def test_cookies_close(self, web_page_class):
        assert (
            web_page_class("https://httpbin.org/cookies", cookies={"test": "test"}).cookies["test"]
            == "test"
        )

    def test_cookies_open(self, web_page_class):
        with web_page_class("https://httpbin.org/cookies", cookies={"test": "test"}) as wp:
            assert wp.cookies["test"] == "test"


class MixinTestWebPageSelenium:
    def test_wait_01(self, web_page_instance):
        web_page_instance.wait("//h1")

    def test_get_timeout_01(self, web_page_instance):
        assert web_page_instance.get("//a[@id='link']", timeout=0)

    def test_get_timeout_02(self, web_page_instance):
        assert web_page_instance.get("//a[@id='link_']", timeout=0) == []

    def test_get_timeout_03(self, web_page_instance):
        with pytest.raises(WebPageTimeoutError):
            web_page_instance.get("//a[@id='link_']", timeout=1)

    def test_get_wait_01(self, web_page_instance):
        web_page_instance.get("//body")[0].wait("a[@id='link']")

    def test_get_click_01(self, web_page_instance):
        web_page_instance.get("//a[@id='link']")[0].click()
        assert web_page_instance.url.endswith("test2.html")

    def test_get_click_timeout_01(self, web_page_instance):
        web_page_instance.get("//a[@id='link']")[0].click(timeout=0)

    def test_get_click_timeout_02(self, web_page_instance):
        web_page_instance.get("//a[@id='link']")[0].click(timeout=1)

    def test_get_mouse_over_01(self, web_page_instance):
        web_page_instance.get("//a[@id='link']")[0].mouse_over()

    def test_get_scroll_01(self, web_page_instance):
        web_page_instance.get("//a[@id='link']")[0].scroll()

    def test_get_switch_01(self, web_page_instance):
        assert web_page_instance.get("//title")[0].inner_text == "Title"
        with web_page_instance.get("//iframe")[0].switch():
            assert web_page_instance.get("//title")[0].inner_text == "Title 2"
        assert web_page_instance.get("//title")[0].inner_text == "Title"

    def test_click_01(self, web_page_instance):
        web_page_instance.click("//a[@id='link']")
        assert web_page_instance.url.endswith("test2.html")

    def test_click_02(self, web_page_instance):
        with pytest.raises(WebPageNoSuchElementError):
            web_page_instance.click("//a[@id='link_']")

    def test_go_01(self, web_page_instance):
        web_page_instance.go("https://temeteke.github.io/pyscraper/tests/testdata/test2.html")
        assert (
            web_page_instance.url
            == "https://temeteke.github.io/pyscraper/tests/testdata/test2.html"
        )

    def test_go_02(self, web_page_instance):
        web_page_instance.go(
            "https://temeteke.github.io/pyscraper/tests/testdata/test2.html",
            params={"param": "value"},
        )
        assert (
            web_page_instance.url
            == "https://temeteke.github.io/pyscraper/tests/testdata/test2.html?param=value"
        )

    def test_dump_01(self, web_page_instance):
        files = web_page_instance.dump()
        for f in files:
            assert f.exists()
            f.unlink()

    def test_proxy_01(self, web_page_class, url):
        os.environ["HTTP_PROXY"] = "proxy_url"
        os.environ["HTTPS_PROXY"] = "proxy_url"
        os.environ["NO_PROXY"] = "no_proxy_01"
        with web_page_class(url):
            pass
        del os.environ["HTTP_PROXY"]
        del os.environ["HTTPS_PROXY"]
        del os.environ["NO_PROXY"]

    def test_proxy_02(self, web_page_class, url):
        os.environ["HTTP_PROXY"] = "proxy_url"
        os.environ["HTTPS_PROXY"] = "proxy_url"
        os.environ["NO_PROXY"] = "no_proxy_01,no_proxy_02"
        with web_page_class(url):
            pass
        del os.environ["HTTP_PROXY"]
        del os.environ["HTTPS_PROXY"]
        del os.environ["NO_PROXY"]


class TestWebPageRequests(MixinTestWebPage, MixinTestWebPageOpenClose):
    @pytest.fixture
    def web_page_class(self):
        return WebPageRequests

    @pytest.fixture
    def web_page_instance(self, web_page_class, url):
        with web_page_class(url) as wp:
            yield wp

    def test_encoding_01(self, web_page_instance):
        assert web_page_instance.encoding == "utf-8"

    def test_encoding_02(self, web_page_instance):
        web_page_instance.encoding = "euc-jp"
        assert web_page_instance.encoding == "euc-jp"

    def test_eq_01(self, web_page_instance, url):
        assert web_page_instance == WebPageRequests(url)

    def test_params_01(self, url):
        assert WebPageRequests(url, params={"param1": 1}).url == url + "?param1=1"

    def test_dump_01(self, web_page_instance):
        f = web_page_instance.dump()
        assert f.exists()
        f.unlink()

    def test_headers_close(self, web_page_class):
        assert (
            web_page_class("https://httpbin.org/headers", headers={"test": "test"}).headers["test"]
            == "test"
        )

    def test_headers_open(self, web_page_class):
        with web_page_class("https://httpbin.org/headers", headers={"test": "test"}) as wp:
            assert wp.headers["test"] == "test"


class TestWebPageFirefox(MixinTestWebPage, MixinTestWebPageOpenClose, MixinTestWebPageSelenium):
    @pytest.fixture
    def web_page_class(self):
        return WebPageFirefox

    @pytest.fixture
    def web_page_instance(self, web_page_class, url):
        with web_page_class(url) as wp:
            yield wp

    def test_language(self):
        with WebPageFirefox("https://httpbin.org/headers", language="ja") as wp:
            assert wp.execute_script("return window.navigator.languages") == ["ja"]


class TestWebPageChrome(MixinTestWebPage, MixinTestWebPageOpenClose, MixinTestWebPageSelenium):
    @pytest.fixture
    def web_page_class(self):
        return WebPageChrome

    @pytest.fixture
    def web_page_instance(self, web_page_class, url):
        with web_page_class(url) as wp:
            yield wp


class TestWebPageCurl(MixinTestWebPage):
    @pytest.fixture
    def web_page_class(self):
        return WebPageCurl

    @pytest.fixture
    def web_page_instance(self, web_page_class, url):
        with web_page_class(url) as wp:
            yield wp
