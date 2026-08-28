"""HLS timing shared by the NVENC GOP and MediaMTX muxer.

MediaMTX ``hlsSegmentDuration`` is a *minimum*: a segment closes on the next
IDR after that duration. HLS ``EXT-X-TARGETDURATION`` is the ceil() of the
longest segment. A 2.002s GOP therefore flips the playlist from 2s to 3s and
clients reload from the oldest slice.

Encoder GOP is therefore floor(output_fps * 2s) so media time never exceeds
2.000s, and the muxer minimum stays at 1s so it closes on that IDR instead of
waiting for the following one.

The published playlist is rewritten as EVENT (or VOD once ended) so players
play in order and do not chase the live edge after a stall. ``hlsSegmentCount``
must stay large enough that MediaMTX does not drop segments during a typical
title; otherwise EVENT would be invalid.
"""

from fractions import Fraction

# Keep these in sync with mediamtx.yml.
HLS_SEGMENT_SECONDS = 2
HLS_SEGMENT_MIN = "1s"
HLS_SEGMENT_COUNT = 7200
HLS_DIRECTORY = ".hls"


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


def as_event_playlist(body: str) -> str:
    """Mark a growing media playlist as EVENT so clients do not snap to live."""
    if "#EXT-X-MEDIA-SEQUENCE:" not in body:
        return body
    newline = "\r\n" if "\r\n" in body else "\n"
    lines = body.splitlines()
    ended = any(line.strip() == "#EXT-X-ENDLIST" for line in lines)
    playlist_type = "VOD" if ended else "EVENT"
    out: list[str] = []
    inserted = False
    for line in lines:
        if line.startswith("#EXT-X-PLAYLIST-TYPE:") or line.startswith("#EXT-X-START:"):
            continue
        out.append(line)
        if not inserted and line.startswith("#EXT-X-MEDIA-SEQUENCE:"):
            out.append(f"#EXT-X-PLAYLIST-TYPE:{playlist_type}")
            if not ended:
                out.append("#EXT-X-START:TIME-OFFSET=0")
            inserted = True
    result = newline.join(out)
    if body.endswith(("\n", "\r")):
        result += newline
    return result
