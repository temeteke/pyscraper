from abc import ABC, abstractmethod
import logging
import mimetypes
import re
import sys
import unicodedata
from functools import cached_property
from pathlib import Path
from urllib.parse import urlparse

import requests
import urllib3.exceptions
from tqdm import tqdm

from pyscraper.requests import RequestsMixin


logger = logging.getLogger(__name__)


class MyTqdm(tqdm):
    def __init__(self, *args, **kwargs):
        if "file" not in kwargs:
            kwargs["file"] = sys.stderr
        if hasattr(kwargs["file"], "isatty") and not kwargs["file"].isatty():
            kwargs["disable"] = True
        elif logger.getEffectiveLevel() > logging.INFO:
            kwargs["disable"] = True
        else:
            kwargs["disable"] = False

        return super().__init__(*args, **kwargs)


class FileIOBase(ABC):
    def __init__(self):
        self.logger = logging.getLogger(".".join([__name__, self.__class__.__name__]))
        self.position = 0

    @abstractmethod
    def read(self, size):
        pass

    def seek(self, position):
        self.logger.debug("Seek to {}".format(position))
        self.position = position
        return position

    def tell(self):
        return self.position

    def read_in_chunks(self, chunk_size, start=0, stop=None):
        self.seek(start)
        while True:
            if stop and stop - self.tell() < chunk_size:
                chunk_size = stop - self.tell()
                self.logger.debug("Read last chunk(size:{})".format(chunk_size))

            chunk = self.read(chunk_size)
            if chunk:
                yield chunk
            else:
                break


class WebFileError(Exception):
    pass


class WebFileConnectionError(WebFileError):
    pass


class WebFileTimeoutError(WebFileError):
    pass


class WebFileClientError(WebFileError):
    pass


class WebFileServerError(WebFileError):
    pass


class WebFileSeekError(WebFileError):
    pass


class WebFileMixin:
    def __str__(self):
        return self.url

    def __eq__(self, other):
        if not isinstance(other, self.__class__):
            return NotImplemented
        return self.url == other.url

    def get_filename(self):
        return urlparse(self.url).path.split("/")[-1]

    @property
    def directory(self):
        if not getattr(self, "_directory", None):
            self._directory = Path(".")
        return self._directory

    @directory.setter
    def directory(self, directory):
        if directory:
            self._directory = Path(re.sub(r'[:|\s\*\?\\"]', "_", str(directory)))

    @property
    def filestem(self):
        if filestem := getattr(self, "_filestem", None):
            return filestem
        elif filename := getattr(self, "_filename", None):
            return Path(filename).stem
        else:
            return Path(self.get_filename()).stem

    @filestem.setter
    def filestem(self, filestem):
        if filestem:
            filestem = unicodedata.normalize("NFC", filestem)
            while len(filestem.encode()) > 255 - 10:
                filestem = filestem[:-1]
            self._filestem = re.sub(r'[/:|\s\*\.\?\\"]', "_", filestem)

    @property
    def filesuffix(self):
        if filesuffix := getattr(self, "_filesuffix", None):
            return filesuffix
        elif filename := getattr(self, "_filename", None):
            return Path(filename).suffix
        else:
            return Path(self.get_filename()).suffix

    @filesuffix.setter
    def filesuffix(self, filesuffix):
        self._filesuffix = filesuffix

    @property
    def filename(self):
        if filename := getattr(self, "_filename", None):
            return filename
        else:
            return self.filestem + self.filesuffix

    @filename.setter
    def filename(self, filename):
        self._filename = filename

    @property
    def filepath(self):
        return Path(self.directory, self.filename)

    def unlink(self):
        try:
            self.filepath.unlink()
        except FileNotFoundError:
            pass


