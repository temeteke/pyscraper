"""Tests for Playwright-based web page backend.

Unit tests mock the Playwright API to avoid requiring an actual browser.
Integration tests are marked with @pytest.mark.integration.
"""

import os
from unittest.mock import MagicMock, PropertyMock, patch

import pytest
import lxml.html

from pyscraper.webpage import (
    WebPageError,
    WebPageNoSuchElementError,
    WebPageTimeoutError,
)
from pyscraper.webpage_playwright import (
    CaptureSession,
    PlaywrightWebPageElement,
    RequestEntry,
    WebPagePlaywright,
    WebPagePlaywrightChromium,
    WebPagePlaywrightFirefox,
    WebPagePlaywrightWebKit,
)


@pytest.fixture
def url():
    return "https://temeteke.github.io/pyscraper/tests/testdata/test.html"


# ---------------------------------------------------------------------------
# Mock infrastructure
# ---------------------------------------------------------------------------

@pytest.fixture
def mock_html_content():
    return """<!DOCTYPE html>
<html>
<head><title>Title</title></head>
<body>
<h1>Header</h1>
<p>paragraph 1<a>link 1</a></p>
<a id="link" href="test2.html">test2</a>
<iframe src="iframe.html"></iframe>
</body>
</html>"""


def _make_mock_locator(outer_html=None, inner_html_content=None, inner_text_content=None):
    """Create a mocked Playwright Locator."""
    loc = MagicMock()
    loc.evaluate.return_value = outer_html or "<div>mock</div>"
    loc.inner_html.return_value = inner_html_content or "mock"
    loc.inner_text.return_value = inner_text_content or "mock"
    loc.text_content.return_value = inner_text_content or "mock"
    loc.all.return_value = []
    return loc


def _make_mock_page(html_content="<html><body>Mock</body></html>"):
    """Create a mocked Playwright Page."""
    page = MagicMock()
    page.content.return_value = html_content
    page.url = "https://example.com/"
    page.viewport_size = {"height": 768, "width": 1024}

    def _locator(selector):
        loc = _make_mock_locator(
            outer_html="<div>element</div>",
            inner_html_content="element",
            inner_text_content="element",
        )
        loc.all.return_value = [loc]
        loc.page = page
        return loc

    page.locator.side_effect = _locator
    return page


@pytest.fixture
def mock_pw(page_html=None):
    """Patch sync_playwright and return a (page_mock, browser_type_attr_name) tuple.

    Usage:
        def test_xxx(mock_pw):
            page_mock, browser_attr = mock_pw
            page_mock.content.return_value = "<html>custom</html>"
    """
    if page_html is None:
        page_html = "<html><body>Mock</body></html>"

    page = _make_mock_page(page_html)

    context = MagicMock()
    context.new_page.return_value = page
    context.cookies.return_value = []

    browser = MagicMock()
    browser.new_context.return_value = context

    pw_instance = MagicMock()
    pw_instance.chromium.launch.return_value = browser
    pw_instance.firefox.launch.return_value = browser
    pw_instance.webkit.launch.return_value = browser

    with patch("playwright.sync_api.sync_playwright") as mock_sync:
        mock_sync.return_value.start.return_value = pw_instance
        yield page, browser, context, pw_instance


# ---------------------------------------------------------------------------
# PlaywrightWebPageElement unit tests
# ---------------------------------------------------------------------------

