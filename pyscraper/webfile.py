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

class WebFileDownloadError(Exception):
    pass

class WebFile():
    def __init__(self, url, session=None, headers={}, directory='.', filename=None):
        self.url = url

        if session:
            self.session = session
        else:
            self.session = requests.Session()

        self.session.headers.update(HEADERS)
        self.session.headers.update(headers)

        self.directory = Path(directory)
        if not self.directory.exists():
            self.directory.mkdir()

        if filename:
            self._filename = re.sub(r'[/:\s\*]', '_', filename)

    @mproperty
    @debug
    def filename(self):
        if hasattr(self, '_filename'):
            return self._filename

        logger.debug("Request Headers: " + str(self.session.headers))
        r = self.session.head(self.url)
        logger.debug("Response Headers: " + str(r.headers))

        if 'Content-Disposition' in r.headers:
            return re.findall('filename="(.+)"', r.headers['Content-Disposition'])[0]
        elif 'Location' in r.headers:
            return urlparse(r.headers['Location']).path.split('/').pop()
        else:
            return urlparse(self.url).path.split('/').pop()

    @mproperty
    @debug
    def filepath(self):
        return Path(self.directory, self.filename)

    @mproperty
    @debug
    def filepath_tmp(self):
        return Path(str(self.filepath) + '.part')

    @retry(WebFileDownloadError, tries=5, delay=2, jitter=(1, 5), logger=logger)
    def download(self):
        logger.info("Downloading {}".format(self.url))

        if self.filepath.exists():
            logger.warning("{} is already downloaded.".format(self.filepath))
            return

        if self.filepath_tmp.exists():
            downloaded_size = self.filepath_tmp.stat().st_size
            self.session.headers['Range'] = 'bytes={}-'.format(downloaded_size)
        else:
            downloaded_size = 0

        try:
            logger.debug("Request Headers: " + str(self.session.headers))
            r = self.session.get(self.url, stream=True)
            logger.debug("Response Headers: " + str(r.headers))
            r.raise_for_status()
        except requests.exceptions.HTTPError as e:
            logger.warning(e)
            if e.response.status_code == 416:
                if self.filepath_tmp.exists():
                    logger.debug("Removing downloaded file.")
                    self.filepath_tmp.unlink()
            raise WebFileDownloadError
        except (requests.exceptions.ConnectionError, requests.exceptions.ChunkedEncodingError) as e:
            logger.warning(e)
            raise WebFileDownloadError

        total_size = int(r.headers['Content-Length'])
        if 'Content-Range' in r.headers:
            total_size = int(r.headers['Content-Range'].split('/')[-1])
        if total_size == 0:
            raise WebFileDownloadError

        with tqdm(total=total_size, initial=downloaded_size, unit='B', unit_scale=True, dynamic_ncols=True, ascii=True) as pbar:
            with self.filepath_tmp.open('ab') as f:
                for block in r.iter_content(1024):
                    f.write(block)
                    pbar.update(len(block))

        if self.filepath_tmp.stat().st_size == total_size:
            self.filepath_tmp.rename(self.filepath)
            return
        else:
            logger.warning("The size of the downloaded file is wrong.")
            raise WebFileDownloadError