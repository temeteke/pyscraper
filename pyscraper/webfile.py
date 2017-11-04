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

class WebFileRequestError(Exception):
    pass

class WebFileSizeError(Exception):
    pass

class WebFile():
    def __init__(self, url, session=None, headers={}, cookies={}, directory='.', filename=None, filestem=None, filesuffix=None):
        self.offset = 0

        self.url = url

        if session:
            self.session = session
        else:
            self.session = requests.Session()

        self.session.headers.update(HEADERS)
        self.session.headers.update(headers)

        for k, v in cookies.items():
            self.session.cookies.set(k, v)

        self.directory = Path(directory)
        if not self.directory.exists():
            self.directory.mkdir()

        self._filename = filename
        self._filestem = filestem
        self._filesuffix = filesuffix

    @mproperty
    @retry(requests.exceptions.ReadTimeout, tries=10, delay=1, backoff=2, jitter=(1, 5), logger=logger)
    def _response(self):
        logger.debug("Request Headers: " + str(self.session.headers))
        r = self.session.head(self.url, allow_redirects=True, timeout=10)
        logger.debug("Response Headers: " + str(r.headers))
        return r

    @mproperty
    @debug
    def _filename_auto(self):
        if 'Content-Disposition' in self._response.headers:
            m = re.search('filename="(.+)"', self._response.headers['Content-Disposition'])
            if m:
                return m.group(1)

        return urlparse(self._response.url).path.split('/').pop()

    @mproperty
    @debug
    def filestem(self):
        if self._filestem:
            return re.sub(r'[/:\s\*\.\?]', '_', self._filestem)[:128]
        elif self._filename:
            return Path(self._filename).stem
        else:
            return Path(self._filename_auto).stem

    @mproperty
    @debug
    def filesuffix(self):
        if self._filesuffix:
            return self._filesuffix
        elif self._filename:
            return Path(self._filename).suffix
        elif self._response.headers['Content-Type'] == 'video/mp4':
            return '.mp4'
        else:
            return Path(self._filename_auto).suffix

    @mproperty
    @debug
    def filename(self):
        return self.filestem + self.filesuffix

    @mproperty
    @debug
    def filepath(self):
        return Path(self.directory, self.filename)

    @mproperty
    @debug
    def filepath_tmp(self):
        return Path(str(self.filepath) + '.part0')

    @mproperty
    @debug
    def size(self):
        return int(self._response.headers['Content-Length'])

    def seek(self, offset):
        self.offset = offset

    @retry((requests.exceptions.HTTPError, requests.exceptions.ConnectionError, requests.exceptions.ChunkedEncodingError, requests.exceptions.ReadTimeout, WebFileSizeError), tries=10, delay=1, backoff=2, jitter=(1, 5), logger=logger)
    def iter_content(self, chunk_size):
        if self.filepath_tmp.exists():
            with self.filepath_tmp.open('rb') as f:
                f.seek(self.offset)
                while True:
                    chunk = f.read(chunk_size)
                    self.offset += len(chunk)
                    if not chunk:
                        break
                    yield chunk
            self.session.headers['Range'] = 'bytes={}-'.format(self.offset)
        else:
            if 'Range' in self.session.headers:
                del self.session.headers['Range']

        try:
            logger.debug("Request Headers: " + str(self.session.headers))
            r = self.session.get(self.url, stream=True, timeout=10)
            logger.debug("Response Headers: " + str(r.headers))
            r.raise_for_status()
        except requests.exceptions.HTTPError as e:
            if 400 <= e.response.status_code < 500:
                if e.response.status_code == 416 and self.filepath_tmp.exists():
                    logger.warning("Removing downloaded file")
                    self.filepath_tmp.unlink()
                    self.offset = 0
                    raise
                else:
                    raise WebFileRequestError(e)
            raise

        with self.filepath_tmp.open('ab') as f:
            for chunk in r.iter_content(chunk_size):
                self.offset += len(chunk)
                f.write(chunk)
                yield chunk

        if self.filepath_tmp.stat().st_size == self.size:
            self.filepath_tmp.rename(self.filepath)
            return
        else:
            raise WebFileSizeError("The size of the downloaded file is wrong.")

    def download(self):
        logger.info("Downloading {}".format(self.url))

        if self.filepath.exists():
            logger.warning("{} is already downloaded.".format(self.filepath))
            return

        logger.info("Filepath is {}".format(self.filepath))

        if self.filepath_tmp.exists():
            self.seek(self.filepath_tmp.stat().st_size)

        with tqdm(total=self.size, initial=self.offset, unit='B', unit_scale=True, dynamic_ncols=True, ascii=True) as pbar:
            for block in self.iter_content(1024):
                pbar.update(len(block))