class TestPlaywrightWebPageElement:
    @pytest.fixture
    def locator(self):
        return _make_mock_locator(
            outer_html="<p>hello</p>",
            inner_html_content="hello",
            inner_text_content="hello",
        )

    @pytest.fixture
    def element(self, locator):
        return PlaywrightWebPageElement(locator)

    def test_html(self, element, locator):
        assert element.html == "<p>hello</p>"
        locator.evaluate.assert_called_with("el => el.outerHTML")

    def test_inner_html(self, element, locator):
        assert element.inner_html == "hello"
        locator.inner_html.assert_called_once()

    def test_inner_text(self, element, locator):
        assert element.inner_text == "hello"
        locator.inner_text.assert_called_once()

    def test_lxml_html(self, element):
        parsed = element.lxml_html
        assert parsed is not None
        assert parsed.tag == "p"

    def test_text_fallback_to_lxml(self, element):
        assert element.text == "hello"

    def test_attrib_fallback_to_lxml(self, element):
        assert element.attrib == {}

    def test_wait(self, element, locator):
        mock_page = MagicMock()
        locator.page = mock_page
        element.wait("//div", timeout=5)
        mock_page.wait_for_selector.assert_called_once_with(
            "xpath=//div", timeout=5000
        )

    def test_get(self, element, locator):
        child_loc = _make_mock_locator()
        locator.locator.return_value.all.return_value = [child_loc]
        results = element.get("//span")
        assert len(results) == 1
        assert isinstance(results[0], PlaywrightWebPageElement)

    def test_click(self, element, locator):
        element.click()
        locator.click.assert_called_once_with()

    def test_click_with_timeout(self, element, locator):
        element.click(timeout=5)
        locator.click.assert_called_once_with(timeout=5000)

    def test_mouse_over(self, element, locator):
        element.mouse_over()
        locator.hover.assert_called_once()

    def test_scroll(self, element, locator):
        element.scroll()
        locator.scroll_into_view_if_needed.assert_called_once()

    def test_switch_success(self):
        mock_page = MagicMock()
        mock_frame = MagicMock()
        locator = _make_mock_locator()
        locator.page = mock_page
        handle = MagicMock()
        handle.content_frame.return_value = mock_frame
        locator.element_handle.return_value = handle

        element = PlaywrightWebPageElement(locator, page=mock_page)
        with element.switch():
            assert element._page is mock_frame
        assert element._page is mock_page

    def test_switch_not_iframe(self):
        locator = _make_mock_locator()
        handle = MagicMock()
        handle.content_frame.return_value = None
        locator.element_handle.return_value = handle

        element = PlaywrightWebPageElement(locator)
        with pytest.raises(WebPageError, match="not an iframe"):
            with element.switch():
                pass


# ---------------------------------------------------------------------------
# WebPagePlaywright base class unit tests
# ---------------------------------------------------------------------------

class TestWebPagePlaywrightBase:
    def test_ensure_open_raises(self):
        wp = WebPagePlaywrightChromium("https://example.com")
        with pytest.raises(WebPageError, match="Page is not opened yet"):
            wp._ensure_open()

    def test_url_before_open(self):
        wp = WebPagePlaywrightChromium("https://example.com/page")
        assert wp.url == "https://example.com/page"

    def test_html_before_open_raises(self):
        wp = WebPagePlaywrightChromium("https://example.com")
        with pytest.raises(WebPageError, match="Page is not opened yet"):
            _ = wp.html

    def test_cookies_before_open(self):
        wp = WebPagePlaywrightChromium("https://example.com", cookies={"a": "1"})
        assert wp.cookies["a"] == "1"

    def test_params_encoding(self, url):
        wp = WebPagePlaywrightChromium(url, params={"p": "1"})
        assert "p=1" in wp.url

    def test_str(self):
        wp = WebPagePlaywrightChromium("https://example.com")
        assert str(wp) == "https://example.com"

    def test_eq(self):
        wp1 = WebPagePlaywrightChromium("https://example.com")
        wp2 = WebPagePlaywrightChromium("https://example.com")
        assert wp1 == wp2

    def test_eq_different_urls(self):
        wp1 = WebPagePlaywrightChromium("https://a.com")
        wp2 = WebPagePlaywrightChromium("https://b.com")
        assert wp1 != wp2

    def test_eq_different_type(self):
        wp = WebPagePlaywrightChromium("https://example.com")
        assert wp.__eq__("not a webpage") is NotImplemented


# ---------------------------------------------------------------------------
# WebPagePlaywrightChromium open/close tests
# ---------------------------------------------------------------------------

