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
        self.position = 0

    def read(self, size):
        pass

    def seek(self, position):
        self.position = position
        return position

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

class WebFileRequestError(Exception):
    pass

class WebFileSizeError(Exception):
    pass

class WebFile(FileIOBase):
    def __init__(self, url, session=None, headers={}, cookies={}, directory='.', filename=None, filestem=None, filesuffix=None):
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

        self.response = self._get_response()

        super().__init__()

    def _get_response(self, headers={}):
        headers_all = self.session.headers.copy()
        headers_all.update(headers)

        logger.debug("Request Headers: " + str(headers_all))
        r = self.session.get(self.url, headers=headers, stream=True, timeout=10)
        logger.debug("Response Headers: " + str(r.headers))

        r.raise_for_status()
        return r

    @mproperty
    @debug
    def size(self):
        return int(self.response.headers['Content-Length'])

    @mproperty
    @debug
    def _filename_auto(self):
        if 'Content-Disposition' in self.response.headers:
            m = re.search('filename="(.+)"', self.response.headers['Content-Disposition'])
            if m:
                return m.group(1)

        return urlparse(self.response.url).path.split('/').pop()

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
        elif self.response.headers['Content-Type'] == 'video/mp4':
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

    def seek(self, offset):
        if offset == self.position:
            return self.position

        if offset:
            headers = {'Range': 'bytes={}-'.format(offset)}
        else:
            headers = {}

        self.response = self._get_response(headers)

        return super().seek(offset)

    def read(self, size=None):
        chunk = self.response.raw.read(size)
        self.position += len(chunk)
        return chunk

    @retry((requests.exceptions.HTTPError, requests.exceptions.ConnectionError, requests.exceptions.ChunkedEncodingError, requests.exceptions.ReadTimeout), tries=10, delay=1, backoff=2, jitter=(1, 5), logger=logger)
    def download(self):
        logger.info("Downloading {}".format(self.url))

        if self.filepath.exists():
            logger.warning("{} is already downloaded.".format(self.filepath))
            return

        logger.info("Filepath is {}".format(self.filepath))

        filepath_tmp = Path(str(self.filepath) + '.part')
        if filepath_tmp.exists():
            filepath_tmp_size = filepath_tmp.stat().st_size
        else:
            filepath_tmp_size = 0

        try:
            with tqdm(total=self.size, initial=filepath_tmp_size, unit='B', unit_scale=True, dynamic_ncols=True, ascii=True) as pbar:
                with filepath_tmp.open('ab') as f:
                    for chunk in self.read_in_chunks(1024, filepath_tmp_size):
                        f.write(chunk)
                        pbar.update(len(chunk))
        except requests.exceptions.HTTPError as e:
            logger.warning(e)
            if 400 <= e.response.status_code < 500:
                if e.response.status_code == 416 and filepath_tmp.exists():
                    logger.warning("Removing downloaded file")
                    filepath_tmp.unlink()
                    raise
                else:
                    raise WebFileRequestError(e)
            raise

        logger.debug('Comparing file size: {} {}'.format(filepath_tmp.stat().st_size, self.size))
        if filepath_tmp.stat().st_size == self.size:
            filepath_tmp.rename(self.filepath)

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
                with filepath.open('rb') as f:
                    f.seek(start_in_partfile)
                    data += f.read(stop_in_partfile-start_in_partfile)

        self.seek(self.tell() + len(data))
        return data

class WebFileCached(WebFile):
    def __init__(self, url, session=None, headers={}, cookies={}, directory='.', filename=None, filestem=None, filesuffix=None):
        self.joinedfiles = JoinedFiles(sorted(self.directory.glob('{}.part*'.format(self.filepath.name)), key=lambda x:int(re.findall(r'\d+$', x.suffix)[0])))

        super().__init__(url=url, session=session, headers=headers, cookies=cookies, filename=filename, filestem=filestem, filesuffix=filesuffix)

    def read(self, size=None):
        data = b''

        self.joinedfiles.seek(self.tell())
        chunk = self.joinedfiles.read(size)
        data += chunk
        self.seek(self.tell() + len(chunk))

        if not size or size > len(data):
            chunk = super().read(size-len(data))
            data += chunk
            self.position += len(chunk)

            partfile = Path('{}.part{}'.format(self.filepath, self.tell()))
            logger.debug('Downloading to {}'.format(partfile))

            with partfile.open('ab') as f:
                f.write(data)

            if self.tell() == self.size and reduce(lambda x,y: x+y, [partfile.stat().st_size for partfile in self.joinedfiles.files]) == self.size:
                self.joinedfiles.seek(0)
                with self.filepath.open('ab') as f:
                    for chunk in self.joinedfiles.read_in_chunks(1024):
                        f.write(chunk)

        return data

    def download(self):
        logger.info("Downloading {}".format(self.url))

        if self.filepath.exists():
            logger.warning("{} is already downloaded.".format(self.filepath))
            return

        logger.info("Filepath is {}".format(self.filepath))

        with tqdm(total=self.size, initial=downloaded_file_size, unit='B', unit_scale=True, dynamic_ncols=True, ascii=True) as pbar:
            for chunk in self.read_in_chunks(1024):
                pbar.update(len(chunk))
