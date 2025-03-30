import logging
import shutil
from functools import cached_property
from pathlib import Path
from urllib.parse import urljoin
from fake_useragent import UserAgent

import ffmpy
import m3u8

from pyscraper.requests import RequestsMixin
from pyscraper.utils import LazyList, get_filename_from_url
from pyscraper.webfile import FileIOBase, MyTqdm, WebFile, WebFileClientError, WebFileMixin

logger = logging.getLogger(__name__)

user_agent = UserAgent(platforms="desktop")


class HlsFileError(Exception):
    pass


class HlsFileMixin(WebFileMixin):
    def get_filename(self):
        return str(Path(get_filename_from_url(self.url)).with_suffix(".mp4"))


class HlsFile(HlsFileMixin, RequestsMixin, FileIOBase):
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
    ):
        super().__init__()

        self.url = url
        self.session = session
        self.headers = headers
        self.cookies = cookies
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
    def m3u8_content_filename(self):
        output_lines = []
        for input_line in self.m3u8_content.split("\n"):
            if input_line.startswith("#"):
                output_lines.append(input_line)
            elif input_line:
                output_lines.append(get_filename_from_url(input_line))
        return "\n".join(output_lines)

    @cached_property
    def web_files(self):
        return LazyList(
            self.m3u8_obj.segments,
            lambda x: WebFile(
                x.absolute_uri,
                headers=self.headers,
                cookies=self.cookies,
                directory=self.temp_directory,
                filename=get_filename_from_url(x.absolute_uri),
            ),
        )

    @property
    def temp_directory(self):
        return self.directory / self.filestem

    @cached_property
    def temp_file(self):
        return self.filepath.with_name("." + self.filepath.name)

    def clear_cache(self):
        try:
            del self.m3u8_obj
        except AttributeError:
            pass
        try:
            del self.m3u8_content
        except AttributeError:
            pass
        try:
            del self.m3u8_content_url
        except AttributeError:
            pass
        try:
            del self.m3u8_content_filename
        except AttributeError:
            pass
        try:
            del self.web_files
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
    ):
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

        with MyTqdm(
            total=len(self.web_files),
            dynamic_ncols=True,
        ) as pbar:
            for web_file in self.web_files:
                web_file.download()
                pbar.update()

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
        try:
            return self.web_files[0].exists()
        except IndexError:
            return False
        except WebFileClientError:
            return False
