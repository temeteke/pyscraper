import logging
from memoize import mproperty
from retry import retry
from tqdm import tqdm
from urllib.parse import urlparse
from pathlib import Path
import re
import requests
from .utils import debug, HEADERS
from functools import reduce

logger = logging.getLogger(__name__)

class FileIOBase():
    def __init__(self):
        self.seek(0)

    def read(self, size):
        pass

    def seek(self, position):
        self.position = position

    def tell(self):
        return self.position

    def read_in_chunks(self, chunk_size, start=0):
        self.seek(start)
        while True:
            chunk = self.read(chunk_size)
            if chunk:
                yield chunk
            else:
                break

class JoinedFiles(FileIOBase):
    def __init__(self, filepaths):
        self.filepaths = filepaths
        super().__init__()

    def read(self, size=None):
        data = b''
        for filepath in self.filepaths:
            start = int(re.findall(r'\d+$', filepath.suffix)[0])
            stop = start + filepath.stat().st_size

            if self.tell() in range(start, stop):
                start_in_partfile = self.tell() - start
                stop_in_partfile = start_in_partfile + size
                #logger.debug('Reading {} from {} to {}'.format(filepath, start_in_partfile, stop_in_partfile))
                with filepath.open('rb') as f:
                    f.seek(start_in_partfile)
                    data += f.read(stop_in_partfile-start_in_partfile)

        self.seek(self.tell() + len(data))
        return data

class WebFileRequestError(Exception):
    pass

class WebFileSizeError(Exception):
    pass

class WebFile(FileIOBase):
    def __init__(self, url, session=None, headers={}, cookies={}, directory='.', filename=None, filestem=None, filesuffix=None, caching=False):
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

        self.caching = caching

        self.joinedfiles = JoinedFiles(sorted(self.directory.glob('{}.part*'.format(self.filepath.name)), key=lambda x:int(re.findall(r'\d+$', x.suffix)[0])))

        super().__init__()

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

    @mproperty
    def _res(self):
        try:
            logger.debug("Request Headers: " + str(self.session.headers))
            r = self.session.get(self.url, stream=True, timeout=10)
            logger.debug("Response Headers: " + str(r.headers))
            r.raise_for_status()
            return r
        except requests.exceptions.HTTPError as e:
            if 400 <= e.response.status_code < 500:
                if e.response.status_code == 416 and self.joinedfiles.filepaths:
                    logger.warning("Removing downloaded file")
                    for filepath in self.joinedfiles.filepaths:
                        filepath.unlink()
                    self.seek(0)
                    raise
                else:
                    raise WebFileRequestError(e)
            raise

    def read(self, size=None):
        if self.caching:
            data = self.joinedfiles.read(size)
            if size and data:
                self.seek(self.tell() + len(data))
                return data

        if self.tell():
            self.session.headers['Range'] = 'bytes={}-'.format(self.tell())
        else:
            if 'Range' in self.session.headers:
                del self.session.headers['Range']

        partfile = Path('{}.part{}'.format(self.filepath, self.tell()))
        logger.debug('Downloading to {}'.format(partfile))
        if self.caching:
            with partfile.open('ab') as f:
                for chunk in self._res.iter_content(1024):
                    self.seek(self.tell() + len(chunk))
                    f.write(chunk)
                    data += chunk
        else:
            for chunk in self._res.iter_content(1024):
                self.seek(self.tell() + len(chunk))
                data += chunk

        if self.caching:
            if self.tell() == self.size and reduce(lambda x,y: x+y, [partfile.stat().st_size for partfile in self.joinedfiles.files]) == self.size:
                self.joinedfiles.seek(0)
                with self.filepath.open('wb') as f:
                    for chunk in self.joinedfiles.read_in_chunks(1024):
                        f.write(chunk)

        return data

    @retry((requests.exceptions.HTTPError, requests.exceptions.ConnectionError, requests.exceptions.ChunkedEncodingError, requests.exceptions.ReadTimeout, WebFileSizeError), tries=10, delay=1, backoff=2, jitter=(1, 5), logger=logger)
    def download(self):
        logger.info("Downloading {}".format(self.url))

        _caching = self.caching
        self.caching = True

        if self.filepath.exists():
            logger.warning("{} is already downloaded.".format(self.filepath))
            return

        logger.info("Filepath is {}".format(self.filepath))

        with tqdm(total=self.size, unit='B', unit_scale=True, dynamic_ncols=True, ascii=True) as pbar:
            for chunk in self.read_in_chunks(1024):
                pbar.update(len(chunk))

        self.caching = _caching
