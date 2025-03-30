from pathlib import Path

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
    return requests.get(url).content


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

    def test_filesuffix_close(self):
        assert WebFile("https://httpbin.org/image/jpeg").filesuffix == ""

    def test_filesuffix_open(self):
        with WebFile("https://httpbin.org/image/jpeg") as wf:
            assert wf.filesuffix == ".jpg"

    def test_user_agent_close(self):
        assert not WebFile("https://httpbin.org/user-agent").user_agent

    def test_user_agent_open(self):
        with WebFile("https://httpbin.org/user-agent") as wf:
            assert "requests" not in wf.user_agent

    def test_session(self):
        session = requests.Session()
        session.headers["test"] = "test"
        assert WebFile("https://httpbin.org/headers", session=session).headers["test"] == "test"
