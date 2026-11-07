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
    WebFileSeekError,
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


class _ChunkLengthStub:
    """Minimal response stub for ``InvalidChunkLength``."""

    length_remaining = 0

    def tell(self):
        return 0


class TestWebFileReadErrors:
    @staticmethod
    def _webfile_with_read_failure(mocker, mock_http_response, failure):
        response = mock_http_response(200, b"x" * 16)
        response.raw.read = mocker.Mock(side_effect=failure)
        wf = WebFile("https://example.com/file")
        wf.response = response
        return wf

    @pytest.mark.parametrize(
        ("make_failure", "expected"),
        [
            (
                lambda: urllib3.exceptions.ReadTimeoutError(None, "/", "Read timed out."),
                WebFileTimeoutError,
            ),
            (lambda: urllib3.exceptions.TimeoutError("timed out"), WebFileTimeoutError),
            (lambda: urllib3.exceptions.ConnectTimeoutError(), WebFileTimeoutError),
            (
                lambda: urllib3.exceptions.NewConnectionError(None, "refused"),
                WebFileConnectionError,
            ),
            (
                lambda: urllib3.exceptions.NameResolutionError("example.com", None, "dns"),
                WebFileConnectionError,
            ),
            (lambda: urllib3.exceptions.ProtocolError("broken"), WebFileConnectionError),
            (
                lambda: urllib3.exceptions.MaxRetryError(None, "/", "retries"),
                WebFileConnectionError,
            ),
            (lambda: urllib3.exceptions.SSLError("bad cert"), WebFileConnectionError),
            (
                lambda: urllib3.exceptions.ProxyError("proxy", OSError("down")),
                WebFileConnectionError,
            ),
            (lambda: urllib3.exceptions.IncompleteRead(1, 2), WebFileConnectionError),
            (
                lambda: urllib3.exceptions.InvalidChunkLength(_ChunkLengthStub(), b"z"),
                WebFileConnectionError,
            ),
            (
                lambda: urllib3.exceptions.ResponseNotChunked("not chunked"),
                WebFileError,
            ),
            (lambda: urllib3.exceptions.DecodeError("bad gzip"), WebFileError),
            (
                lambda: urllib3.exceptions.ClosedPoolError(None, "closed"),
                WebFileError,
            ),
            (lambda: urllib3.exceptions.HTTPError("generic"), WebFileError),
        ],
        ids=[
            "read-timeout",
            "timeout",
            "connect-timeout",
            "new-connection",
            "name-resolution",
            "protocol",
            "max-retry",
            "ssl",
            "proxy",
            "incomplete-read",
            "invalid-chunk-length",
            "response-not-chunked",
            "decode",
            "closed-pool",
            "generic-http",
        ],
    )
    def test_read_maps_urllib3_residue(self, mocker, mock_http_response, make_failure, expected):
        failure = make_failure()
        wf = self._webfile_with_read_failure(mocker, mock_http_response, failure)
        with pytest.raises(expected) as exc:
            wf.read()
        assert exc.value.__cause__ is failure
        assert exc.value.status_code is None
        assert type(exc.value) is expected

    def test_read_propagates_non_urllib3_errors(self, mocker, mock_http_response):
        failure = ValueError("programmer error")
        wf = self._webfile_with_read_failure(mocker, mock_http_response, failure)
        with pytest.raises(ValueError) as exc:
            wf.read()
        assert exc.value is failure


