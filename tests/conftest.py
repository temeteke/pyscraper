"""Pytest configuration and fixtures for mocking external dependencies."""

import pytest
from unittest.mock import Mock, MagicMock
from requests.exceptions import HTTPError


@pytest.fixture
def mock_http_response():
    """Factory for creating mock HTTP response objects.

    Usage:
        response = mock_http_response(status_code=200, content=b"test", headers={"Content-Type": "text/html"})
    """
    def _make_response(status_code=200, content=b"", headers=None, url=None):
        response = Mock()
        response.status_code = status_code
        response.content = content
        response.text = content.decode('utf-8', errors='ignore') if isinstance(content, bytes) else content
        response.headers = headers or {}
        response.url = url or "https://example.com/test"
        response.ok = 200 <= status_code < 300

        # Mock raise_for_status
        if 400 <= status_code < 600:
            error = HTTPError()
            error.response = response
            response.raise_for_status = Mock(side_effect=error)
        else:
            response.raise_for_status = Mock()

        # Mock iter_content for streaming
        chunk_size = 8192
        chunks = [content[i:i+chunk_size] for i in range(0, len(content), chunk_size)] if content else []
        response.iter_content = Mock(return_value=iter(chunks))

        # Mock raw for direct reading using BytesIO for proper stream behavior
        from io import BytesIO
        response.raw = BytesIO(content)
        response.raw.decode_content = True

        # Mock cookies
        response.cookies = {}

        return response
    return _make_response


@pytest.fixture
def mock_range_response(mock_http_response):
    """Factory for creating mock HTTP Range request responses.

    Usage:
        response = mock_range_response(start=0, end=127, total=1024)
    """
    def _make(start=0, end=127, total=1024, content=None):
        if content is None:
            content = b'x' * (end - start + 1)
        headers = {
            'Content-Range': f'bytes {start}-{end}/{total}',
            'Accept-Ranges': 'bytes',
            'Content-Length': str(len(content)),
            'Content-Type': 'application/octet-stream'
        }
        return mock_http_response(206, content, headers)
    return _make


@pytest.fixture
def mock_html_response(mock_http_response):
    """Factory for creating mock HTML responses.

    Usage:
        response = mock_html_response(html="<html><body>Test</body></html>")
    """
    def _make(html="<html><body></body></html>", encoding="utf-8", url=None):
        content = html.encode(encoding) if isinstance(html, str) else html
        headers = {
            'Content-Type': f'text/html; charset={encoding}',
            'Content-Length': str(len(content))
        }
        response = mock_http_response(200, content, headers, url)
        response.encoding = encoding
        response.apparent_encoding = encoding
        return response
    return _make


@pytest.fixture
def mock_redirect_response(mock_http_response):
    """Factory for creating mock redirect responses.

    Usage:
        response = mock_redirect_response(final_url="https://httpbin.org/")
    """
    def _make(original_url="https://example.com/redirect", final_url="https://example.com/final"):
        response = mock_http_response(200, b"Redirected content", url=final_url)
        response.history = [
            mock_http_response(301, b"", {"Location": final_url}, url=original_url)
        ]
        return response
    return _make


@pytest.fixture
def mock_session(mocker, mock_http_response):
    """Mock requests.Session for testing without actual HTTP calls.

    Usage:
        session = mock_session
        session.get.return_value = mock_http_response(200, b"test")
    """
    session = MagicMock()
    session.headers = {}
    session.cookies = {}

    # Default successful response
    session.get.return_value = mock_http_response(200, b"default response")
    session.post.return_value = mock_http_response(200, b"default response")

    return session


