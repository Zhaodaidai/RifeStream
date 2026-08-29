from fractions import Fraction
import os
import sys
import tempfile
import threading
import time
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from rife.hls import (
    encoder_gop,
    force_key_frames_expr,
    gop_frames,
    hls_muxer_flags,
    reset_hls_output,
)
from rife.hls_server import wait_hls_bytes
from rife.paths import windows_hls_dir, windows_rife_dir


class HlsTimingTests(unittest.TestCase):
    def test_integer_fps_gop_is_exactly_two_seconds(self) -> None:
        self.assertEqual(gop_frames(Fraction(25), 2), 100)
        self.assertEqual(100 / 50, 2.0)

    def test_ntsc_gop_stays_at_or_under_two_seconds(self) -> None:
        rate = Fraction(24_000, 1001)
        gop = gop_frames(rate, 2)
        self.assertEqual(gop, 95)
        self.assertLessEqual(gop / float(rate * 2), 2.0)
        self.assertGreater(gop / float(rate * 2), 1.9)

    def test_requested_gop_overrides_the_two_second_default(self) -> None:
        self.assertEqual(encoder_gop(Fraction(25), 2, 48), 48)
        self.assertEqual(force_key_frames_expr(48), "expr:gte(n,n_forced*48)")

    def test_reset_hls_output_clears_old_segments(self) -> None:
        with tempfile.TemporaryDirectory() as folder:
            playlist = Path(folder) / "rife" / "index.m3u8"
            reset_hls_output(playlist)
            (playlist.parent / "seg0.ts").write_bytes(b"old")
            playlist.write_text("#EXTM3U\n", encoding="utf-8")
            reset_hls_output(playlist)
            text = playlist.read_bytes()
            self.assertTrue(playlist.parent.is_dir())
            self.assertTrue(text.startswith(b"#EXTM3U"))
            self.assertNotIn(b"#EXT-X-ENDLIST", text)
            self.assertFalse((playlist.parent / "seg0.ts").exists())

    def test_wait_hls_bytes_blocks_until_the_next_segment_exists(self) -> None:
        with tempfile.TemporaryDirectory() as folder:
            path = str(Path(folder) / "seg1.ts")

            def writer() -> None:
                time.sleep(0.2)
                Path(path).write_bytes(b"tsdata")

            threading.Thread(target=writer, daemon=True).start()
            self.assertEqual(wait_hls_bytes(path, timeout=2.0), b"tsdata")

    def test_hls_flags_write_complete_files_before_publish(self) -> None:
        self.assertEqual(hls_muxer_flags(), "independent_segments+temp_file")

    def test_wait_hls_bytes_times_out_when_the_file_never_appears(self) -> None:
        with tempfile.TemporaryDirectory() as folder:
            path = str(Path(folder) / "missing.ts")
            with self.assertRaises(FileNotFoundError):
                wait_hls_bytes(path, timeout=0.15)

    def test_windows_hls_dir_uses_localappdata(self) -> None:
        with patch.dict(os.environ, {"LOCALAPPDATA": "/tmp/appdata"}):
            self.assertEqual(windows_rife_dir(), Path("/tmp/appdata") / "rife")
            self.assertEqual(windows_hls_dir(), Path("/tmp/appdata") / "rife" / "hls")

    def test_windows_engine_dir_stays_on_local_ntfs(self) -> None:
        with patch.dict(os.environ, {"LOCALAPPDATA": "/tmp/appdata"}):
            self.assertEqual(
                windows_rife_dir() / "engines",
                Path("/tmp/appdata") / "rife" / "engines",
            )


if __name__ == "__main__":
    unittest.main()
