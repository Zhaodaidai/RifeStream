import io
import json
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from rife.webui import (
    PLAYBACK,
    Playlist,
    SkipSettings,
    clamp_seek,
    display_title,
    effective_start,
    encode_duration,
    estimate_position,
    hls_playlist_url,
    normalize_playlist_source,
    outro_reached,
    parse_settings,
    parse_sources,
    playback_snapshot,
    relay_stream_output,
    reset_playback,
    source_kind,
    stream_command,
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

    def test_skip_settings_persist_and_survive_clear(self) -> None:
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "playlist.json"
            playlist = Playlist(path)
            playlist.update_settings(
                {"intro": 90, "outro": 75, "skip_intro": True, "skip_outro": True}
            )
            saved = json.loads(path.read_text(encoding="utf-8"))
            self.assertEqual(saved["settings"]["intro"], 90)
            self.assertTrue(saved["settings"]["skip_intro"])

            first = Path(folder) / "a.mkv"
            first.write_bytes(b"")
            playlist.add_sources([str(first)])
            playlist.clear()
            self.assertEqual(playlist.settings().intro, 90)
            self.assertEqual(playlist.settings().outro, 75)
            self.assertTrue(playlist.settings().skip_outro)
            self.assertEqual(playlist.snapshot()["items"], [])

            reloaded = Playlist(path)
            self.assertEqual(reloaded.settings().intro, 90)
            self.assertTrue(reloaded.settings().skip_intro)

    def test_parse_settings_rejects_negative_when_strict(self) -> None:
        with self.assertRaises(ValueError):
            parse_settings({"intro": -1}, strict=True)
        loaded = parse_settings({"intro": -1, "skip_intro": True})
        self.assertEqual(loaded.intro, 0)
        self.assertTrue(loaded.skip_intro)


class SkipWindowTests(unittest.TestCase):
    def test_effective_start_skips_intro_from_zero(self) -> None:
        settings = SkipSettings(intro=88, skip_intro=True)
        self.assertEqual(effective_start(0, settings), 88)
        self.assertEqual(effective_start(12, settings), 12)
        self.assertEqual(effective_start(0, SkipSettings(intro=88, skip_intro=False)), 0)

    def test_encode_duration_stops_before_outro(self) -> None:
        settings = SkipSettings(outro=90, skip_outro=True)
        self.assertEqual(encode_duration(88, 1200, settings), 1022)
        self.assertEqual(encode_duration(0, 80, settings), 0)
        self.assertEqual(encode_duration(10, 1200, SkipSettings(outro=90)), 0)

    def test_outro_reached(self) -> None:
        settings = SkipSettings(outro=90, skip_outro=True)
        self.assertFalse(outro_reached(1000, 1200, settings))
        self.assertTrue(outro_reached(1110, 1200, settings))
        self.assertFalse(outro_reached(1110, 1200, SkipSettings(outro=90)))


class PlaybackTests(unittest.TestCase):
    def setUp(self) -> None:
        reset_playback()

    def tearDown(self) -> None:
        reset_playback()

    def test_stream_command_includes_start(self) -> None:
        command = stream_command("https://example.com/v.mp4", "Title", 42.5)
        self.assertEqual(command[command.index("--start") + 1], "42.5")
        self.assertEqual(command[:3], [sys.executable, "-u", command[2]])
        self.assertNotIn("--start", stream_command("https://example.com/v.mp4", None, 0))
        timed = stream_command("https://example.com/v.mp4", None, 10, 500)
        self.assertEqual(timed[timed.index("--duration") + 1], "500")

    def test_position_advances_while_streaming(self) -> None:
        self.assertEqual(estimate_position(10, 100.0, 115.0, 120.0, True), 25.0)
        self.assertEqual(estimate_position(10, 100.0, 300.0, 40.0, True), 40.0)
        self.assertEqual(estimate_position(10, 100.0, 115.0, 120.0, False), 10.0)

    def test_clamp_seek_rejects_negative_and_caps_duration(self) -> None:
        self.assertEqual(clamp_seek(15, 100), 15)
        self.assertEqual(clamp_seek(100, 100), 99.75)
        with self.assertRaises(ValueError):
            clamp_seek(-1, 100)

    def test_snapshot_uses_stream_status_when_webui_has_no_clock(self) -> None:
        with tempfile.TemporaryDirectory() as folder:
            status = Path(folder) / "status.json"
            status.write_text(
                json.dumps({"duration": 200, "start": 50, "started_at": 1000}),
                encoding="utf-8",
            )
            with patch("rife.webui.STREAM_STATUS_FILE", status):
                payload = playback_snapshot(True, True, now=1010)
        self.assertEqual(payload["duration"], 200)
        self.assertEqual(payload["position"], 60)
        self.assertTrue(payload["seekable"])
        self.assertEqual(PLAYBACK.duration, 200)

    def test_snapshot_is_not_seekable_without_duration(self) -> None:
        payload = playback_snapshot(False, True, now=0)
        self.assertFalse(payload["seekable"])
        self.assertIsNone(payload["duration"])

    def test_relay_prints_stream_errors_to_stderr(self) -> None:
        pipe = io.StringIO(
            "Pipeline   : VSPipe\nError: ffprobe could not inspect the input video\n"
        )
        stderr = io.StringIO()
        with tempfile.TemporaryDirectory() as folder:
            log = Path(folder) / "webui.log"
            playlist = Playlist(Path(folder) / "playlist.json")
            with patch("rife.webui.WEBUI_LOG_FILE", log), patch(
                "rife.webui.sys.stderr", stderr
            ), patch("rife.webui.PLAYLIST", playlist):
                relay_stream_output(pipe, "\nPlay: https://example.com/v.mp4 start=0\n")
            self.assertIn("Error: ffprobe could not inspect the input video", log.read_text(encoding="utf-8"))
        self.assertIn("Play: https://example.com/v.mp4", stderr.getvalue())
        self.assertIn("Error: ffprobe could not inspect the input video", stderr.getvalue())
        self.assertEqual(
            playlist.snapshot()["last_error"],
            "Error: ffprobe could not inspect the input video",
        )


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