class TestWebPagePlaywrightChromium:
    @pytest.fixture
    def wp(self, url, mock_pw):
        page_mock, browser, context, pw_instance = mock_pw
        page_mock.content.return_value = """<html><body><h1>Header</h1><a id="link" href="test2.html">test2</a></body></html>"""
        page_mock.url = url
        with WebPagePlaywrightChromium(url) as wp:
            yield wp

    def test_url_after_open(self, wp, url):
        assert wp.url == url

    def test_url_change(self, wp, url):
        wp.url = "https://other.com/page"
        assert wp.request_url == "https://other.com/page"

    def test_html(self, wp):
        html = wp.html
        assert "<h1>Header</h1>" in html

    def test_get(self, wp):
        results = wp.get("//a[@id='link']")
        assert len(results) == 1
        assert isinstance(results[0], PlaywrightWebPageElement)

    def test_get_no_match(self, wp, mock_pw):
        page_mock = mock_pw[0]
        empty_loc = MagicMock()
        empty_loc.all.return_value = []
        page_mock.locator.side_effect = lambda sel: empty_loc
        assert wp.get("//nonexistent") == []

    def test_wait(self, wp, mock_pw):
        page_mock = mock_pw[0]
        wp.wait("//h1", timeout=3)
        page_mock.wait_for_selector.assert_called_with(
            "xpath=//h1", timeout=3000
        )

    def test_click(self, wp, mock_pw):
        page_mock = mock_pw[0]
        wp.click("//a[@id='link']")
        page_mock.locator.assert_called_with("xpath=//a[@id='link']")

    def test_click_no_element(self, wp, mock_pw):
        page_mock = mock_pw[0]
        empty_loc = MagicMock()
        empty_loc.click.side_effect = Exception("not found")
        page_mock.locator.side_effect = lambda sel: empty_loc
        with pytest.raises(WebPageNoSuchElementError):
            wp.click("//nonexistent")

    def test_move_to(self, wp, mock_pw):
        page_mock = mock_pw[0]
        wp.move_to("//h1")
        page_mock.locator.assert_called_with("xpath=//h1")

    def test_go(self, wp, mock_pw):
        page_mock = mock_pw[0]
        wp.go("https://other.com")
        page_mock.goto.assert_called_with("https://other.com")

    def test_go_with_params(self, wp, mock_pw):
        page_mock = mock_pw[0]
        wp.go("https://other.com", params={"key": "val"})
        args = page_mock.goto.call_args[0][0]
        assert "key=val" in args

    def test_forward(self, wp, mock_pw):
        page_mock = mock_pw[0]
        wp.forward()
        page_mock.go_forward.assert_called_once()

    def test_back(self, wp, mock_pw):
        page_mock = mock_pw[0]
        wp.back()
        page_mock.go_back.assert_called_once()

    def test_refresh(self, wp, mock_pw):
        page_mock = mock_pw[0]
        wp.refresh()
        page_mock.reload.assert_called_once()

    def test_execute_script(self, wp, mock_pw):
        page_mock = mock_pw[0]
        wp.execute_script("return 1 + 1")
        page_mock.evaluate.assert_called_with("return 1 + 1")

    def test_execute_async_script(self, wp, mock_pw):
        page_mock = mock_pw[0]
        wp.execute_async_script("return Promise.resolve(42)")
        page_mock.evaluate_async.assert_called_with("return Promise.resolve(42)")

    def test_user_agent(self, wp, mock_pw):
        page_mock = mock_pw[0]
        page_mock.evaluate.return_value = "PlaywrightMock/1.0"
        assert wp.user_agent == "PlaywrightMock/1.0"

    def test_cookies_after_open(self, wp, mock_pw):
        context = mock_pw[2]
        context.cookies.return_value = [{"name": "session", "value": "abc"}]
        assert wp.cookies["session"] == "abc"

    def test_cookies_setter(self, wp, mock_pw):
        wp.cookies = {"new": "cookie"}
        assert wp._cookies["new"] == "cookie"

    def test_dump(self, wp, mock_pw):
        page_mock = mock_pw[0]
        page_mock.evaluate.return_value = 0
        files = wp.dump()
        assert files
        for f in files:
            assert f.exists()
            f.unlink()

    def test_dump_with_filestem(self, wp, mock_pw):
        page_mock = mock_pw[0]
        page_mock.evaluate.return_value = 0
        files = wp.dump(filestem="test_dump")
        for f in files:
            assert f.exists()
            f.unlink()

    def test_context_manager(self, wp):
        assert wp._page is not None

    def test_switch_to_frame(self, wp, mock_pw):
        page_mock = mock_pw[0]
        loc = MagicMock()
        loc.get_attribute.return_value = "iframe.html"
        handle = MagicMock()
        mock_frame = MagicMock()
        handle.content_frame.return_value = mock_frame
        loc.element_handle.return_value = handle
        page_mock.locator.side_effect = lambda sel: loc

        src = wp.switch_to_frame("//iframe")
        assert src == "iframe.html"
        assert wp._page is mock_frame

    def test_switch_to_frame_not_iframe(self, wp, mock_pw):
        page_mock = mock_pw[0]
        loc = MagicMock()
        handle = MagicMock()
        handle.content_frame.return_value = None
        loc.element_handle.return_value = handle
        page_mock.locator.side_effect = lambda sel: loc

        with pytest.raises(WebPageError, match="not an iframe"):
            wp.switch_to_frame("//iframe")


