import logging
import mimetypes
import shutil
import sys
from functools import partial
from pathlib import Path
from urllib.parse import unquote

import requests
import urllib3.exceptions
from tqdm import tqdm

from pyscraper.requests import RequestsMixin
from pyscraper.utils import get_filename_from_url

logger = logging.getLogger(__name__)


_HEXDIGITS = set("0123456789abcdefABCDEF")


def _parse_header_params(value):
    """Split a header value into its ``;``-separated parameters.

    Handles both quoted and unquoted parameter values. Inside a quoted string only
    ``\\"`` and ``\\\\`` are treated as escapes, so Windows-style backslashes in a
    value such as ``filename="C:\\dir\\a.mp4"`` are preserved. A leading disposition
    type (a token without ``=``) is skipped, so headers that consist of parameters
    only are handled too. Returns ``None`` when a quoted value is left unterminated.
    """
    params = []
    length = len(value)
    i = 0

    while i < length:
        if value[i] == ";":
            i += 1
        while i < length and value[i] in " \t":
            i += 1
        if i >= length:
            break

        name_start = i
        while i < length and value[i] not in "=;":
            i += 1
        name = value[name_start:i].strip().lower()

        if i >= length or value[i] != "=":
            # Disposition type or a stray token without a value; skip it.
            continue

        i += 1
        while i < length and value[i] in " \t":
            i += 1

        param_value = ""
        if i < length and value[i] == '"':
            i += 1
            chars = []
            closed = False
            while i < length:
                char = value[i]
                if char == '"':
                    closed = True
                    i += 1
                    break
                if char == "\\" and i + 1 < length and value[i + 1] in '"\\':
                    i += 1
                    char = value[i]
                chars.append(char)
                i += 1
            if not closed:
                return None
            param_value = "".join(chars)
            while i < length and value[i] != ";":
                i += 1
        else:
            value_start = i
            while i < length and value[i] != ";":
                i += 1
            param_value = value[value_start:i].strip()

        if name:
            params.append((name, param_value))

    return params


def _has_invalid_percent_encoding(value):
    index = value.find("%")
    while index != -1:
        if index + 3 > len(value) or any(
            c not in _HEXDIGITS for c in value[index + 1 : index + 3]
        ):
            return True
        index = value.find("%", index + 3)
    return False


def _decode_extended_value(value):
    """Decode an RFC 5987/6266 ``ext-value`` (``charset'language'pct-encoded``).

    Returns ``None`` for values that are not ext-values (no ``'`` separator),
    carry an invalid percent-encoding, or fail to decode.
    """
    if "'" not in value:
        return None
    charset, _, rest = value.partition("'")
    charset = charset or "UTF-8"
    _, separator, remainder = rest.partition("'")
    encoded = remainder if separator else rest
    if _has_invalid_percent_encoding(encoded):
        return None
    try:
        return unquote(encoded, encoding=charset, errors="strict")
    except (LookupError, UnicodeDecodeError):
        return None


def _basename(value):
    return value.replace("\\", "/").rsplit("/", 1)[-1]


def _is_valid_filename(name):
    if not name.strip() or name in (".", ".."):
        return False
    return not any(ord(char) < 32 or ord(char) == 127 for char in name)