class WebFile(WebFileMixin, RequestsMixin, FileIOBase):
    def __init__(
        self,
        url,
        session=None,
        headers={},
        cookies={},
        directory=".",
        filename=None,
        filestem=None,
        filesuffix=None,
        timeout=30,
    ):
        super().__init__()

        self.logger.debug(url)

        self.url = url
        self.session = session
        self.headers = headers
        self.cookies = cookies
        self.directory = directory
        self.filename = filename
        self.filestem = filestem
        self.filesuffix = filesuffix
        self.timeout = timeout

    @cached_property
    def response(self):
        self.logger.debug("Getting {}".format(self.request_url))
        self.logger.debug("Request Headers: " + str(self.session.headers))

        try:
            r = self.session.get(self.request_url, stream=True, timeout=self.timeout)
        except requests.exceptions.ConnectionError as e:
            raise WebFileConnectionError(e) from e
        except requests.exceptions.Timeout as e:
            raise WebFileTimeoutError(e) from e

        self.logger.debug("Response Headers: " + str(r.headers))

        try:
            r.raise_for_status()
        except requests.exceptions.HTTPError as e:
            if 400 <= e.response.status_code < 500:
                raise WebFileClientError(e) from e
            elif 500 <= e.response.status_code < 600:
                raise WebFileServerError(e) from e
            else:
                raise WebFileError(e) from e

        return r

    @property
    def url(self):
        try:
            return self.response.url
        except WebFileError as e:
            logger.error(e)
            return self.request_url

    @url.setter
    def url(self, value):
        self.request_url = value
        try:
            del self.response
        except AttributeError:
            pass

    @cached_property
    def size(self):
        try:
            return int(self.response.headers["Content-Length"])
        except KeyError:
            return None

    def get_filename(self):
        if "Content-Disposition" in self.response.headers:
            if m := re.search(
                'filename="?([^"]+)"?', self.response.headers["Content-Disposition"]
            ):
                return m.group(1)
        return super().get_filename()

    @property
    def filesuffix(self):
        if filesuffix := getattr(self, "_filesuffix", None):
            return filesuffix
        elif filename := getattr(self, "_filename", None):
            return Path(filename).suffix
        elif extension := mimetypes.guess_extension(self.response.headers.get("Content-Type", "")):
            return extension
        else:
            return Path(self.get_filename()).suffix

    @filesuffix.setter
    def filesuffix(self, filesuffix):
        self._filesuffix = filesuffix

    @property
    def tempfile(self):
        return self.filepath.with_name(self.filepath.name + ".part")

    def seek(self, offset, force=False):
        if offset >= self.size:
            raise WebFileSeekError("{} is out of range 0-{}".format(offset, self.size - 1))

        if not force and offset == self.position:
            return self.position

        if offset:
            self.headers = {"Range": "bytes={}-".format(offset)}
        else:
            self.headers = {"Range": None}

        return super().seek(offset)

    def reload(self):
        self.logger.debug("Reloading")
        self.seek(self.tell(), force=True)

    def read(self, size=None):
        """Read and return contents."""
        self.response.raw.decode_content = True
        try:
            chunk = self.response.raw.read(size)
        except urllib3.exceptions.ProtocolError as e:
            raise WebFileConnectionError(e) from e
        except urllib3.exceptions.ReadTimeoutError as e:
            raise WebFileTimeoutError(e) from e
        self.position += len(chunk)
        return chunk

    def download_and_check_size(self):
        """Download file and check downloaded file size"""
        if self.tempfile.exists():
            downloaded_file_size = self.tempfile.stat().st_size
        else:
            downloaded_file_size = 0

        try:
            with MyTqdm(
                total=self.size,
                initial=downloaded_file_size,
                unit="B",
                unit_scale=True,
                dynamic_ncols=True,
            ) as pbar:
                with self.tempfile.open("ab") as f:
                    for chunk in self.read_in_chunks(1024, downloaded_file_size):
                        f.write(chunk)
                        pbar.update(len(chunk))
        except requests.exceptions.HTTPError as e:
            self.logger.warning(e)
            if e.response.status_code == 416 and self.tempfile.exists():
                self.tempfile.unlink()
                raise WebFileClientError("Range Not Satisfiable. Removed downloaded file.") from e
            else:
                raise WebFileError(e) from e
        except WebFileSeekError as e:
            self.logger.warning(e)
            self.tempfile.unlink()
            raise WebFileClientError("Seek Error. Removed downloaded file.") from e

        if "gzip" not in self.response.headers.get("Content-Encoding", ""):
            self.logger.debug(
                "Comparing file size {} {}".format(self.tempfile.stat().st_size, self.size)
            )
            if self.tempfile.stat().st_size > self.size:
                self.tempfile.unlink()
                raise WebFileError(
                    "Downloaded file size is larger than expected. Removed downloaded file."
                )
            elif self.tempfile.stat().st_size < self.size:
                raise WebFileError("Downloaded file size is smaller than expected.")

        self.logger.debug("Removing temporary file")
        self.tempfile.rename(self.filepath)

    def download(
        self,
        directory=None,
        file_name=None,
        filename=None,
        file_stem=None,
        filestem=None,
        file_suffix=None,
        filesuffix=None,
    ):
        """Read contents and save into a file."""

        self.directory = directory
        self.filename = file_name or filename
        self.filestem = file_stem or filestem
        self.filesuffix = file_suffix or filesuffix

        if self.filepath.exists():
            self.logger.warning(f"{self.filepath} is already downloaded.")
            return

        self.logger.info(f"Downloading {self.url} to {self.filepath}")

        self.directory.mkdir(parents=True, exist_ok=True)

        if self.size:
            self.download_and_check_size()
        else:
            with self.filepath.open("ab") as f:
                for chunk in self.response.iter_content():
                    f.write(chunk)

        return self.filepath

    def unlink(self):
        super().unlink()

        try:
            self.tempfile.unlink()
        except FileNotFoundError:
            pass

    def exists(self):
        try:
            return self.response.ok
        except WebFileClientError:
            return False