# ---------------------------------------------------------------------------
# Browser type specific tests
# ---------------------------------------------------------------------------

class TestWebPagePlaywrightConcreteClasses:
    def test_chromium_default_url(self):
        wp = WebPagePlaywrightChromium()
        assert wp.url == "about:blank"

    def test_firefox_default_url(self):
        wp = WebPagePlaywrightFirefox()
        assert wp.url == "about:blank"

    def test_webkit_default_url(self):
        wp = WebPagePlaywrightWebKit()
        assert wp.url == "about:blank"

    def test_chromium_launch(self, mock_pw):
        page_mock, browser, context, pw_instance = mock_pw
        with WebPagePlaywrightChromium("https://example.com"):
            pw_instance.chromium.launch.assert_called_once_with(headless=True)

    def test_firefox_launch(self, mock_pw):
        page_mock, browser, context, pw_instance = mock_pw
        with WebPagePlaywrightFirefox("https://example.com"):
            pw_instance.firefox.launch.assert_called_once_with(headless=True)

    def test_webkit_launch(self, mock_pw):
        page_mock, browser, context, pw_instance = mock_pw
        with WebPagePlaywrightWebKit("https://example.com"):
            pw_instance.webkit.launch.assert_called_once_with(headless=True)

    def test_cookies_passed_to_context(self, mock_pw):
        page_mock, browser, context, pw_instance = mock_pw
        with WebPagePlaywrightChromium("https://example.com", cookies={"sess": "val"}):
            context.add_cookies.assert_called()


# ---------------------------------------------------------------------------
# Remote browser URL tests
# ---------------------------------------------------------------------------

class TestWebPagePlaywrightRemote:
    REMOTE_URL = "ws://playwright:4444/ws"

    def test_chromium_remote(self, mock_pw):
        page_mock, browser, context, pw_instance = mock_pw
        saved = os.environ.get("PLAYWRIGHT_CHROMIUM_URL")
        os.environ["PLAYWRIGHT_CHROMIUM_URL"] = self.REMOTE_URL
        try:
            with WebPagePlaywrightChromium("https://example.com"):
                pw_instance.chromium.connect.assert_called_once_with(self.REMOTE_URL)
        finally:
            if saved is None:
                del os.environ["PLAYWRIGHT_CHROMIUM_URL"]
            else:
                os.environ["PLAYWRIGHT_CHROMIUM_URL"] = saved

    def test_firefox_remote(self, mock_pw):
        page_mock, browser, context, pw_instance = mock_pw
        saved = os.environ.get("PLAYWRIGHT_FIREFOX_URL")
        os.environ["PLAYWRIGHT_FIREFOX_URL"] = self.REMOTE_URL
        try:
            with WebPagePlaywrightFirefox("https://example.com"):
                pw_instance.firefox.connect.assert_called_once_with(self.REMOTE_URL)
        finally:
            if saved is None:
                del os.environ["PLAYWRIGHT_FIREFOX_URL"]
            else:
                os.environ["PLAYWRIGHT_FIREFOX_URL"] = saved

    def test_webkit_remote(self, mock_pw):
        page_mock, browser, context, pw_instance = mock_pw
        saved = os.environ.get("PLAYWRIGHT_WEBKIT_URL")
        os.environ["PLAYWRIGHT_WEBKIT_URL"] = self.REMOTE_URL
        try:
            with WebPagePlaywrightWebKit("https://example.com"):
                pw_instance.webkit.connect.assert_called_once_with(self.REMOTE_URL)
        finally:
            if saved is None:
                del os.environ["PLAYWRIGHT_WEBKIT_URL"]
            else:
                os.environ["PLAYWRIGHT_WEBKIT_URL"] = saved

    def test_remote_preferred_over_launch(self, mock_pw):
        page_mock, browser, context, pw_instance = mock_pw
        os.environ["PLAYWRIGHT_CHROMIUM_URL"] = self.REMOTE_URL
        try:
            with WebPagePlaywrightChromium("https://example.com"):
                pw_instance.chromium.launch.assert_not_called()
        finally:
            del os.environ["PLAYWRIGHT_CHROMIUM_URL"]


