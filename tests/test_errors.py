import subprocess

import pytest
import requests
import selenium.common.exceptions
import urllib3.exceptions

from pyscraper import (
    HlsFile,
    HlsFileError,
    PyscraperError,
    WebFile,
    WebFileClientError,
    WebFileConnectionError,
    WebFileError,
    WebFileServerError,
    WebFileTimeoutError,
)
from pyscraper.webpage import (
    WebPageBrowserError,
    WebPageClickInterceptedError,
    WebPageConnectionError,
    WebPageError,
    WebPageNoSuchElementError,
    WebPageStaleElementReferenceError,
    WebPageTimeoutError,
)
from pyscraper.webpage_curl import WebPageCurl
from pyscraper.webpage_requests import WebPageRequests
from pyscraper.webpage_selenium import SeleniumWebPageElement, WebPageSeleniumFirefox


class TestPyscraperErrorBase:
    def test_common_base_catches_all_three_families(self):
        assert issubclass(WebPageError, PyscraperError)
        assert issubclass(WebFileError, PyscraperError)
        assert issubclass(HlsFileError, PyscraperError)

    def test_existing_except_still_works(self):
        with pytest.raises(WebPageError):
            raise WebPageTimeoutError("timeout")
        with pytest.raises(WebFileError):
            raise WebFileClientError("client")
        with pytest.raises(HlsFileError):
            raise HlsFileError("hls")

    def test_cross_family_catch(self):
        for exc in (
            WebPageTimeoutError("t"),
            WebFileClientError("c"),
            HlsFileError("h"),
        ):
            with pytest.raises(PyscraperError):
                raise exc

    def test_exported_from_package(self):
        import pyscraper

        assert pyscraper.PyscraperError is PyscraperError
        assert "PyscraperError" in pyscraper.__all__

    def test_status_code_defaults_to_none(self):
        assert PyscraperError("x").status_code is None
        assert WebPageError("x").status_code is None
        assert WebFileError("x").status_code is None
        assert HlsFileError("x").status_code is None


