import logging
from pathlib import Path

import pytest
import requests

from pyscraper.webfile import WebFile
from pyscraper.hlsfile import HlsFile

logger = logging.getLogger("pyscraper")
logger.setLevel(logging.DEBUG)

fh = logging.FileHandler(filename="test_pyscraper.log")
fh.setFormatter(logging.Formatter("%(asctime)s %(name)s %(levelname)8s %(message)s"))
logger.addHandler(fh)


@pytest.fixture(scope="session")
def url():
    return "https://raw.githubusercontent.com/temeteke/pyscraper/master/tests/testdata/video.m3u8"


@pytest.fixture(scope="session")
def url_absolute():
    return "https://raw.githubusercontent.com/temeteke/pyscraper/master/tests/testdata/video_absolute_url.m3u8"


@pytest.fixture(scope="session")
def url_error():
    return "https://raw.githubusercontent.com/temeteke/pyscraper/master/tests/testdata/video_.m3u8"


@pytest.fixture(scope="session")
def web_files():
    return [
        WebFile(
            "https://raw.githubusercontent.com/temeteke/pyscraper/master/tests/testdata/video000.ts"
        ),
        WebFile(
            "https://raw.githubusercontent.com/temeteke/pyscraper/master/tests/testdata/video001.ts"
        ),
        WebFile(
            "https://raw.githubusercontent.com/temeteke/pyscraper/master/tests/testdata/video002.ts"
        ),
    ]


@pytest.fixture(scope="session")
def content(web_files):
    content = b""
    for web_file in web_files:
        with web_file.open() as wf:
            content += wf.read()
    return content