# ---------------------------------------------------------------------------
# Proxy configuration tests
# ---------------------------------------------------------------------------

class TestWebPagePlaywrightProxy:
    def _run_with_proxy_env(self, env_vars):
        saved = {}
        for k, v in env_vars.items():
            saved[k] = os.environ.get(k)
            os.environ[k] = v
        try:
            with patch("playwright.sync_api.sync_playwright") as mock_sync:
                pw_instance = MagicMock()
                mock_sync.return_value.start.return_value = pw_instance
                browser = MagicMock()
                pw_instance.chromium.launch.return_value = browser
                with WebPagePlaywrightChromium("https://example.com"):
                    return browser.new_context.call_args
        finally:
            for k in env_vars:
                if saved[k] is None:
                    del os.environ[k]
                else:
                    os.environ[k] = saved[k]

    def test_http_proxy(self):
        call_args = self._run_with_proxy_env({"HTTP_PROXY": "http://proxy:8080"})
        kwargs = call_args[1] if call_args else {}
        assert kwargs.get("proxy", {}).get("server") == "http://proxy:8080"

    def test_https_proxy(self):
        call_args = self._run_with_proxy_env({"HTTPS_PROXY": "http://proxy:8080"})
        kwargs = call_args[1] if call_args else {}
        assert kwargs.get("proxy", {}).get("server") == "http://proxy:8080"

    def test_no_proxy(self):
        call_args = self._run_with_proxy_env({
            "HTTP_PROXY": "http://proxy:8080",
            "NO_PROXY": "localhost,.local",
        })
        kwargs = call_args[1] if call_args else {}
        assert kwargs.get("proxy", {}).get("bypass") == "localhost,.local"

    def test_no_proxy_only(self):
        call_args = self._run_with_proxy_env({"NO_PROXY": "localhost"})
        kwargs = call_args[1] if call_args else {}
        assert kwargs.get("proxy", {}).get("bypass") == "localhost"

    def test_lowercase_env_var_preferred(self):
        saved_lower = os.environ.get("http_proxy")
        saved_upper = os.environ.get("HTTP_PROXY")
        try:
            os.environ["http_proxy"] = "http://lower:8080"
            os.environ["HTTP_PROXY"] = "http://UPPER:8080"
            with patch("playwright.sync_api.sync_playwright") as mock_sync:
                pw_instance = MagicMock()
                mock_sync.return_value.start.return_value = pw_instance
                browser = MagicMock()
                pw_instance.chromium.launch.return_value = browser
                with WebPagePlaywrightChromium("https://example.com"):
                    kwargs = browser.new_context.call_args[1]
                    assert kwargs["proxy"]["server"] == "http://lower:8080"
        finally:
            for k, v in [("http_proxy", saved_lower), ("HTTP_PROXY", saved_upper)]:
                if v is None:
                    os.environ.pop(k, None)
                else:
                    os.environ[k] = v


# ---------------------------------------------------------------------------
# CaptureSession tests
# ---------------------------------------------------------------------------

