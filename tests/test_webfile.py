from pathlib import Path

import pytest
import requests
from pyscraper import WebFile, WebFileCached, WebFileError
from pyscraper.webfile import JoinedFile


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
        assert webfile.read(128) == content[:128]

    def test_read_512(self, webfile, content):
        webfile.seek(512)
        assert webfile.read(128) == content[512 : 512 + 128]

    def test_read_576(self, webfile, content):
        webfile.seek(576)
        assert webfile.read(128) == content[576 : 576 + 128]

    def test_read_256(self, webfile, content):
        webfile.seek(256)
        assert webfile.read() == content[256:]

    def test_seek_read_0(self, webfile, content):
        webfile.seek(128)
        webfile.seek(0)
        assert webfile.read(128) == content[:128]

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
            WebFile("http://a.temeteke.com").read()

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


class TestWebFileCached(MixinTestWebFile):
    @pytest.fixture
    def webfile(self, url, filename):
        wfc = WebFileCached(url, filename=filename)
        yield wfc
        wfc.unlink()

    def test_read_0_2(self, webfile, content):
        webfile.seek(0)
        assert webfile.read(128) == content[:128]

    def test_read_512_2(self, webfile, content):
        webfile.seek(512)
        assert webfile.read(128) == content[512 : 512 + 128]

    def test_read_576_2(self, webfile, content):
        webfile.seek(576)
        assert webfile.read(128) == content[576 : 576 + 128]

    def test_read_256_2(self, webfile, content):
        webfile.seek(256)
        assert webfile.read() == content[256:]

    def test_read_join(self, webfile, content):
        webfile.seek(0)
        webfile.read(128)
        webfile.seek(256)
        webfile.read()
        webfile.seek(128)
        webfile.read(128)
        with webfile.filepath.open("rb") as f:
            actual = f.read()
        assert actual == content


class TestJoinedFile:
    @pytest.fixture
    def joinedfile(self, filename):
        jf = JoinedFile(filename)
        jf.seek(0)
        jf.write(b"abcdefg")
        jf.seek(10)
        jf.write(b"hijklmn")
        yield jf
        jf.unlink()

    def test_size01(self, joinedfile):
        assert joinedfile.size == 7

    def test_size02(self, joinedfile):
        joinedfile.seek(7)
        joinedfile.write(b"xyz")
        assert joinedfile.size == 17

    def test_read01(self, joinedfile):
        joinedfile.seek(0)
        assert joinedfile.read(7) == b"abcdefg"

    def test_read02(self, joinedfile):
        joinedfile.seek(10)
        assert joinedfile.read(7) == b"hijklmn"

    def test_read03(self, joinedfile):
        joinedfile.seek(0)
        assert joinedfile.read(20) == b"abcdefg"

    def test_read04(self, joinedfile):
        joinedfile.seek(0)
        assert joinedfile.read() == b"abcdefg"

    def test_read05(self, joinedfile):
        joinedfile.seek(8)
        assert joinedfile.read() == b""

    def test_write_read01(self, joinedfile):
        joinedfile.seek(0)
        joinedfile.write(b"xyz")
        joinedfile.seek(0)
        assert joinedfile.read() == b"xyzdefg"

    def test_write_read02(self, joinedfile):
        joinedfile.seek(7)
        joinedfile.write(b"xyz")
        joinedfile.seek(0)
        assert joinedfile.read() == b"abcdefgxyzhijklmn"

    def test_writ_reade03(self, joinedfile):
        joinedfile.seek(7)
        joinedfile.write(b"xyzxyz")
        joinedfile.seek(0)
        assert joinedfile.read() == b"abcdefgxyzxyzklmn"

    def test_write_read04(self, joinedfile):
        joinedfile.seek(3)
        joinedfile.write(b"xyz")
        joinedfile.seek(0)
        assert joinedfile.read() == b"abcxyzg"

    def test_write_read05(self, joinedfile):
        joinedfile.seek(13)
        joinedfile.write(b"xyz")
        joinedfile.seek(10)
        assert joinedfile.read() == b"hijxyzn"

    def test_write_partfile01(self, joinedfile, filename):
        joinedfile.seek(7)
        joinedfile.write(b"xyz")
        with Path(f"{filename}.part0").open("rb") as f:
            actual = f.read()
        assert actual == b"abcdefgxyz"

    def test_join_partfile01(self, joinedfile, filename):
        joinedfile.join()
        with Path(filename).open("rb") as f:
            actual = f.read()
        assert actual == b"abcdefg"

    def test_join_read01(self, joinedfile):
        joinedfile.join()
        joinedfile.seek(0)
        assert joinedfile.read() == b"abcdefg"

    def test_join_write_read01(self, joinedfile):
        joinedfile.join()
        joinedfile.seek(0)
        joinedfile.write(b"xyz")
        joinedfile.seek(0)
        assert joinedfile.read() == b"xyzdefg"

    def test_write_join_partfile01(self, joinedfile, filename):
        joinedfile.seek(7)
        joinedfile.write(b"xyz")
        joinedfile.join()
        with Path(filename).open("rb") as f:
            actual = f.read()
        assert actual == b"abcdefgxyzhijklmn"

    def test_write_join_partfile02(self, joinedfile, filename):
        joinedfile.seek(7)
        joinedfile.write(b"xyzxyz")
        joinedfile.join()
        with Path(filename).open("rb") as f:
            actual = f.read()
        assert actual == b"abcdefgxyzxyzklmn"

    def test_write_join_read01(self, joinedfile):
        joinedfile.seek(7)
        joinedfile.write(b"xyz")
        joinedfile.join()
        joinedfile.seek(0)
        assert joinedfile.read() == b"abcdefgxyzhijklmn"

    def test_write_join_read02(self, joinedfile):
        joinedfile.seek(7)
        joinedfile.write(b"xyzxyz")
        joinedfile.join()
        joinedfile.seek(0)
        assert joinedfile.read() == b"abcdefgxyzxyzklmn"
