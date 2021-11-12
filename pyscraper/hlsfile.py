import re
from urllib.parse import urljoin, urlparse
import ffmpy
import logging
from pathlib import Path
import m3u8
import shutil
from functools import cached_property
from .webfile import WebFile, WebFileMixin
from .utils import HEADERS, RequestsMixin

logger = logging.getLogger(__name__)


class HlsFileError(Exception):
    pass


class HlsFileMixin(WebFileMixin):
    @cached_property
    def filesuffix(self):
        return '.mp4'


class HlsFileFfmpeg(HlsFileMixin):
    def __init__(self, url, headers={}, directory='.', filename=None, filestem=None, filesuffix=None):
        self.logger = logging.getLogger('.'.join([__name__, self.__class__.__name__]))

        self.url = url
        self.headers = headers
        self.headers.update(HEADERS)

        self.set_path(directory, filename, filestem, filesuffix)

    @cached_property
    def tempfile(self):
        return self.filepath.with_name('.tmp.' + self.filepath.name)

    def download(self):
        if self.filepath.exists():
            self.logger.warning(f"{self.filepath} is already downloaded.")
            return

        self.logger.info(f"Downloading {self.url} to {self.filepath}")

        if self.tempfile.exists():
            self.tempfile.unlink()

        try:
            ff = ffmpy.FFmpeg(
                global_options="-headers '" + '\r\n'.join(['{}: {}'.format(k, v) for k, v in self.headers.items()]) + "'",
                inputs={self.url: None},
                outputs={self.tempfile: '-c copy'},
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


class HlsFileRequests(HlsFileMixin, RequestsMixin):
    def __init__(self, url, session=None, headers={}, cookies={}, directory='.', filename=None, filestem=None, filesuffix=None):
        self.logger = logging.getLogger('.'.join([__name__, self.__class__.__name__]))

        self.url = url

        self.init_session(session, headers, cookies)

        self.set_path(directory, filename, filestem, filesuffix)

    def download(self):
        if self.filepath.exists():
            self.logger.warning(f"{self.filepath} is already downloaded.")
            return

        self.logger.info(f"Downloading {self.url} to {self.filepath}")

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

        m3u8_file = WebFile(m3u8_playlist_url, session=self.session, directory=str(self.directory / Path(self.filestem)), filename='hls.m3u8')
        if m3u8_file.filepath.exists():
            m3u8_file.filepath.unlink()
        m3u8_file.download()

        for ts_url in re.findall(r'^[^#\s].+', m3u8_file.filepath.read_text(), flags=re.MULTILINE):
            if not (self.directory / Path(self.filestem) / Path(urlparse(ts_url).path).name).exists():
                WebFile(urljoin(m3u8_playlist_url, ts_url), session=self.session, directory=str(self.directory / Path(self.filestem))).download()

        # 連結
        temp = []
        with m3u8_file.filepath.open() as f:
            for x in f:
                if x.startswith('http'):
                    temp.append(urlparse(x).path.split('/').pop())
                else:
                    temp.append(x)
        with m3u8_file.filepath.open('w') as f:
            f.write('\n'.join(temp))

        ff = ffmpy.FFmpeg(
            inputs={str(m3u8_file.filepath): None},
            outputs={str(self.filepath): '-c copy'},
        )
        self.logger.debug(ff)
        ff.run()

        shutil.rmtree(str(self.directory / Path(self.filestem)))

        return self.filepath