class TestWebFileSizeHeader:
    @pytest.mark.parametrize(
        ("status", "headers", "header_name"),
        [
            (200, {"Content-Length": "abc"}, "Content-Length"),
            (206, {"Content-Range": "bytes 0-9/abc"}, "Content-Range"),
            (206, {"Content-Range": "bytes 0-9/"}, "Content-Range"),
            (206, {"Content-Range": "bytes 0-9"}, "Content-Range"),
        ],
        ids=[
            "content-length",
            "content-range",
            "content-range-empty-total",
            "content-range-no-slash",
        ],
    )
    def test_malformed_size_header_raises_webfile_error(
        self, mock_http_response, status, headers, header_name
    ):
        response = mock_http_response(status, b"x" * 10, headers)
        wf = WebFile("https://example.com/file")
        wf.response = response
        with pytest.raises(WebFileError) as exc:
            _ = wf.size
        assert type(exc.value) is WebFileError
        assert exc.value.status_code is None
        assert isinstance(exc.value.__cause__, ValueError)
        assert header_name in str(exc.value)
        assert repr(headers[header_name].split("/")[-1]) in str(exc.value)

    @pytest.mark.parametrize(
        ("status", "headers"),
        [
            (200, {"Content-Length": "-5"}),
            (206, {"Content-Range": "bytes 0-9/-5"}),
        ],
        ids=["content-length", "content-range"],
    )
    def test_negative_size_header_raises_webfile_error(self, mock_http_response, status, headers):
        response = mock_http_response(status, b"x" * 10, headers)
        wf = WebFile("https://example.com/file")
        wf.response = response
        with pytest.raises(WebFileError) as exc:
            _ = wf.size
        assert type(exc.value) is WebFileError
        assert exc.value.status_code is None
        assert exc.value.__cause__ is None

    def test_content_range_takes_priority(self, mock_http_response):
        response = mock_http_response(
            206,
            b"x",
            {"Content-Range": "bytes 0-0/123", "Content-Length": "1"},
        )
        wf = WebFile("https://example.com/file")
        wf.response = response
        assert wf.size == 123

    def test_content_range_used_when_content_length_is_blank(self, mock_http_response):
        response = mock_http_response(
            206,
            b"x",
            {"Content-Range": "bytes 0-0/123", "Content-Length": "   "},
        )
        wf = WebFile("https://example.com/file")
        wf.response = response
        assert wf.size == 123

    def test_content_length_used_without_content_range(self, mock_http_response):
        response = mock_http_response(200, b"x", {"Content-Length": "42"})
        wf = WebFile("https://example.com/file")
        wf.response = response
        assert wf.size == 42

    def test_missing_size_headers_returns_none(self, mock_http_response):
        response = mock_http_response(200, b"x")
        wf = WebFile("https://example.com/file")
        wf.response = response
        assert wf.size is None

    def test_unknown_content_range_length_returns_none(self, mock_http_response):
        # RFC 9110 allows "*" for an unknown complete-length.
        response = mock_http_response(
            206,
            b"x",
            {"Content-Range": "bytes 0-0/*", "Content-Length": "1"},
        )
        wf = WebFile("https://example.com/file")
        wf.response = response
        assert wf.size is None

    @pytest.mark.parametrize(
        ("header", "value"),
        [
            ("Content-Length", ""),
            ("Content-Length", "   "),
            ("Content-Range", ""),
            ("Content-Range", "   "),
        ],
        ids=["length-empty", "length-blank", "range-empty", "range-blank"],
    )
    def test_blank_size_header_is_treated_as_missing(self, mock_http_response, header, value):
        response = mock_http_response(200, b"x", {header: value})
        wf = WebFile("https://example.com/file")
        wf.response = response
        assert wf.size is None

    def test_blank_content_range_does_not_fall_back_to_content_length(self, mock_http_response):
        response = mock_http_response(
            206,
            b"x",
            {"Content-Range": "   ", "Content-Length": "42"},
        )
        wf = WebFile("https://example.com/file")
        wf.response = response
        assert wf.size is None

    def test_206_without_content_range_returns_none(self, mock_http_response):
        # Content-Length on a 206 is only the partial body length.
        response = mock_http_response(206, b"x", {"Content-Length": "10"})
        wf = WebFile("https://example.com/file")
        wf.response = response
        assert wf.size is None

    def test_size_without_open_raises_error(self):
        wf = WebFile("https://example.com/file")
        with pytest.raises(WebFileError, match="not opened"):
            _ = wf.size

    def test_unknown_total_makes_seek_fail(self, mock_http_response):
        response = mock_http_response(
            206,
            b"x",
            {"Accept-Ranges": "bytes", "Content-Range": "bytes 0-0/*"},
        )
        wf = WebFile("https://example.com/file")
        wf.response = response
        with pytest.raises(WebFileSeekError, match="unknown"):
            wf.seek(0)


