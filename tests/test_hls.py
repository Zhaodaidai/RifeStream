from fractions import Fraction
import errno
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from rife.hls import (
    encoder_gop,
    force_key_frames_expr,
    gop_frames,
    hls_muxer_flags,
    reset_hls_output,
)
from rife.hls_server import load_playlist, playlist_is_usable, retryable_os_error
from rife.paths import default_hls_dir, is_remote_path


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
            self.assertTrue(playlist.parent.is_dir())
            self.assertFalse(playlist.exists())
            self.assertFalse((playlist.parent / "seg0.ts").exists())

    def test_hls_flags_write_complete_files_before_publish(self) -> None:
        self.assertEqual(hls_muxer_flags(), "independent_segments+temp_file")

    def test_truncated_playlist_is_not_usable(self) -> None:
        complete = b"#EXTM3U\n#EXT-X-TARGETDURATION:2\n#EXTINF:2.000,\nseg0.ts\n"
        self.assertTrue(playlist_is_usable(complete))
        self.assertFalse(playlist_is_usable(complete.rstrip()[:-2]))

    def test_sharing_violation_is_retried_instead_of_missing(self) -> None:
        busy = OSError(errno.EACCES, "busy")
        busy.winerror = 32
        self.assertTrue(retryable_os_error(busy))
        self.assertFalse(retryable_os_error(FileNotFoundError("index.m3u8")))

    def test_playlist_loader_keeps_last_complete_copy(self) -> None:
        with tempfile.TemporaryDirectory() as folder:
            path = str(Path(folder) / "index.m3u8")
            complete = b"#EXTM3U\n#EXTINF:2.000,\nseg0.ts\n"
            Path(path).write_bytes(complete)
            self.assertEqual(load_playlist(path), complete)
            Path(path).write_bytes(b"#EXTM3U\n#EXTINF:2.000,\nseg1")
            self.assertEqual(load_playlist(path), complete)

    def test_unc_project_writes_hls_to_local_disk(self) -> None:
        self.assertTrue(is_remote_path(Path(r"\\192.168.10.100\game\rife")))
        self.assertTrue(is_remote_path(Path("//192.168.10.100/game/rife")))
        self.assertFalse(is_remote_path(Path("/mnt/game/rife")))
        local = default_hls_dir(Path("//192.168.10.100/game/rife"))
        self.assertNotEqual(local, Path("//192.168.10.100/game/rife") / ".hls")
        self.assertTrue(str(local).endswith(str(Path("rife") / "hls")))


if __name__ == "__main__":
    unittest.main()
