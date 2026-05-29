import copy
import hashlib
import logging
import os
import shutil
from functools import cached_property
from pathlib import Path
from urllib.parse import urljoin
from fake_useragent import UserAgent

import ffmpy
import m3u8

from pyscraper.requests import RequestsMixin
from pyscraper.utils import get_filename_from_url
from pyscraper.webfile import FileIOBase, MyTqdm, WebFile, WebFileClientError, WebFileMixin

logger = logging.getLogger(__name__)


class HlsFileError(Exception):
    pass


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
            with WebFile(url, session=self.session) as wf:
                m3u8_obj = m3u8.loads(wf.read().decode(), uri=url)
            if m3u8_obj.playlists:
                return get_best_playlist(
                    sorted(m3u8_obj.playlists, key=lambda x: x.stream_info.bandwidth)[
                        -1
                    ].absolute_uri
                )
            else:
                return m3u8_obj

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
    def _local_name_map(self):
        all_uris = []
        for segment in self.m3u8_obj.segments:
            all_uris.append(segment.absolute_uri)
            if segment.init_section:
                all_uris.append(segment.init_section.absolute_uri)
        for init_section in self.m3u8_obj.segment_map:
            all_uris.append(init_section.absolute_uri)

        basename_groups = {}
        for uri in all_uris:
            basename = get_filename_from_url(uri)
            if basename not in basename_groups:
                basename_groups[basename] = []
            basename_groups[basename].append(uri)

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
        mapping = self._local_name_map
        obj = copy.deepcopy(self.m3u8_obj)
        for init_section in obj.segment_map:
            init_section.uri = mapping[init_section.absolute_uri]
        for segment in obj.segments:
            if segment.init_section:
                segment.init_section.uri = mapping[segment.init_section.absolute_uri]
            segment.uri = mapping[segment.absolute_uri]
        return obj.dumps()

    @cached_property
    def web_files(self):
        mapping = self._local_name_map
        files = []
        last_init_uri = None
        for segment in self.m3u8_obj.segments:
            init = segment.init_section
            if init and init.absolute_uri != last_init_uri:
                files.append(
                    WebFile(
                        init.absolute_uri,
                        headers=dict(self.headers),
                        cookies=dict(self.cookies),
                        directory=self.temp_directory,
                        filename=mapping[init.absolute_uri],
                    )
                )
                last_init_uri = init.absolute_uri
            files.append(
                WebFile(
                    segment.absolute_uri,
                    headers=dict(self.headers),
                    cookies=dict(self.cookies),
                    directory=self.temp_directory,
                    filename=mapping[segment.absolute_uri],
                )
            )
        return files

    @property
    def temp_directory(self):
        return self.directory / self.filestem

    @cached_property
    def temp_file(self):
        return self.filepath.with_name("." + self.filepath.name)

    def clear_cache(self):
        """Clear all cached properties."""
        cached_properties = [
            'm3u8_obj',
            'm3u8_content',
            'm3u8_content_url',
            'm3u8_content_filename',
            '_local_name_map',
            'web_files'
        ]
        for prop_name in cached_properties:
            try:
                delattr(self, prop_name)
            except AttributeError:
                pass

    def read(self, size=None):
        total_chunk = b""
        web_file_position = self.position
        for web_file in self.web_files:
            with web_file as wf:
                if web_file_position >= wf.size:
                    web_file_position -= wf.size
                    continue
                else:
                    wf.seek(web_file_position)
                    web_file_position = 0
                    chunk = wf.read(size)
                total_chunk += chunk
                if size:
                    size -= len(chunk)
                    if size == 0:
                        break
        self.position += len(total_chunk)
        return total_chunk

    def read_files(self):
        for web_file in self.web_files:
            with web_file as wf:
                yield wf.read()

    def download(
        self,
        directory=None,
        filename=None,
        filestem=None,
        filesuffix=None,
        progress_callback=None,
    ):
        """
        Download all segments and merge into a single file.

        Args:
            directory (str or Path, optional): Output directory.
            filename (str, optional): Output filename.
            filestem (str, optional): Output file stem.
            filesuffix (str, optional): Output file suffix.
            progress_callback (callable, optional):
                Callback function to notify download progress.
                Called as progress_callback(current_file_count, total_file_count)
                where:
                    current_file_count (int): Number of files downloaded so far.
                    total_file_count (int): Total number of files to download.
        """
        self.directory = directory
        self.filename = filename
        self.filestem = filestem
        self.filesuffix = filesuffix

        if self.filepath.exists():
            self.logger.warning(f"{self.filepath} is already downloaded.")
            return

        self.logger.info(f"Downloading {self.url} to {self.filepath}")

        self.temp_directory.mkdir(parents=True, exist_ok=True)

        if self.temp_file.exists():
            self.temp_file.unlink()

        m3u8_file = self.temp_directory / Path(self.filestem + ".m3u8")
        with m3u8_file.open("w") as f:
            f.write(self.m3u8_content_filename)

        total_files = len(self.web_files)
        current_file = 0
        with MyTqdm(
            total=total_files,
            unit="file",
            dynamic_ncols=True,
        ) as pbar:
            for web_file in self.web_files:
                web_file.download()
                current_file += 1
                pbar.update(1)
                if progress_callback:
                    progress_callback(current_file, total_files)

        ff = ffmpy.FFmpeg(inputs={str(m3u8_file): None}, outputs={str(self.temp_file): "-c copy"})
        ff.run()

        self.temp_file.rename(self.filepath)

        shutil.rmtree(self.temp_directory)

        return self.filepath

    def unlink(self):
        super().unlink()

        temp_directory = self.temp_directory
        if temp_directory.exists():
            shutil.rmtree(temp_directory)

    def exists(self):
        # NOTE: checks reachability of the first resource in playlist order.
        # For fMP4 this is the EXT-X-MAP init section, not necessarily a segment.
        # Not a complete validity check for all segments.
        try:
            return self.web_files[0].exists()
        except IndexError:
            return False
        except WebFileClientError:
            return False
