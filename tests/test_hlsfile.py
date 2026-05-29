import logging
from pathlib import Path

import pytest
import requests

from pyscraper.webfile import WebFile
from pyscraper.hlsfile import HlsFile, _stable_local_name

logger = logging.getLogger("pyscraper")
logger.setLevel(logging.DEBUG)

fh = logging.FileHandler(filename="test_pyscraper.log")
fh.setFormatter(logging.Formatter("%(asctime)s %(name)s %(levelname)8s %(message)s"))
logger.addHandler(fh)


@pytest.fixture(scope="session")
def url():
    return "https://raw.githubusercontent.com/temeteke/pyscraper/master/tests/testdata/video.m3u8"


@pytest.fixture(scope="session")
def url_absolute():
    return "https://raw.githubusercontent.com/temeteke/pyscraper/master/tests/testdata/video_absolute_url.m3u8"


@pytest.fixture(scope="session")
def url_with_map():
    return "https://raw.githubusercontent.com/temeteke/pyscraper/master/tests/testdata/video_with_map.m3u8"


@pytest.fixture(scope="session")
def url_collide_seg():
    return "https://raw.githubusercontent.com/temeteke/pyscraper/master/tests/testdata/video_collide_seg.m3u8"


@pytest.fixture(scope="session")
def url_collide_init_query():
    return "https://raw.githubusercontent.com/temeteke/pyscraper/master/tests/testdata/video_collide_init_query.m3u8"


@pytest.fixture(scope="session")
def url_error():
    return "https://raw.githubusercontent.com/temeteke/pyscraper/master/tests/testdata/video_.m3u8"


@pytest.fixture(scope="session")
def web_files():
    return [
        WebFile(
            "https://raw.githubusercontent.com/temeteke/pyscraper/master/tests/testdata/video000.ts"
        ),
        WebFile(
            "https://raw.githubusercontent.com/temeteke/pyscraper/master/tests/testdata/video001.ts"
        ),
        WebFile(
            "https://raw.githubusercontent.com/temeteke/pyscraper/master/tests/testdata/video002.ts"
        ),
    ]


@pytest.fixture(scope="session")
def content(web_files):
    # Return mocked content instead of making real HTTP requests
    # This simulates the concatenated video segments
    # video000.ts (57152 bytes) + video001.ts (56400 bytes) + video002.ts (23312 bytes) = 136864 bytes
    segment_size = 20000  # Mock segment size
    return b'\x47' + b'x' * (segment_size * 3 - 1)  # 3 segments of ~20KB each


