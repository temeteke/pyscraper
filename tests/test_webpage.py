import contextlib
import json
import logging
import os
import subprocess
from unittest.mock import PropertyMock, patch

import pytest
import requests
from selenium.common.exceptions import NoSuchElementException, TimeoutException
from selenium.webdriver.common.by import By
from selenium.webdriver.remote.webelement import WebElement

from pyscraper.webpage import WebPageNoSuchElementError, WebPageTimeoutError
from pyscraper.webpage_curl import WebPageCurl
from pyscraper.webpage_requests import WebPageRequests
from pyscraper.webpage_selenium import (
    SeleniumWebPageElement,
    WebPageSeleniumChrome,
    WebPageSeleniumFirefox,
)


@pytest.mark.parametrize(
    ("legacy_name", "new_name"),
    [
        ("WebPageChrome", "WebPageSeleniumChrome"),
        ("WebPageFirefox", "WebPageSeleniumFirefox"),
    ],
)
def test_selenium_public_names_and_legacy_aliases(legacy_name, new_name):
    import pyscraper
    from pyscraper import webpage_selenium

    page_class = getattr(webpage_selenium, new_name)
    assert page_class.__name__ == new_name
    assert getattr(webpage_selenium, legacy_name) is page_class
    assert getattr(pyscraper, new_name) is page_class
    assert getattr(pyscraper, legacy_name) is page_class
    assert new_name in pyscraper.__all__
    assert legacy_name in pyscraper.__all__


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
        assert (
            WebPageRequests("https://example.com/?flag&key=value").url
            == "https://example.com/?flag&key=value"
        )

    def test_params_with_existing_query(self):
        assert (
            WebPageRequests("https://example.com/?a=1", params={"b": 2}).url
            == "https://example.com/?a=1&b=2"
        )

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
class TestWebPageSeleniumFirefox(
    MixinTestWebPage, MixinTestWebPageOpenClose, MixinTestWebPageSelenium
):
    """Integration tests using Firefox browser automation."""

    @pytest.fixture
    def web_page_class(self):
        return WebPageSeleniumFirefox

    @pytest.fixture
    def web_page_instance(self, web_page_class, url):
        with web_page_class(url) as wp:
            yield wp

    def test_language(self):
        with WebPageSeleniumFirefox("https://httpbin.org/headers", language="ja") as wp:
            assert wp.execute_script("return window.navigator.languages") == ["ja"]


@pytest.mark.integration
class TestWebPageSeleniumChrome(
    MixinTestWebPage, MixinTestWebPageOpenClose, MixinTestWebPageSelenium
):
    """Integration tests using Chrome browser automation."""

    @pytest.fixture
    def web_page_class(self):
        return WebPageSeleniumChrome

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


class TestWebPageCurlCommand:
    """Unit checks for how WebPageCurl invokes curl (no real network)."""

    def test_html_passes_check_and_captures_stderr(self):
        with patch("pyscraper.webpage_curl.subprocess.run") as run:
            run.return_value.stdout = b"<html></html>"
            assert WebPageCurl("https://example.com").html == "<html></html>"
        kwargs = run.call_args.kwargs
        assert kwargs["check"] is True
        assert kwargs["stderr"] == subprocess.PIPE


@pytest.fixture
def selenium_env(monkeypatch):
    """Isolate browser and proxy settings, including changes made by the library."""
    keys = (
        "SELENIUM_FIREFOX_URL",
        "SELENIUM_CHROME_URL",
        "SELENIUM_FIREFOX_PROFILE",
        "SELENIUM_CHROME_PROFILE",
        "HTTP_PROXY",
        "HTTPS_PROXY",
        "NO_PROXY",
        "http_proxy",
        "https_proxy",
        "no_proxy",
    )

    @contextlib.contextmanager
    def configure(env_vars=None):
        with monkeypatch.context() as env:
            for key in keys:
                # Track absent keys too: the library can add them directly.
                env.setenv(key, "")
                env.delenv(key)
            for key, value in (env_vars or {}).items():
                env.setenv(key, value)
            yield

    return configure


@pytest.fixture
def selenium_driver(selenium_env):
    def create(page_class, env_vars=None, **kwargs):
        with selenium_env(env_vars):
            return page_class("http://example.com", **kwargs)._create_driver()

    return create


