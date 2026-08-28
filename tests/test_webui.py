import json
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from rife.webui import (
    Playlist,
    display_title,
    hls_playlist_url,
    normalize_playlist_source,
    parse_sources,
    source_kind,
)


class PlaylistHelperTests(unittest.TestCase):
    def test_parse_sources_splits_lines_and_strips_quotes(self) -> None:
        text = "https://a.example/v.mp4\n\"/data/video/ep02.mkv\"\n\n  \nhttps://b.example/x.m3u8"
        self.assertEqual(
            parse_sources(text),
            [
                "https://a.example/v.mp4",
                "/data/video/ep02.mkv",
                "https://b.example/x.m3u8",
            ],
        )

    def test_http_source_keeps_url_and_title(self) -> None:
        url = "https://cdn.example/show/ep01.m3u8?token=1"
        self.assertEqual(normalize_playlist_source(url), url)
        self.assertEqual(source_kind(url), "url")
        self.assertEqual(display_title(url), "ep01.m3u8")

    def test_missing_file_is_rejected(self) -> None:
        with self.assertRaises(ValueError):
            normalize_playlist_source("/definitely/missing/rife-test.mkv")

    def test_playlist_prev_next_and_current(self) -> None:
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "playlist.json"
            playlist = Playlist(path)
            first = Path(folder) / "a.mkv"
            second = Path(folder) / "b.mkv"
            first.write_bytes(b"")
            second.write_bytes(b"")
            playlist.add_sources([str(first), str(second), "https://example.com/c.mp4"])
            self.assertEqual(playlist.current().title, "a.mkv")

            playlist.select(offset=1)
            self.assertEqual(playlist.current().title, "b.mkv")
            self.assertTrue(playlist.snapshot()["has_prev"])
            self.assertTrue(playlist.snapshot()["has_next"])

            playlist.select(offset=1)
            self.assertEqual(playlist.current().title, "c.mp4")
            self.assertFalse(playlist.snapshot()["has_next"])
            with self.assertRaises(ValueError):
                playlist.select(offset=1)

            saved = json.loads(path.read_text(encoding="utf-8"))
            self.assertEqual(len(saved["items"]), 3)


class HlsUrlTests(unittest.TestCase):
    @patch("rife.webui.lan_ipv4", return_value="192.168.1.8")
    def test_hls_url_always_uses_lan_ip(self, _lan_ipv4) -> None:
        expected = "http://192.168.1.8:8888/rife/index.m3u8"
        self.assertEqual(hls_playlist_url("127.0.0.1:10000"), expected)
        self.assertEqual(hls_playlist_url("localhost:10000"), expected)
        self.assertEqual(hls_playlist_url("example.local:10000"), expected)
        self.assertEqual(hls_playlist_url(None), expected)


if __name__ == "__main__":
    unittest.main()
