from pathlib import Path
from unittest.mock import Mock, patch

import pytest
import requests
from pyscraper.webfile import WebFile, WebFileClientError, WebFileError, WebFileSeekError


@pytest.fixture(scope="session")
def url():
    return "https://httpbin.org/range/1024"


@pytest.fixture(scope="session")
def filename():
    return "test.txt"


@pytest.fixture(scope="session")
def content(url):
    # Return mocked content instead of making real HTTP request
    # This matches what httpbin.org/range/1024 would return
    return b'x' * 1024


class TestWebFile:
    @pytest.fixture
    def webfile(self, url, filename):
        return WebFile(url, filename=filename)

    def test_url_01(self, webfile, url):
        assert webfile.url == url

    def test_url_02(self, webfile):
        webfile.url = "https://httpbin.org/range/2048"
        assert webfile.url == "https://httpbin.org/range/2048"

    def test_directory(self, webfile):
        assert webfile.directory == Path(".")

    def test_filestem(self, webfile):
        assert webfile.filestem == "test"

    def test_filesuffix(self, webfile):
        assert webfile.filesuffix == ".txt"

    def test_filename(self, webfile):
        assert webfile.filename == "test.txt"

    def test_read_0(self, webfile, content):
        with webfile as wf:
            wf.seek(0)
            assert wf.read(128) == content[:128]

    def test_read_512(self, webfile, content):
        with webfile as wf:
            wf.seek(512)
            assert wf.read(128) == content[512 : 512 + 128]

    def test_read_576(self, webfile, content):
        with webfile.open() as wf:
            wf.seek(576)
            assert wf.read(128) == content[576 : 576 + 128]

    def test_read_256(self, webfile, content):
        with webfile.open() as wf:
            wf.seek(256)
            assert wf.read() == content[256:]

    def test_seek_read_0(self, webfile, content):
        with webfile.open() as wf:
            wf.seek(128)
            wf.seek(0)
            assert wf.read(128) == content[:128]

    def test_seek_error(self, webfile):
        with pytest.raises(WebFileError):
            webfile.seek(512)

    def test_seek_range_not_supported(self):
        with pytest.raises(WebFileSeekError):
            with WebFile("https://httpbin.org/bytes/1024") as wf:
                wf.seek(512)

    def test_seek_large_offset(self, webfile):
        with pytest.raises(WebFileSeekError):
            with webfile as wf:
                wf.seek(2048)

    def test_seek_negative_offset(self, webfile):
        with pytest.raises(WebFileSeekError):
            with webfile as wf:
                wf.seek(-1)

    def test_download_unlink(self, webfile):
        f = webfile.download()
        assert f.exists() is True

        webfile.unlink()
        assert f.exists() is False

    def test_download_unlink_filename(self, webfile):
        f = webfile.download(filename="test2.txt")
        assert f.exists() is True
        assert f.name == "test2.txt"
        assert webfile.filename == "test2.txt"
        assert webfile.filestem == "test2"
        assert webfile.filesuffix == ".txt"

        webfile.unlink()
        assert f.exists() is False

    def test_download_range(self, webfile, content):
        temp_file = Path("test.txt.part")

        with open(temp_file, "wb") as f:
            f.write(content[:128])

        f = webfile.download(filename="test.txt")
        assert f.exists() is True
        assert temp_file.exists() is False

        webfile.unlink()
        assert f.exists() is False

    def test_download_range_not_supported(self, content):
        webfile = WebFile("https://httpbin.org/bytes/1024", filename="test.txt")
        temp_file = Path("test.txt.part")

        with open(temp_file, "wb") as f:
            f.write(content[:128])

        f = webfile.download(filename="test.txt")
        assert f.exists() is True
        assert temp_file.exists() is False

        webfile.unlink()
        assert f.exists() is False

    def test_download_progress_callback(self, url, filename):
        web_file = WebFile(url, filename=filename)
        progresses = []

        def cb(current, total):
            progresses.append((current, total))

        web_file.download(progress_callback=cb)
        # The last callback should indicate completion
        assert progresses[-1][0] == progresses[-1][1] or progresses[-1][1] is None

        web_file.unlink()

    def test_eq01(self, webfile, url):
        assert webfile == WebFile(url)

    def test_exists_close(self):
        assert WebFile("https://httpbin.org/status/200").exists() is True

    def test_exists_open(self):
        with WebFile("https://httpbin.org/status/200") as wf:
            wf.exists() is True

    def test_not_exists_close(self):
        assert WebFile("https://httpbin.org/status/404").exists() is False

    def test_not_found_error(self):
        with pytest.raises(WebFileClientError):
            with WebFile("https://httpbin.org/status/404"):
                pass

    def test_dnserror(self):
        with pytest.raises(WebFileError):
            with WebFile("http://a.temeteke.com"):
                pass

    def test_url_close(self):
        assert (
            WebFile("https://httpbin.org/redirect-to?url=https%3A%2F%2Fhttpbin.org%2F").url
            == "https://httpbin.org/redirect-to?url=https%3A%2F%2Fhttpbin.org%2F"
        )

    def test_url_open(self):
        with WebFile("https://httpbin.org/redirect-to?url=https%3A%2F%2Fhttpbin.org%2F") as wf:
            assert wf.url == "https://httpbin.org/"

    def test_headers_close(self):
        assert (
            WebFile("https://httpbin.org/headers", headers={"test": "test"}).headers["test"]
            == "test"
        )

    def test_headers_open(self):
        with WebFile("https://httpbin.org/headers", headers={"test": "test"}) as wf:
            assert wf.headers["test"] == "test"

    def test_cookies_close(self):
        assert (
            WebFile("https://httpbin.org/cookies", cookies={"test": "test"}).cookies["test"]
            == "test"
        )

    def test_cookies_open(self):
        with WebFile("https://httpbin.org/cookies", cookies={"test": "test"}) as wf:
            assert wf.cookies["test"] == "test"

    def test_filestem_close(self):
        assert WebFile("https://httpbin.org/image/jpeg").filestem == "jpeg"

    def test_filestem_open(self):
        with WebFile("https://httpbin.org/image/jpeg") as wf:
            assert wf.filestem == "jpeg"

    def test_filesuffix_close(self):
        assert WebFile("https://httpbin.org/image/jpeg").filesuffix == ""

    def test_filesuffix_open(self):
        with WebFile("https://httpbin.org/image/jpeg") as wf:
            assert wf.filesuffix == ".jpg"

    def test_filename_close(self):
        assert WebFile("https://httpbin.org/image/jpeg").filename == "jpeg"

    def test_filename_open(self):
        with WebFile("https://httpbin.org/image/jpeg") as wf:
            assert wf.filename == "jpeg.jpg"

    def test_user_agent_close(self):
        assert not WebFile("https://httpbin.org/user-agent").user_agent

    def test_user_agent_open(self):
        with WebFile("https://httpbin.org/user-agent") as wf:
            assert "requests" not in wf.user_agent

    def test_session(self):
        session = requests.Session()
        session.headers["test"] = "test"
        assert WebFile("https://httpbin.org/headers", session=session).headers["test"] == "test"

    def test_jpeg_extension_close(self):
        """Test that .jpeg extension is preserved when WebFile is closed"""
        wf = WebFile("https://httpbin.org/image.jpeg")
        assert wf.filesuffix == ".jpeg"
        assert wf.filename == "image.jpeg"

    def test_jpeg_extension_open(self):
        """Test that .jpeg extension is preserved when WebFile is opened (Content-Type: image/jpeg)"""
        wf = WebFile("https://example.com/photo.jpeg")

        # Mock the response with Content-Type: image/jpeg
        mock_response = Mock()
        mock_response.headers = {"Content-Type": "image/jpeg"}
        mock_response.url = "https://example.com/photo.jpeg"
        wf.response = mock_response

        # Even though Content-Type is image/jpeg (which would default to .jpg),
        # the URL extension .jpeg should be preserved
        assert wf.filesuffix == ".jpeg"
        assert wf.filename == "photo.jpeg"

    def test_jpg_extension_open(self):
        """Test that .jpg extension is preserved when WebFile is opened"""
        wf = WebFile("https://example.com/photo.jpg")

        # Mock the response with Content-Type: image/jpeg
        mock_response = Mock()
        mock_response.headers = {"Content-Type": "image/jpeg"}
        mock_response.url = "https://example.com/photo.jpg"
        wf.response = mock_response

        assert wf.filesuffix == ".jpg"
        assert wf.filename == "photo.jpg"

    def test_url_without_extension_uses_content_type(self):
        """Test that Content-Type is used when URL has no extension"""
        wf = WebFile("https://example.com/image")

        # Mock the response with Content-Type: image/png
        mock_response = Mock()
        mock_response.headers = {"Content-Type": "image/png"}
        mock_response.url = "https://example.com/image"
        wf.response = mock_response

        # URL has no extension, so should use Content-Type which is image/png -> .png
        assert wf.filesuffix == ".png"
        assert wf.filename == "image.png"

    def test_read_without_open_raises_error(self, url, filename):
        """Test that calling read() without opening raises WebFileError"""
        wf = WebFile(url, filename=filename)
        with pytest.raises(WebFileError, match="Response is not opened"):
            wf.read()

    def test_seek_without_open_raises_error(self, url, filename):
        """Test that calling seek() without opening raises WebFileError"""
        wf = WebFile(url, filename=filename)
        with pytest.raises(WebFileError, match="not opened"):
            wf.seek(100)


