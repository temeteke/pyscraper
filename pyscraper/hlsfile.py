import copy
import hashlib
import logging
import os
import shutil
from functools import cached_property
from pathlib import Path
from urllib.parse import urljoin, urlparse, urlunparse

import ffmpy
import m3u8
from fake_useragent import UserAgent  # noqa: F401 -- patched by tests

from pyscraper.errors import PyscraperError
from pyscraper.requests import RequestsMixin
from pyscraper.utils import get_filename_from_url
from pyscraper.webfile import (
    FileIOBase,
    MyTqdm,
    WebFile,
    WebFileClientError,
    WebFileError,
    WebFileMixin,
)

logger = logging.getLogger(__name__)


def _apply_base_query_string(url, base_qs):
    """Append ``base_qs`` to ``url`` when it has no query string."""
    if base_qs:
        parsed = urlparse(url)
        if not parsed.query:
            return urlunparse(parsed._replace(query=base_qs))
    return url


def _validate_temp_directory(temp_directory, filepath):
    """Reject a scratch directory that ``shutil.rmtree`` must not remove.

    Raises ``ValueError`` for empty or whitespace-only values, ``.``, ``..``,
    the current working directory or its ancestors, the filesystem root, and the
    output file or its ancestors. See docs/downloading.md for the full contract.
    """
    raw = str(temp_directory)
    if raw.rstrip("/\\").strip() in ("", ".", ".."):
        raise ValueError(f"Invalid temp_directory: {temp_directory!r}")
    resolved = Path(temp_directory).resolve()
    if resolved == resolved.parent:
        raise ValueError(f"Invalid temp_directory (filesystem root): {temp_directory!r}")
    cwd = Path.cwd().resolve()
    if resolved == cwd or resolved in cwd.parents:
        raise ValueError(
            f"Invalid temp_directory (current working directory or its ancestor): "
            f"{temp_directory!r}"
        )
    output = Path(filepath).resolve()
    if resolved == output or resolved in output.parents:
        raise ValueError(
            f"temp_directory {temp_directory!r} must not contain the output file {filepath!r}"
        )
    return Path(temp_directory)


class HlsFileError(PyscraperError):
    """Base class for HLS failures (e.g. encrypted streams).

    ``status_code`` is None for HLS-level failures. Segment download
    failures propagate as ``WebFile*`` errors carrying their own
    ``status_code``. No automatic transient/permanent classification
    is performed.
    """


class HlsFileMixin(WebFileMixin):
    def get_filename(self):
        return str(Path(get_filename_from_url(self.url)).with_suffix(".mp4"))


