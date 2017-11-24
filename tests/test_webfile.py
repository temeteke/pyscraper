import unittest
from pyscraper import WebFile, WebFileCached
from pyscraper.webfile import JoinedFile, JoinedFileReadError
import requests
from pathlib import Path

import logging

logger = logging.getLogger('pyscraper')
logger.setLevel(logging.DEBUG)

fh = logging.FileHandler(filename='test_pyscraper.log')
fh.setFormatter(logging.Formatter("%(asctime)s %(name)s %(levelname)8s %(message)s"))
logger.addHandler(fh)

class TestWebFile(unittest.TestCase):
    URL = 'https://httpbin.org/range/1024'

    @classmethod
    def _get_webfile(cls, url):
        return WebFile(url)

    @classmethod
    def setUpClass(cls):
        logger.debug('setUpClass')
        cls.content = requests.get(cls.URL).content
        cls.wf = cls._get_webfile(cls.URL)

    def test_read01(self):
        logger.debug('test_read01')
        self.wf.seek(0)
        self.assertEqual(self.content[:128], self.wf.read(128))

    def test_read02(self):
        logger.debug('test_read02')
        self.wf.seek(512)
        self.assertEqual(self.content[512:640], self.wf.read(128))

    def test_read03(self):
        logger.debug('test_read03')
        self.wf.seek(576)
        self.assertEqual(self.content[576:704], self.wf.read(128))

    def test_read04(self):
        logger.debug('test_read04')
        self.wf.seek(256)
        self.assertEqual(self.content[256:], self.wf.read())

class TestWebFileCached(TestWebFile):
    @classmethod
    def _get_webfile(cls, url):
        return WebFileCached(url)

class TestWebFileCached2(TestWebFileCached):
    def test_read05(self):
        logger.debug('test_read05')
        self.wf.seek(128)
        self.assertEqual(self.content[128:256], self.wf.read(128))

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
        self.assertEqual(7, self.jf.size)

    def test_size02(self):
        self.jf.seek(7)
        self.jf.write(b'xyz')
        self.assertEqual(17, self.jf.size)

    def test_read01(self):
        self.jf.seek(0)
        self.assertEqual(b'abcdefg', self.jf.read(7))

    def test_read02(self):
        self.jf.seek(10)
        self.assertEqual(b'hijklmn', self.jf.read(7))

    def test_read03(self):
        self.jf.seek(0)
        self.assertEqual(b'abcdefg', self.jf.read(20))

    def test_read04(self):
        self.jf.seek(0)
        self.assertEqual(b'abcdefg', self.jf.read())

    def test_read05(self):
        self.jf.seek(8)
        self.assertEqual(b'', self.jf.read())

    def test_write01(self):
        self.jf.seek(7)
        self.jf.write(b'xyz')
        self.jf.seek(0)
        self.assertEqual(b'abcdefgxyzhijklmn', self.jf.read())

    def test_write02(self):
        self.jf.seek(7)
        self.jf.write(b'xyzxyz')
        self.jf.seek(0)
        self.assertEqual(b'abcdefgxyzxyzklmn', self.jf.read())

    def test_write03(self):
        self.jf.seek(7)
        self.jf.write(b'xyz')
        with Path('{}.part0'.format(self.TEST_FILE)).open('rb') as f:
            actual = f.read()
        self.assertEqual(b'abcdefgxyz', actual)

    def test_join01(self):
        self.jf.join()
        with Path(self.TEST_FILE).open('rb') as f:
            actual = f.read()
        self.assertEqual(b'abcdefg', actual)

    def test_join02(self):
        self.jf.seek(7)
        self.jf.write(b'xyz')
        self.jf.join()
        with Path(self.TEST_FILE).open('rb') as f:
            actual = f.read()
        self.assertEqual(b'abcdefgxyzhijklmn', actual)

    def test_join03(self):
        self.jf.join()
        self.jf.seek(0)
        self.assertEqual(b'abcdefg', self.jf.read())

    def test_join04(self):
        self.jf.seek(7)
        self.jf.write(b'xyz')
        self.jf.join()
        self.jf.seek(0)
        self.assertEqual(b'abcdefgxyzhijklmn', self.jf.read())
