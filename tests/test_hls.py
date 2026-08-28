from fractions import Fraction
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from rife.hls import encoder_gop, force_key_frames_expr, gop_frames


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


if __name__ == "__main__":
    unittest.main()
