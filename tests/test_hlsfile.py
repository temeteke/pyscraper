import unittest
from pyscraper.hlsfile import HlsFileFfmpeg, HlsFileRequests
from pathlib import Path
import threading
from multiprocessing import Process, Pool, TimeoutError

import logging

from time import sleep

logger = logging.getLogger('pyscraper')
logger.setLevel(logging.DEBUG)

fh = logging.FileHandler(filename='test_pyscraper.log')
fh.setFormatter(logging.Formatter("%(asctime)s %(name)s %(levelname)8s %(message)s"))
logger.addHandler(fh)

URL = 'https://raw.githubusercontent.com/temeteke/pyscraper/master/tests/testdata/video.m3u8'

class TestHlsFileFfmpeg(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.hf = HlsFileFfmpeg(URL)

    def test_download_unlink(self):
        self.hf.download()
        self.assertTrue(self.hf.exists())

        self.hf.unlink()
        self.assertFalse(self.hf.exists())


class TestHlsFileRequests(TestHlsFileFfmpeg):
    @classmethod
    def setUpClass(cls):
        cls.hf = HlsFileRequests(URL)