class JoinedFile(FileIOBase):
    def __init__(self, filepath):
        super().__init__()
        self.filepath = Path(filepath)

    @property
    def filepaths(self):
        """Return a list of files."""
        return sorted(
            self.filepath.parent.glob("{}.part*".format(self.filepath.name)),
            key=lambda x: int(re.findall(r"\d+$", x.suffix)[0]),
        )

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
        with self.filepath.open("rb") as f:
            f.seek(self.tell())
            return f.read(size)

    def read_part_files(self, size=-1):
        """Read and return contents of part files."""
        data = b""
        for filepath in self.filepaths:
            start = int(re.findall(r"\d+$", filepath.suffix)[0])
            stop = start + filepath.stat().st_size

            if self.tell() in range(start, stop):
                start_in_partfile = self.tell() - start
                stop_in_partfile = stop if size is None or size < 0 else start_in_partfile + size
                self.logger.debug(
                    "Read from cached file {} from {} to {}".format(
                        filepath, start_in_partfile, stop_in_partfile
                    )
                )
                with filepath.open("rb") as f:
                    f.seek(start_in_partfile)
                    read_data = f.read(stop_in_partfile - start_in_partfile)

                if size >= 0:
                    size -= len(read_data)
                self.seek(self.tell() + len(read_data))
                data += read_data

        return data

    def write(self, b):
        """Write contents."""
        if self.filepath.exists():
            with self.filepath.open("r+b") as f:
                f.seek(self.tell())
                f.write(b)
                return len(b)

        for filepath in self.filepaths:
            start = int(re.findall(r"\d+$", filepath.suffix)[0])
            stop = start + filepath.stat().st_size

            if self.tell() in range(start, stop + 1):
                self.logger.debug("Saving data to {}".format(filepath))
                with filepath.open("r+b") as f:
                    f.seek(self.tell() - start)
                    f.write(b)
                self.position += len(b)
                return len(b)

        partfile = Path("{}.part{}".format(self.filepath, self.tell()))
        self.logger.debug("Saving data to {}".format(partfile))
        with partfile.open("ab") as f:
            f.write(b)
        self.position += len(b)
        return len(b)

    def join(self):
        if self.filepath.exists():
            return

        self.logger.debug("Joining files")
        self.seek(0)
        with self.filepath.open("wb") as f:
            while True:
                chunk = self.read_part_files(1024)
                if chunk:
                    f.write(chunk)
                else:
                    break

        for filepath in self.filepaths:
            self.logger.debug("Removing {}".format(filepath))
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
            with self.filepath.open("rb") as f:
                f.seek(self.tell())
                return f.read(size)

        joined_files = JoinedFile(self.filepath)

        joined_files.seek(self.tell())
        cached_data = joined_files.read(size)
        self.seek(self.tell() + len(cached_data))

        try:
            super().seek(joined_files.tell())
        except WebFileSeekError:
            return cached_data

        if not size or size < 0 or size > len(cached_data):
            if not size or size < 0:
                new_data = super().read()
                joined_files.write(new_data)
                self.seek(self.tell() + len(new_data))
            elif size > len(cached_data):
                new_data = super().read(size - len(cached_data))
                joined_files.write(new_data)
                self.seek(self.tell() + len(new_data))
        else:
            new_data = b""

        if joined_files.size == self.size:
            joined_files.join()

        return cached_data + new_data

    def download(
        self,
        directory=None,
        file_name=None,
        filename=None,
        file_stem=None,
        filestem=None,
        file_suffix=None,
        filesuffix=None,
    ):
        """Read contents and save into a file."""

        self.directory = directory
        self.filename = file_name or filename
        self.filestem = file_stem or filestem
        self.filesuffix = file_suffix or filesuffix

        if self.filepath.exists():
            self.logger.warning(f"{self.filepath} is already downloaded.")
            return

        self.logger.info(f"Downloading {self.url} to {self.filepath}")

        with MyTqdm(
            total=self.size, initial=0, unit="B", unit_scale=True, dynamic_ncols=True
        ) as pbar:
            for chunk in self.read_in_chunks(1024):
                pbar.update(len(chunk))

        return self.filepath

    def unlink(self):
        JoinedFile(self.filepath).unlink()