class TestHlsFile:
    @pytest.fixture
    def hls_file(self, url):
        return HlsFile(url)

    @pytest.fixture
    def hls_file_absolute_url(self, url_absolute):
        return HlsFile(url_absolute)

    @pytest.fixture
    def hls_file_error(self, url_error):
        return HlsFile(url_error)

    def test_url_01(self, hls_file, url):
        assert hls_file.url == url

    def test_url_02(self, hls_file, url_error):
        hls_file.web_files[0]
        hls_file.url = url_error
        assert hls_file.url == url_error

    def test_directory(self, hls_file):
        assert hls_file.directory == Path(".")

    def test_filestem(self, hls_file):
        assert hls_file.filestem == "video"

    def test_filesuffix(self, hls_file):
        assert hls_file.filesuffix == ".mp4"

    def test_filename(self, hls_file):
        assert hls_file.filename == "video.mp4"

    def test_m3u8_content_url(self, hls_file):
        assert (
            hls_file.m3u8_content_url.strip()
            == """
#EXTM3U
#EXT-X-VERSION:3
#EXT-X-TARGETDURATION:8
#EXTINF:8.341667,
https://raw.githubusercontent.com/temeteke/pyscraper/master/tests/testdata/video000.ts
#EXTINF:8.341667,
https://raw.githubusercontent.com/temeteke/pyscraper/master/tests/testdata/video001.ts
#EXTINF:3.336667,
https://raw.githubusercontent.com/temeteke/pyscraper/master/tests/testdata/video002.ts
#EXT-X-ENDLIST
""".strip()
        )

    def test_m3u8_content_filename(self, hls_file):
        assert (
            hls_file.m3u8_content_filename.strip()
            == """
#EXTM3U
#EXT-X-VERSION:3
#EXT-X-TARGETDURATION:8
#EXTINF:8.341667,
video000.ts
#EXTINF:8.341667,
video001.ts
#EXTINF:3.336667,
video002.ts
#EXT-X-ENDLIST
""".strip()
        )

    def test_web_files_01(self, hls_file):
        expected = [
            WebFile(
                "https://raw.githubusercontent.com/temeteke/pyscraper/master/tests/testdata/video000.ts"
            ),
            WebFile(
                "https://raw.githubusercontent.com/temeteke/pyscraper/master/tests/testdata/video001.ts"
            ),
            WebFile(
                "https://raw.githubusercontent.com/temeteke/pyscraper/master/tests/testdata/video002.ts"
            ),
        ]
        assert list(hls_file.web_files) == expected
        assert list(hls_file.web_files) == expected

    def test_web_files_02(self, hls_file):
        assert (
            WebFile(
                "https://raw.githubusercontent.com/temeteke/pyscraper/master/tests/testdata/video000.ts"
            )
            in hls_file.web_files
        )
        assert (
            WebFile(
                "https://raw.githubusercontent.com/temeteke/pyscraper/master/tests/testdata/video001.ts"
            )
            in hls_file.web_files
        )
        assert (
            WebFile(
                "https://raw.githubusercontent.com/temeteke/pyscraper/master/tests/testdata/video002.ts"
            )
            in hls_file.web_files
        )

    def test_read_all(self, hls_file, content):
        assert hls_file.read() == content

    def test_read_0(self, hls_file, content):
        hls_file.seek(0)
        assert hls_file.read(128) == content[:128]

    def test_read_512(self, hls_file, content):
        hls_file.seek(512)
        assert hls_file.read(128) == content[512 : 512 + 128]

    def test_read_57152(self, hls_file, content):
        hls_file.seek(57152)
        assert hls_file.read(128) == content[57152 : 57152 + 128]

    def test_read_60000(self, hls_file, content):
        hls_file.seek(60000)
        assert hls_file.read(128) == content[60000 : 60000 + 128]

    def test_read_256(self, hls_file, content):
        hls_file.seek(256)
        assert hls_file.read() == content[256:]

    def test_read_files(self, hls_file, web_files):
        for hls_file_content, web_file in zip(hls_file.read_files(), web_files):
            with web_file.open() as wf:
                assert hls_file_content == wf.read()

    def test_exists_true(self, hls_file):
        assert hls_file.exists()

    def test_exists_false(self, hls_file_error):
        assert not hls_file_error.exists()

    def test_download_unlink(self, hls_file):
        f = hls_file.download()
        assert f.exists()

        hls_file.unlink()
        assert not f.exists()

    def test_download_unlink_absolute_url(self, hls_file_absolute_url):
        f = hls_file_absolute_url.download()
        assert f.exists()

        hls_file_absolute_url.unlink()
        assert not f.exists()

    def test_download_unlink_filename(self, hls_file):
        f = hls_file.download(filename="video_file.mp4")
        assert f.exists()
        assert f.name == "video_file.mp4"

        hls_file.unlink()
        assert not f.exists()

    def test_download_progress_callback(self, hls_file):
        progresses = []

        def cb(current, total):
            progresses.append((current, total))

        hls_file.download(progress_callback=cb)
        # The last callback should indicate completion
        assert progresses[-1][0] == progresses[-1][1]

        hls_file.unlink()

    def test_session(self):
        session = requests.Session()
        session.headers["test"] = "test"
        assert HlsFile("https://httpbin.org/headers", session=session).headers["test"] == "test"

    def test_clear_cache(self, hls_file):
        """Test that clear_cache removes all cached properties"""
        # Access cached properties to ensure they are cached
        _ = hls_file.m3u8_obj
        _ = hls_file.m3u8_content
        _ = hls_file.m3u8_content_url
        _ = hls_file.m3u8_content_filename
        _ = hls_file._local_name_map
        _ = hls_file.web_files

        # Verify properties are cached (accessing __dict__ directly)
        assert "m3u8_obj" in hls_file.__dict__
        assert "m3u8_content" in hls_file.__dict__
        assert "m3u8_content_url" in hls_file.__dict__
        assert "m3u8_content_filename" in hls_file.__dict__
        assert "_local_name_map" in hls_file.__dict__
        assert "web_files" in hls_file.__dict__

        # Clear cache
        hls_file.clear_cache()

        # Verify all cached properties are removed
        assert "m3u8_obj" not in hls_file.__dict__
        assert "m3u8_content" not in hls_file.__dict__
        assert "m3u8_content_url" not in hls_file.__dict__
        assert "m3u8_content_filename" not in hls_file.__dict__
        assert "_local_name_map" not in hls_file.__dict__
        assert "web_files" not in hls_file.__dict__

    def test_url_change_clears_cache(self, hls_file, url_error):
        """Test that changing URL automatically clears cached properties"""
        # Access cached properties
        original_obj = hls_file.m3u8_obj
        _ = hls_file.web_files

        # Verify properties are cached
        assert "m3u8_obj" in hls_file.__dict__
        assert "web_files" in hls_file.__dict__

        # Change URL (should trigger clear_cache)
        hls_file.url = url_error

        # Verify cache was cleared
        assert "m3u8_obj" not in hls_file.__dict__
        assert "web_files" not in hls_file.__dict__

    def test_cached_property_recomputation(self, hls_file):
        """Test that cached properties are recomputed after clearing cache"""
        # Access and cache a property
        first_obj = hls_file.m3u8_obj
        first_id = id(first_obj)

        # Clear cache
        hls_file.clear_cache()

        # Access again - should create new object
        second_obj = hls_file.m3u8_obj
        second_id = id(second_obj)

        # Objects should have same content but different identity (new instance)
        assert first_id != second_id
        assert first_obj.is_variant == second_obj.is_variant

    def test_web_files_headers_cookies_not_shared(self):
        hls = HlsFile("https://a.com/playlist.m3u8")
        wf1 = WebFile("https://a.com/seg0.ts", headers=dict(hls.headers), cookies=dict(hls.cookies))
        wf2 = WebFile("https://a.com/seg1.ts", headers=dict(hls.headers), cookies=dict(hls.cookies))
        wf1.request_headers["X"] = "1"
        assert "X" not in wf2.request_headers

    def test_no_map_in_segment_only_playlist(self, hls_file):
        content = hls_file.m3u8_content_filename
        assert "#EXT-X-MAP:" not in content
        assert content.strip() == """
#EXTM3U
#EXT-X-VERSION:3
#EXT-X-TARGETDURATION:8
#EXTINF:8.341667,
video000.ts
#EXTINF:8.341667,
video001.ts
#EXTINF:3.336667,
video002.ts
#EXT-X-ENDLIST
""".strip()