@pytest.mark.parametrize("original", [None, "original-host"])
def test_selenium_env_restores_library_changes(monkeypatch, selenium_env, original):
    for key in ("no_proxy", "NO_PROXY"):
        if original is None:
            monkeypatch.delenv(key, raising=False)
        else:
            monkeypatch.setenv(key, original)
    with pytest.raises(RuntimeError), selenium_env():
        for key in ("no_proxy", "NO_PROXY"):
            os.environ[key] = "firefox:4444"
        raise RuntimeError("session failed")
    for key in ("no_proxy", "NO_PROXY"):
        assert os.environ.get(key) == original


class TestConfigureNoProxyForRemote:
    """Remote sessions bypass proxies without losing existing exclusions."""

    @pytest.mark.parametrize(
        ("page_class", "remote_env", "remote_url", "host"),
        [
            (
                WebPageSeleniumFirefox,
                "SELENIUM_FIREFOX_URL",
                "http://firefox:4444/wd/hub",
                "firefox:4444",
            ),
            (
                WebPageSeleniumChrome,
                "SELENIUM_CHROME_URL",
                "http://chrome:9515/wd/hub",
                "chrome:9515",
            ),
        ],
        ids=["firefox", "chrome"],
    )
    @pytest.mark.parametrize(
        ("env_vars", "expected_lower", "expected_upper"),
        [
            (
                {"no_proxy": "localhost,127.0.0.1", "NO_PROXY": "localhost,127.0.0.1"},
                "localhost,127.0.0.1,{host}",
                "localhost,127.0.0.1,{host}",
            ),
            ({"NO_PROXY": "localhost,127.0.0.1"}, "{host}", "localhost,127.0.0.1,{host}"),
            ({}, "{host}", "{host}"),
            ({"no_proxy": "{host}", "NO_PROXY": "{host}"}, "{host}", "{host}"),
            (
                {"no_proxy": "my{host}", "NO_PROXY": "my{host}"},
                "my{host},{host}",
                "my{host},{host}",
            ),
        ],
        ids=["both-cases", "uppercase-only", "unset", "duplicate", "partial-hostname"],
    )
    def test_remote_host_added(
        self,
        selenium_env,
        page_class,
        remote_env,
        remote_url,
        host,
        env_vars,
        expected_lower,
        expected_upper,
    ):
        env_vars = {key: value.format(host=host) for key, value in env_vars.items()}
        env_vars[remote_env] = remote_url
        with selenium_env(env_vars):
            with patch("pyscraper.webpage_selenium.webdriver.Remote") as mock_remote:
                with page_class("http://example.com"):
                    pass
            mock_remote.assert_called_once()
            assert os.environ["no_proxy"] == expected_lower.format(host=host)
            assert os.environ["NO_PROXY"] == expected_upper.format(host=host)

    @pytest.mark.parametrize(
        ("env_vars", "expected_proxy", "expected_no_proxy"),
        [
            (
                {
                    "http_proxy": "http://lower-proxy:80",
                    "https_proxy": "http://lower-proxy:80",
                    "no_proxy": "localhost,.local",
                },
                "lower-proxy:80",
                ["localhost", ".local"],
            ),
            (
                {
                    "http_proxy": "http://lower-proxy:80",
                    "https_proxy": "http://lower-proxy:80",
                    "no_proxy": "localhost,.local",
                    "HTTP_PROXY": "http://UPPER-proxy:80",
                    "HTTPS_PROXY": "http://UPPER-proxy:80",
                    "NO_PROXY": "192.168.1.0/24",
                },
                "lower-proxy:80",
                ["localhost", ".local"],
            ),
            (
                {
                    "HTTP_PROXY": "http://upper-proxy:80",
                    "HTTPS_PROXY": "http://upper-proxy:80",
                    "NO_PROXY": "192.168.1.0/24",
                },
                "upper-proxy:80",
                ["192.168.1.0/24"],
            ),
            (
                {
                    "http_proxy": "plain-proxy:3128",
                    "https_proxy": "plain-proxy:3128",
                    "no_proxy": "localhost",
                },
                "plain-proxy:3128",
                ["localhost"],
            ),
        ],
        ids=["lowercase-only", "lowercase-priority", "uppercase-only", "no-scheme"],
    )
    def test_firefox_proxy(self, selenium_env, env_vars, expected_proxy, expected_no_proxy):
        env_vars = {"SELENIUM_FIREFOX_URL": "http://firefox:4444/wd/hub", **env_vars}
        with selenium_env(env_vars):
            with patch("pyscraper.webpage_selenium.webdriver.Remote") as mock_remote:
                with WebPageSeleniumFirefox("http://example.com"):
                    pass
            mock_remote.assert_called_once()
            options = mock_remote.call_args.kwargs["options"]
            assert options.proxy.httpProxy == expected_proxy
            assert options.proxy.sslProxy == expected_proxy
            assert options.proxy.noProxy == expected_no_proxy
            assert "firefox:4444" in os.environ["no_proxy"].split(",")
            assert "firefox:4444" in os.environ["NO_PROXY"].split(",")


