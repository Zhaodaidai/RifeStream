from fractions import Fraction
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from rife.hls import as_event_playlist, encoder_gop, force_key_frames_expr, gop_frames


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

    def test_media_playlist_becomes_event_and_starts_at_zero(self) -> None:
        body = (
            "#EXTM3U\n"
            "#EXT-X-VERSION:10\n"
            "#EXT-X-TARGETDURATION:2\n"
            "#EXT-X-MEDIA-SEQUENCE:0\n"
            "#EXTINF:2.000,\n"
            "seg0.mp4\n"
        )
        rewritten = as_event_playlist(body)
        self.assertIn("#EXT-X-PLAYLIST-TYPE:EVENT", rewritten)
        self.assertIn("#EXT-X-START:TIME-OFFSET=0", rewritten)
        self.assertNotIn("#EXT-X-ENDLIST", rewritten)

    def test_ended_media_playlist_becomes_vod(self) -> None:
        body = (
            "#EXTM3U\n"
            "#EXT-X-MEDIA-SEQUENCE:0\n"
            "#EXTINF:2.000,\n"
            "seg0.mp4\n"
            "#EXT-X-ENDLIST\n"
        )
        rewritten = as_event_playlist(body)
        self.assertIn("#EXT-X-PLAYLIST-TYPE:VOD", rewritten)
        self.assertNotIn("#EXT-X-START:", rewritten)

    def test_master_playlist_is_left_alone(self) -> None:
        body = "#EXTM3U\n#EXT-X-STREAM-INF:BANDWIDTH=1000\nindex.m3u8\n"
        self.assertEqual(as_event_playlist(body), body)


if __name__ == "__main__":
    unittest.main()
