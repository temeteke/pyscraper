import os
from unittest.mock import patch

import pytest
import requests

from pyscraper.webpage import WebPageError, WebPageNoSuchElementError, WebPageTimeoutError
from pyscraper.webpage_curl import WebPageCurl
from pyscraper.webpage_requests import WebPageRequests
from pyscraper.webpage_selenium import WebPageChrome, WebPageFirefox


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

    def test_bare_param_preserved(self):
        url = "https://example.com/?key"
        assert WebPageRequests(url).url == url

    def test_bare_param_preserved_multiple(self):
        url = "https://example.com/?key&flag"
        assert WebPageRequests(url).url == url

    def test_bare_param_with_value_param_not_lost(self):
        url = "https://example.com/?key=value"
        assert WebPageRequests(url).url == url

    def test_mixed_bare_and_keyvalue(self):
        assert WebPageRequests("https://example.com/?flag&key=value").url == "https://example.com/?flag&key=value"

    def test_params_with_existing_query(self):
        assert WebPageRequests("https://example.com/?a=1", params={"b": 2}).url == "https://example.com/?a=1&b=2"

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

    def test_session(self, web_page_class):
        session = requests.Session()
        session.headers["test"] = "test"
        assert (
            web_page_class("https://httpbin.org/headers", session=session).headers["test"]
            == "test"
        )


@pytest.mark.integration
class TestWebPageFirefox(MixinTestWebPage, MixinTestWebPageOpenClose, MixinTestWebPageSelenium):
    """Integration tests using Firefox browser automation."""

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


@pytest.mark.integration
class TestWebPageChrome(MixinTestWebPage, MixinTestWebPageOpenClose, MixinTestWebPageSelenium):
    """Integration tests using Chrome browser automation."""

    @pytest.fixture
    def web_page_class(self):
        return WebPageChrome

    @pytest.fixture
    def web_page_instance(self, web_page_class, url):
        with web_page_class(url) as wp:
            yield wp


@pytest.mark.integration
class TestWebPageCurl(MixinTestWebPage):
    """Integration tests for WebPageCurl using actual curl command.

    WebPageCurl is a thin wrapper around subprocess.run(['curl', url]).
    These tests execute real curl commands and may fail in environments
    where test URLs are inaccessible (e.g., firewall restrictions).

    Run with: pytest tests/test_webpage.py::TestWebPageCurl -m integration -v
    """

    @pytest.fixture
    def web_page_class(self):
        return WebPageCurl

    @pytest.fixture
    def web_page_instance(self, web_page_class, url):
        with web_page_class(url) as wp:
            yield wp


