"""Integration tests for WebFile using real HTTP endpoints.

These tests make actual network requests to httpbin.org and other services.
They verify that the library works correctly with real-world HTTP responses.

Run with:
    pytest tests/integration/test_webfile_integration.py -m integration -v

Or set environment variable:
    INTEGRATION_TEST=1 pytest tests/integration/test_webfile_integration.py -v
"""
import pytest
from pathlib import Path
from pyscraper.webfile import WebFile, WebFileError


@pytest.mark.integration
class TestWebFileIntegration:
    """Integration tests using real httpbin.org endpoints."""

    @pytest.mark.integration
    def test_real_http_download(self, tmp_path):
        """Test downloading a file from real httpbin.org"""
        url = "https://httpbin.org/bytes/1024"
        wf = WebFile(url, directory=tmp_path)

        with wf as f:
            content = f.read()
            assert len(content) == 1024

        # Clean up
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


@pytest.mark.integration
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


# Note: These tests require network access and may fail if:
# - httpbin.org is down
# - Network connectivity issues
# - Firewall blocks external requests
#
# For CI/CD, run these tests on main branch merges or scheduled runs,
# not on every commit.
