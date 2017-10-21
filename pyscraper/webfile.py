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

        if session:
            self.session = session
        else:
            self.session = requests.Session()

        self.session.headers.update(HEADERS)
        self.session.headers.update(headers)

        for k, v in cookies.items():
            self.session.cookies.set(k, v)

    @mproperty
    @debug
    def filename(self):
        if hasattr(self, '_filename'):
            return self._filename

        logger.debug("Request Headers: " + str(self.session.headers))
        r = self.session.head(self.url)
        logger.debug("Response Headers: " + str(r.headers))

        if 'Content-Disposition' in r.headers:
            m = re.search('filename="(.+)"', r.headers['Content-Disposition'])
            if m:
                return m.group(1)

        if 'Location' in r.headers:
            return urlparse(r.headers['Location']).path.split('/').pop()

        return urlparse(self.url).path.split('/').pop()

    @mproperty
    @debug
    def filepath(self):
        return Path(self.directory, self.filename)

    @mproperty
    @debug
    def filepath_tmp(self):
        return Path(str(self.filepath) + '.part')

    @retry((requests.exceptions.HTTPError, requests.exceptions.ConnectionError, requests.exceptions.ChunkedEncodingError, WebFileSizeError), tries=5, delay=1, backoff=2, jitter=(1, 5), logger=logger)
    def download(self, directory='.', filename=None):
        self.directory = Path(directory)
        if not self.directory.exists():
            self.directory.mkdir()

        if filename:
            self._filename = re.sub(r'[/:\s\*]', '_', filename)

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
            r = self.session.get(self.url, stream=True)
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
