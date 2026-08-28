"""HLS timing shared by the NVENC GOP and the FFmpeg HLS muxer.

``hls_time`` is a *minimum*: a segment closes on the next IDR after that
duration. HLS ``EXT-X-TARGETDURATION`` is the ceil() of the longest segment.
A 2.002s GOP therefore flips the playlist from 2s to 3s and clients reload.

Encoder GOP is therefore floor(output_fps * 2s) so media time never exceeds
2.000s. The playlist is FFmpeg ``event`` type so players play in order and
do not chase a live edge after a stall.
"""

from fractions import Fraction
from pathlib import Path

HLS_SEGMENT_SECONDS = 2


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


def hls_segment_pattern(playlist: Path) -> str:
    return str(playlist.with_name("seg%d.ts"))


def hls_muxer_flags() -> str:
    # temp_file writes the playlist/segment to *.tmp and renames when complete.
    # HLS output is on local disk, so rename is reliable; in-place writes let
    # players snapshot a truncated playlist and then never request the next .ts.
    return "independent_segments+temp_file"


def reset_hls_output(playlist: Path) -> None:
    folder = playlist.parent
    folder.mkdir(parents=True, exist_ok=True)
    for path in folder.iterdir():
        if path.suffix.lower() in {".m3u8", ".ts", ".tmp"}:
            path.unlink(missing_ok=True)
