import logging
from memoize import mproperty
from retry import retry
from tqdm import tqdm
from urllib.parse import urlparse
from pathlib import Path
import re
import requests
import urllib3
from .utils import debug, HEADERS
from functools import reduce
import unicodedata
from http.cookiejar import MozillaCookieJar

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
    def __init__(self, url, session=None, headers={}, cookies={}, cookies_file=None, directory='.', filename=None, filestem=None, filesuffix=None):
        super().__init__()

        self.url = url

        if session:
            self.session = session
        else:
            self.session = requests.Session()

        self.session.headers.update(HEADERS)
        self.session.headers.update(headers)

        if cookies_file:
            cookies = MozillaCookieJar(cookies_file)
            cookies.load()
            self.session.cookies = cookies
        else:
            for k, v in cookies.items():
                self.session.cookies.set(k, v)

        self.directory = Path(re.sub(r'[:|\s\*\?\\"]', '_', directory))
        if not self.directory.exists():
            self.directory.mkdir(parents=True)

        self._filename = filename
        self._filestem = filestem
        self._filesuffix = filesuffix

        self.response = self._get_response()
        self.response.raw.decode_content = True

    @retry((requests.exceptions.HTTPError, requests.exceptions.Timeout), tries=10, delay=1, backoff=2, jitter=(1, 5), logger=logger)
    def _get_response(self, headers={}):
        headers_all = self.session.headers.copy()
        headers_all.update(headers)

        r = self.session.get(self.url, headers=headers, stream=True, timeout=10)
        self.logger.debug("Request Headers: " + str(r.request.headers))
        self.logger.debug("Response Headers: " + str(r.headers))

        try:
            r.raise_for_status()
        except requests.exceptions.HTTPError as e:
            if 400 <= e.response.status_code < 500:
                raise WebFileRequestError(e)
            else:
                raise

        return r

    @mproperty
    @debug
    def size(self):
        try:
            return int(self.response.headers['Content-Length'])
        except KeyError:
            return None

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
            filestem = unicodedata.normalize('NFC', self._filestem)
            while len(filestem.encode()) > 192:
                filestem = filestem[:-1]
            return re.sub(r'[/:|\s\*\.\?\\"]', '_', filestem)
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
        elif 'Content-Type' in self.response.headers and self.response.headers['Content-Type'] == 'video/mp4':
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

    def seek(self, offset, force=False):
        if offset >= self.size:
            raise WebFileSeekError('{} is out of range 0-{}'.format(offset, self.size-1))

        if not force and offset == self.position:
            return self.position

        if offset:
            headers = {'Range': 'bytes={}-'.format(offset)}
        else:
            headers = {}

        self.response = self._get_response(headers)

        return super().seek(offset)

    def reload(self):
        self.logger.debug("Reloading")
        self.seek(self.tell(), force=True)

    @retry((requests.exceptions.HTTPError, requests.exceptions.ConnectionError, requests.exceptions.Timeout, requests.exceptions.ChunkedEncodingError, urllib3.exceptions.ReadTimeoutError, urllib3.exceptions.ProtocolError), tries=10, delay=1, backoff=2, jitter=(1, 5), logger=logger)
    def read(self, size=None):
        """Read and return contents."""
        chunk = self.response.raw.read(size)
        self.position += len(chunk)
        return chunk

    @retry(WebFileRequestError, tries=10, delay=1, backoff=2, jitter=(1, 5), logger=logger)
    def download_and_check_size(self):
        """Download file and check downloaded file size"""
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
        except WebFileRequestError as e:
            self.logger.warning(e)
            if e.response.status_code == 416 and filepath_tmp.exists():
                self.logger.warning("Removing downloaded file")
                filepath_tmp.unlink()
            raise

        if not 'gzip' in self.response.headers.get('Content-Encoding', ''):
            self.logger.debug("Comparing file size {} {}".format(filepath_tmp.stat().st_size, self.size))
            if filepath_tmp.stat().st_size != self.size:
                self.logger.debug("Downloaded file size is wrong")
                self.reload()
                raise WebFileRequestError("Downloaded file size is wrong")

        self.logger.debug("Removing temporary file")
        filepath_tmp.rename(self.filepath)

    def download(self):
        """Read contents and save into a file."""
        if self.filepath.exists():
            self.logger.warning("{} is already downloaded.".format(self.filepath))
            return

        self.logger.info("Filepath is {}".format(self.filepath))

        if self.size:
            self.download_and_check_size()
        else:
            with self.filepath.open('ab') as f:
                for chunk in self.response.iter_content():
                    f.write(chunk)

    def unlink(self):
        try:
            self.filepath.unlink()
        except FileNotFoundError as e:
            pass

        try:
            Path(str(self.filepath) + '.part').unlink()
        except FileNotFoundError as e:
            pass

class WebFileSeekError(Exception):
    pass