class TestWebPageSeleniumCapabilitiesAndProfile:
    """Unit tests for WebPageSeleniumFirefox/WebPageSeleniumChrome capabilities and profile arguments."""

    def _remote_options(self, mock_remote):
        mock_remote.assert_called_once()
        _, kwargs = mock_remote.call_args
        return kwargs["options"]

    def test_firefox_grid_capabilities(self, selenium_driver):
        env = {"SELENIUM_FIREFOX_URL": "http://firefox:4444/wd/hub"}
        caps = {"grid:profile": "fixed-profile", "se:name": "my-session"}
        with patch("pyscraper.webpage_selenium.webdriver.Remote") as mock_remote:
            selenium_driver(WebPageSeleniumFirefox, env, capabilities=caps)
        options = self._remote_options(mock_remote)
        assert options.capabilities["grid:profile"] == "fixed-profile"
        assert options.capabilities["se:name"] == "my-session"

    def test_firefox_grid_profile_argument(self, selenium_driver):
        env = {"SELENIUM_FIREFOX_URL": "http://firefox:4444/wd/hub"}
        with patch("pyscraper.webpage_selenium.webdriver.Remote") as mock_remote:
            selenium_driver(WebPageSeleniumFirefox, env, profile="/tmp/arg-profile")
        options = self._remote_options(mock_remote)
        assert "-profile" in options.arguments
        assert "/tmp/arg-profile" in options.arguments

    def test_firefox_grid_profile_env_fallback(self, selenium_driver):
        env = {
            "SELENIUM_FIREFOX_URL": "http://firefox:4444/wd/hub",
            "SELENIUM_FIREFOX_PROFILE": "/tmp/env-profile",
        }
        with patch("pyscraper.webpage_selenium.webdriver.Remote") as mock_remote:
            selenium_driver(WebPageSeleniumFirefox, env)
        options = self._remote_options(mock_remote)
        assert "-profile" in options.arguments
        assert "/tmp/env-profile" in options.arguments

    def test_firefox_grid_profile_argument_precedence(self, selenium_driver):
        env = {
            "SELENIUM_FIREFOX_URL": "http://firefox:4444/wd/hub",
            "SELENIUM_FIREFOX_PROFILE": "/tmp/env-profile",
        }
        with patch("pyscraper.webpage_selenium.webdriver.Remote") as mock_remote:
            selenium_driver(WebPageSeleniumFirefox, env, profile="/tmp/arg-profile")
        options = self._remote_options(mock_remote)
        assert "-profile" in options.arguments
        assert "/tmp/arg-profile" in options.arguments
        assert "/tmp/env-profile" not in options.arguments

    def test_chrome_grid_capabilities(self, selenium_driver):
        env = {"SELENIUM_CHROME_URL": "http://chrome:9515/wd/hub"}
        caps = {"grid:profile": "fixed-profile", "se:name": "my-session"}
        with patch("pyscraper.webpage_selenium.webdriver.Remote") as mock_remote:
            selenium_driver(WebPageSeleniumChrome, env, capabilities=caps)
        options = self._remote_options(mock_remote)
        assert options.capabilities["grid:profile"] == "fixed-profile"
        assert options.capabilities["se:name"] == "my-session"

    def test_chrome_grid_profile_argument(self, selenium_driver):
        env = {"SELENIUM_CHROME_URL": "http://chrome:9515/wd/hub"}
        with patch("pyscraper.webpage_selenium.webdriver.Remote") as mock_remote:
            selenium_driver(WebPageSeleniumChrome, env, profile="/tmp/arg-profile")
        options = self._remote_options(mock_remote)
        assert "--user-data-dir=/tmp/arg-profile" in options.arguments

    def test_chrome_grid_profile_env_fallback(self, selenium_driver):
        env = {
            "SELENIUM_CHROME_URL": "http://chrome:9515/wd/hub",
            "SELENIUM_CHROME_PROFILE": "/tmp/env-profile",
        }
        with patch("pyscraper.webpage_selenium.webdriver.Remote") as mock_remote:
            selenium_driver(WebPageSeleniumChrome, env)
        options = self._remote_options(mock_remote)
        assert "--user-data-dir=/tmp/env-profile" in options.arguments

    def test_chrome_grid_profile_argument_precedence(self, selenium_driver):
        env = {
            "SELENIUM_CHROME_URL": "http://chrome:9515/wd/hub",
            "SELENIUM_CHROME_PROFILE": "/tmp/env-profile",
        }
        with patch("pyscraper.webpage_selenium.webdriver.Remote") as mock_remote:
            selenium_driver(WebPageSeleniumChrome, env, profile="/tmp/arg-profile")
        options = self._remote_options(mock_remote)
        assert "--user-data-dir=/tmp/arg-profile" in options.arguments
        assert "--user-data-dir=/tmp/env-profile" not in options.arguments

    def test_firefox_grid_node_capability(self, selenium_driver):
        env = {"SELENIUM_FIREFOX_URL": "http://firefox:4444/wd/hub"}
        with patch("pyscraper.webpage_selenium.webdriver.Remote") as mock_remote:
            selenium_driver(WebPageSeleniumFirefox, env, node="cf")
        options = self._remote_options(mock_remote)
        assert options.capabilities["pyscraper:node"] == "cf"

    def test_chrome_grid_node_capability(self, selenium_driver):
        env = {"SELENIUM_CHROME_URL": "http://chrome:9515/wd/hub"}
        with patch("pyscraper.webpage_selenium.webdriver.Remote") as mock_remote:
            selenium_driver(WebPageSeleniumChrome, env, node="cf")
        options = self._remote_options(mock_remote)
        assert options.capabilities["pyscraper:node"] == "cf"

    def test_chrome_local_profile(self, selenium_driver):
        with patch("pyscraper.webpage_selenium.webdriver.Chrome") as mock_chrome:
            selenium_driver(WebPageSeleniumChrome, profile="/tmp/local-profile")
        mock_chrome.assert_called_once()
        _, kwargs = mock_chrome.call_args
        assert "--user-data-dir=/tmp/local-profile" in kwargs["options"].arguments

    def test_chrome_local_no_profile(self, selenium_driver):
        with patch("pyscraper.webpage_selenium.webdriver.Chrome") as mock_chrome:
            selenium_driver(WebPageSeleniumChrome)
        mock_chrome.assert_called_once()
        _, kwargs = mock_chrome.call_args
        assert not any(
            argument.startswith("--user-data-dir") for argument in kwargs["options"].arguments
        )

    def test_firefox_local_profile(self, selenium_driver):
        import tempfile

        profile_dir = tempfile.mkdtemp()
        try:
            with patch("pyscraper.webpage_selenium.webdriver.Firefox") as mock_firefox:
                selenium_driver(WebPageSeleniumFirefox, profile=profile_dir)
        finally:
            import shutil

            shutil.rmtree(profile_dir, ignore_errors=True)
        mock_firefox.assert_called_once()
        _, kwargs = mock_firefox.call_args
        # FirefoxProfile via options.profile is preferred (deprecated firefox_profile kwarg fallback)
        opts = kwargs["options"]
        profile = kwargs.get("firefox_profile") or getattr(opts, "profile", None)
        assert profile is not None

    def test_firefox_local_user_data_dir(self, selenium_driver):
        import tempfile

        profile_dir = tempfile.mkdtemp()
        try:
            with patch("pyscraper.webpage_selenium.webdriver.Firefox") as mock_firefox:
                selenium_driver(WebPageSeleniumFirefox, user_data_dir=profile_dir)
        finally:
            import shutil

            shutil.rmtree(profile_dir, ignore_errors=True)
        mock_firefox.assert_called_once()
        _, kwargs = mock_firefox.call_args
        opts = kwargs["options"]
        profile = kwargs.get("firefox_profile") or getattr(opts, "profile", None)
        assert profile is not None

    def test_chrome_local_user_data_dir(self, selenium_driver):
        with patch("pyscraper.webpage_selenium.webdriver.Chrome") as mock_chrome:
            selenium_driver(WebPageSeleniumChrome, user_data_dir="/tmp/local-udd")
        mock_chrome.assert_called_once()
        _, kwargs = mock_chrome.call_args
        assert "--user-data-dir=/tmp/local-udd" in kwargs["options"].arguments

    def test_firefox_grid_user_data_dir(self, selenium_driver):
        env = {"SELENIUM_FIREFOX_URL": "http://firefox:4444/wd/hub"}
        with patch("pyscraper.webpage_selenium.webdriver.Remote") as mock_remote:
            selenium_driver(WebPageSeleniumFirefox, env, user_data_dir="/tmp/grid-udd")
        options = self._remote_options(mock_remote)
        assert "-profile" in options.arguments
        assert "/tmp/grid-udd" in options.arguments

    def test_chrome_grid_user_data_dir(self, selenium_driver):
        env = {"SELENIUM_CHROME_URL": "http://chrome:9515/wd/hub"}
        with patch("pyscraper.webpage_selenium.webdriver.Remote") as mock_remote:
            selenium_driver(WebPageSeleniumChrome, env, user_data_dir="/tmp/grid-udd")
        options = self._remote_options(mock_remote)
        assert "--user-data-dir=/tmp/grid-udd" in options.arguments

    def test_profile_overrides_user_data_dir(self, selenium_driver):
        with patch("pyscraper.webpage_selenium.webdriver.Chrome") as mock_chrome:
            with pytest.warns(UserWarning, match="profile takes precedence"):
                selenium_driver(
                    WebPageSeleniumChrome,
                    profile="/tmp/profile",
                    user_data_dir="/tmp/udd",
                )
        _, kwargs = mock_chrome.call_args
        assert "--user-data-dir=/tmp/profile" in kwargs["options"].arguments
        assert "--user-data-dir=/tmp/udd" not in kwargs["options"].arguments

    def test_firefox_grid_page_load_strategy_argument_wins(self, selenium_driver):
        env = {"SELENIUM_FIREFOX_URL": "http://firefox:4444/wd/hub"}
        caps = {"pageLoadStrategy": "eager"}
        with patch("pyscraper.webpage_selenium.webdriver.Remote") as mock_remote:
            selenium_driver(
                WebPageSeleniumFirefox, env, capabilities=caps, page_load_strategy="none"
            )
        options = self._remote_options(mock_remote)
        assert options.capabilities["pageLoadStrategy"] == "none"

    def test_chrome_grid_page_load_strategy_argument_wins(self, selenium_driver):
        env = {"SELENIUM_CHROME_URL": "http://chrome:9515/wd/hub"}
        caps = {"pageLoadStrategy": "eager"}
        with patch("pyscraper.webpage_selenium.webdriver.Remote") as mock_remote:
            selenium_driver(
                WebPageSeleniumChrome, env, capabilities=caps, page_load_strategy="none"
            )
        options = self._remote_options(mock_remote)
        assert options.capabilities["pageLoadStrategy"] == "none"

    def test_firefox_grid_proxy_env_wins(self, selenium_driver):
        env = {
            "SELENIUM_FIREFOX_URL": "http://firefox:4444/wd/hub",
            "HTTP_PROXY": "http://proxy.example:80",
        }
        caps = {"proxy": {"proxyType": "system"}}
        with patch("pyscraper.webpage_selenium.webdriver.Remote") as mock_remote:
            selenium_driver(WebPageSeleniumFirefox, env, capabilities=caps)
        options = self._remote_options(mock_remote)
        assert options.proxy.httpProxy == "proxy.example:80"

    def test_firefox_grid_language_argument_wins(self, selenium_driver):
        env = {"SELENIUM_FIREFOX_URL": "http://firefox:4444/wd/hub"}
        caps = {"moz:firefoxOptions": {"prefs": {"intl.accept_languages": "en"}}}
        with patch("pyscraper.webpage_selenium.webdriver.Remote") as mock_remote:
            selenium_driver(WebPageSeleniumFirefox, env, capabilities=caps, language="ja")
        options = self._remote_options(mock_remote)
        prefs = options.to_capabilities()["moz:firefoxOptions"]["prefs"]
        assert prefs["intl.accept_languages"] == "ja"

    def test_capabilities_defensive_copy(self):
        caps = {"grid:profile": "fixed"}
        page = WebPageSeleniumFirefox("http://example.com", capabilities=caps)
        caps["grid:profile"] = "mutated"
        assert page.capabilities["grid:profile"] == "fixed"

    def test_firefox_grid_reserved_key_warns(self, selenium_driver, caplog):
        env = {"SELENIUM_FIREFOX_URL": "http://firefox:4444/wd/hub"}
        caps = {"moz:firefoxOptions": {"binary": "/custom/ff"}}
        with patch("pyscraper.webpage_selenium.webdriver.Remote"):
            selenium_driver(WebPageSeleniumFirefox, env, capabilities=caps)
        assert any("moz:firefoxOptions" in record.message for record in caplog.records)

    def test_chrome_grid_reserved_key_warns(self, selenium_driver, caplog):
        env = {"SELENIUM_CHROME_URL": "http://chrome:9515/wd/hub"}
        caps = {"goog:chromeOptions": {"binary": "/custom/chrome"}}
        with patch("pyscraper.webpage_selenium.webdriver.Remote"):
            selenium_driver(WebPageSeleniumChrome, env, capabilities=caps)
        assert any("goog:chromeOptions" in record.message for record in caplog.records)

    def test_firefox_grid_proxy_key_warns(self, selenium_driver, caplog):
        env = {"SELENIUM_FIREFOX_URL": "http://firefox:4444/wd/hub"}
        caps = {"proxy": {"proxyType": "system"}}
        with patch("pyscraper.webpage_selenium.webdriver.Remote"):
            selenium_driver(WebPageSeleniumFirefox, env, capabilities=caps)
        assert any(repr("proxy") in record.message for record in caplog.records)

    def test_firefox_grid_non_json_value_warns(self, selenium_driver, caplog):
        env = {"SELENIUM_FIREFOX_URL": "http://firefox:4444/wd/hub"}
        caps = {"weird": {1, 2}}
        with patch("pyscraper.webpage_selenium.webdriver.Remote"):
            selenium_driver(WebPageSeleniumFirefox, env, capabilities=caps)
        assert any("not JSON serializable" in record.message for record in caplog.records)

    def test_firefox_grid_normal_key_no_warning(self, selenium_driver, caplog):
        env = {"SELENIUM_FIREFOX_URL": "http://firefox:4444/wd/hub"}
        caps = {"grid:profile": "fixed-profile"}
        with patch("pyscraper.webpage_selenium.webdriver.Remote"):
            selenium_driver(WebPageSeleniumFirefox, env, capabilities=caps)
        assert not [r for r in caplog.records if r.levelno == logging.WARNING]

    @pytest.mark.parametrize(
        ("page_class", "remote_env", "browser_options", "foreign_options"),
        [
            (
                WebPageSeleniumFirefox,
                "SELENIUM_FIREFOX_URL",
                "moz:firefoxOptions",
                "goog:chromeOptions",
            ),
            (
                WebPageSeleniumChrome,
                "SELENIUM_CHROME_URL",
                "goog:chromeOptions",
                "moz:firefoxOptions",
            ),
        ],
    )
    @pytest.mark.parametrize("invalid_kind", ["set", "circular"])
    def test_unsupported_capabilities_excluded_from_session(
        self,
        selenium_driver,
        caplog,
        page_class,
        remote_env,
        browser_options,
        foreign_options,
        invalid_kind,
    ):
        invalid_value = {1, 2} if invalid_kind == "set" else []
        if invalid_kind == "circular":
            invalid_value.append(invalid_value)
        caps = {
            "moz:firefoxOptions": {"binary": "/custom/firefox"},
            "goog:chromeOptions": {"binary": "/custom/chrome"},
            "proxy": {"proxyType": "system"},
            "custom:invalid": invalid_value,
            "custom:valid": {"labels": ["session"]},
        }
        with patch("pyscraper.webpage_selenium.webdriver.Remote") as mock_remote:
            selenium_driver(page_class, {remote_env: "http://grid:4444/wd/hub"}, capabilities=caps)
        options = self._remote_options(mock_remote)
        request_caps = options.to_capabilities()
        # Exercise the serialization boundary hidden by the mocked Remote driver.
        json.dumps(request_caps)
        assert "custom:invalid" not in request_caps
        assert foreign_options not in request_caps
        assert "binary" not in request_caps[browser_options]
        assert request_caps.get("proxy", {}).get("proxyType") != "system"
        assert request_caps["custom:valid"] == caps["custom:valid"]
        assert caps["custom:invalid"] is invalid_value
        for key in ("moz:firefoxOptions", "goog:chromeOptions", "proxy", "custom:invalid"):
            assert any(repr(key) in record.message for record in caplog.records)

    def test_firefox_local_legacy_profile_fallback(self, selenium_driver, mocker):
        profile = mocker.Mock()
        mocker.patch("pyscraper.webpage_selenium.webdriver.FirefoxProfile", return_value=profile)
        mocker.patch(
            "pyscraper.webpage_selenium.webdriver.FirefoxOptions.profile",
            new_callable=PropertyMock,
            side_effect=AttributeError("profile setter unavailable"),
        )
        with patch("pyscraper.webpage_selenium.webdriver.Firefox") as mock_firefox:
            selenium_driver(
                WebPageSeleniumFirefox,
                profile="/tmp/profile",
                page_load_strategy="eager",
                language="ja",
            )
        mock_firefox.assert_called_once()
        kwargs = mock_firefox.call_args.kwargs
        assert kwargs["firefox_profile"] is profile
        assert "-headless" in kwargs["options"].arguments
        assert kwargs["options"].page_load_strategy == "eager"
        assert (
            kwargs["options"].to_capabilities()["moz:firefoxOptions"]["prefs"][
                "intl.accept_languages"
            ]
            == "ja"
        )


