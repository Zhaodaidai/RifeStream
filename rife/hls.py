"""HLS GOP timing and muxer flags.

``hls_time`` is a minimum: a segment closes on the next IDR after that
duration. GOP is ``floor(output_fps * 2s)`` so media time never exceeds
2.000s and ``EXT-X-TARGETDURATION`` stays 2.

The playlist is a growing live list (``hls_list_size 0``, no EVENT).
FFmpeg ``temp_file`` publishes complete playlist and segment files.
"""

from pathlib import Path
from fractions import Fraction
import re
import uuid

HLS_SEGMENT_SECONDS = 2
STUB_PLAYLIST = (
    "#EXTM3U\n"
    "#EXT-X-VERSION:3\n"
    f"#EXT-X-TARGETDURATION:{HLS_SEGMENT_SECONDS}\n"
    "#EXT-X-MEDIA-SEQUENCE:0\n"
).encode("ascii")


def gop_frames(
    source_rate: Fraction,
    factor: int,
    segment_seconds: int = HLS_SEGMENT_SECONDS,
) -> int:
    return max(1, int(source_rate * factor * segment_seconds))


def force_key_frames_expr(gop: int) -> str:
    return f"expr:gte(n,n_forced*{gop})"


def encoder_gop(source_rate: Fraction, factor: int, requested: int) -> int:
    if requested > 0:
        return requested
    return gop_frames(source_rate, factor)


def hls_segment_pattern(playlist: Path) -> str:
    return str(playlist.with_name(f"seg_{uuid.uuid4().hex}_%d.ts"))


HLS_MUXER_FLAGS = "temp_file"


def hls_muxer_flags() -> str:
    return HLS_MUXER_FLAGS


def hls_output_files(playlist: Path) -> list[Path]:
    folder = playlist.parent
    temporary_playlist = playlist.with_name(playlist.name + ".tmp")
    return [
        path
        for path in folder.iterdir()
        if path in {playlist, temporary_playlist}
        or is_hls_segment(path)
    ]


def is_hls_segment(path: Path) -> bool:
    return bool(re.fullmatch(r"seg(?:[0-9]+|_[0-9a-f]{32}_[0-9]+)\.ts(?:\.tmp)?", path.name))


def clear_hls_output(playlist: Path) -> None:
    if not playlist.parent.is_dir():
        return
    for path in hls_output_files(playlist):
        path.unlink(missing_ok=True)


def reset_hls_output(playlist: Path) -> None:
    folder = playlist.parent
    folder.mkdir(parents=True, exist_ok=True)
    clear_hls_output(playlist)
    playlist.write_bytes(STUB_PLAYLIST)
