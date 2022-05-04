import logging
import unittest
from pathlib import Path

import requests
from pyscraper import WebFile, WebFileCached, WebFileError
from pyscraper.webfile import JoinedFile

logger = logging.getLogger('pyscraper')
logger.setLevel(logging.DEBUG)

fh = logging.FileHandler(filename='test_pyscraper.log')
fh.setFormatter(logging.Formatter("%(asctime)s %(name)s %(levelname)8s %(message)s"))
logger.addHandler(fh)


class TestWebFileMixin():
    URL = 'https://httpbin.org/range/1024'

    def test_filestem(self):
        logger.debug('test_filestem')
        self.assertEqual('test', self.wf.filestem)

    def test_filesuffix(self):
        logger.debug('test_filesuffix')
        self.assertEqual('.txt', self.wf.filesuffix)

    def test_filename(self):
        logger.debug('test_filename')
        self.assertEqual('test.txt', self.wf.filename)

    def test_read_0(self):
        logger.debug('test_read_0')
        self.wf.seek(0)
        self.assertEqual(self.content[:128], self.wf.read(128))

    def test_read_512(self):
        logger.debug('test_read_512')
        self.wf.seek(512)
        self.assertEqual(self.content[512:512 + 128], self.wf.read(128))

    def test_read_576(self):
        logger.debug('test_read_576')
        self.wf.seek(576)
        self.assertEqual(self.content[576:576 + 128], self.wf.read(128))

    def test_read_256(self):
        logger.debug('test_read_256')
        self.wf.seek(256)
        self.assertEqual(self.content[256:], self.wf.read())

    def test_download_unlink(self):
        logger.debug('test_download')
        f = self.wf.download()
        self.assertTrue(f.exists())
        self.assertTrue(self.wf.exists())

        self.wf.unlink()
        self.assertFalse(f.exists())
        self.assertFalse(self.wf.exists())


class TestWebFile(TestWebFileMixin, unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        logger.debug('setUpClass')
        cls.content = requests.get(cls.URL).content
        cls.wf = WebFile(cls.URL, filename='test.txt')

    @classmethod
    def tearDownClass(cls):
        cls.wf.unlink()


class TestWebFileCached(TestWebFileMixin, unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        logger.debug('setUpClass')
        cls.content = requests.get(cls.URL).content
        cls.wf = WebFileCached(cls.URL, filename='test.txt')

    @classmethod
    def tearDownClass(cls):
        cls.wf.unlink()

    def test_read_0_2(self):
        logger.debug('test_read_0_2')
        self.wf.seek(0)
        self.assertEqual(self.content[:128], self.wf.read(128))

    def test_read_512_2(self):
        logger.debug('test_read_512_2')
        self.wf.seek(512)
        self.assertEqual(self.content[512:512 + 128], self.wf.read(128))

    def test_read_576_2(self):
        logger.debug('test_read_576_2')
        self.wf.seek(576)
        self.assertEqual(self.content[576:576 + 128], self.wf.read(128))

    def test_read_256_2(self):
        logger.debug('test_read_256_2')
        self.wf.seek(256)
        self.assertEqual(self.content[256:], self.wf.read())

    def test_read_join(self):
        logger.debug('test_read_join')
        self.wf.seek(128)
        self.wf.read(128)
        with self.wf.filepath.open('rb') as f:
            actual = f.read()
        self.assertEqual(self.content, actual)


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

    def test_write_read01(self):
        self.jf.seek(0)
        self.jf.write(b'xyz')
        self.jf.seek(0)
        self.assertEqual(b'xyzdefg', self.jf.read())

    def test_write_read02(self):
        self.jf.seek(7)
        self.jf.write(b'xyz')
        self.jf.seek(0)
        self.assertEqual(b'abcdefgxyzhijklmn', self.jf.read())

    def test_writ_reade03(self):
        self.jf.seek(7)
        self.jf.write(b'xyzxyz')
        self.jf.seek(0)
        self.assertEqual(b'abcdefgxyzxyzklmn', self.jf.read())

    def test_write_read04(self):
        self.jf.seek(3)
        self.jf.write(b'xyz')
        self.jf.seek(0)
        self.assertEqual(b'abcxyzg', self.jf.read())

    def test_write_read05(self):
        self.jf.seek(13)
        self.jf.write(b'xyz')
        self.jf.seek(10)
        self.assertEqual(b'hijxyzn', self.jf.read())

    def test_write_partfile01(self):
        self.jf.seek(7)
        self.jf.write(b'xyz')
        with Path('{}.part0'.format(self.TEST_FILE)).open('rb') as f:
            actual = f.read()
        self.assertEqual(b'abcdefgxyz', actual)

    def test_join_partfile01(self):
        self.jf.join()
        with Path(self.TEST_FILE).open('rb') as f:
            actual = f.read()
        self.assertEqual(b'abcdefg', actual)

    def test_join_read01(self):
        self.jf.join()
        self.jf.seek(0)
        self.assertEqual(b'abcdefg', self.jf.read())

    def test_join_write_read01(self):
        self.jf.join()
        self.jf.seek(0)
        self.jf.write(b'xyz')
        self.jf.seek(0)
        self.assertEqual(b'xyzdefg', self.jf.read())

    def test_write_join_partfile01(self):
        self.jf.seek(7)
        self.jf.write(b'xyz')
        self.jf.join()
        with Path(self.TEST_FILE).open('rb') as f:
            actual = f.read()
        self.assertEqual(b'abcdefgxyzhijklmn', actual)

    def test_write_join_partfile02(self):
        self.jf.seek(7)
        self.jf.write(b'xyzxyz')
        self.jf.join()
        with Path(self.TEST_FILE).open('rb') as f:
            actual = f.read()
        self.assertEqual(b'abcdefgxyzxyzklmn', actual)

    def test_write_join_read01(self):
        self.jf.seek(7)
        self.jf.write(b'xyz')
        self.jf.join()
        self.jf.seek(0)
        self.assertEqual(b'abcdefgxyzhijklmn', self.jf.read())

    def test_write_join_read02(self):
        self.jf.seek(7)
        self.jf.write(b'xyzxyz')
        self.jf.join()
        self.jf.seek(0)
        self.assertEqual(b'abcdefgxyzxyzklmn', self.jf.read())


class TestWebFileError(unittest.TestCase):
    def test_dnserror(self):
        with self.assertRaises(WebFileError):
            WebFile('http://a.temeteke.com')