class TestCaptureSession:
    def test_wp_capture_returns_session(self, mock_pw):
        with WebPagePlaywrightChromium("https://example.com") as wp:
            cap = wp.capture()
            assert isinstance(cap, CaptureSession)
            assert cap._wp is wp
            assert cap._filter_url is None
            assert cap.requests == []

    def test_wp_capture_with_filter(self, mock_pw):
        with WebPagePlaywrightChromium("https://example.com") as wp:
            f = lambda u: "api" in u
            cap = wp.capture(filter_url=f)
            assert cap._filter_url is f

    def test_enter_registers_listeners(self, mock_pw):
        page_mock = mock_pw[0]
        with WebPagePlaywrightChromium("https://example.com") as wp:
            with wp.capture() as cap:
                request_calls = [c for c in page_mock.on.call_args_list if c.args[0] == "request"]
                response_calls = [c for c in page_mock.on.call_args_list if c.args[0] == "response"]
                assert len(request_calls) == 1
                assert len(response_calls) == 1

    def test_exit_removes_listeners(self, mock_pw):
        page_mock = mock_pw[0]
        with WebPagePlaywrightChromium("https://example.com") as wp:
            with wp.capture() as cap:
                pass
            remove_calls = page_mock.remove_listener.call_args_list
            names = [c.args[0] for c in remove_calls]
            assert names == ["request", "response"]

    def test_captures_request(self, mock_pw):
        page_mock = mock_pw[0]
        with WebPagePlaywrightChromium("https://example.com") as wp:
            with wp.capture() as cap:
                handler = next(c.args[1] for c in page_mock.on.call_args_list if c.args[0] == "request")
                req = MagicMock()
                req.url = "https://cdn.example.com/video.mp4"
                req.method = "GET"
                req.headers = {"Accept": "*/*"}
                req.resource_type = "media"
                handler(req)
                assert len(cap.requests) == 1
                assert cap.requests[0].url == "https://cdn.example.com/video.mp4"
                assert cap.requests[0].method == "GET"
                assert cap.requests[0].resource_type == "media"
                assert cap.requests[0].status is None

    def test_response_updates_entry(self, mock_pw):
        page_mock = mock_pw[0]
        with WebPagePlaywrightChromium("https://example.com") as wp:
            with wp.capture() as cap:
                handlers = {c.args[0]: c.args[1] for c in page_mock.on.call_args_list}
                req = MagicMock()
                req.url = "https://example.com/data.json"
                req.method = "GET"
                req.headers = {}
                req.resource_type = "xhr"
                handlers["request"](req)
                res = MagicMock()
                res.status = 200
                res.headers = {"Content-Type": "application/json"}
                res.request = req
                handlers["response"](res)
                entry = cap.requests[0]
                assert entry.status == 200
                assert entry.response_headers == {"Content-Type": "application/json"}

    def test_filter_url_excludes_unmatched(self, mock_pw):
        page_mock = mock_pw[0]
        with WebPagePlaywrightChromium("https://example.com") as wp:
            with wp.capture(filter_url=lambda u: "api" in u) as cap:
                handler = next(c.args[1] for c in page_mock.on.call_args_list if c.args[0] == "request")
                api_req = MagicMock()
                api_req.url = "https://example.com/api/data"
                api_req.method = "GET"
                api_req.headers = {}
                api_req.resource_type = "xhr"
                handler(api_req)
                css_req = MagicMock()
                css_req.url = "https://example.com/style.css"
                css_req.method = "GET"
                css_req.headers = {}
                css_req.resource_type = "stylesheet"
                handler(css_req)
                assert len(cap.requests) == 1
                assert cap.requests[0].url == "https://example.com/api/data"

    def test_capture_before_open_no_error(self):
        wp = WebPagePlaywrightChromium("https://example.com")
        cap = wp.capture()
        with cap:
            pass
        assert cap.requests == []

    def test_stop_idempotent(self, mock_pw):
        page_mock = mock_pw[0]
        with WebPagePlaywrightChromium("https://example.com") as wp:
            with wp.capture() as cap:
                pass
            cap.stop()
            assert cap._stopped


# ============================================================================
# Integration Tests (require real Playwright browser server)
# ============================================================================