class TestSeleniumClickTranslation:
    @pytest.mark.parametrize(
        ("selenium_exc", "expected"),
        [
            (
                selenium.common.exceptions.ElementClickInterceptedException("intercepted"),
                WebPageClickInterceptedError,
            ),
            (
                selenium.common.exceptions.StaleElementReferenceException("stale"),
                WebPageStaleElementReferenceError,
            ),
            (
                selenium.common.exceptions.WebDriverException("generic"),
                WebPageBrowserError,
            ),
        ],
        ids=["intercepted", "stale", "generic"],
    )
    def test_element_click_translates(self, mocker, selenium_exc, expected):
        element = mocker.Mock()
        element.click.side_effect = selenium_exc
        with pytest.raises(expected) as exc:
            SeleniumWebPageElement(element).click()
        assert isinstance(exc.value, WebPageError)
        assert isinstance(exc.value, PyscraperError)
        assert exc.value.__cause__ is selenium_exc
        assert str(exc.value)

    @pytest.mark.parametrize(
        ("selenium_exc", "expected"),
        [
            (
                selenium.common.exceptions.ElementClickInterceptedException("intercepted"),
                WebPageClickInterceptedError,
            ),
            (
                selenium.common.exceptions.StaleElementReferenceException("stale"),
                WebPageStaleElementReferenceError,
            ),
            (
                selenium.common.exceptions.WebDriverException("generic"),
                WebPageBrowserError,
            ),
            (
                selenium.common.exceptions.TimeoutException("not clickable"),
                WebPageTimeoutError,
            ),
            (
                selenium.common.exceptions.NoSuchElementException("missing"),
                WebPageNoSuchElementError,
            ),
            (
                selenium.common.exceptions.InvalidSelectorException("bad xpath"),
                WebPageBrowserError,
            ),
        ],
        ids=["intercepted", "stale", "generic", "timeout", "no-such-element", "bad-xpath"],
    )
    def test_page_click_translates(self, mocker, selenium_exc, expected):
        page = WebPageSeleniumFirefox()
        page.driver = mocker.Mock()
        page.driver.find_element.side_effect = selenium_exc
        with pytest.raises(expected) as exc:
            page.click("//a")
        assert isinstance(exc.value, WebPageError)
        assert isinstance(exc.value, PyscraperError)
        assert exc.value.__cause__ is selenium_exc
        assert str(exc.value)

    def test_open_translates_webdriver_exception(self, mocker):
        page = WebPageSeleniumFirefox("http://example.com")
        driver = mocker.Mock()
        failure = selenium.common.exceptions.WebDriverException("no session")
        driver.get.side_effect = failure
        page._create_driver = mocker.Mock(return_value=driver)
        with pytest.raises(WebPageBrowserError) as exc:
            page.open()
        assert exc.value.__cause__ is failure
        assert page.driver is None

    def test_open_translates_driver_creation_failure(self, mocker):
        page = WebPageSeleniumFirefox("http://example.com")
        failure = selenium.common.exceptions.SessionNotCreatedException("no grid")
        page._create_driver = mocker.Mock(side_effect=failure)
        with pytest.raises(WebPageBrowserError) as exc:
            page.open()
        assert exc.value.__cause__ is failure
        assert page.driver is None

    def test_webdriver_error_alias(self):
        from pyscraper import webpage as webpage_module

        assert webpage_module.WebPageWebDriverError is WebPageBrowserError

    @pytest.mark.parametrize("method", ["move_to", "go", "forward", "back", "refresh"])
    def test_navigation_translates(self, mocker, method):
        from selenium.webdriver.common.action_chains import ActionChains

        page = WebPageSeleniumFirefox()
        page.driver = mocker.Mock()
        failure = selenium.common.exceptions.WebDriverException("gone")
        if method == "move_to":
            mocker.patch.object(ActionChains, "move_to_element", side_effect=failure)

            def call():
                page.move_to("//a")
        elif method == "go":
            page.driver.get.side_effect = failure

            def call():
                page.go("https://example.com")
        elif method == "forward":
            page.driver.forward.side_effect = failure

            def call():
                page.forward()
        elif method == "back":
            page.driver.back.side_effect = failure

            def call():
                page.back()
        else:
            page.driver.refresh.side_effect = failure

            def call():
                page.refresh()

        with pytest.raises(WebPageBrowserError) as exc:
            call()
        assert exc.value.__cause__ is failure

    @pytest.mark.parametrize("prop", ["url", "html", "cookies", "user_agent"])
    def test_property_translates(self, mocker, prop):
        page = WebPageSeleniumFirefox("https://example.com")
        page.driver = mocker.Mock()
        failure = selenium.common.exceptions.WebDriverException("crashed")
        if prop == "url":
            mocker.patch.object(
                type(page.driver),
                "current_url",
                new_callable=mocker.PropertyMock,
                side_effect=failure,
                create=True,
            )
        elif prop == "html":
            mocker.patch.object(
                type(page.driver),
                "page_source",
                new_callable=mocker.PropertyMock,
                side_effect=failure,
                create=True,
            )
        elif prop == "cookies":
            page.driver.get_cookies.side_effect = failure
        else:
            page.driver.execute_script.side_effect = failure
        with pytest.raises(WebPageBrowserError) as exc:
            getattr(page, prop)
        assert exc.value.__cause__ is failure

    def test_element_property_translates(self, mocker):
        element = mocker.Mock()
        failure = selenium.common.exceptions.StaleElementReferenceException("gone")
        element.get_attribute.side_effect = failure
        wrapped = SeleniumWebPageElement(element)
        with pytest.raises(WebPageStaleElementReferenceError) as exc:
            _ = wrapped.html
        assert exc.value.__cause__ is failure


class TestStatusCode:
    @pytest.mark.parametrize(
        ("status", "expected"),
        [(403, WebFileClientError), (404, WebFileClientError), (500, WebFileServerError)],
        ids=["403", "404", "500"],
    )
    def test_http_errors_carry_status_code(self, status, expected):
        with pytest.raises(expected) as exc:
            with WebFile(f"https://httpbin.org/status/{status}"):
                pass
        assert exc.value.status_code == status

    def test_connection_error_has_no_status_code(self):
        with pytest.raises(WebFileConnectionError) as exc:
            with WebFile("http://a.temeteke.com"):
                pass
        assert exc.value.status_code is None

    def test_timeout_error_has_no_status_code(self, mocker):
        session = mocker.Mock()
        session.headers = {}
        session.cookies = {}
        session.get.side_effect = requests.exceptions.Timeout("timed out")
        with pytest.raises(WebFileTimeoutError) as exc:
            with WebFile("https://example.com/file", session=session):
                pass
        assert exc.value.status_code is None

    def test_request_residue_wraps_as_webfile_error(self, mocker):
        session = mocker.Mock()
        session.headers = {}
        session.cookies = {}
        failure = requests.exceptions.TooManyRedirects("loop")
        session.get.side_effect = failure
        with pytest.raises(WebFileError) as exc:
            with WebFile("https://example.com/file", session=session):
                pass
        assert exc.value.__cause__ is failure
        assert exc.value.status_code is None

    def test_invalid_url_wraps_as_webfile_error(self, mocker):
        session = mocker.Mock()
        session.headers = {}
        session.cookies = {}
        failure = requests.exceptions.InvalidURL("bad url")
        session.get.side_effect = failure
        with pytest.raises(WebFileError) as exc:
            with WebFile("https://example.com/file", session=session):
                pass
        assert exc.value.__cause__ is failure

    def test_read_residue_wraps_as_connection_error(self, mocker, mock_http_response):
        response = mock_http_response(200, b"x" * 16)
        failure = urllib3.exceptions.ClosedPoolError("pool", "closed")
        response.raw.read = mocker.Mock(side_effect=failure)
        wf = WebFile("https://example.com/file")
        wf.response = response
        with pytest.raises(WebFileConnectionError) as exc:
            wf.read()
        assert exc.value.__cause__ is failure