class TestWebFileDownloadSize:
    def test_resume_unknown_total_uses_pre_seek_size(self, mocker, mock_http_response, tmp_path):
        content = b"x" * 1024
        temp_file = tmp_path / "file.part"
        temp_file.write_bytes(content[:128])

        initial = mock_http_response(200, content, {"Content-Length": "1024"})
        ranged = mock_http_response(
            206,
            content[128:],
            {"Content-Range": "bytes 128-1023/*", "Content-Length": "896"},
        )

        wf = WebFile("https://example.com/file", directory=tmp_path, filename="file")
        wf.response = initial

        def fake_seek(offset):
            wf.response = ranged
            return offset

        mocker.patch.object(wf, "seek", side_effect=fake_seek)
        wf._download_known_size(wf, temp_file, None)

        assert temp_file.read_bytes() == content

    def test_resume_unknown_total_still_verifies_expected_size(
        self, mocker, mock_http_response, tmp_path
    ):
        content = b"x" * 1024
        temp_file = tmp_path / "file.part"
        temp_file.write_bytes(content[:128])

        initial = mock_http_response(200, content, {"Content-Length": "1024"})
        # Deliberately short body: verification must still use the pre-seek 1024.
        ranged = mock_http_response(
            206,
            content[128:256],
            {"Content-Range": "bytes 128-255/*", "Content-Length": "128"},
        )

        wf = WebFile("https://example.com/file", directory=tmp_path, filename="file")
        wf.response = initial

        def fake_seek(offset):
            wf.response = ranged
            return offset

        mocker.patch.object(wf, "seek", side_effect=fake_seek)
        with pytest.raises(WebFileError, match="smaller than expected"):
            wf._download_known_size(wf, temp_file, None)
        assert temp_file.exists()

    def test_resume_progress_callback_uses_pre_seek_total(
        self, mocker, mock_http_response, tmp_path
    ):
        content = b"x" * 1024
        temp_file = tmp_path / "file.part"
        temp_file.write_bytes(content[:128])

        initial = mock_http_response(200, content, {"Content-Length": "1024"})
        ranged = mock_http_response(
            206,
            content[128:],
            {"Content-Range": "bytes 128-1023/*", "Content-Length": "896"},
        )

        wf = WebFile("https://example.com/file", directory=tmp_path, filename="file")
        wf.response = initial

        def fake_seek(offset):
            wf.response = ranged
            return offset

        progresses = []
        mocker.patch.object(wf, "seek", side_effect=fake_seek)
        wf._download_known_size(
            wf, temp_file, lambda current, total: progresses.append((current, total))
        )

        assert progresses[-1] == (1024, 1024)

    def test_download_rejects_initial_206_with_unknown_size(
        self, mocker, mock_http_response, tmp_path
    ):
        response = mock_http_response(
            206,
            b"x" * 100,
            {"Content-Range": "bytes 0-99/*", "Content-Length": "100"},
        )
        session = mocker.Mock()
        session.headers = {}
        session.cookies = {}
        session.get.return_value = response
        wf = WebFile(
            "https://example.com/file",
            session=session,
            directory=tmp_path,
            filename="file",
        )
        with pytest.raises(WebFileError, match="partial response"):
            wf.download()
        assert not wf.filepath.exists()

    def test_download_malformed_content_length_raises_webfile_error(
        self, mocker, mock_http_response, tmp_path
    ):
        response = mock_http_response(200, b"x", {"Content-Length": "abc"})
        session = mocker.Mock()
        session.headers = {}
        session.cookies = {}
        session.get.return_value = response
        wf = WebFile(
            "https://example.com/file",
            session=session,
            directory=tmp_path,
            filename="file",
        )
        with pytest.raises(WebFileError, match="Invalid Content-Length"):
            wf.download()
        assert not wf.filepath.exists()


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

    def test_requests_exists_propagates_connection_error(self, mocker):
        failure = requests.exceptions.ConnectionError("dns")
        session = mocker.Mock()
        session.headers = {}
        session.cookies = {}
        session.get.side_effect = failure

        with pytest.raises(WebPageConnectionError) as exc:
            WebPageRequests("https://example.com", session=session).exists()

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