@pytest.fixture(autouse=True)
def mock_useragent(request, mocker):
    """Mock fake_useragent to avoid network calls.

    Skip mocking for integration tests or when explicitly disabled.
    """
    import os

    # Skip mocking for integration tests or when explicitly disabled
    if ('integration' in request.keywords or
        'no_mock' in request.keywords or
        os.getenv('INTEGRATION_TEST') == '1'):
        yield
        return

    # Mock UserAgent to return a static user agent string
    mock_ua = Mock()
    mock_ua.random = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"
    mocker.patch('fake_useragent.UserAgent', return_value=mock_ua)
    mocker.patch('pyscraper.requests.UserAgent', return_value=mock_ua)
    mocker.patch('pyscraper.hlsfile.UserAgent', return_value=mock_ua)

    yield


@pytest.fixture(autouse=True)
def mock_ffmpeg(request, mocker):
    """Automatically mock FFmpeg subprocess calls for HLS testing.

    Skip mocking for integration tests or when explicitly disabled.
    Tests can opt-out with @pytest.mark.no_mock_ffmpeg or @pytest.mark.integration
    """
    import os

    # Skip mocking for integration tests or when explicitly disabled
    if ('integration' in request.keywords or
        'no_mock' in request.keywords or
        'no_mock_ffmpeg' in request.keywords or
        os.getenv('INTEGRATION_TEST') == '1'):
        yield
        return

    # Create a function to handle subprocess.run calls based on command
    def mock_subprocess_run(cmd, *args, **kwargs):
        """Mock subprocess.run to handle both curl and ffmpeg calls."""
        mock_result = Mock()
        mock_result.returncode = 0
        mock_result.stderr = b''

        # Handle curl commands for WebPageCurl
        if cmd and len(cmd) > 0 and 'curl' in cmd[0]:
            # Extract URL from curl command
            url = cmd[1] if len(cmd) > 1 else ''

            # Return appropriate HTML based on URL
            if 'test2.html' in url:
                from pathlib import Path
                test2_path = Path(__file__).parent / 'testdata' / 'test2.html'
                mock_result.stdout = test2_path.read_bytes()
            elif 'test.html' in url or 'temeteke.github.io' in url:
                from pathlib import Path
                test_path = Path(__file__).parent / 'testdata' / 'test.html'
                mock_result.stdout = test_path.read_bytes()
            else:
                mock_result.stdout = b'<html><body>Mock HTML</body></html>'
        else:
            # For ffmpeg and other commands, return empty result
            mock_result.stdout = b''

        return mock_result

    # Check if ffmpy is being used (for HLS tests)
    try:
        # Mock subprocess.run for direct subprocess usage
        mock_run = mocker.patch('subprocess.run', side_effect=mock_subprocess_run)

        # Create a custom mock for ffmpy.FFmpeg that creates the output file when run() is called
        import ffmpy as ffmpy_module
        OriginalFFmpeg = ffmpy_module.FFmpeg

        class MockFFmpeg:
            """Mock FFmpeg that doesn't actually run ffmpeg."""
            def __init__(self, inputs=None, outputs=None, global_options=None, executable='ffmpeg'):
                # Don't call super().__init__() to avoid actual ffmpeg initialization
                # Just store the parameters we need
                self.inputs = inputs or {}
                self.outputs = outputs or {}
                self.global_options = global_options or []
                self.executable = executable
                self.cmd = f'mock ffmpeg: {inputs} -> {outputs}'
                self.process = None

            def run(self, *args, **kwargs):
                """Override run to create the output file without calling ffmpeg."""
                # Extract the output filename from stored outputs
                if self.outputs:
                    output_file = list(self.outputs.keys())[0]
                    # Create the output file with some dummy content
                    from pathlib import Path
                    output_path = Path(output_file)
                    output_path.parent.mkdir(parents=True, exist_ok=True)
                    output_path.write_bytes(b'mock ffmpeg output')
                return None

            def __repr__(self):
                return f"<MockFFmpeg: {self.cmd}>"

        mocker.patch('ffmpy.FFmpeg', MockFFmpeg)
        mocker.patch('pyscraper.hlsfile.ffmpy.FFmpeg', MockFFmpeg)

        yield mock_run
    except Exception:
        # If mocking fails, just yield
        yield


