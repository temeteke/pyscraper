from pathlib import Path

import pytest
import requests
from pyscraper.webfile import WebFile, WebFileError, WebFileSeekError


@pytest.fixture(scope="session")
def url():
    return "https://httpbin.org/range/1024"


@pytest.fixture(scope="session")
def filename():
    return "test.txt"


@pytest.fixture(scope="session")
def content(url):
    return requests.get(url).content


class MixinTestWebFile:
    def test_url_01(self, webfile, url):
        assert not hasattr(webfile, "cached_url")
        assert webfile.url == url
        assert webfile.cached_url == url

    def test_url_02(self, webfile):
        webfile.exists()
        webfile.url = "https://httpbin.org/range/2048"
        assert not hasattr(webfile, "cached_url")
        assert webfile.url == "https://httpbin.org/range/2048"
        assert webfile.cached_url == "https://httpbin.org/range/2048"

    def test_url_03(self, webfile):
        webfile.exists()
        webfile.url = "https://httpbin.org/status/404"
        assert not hasattr(webfile, "cached_url")
        assert webfile.url == "https://httpbin.org/status/404"
        assert webfile.cached_url == "https://httpbin.org/status/404"

    def test_directory(self, webfile):
        assert webfile.directory == Path(".")

    def test_filestem(self, webfile):
        assert webfile.filestem == "test"

    def test_filesuffix(self, webfile):
        assert webfile.filesuffix == ".txt"

    def test_filename(self, webfile):
        assert webfile.filename == "test.txt"

    def test_read_0(self, webfile, content):
        webfile.seek(0)
        with webfile.open() as wf:
            assert wf.read(128) == content[:128]

    def test_read_512(self, webfile, content):
        webfile.seek(512)
        with webfile.open() as wf:
            assert wf.read(128) == content[512 : 512 + 128]

    def test_read_576(self, webfile, content):
        webfile.seek(576)
        with webfile.open() as wf:
            assert wf.read(128) == content[576 : 576 + 128]

    def test_read_256(self, webfile, content):
        webfile.seek(256)
        with webfile.open() as wf:
            assert wf.read() == content[256:]

    def test_seek_read_0(self, webfile, content):
        webfile.seek(128)
        webfile.seek(0)
        with webfile.open() as wf:
            assert wf.read(128) == content[:128]

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

    def test_seek_range_not_supported(self):
        webfile = WebFile("https://httpbin.org/bytes/1024")
        with pytest.raises(WebFileSeekError):
            webfile.seek(512)

    def test_seek_large_offset(self, webfile):
        with pytest.raises(WebFileSeekError):
            webfile.seek(2048)

    def test_seek_negative_offset(self, webfile):
        with pytest.raises(WebFileSeekError):
            webfile.seek(-1)


class TestWebFile(MixinTestWebFile):
    @pytest.fixture
    def webfile(self, url, filename):
        return WebFile(url, filename=filename)

    def test_eq01(self, webfile, url):
        assert webfile == WebFile(url)

    def test_exists(self):
        assert WebFile("https://httpbin.org/status/200").exists() is True

    def test_not_exists(self):
        assert WebFile("https://httpbin.org/status/404").exists() is False

    def test_dnserror(self):
        with pytest.raises(WebFileError):
            WebFile("http://a.temeteke.com").open()

    def test_url_redirect(self):
        assert (
            WebFile("https://httpbin.org/redirect-to?url=https%3A%2F%2Fhttpbin.org").url
            == "https://httpbin.org"
        )

    def test_headers(self):
        assert (
            WebFile("https://httpbin.org/headers", headers={"test": "test"}).headers["test"]
            == "test"
        )

    def test_cookies(self):
        assert (
            WebFile("https://httpbin.org/cookies", cookies={"test": "test"}).cookies["test"]
            == "test"
        )

    def test_filesuffix_jpg(self, webfile):
        return WebFile("https://httpbin.org/image/jpeg").filesuffix == ".jpg"