class TestPlaywrightTranslation:
    def test_page_click_timeout(self, mocker):
        from playwright.sync_api import Error as PlaywrightError
        from playwright.sync_api import TimeoutError as PlaywrightTimeoutError

        assert issubclass(PlaywrightTimeoutError, PlaywrightError)
        from pyscraper.webpage_playwright import WebPagePlaywrightChromium

        page = WebPagePlaywrightChromium("https://example.com")
        page._page = mocker.Mock()
        failure = PlaywrightTimeoutError("Timeout 10000ms exceeded")
        page._page.locator.return_value.click.side_effect = failure
        with pytest.raises(WebPageTimeoutError) as exc:
            page.click("//a")
        assert exc.value.__cause__ is failure
        assert str(exc.value)

    def test_page_click_browser_error(self, mocker):
        from playwright.sync_api import Error as PlaywrightError

        from pyscraper.webpage_playwright import WebPagePlaywrightChromium

        page = WebPagePlaywrightChromium("https://example.com")
        page._page = mocker.Mock()
        failure = PlaywrightError("Target crashed")
        page._page.locator.return_value.click.side_effect = failure
        with pytest.raises(WebPageBrowserError) as exc:
            page.click("//a")
        assert exc.value.__cause__ is failure
        assert str(exc.value)

    def test_open_translates(self, mocker):
        from playwright.sync_api import Error as PlaywrightError

        from pyscraper.webpage_playwright import WebPagePlaywrightChromium

        page = WebPagePlaywrightChromium("https://example.com")
        failure = PlaywrightError("browser closed")
        mocker.patch("playwright.sync_api.sync_playwright", side_effect=failure)
        with pytest.raises(WebPageBrowserError) as exc:
            page.open()
        assert exc.value.__cause__ is failure

    @pytest.mark.parametrize("prop", ["url", "html", "cookies", "user_agent"])
    def test_property_translates(self, mocker, prop):
        from playwright.sync_api import Error as PlaywrightError

        from pyscraper.webpage_playwright import WebPagePlaywrightChromium

        page = WebPagePlaywrightChromium("https://example.com")
        page._page = mocker.Mock()
        page._context = mocker.Mock()
        failure = PlaywrightError("crashed")
        if prop == "url":
            mocker.patch.object(
                type(page._page),
                "url",
                new_callable=mocker.PropertyMock,
                side_effect=failure,
                create=True,
            )
        elif prop == "html":
            page._page.content.side_effect = failure
        elif prop == "cookies":
            page._context.cookies.side_effect = failure
        else:
            page._page.evaluate.side_effect = failure
        with pytest.raises(WebPageBrowserError) as exc:
            getattr(page, prop)
        assert exc.value.__cause__ is failure

    def test_switch_to_frame_translates(self, mocker):
        from playwright.sync_api import Error as PlaywrightError

        from pyscraper.webpage_playwright import WebPagePlaywrightChromium

        page = WebPagePlaywrightChromium("https://example.com")
        page._page = mocker.Mock()
        failure = PlaywrightError("crashed")
        page._page.locator.return_value.get_attribute.side_effect = failure
        with pytest.raises(WebPageBrowserError) as exc:
            page.switch_to_frame("//iframe")
        assert exc.value.__cause__ is failure

    def test_element_property_translates(self, mocker):
        from playwright.sync_api import Error as PlaywrightError

        from pyscraper.webpage_playwright import PlaywrightWebPageElement

        locator = mocker.Mock()
        failure = PlaywrightError("detached")
        locator.evaluate.side_effect = failure
        with pytest.raises(WebPageBrowserError) as exc:
            _ = PlaywrightWebPageElement(locator).html
        assert exc.value.__cause__ is failure


