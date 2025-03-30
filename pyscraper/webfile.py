import logging
import mimetypes
import re
import sys
import unicodedata
from functools import partial
from pathlib import Path

import requests
import urllib3.exceptions
from tqdm import tqdm

from pyscraper.requests import RequestsMixin
from pyscraper.utils import get_filename_from_url


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


class FileIOBase:
    def __init__(self):
        self.logger = logging.getLogger(".".join([__name__, self.__class__.__name__]))
        self.position = 0

    def seek(self, position: int) -> int:
        """Move the file pointer to a new position."""
        self.position = position
        return position

    def tell(self) -> int:
        """Return the current file pointer position."""
        return self.position


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
        return get_filename_from_url(self.url)

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
        if filesuffix:
            self._filesuffix = filesuffix

    @property
    def filename(self):
        if filename := getattr(self, "_filename", None):
            return filename
        else:
            return self.filestem + self.filesuffix

    @filename.setter
    def filename(self, filename):
        if filename:
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
        url: str,
        session: requests.Session = None,
        headers: dict = {},
        cookies: dict = {},
        directory: str = ".",
        filename: str = None,
        filestem: str = None,
        filesuffix: str = None,
        timeout: int = 30,
    ):
        self.response = None

        super().__init__()

        self.logger.debug(url)

        self.url = url
        self.session = session
        self.headers = headers
        self.cookies = cookies
        self.timeout = timeout

        self.directory = directory
        self.filename = filename
        self.filestem = filestem
        self.filesuffix = filesuffix

    def __enter__(self):
        return self.open()

    def __exit__(self, exc_type, exc_value, traceback):
        self.close()

    @property
    def url(self):
        if self.response:
            return self.response.url
        else:
            return self.request_url

    @url.setter
    def url(self, url):
        self.request_url = url

        # Reopen response if it was already opened
        if self.response:
            self.open_response()

    @property
    def size(self):
        if not self.response:
            raise WebFileError("Response is not opened.")

        if self.response:
            if content_range := self.response.headers.get("Content-Range"):
                return int(content_range.split("/")[-1].strip())
            elif content_length := self.response.headers.get("Content-Length"):
                return int(content_length)

    def get_filename(self):
        if self.response:
            if content_disposition := self.response.headers.get("Content-Disposition"):
                if m := re.search('filename="?([^"]+)"?', content_disposition):
                    return m.group(1)
        return super().get_filename()

    @property
    def filesuffix(self):
        if filesuffix := getattr(self, "_filesuffix", None):
            return filesuffix
        if filename := getattr(self, "_filename", None):
            return Path(filename).suffix
        if self.response:
            content_type = self.response.headers.get("Content-Type", "")
            if extension := mimetypes.guess_extension(content_type):
                return extension
        return Path(self.get_filename()).suffix

    @filesuffix.setter
    def filesuffix(self, filesuffix):
        self._filesuffix = filesuffix

    @property
    def tempfile(self):
        return self.filepath.with_name(self.filepath.name + ".part")

    def open_response(self):
        self.logger.debug("Getting {}".format(self.request_url))
        self.logger.debug("Request Headers: " + str(self.session.headers))

        # Make a GET request to the URL
        try:
            self.response = self.session.get(self.request_url, stream=True, timeout=self.timeout)
        except requests.exceptions.ConnectionError as e:
            raise WebFileConnectionError(e) from e
        except requests.exceptions.Timeout as e:
            raise WebFileTimeoutError(e) from e

        self.logger.debug("Response Headers: " + str(self.response.headers))

        try:
            self.response.raise_for_status()
        except requests.exceptions.HTTPError as e:
            self.close()
            if 400 <= e.response.status_code < 500:
                raise WebFileClientError(e) from e
            elif 500 <= e.response.status_code < 600:
                raise WebFileServerError(e) from e
            else:
                raise WebFileError(e) from e

        self.response.raw.decode_content = True

    def close_response(self):
        if self.response:
            self.response.close()
            self.response = None

    def open(self):
        self.open_session()
        self.open_response()
        return self

    def close(self):
        self.close_response()
        self.close_session()

    def read(self, size=None):
        """Read and return contents."""
        if not self.response:
            raise WebFileError("Response is not opened.")

        try:
            chunk = self.response.raw.read(size)
        except urllib3.exceptions.ProtocolError as e:
            raise WebFileConnectionError(e) from e
        except urllib3.exceptions.ReadTimeoutError as e:
            raise WebFileTimeoutError(e) from e
        return chunk

    def seek(self, offset: int):
        if not self.response:
            raise WebFileError("Response is not opened.")

        # check the server supports range requests
        if not self.response.headers.get("Accept-Ranges") == "bytes":
            raise WebFileSeekError("Server does not support range requests.")

        # check if offset is within range
        if offset < 0 or offset >= self.size:
            raise WebFileSeekError(f"Offset {offset} is out of range. File size is {self.size}.")

        if offset == self.position:
            return self.position

        if offset:
            self.headers = {"Range": "bytes={}-".format(offset)}
        else:
            self.headers = {"Range": None}

        # Reopen response with new range
        self.open_response()

        return super().seek(offset)

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

        with self as wf:
            if wf.size:
                if wf.tempfile.exists():
                    downloaded_file_size = wf.tempfile.stat().st_size
                else:
                    downloaded_file_size = 0

                wf.seek(downloaded_file_size)

                try:
                    with MyTqdm(
                        total=wf.size,
                        initial=downloaded_file_size,
                        unit="B",
                        unit_scale=True,
                        dynamic_ncols=True,
                    ) as pbar:
                        with self.tempfile.open("ab") as f:
                            for chunk in iter(partial(wf.read, 8192), b""):
                                f.write(chunk)
                                pbar.update(len(chunk))
                except requests.exceptions.HTTPError as e:
                    wf.logger.warning(e)
                    if e.response.status_code == 416 and wf.tempfile.exists():
                        wf.tempfile.unlink()
                        raise WebFileClientError(
                            "Range Not Satisfiable. Removed downloaded file."
                        ) from e
                    else:
                        raise WebFileError(e) from e
                except WebFileSeekError as e:
                    wf.logger.warning(e)
                    wf.tempfile.unlink()
                    raise WebFileClientError("Seek Error. Removed downloaded file.") from e

                # Check file size after download if not compressed
                if not wf.response.headers.get("Content-Encoding"):
                    wf.logger.debug(f"Comparing file size {wf.tempfile.stat().st_size} {wf.size}")
                    if wf.tempfile.stat().st_size > wf.size:
                        wf.tempfile.unlink()
                        raise WebFileError(
                            "Downloaded file size is larger than expected. Removed downloaded file."
                        )
                    elif wf.tempfile.stat().st_size < wf.size:
                        raise WebFileError("Downloaded file size is smaller than expected.")

                wf.logger.debug("Removing temporary file")
                wf.tempfile.rename(wf.filepath)

            else:
                with wf.filepath.open("wb") as f:
                    for chunk in iter(partial(wf.read, 8192), b""):
                        f.write(chunk)

        return self.filepath

    def unlink(self):
        super().unlink()
        self.tempfile.unlink(missing_ok=True)

    def exists(self):
        if self.response:
            return self.response.ok
        else:
            try:
                with self as wf:
                    return wf.response.ok
            except WebFileClientError:
                return False