class TestConfigureNoProxyForRemote:
    """Unit tests for WebPageSelenium._configure_no_proxy_for_remote.

    Tests that the method correctly updates lowercase 'no_proxy' and
    uppercase 'NO_PROXY' env vars when using remote Selenium WebDriver.
    """

    def _cleanup_env(self, keys):
        for key in keys:
            os.environ.pop(key, None)

    def _set_env_and_run(self, env_vars, page_class, url):
        saved = {}
        for key, value in env_vars.items():
            saved[key] = os.environ.get(key)
            if value is None:
                os.environ.pop(key, None)
            else:
                os.environ[key] = value
        try:
            with patch("pyscraper.webpage_selenium.webdriver.Remote"):
                with page_class(url):
                    pass
        finally:
            for key, value in saved.items():
                if value is None:
                    os.environ.pop(key, None)
                else:
                    os.environ[key] = value

    def test_lowercase_updated(self):
        saved_no_proxy = os.environ.get("no_proxy")
        saved_NO_PROXY = os.environ.get("NO_PROXY")
        saved_ff_url = os.environ.get("SELENIUM_FIREFOX_URL")
        saved_http = os.environ.get("HTTP_PROXY")
        saved_https = os.environ.get("HTTPS_PROXY")
        try:
            os.environ["SELENIUM_FIREFOX_URL"] = "http://firefox:4444/wd/hub"
            os.environ["no_proxy"] = "localhost,127.0.0.1"
            os.environ["NO_PROXY"] = "localhost,127.0.0.1"
            os.environ.pop("HTTP_PROXY", None)
            os.environ.pop("HTTPS_PROXY", None)
            with patch("pyscraper.webpage_selenium.webdriver.Remote"):
                with WebPageFirefox("http://example.com"):
                    pass
            assert "firefox:4444" in os.environ["no_proxy"]
            assert "firefox:4444" in os.environ["NO_PROXY"]
        finally:
            for k, v in [("no_proxy", saved_no_proxy), ("NO_PROXY", saved_NO_PROXY),
                         ("SELENIUM_FIREFOX_URL", saved_ff_url),
                         ("HTTP_PROXY", saved_http), ("HTTPS_PROXY", saved_https)]:
                if v is None:
                    os.environ.pop(k, None)
                else:
                    os.environ[k] = v

    def test_uppercase_only(self):
        saved_no_proxy = os.environ.get("no_proxy")
        saved_NO_PROXY = os.environ.get("NO_PROXY")
        saved_ff_url = os.environ.get("SELENIUM_FIREFOX_URL")
        saved_http = os.environ.get("HTTP_PROXY")
        saved_https = os.environ.get("HTTPS_PROXY")
        try:
            os.environ["SELENIUM_FIREFOX_URL"] = "http://firefox:4444/wd/hub"
            os.environ.pop("no_proxy", None)
            os.environ["NO_PROXY"] = "localhost,127.0.0.1"
            os.environ.pop("HTTP_PROXY", None)
            os.environ.pop("HTTPS_PROXY", None)
            with patch("pyscraper.webpage_selenium.webdriver.Remote"):
                with WebPageFirefox("http://example.com"):
                    pass
            assert "firefox:4444" in os.environ["no_proxy"]
            assert "firefox:4444" in os.environ["NO_PROXY"]
        finally:
            for k, v in [("no_proxy", saved_no_proxy), ("NO_PROXY", saved_NO_PROXY),
                         ("SELENIUM_FIREFOX_URL", saved_ff_url),
                         ("HTTP_PROXY", saved_http), ("HTTPS_PROXY", saved_https)]:
                if v is None:
                    os.environ.pop(k, None)
                else:
                    os.environ[k] = v

    def test_neither_set(self):
        saved_no_proxy = os.environ.get("no_proxy")
        saved_NO_PROXY = os.environ.get("NO_PROXY")
        saved_ff_url = os.environ.get("SELENIUM_FIREFOX_URL")
        saved_http = os.environ.get("HTTP_PROXY")
        saved_https = os.environ.get("HTTPS_PROXY")
        try:
            os.environ["SELENIUM_FIREFOX_URL"] = "http://firefox:4444/wd/hub"
            os.environ.pop("no_proxy", None)
            os.environ.pop("NO_PROXY", None)
            os.environ.pop("HTTP_PROXY", None)
            os.environ.pop("HTTPS_PROXY", None)
            with patch("pyscraper.webpage_selenium.webdriver.Remote"):
                with WebPageFirefox("http://example.com"):
                    pass
            assert os.environ["no_proxy"] == "firefox:4444"
            assert os.environ["NO_PROXY"] == "firefox:4444"
        finally:
            for k, v in [("no_proxy", saved_no_proxy), ("NO_PROXY", saved_NO_PROXY),
                         ("SELENIUM_FIREFOX_URL", saved_ff_url),
                         ("HTTP_PROXY", saved_http), ("HTTPS_PROXY", saved_https)]:
                if v is None:
                    os.environ.pop(k, None)
                else:
                    os.environ[k] = v

    def test_duplicate_not_added(self):
        saved_no_proxy = os.environ.get("no_proxy")
        saved_NO_PROXY = os.environ.get("NO_PROXY")
        saved_ff_url = os.environ.get("SELENIUM_FIREFOX_URL")
        saved_http = os.environ.get("HTTP_PROXY")
        saved_https = os.environ.get("HTTPS_PROXY")
        try:
            os.environ["SELENIUM_FIREFOX_URL"] = "http://firefox:4444/wd/hub"
            os.environ["no_proxy"] = "firefox:4444"
            os.environ["NO_PROXY"] = "firefox:4444"
            os.environ.pop("HTTP_PROXY", None)
            os.environ.pop("HTTPS_PROXY", None)
            with patch("pyscraper.webpage_selenium.webdriver.Remote"):
                with WebPageFirefox("http://example.com"):
                    pass
            assert os.environ["no_proxy"] == "firefox:4444"
            assert os.environ["NO_PROXY"] == "firefox:4444"
        finally:
            for k, v in [("no_proxy", saved_no_proxy), ("NO_PROXY", saved_NO_PROXY),
                         ("SELENIUM_FIREFOX_URL", saved_ff_url),
                         ("HTTP_PROXY", saved_http), ("HTTPS_PROXY", saved_https)]:
                if v is None:
                    os.environ.pop(k, None)
                else:
                    os.environ[k] = v

    def test_chrome_lowercase_updated(self):
        saved_no_proxy = os.environ.get("no_proxy")
        saved_NO_PROXY = os.environ.get("NO_PROXY")
        saved_chrome_url = os.environ.get("SELENIUM_CHROME_URL")
        saved_http = os.environ.get("HTTP_PROXY")
        saved_https = os.environ.get("HTTPS_PROXY")
        try:
            os.environ["SELENIUM_CHROME_URL"] = "http://chrome:9515/wd/hub"
            os.environ["no_proxy"] = "localhost,127.0.0.1"
            os.environ["NO_PROXY"] = "localhost,127.0.0.1"
            os.environ.pop("HTTP_PROXY", None)
            os.environ.pop("HTTPS_PROXY", None)
            with patch("pyscraper.webpage_selenium.webdriver.Remote"):
                with WebPageChrome("http://example.com"):
                    pass
            assert "chrome:9515" in os.environ["no_proxy"]
            assert "chrome:9515" in os.environ["NO_PROXY"]
        finally:
            for k, v in [("no_proxy", saved_no_proxy), ("NO_PROXY", saved_NO_PROXY),
                         ("SELENIUM_CHROME_URL", saved_chrome_url),
                         ("HTTP_PROXY", saved_http), ("HTTPS_PROXY", saved_https)]:
                if v is None:
                    os.environ.pop(k, None)
                else:
                    os.environ[k] = v

    def _assert_firefox_proxy(self, mock_remote, http_proxy=None, https_proxy=None, no_proxy=None):
        mock_remote.assert_called_once()
        _, kwargs = mock_remote.call_args
        opts = kwargs["options"]

        if http_proxy:
            assert opts.proxy.httpProxy == http_proxy
        else:
            assert opts.proxy.httpProxy is None

        if https_proxy:
            assert opts.proxy.sslProxy == https_proxy
        else:
            assert opts.proxy.sslProxy is None

        if no_proxy:
            assert opts.proxy.noProxy == no_proxy
        else:
            assert opts.proxy.noProxy is None

    def test_firefox_proxy_lowercase_only(self):
        saved = {k: os.environ.get(k) for k in ("http_proxy", "https_proxy", "no_proxy",
                  "HTTP_PROXY", "HTTPS_PROXY", "NO_PROXY", "SELENIUM_FIREFOX_URL")}
        try:
            os.environ["SELENIUM_FIREFOX_URL"] = "http://firefox:4444/wd/hub"
            os.environ["http_proxy"] = "http://lower-proxy:80"
            os.environ["https_proxy"] = "http://lower-proxy:80"
            os.environ["no_proxy"] = "localhost,.local"
            os.environ.pop("HTTP_PROXY", None)
            os.environ.pop("HTTPS_PROXY", None)
            os.environ.pop("NO_PROXY", None)
            with patch("pyscraper.webpage_selenium.webdriver.Remote") as mock_remote:
                with WebPageFirefox("http://example.com"):
                    pass
            self._assert_firefox_proxy(mock_remote,
                                        http_proxy="lower-proxy:80",
                                        https_proxy="lower-proxy:80",
                                        no_proxy=["localhost", ".local"])
            assert "firefox:4444" in os.environ["no_proxy"]
            assert "firefox:4444" in os.environ["NO_PROXY"]
        finally:
            for k, v in saved.items():
                os.environ.pop(k, None) if v is None else os.environ.__setitem__(k, v)

    def test_firefox_proxy_both_cases(self):
        saved = {k: os.environ.get(k) for k in ("http_proxy", "https_proxy", "no_proxy",
                  "HTTP_PROXY", "HTTPS_PROXY", "NO_PROXY", "SELENIUM_FIREFOX_URL")}
        try:
            os.environ["SELENIUM_FIREFOX_URL"] = "http://firefox:4444/wd/hub"
            os.environ["http_proxy"] = "http://lower-proxy:80"
            os.environ["https_proxy"] = "http://lower-proxy:80"
            os.environ["no_proxy"] = "localhost,.local"
            os.environ["HTTP_PROXY"] = "http://UPPER-proxy:80"
            os.environ["HTTPS_PROXY"] = "http://UPPER-proxy:80"
            os.environ["NO_PROXY"] = "192.168.1.0/24"
            with patch("pyscraper.webpage_selenium.webdriver.Remote") as mock_remote:
                with WebPageFirefox("http://example.com"):
                    pass
            self._assert_firefox_proxy(mock_remote,
                                        http_proxy="lower-proxy:80",
                                        https_proxy="lower-proxy:80",
                                        no_proxy=["localhost", ".local"])
            assert "firefox:4444" in os.environ["no_proxy"]
            assert "firefox:4444" in os.environ["NO_PROXY"]
        finally:
            for k, v in saved.items():
                os.environ.pop(k, None) if v is None else os.environ.__setitem__(k, v)

    def test_firefox_proxy_uppercase_only(self):
        saved = {k: os.environ.get(k) for k in ("http_proxy", "https_proxy", "no_proxy",
                  "HTTP_PROXY", "HTTPS_PROXY", "NO_PROXY", "SELENIUM_FIREFOX_URL")}
        try:
            os.environ["SELENIUM_FIREFOX_URL"] = "http://firefox:4444/wd/hub"
            os.environ["HTTP_PROXY"] = "http://upper-proxy:80"
            os.environ["HTTPS_PROXY"] = "http://upper-proxy:80"
            os.environ["NO_PROXY"] = "192.168.1.0/24"
            with patch("pyscraper.webpage_selenium.webdriver.Remote") as mock_remote:
                with WebPageFirefox("http://example.com"):
                    pass
            self._assert_firefox_proxy(mock_remote,
                                        http_proxy="upper-proxy:80",
                                        https_proxy="upper-proxy:80",
                                        no_proxy=["192.168.1.0/24"])
            assert "firefox:4444" in os.environ["no_proxy"]
            assert "firefox:4444" in os.environ["NO_PROXY"]
        finally:
            for k, v in saved.items():
                os.environ.pop(k, None) if v is None else os.environ.__setitem__(k, v)

    def test_firefox_proxy_no_scheme_passthrough(self):
        saved = {k: os.environ.get(k) for k in ("http_proxy", "https_proxy", "no_proxy",
                  "HTTP_PROXY", "HTTPS_PROXY", "NO_PROXY", "SELENIUM_FIREFOX_URL")}
        try:
            os.environ["SELENIUM_FIREFOX_URL"] = "http://firefox:4444/wd/hub"
            os.environ["http_proxy"] = "plain-proxy:3128"
            os.environ["https_proxy"] = "plain-proxy:3128"
            os.environ["no_proxy"] = "localhost"
            os.environ.pop("HTTP_PROXY", None)
            os.environ.pop("HTTPS_PROXY", None)
            os.environ.pop("NO_PROXY", None)
            with patch("pyscraper.webpage_selenium.webdriver.Remote") as mock_remote:
                with WebPageFirefox("http://example.com"):
                    pass
            self._assert_firefox_proxy(mock_remote,
                                        http_proxy="plain-proxy:3128",
                                        https_proxy="plain-proxy:3128",
                                        no_proxy=["localhost"])
            assert "firefox:4444" in os.environ["no_proxy"]
            assert "firefox:4444" in os.environ["NO_PROXY"]
        finally:
            for k, v in saved.items():
                os.environ.pop(k, None) if v is None else os.environ.__setitem__(k, v)