class TestRequestsCurlTranslation:
    @pytest.mark.parametrize(
        ("failure", "expected"),
        [
            (requests.exceptions.ConnectionError("dns"), WebPageConnectionError),
            (requests.exceptions.Timeout("slow"), WebPageTimeoutError),
            (requests.exceptions.TooManyRedirects("loop"), WebPageError),
            (requests.exceptions.InvalidURL("bad"), WebPageError),
        ],
        ids=["connection", "timeout", "redirects", "invalid-url"],
    )
    def test_requests_open_response(self, mocker, failure, expected):
        session = mocker.Mock()
        session.headers = {}
        session.cookies = {}
        session.get.side_effect = failure
        with pytest.raises(expected) as exc:
            with WebPageRequests("https://example.com", session=session):
                pass
        assert exc.value.__cause__ is failure
        assert exc.value.status_code is None

    @pytest.mark.parametrize(
        "failure",
        [
            subprocess.CalledProcessError(7, ["curl", "https://example.com"]),
            OSError("curl missing"),
        ],
        ids=["nonzero-exit", "os-error"],
    )
    def test_curl_html(self, mocker, failure):
        mocker.patch("pyscraper.webpage_curl.subprocess.run", side_effect=failure)
        with pytest.raises(WebPageConnectionError) as exc:
            _ = WebPageCurl("https://example.com").html
        assert exc.value.__cause__ is failure

    def test_curl_decode_failure(self, mocker):
        result = mocker.Mock()
        result.stdout = b"\xff\xfe invalid"
        mocker.patch("pyscraper.webpage_curl.subprocess.run", return_value=result)
        with pytest.raises(WebPageError) as exc:
            _ = WebPageCurl("https://example.com").html
        assert isinstance(exc.value.__cause__, UnicodeDecodeError)

    def test_curl_unknown_encoding(self, mocker):
        result = mocker.Mock()
        result.stdout = b"<html></html>"
        mocker.patch("pyscraper.webpage_curl.subprocess.run", return_value=result)
        page = WebPageCurl("https://example.com")
        page.encoding = "unknown-encoding-xyz"
        with pytest.raises(WebPageError) as exc:
            _ = page.html
        assert isinstance(exc.value.__cause__, LookupError)


class TestHlsTranslation:
    def test_playlist_decode_failure(self, mocker, mock_http_response):
        response = mock_http_response(200, b"\xff\xfe invalid", {}, "https://x/v.m3u8")

        class _Raw:
            def read(self, size=None):
                return b"\xff\xfe invalid"

        response.raw = _Raw()
        session = mocker.Mock()
        session.headers = {}
        session.cookies = {}
        session.get.return_value = response
        hls = HlsFile("https://example.com/v.m3u8", session=session)
        with pytest.raises(HlsFileError) as exc:
            _ = hls.m3u8_obj
        assert isinstance(exc.value.__cause__, UnicodeDecodeError)
        assert str(exc.value)

    def test_merge_failure(self, mocker, tmp_path):
        import ffmpy

        hls = HlsFile("https://example.com/v.m3u8", directory=tmp_path)
        failure = ffmpy.FFRuntimeError("cmd", "out", "err", 1)
        mocker.patch("pyscraper.hlsfile.ffmpy.FFmpeg.run", side_effect=failure)
        with pytest.raises(HlsFileError) as exc:
            hls._merge_resources(tmp_path / "in.m3u8", tmp_path / "out.mp4")
        assert exc.value.__cause__ is failure
        assert str(exc.value)

    def test_empty_playlist(self, mocker, mock_http_response):
        response = mock_http_response(
            200,
            b"#EXTM3U\n",
            {"Content-Type": "application/vnd.apple.mpegurl"},
            "https://example.com/empty.m3u8",
        )
        session = mocker.Mock()
        session.headers = {}
        session.cookies = {}
        session.get.return_value = response
        hls = HlsFile("https://example.com/empty.m3u8", session=session)
        with pytest.raises(HlsFileError, match="Empty playlist"):
            _ = hls.m3u8_obj

    def test_empty_playlist_exists_false(self, mocker, mock_http_response):
        response = mock_http_response(
            200,
            b"#EXTM3U\n",
            {"Content-Type": "application/vnd.apple.mpegurl"},
            "https://example.com/empty.m3u8",
        )
        session = mocker.Mock()
        session.headers = {}
        session.cookies = {}
        session.get.return_value = response
        hls = HlsFile("https://example.com/empty.m3u8", session=session)
        assert hls.exists() is False

    def test_lxml_parse_failure(self, mocker):
        import lxml.etree

        element = mocker.Mock()
        failure = lxml.etree.ParserError("empty")
        mocker.patch("lxml.html.fromstring", side_effect=failure)
        wrapped = SeleniumWebPageElement(element)
        with pytest.raises(WebPageError) as exc:
            _ = wrapped.lxml_html
        assert exc.value.__cause__ is failure
