"""Live HLS timing shared by the NVENC GOP and MediaMTX muxer.

MediaMTX ``hlsSegmentDuration`` is a *minimum*: a segment closes on the next
IDR after that duration. HLS ``EXT-X-TARGETDURATION`` is the ceil() of the
longest segment. A 2.002s GOP therefore flips the playlist from 2s to 3s and
clients reload from the oldest slice.

Encoder GOP is therefore floor(output_fps * 2s) so media time never exceeds
2.000s, and the muxer minimum stays at 1s so it closes on that IDR instead of
waiting for the following one.
"""

from fractions import Fraction

# Keep these in sync with mediamtx.yml.
HLS_SEGMENT_SECONDS = 2
HLS_SEGMENT_MIN = "1s"
HLS_SEGMENT_COUNT = 8


def output_fps(source_rate: Fraction, factor: int) -> Fraction:
    return source_rate * factor


def gop_frames(
    source_rate: Fraction,
    factor: int,
    segment_seconds: int = HLS_SEGMENT_SECONDS,
) -> int:
    frames = output_fps(source_rate, factor) * segment_seconds
    return max(1, int(frames))


def force_key_frames_expr(gop: int) -> str:
    return f"expr:gte(n,n_forced*{gop})"


def encoder_gop(source_rate: Fraction, factor: int, requested: int) -> int:
    if requested > 0:
        return requested
    return gop_frames(source_rate, factor)