class TestSeleniumWaits:
    @pytest.mark.parametrize("target_kind", ["page", "element"])
    def test_wait_uses_target_search_context(self, mocker, target_kind):
        context = mocker.Mock()
        if target_kind == "page":
            target = WebPageSeleniumFirefox()
            target.driver = context
        else:
            target = SeleniumWebPageElement(context)
        assert target.wait(".//a", timeout=0) is None
        context.find_element.assert_called_once_with(By.XPATH, ".//a")

    @pytest.mark.parametrize("target_kind", ["page", "element"])
    def test_wait_translates_timeout(self, mocker, target_kind):
        context = mocker.Mock()
        context.find_element.side_effect = NoSuchElementException("missing")
        if target_kind == "page":
            target = WebPageSeleniumFirefox()
            target.driver = context
        else:
            target = SeleniumWebPageElement(context)
        with pytest.raises(WebPageTimeoutError) as exc:
            target.wait(".//missing", timeout=0)
        assert isinstance(exc.value.__cause__, TimeoutException)

    @pytest.mark.parametrize("timeout", [0, 1])
    def test_element_click(self, mocker, timeout):
        element = mocker.Mock(spec=WebElement)
        element.is_displayed.return_value = True
        element.is_enabled.return_value = True
        SeleniumWebPageElement(element).click(timeout=timeout)
        element.click.assert_called_once_with()
        if timeout:
            element.is_displayed.assert_called_once_with()
            element.is_enabled.assert_called_once_with()
        else:
            element.is_displayed.assert_not_called()

    def test_element_click_does_not_click_after_timeout(self, mocker):
        element = mocker.Mock()
        timeout = TimeoutException("not clickable")
        mocker.patch("pyscraper.webpage_selenium.WebDriverWait.until", side_effect=timeout)
        with pytest.raises(WebPageTimeoutError) as exc:
            SeleniumWebPageElement(element).click(timeout=1)
        assert exc.value.__cause__ is timeout
        element.click.assert_not_called()

    def test_page_click_preserves_selenium_timeout(self, mocker):
        page = WebPageSeleniumFirefox()
        page.driver = mocker.Mock()
        timeout = TimeoutException("not clickable")
        mocker.patch("pyscraper.webpage_selenium.WebDriverWait.until", side_effect=timeout)
        with pytest.raises(TimeoutException) as exc:
            page.click("//a", timeout=0)
        assert exc.value is timeout
        page.driver.find_element.return_value.click.assert_not_called()


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
        import lxml.html

        from pyscraper.webpage import WebPageElement

        html = "<div>Hello <b>World</b> and more</div>"
        element = lxml.html.fromstring(html)
        wp_element = WebPageElement(element)
        assert "and more" in wp_element.inner_text

    def test_inner_html_includes_child_tail(self):
        import lxml.html

        from pyscraper.webpage import WebPageElement

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
