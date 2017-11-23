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
        self.logger = logging.getLogger('.'.join([__name__, self.__class__.__name__]))
        self.position = 0

    def read(self, size):
        pass

    def seek(self, position):
        self.logger.debug('Seek to {}'.format(position))
        self.position = position
        return position

    def tell(self):
        return self.position

    def read_in_chunks(self, chunk_size, start=0, stop=None):
        self.seek(start)
        while True:
            if stop and stop-self.tell() < chunk_size:
                chunk_size = stop-self.tell()
                self.logger.debug('Read last chunk(size:{})'.format(chunk_size))

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
        super().__init__()

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

    def _get_response(self, headers={}):
        headers_all = self.session.headers.copy()
        headers_all.update(headers)

        self.logger.debug("Request Headers: " + str(headers_all))
        r = self.session.get(self.url, headers=headers, stream=True, timeout=10)
        self.logger.debug("Response Headers: " + str(r.headers))

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
        if offset >= self.size:
            raise WebFileSeekError('{} is out of range 0-{}'.format(offset, self.size-1))

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
        self.logger.info("Downloading {}".format(self.url))

        if self.filepath.exists():
            self.logger.warning("{} is already downloaded.".format(self.filepath))
            return

        self.logger.info("Filepath is {}".format(self.filepath))

        filepath_tmp = Path(str(self.filepath) + '.part')
        if filepath_tmp.exists():
            downloaded_file_size = filepath_tmp.stat().st_size
        else:
            downloaded_file_size = 0

        try:
            with tqdm(total=self.size, initial=downloaded_file_size, unit='B', unit_scale=True, dynamic_ncols=True, ascii=True) as pbar:
                with filepath_tmp.open('ab') as f:
                    for chunk in self.read_in_chunks(1024, downloaded_file_size):
                        f.write(chunk)
                        pbar.update(len(chunk))
        except requests.exceptions.HTTPError as e:
            self.logger.warning(e)
            if 400 <= e.response.status_code < 500:
                if e.response.status_code == 416 and filepath_tmp.exists():
                    self.logger.warning("Removing downloaded file")
                    filepath_tmp.unlink()
                    raise
                else:
                    raise WebFileRequestError(e)
            raise

        self.logger.debug('Comparing file size: {} {}'.format(filepath_tmp.stat().st_size, self.size))
        if filepath_tmp.stat().st_size == self.size:
            filepath_tmp.rename(self.filepath)

class WebFileSeekError(Exception):
    pass

class JoinedFiles(FileIOBase):
    def __init__(self, filepath):
        super().__init__()
        self.filepath = filepath

    @property
    def filepaths(self):
        return sorted(self.filepath.parent.glob('{}.part*'.format(self.filepath.name)), key=lambda x:int(re.findall(r'\d+$', x.suffix)[0]))

    @property
    def size(self):
        position = self.tell()
        self.seek(0)
        size = len(self.read())
        self.seek(position)
        return size

    def read(self, size=-1):
        data = b''

        for filepath in self.filepaths:
            start = int(re.findall(r'\d+$', filepath.suffix)[0])
            stop = start + filepath.stat().st_size

            if self.tell() in range(start, stop):
                start_in_partfile = self.tell() - start
                stop_in_partfile = stop if not size or size < 0 else start_in_partfile + size
                self.logger.debug('Read from downloaded file {} from {} to {}'.format(filepath, start_in_partfile, stop_in_partfile))
                with filepath.open('rb') as f:
                    f.seek(start_in_partfile)
                    read_data = f.read(stop_in_partfile-start_in_partfile)

                self.seek(self.tell() + len(read_data))
                data += read_data

        return data

    def write(self, b):
        for filepath in self.filepaths:
            start = int(re.findall(r'\d+$', filepath.suffix)[0])
            stop = start + filepath.stat().st_size

            if self.tell() in range(start, stop+1):
                self.logger.debug('Saving data to {}'.format(filepath))
                with filepath.open('ab') as f:
                    f.write(b[self.tell()-stop:])
                self.position += len(b)
                return len(b)

        partfile = Path('{}.part{}'.format(self.filepath, self.tell()))
        self.logger.debug('Saving data to {}'.format(partfile))
        with partfile.open('ab') as f:
            f.write(b)
        self.position += len(b)
        return len(b)

    def join(self):
        self.logger.debug('Joining files')
        self.seek(0)

        with self.filepath.open('wb') as f:
            for chunk in self.read_in_chunks(1024):
                f.write(chunk)

        for filepath in self.filepaths:
            self.logger.debug('Removing {}'.format(filepath))
            filepath.unlink()

class WebFileCached(WebFile):
    def seek(self, offset):
        if self.filepath.exists():
            self.logger.debug("Seek using cached file '{}'".format(self.filepath))
            FileIOBase.seek(self, offset)
        else:
            super().seek(offset)

    def read(self, size=-1):
        if self.filepath.exists():
            self.logger.debug("Reading from cached file '{}'".format(self.filepath))
            with self.filepath.open('rb') as f:
                f.seek(self.tell())
                return f.read(size)

        joined_files = JoinedFiles(self.filepath)

        joined_files.seek(self.tell())
        old_data = joined_files.read(size)
        new_data = b''

        try:
            self.seek(joined_files.tell())
        except WebFileSeekError as e:
            return old_data

        if not size or size < 0 or size > len(old_data):
            if not size or size < 0:
                new_data = super().read()
                joined_files.write(new_data)
            elif size > len(old_data):
                new_data = super().read(size-len(old_data))
                joined_files.write(new_data)

        if joined_files.size == self.size:
            joined_files.join()

        return old_data + new_data

    def download(self):
        self.logger.info("Downloading {}".format(self.url))

        if self.filepath.exists():
            self.logger.warning("{} is already downloaded.".format(self.filepath))
            return

        self.logger.info("Filepath is {}".format(self.filepath))

        with tqdm(total=self.size, initial=downloaded_file_size, unit='B', unit_scale=True, dynamic_ncols=True, ascii=True) as pbar:
            for chunk in self.read_in_chunks(1024):
                pbar.update(len(chunk))
