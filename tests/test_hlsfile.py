import unittest
from pyscraper.hlsfile import HlsFileFfmpeg, HlsFileRequests
import logging

logger = logging.getLogger('pyscraper')
logger.setLevel(logging.DEBUG)

fh = logging.FileHandler(filename='test_pyscraper.log')
fh.setFormatter(logging.Formatter("%(asctime)s %(name)s %(levelname)8s %(message)s"))
logger.addHandler(fh)

URL = 'https://raw.githubusercontent.com/temeteke/pyscraper/master/tests/testdata/video.m3u8'


class TestHlsFileMixin():
    def test_download_unlink(self):
        f = self.hf.download()
        self.assertTrue(f.exists())
        self.assertTrue(self.hf.exists())

        self.hf.unlink()
        self.assertFalse(f.exists())
        self.assertFalse(self.hf.exists())


class TestHlsFileFfmpeg(TestHlsFileMixin, unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.hf = HlsFileFfmpeg(URL)


class TestHlsFileRequests(TestHlsFileMixin, unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.hf = HlsFileRequests(URL)