@pytest.mark.no_mock
class TestStableLocalName:
    def test_no_query_returns_basename(self):
        assert _stable_local_name("https://example.com/init.mp4") == "init.mp4"

    def test_query_different_uri_different_name(self):
        a = _stable_local_name("https://example.com/init.mp4?token=abc")
        b = _stable_local_name("https://example.com/init.mp4?token=xyz")
        assert a != b

    def test_query_name_format(self):
        name = _stable_local_name("https://example.com/init.mp4?token=abc")
        assert name.startswith("init_")
        assert name.endswith(".mp4")
        assert "?" not in name

    def test_same_query_same_name(self):
        a = _stable_local_name("https://example.com/init.mp4?token=abc")
        b = _stable_local_name("https://example.com/init.mp4?token=abc")
        assert a == b


class TestHlsFileWithMap:
    @pytest.fixture
    def hls_file_with_map(self, url_with_map):
        return HlsFile(url_with_map)

    def test_m3u8_content_filename_has_map(self, hls_file_with_map):
        content = hls_file_with_map.m3u8_content_filename
        assert "#EXT-X-MAP:" in content
        assert "init.mp4?token=abc" not in content
        assert "#EXT-X-MAP:URI=\"init_" in content
        assert "BYTERANGE" in content

    def test_m3u8_content_filename_segments(self, hls_file_with_map):
        content = hls_file_with_map.m3u8_content_filename
        assert "seg0.m4s" in content
        assert "seg1.m4s" in content
        assert "#EXTINF:" in content
        assert "seg0.m4s" in content

    def test_init_web_files(self, hls_file_with_map):
        inits = hls_file_with_map.init_web_files
        assert len(inits) == 1
        wf = inits[0]
        assert "init_" in wf.filename
        assert wf.filename.endswith(".mp4")

    def test_download_with_map(self, hls_file_with_map):
        f = hls_file_with_map.download()
        assert f.exists()
        hls_file_with_map.unlink()
        assert not f.exists()