@pytest.fixture
def mock_m3u8_content():
    """Sample m3u8 playlist content for testing.

    Usage:
        content = mock_m3u8_content
    """
    return """#EXTM3U
#EXT-X-VERSION:3
#EXT-X-TARGETDURATION:8
#EXTINF:8.341667,
video000.ts
#EXTINF:8.341667,
video001.ts
#EXTINF:3.336667,
video002.ts
#EXT-X-ENDLIST
"""


# Override content fixture from test_webfile.py to use mocked data
@pytest.fixture(scope="session")
def content():
    """Mocked content fixture for WebFile tests."""
    # Return same content that would come from https://httpbin.org/range/1024
    return b'x' * 1024


# Auto-mock external HTTP requests for specific test scenarios
@pytest.fixture(autouse=True)
def mock_external_http(request, mocker, mock_http_response, mock_range_response, mock_html_response):
    """Automatically mock external HTTP requests for tests that would fail due to network issues.

    This fixture intercepts requests to httpbin.org and temeteke.github.io and returns mock responses.

    Skip mocking for integration tests or when explicitly disabled.
    """
    import os

    # Skip mocking for integration tests or when explicitly disabled
    if ('integration' in request.keywords or
        'no_mock' in request.keywords or
        'no_mock_http' in request.keywords or
        os.getenv('INTEGRATION_TEST') == '1'):
        yield
        return

    def mock_get(session_instance, url, **kwargs):
        # Get headers from kwargs and merge with session headers
        headers_dict = kwargs.get('headers', {}) or {}
        if hasattr(session_instance, 'headers'):
            # Merge session headers with request headers
            session_headers = dict(session_instance.headers) if hasattr(session_instance.headers, '__iter__') else {}
            headers_dict = {**session_headers, **headers_dict}

        # Mock httpbin.org/range/* requests
        if 'httpbin.org/range/' in url:
            # Extract size from URL
            size = int(url.split('/range/')[-1])
            content = b'x' * size

            # Check if Range header is present
            range_header = headers_dict.get('Range', '')

            if range_header:
                # Parse Range header: "bytes=start-end"
                range_val = range_header.replace('bytes=', '')
                if '-' in range_val:
                    parts = range_val.split('-')
                    start = int(parts[0]) if parts[0] else 0
                    end = int(parts[1]) if parts[1] else size - 1
                    return mock_range_response(start, end, size, content[start:end+1])
            else:
                # No Range header - return full content
                return mock_http_response(200, content, {
                    'Content-Length': str(size),
                    'Content-Type': 'application/octet-stream',
                    'Accept-Ranges': 'bytes'
                }, url)

        # Mock httpbin.org/bytes/* requests (without Range support)
        elif 'httpbin.org/bytes/' in url:
            size = int(url.split('/bytes/')[-1])
            content = b'x' * size

            # Check if Range header is present - should fail
            if headers_dict.get('Range'):
                # Simulate no Range support
                return mock_http_response(200, content, {
                    'Content-Length': str(size),
                    'Content-Type': 'application/octet-stream'
                }, url)

            return mock_http_response(200, content, {
                'Content-Length': str(size),
                'Content-Type': 'application/octet-stream'
            }, url)

        # Mock httpbin.org redirect
        elif 'httpbin.org/redirect-to' in url:
            target_url = url.split('url=')[-1] if 'url=' in url else 'https://httpbin.org/'
            from urllib.parse import unquote
            target_url = unquote(target_url)
            response = mock_http_response(200, b'redirected', url=target_url)
            response.history = [mock_http_response(302, b'', {'Location': target_url}, url)]
            return response

        # Mock httpbin.org/headers
        elif 'httpbin.org/headers' in url:
            import json
            response_data = {'headers': dict(headers_dict)}
            content = json.dumps(response_data).encode()
            return mock_http_response(200, content, {'Content-Type': 'application/json'}, url)

        # Mock httpbin.org/cookies
        elif 'httpbin.org/cookies' in url:
            import json
            cookies_dict = kwargs.get('cookies', {})
            response_data = {'cookies': dict(cookies_dict)}
            content = json.dumps(response_data).encode()
            response = mock_http_response(200, content, {'Content-Type': 'application/json'}, url)
            response.cookies = cookies_dict
            return response

        # Mock httpbin.org/user-agent
        elif 'httpbin.org/user-agent' in url:
            import json
            user_agent = headers_dict.get('User-Agent', '')
            response_data = {'user-agent': user_agent}
            content = json.dumps(response_data).encode()
            return mock_http_response(200, content, {'Content-Type': 'application/json'}, url)

        # Mock httpbin.org/status/*
        elif 'httpbin.org/status/' in url:
            status = int(url.split('/status/')[-1])
            return mock_http_response(status, b'', {}, url)

        # Mock httpbin.org/image/jpeg
        elif 'httpbin.org/image/jpeg' in url:
            # Return a small JPEG-like content
            content = b'\xff\xd8\xff\xe0' + b'x' * 100  # JPEG header + dummy data
            return mock_http_response(200, content, {'Content-Type': 'image/jpeg'}, url)

        # Mock temeteke.github.io test pages
        elif 'temeteke.github.io/pyscraper/tests/testdata/test.html' in url:
            html = """<!DOCTYPE html>
<html>
<head><title>Title</title></head>
<body>
<h1>Header</h1>
<p>paragraph 1<a>link 1</a></p>
<a id="link" href="test2.html">test2</a>
<iframe src="iframe.html"></iframe>
</body>
</html>"""
            return mock_html_response(html, url=url)

        elif 'temeteke.github.io/pyscraper/tests/testdata/test2.html' in url:
            html = """<!DOCTYPE html>
<html>
<head><title>Title 2</title></head>
<body>
<h1>Header 2</h1>
</body>
</html>"""
            return mock_html_response(html, url=url)

        # Mock GitHub raw content for HLS tests
        elif 'raw.githubusercontent.com/temeteke/pyscraper/master/tests/testdata/' in url:
            # Handle non-existent files (video_.m3u8 is intentionally missing)
            if 'video_.m3u8' in url:
                return mock_http_response(404, b'Not Found', {'Content-Type': 'text/plain'}, url)
            if 'video_with_map.m3u8' in url:
                content = """#EXTM3U
#EXT-X-VERSION:7
#EXT-X-TARGETDURATION:4
#EXT-X-MAP:URI="init.mp4?token=abc",BYTERANGE="720@0"
#EXTINF:4.0,
seg0.m4s
#EXTINF:4.0,
seg1.m4s
#EXT-X-ENDLIST
""".encode()
                return mock_http_response(200, content, {
                    'Content-Type': 'application/vnd.apple.mpegurl',
                    'Content-Length': str(len(content))
                }, url)
            if 'video_collide_seg.m3u8' in url:
                content = """#EXTM3U
#EXT-X-VERSION:7
#EXT-X-TARGETDURATION:4
#EXT-X-MAP:URI="a/init.mp4"
#EXTINF:4.0,
a/seg.ts
#EXT-X-MAP:URI="b/init.mp4"
#EXTINF:4.0,
b/seg.ts
#EXT-X-ENDLIST
""".encode()
                return mock_http_response(200, content, {
                    'Content-Type': 'application/vnd.apple.mpegurl',
                    'Content-Length': str(len(content))
                }, url)
            if 'video_collide_init_query.m3u8' in url:
                content = """#EXTM3U
#EXT-X-VERSION:7
#EXT-X-TARGETDURATION:4
#EXT-X-MAP:URI="init.mp4?token=a"
#EXTINF:4.0,
seg0.m4s
#EXT-X-MAP:URI="init.mp4?token=b"
#EXTINF:4.0,
seg1.m4s
#EXT-X-ENDLIST
""".encode()
                return mock_http_response(200, content, {
                    'Content-Type': 'application/vnd.apple.mpegurl',
                    'Content-Length': str(len(content))
                }, url)
            if url.endswith('.m3u8'):
                content = """#EXTM3U
#EXT-X-VERSION:3
#EXT-X-TARGETDURATION:8
#EXTINF:8.341667,
video000.ts
#EXTINF:8.341667,
video001.ts
#EXTINF:3.336667,
video002.ts
#EXT-X-ENDLIST
""".encode()
                return mock_http_response(200, content, {
                    'Content-Type': 'application/vnd.apple.mpegurl',
                    'Content-Length': str(len(content))
                }, url)
            elif url.endswith('.m4s'):
                full_content = b'x' * 20000
                range_header = headers_dict.get('Range', '')
                if range_header:
                    range_val = range_header.replace('bytes=', '')
                    if '-' in range_val:
                        parts = range_val.split('-')
                        start = int(parts[0]) if parts[0] else 0
                        end = int(parts[1]) if parts[1] else len(full_content) - 1
                        content = full_content[start:end+1]
                        return mock_range_response(start, end, len(full_content), content)
                else:
                    return mock_http_response(200, full_content, {
                        'Content-Type': 'application/octet-stream',
                        'Content-Length': str(len(full_content)),
                        'Accept-Ranges': 'bytes'
                    }, url)
            elif 'init.mp4' in url:
                full_content = b'i' * 200
                return mock_http_response(200, full_content, {
                    'Content-Type': 'application/octet-stream',
                    'Content-Length': str(len(full_content)),
                    'Accept-Ranges': 'bytes'
                }, url)
            elif url.endswith('.ts'):
                # Mock video segment - differentiate by filename to create continuous stream
                # video000.ts starts with TS header, others are plain data
                if 'video000.ts' in url:
                    full_content = b'\x47' + b'x' * 19999  # First segment: TS header + data (20000 bytes)
                else:
                    full_content = b'x' * 20000  # Other segments: plain data (20000 bytes)

                # Check if Range header is present
                range_header = headers_dict.get('Range', '')

                if range_header:
                    # Parse Range header: "bytes=start-end"
                    range_val = range_header.replace('bytes=', '')
                    if '-' in range_val:
                        parts = range_val.split('-')
                        start = int(parts[0]) if parts[0] else 0
                        end = int(parts[1]) if parts[1] else len(full_content) - 1
                        content = full_content[start:end+1]
                        return mock_range_response(start, end, len(full_content), content)
                else:
                    # No Range header - return full content
                    return mock_http_response(200, full_content, {
                        'Content-Type': 'video/mp2t',
                        'Content-Length': str(len(full_content)),
                        'Accept-Ranges': 'bytes'
                    }, url)

        # Handle DNS error test case
        if 'a.temeteke.com' in url:
            import requests
            raise requests.exceptions.ConnectionError(f"DNS lookup failed for {url}")

        # If we get here, it's an unmocked URL - let it fail or pass through
        # For testing, we'll return a generic response
        return mock_http_response(200, b'generic response', {}, url)

    # Import requests module to patch the Session class
    import requests as requests_module

    # Save original Session class
    OriginalSession = requests_module.Session

    def mock_session_factory(*args, **kwargs):
        """Create a real Session but with mocked get method."""
        session = OriginalSession(*args, **kwargs)
        original_get = session.get

        def mocked_get(url, **kw):
            # Call our mock_get with access to the session instance
            return mock_get(session, url, **kw)

        session.get = mocked_get
        return session

    # Patch Session constructor to return our wrapped sessions
    mocker.patch('requests.Session', side_effect=mock_session_factory)
    mocker.patch('pyscraper.requests.requests.Session', side_effect=mock_session_factory)

    # Also patch the module-level requests.get (doesn't have session context)
    def module_level_get(url, **kwargs):
        # For module-level get, create a temporary session-like object
        class TempSession:
            headers = kwargs.get('headers', {})
        return mock_get(TempSession(), url, **kwargs)

    mocker.patch('requests.get', side_effect=module_level_get)

    yield

    # Cleanup if needed
    # (mocker handles cleanup automatically)
