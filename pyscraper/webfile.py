import logging
from memoize import mproperty
from retry import retry
from tqdm import tqdm
from urllib.parse import urlparse
from pathlib import Path
import re
import requests
from .utils import debug, HEADERS

logger = logging.getLogger(__name__)

class WebFileSizeError(Exception):
    pass

class WebFile():
    def __init__(self, url, session=None, headers={}, cookies={}):
        self.url = url
        self._filename = None
        self._filestem = None
        self._filesuffix = None

        if session:
            self.session = session
        else:
            self.session = requests.Session()

        self.session.headers.update(HEADERS)
        self.session.headers.update(headers)

        for k, v in cookies.items():
            self.session.cookies.set(k, v)

    def _get_normal_path(self, string):
        return re.sub(r'[/:\s\*]', '_', string)[:128]

    @mproperty
    @debug
    @retry(requests.exceptions.ReadTimeout, tries=5, delay=1, backoff=2, jitter=(1, 5), logger=logger)
    def headers(self):
        logger.debug("Request Headers: " + str(self.session.headers))
        r = self.session.head(self.url, timeout=10)
        logger.debug("Response Headers: " + str(r.headers))
        return r.headers

    @mproperty
    @debug
    def filestem(self):
        if self._filestem:
            return self._get_normal_path(self._filestem)
        elif self._filename:
            return Path(self._filename).stem
        else:
            return Path(self.filename).stem

    @mproperty
    @debug
    def filesuffix(self):
        if self._filesuffix:
            return self._filesuffix
        elif self._filename:
            return Path(self._filename).suffix
        else:
            if self.headers['Content-Type'] == 'video/mp4':
                return 'mp4'
            else:
                return Path(self.filename).suffix

    @mproperty
    @debug
    def filename(self):
        if self._filename or self._filestem:
            return '{}.{}'.format(self.filestem, self.filesuffix)

        if 'Content-Disposition' in self.headers:
            m = re.search('filename="(.+)"', self.headers['Content-Disposition'])
            if m:
                return m.group(1)

        if 'Location' in self.headers:
            return urlparse(self.headers['Location']).path.split('/').pop()

        return urlparse(self.url).path.split('/').pop()

    @mproperty
    @debug
    def filepath(self):
        return Path(self.directory, self.filename)

    @mproperty
    @debug
    def filepath_tmp(self):
        return Path(str(self.filepath) + '.part')

    @retry((requests.exceptions.HTTPError, requests.exceptions.ConnectionError, requests.exceptions.ChunkedEncodingError, requests.exceptions.ReadTimeout, WebFileSizeError), tries=5, delay=1, backoff=2, jitter=(1, 5), logger=logger)
    def download(self, directory='.', filename=None, filestem=None, filesuffix=None):
        self.directory = Path(directory)
        if not self.directory.exists():
            self.directory.mkdir()

        self._filename = filename
        self._filestem = filestem
        self._filesuffix = filesuffix

        logger.info("Downloading {}".format(self.url))

        if self.filepath.exists():
            logger.warning("{} is already downloaded.".format(self.filepath))
            return

        if self.filepath_tmp.exists():
            downloaded_size = self.filepath_tmp.stat().st_size
            self.session.headers['Range'] = 'bytes={}-'.format(downloaded_size)
        else:
            downloaded_size = 0
            if 'Range' in self.session.headers:
                del self.session.headers['Range']

        try:
            logger.debug("Request Headers: " + str(self.session.headers))
            r = self.session.get(self.url, stream=True, timeout=10)
            logger.debug("Response Headers: " + str(r.headers))
            r.raise_for_status()
        except requests.exceptions.HTTPError as e:
            if e.response.status_code == 416:
                if self.filepath_tmp.exists():
                    logger.debug("Removing downloaded file.")
                    self.filepath_tmp.unlink()
            raise

        total_size = int(r.headers['Content-Length'])
        if 'Content-Range' in r.headers:
            total_size = int(r.headers['Content-Range'].split('/')[-1])
        if total_size == 0:
            raise WebFileSizeError("File size is zero.")

        with tqdm(total=total_size, initial=downloaded_size, unit='B', unit_scale=True, dynamic_ncols=True, ascii=True) as pbar:
            with self.filepath_tmp.open('ab') as f:
                for block in r.iter_content(1024):
                    f.write(block)
                    pbar.update(len(block))

        if self.filepath_tmp.stat().st_size == total_size:
            self.filepath_tmp.rename(self.filepath)
            return
        else:
            raise WebFileSizeError("The size of the downloaded file is wrong.")