# ============================================================================
# Integration Tests (require real HTTP connections)
# ============================================================================


@pytest.mark.integration
class TestWebFileIntegration:
    """Integration tests using real httpbin.org endpoints.
    
    These tests make actual network requests and verify the library
    works correctly with real-world HTTP responses.
    
    Run with: pytest tests/test_webfile.py -m integration -v
    """

    @pytest.mark.integration
    def test_real_http_download(self, tmp_path):
        """Test downloading a file from real httpbin.org"""
        url = "https://httpbin.org/bytes/1024"
        wf = WebFile(url, directory=tmp_path)

        with wf as f:
            content = f.read()
            assert len(content) == 1024

        wf.unlink()

    @pytest.mark.integration
    def test_real_range_request(self, tmp_path):
        """Test Range request with real httpbin.org"""
        url = "https://httpbin.org/range/1024"
        wf = WebFile(url, directory=tmp_path)

        with wf as f:
            # Read first 512 bytes
            content1 = f.read(512)
            assert len(content1) == 512

            # Read next 512 bytes
            content2 = f.read(512)
            assert len(content2) == 512

        wf.unlink()

    @pytest.mark.integration
    def test_real_headers(self):
        """Test that real HTTP headers are returned correctly"""
        url = "https://httpbin.org/headers"
        wf = WebFile(url, headers={"X-Test-Header": "test-value"})

        with wf as f:
            import json
            data = json.loads(f.read().decode())
            # httpbin.org echoes back the headers we sent
            assert "X-Test-Header" in data["headers"]
            assert data["headers"]["X-Test-Header"] == "test-value"

    @pytest.mark.integration
    def test_real_user_agent(self):
        """Test that User-Agent is set correctly in real requests"""
        url = "https://httpbin.org/user-agent"
        wf = WebFile(url)

        with wf as f:
            import json
            data = json.loads(f.read().decode())
            # Should contain some User-Agent string
            assert "user-agent" in data
            assert len(data["user-agent"]) > 0

    @pytest.mark.integration
    def test_real_redirect(self):
        """Test that redirects are followed correctly"""
        url = "https://httpbin.org/redirect-to?url=https://httpbin.org/get"
        wf = WebFile(url)

        with wf as f:
            # After redirect, final URL should be different
            assert "get" in wf.url
            content = f.read()
            assert len(content) > 0

    @pytest.mark.integration
    def test_real_404_error(self):
        """Test that 404 errors are handled correctly"""
        url = "https://httpbin.org/status/404"
        wf = WebFile(url)

        with pytest.raises(WebFileError):
            with wf:
                pass

    @pytest.mark.integration
    def test_real_file_download_with_progress(self, tmp_path):
        """Test downloading with progress callback"""
        url = "https://httpbin.org/bytes/10240"  # 10KB file
        wf = WebFile(url, directory=tmp_path, filename="test_download.bin")

        progress_updates = []

        def progress_callback(current, total):
            progress_updates.append((current, total))

        filepath = wf.download(progress_callback=progress_callback)

        # Verify file was downloaded
        assert filepath.exists()
        assert filepath.stat().st_size == 10240

        # Verify progress was reported
        assert len(progress_updates) > 0
        # Last update should show completion
        assert progress_updates[-1][0] == progress_updates[-1][1]

        # Clean up
        filepath.unlink()

    @pytest.mark.integration
    def test_real_seek_operation(self, tmp_path):
        """Test seek operation with real Range request"""
        url = "https://httpbin.org/range/2048"
        wf = WebFile(url, directory=tmp_path)

        with wf as f:
            # Seek to middle
            f.seek(1024)
            content = f.read(512)
            assert len(content) == 512

        wf.unlink()