class JoinedFile(FileIOBase):
    def __init__(self, filepath):
        super().__init__()
        self.filepath = Path(filepath)

    @property
    def filepaths(self):
        """Return a list of files."""
        return sorted(self.filepath.parent.glob('{}.part*'.format(self.filepath.name)), key=lambda x:int(re.findall(r'\d+$', x.suffix)[0]))

    @property
    def size(self):
        """Return a total size of files."""
        position = self.tell()
        self.seek(0)
        size = len(self.read())
        self.seek(position)
        return size

    def read(self, size=-1):
        if self.filepath.exists():
            return self.read_joined_file(size)
        else:
            return self.read_part_files(size)

    def read_joined_file(self, size=-1):
        """Read and return contents of joined file."""
        with self.filepath.open('rb') as f:
            f.seek(self.tell())
            return f.read(size)

    def read_part_files(self, size=-1):
        """Read and return contents of part files."""
        data = b''
        for filepath in self.filepaths:
            start = int(re.findall(r'\d+$', filepath.suffix)[0])
            stop = start + filepath.stat().st_size

            if self.tell() in range(start, stop):
                start_in_partfile = self.tell() - start
                stop_in_partfile = stop if size is None or size < 0 else start_in_partfile + size
                self.logger.debug('Read from cached file {} from {} to {}'.format(filepath, start_in_partfile, stop_in_partfile))
                with filepath.open('rb') as f:
                    f.seek(start_in_partfile)
                    read_data = f.read(stop_in_partfile-start_in_partfile)

                if size >= 0:
                    size -= len(read_data)
                self.seek(self.tell() + len(read_data))
                data += read_data

        return data

    def write(self, b):
        """Write contents."""
        if self.filepath.exists():
            with self.filepath.open('r+b') as f:
                f.seek(self.tell())
                f.write(b)
                return len(b)

        for filepath in self.filepaths:
            start = int(re.findall(r'\d+$', filepath.suffix)[0])
            stop = start + filepath.stat().st_size

            if self.tell() in range(start, stop+1):
                self.logger.debug('Saving data to {}'.format(filepath))
                with filepath.open('r+b') as f:
                    f.seek(self.tell()-start)
                    f.write(b)
                self.position += len(b)
                return len(b)

        partfile = Path('{}.part{}'.format(self.filepath, self.tell()))
        self.logger.debug('Saving data to {}'.format(partfile))
        with partfile.open('ab') as f:
            f.write(b)
        self.position += len(b)
        return len(b)

    def join(self):
        if self.filepath.exists():
            return

        self.logger.debug('Joining files')
        self.seek(0)
        with self.filepath.open('wb') as f:
            while True:
                chunk = self.read_part_files(1024)
                if chunk:
                    f.write(chunk)
                else:
                    break

        for filepath in self.filepaths:
            self.logger.debug('Removing {}'.format(filepath))
            filepath.unlink()

    def unlink(self):
        try:
            self.filepath.unlink()
        except FileNotFoundError:
            pass

        for filepath in self.filepaths:
            try:
                filepath.unlink()
            except FileNotFoundError:
                pass

class JoinedFileReadError(Exception):
    pass

class WebFileCached(WebFile):
    def seek(self, offset):
        self.position_cached = offset
        return offset

    def tell(self):
        return self.position_cached

    def read(self, size=-1):
        """Read and return contents."""
        if self.filepath.exists():
            self.logger.debug("Reading from cached file '{}'".format(self.filepath))
            with self.filepath.open('rb') as f:
                f.seek(self.tell())
                return f.read(size)

        joined_files = JoinedFile(self.filepath)

        joined_files.seek(self.tell())
        cached_data = joined_files.read(size)
        self.seek(self.tell()+len(cached_data))

        try:
            super().seek(joined_files.tell())
        except WebFileSeekError as e:
            return cached_data

        if not size or size < 0 or size > len(cached_data):
            if not size or size < 0:
                new_data = super().read()
                joined_files.write(new_data)
                self.seek(self.tell()+len(new_data))
            elif size > len(cached_data):
                new_data = super().read(size-len(cached_data))
                joined_files.write(new_data)
                self.seek(self.tell()+len(new_data))
        else:
            new_data = b''

        if joined_files.size == self.size:
            joined_files.join()

        return cached_data + new_data

    def download(self):
        """Read contents and save into a file."""
        if self.filepath.exists():
            self.logger.warning("{} is already downloaded.".format(self.filepath))
            return

        self.logger.info("Filepath is {}".format(self.filepath))

        with tqdm(total=self.size, initial=downloaded_file_size, unit='B', unit_scale=True, dynamic_ncols=True, ascii=True) as pbar:
            for chunk in self.read_in_chunks(1024):
                pbar.update(len(chunk))

    def unlink(self):
        JoinedFile(self.filepath).unlink()