class TestHlsFileCollideSeg:
    @pytest.fixture
    def hls_file_collide_seg(self, url_collide_seg):
        return HlsFile(url_collide_seg)

    def test_local_name_map_uses_hash(self, hls_file_collide_seg):
        mapping = hls_file_collide_seg._local_name_map
        uris = list(mapping.keys())
        assert len(uris) == 4
        names = list(mapping.values())
        for name in names:
            assert "_" in name

    def test_seg_filenames_differ(self, hls_file_collide_seg):
        mapping = hls_file_collide_seg._local_name_map
        seg_uris = [
            s.absolute_uri for s in hls_file_collide_seg.m3u8_obj.segments
        ]
        f0, f1 = (mapping[u] for u in seg_uris)
        assert f0 != f1
        assert f0.endswith(".ts")
        assert f1.endswith(".ts")
        assert f0 != "seg.ts"
        assert f1 != "seg.ts"

    def test_init_filenames_differ(self, hls_file_collide_seg):
        mapping = hls_file_collide_seg._local_name_map
        init_uris = [
            s.init_section.absolute_uri
            for s in hls_file_collide_seg.m3u8_obj.segments
        ]
        f0, f1 = (mapping[u] for u in init_uris)
        assert f0 != f1
        assert f0.endswith(".mp4")
        assert f1.endswith(".mp4")
        assert f0 != "init.mp4"
        assert f1 != "init.mp4"

    def test_m3u8_content_filename_no_original(self, hls_file_collide_seg):
        content = hls_file_collide_seg.m3u8_content_filename
        assert "a/init.mp4" not in content
        assert "b/init.mp4" not in content
        assert "a/seg.ts" not in content
        assert "b/seg.ts" not in content

    def test_web_files_filenames_differ(self, hls_file_collide_seg):
        filenames = [wf.filename for wf in hls_file_collide_seg.web_files]
        assert len(filenames) == len(set(filenames))

    def test_init_web_files_count(self, hls_file_collide_seg):
        inits = hls_file_collide_seg.init_web_files
        assert len(inits) == 2
        filenames = [wf.filename for wf in inits]
        assert len(filenames) == len(set(filenames))

    def test_download(self, hls_file_collide_seg):
        f = hls_file_collide_seg.download()
        assert f.exists()
        hls_file_collide_seg.unlink()
        assert not f.exists()


class TestHlsFileCollideInitQuery:
    @pytest.fixture
    def hls_file_collide_query(self, url_collide_init_query):
        return HlsFile(url_collide_init_query)

    def test_local_name_map_size(self, hls_file_collide_query):
        mapping = hls_file_collide_query._local_name_map
        assert len(mapping) == 4

    def test_init_filenames_differ(self, hls_file_collide_query):
        mapping = hls_file_collide_query._local_name_map
        init_uris = [
            s.init_section.absolute_uri
            for s in hls_file_collide_query.m3u8_obj.segments
        ]
        f0, f1 = (mapping[u] for u in init_uris)
        assert f0 != f1

    def test_init_web_files_count(self, hls_file_collide_query):
        inits = hls_file_collide_query.init_web_files
        assert len(inits) == 2
        filenames = [wf.filename for wf in inits]
        assert len(filenames) == len(set(filenames))

    def test_m3u8_content_filename_uses_local(self, hls_file_collide_query):
        content = hls_file_collide_query.m3u8_content_filename
        assert "init.mp4?token=a" not in content
        assert "init.mp4?token=b" not in content

    def test_download(self, hls_file_collide_query):
        f = hls_file_collide_query.download()
        assert f.exists()
        hls_file_collide_query.unlink()
        assert not f.exists()