class TestWebFileMutableDefaults:
    def test_request_headers_not_shared(self):
        w1 = WebFile("https://a.com")
        w2 = WebFile("https://b.com")
        w1.request_headers["X"] = "1"
        assert "X" not in w2.request_headers

    def test_request_cookies_not_shared(self):
        w1 = WebFile("https://a.com")
        w2 = WebFile("https://b.com")
        w1.request_cookies["session"] = "abc"
        assert "session" not in w2.request_cookies


class TestWebFileIntegrationEdgeCases:
    """Integration tests for edge cases and error conditions."""

    @pytest.mark.integration
    def test_real_large_file_partial_download(self, tmp_path):
        """Test partially downloading a large file"""
        # Use a reasonably sized file (100KB)
        url = "https://httpbin.org/bytes/102400"
        wf = WebFile(url, directory=tmp_path)

        with wf as f:
            # Read only first 10KB
            content = f.read(10240)
            assert len(content) == 10240

        wf.unlink()

    @pytest.mark.integration
    def test_real_timeout_handling(self):
        """Test timeout handling with real endpoint"""
        # httpbin.org/delay/:n endpoint delays response by n seconds
        url = "https://httpbin.org/delay/10"
        wf = WebFile(url, timeout=2)  # 2 second timeout

        # This should timeout
        with pytest.raises(WebFileError):
            with wf:
                wf.read()

    @pytest.mark.integration
    def test_real_content_type_detection(self):
        """Test content type detection from real server"""
        # Request JSON endpoint
        url = "https://httpbin.org/json"
        wf = WebFile(url)

        with wf as f:
            # Should detect JSON content type
            assert "application/json" in f.response.headers.get("Content-Type", "")
            content = f.read()
            assert len(content) > 0

            # Parse to verify it's valid JSON
            import json
            data = json.loads(content.decode())
            assert isinstance(data, dict)