class HlsFile(HlsFileMixin, RequestsMixin, FileIOBase):
    def __init__(
        self,
        url,
        headers: dict | None = None,
        cookies: dict | None = None,
        session=None,
        directory=".",
        filename=None,
        filestem=None,
        filesuffix=None,
    ):
        super().__init__()

        self.request_url = url
        self.request_headers = dict(headers) if headers else {}
        self.request_cookies = dict(cookies) if cookies else {}
        self.session = session
        self.directory = directory
        self.filename = filename
        self.filestem = filestem
        self.filesuffix = filesuffix
        self._base_query_string = ""

    @property
    def url(self):
        return self.request_url

    @url.setter
    def url(self, value):
        self.request_url = value
        self.clear_cache()

    @cached_property
    def m3u8_obj(self):
        def get_best_playlist(url):
            with WebFile(
                url,
                session=self.session,
                headers=self.request_headers,
                cookies=self.request_cookies,
            ) as wf:
                try:
                    content = wf.read().decode()
                except UnicodeDecodeError as e:
                    raise HlsFileError(e) from e
                base_uri = wf.response.url
                self._base_query_string = urlparse(base_uri).query
                m3u8_obj = m3u8.loads(content, uri=base_uri)
            if m3u8_obj.playlists:
                best = sorted(m3u8_obj.playlists, key=lambda x: x.stream_info.bandwidth)[-1]
                variant_url = _apply_base_query_string(best.absolute_uri, self._base_query_string)
                return get_best_playlist(variant_url)
            elif m3u8_obj.segments:
                return m3u8_obj
            else:
                raise HlsFileError(f"Empty playlist: {url}")

        return get_best_playlist(self.url)

    @cached_property
    def m3u8_content(self):
        return self.m3u8_obj.dumps()

    @cached_property
    def m3u8_content_url(self):
        output_lines = []
        for input_line in self.m3u8_content.split("\n"):
            if input_line.startswith("#"):
                output_lines.append(input_line)
            elif input_line:
                output_lines.append(urljoin(self.m3u8_obj.base_uri, input_line))
        return "\n".join(output_lines)

    @cached_property
    def _has_encryption(self):
        if any(k for k in self.m3u8_obj.keys if k and k.uri):
            return True
        if any(k for k in self.m3u8_obj.session_keys if k and k.uri):
            return True
        for segment in self.m3u8_obj.segments:
            if segment.key and segment.key.uri:
                return True
        return False

    def _iter_resource_uris(self):
        """Yield playlist resource URIs in download order, deduplicated."""
        seen = set()

        def _emit(uri):
            if uri and uri not in seen:
                seen.add(uri)
                return uri
            return None

        for segment in self.m3u8_obj.segments:
            if uri := _emit(segment.absolute_uri):
                yield uri
            init = segment.init_section
            if init and (uri := _emit(init.absolute_uri)):
                yield uri
        for key in filter(None, self.m3u8_obj.keys):
            if key.uri and (uri := _emit(key.absolute_uri)):
                yield uri
        for key in filter(None, self.m3u8_obj.session_keys):
            if key.uri and (uri := _emit(key.absolute_uri)):
                yield uri
        for segment in self.m3u8_obj.segments:
            key = segment.key
            if key and key.uri and (uri := _emit(key.absolute_uri)):
                yield uri
        for init_section in self.m3u8_obj.segment_map:
            if uri := _emit(init_section.absolute_uri):
                yield uri

    @cached_property
    def _uri_to_local_name(self):
        ordered_uris = list(self._iter_resource_uris())

        basename_groups = {}
        for uri in ordered_uris:
            basename = get_filename_from_url(uri)
            basename_groups.setdefault(basename, []).append(uri)

        name_map = {}
        for basename, uris in basename_groups.items():
            if len(uris) == 1:
                name_map[uris[0]] = basename
            else:
                stem, ext = os.path.splitext(basename)
                for uri in uris:
                    h = hashlib.sha256(uri.encode()).hexdigest()[:8]
                    name_map[uri] = f"{stem}_{h}{ext}"
        return name_map

    @cached_property
    def m3u8_content_filename(self):
        mapping = self._uri_to_local_name
        obj = copy.deepcopy(self.m3u8_obj)
        for init_section in obj.segment_map:
            init_section.uri = mapping[init_section.absolute_uri]
        for key in filter(None, obj.keys):
            if key.uri and key.absolute_uri in mapping:
                key.uri = mapping[key.absolute_uri]
        for key in filter(None, obj.session_keys):
            if key.uri and key.absolute_uri in mapping:
                key.uri = mapping[key.absolute_uri]
        for segment in obj.segments:
            if segment.init_section:
                segment.init_section.uri = mapping[segment.init_section.absolute_uri]
            if segment.key and segment.key.uri and segment.key.absolute_uri in mapping:
                segment.key.uri = mapping[segment.key.absolute_uri]
            segment.uri = mapping[segment.absolute_uri]
        return obj.dumps()

    def _make_resource_file(self, absolute_uri, temp_directory):
        mapping = self._uri_to_local_name
        base_qs = getattr(self, "_base_query_string", "")
        return WebFile(
            _apply_base_query_string(absolute_uri, base_qs),
            headers=dict(self.headers),
            cookies=dict(self.cookies),
            directory=temp_directory,
            filename=mapping[absolute_uri],
        )

    def _build_web_files(self, temp_directory):
        mapping = self._uri_to_local_name
        files = []
        last_init_uri = None
        for segment in self.m3u8_obj.segments:
            init = segment.init_section
            if init and init.absolute_uri != last_init_uri:
                files.append(self._make_resource_file(init.absolute_uri, temp_directory))
                last_init_uri = init.absolute_uri
            files.append(self._make_resource_file(segment.absolute_uri, temp_directory))

        seen_keys = set()
        key_groups = [self.m3u8_obj.keys, self.m3u8_obj.session_keys]
        for keys in key_groups:
            for key in filter(None, keys):
                if key.uri and key.absolute_uri in mapping and key.absolute_uri not in seen_keys:
                    seen_keys.add(key.absolute_uri)
                    files.append(self._make_resource_file(key.absolute_uri, temp_directory))
        for segment in self.m3u8_obj.segments:
            key = segment.key
            if (
                key
                and key.uri
                and key.absolute_uri in mapping
                and key.absolute_uri not in seen_keys
            ):
                seen_keys.add(key.absolute_uri)
                files.append(self._make_resource_file(key.absolute_uri, temp_directory))
        return files

    @cached_property
    def web_files(self):
        """Segment/key ``WebFile`` objects for the default :attr:`temp_directory`."""
        return self._build_web_files(self.temp_directory)

    @property
    def temp_directory(self):
        """Scratch directory for segments and the playlist (default ``directory / filestem``)."""
        return self.directory / self.filestem

    @property
    def temp_file(self):
        """Temporary ffmpeg output path (default ``.<filename>``)."""
        return self.filepath.with_name("." + self.filepath.name)

    def clear_cache(self):
        """Clear all cached properties."""
        for name, value in type(self).__dict__.items():
            if isinstance(value, cached_property):
                try:
                    delattr(self, name)
                except AttributeError:
                    pass
        self._base_query_string = ""

    def _require_unencrypted(self, method):
        if self._has_encryption:
            raise HlsFileError(f"Cannot {method}() encrypted HLS stream.")

    def read(self, size=None):
        """
        Read the concatenated content of all playlist resources in order.

        For fMP4 playlists, EXT-X-MAP init sections are included before the
        segments that reference them, producing a logically complete byte stream.

        Args:
            size (int, optional): Number of bytes to read. If None, read all.

        Returns:
            bytes: Concatenated content of all playlist resources.
        """
        self._require_unencrypted("read")
        if size == 0:
            return b""
        chunks = []
        web_file_position = self.position
        for web_file in self.web_files:
            with web_file as wf:
                file_size = wf.size
                if file_size is None:
                    if web_file_position:
                        raise WebFileError("Cannot read() when a segment size is unknown.")
                elif web_file_position >= file_size:
                    web_file_position -= file_size
                    continue
                if web_file_position:
                    wf.seek(web_file_position)
                    web_file_position = 0
                chunk = wf.read(size)
                chunks.append(chunk)
                if size is not None:
                    size -= len(chunk)
                    if size == 0:
                        break
        total_chunk = b"".join(chunks)
        self.position += len(total_chunk)
        return total_chunk

    def read_files(self):
        """
        Yield the full content of each playlist resource in order.

        For fMP4 playlists, EXT-X-MAP init sections are yielded before the
        segments that reference them.

        Yields:
            bytes: Full content of each playlist resource.
        """
        self._require_unencrypted("read_files")
        for web_file in self.web_files:
            with web_file as wf:
                yield wf.read()

    def _prepare_download(
        self, directory, filename, filestem, filesuffix, temp_file, temp_directory
    ):
        """Apply naming overrides and validate call-local scratch paths."""
        self.directory = directory
        self.filename = filename
        self.filestem = filestem
        self.filesuffix = filesuffix
        resolved_temp_file = Path(temp_file) if temp_file is not None else self.temp_file
        resolved_temp_directory = _validate_temp_directory(
            temp_directory if temp_directory is not None else self.temp_directory,
            self.filepath,
        )
        return resolved_temp_file, resolved_temp_directory

    def _write_local_playlist(self, temp_directory):
        m3u8_file = temp_directory / Path(self.filestem + ".m3u8")
        with m3u8_file.open("w") as f:
            f.write(self.m3u8_content_filename)
        return m3u8_file

    def _download_resources(self, temp_directory, progress_callback):
        web_files = self._build_web_files(temp_directory)
        total_files = len(web_files)
        with MyTqdm(total=total_files, unit="file", dynamic_ncols=True) as pbar:
            for current_file, web_file in enumerate(web_files, start=1):
                web_file.download()
                pbar.update(1)
                if progress_callback:
                    progress_callback(current_file, total_files)

    def _merge_resources(self, m3u8_file, temp_file):
        ff = ffmpy.FFmpeg(
            inputs={str(m3u8_file): "-allowed_extensions ALL -extension_picky 0"},
            outputs={str(temp_file): "-c copy"},
        )
        try:
            ff.run()
        except (ffmpy.FFRuntimeError, ffmpy.FFExecutableNotFoundError) as e:
            raise HlsFileError(e) from e

    def download(
        self,
        directory=None,
        filename=None,
        filestem=None,
        filesuffix=None,
        progress_callback=None,
        temp_file=None,
        temp_directory=None,
    ):
        """
        Download all playlist resources (init segments, media segments) and merge into a single file.

        Resources are processed in playlist order. For fMP4 playlists, EXT-X-MAP init
        sections are downloaded before the segments that reference them.

        Args:
            directory (str or Path, optional): Output directory.
            filename (str, optional): Output filename.
            filestem (str, optional): Output file stem.
            filesuffix (str, optional): Output file suffix.
            progress_callback (callable, optional):
                Callback function to notify download progress.
                Called as progress_callback(current_resource_count, total_resource_count)
                where:
                    current_resource_count (int): Number of resources downloaded so far.
                    total_resource_count (int): Total number of resources to download.
            temp_file (str or Path, optional):
                Override the ffmpeg merge output path. Defaults to ``.<filename>``.
                The override is local to this call and does not mutate the
                instance; pass it to ``unlink(temp_file=...)`` to clean it up.
            temp_directory (str or Path, optional):
                Override the segment/playlist scratch directory. Defaults to
                ``directory / filestem``. Local to this call; pass it to
                ``unlink(temp_directory=...)`` to clean it up.
        """
        resolved_temp_file, resolved_temp_directory = self._prepare_download(
            directory, filename, filestem, filesuffix, temp_file, temp_directory
        )

        if self.filepath.exists():
            self.logger.warning(f"{self.filepath} is already downloaded.")
            return

        self.logger.info(f"Downloading {self.url} to {self.filepath}")

        resolved_temp_directory.mkdir(parents=True, exist_ok=True)

        if resolved_temp_file.exists():
            resolved_temp_file.unlink()

        m3u8_file = self._write_local_playlist(resolved_temp_directory)
        self._download_resources(resolved_temp_directory, progress_callback)
        self._merge_resources(m3u8_file, resolved_temp_file)

        shutil.move(resolved_temp_file, self.filepath)

        shutil.rmtree(resolved_temp_directory)

        return self.filepath

    def unlink(self, temp_file=None, temp_directory=None):
        """Remove the merged file and the temporary file/directory.

        Args:
            temp_file (str or Path, optional): Temporary file to remove instead
                of the default :attr:`temp_file`.
            temp_directory (str or Path, optional): Temporary directory to remove
                instead of the default :attr:`temp_directory`.
        """
        resolved_temp_file = Path(temp_file) if temp_file is not None else self.temp_file
        resolved_temp_directory = _validate_temp_directory(
            temp_directory if temp_directory is not None else self.temp_directory,
            self.filepath,
        )

        super().unlink()
        resolved_temp_file.unlink(missing_ok=True)

        if resolved_temp_directory.exists():
            shutil.rmtree(resolved_temp_directory)

    def exists(self):
        """Check reachability of the first playlist resource only.

        For fMP4 this is the EXT-X-MAP init section, not necessarily a
        segment. Not a complete validity check for all segments.
        Returns False for empty playlists and 4xx client errors;
        other failures propagate (same contract as WebFile.exists).
        """
        try:
            return self.web_files[0].exists()
        except IndexError:
            return False
        except HlsFileError:
            return False
        except WebFileClientError:
            return False
