import logging
import re
import shutil
from functools import cached_property
from pathlib import Path
from urllib.parse import urljoin, urlparse

import ffmpy
import m3u8

from .utils import HEADERS, RequestsMixin
from .webfile import FileIOBase, WebFile, WebFileMixin

logger = logging.getLogger(__name__)


class HlsFileError(Exception):
    pass


class HlsFile(WebFileMixin, RequestsMixin, FileIOBase):
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

        self.init_session(session, headers, cookies)

        self.set_path(directory, filename, filestem, filesuffix)

    @cached_property
    def m3u8_obj(self):
        def get_best_playlist(url):
            m3u8_obj = m3u8.loads(WebFile(url, session=self.session).read().decode(), uri=url)
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
        output_lines = []
        for input_line in self.m3u8_obj.dumps().split("\n"):
            if input_line.startswith("#"):
                output_lines.append(input_line)
            elif input_line:
                output_lines.append(urljoin(self.m3u8_obj.base_uri, input_line))
        return "\n".join(output_lines)

    @cached_property
    def web_files(self):
        return [
            WebFile(segment.absolute_uri, session=self.session)
            for segment in self.m3u8_obj.segments
        ]

    def read(self, size=None):
        total_chunk = b""
        web_file_position = self.position
        for web_file in self.web_files:
            if web_file_position >= web_file.size:
                web_file_position -= web_file.size
                continue
            else:
                web_file.seek(web_file_position)
                web_file_position = 0
            chunk = web_file.read(size)
            total_chunk += chunk
            if size:
                size -= len(chunk)
                if size == 0:
                    break
        self.position += len(total_chunk)
        return total_chunk

    def read_files(self):
        for web_file in self.web_files:
            yield web_file.read()


class HlsFileMixin(WebFileMixin):
    @cached_property
    def filesuffix(self):
        return ".mp4"


class HlsFileFfmpeg(HlsFileMixin):
    def __init__(
        self, url, headers={}, directory=".", filename=None, filestem=None, filesuffix=None
    ):
        self.logger = logging.getLogger(".".join([__name__, self.__class__.__name__]))

        self.url = url
        self.headers = headers
        self.headers.update(HEADERS)

        self.set_path(directory, filename, filestem, filesuffix)

    @cached_property
    def tempfile(self):
        return self.filepath.with_name(".tmp." + self.filepath.name)

    def download(
        self,
        directory=None,
        filename=None,
        filestem=None,
        filesuffix=None,
    ):
        self.set_path(directory, filename, filestem, filesuffix)

        if self.filepath.exists():
            self.logger.warning(f"{self.filepath} is already downloaded.")
            return self.filepath

        self.logger.info(f"Downloading {self.url} to {self.filepath}")

        if self.tempfile.exists():
            self.tempfile.unlink()

        try:
            ff = ffmpy.FFmpeg(
                global_options="-headers '"
                + "\r\n".join(["{}: {}".format(k, v) for k, v in self.headers.items()])
                + "'",
                inputs={self.url: None},
                outputs={self.tempfile: "-c copy"},
            )
            self.logger.debug(ff)
            ff.run()
        except Exception as e:
            self.logger.exception(e)
            if self.tempfile.exists():
                self.tempfile.unlink()
            raise HlsFileError from None

        self.tempfile.rename(self.filepath)

        return self.filepath

    def unlink(self):
        super().unlink()

        try:
            self.tempfile.unlink()
        except FileNotFoundError:
            pass

    def exists(self):
        try:
            ff = ffmpy.FFprobe(
                global_options="-headers '"
                + "\r\n".join(["{}: {}".format(k, v) for k, v in self.headers.items()])
                + "'",
                inputs={self.url: None},
            )
            self.logger.debug(ff)
            ff.run()
            return True
        except ffmpy.FFRuntimeError:
            return False


class HlsFileRequests(HlsFileMixin, RequestsMixin):
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
        self.logger = logging.getLogger(".".join([__name__, self.__class__.__name__]))

        self.url = url

        self.init_session(session, headers, cookies)

        self.set_path(directory, filename, filestem, filesuffix)

    @cached_property
    def m3u8_file(self):
        r = self.session.get(self.url)
        self.logger.debug(self.url)
        self.logger.debug("Request Headers: " + str(r.request.headers))
        self.logger.debug("Response Headers: " + str(r.headers))

        # m3u8のリンクが含まれていた場合は選択する
        m3u8_obj = m3u8.loads(r.text)
        if m3u8_obj.playlists:
            m3u8_playlist = sorted(m3u8_obj.playlists, key=lambda x: x.stream_info.bandwidth)[-1]
            m3u8_playlist_url = urljoin(self.url, m3u8_playlist.uri)
            self.logger.debug(m3u8_playlist_url)
        else:
            m3u8_playlist_url = self.url

        return WebFile(
            m3u8_playlist_url,
            session=self.session,
            directory=str(self.directory / Path(self.filestem)),
            filename="hls.m3u8",
        )

    def download(
        self,
        directory=None,
        filename=None,
        filestem=None,
        filesuffix=None,
    ):
        self.set_path(directory, filename, filestem, filesuffix)

        if self.filepath.exists():
            self.logger.warning(f"{self.filepath} is already downloaded.")
            return

        self.logger.info(f"Downloading {self.url} to {self.filepath}")

        if self.m3u8_file.filepath.exists():
            self.m3u8_file.filepath.unlink()
        self.m3u8_file.download()

        for ts_url in re.findall(
            r"^[^#\s].+", self.m3u8_file.filepath.read_text(), flags=re.MULTILINE
        ):
            if not (
                self.directory / Path(self.filestem) / Path(urlparse(ts_url).path).name
            ).exists():
                WebFile(
                    urljoin(self.m3u8_file.url, ts_url),
                    session=self.session,
                    directory=str(self.directory / Path(self.filestem)),
                ).download()

        # 連結
        temp = []
        with self.m3u8_file.filepath.open() as f:
            for x in f:
                if x.startswith("http"):
                    temp.append(urlparse(x).path.split("/").pop())
                else:
                    temp.append(x)
        with self.m3u8_file.filepath.open("w") as f:
            f.write("\n".join(temp))

        ff = ffmpy.FFmpeg(
            inputs={str(self.m3u8_file.filepath): None},
            outputs={str(self.filepath): "-c copy"},
        )
        self.logger.debug(ff)
        ff.run()

        shutil.rmtree(str(self.directory / Path(self.filestem)))

        return self.filepath

    def exists(self):
        return self.m3u8_file.exists()
