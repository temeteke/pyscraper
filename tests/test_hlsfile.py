import logging
import unittest

from pyscraper.hlsfile import HlsFileFfmpeg, HlsFileRequests

logger = logging.getLogger("pyscraper")
logger.setLevel(logging.DEBUG)

fh = logging.FileHandler(filename="test_pyscraper.log")
fh.setFormatter(logging.Formatter("%(asctime)s %(name)s %(levelname)8s %(message)s"))
logger.addHandler(fh)

URL = "https://raw.githubusercontent.com/temeteke/pyscraper/master/tests/testdata/video.m3u8"


class MixinTestHlsFile:
    def test_download_unlink(self):
        f = self.hf.download()
        self.assertTrue(f.exists())

        self.hf.unlink()
        self.assertFalse(f.exists())


class TestHlsFileFfmpeg(MixinTestHlsFile, unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.hf = HlsFileFfmpeg(URL)


class TestHlsFileRequests(MixinTestHlsFile, unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.hf = HlsFileRequests(URL)
