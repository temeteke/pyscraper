import unittest
from pathlib import Path

import requests
from pyscraper import WebFile, WebFileCached, WebFileError
from pyscraper.webfile import JoinedFile


class MixinTestWebFile:
    URL = 'https://httpbin.org/range/1024'

    @classmethod
    def setUpClass(cls):
        cls.content = requests.get(cls.URL).content
        cls.webfile = cls.webfile_class(cls.URL, filename='test.txt')

    @classmethod
    def tearDownClass(cls):
        cls.webfile.unlink()

    def test_eq01(self):
        assert self.webfile_class(self.URL) == self.webfile

    def test_filestem(self):
        assert self.webfile.filestem == 'test'

    def test_filesuffix(self):
        assert self.webfile.filesuffix == '.txt'

    def test_filename(self):
        assert self.webfile.filename == 'test.txt'

    def test_read_0(self):
        self.webfile.seek(0)
        assert self.webfile.read(128) == self.content[:128]

    def test_read_512(self):
        self.webfile.seek(512)
        assert self.webfile.read(128) == self.content[512:512 + 128]

    def test_read_576(self):
        self.webfile.seek(576)
        assert self.webfile.read(128) == self.content[576:576 + 128]

    def test_read_256(self):
        self.webfile.seek(256)
        assert self.webfile.read() == self.content[256:]

    def test_download_unlink(self):
        f = self.webfile.download()
        assert f.exists() is True

        self.webfile.unlink()
        assert f.exists() is False


class TestWebFile(MixinTestWebFile, unittest.TestCase):
    webfile_class = WebFile

    def test_exists(self):
        assert self.webfile_class('https://httpbin.org/status/200').exists() is True

    def test_not_exists(self):
        assert self.webfile_class('https://httpbin.org/status/404').exists() is False


class TestWebFileCached(MixinTestWebFile, unittest.TestCase):
    webfile_class = WebFileCached

    def test_read_0_2(self):
        self.webfile.seek(0)
        assert self.webfile.read(128) == self.content[:128]

    def test_read_512_2(self):
        self.webfile.seek(512)
        assert self.webfile.read(128) == self.content[512:512 + 128]

    def test_read_576_2(self):
        self.webfile.seek(576)
        assert self.webfile.read(128) == self.content[576:576 + 128]

    def test_read_256_2(self):
        self.webfile.seek(256)
        assert self.webfile.read() == self.content[256:]

    def test_read_join(self):
        self.webfile.seek(128)
        self.webfile.read(128)
        with self.webfile.filepath.open('rb') as f:
            actual = f.read()
        assert actual == self.content


class TestJoinedFile(unittest.TestCase):
    TEST_FILE = 'test_joined_file'

    def setUp(self):
        self.jf = JoinedFile(self.TEST_FILE)
        self.jf.seek(0)
        self.jf.write(b'abcdefg')
        self.jf.seek(10)
        self.jf.write(b'hijklmn')

    def tearDown(self):
        self.jf.unlink()

    def test_size01(self):
        assert self.jf.size == 7

    def test_size02(self):
        self.jf.seek(7)
        self.jf.write(b'xyz')
        assert self.jf.size == 17

    def test_read01(self):
        self.jf.seek(0)
        assert self.jf.read(7) == b'abcdefg'

    def test_read02(self):
        self.jf.seek(10)
        assert self.jf.read(7) == b'hijklmn'

    def test_read03(self):
        self.jf.seek(0)
        assert self.jf.read(20) == b'abcdefg'

    def test_read04(self):
        self.jf.seek(0)
        assert self.jf.read() == b'abcdefg'

    def test_read05(self):
        self.jf.seek(8)
        assert self.jf.read() == b''

    def test_write_read01(self):
        self.jf.seek(0)
        self.jf.write(b'xyz')
        self.jf.seek(0)
        assert self.jf.read() == b'xyzdefg'

    def test_write_read02(self):
        self.jf.seek(7)
        self.jf.write(b'xyz')
        self.jf.seek(0)
        assert self.jf.read() == b'abcdefgxyzhijklmn'

    def test_writ_reade03(self):
        self.jf.seek(7)
        self.jf.write(b'xyzxyz')
        self.jf.seek(0)
        assert self.jf.read() == b'abcdefgxyzxyzklmn'

    def test_write_read04(self):
        self.jf.seek(3)
        self.jf.write(b'xyz')
        self.jf.seek(0)
        assert self.jf.read() == b'abcxyzg'

    def test_write_read05(self):
        self.jf.seek(13)
        self.jf.write(b'xyz')
        self.jf.seek(10)
        assert self.jf.read() == b'hijxyzn'

    def test_write_partfile01(self):
        self.jf.seek(7)
        self.jf.write(b'xyz')
        with Path('{}.part0'.format(self.TEST_FILE)).open('rb') as f:
            actual = f.read()
        assert actual == b'abcdefgxyz'

    def test_join_partfile01(self):
        self.jf.join()
        with Path(self.TEST_FILE).open('rb') as f:
            actual = f.read()
        assert actual == b'abcdefg'

    def test_join_read01(self):
        self.jf.join()
        self.jf.seek(0)
        assert self.jf.read() == b'abcdefg'

    def test_join_write_read01(self):
        self.jf.join()
        self.jf.seek(0)
        self.jf.write(b'xyz')
        self.jf.seek(0)
        assert self.jf.read() == b'xyzdefg'

    def test_write_join_partfile01(self):
        self.jf.seek(7)
        self.jf.write(b'xyz')
        self.jf.join()
        with Path(self.TEST_FILE).open('rb') as f:
            actual = f.read()
        assert actual == b'abcdefgxyzhijklmn'

    def test_write_join_partfile02(self):
        self.jf.seek(7)
        self.jf.write(b'xyzxyz')
        self.jf.join()
        with Path(self.TEST_FILE).open('rb') as f:
            actual = f.read()
        assert actual == b'abcdefgxyzxyzklmn'

    def test_write_join_read01(self):
        self.jf.seek(7)
        self.jf.write(b'xyz')
        self.jf.join()
        self.jf.seek(0)
        assert self.jf.read() == b'abcdefgxyzhijklmn'

    def test_write_join_read02(self):
        self.jf.seek(7)
        self.jf.write(b'xyzxyz')
        self.jf.join()
        self.jf.seek(0)
        assert self.jf.read() == b'abcdefgxyzxyzklmn'


class TestWebFileError(unittest.TestCase):
    def test_dnserror(self):
        with self.assertRaises(WebFileError):
            WebFile('http://a.temeteke.com').read()