def _filename_from_content_disposition(content_disposition):
    """Resolve a filename from a Content-Disposition header value.

    ``filename*`` takes precedence over ``filename``. Returns ``None`` when no
    usable value is present, letting the caller fall back to the URL basename.
    """
    params = _parse_header_params(content_disposition)
    if params is None:
        return None
    extended = next((v for k, v in params if k == "filename*"), None)
    plain = next((v for k, v in params if k == "filename"), None)

    for raw, is_extended in ((extended, True), (plain, False)):
        if raw is None:
            continue
        value = _decode_extended_value(raw) if is_extended else raw
        if value is None:
            continue
        name = _basename(value)
        if _is_valid_filename(name):
            return name
    return None


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
            if isinstance(directory, Path):
                self._directory = directory
            elif isinstance(directory, str):
                self._directory = Path(directory)

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
            self._filestem = filestem

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
        headers: dict | None = None,
        cookies: dict | None = None,
        session: requests.Session = None,
        timeout: int = 30,
        directory: str = ".",
        filename: str = None,
        filestem: str = None,
        filesuffix: str = None,
    ):
        self.response = None

        super().__init__()

        self.logger.debug(url)

        self.request_url = url
        self.request_headers = dict(headers) if headers else {}
        self.request_cookies = dict(cookies) if cookies else {}
        self.session = session
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
        if self.response is None:
            return self.request_url
        else:
            return self.response.url

    @url.setter
    def url(self, url):
        self.request_url = url

        # Reopen response if it was already opened
        if self.response is not None:
            self.close_response()
            self.open_response()

    @property
    def size(self):
        if self.response is None:
            raise WebFileError("Response is not opened.")

        if content_range := self.response.headers.get("Content-Range"):
            return int(content_range.split("/")[-1].strip())
        elif content_length := self.response.headers.get("Content-Length"):
            return int(content_length)

    def get_filename(self):
        """Resolve the output filename.

        When the response carries a ``Content-Disposition`` header, its
        ``filename*`` parameter (RFC 5987, ``charset'language'percent-encoded``,
        UTF-8 when the charset is omitted) takes precedence over ``filename``.
        Both quoted and unquoted values are supported, directory components
        (``/`` and ``\\``) are stripped, and empty, ``.``, ``..`` or
        control-character values are rejected. Anything rejected or absent
        falls back to the URL basename.
        """
        if self.response is not None:
            if content_disposition := self.response.headers.get("Content-Disposition"):
                if filename := _filename_from_content_disposition(content_disposition):
                    return filename
        return super().get_filename()

    @property
    def filesuffix(self):
        if filesuffix := getattr(self, "_filesuffix", None):
            return filesuffix
        if filename := getattr(self, "_filename", None):
            return Path(filename).suffix
        # Prioritize URL extension if present
        if url_suffix := Path(self.get_filename()).suffix:
            return url_suffix
        # Fallback to Content-Type when URL has no extension
        if self.response:
            content_type = self.response.headers.get("Content-Type", "")
            if extension := mimetypes.guess_extension(content_type):
                return extension
        return ""

    @filesuffix.setter
    def filesuffix(self, filesuffix):
        self._filesuffix = filesuffix

    @property
    def temp_file(self):
        """Temporary path used while downloading.

        Defaults to ``<filepath>.part``. Overridable per call via
        ``download(temp_file=...)`` without mutating the instance.
        """
        return self.filepath.with_name(self.filepath.name + ".part")

    @property
    def tempfile(self):
        """Deprecated alias for :attr:`temp_file`."""
        return self.temp_file

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
        if self.response is not None:
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
        if self.response is None:
            raise WebFileError("Response is not opened.")

        try:
            chunk = self.response.raw.read(size)
        except urllib3.exceptions.ProtocolError as e:
            raise WebFileConnectionError(e) from e
        except urllib3.exceptions.ReadTimeoutError as e:
            raise WebFileTimeoutError(e) from e
        return chunk

    def seek(self, offset: int):
        if self.response is None:
            raise WebFileError("Response is not opened.")

        # check the server supports range requests
        if self.response.headers.get("Accept-Ranges") != "bytes":
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
        progress_callback=None,
        temp_file=None,
    ):
        """
        Download the file from the web and save it locally.

        Args:
            directory (str or Path, optional): Output directory.
            file_name, filename, file_stem, filestem, file_suffix, filesuffix: Output file naming options.
            progress_callback (callable, optional):
                Callback function to notify download progress.
                Called as progress_callback(current_size, total_size)
                where:
                    current_size (int): Number of bytes downloaded so far.
                    total_size (int or None): Total number of bytes to download (None if unknown).
            temp_file (str or Path, optional):
                Override the temporary path used for the partial download.
                Defaults to ``<filepath>.part`` when omitted. The override is
                local to this call and does not mutate the instance; pass it to
                ``unlink(temp_file=...)`` to clean it up.
        """

        self.directory = directory
        self.filename = file_name or filename
        self.filestem = file_stem or filestem
        self.filesuffix = file_suffix or filesuffix

        resolved_temp_file = Path(temp_file) if temp_file is not None else self.temp_file

        if self.filepath.exists():
            self.logger.warning(f"{self.filepath} is already downloaded.")
            return

        self.logger.info(f"Downloading {self.url} to {self.filepath}")

        self.directory.mkdir(parents=True, exist_ok=True)

        with self as wf:
            if wf.size:
                if resolved_temp_file.exists():
                    downloaded_file_size = resolved_temp_file.stat().st_size
                    try:
                        wf.seek(downloaded_file_size)
                    except WebFileSeekError:
                        resolved_temp_file.unlink()
                        downloaded_file_size = 0
                else:
                    downloaded_file_size = 0

                with MyTqdm(
                    total=wf.size,
                    initial=downloaded_file_size,
                    unit="B",
                    unit_scale=True,
                    dynamic_ncols=True,
                ) as pbar:
                    with resolved_temp_file.open("ab") as f:
                        current_size = downloaded_file_size
                        for chunk in iter(partial(wf.read, 8192), b""):
                            f.write(chunk)
                            pbar.update(len(chunk))
                            current_size += len(chunk)
                            if progress_callback:
                                progress_callback(current_size, wf.size)

                # Check file size after download if not compressed
                if not wf.response.headers.get("Content-Encoding"):
                    wf.logger.debug(
                        f"Comparing file size {resolved_temp_file.stat().st_size} {wf.size}"
                    )
                    if resolved_temp_file.stat().st_size > wf.size:
                        resolved_temp_file.unlink()
                        raise WebFileError(
                            "Downloaded file size is larger than expected. Removed downloaded file."
                        )
                    elif resolved_temp_file.stat().st_size < wf.size:
                        raise WebFileError("Downloaded file size is smaller than expected.")

                wf.logger.debug("Removing temporary file")
                shutil.move(resolved_temp_file, wf.filepath)

            else:
                with wf.filepath.open("wb") as f:
                    current_size = 0
                    for chunk in iter(partial(wf.read, 8192), b""):
                        f.write(chunk)
                        current_size += len(chunk)
                        if progress_callback:
                            progress_callback(current_size, None)

        return self.filepath

    def unlink(self, temp_file=None):
        """Remove the downloaded file and its temporary file.

        Args:
            temp_file (str or Path, optional): Temporary path to remove instead
                of the default :attr:`temp_file`.
        """
        super().unlink()
        resolved_temp_file = Path(temp_file) if temp_file is not None else self.temp_file
        resolved_temp_file.unlink(missing_ok=True)

    def exists(self):
        if self.response is None:
            try:
                with self as wf:
                    return wf.response.ok
            except WebFileClientError:
                return False
        else:
            return self.response.ok