class TestWebPageMutableDefaults:
    def test_request_headers_not_shared(self):
        w1 = WebPageRequests("https://a.com")
        w2 = WebPageRequests("https://b.com")
        w1.request_headers["X"] = "1"
        assert "X" not in w2.request_headers

    def test_request_cookies_not_shared(self):
        w1 = WebPageRequests("https://a.com")
        w2 = WebPageRequests("https://b.com")
        w1.request_cookies["session"] = "abc"
        assert "session" not in w2.request_cookies


class TestWebPageElementInnerText:
    def test_inner_text_includes_child_tail(self):
        from pyscraper.webpage import WebPageElement
        import lxml.html
        html = "<div>Hello <b>World</b> and more</div>"
        element = lxml.html.fromstring(html)
        wp_element = WebPageElement(element)
        assert "and more" in wp_element.inner_text

    def test_inner_html_includes_child_tail(self):
        from pyscraper.webpage import WebPageElement
        import lxml.html
        html = "<div>Hello <b>World</b> and more</div>"
        element = lxml.html.fromstring(html)
        wp_element = WebPageElement(element)
        assert "and more" in wp_element.inner_html


class TestWebPageGetInnerhtml:
    def test_get_innerhtml_includes_child_tail(self, url):
        with WebPageRequests(url) as wp:
            results = wp.get_innerhtml("//p")
            assert results
            for result in results:
                assert isinstance(result, str)