class TestHlsFile:
    @pytest.fixture
    def hls_file(self, url):
        return HlsFile(url)

    @pytest.fixture
    def hls_file_absolute_url(self, url_absolute):
        return HlsFile(url_absolute)

    @pytest.fixture
    def hls_file_error(self, url_error):
        return HlsFile(url_error)

    def test_url_01(self, hls_file, url):
        assert hls_file.url == url

    def test_url_02(self, hls_file, url_error):
        hls_file.web_files[0]
        hls_file.url = url_error
        assert hls_file.url == url_error

    def test_directory(self, hls_file):
        assert hls_file.directory == Path(".")

    def test_filestem(self, hls_file):
        assert hls_file.filestem == "video"

    def test_filesuffix(self, hls_file):
        assert hls_file.filesuffix == ".mp4"

    def test_filename(self, hls_file):
        assert hls_file.filename == "video.mp4"

    def test_m3u8_content_url(self, hls_file):
        assert (
            hls_file.m3u8_content_url.strip()
            == """
#EXTM3U
#EXT-X-VERSION:3
#EXT-X-TARGETDURATION:8
#EXTINF:8.341667,
https://raw.githubusercontent.com/temeteke/pyscraper/master/tests/testdata/video000.ts
#EXTINF:8.341667,
https://raw.githubusercontent.com/temeteke/pyscraper/master/tests/testdata/video001.ts
#EXTINF:3.336667,
https://raw.githubusercontent.com/temeteke/pyscraper/master/tests/testdata/video002.ts
#EXT-X-ENDLIST
""".strip()
        )

    def test_m3u8_content_filename(self, hls_file):
        assert (
            hls_file.m3u8_content_filename.strip()
            == """
#EXTM3U
#EXT-X-VERSION:3
#EXT-X-TARGETDURATION:8
#EXTINF:8.341667,
video000.ts
#EXTINF:8.341667,
video001.ts
#EXTINF:3.336667,
video002.ts
#EXT-X-ENDLIST
""".strip()
        )

    def test_web_files_01(self, hls_file):
        expected = [
            WebFile(
                "https://raw.githubusercontent.com/temeteke/pyscraper/master/tests/testdata/video000.ts"
            ),
            WebFile(
                "https://raw.githubusercontent.com/temeteke/pyscraper/master/tests/testdata/video001.ts"
            ),
            WebFile(
                "https://raw.githubusercontent.com/temeteke/pyscraper/master/tests/testdata/video002.ts"
            ),
        ]
        assert list(hls_file.web_files) == expected
        assert list(hls_file.web_files) == expected

    def test_web_files_02(self, hls_file):
        assert (
            WebFile(
                "https://raw.githubusercontent.com/temeteke/pyscraper/master/tests/testdata/video000.ts"
            )
            in hls_file.web_files
        )
        assert (
            WebFile(
                "https://raw.githubusercontent.com/temeteke/pyscraper/master/tests/testdata/video001.ts"
            )
            in hls_file.web_files
        )
        assert (
            WebFile(
                "https://raw.githubusercontent.com/temeteke/pyscraper/master/tests/testdata/video002.ts"
            )
            in hls_file.web_files
        )

    def test_read_all(self, hls_file, content):
        assert hls_file.read() == content

    def test_read_0(self, hls_file, content):
        hls_file.seek(0)
        assert hls_file.read(128) == content[:128]

    def test_read_512(self, hls_file, content):
        hls_file.seek(512)
        assert hls_file.read(128) == content[512 : 512 + 128]

    def test_read_57152(self, hls_file, content):
        hls_file.seek(57152)
        assert hls_file.read(128) == content[57152 : 57152 + 128]

    def test_read_60000(self, hls_file, content):
        hls_file.seek(60000)
        assert hls_file.read(128) == content[60000 : 60000 + 128]

    def test_read_256(self, hls_file, content):
        hls_file.seek(256)
        assert hls_file.read() == content[256:]

    def test_read_files(self, hls_file, web_files):
        for hls_file_content, web_file in zip(hls_file.read_files(), web_files):
            with web_file.open() as wf:
                assert hls_file_content == wf.read()

    def test_exists_true(self, hls_file):
        assert hls_file.exists()

    def test_exists_false(self, hls_file_error):
        assert not hls_file_error.exists()

    def test_download_unlink(self, hls_file):
        f = hls_file.download()
        assert f.exists()

        hls_file.unlink()
        assert not f.exists()

    def test_download_unlink_absolute_url(self, hls_file_absolute_url):
        f = hls_file_absolute_url.download()
        assert f.exists()

        hls_file_absolute_url.unlink()
        assert not f.exists()

    def test_download_unlink_filename(self, hls_file):
        f = hls_file.download(filename="video_file.mp4")
        assert f.exists()
        assert f.name == "video_file.mp4"

        hls_file.unlink()
        assert not f.exists()

    def test_download_progress_callback(self, hls_file):
        progresses = []

        def cb(current, total):
            progresses.append((current, total))

        hls_file.download(progress_callback=cb)
        # The last callback should indicate completion
        assert progresses[-1][0] == progresses[-1][1]

        hls_file.unlink()

    def test_session(self):
        session = requests.Session()
        session.headers["test"] = "test"
        assert HlsFile("https://httpbin.org/headers", session=session).headers["test"] == "test"

    def test_clear_cache(self, hls_file):
        """Test that clear_cache removes all cached properties"""
        # Access cached properties to ensure they are cached
        _ = hls_file.m3u8_obj
        _ = hls_file.m3u8_content
        _ = hls_file.m3u8_content_url
        _ = hls_file.m3u8_content_filename
        _ = hls_file.web_files

        # Verify properties are cached (accessing __dict__ directly)
        assert "m3u8_obj" in hls_file.__dict__
        assert "m3u8_content" in hls_file.__dict__
        assert "m3u8_content_url" in hls_file.__dict__
        assert "m3u8_content_filename" in hls_file.__dict__
        assert "web_files" in hls_file.__dict__

        # Clear cache
        hls_file.clear_cache()

        # Verify all cached properties are removed
        assert "m3u8_obj" not in hls_file.__dict__
        assert "m3u8_content" not in hls_file.__dict__
        assert "m3u8_content_url" not in hls_file.__dict__
        assert "m3u8_content_filename" not in hls_file.__dict__
        assert "web_files" not in hls_file.__dict__

    def test_url_change_clears_cache(self, hls_file, url_error):
        """Test that changing URL automatically clears cached properties"""
        # Access cached properties
        original_obj = hls_file.m3u8_obj
        _ = hls_file.web_files

        # Verify properties are cached
        assert "m3u8_obj" in hls_file.__dict__
        assert "web_files" in hls_file.__dict__

        # Change URL (should trigger clear_cache)
        hls_file.url = url_error

        # Verify cache was cleared
        assert "m3u8_obj" not in hls_file.__dict__
        assert "web_files" not in hls_file.__dict__

    def test_cached_property_recomputation(self, hls_file):
        """Test that cached properties are recomputed after clearing cache"""
        # Access and cache a property
        first_obj = hls_file.m3u8_obj
        first_id = id(first_obj)

        # Clear cache
        hls_file.clear_cache()

        # Access again - should create new object
        second_obj = hls_file.m3u8_obj
        second_id = id(second_obj)

        # Objects should have same content but different identity (new instance)
        assert first_id != second_id
        assert first_obj.is_variant == second_obj.is_variant
