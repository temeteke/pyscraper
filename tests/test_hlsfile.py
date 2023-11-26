import logging

import pytest

from pyscraper import WebFile

from pyscraper.hlsfile import HlsFileFfmpeg, HlsFileRequests

logger = logging.getLogger("pyscraper")
logger.setLevel(logging.DEBUG)

fh = logging.FileHandler(filename="test_pyscraper.log")
fh.setFormatter(logging.Formatter("%(asctime)s %(name)s %(levelname)8s %(message)s"))
logger.addHandler(fh)


@pytest.fixture(scope="session")
def url():
    return "https://raw.githubusercontent.com/temeteke/pyscraper/master/tests/testdata/video.m3u8"


@pytest.fixture(scope="session")
def content():
    web_files = [
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
    content = b""
    for web_file in web_files:
        content += web_file.read()
    return content


class MixinTestHlsFile:
    def test_m3u8_url(self, hls_file, url):
        assert hls_file.m3u8_url == url

    def test_m3u8_content(self, hls_file, url):
        assert (
            hls_file.m3u8_content.strip()
            == """
#EXTM3U
#EXT-X-VERSION:3
#EXT-X-TARGETDURATION:8
#EXT-X-MEDIA-SEQUENCE:0
#EXTINF:8.341667,
https://raw.githubusercontent.com/temeteke/pyscraper/master/tests/testdata/video000.ts
#EXTINF:8.341667,
https://raw.githubusercontent.com/temeteke/pyscraper/master/tests/testdata/video001.ts
#EXTINF:3.336667,
https://raw.githubusercontent.com/temeteke/pyscraper/master/tests/testdata/video002.ts
#EXT-X-ENDLIST
""".strip()
        )

    def test_web_files(self, hls_file):
        assert hls_file.web_files == [
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

    def test_download_unlink(self, hls_file):
        f = hls_file.download()
        assert f.exists()

        hls_file.unlink()
        assert not f.exists()


class TestHlsFileFfmpeg(MixinTestHlsFile):
    @pytest.fixture
    def hls_file(self, url):
        return HlsFileFfmpeg(url)


class TestHlsFileRequests(MixinTestHlsFile):
    @pytest.fixture
    def hls_file(self, url):
        return HlsFileRequests(url)