@pytest.mark.integration
class TestWebPagePlaywrightIntegration:
    """Integration tests using real Playwright browser servers.

    These tests require Docker services to be running:
      docker compose up -d playwright-chromium playwright-firefox playwright-webkit
      pytest tests/test_webpage_playwright.py -m integration -k Playwright -v
    """

    CONTAINER_NAMES = {
        "chromium": "pyscraper-playwright-chromium-1",
        "firefox": "pyscraper-playwright-firefox-1",
        "webkit": "pyscraper-playwright-webkit-1",
    }
    PORTS = {"chromium": 3000, "firefox": 3002, "webkit": 3003}

    @staticmethod
    def _get_ip(container_name):
        import subprocess
        result = subprocess.run(
            ["docker", "inspect", container_name,
             "-f", "{{range .NetworkSettings.Networks}}{{.IPAddress}}{{end}}"],
            capture_output=True, text=True, timeout=10,
        )
        ip = result.stdout.strip()
        if not ip:
            raise RuntimeError(f"Container {container_name} not found. "
                               "Start with: docker compose up -d ...")
        return ip

    def _connect(self, browser, container_name, port):
        ip = self._get_ip(container_name)
        return f"http://{ip}:{port}"

    @pytest.mark.integration
    def test_remote_chromium_open(self):
        url = self._connect("chromium", "pyscraper-playwright-chromium-1", 3000)
        target = "https://temeteke.github.io/pyscraper/tests/testdata/test.html"
        os.environ["PLAYWRIGHT_CHROMIUM_URL"] = url
        try:
            with WebPagePlaywrightChromium(target) as wp:
                html = wp.html
                assert "<h1>Header</h1>" in html or "<h1>Test</h1>" in html
                results = wp.get("//h1")
                assert len(results) >= 1
        finally:
            os.environ.pop("PLAYWRIGHT_CHROMIUM_URL", None)

    @pytest.mark.integration
    def test_remote_chromium_click(self):
        url = self._connect("chromium", "pyscraper-playwright-chromium-1", 3000)
        target = "https://temeteke.github.io/pyscraper/tests/testdata/test.html"
        os.environ["PLAYWRIGHT_CHROMIUM_URL"] = url
        try:
            with WebPagePlaywrightChromium(target) as wp:
                wp.click("//a[@id='link']")
        finally:
            os.environ.pop("PLAYWRIGHT_CHROMIUM_URL", None)

    @staticmethod
    def _get_ws_endpoint(container_name, port):
        import subprocess
        from urllib.parse import urlparse, urlunparse
        ip = TestWebPagePlaywrightIntegration._get_ip(container_name)
        result = subprocess.run(
            ["docker", "logs", container_name],
            capture_output=True, text=True, timeout=10,
        )
        for line in result.stdout.splitlines():
            if "WS_ENDPOINT=" in line:
                ws = line.split("WS_ENDPOINT=", 1)[1].strip()
                parsed = urlparse(ws)
                return urlunparse(parsed._replace(netloc=f"{ip}:{parsed.port}"))
        return f"ws://{ip}:{port}"

    @pytest.mark.integration
    def test_remote_firefox_open(self):
        ws_url = self._get_ws_endpoint("pyscraper-playwright-firefox-1", 3002)
        target = "https://temeteke.github.io/pyscraper/tests/testdata/test.html"
        os.environ["PLAYWRIGHT_FIREFOX_URL"] = ws_url
        try:
            with WebPagePlaywrightFirefox(target) as wp:
                html = wp.html
                assert "<h1>Header</h1>" in html or "<h1>Test</h1>" in html
        finally:
            os.environ.pop("PLAYWRIGHT_FIREFOX_URL", None)

    @pytest.mark.integration
    def test_remote_webkit_open(self):
        ws_url = self._get_ws_endpoint("pyscraper-playwright-webkit-1", 3003)
        target = "https://temeteke.github.io/pyscraper/tests/testdata/test.html"
        os.environ["PLAYWRIGHT_WEBKIT_URL"] = ws_url
        try:
            with WebPagePlaywrightWebKit(target) as wp:
                html = wp.html
                assert "<h1>Header</h1>" in html or "<h1>Test</h1>" in html
        finally:
            os.environ.pop("PLAYWRIGHT_WEBKIT_URL", None)
