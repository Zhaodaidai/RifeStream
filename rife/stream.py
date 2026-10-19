import argparse
from dataclasses import dataclass
from contextlib import nullcontext
from fractions import Fraction
import json
import math
import os
from pathlib import Path
import shutil
import signal
import threading
import subprocess
import tempfile
import time
import sys
from urllib.parse import urlsplit, urlunsplit

from rife.sessions import SessionStore, atomic_json
from rife.performance import Concurrency, PerformanceRun, positive_int

WORKER_SESSION_ID: str | None = None

from rife.hls import (
    HLS_MUXER_FLAGS,
    HLS_SEGMENT_SECONDS,
    clear_hls_output,
    encoder_gop,
    force_key_frames_expr,
    hls_segment_pattern,
    reset_hls_output,
)
from rife.hls_server import ensure as ensure_hls_server
from rife.paths import (
    ENGINE_DIR,
    FFMPEG,
    FFPROBE,
    HLS_PLAYLIST,
    HTTP_SCHEMES,
    PROCESS_FLAGS,
    RIFE_SCRIPT,
    ROOT,
    STREAM_PID_FILE,
    STREAM_STATUS_FILE,
    VSPIPE,
    capture,
    ensure_var,
    is_http_source,
    read_pid,
    replace_existing_stream,
    windows_rife_dir,
)


DEFAULT_USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/138.0.0.0 Safari/537.36"
)
FFMPEG_BASE = [str(FFMPEG), "-hide_banner", "-nostdin", "-loglevel", "warning"]
BITMAP_SUBTITLE_CODECS = {
    "dvd_subtitle",
    "dvb_subtitle",
    "dvb_teletext",
    "hdmv_pgs_subtitle",
    "xsub",
}
TEXT_SUBTITLE_CODECS = {
    "arib_caption",
    "ass",
    "eia_608",
    "jacosub",
    "microdvd",
    "mpl2",
    "mov_text",
    "sami",
    "srt",
    "ssa",
    "stl",
    "subrip",
    "subviewer",
    "text",
    "ttml",
    "webvtt",
}


@dataclass
class MediaInfo:
    frame_rate: Fraction
    width: int
    height: int
    duration: float | None


@dataclass(frozen=True)
class Timeline:
    """One CFR timebase shared by decoding, RIFE, audio, subtitles and HLS.

    A duration of zero means no explicit FFmpeg limit, not an empty clip.
    The raw pipe retains its historical one-frame safety margin. Unknown
    lengths retain the large BlankClip ceiling; EOF policy is unchanged.
    """

    source_rate: Fraction
    factor: int
    start: float
    requested_duration: float
    duration: float | None

    @classmethod
    def resolve(cls, source_rate: Fraction, factor: int, start: float,
                duration: float, media_duration: float | None) -> "Timeline":
        rate = Fraction(source_rate)
        start_value = float(start)
        requested = float(duration)
        values = [start_value, requested]
        if media_duration is not None:
            values.append(media_duration)
        if not all(math.isfinite(value) and value >= 0 for value in values):
            raise ValueError("Timeline times must be finite and non-negative")
        if rate <= 0 or factor <= 0 or start_value < 0 or requested < 0:
            raise ValueError("Timeline requires positive FPS/factor and non-negative start/duration")
        effective = requested if requested > 0 else (
            max(0.0, media_duration - start_value)
            if media_duration is not None else None
        )
        return cls(rate, factor, start_value, requested, effective)

    @property
    def output_rate(self) -> Fraction:
        return self.source_rate * self.factor

    @property
    def pipe_frames(self) -> int:
        if self.duration is None:
            return 2_000_000_000
        return max(1, math.floor(self.duration * float(self.source_rate)) - 1)

    @property
    def start_text(self) -> str:
        return format(float(self.start), ".12g")

    @property
    def duration_text(self) -> str:
        return format(float(self.requested_duration), ".12g")


@dataclass(frozen=True)
class SubtitleTrack:
    index: int
    codec: str
    language: str | None = None
    title: str | None = None
    default: bool = False

    @property
    def label(self) -> str:
        parts = [f"s:{self.index}", self.codec]
        if self.language:
            parts.append(self.language)
        if self.title:
            parts.append(self.title)
        return " ".join(parts)


@dataclass
class StreamInput:
    video: str
    audio: str | None
    headers: list[str]
    title: str | None
    info: MediaInfo
    rate: Fraction
    subtitle: str | None = None
    subtitle_index: int = 0
    subtitle_label: str | None = None
    subtitle_fontsdir: str | None = None
    subtitle_workdir: str | None = None

    @property
    def is_network(self) -> bool:
        return is_http_source(self.video)


def build_timeline(source: StreamInput, args: argparse.Namespace) -> Timeline:
    return Timeline.resolve(
        source.rate, getattr(args, "factor", 2), args.start, args.duration,
        source.info.duration,
    )


def normalize_source(source: str, name: str) -> str:
    parsed = urlsplit(source)
    if parsed.scheme.lower() in HTTP_SCHEMES:
        if not parsed.netloc:
            raise ValueError(f"{name} is not a valid HTTP URL")
        return source
    path = Path(source).expanduser().resolve()
    if not path.is_file():
        raise ValueError(f"{name} file not found: {path}")
    return str(path)


def normalize_headers(values: list[str]) -> list[str]:
    headers: dict[str, tuple[str, str]] = {}
    for value in values:
        name, separator, header_value = value.partition(":")
        name = name.strip()
        header_value = header_value.strip()
        if not separator or not name or not header_value:
            raise ValueError(f"Invalid HTTP header: {value}")
        headers[name.lower()] = (name, header_value)
    return [f"{name}: {value}" for name, value in headers.values()]


def merge_headers(*groups: list[str]) -> list[str]:
    return normalize_headers([header for group in groups for header in group])


def scaled_video_size(info: MediaInfo, max_height: int) -> tuple[int, int, int, int]:
    width = info.width // 2 * 2
    height = info.height // 2 * 2
    if max_height and height > max_height:
        height = max_height // 2 * 2
        width = max(2, int(info.width * height / info.height) // 2 * 2)
    # Pad width to 32 so 1910x1080 reuses a 1920x1080 TensorRT engine.
    padded_width = max(2, (width + 31) // 32 * 32)
    return width, height, padded_width, height


def video_size(info: MediaInfo, max_height: int) -> tuple[int, int]:
    _, _, width, height = scaled_video_size(info, max_height)
    return width, height


def decoder_scale_filter(
    info: MediaInfo, max_height: int, rate: Fraction
) -> str:
    scale_width, scale_height, out_width, out_height = scaled_video_size(
        info, max_height
    )
    rate_text = f"{rate.numerator}/{rate.denominator}"
    filters = [
        f"scale_cuda={scale_width}:{scale_height}:format=yuv420p:interp_algo=lanczos",
        "hwdownload",
        "format=yuv420p",
    ]
    if out_width != scale_width or out_height != scale_height:
        filters.append(f"pad={out_width}:{out_height}:0:0")
    filters.append(f"fps={rate_text}")
    return ",".join(filters)


HTTP_RECONNECT_OPTIONS = [
    # EOF 对点播和已结束的 HLS 媒体是正常状态，不把它当成网络故障重连。
    "-reconnect",
    "1",
    "-reconnect_streamed",
    "1",
    "-reconnect_on_network_error",
    "1",
    "-reconnect_delay_max",
    "2",
    "-icy",
    "0",
]


def ffmpeg_input_options(
    source: str, headers: list[str], proxy: str | None
) -> list[str]:
    options: list[str] = []
    parsed = urlsplit(source)
    if parsed.scheme.lower() in HTTP_SCHEMES:
        options.extend(HTTP_RECONNECT_OPTIONS)
        # HLS demuxer only. The HTTP protocol used for .mp4 rejects this option.
        if parsed.path.lower().endswith(".m3u8"):
            options.extend(["-http_persistent", "0"])
    if headers:
        options.extend(["-headers", "\r\n".join(headers) + "\r\n"])
    if proxy:
        options.extend(["-http_proxy", proxy])
    return options


def option_args(*pairs: tuple[object, ...]) -> list[str]:
    return [str(value) for pair in pairs for value in pair]


def safe_float(value: object) -> float | None:
    try:
        result = float(value)
    except (TypeError, ValueError):
        return None
    return result if math.isfinite(result) and result >= 0 else None


def probe_media(
    input_source: str, headers: list[str], proxy: str | None
) -> tuple[MediaInfo, list[SubtitleTrack]]:
    command = [
        str(FFPROBE),
        "-v",
        "error",
        *ffmpeg_input_options(input_source, headers, proxy),
        "-show_entries",
        "stream=codec_type,width,height,avg_frame_rate,r_frame_rate,duration,"
        "codec_name,disposition:stream_tags=language,title:format=duration",
        "-of",
        "json",
        input_source,
    ]
    result = capture(command)
    if result.returncode != 0:
        detail = result.stderr.strip()
        if detail:
            detail = detail.replace(input_source, display_source(input_source))
            detail = detail.splitlines()[-1]
            raise RuntimeError(f"ffprobe could not inspect the input video: {detail}")
        raise RuntimeError("ffprobe could not inspect the input video")
    try:
        document = json.loads(result.stdout)
        streams = document["streams"]
        stream = next(item for item in streams if item.get("codec_type") == "video")
        width = int(stream["width"])
        height = int(stream["height"])
        for key in ("avg_frame_rate", "r_frame_rate"):
            rate = Fraction(stream.get(key, "0/1"))
            if rate > 0:
                duration = safe_float(stream.get("duration"))
                if duration is None:
                    duration = safe_float(document.get("format", {}).get("duration"))
                subtitle_document = {
                    "streams": [
                        item for item in streams if item.get("codec_type") == "subtitle"
                    ]
                }
                return MediaInfo(rate, width, height, duration), parse_subtitle_tracks(
                    subtitle_document
                )
    except (
        KeyError,
        IndexError,
        StopIteration,
        TypeError,
        ValueError,
        ZeroDivisionError,
    ) as exc:
        raise RuntimeError("ffprobe returned invalid video metadata") from exc
    raise RuntimeError("Input frame rate is unavailable; pass --source-fps")


def is_text_subtitle(codec: str) -> bool:
    name = codec.lower()
    if name in BITMAP_SUBTITLE_CODECS:
        return False
    return name in TEXT_SUBTITLE_CODECS


def escape_filter_path(path: str) -> str:
    escaped = path.replace("\\", "/")
    for character in (":", "'", "[", "]", ",", ";"):
        escaped = escaped.replace(character, f"\\{character}")
    return escaped


def subtitle_filter(
    path: str,
    stream_index: int,
    start: float,
    original_size: tuple[int, int],
    fontsdir: str | None = None,
) -> str:
    width, height = original_size
    overlay = (
        f"subtitles='{escape_filter_path(path)}':si={stream_index}"
        f":original_size={width}x{height}"
    )
    if fontsdir:
        overlay += f":fontsdir='{escape_filter_path(fontsdir)}'"
    if start <= 0:
        return overlay
    offset = format(start, ".12g")
    return f"setpts=PTS+{offset}/TB,{overlay},setpts=PTS-STARTPTS"


@dataclass(frozen=True)
class ResolvedSubtitles:
    path: str | None = None
    index: int = 0
    label: str | None = None
    fontsdir: str | None = None
    workdir: str | None = None


def subtitle_cache_dir() -> Path:
    base = windows_rife_dir() / "subs" if os.name == "nt" else ROOT / ".subs"
    base.mkdir(parents=True, exist_ok=True)
    return base


def extract_embedded_subtitles_command(
    video: str,
    stream_index: int,
    headers: list[str],
    proxy: str | None,
    ass_path: str,
    dump_fonts: bool,
) -> list[str]:
    command = [*FFMPEG_BASE]
    if dump_fonts:
        command.extend(["-dump_attachment:t", ""])
    command.extend(ffmpeg_input_options(video, headers, proxy))
    command.extend(
        [
            "-i",
            video,
            "-map",
            f"0:s:{stream_index}",
            "-vn",
            "-an",
            "-c:s",
            "ass",
            "-y",
            ass_path,
        ]
    )
    return command


def extract_embedded_subtitles(
    video: str,
    stream_index: int,
    headers: list[str],
    proxy: str | None,
) -> tuple[str, str | None, str]:
    workdir = Path(tempfile.mkdtemp(prefix="subs-", dir=str(subtitle_cache_dir())))
    ass_path = workdir / "track.ass"
    fontsdir = workdir / "fonts"
    fontsdir.mkdir()

    def extracted() -> bool:
        return ass_path.is_file() and ass_path.stat().st_size > 0

    result = capture(
        extract_embedded_subtitles_command(
            video, stream_index, headers, proxy, str(ass_path), True
        ),
        cwd=fontsdir,
    )
    if not extracted():
        result = capture(
            extract_embedded_subtitles_command(
                video, stream_index, headers, proxy, str(ass_path), False
            )
        )
    if not extracted():
        shutil.rmtree(workdir, ignore_errors=True)
        detail = result.stderr.strip().splitlines()
        raise RuntimeError(
            "Could not extract network subtitles"
            + (f": {detail[-1]}" if detail else "")
        )
    font_path = str(fontsdir) if any(fontsdir.iterdir()) else None
    return str(ass_path), font_path, str(workdir)


def parse_subtitle_tracks(document: object) -> list[SubtitleTrack]:
    if not isinstance(document, dict):
        return []
    tracks: list[SubtitleTrack] = []
    streams = document.get("streams")
    if not isinstance(streams, list):
        return []
    for position, stream in enumerate(streams):
        if not isinstance(stream, dict):
            continue
        codec = stream.get("codec_name")
        if not isinstance(codec, str) or not codec:
            continue
        disposition = stream.get("disposition")
        tags = stream.get("tags")
        language = None
        title = None
        if isinstance(tags, dict):
            raw_language = tags.get("language")
            raw_title = tags.get("title")
            language = raw_language if isinstance(raw_language, str) else None
            title = raw_title if isinstance(raw_title, str) else None
        tracks.append(
            SubtitleTrack(
                position,
                codec,
                language,
                title,
                bool(isinstance(disposition, dict) and disposition.get("default")),
            )
        )
    return tracks


def _subtitle_language(track: SubtitleTrack) -> str:
    return (track.language or "").strip().lower().replace("_", "-")


def _subtitle_blob(track: SubtitleTrack) -> str:
    return " ".join(
        part for part in (_subtitle_language(track), track.title or "") if part
    ).lower()


def is_simplified_chinese(track: SubtitleTrack) -> bool:
    language = _subtitle_language(track)
    if language in {"zh-cn", "zh-sg", "zh-hans", "zh-chs", "chi-hans", "cmn-hans"}:
        return True
    if language.startswith(("zh-hans", "zh-cn", "zh-sg", "zh-chs")):
        return True
    blob = _subtitle_blob(track)
    markers = (
        "简体",
        "简中",
        "简日",
        "简英",
        "simplified",
        "chs",
        "gb2312",
        "gbk",
    )
    return any(marker in blob for marker in markers)


def is_chinese_subtitle(track: SubtitleTrack) -> bool:
    if is_simplified_chinese(track):
        return True
    language = _subtitle_language(track)
    if language in {"chi", "zho", "zh", "cmn", "yue", "zh-tw", "zh-hk", "zh-mo", "zh-hant", "zh-cht", "chi-hant"}:
        return True
    if language.startswith(("zh", "chi", "zho", "cmn", "yue")):
        return True
    blob = _subtitle_blob(track)
    markers = (
        "中文",
        "汉语",
        "漢語",
        "国语",
        "國語",
        "普通话",
        "粤语",
        "粵語",
        "繁体",
        "繁體",
        "繁中",
        "双语",
        "雙語",
        "中日",
        "中英",
        "chinese",
        "traditional",
        "big5",
        "cht",
        "zh-han",
    )
    return any(marker in blob for marker in markers)


def pick_subtitle_stream(
    tracks: list[SubtitleTrack], requested: int | None
) -> SubtitleTrack | None:
    if requested is not None:
        if requested < 0 or requested >= len(tracks):
            raise ValueError(f"Subtitle stream {requested} is not in the file")
        track = tracks[requested]
        if not is_text_subtitle(track.codec):
            raise ValueError(
                f"Subtitle stream {requested} is {track.codec}; "
                "bitmap subtitles cannot be burned in"
            )
        return track
    text = [track for track in tracks if is_text_subtitle(track.codec)]
    chinese = [track for track in text if is_chinese_subtitle(track)]
    if chinese:
        simplified = [track for track in chinese if is_simplified_chinese(track)]
        return simplified[0] if simplified else chinese[0]
    return next((track for track in text if track.default), text[0] if text else None)


def probe_subtitle_tracks(
    input_source: str, headers: list[str], proxy: str | None
) -> list[SubtitleTrack]:
    command = [
        str(FFPROBE),
        "-v",
        "error",
        *ffmpeg_input_options(input_source, headers, proxy),
        "-select_streams",
        "s",
        "-show_entries",
        "stream=codec_name,disposition:stream_tags=language,title",
        "-of",
        "json",
        input_source,
    ]
    result = capture(command)
    if result.returncode != 0:
        return []
    try:
        return parse_subtitle_tracks(json.loads(result.stdout))
    except json.JSONDecodeError:
        return []


def resolve_subtitles(
    video: str,
    args: argparse.Namespace,
    headers: list[str],
    proxy: str | None,
    tracks: list[SubtitleTrack] | None = None,
) -> ResolvedSubtitles:
    requested = args.subtitle_stream
    explicit = bool(args.subtitles) or requested is not None
    empty = ResolvedSubtitles()
    if args.no_subtitles:
        if explicit:
            raise ValueError("Cannot combine --no-subtitles with subtitle options")
        return empty
    subtitle_file = (
        normalize_source(args.subtitles, "Subtitles") if args.subtitles else None
    )
    if subtitle_file and is_http_source(subtitle_file):
        raise ValueError("Subtitle files must be local")
    if subtitle_file is None:
        subtitle_file = video
    probe_headers = headers if subtitle_file == video else []
    if tracks is None or subtitle_file != video:
        tracks = probe_subtitle_tracks(subtitle_file, probe_headers, proxy)
    try:
        track = pick_subtitle_stream(tracks, requested)
    except ValueError:
        if explicit:
            raise
        return empty
    if track is None:
        if explicit:
            raise ValueError("No text subtitle stream found")
        return empty
    if is_http_source(subtitle_file):
        try:
            path, fontsdir, workdir = extract_embedded_subtitles(
                subtitle_file, track.index, probe_headers, proxy
            )
        except RuntimeError as exc:
            if explicit:
                raise
            print(f"Warning    : {exc}", file=sys.stderr, flush=True)
            return empty
        return ResolvedSubtitles(path, 0, track.label, fontsdir, workdir)
    return ResolvedSubtitles(subtitle_file, track.index, track.label)


def headers_from_ytdlp(value: object) -> list[str]:
    if not isinstance(value, dict):
        return []
    return normalize_headers(
        [
            f"{name}: {header}"
            for name, header in value.items()
            if isinstance(name, str) and isinstance(header, str)
        ]
    )


def resolve_ytdlp(
    source: str,
    format_selector: str,
    proxy: str | None,
    headers: list[str],
) -> tuple[str, str | None, list[str], str | None]:
    command = [
        sys.executable,
        "-m",
        "yt_dlp",
        "--dump-single-json",
        "--no-playlist",
        "--no-warnings",
        "--format",
        format_selector,
    ]
    if proxy:
        command.extend(["--proxy", proxy])
    for header in headers:
        command.extend(["--add-headers", header])
    command.append(source)
    result = capture(command)
    if result.returncode != 0:
        detail = result.stderr.strip().splitlines()
        raise RuntimeError(f"yt-dlp failed: {detail[-1] if detail else 'unknown error'}")
    try:
        info = json.loads(result.stdout)
    except json.JSONDecodeError as exc:
        raise RuntimeError("yt-dlp returned invalid JSON") from exc

    formats = info.get("requested_formats") or info.get("requested_downloads") or []
    video_format = next(
        (item for item in formats if item.get("vcodec") not in (None, "none")), None
    )
    audio_format = next(
        (
            item
            for item in formats
            if item.get("acodec") not in (None, "none")
            and item.get("vcodec") in (None, "none")
        ),
        None,
    )
    video_source = (video_format or info).get("url")
    audio_source = audio_format.get("url") if audio_format else None
    if not isinstance(video_source, str):
        raise RuntimeError("yt-dlp did not return a playable video URL")
    resolved_headers = merge_headers(
        headers_from_ytdlp(info.get("http_headers")),
        headers_from_ytdlp((video_format or {}).get("http_headers")),
        headers_from_ytdlp((audio_format or {}).get("http_headers")),
        headers,
    )
    title = info.get("title") if isinstance(info.get("title"), str) else None
    return video_source, audio_source, resolved_headers, title


def display_source(source: str) -> str:
    if not is_http_source(source):
        return source
    parsed = urlsplit(source)
    return urlunsplit((parsed.scheme, parsed.netloc, parsed.path, "", ""))


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="VSPipe RIFE -> standalone FFmpeg NVENC -> HLS"
    )
    parser.add_argument("input", help="local file or HTTP video URL")
    parser.add_argument("--session-id", help=argparse.SUPPRESS)
    parser.add_argument("--audio-input", help="separate local file or HTTP audio URL")
    parser.add_argument(
        "--http-header-field",
        action="append",
        default=[],
        metavar="NAME:VALUE",
        help="HTTP input header; may be repeated",
    )
    parser.add_argument("--http-proxy", help="HTTP proxy used by FFmpeg inputs")
    parser.add_argument("--ytdl-proxy", help="proxy used while yt-dlp resolves a page")
    parser.add_argument("--ytdl-format", help="yt-dlp format selector from MPV")
    parser.add_argument("--title", help="display title supplied by External Player")
    parser.add_argument("--publish-url", default=str(HLS_PLAYLIST), help="HLS playlist path")
    parser.add_argument("--factor", type=int, choices=(2, 3, 4), default=2)
    parser.add_argument("--max-height", type=int, default=1080)
    parser.add_argument("--gpu", type=int, choices=(0, 1, 2), default=0)
    parser.add_argument("--gpu-threads", type=int, choices=(1, 2, 3, 4), default=3)
    parser.add_argument("--vs-requests", type=positive_int, default=None,
                        help="VSPipe concurrent frame requests; default: --gpu-threads")
    parser.add_argument("--vs-threads", type=positive_int, default=None,
                        help="VapourSynth workers; default: max(2, --gpu-threads)")
    parser.add_argument("--raw-prefetch", type=positive_int, default=None,
                        help="raw frame prefetch limit, independent of --vs-threads")
    parser.add_argument("--perf-report", metavar="REPORT.json", default=None,
                        help="opt-in performance report; refuses to overwrite existing files")
    parser.add_argument("--scene-mode", type=int, choices=(0, 1, 2), default=1)
    parser.add_argument("--workspace-mib", type=int, default=0)
    parser.add_argument("--source-fps", type=float, default=0.0)
    parser.add_argument(
        "--quality",
        type=int,
        choices=range(1, 31),
        default=12,
        help="NVENC constant quality; lower is closer to visually lossless",
    )
    parser.add_argument(
        "--gop",
        type=int,
        default=0,
        help="keyframe interval in output frames; 0 = floor(output_fps * 2s)",
    )
    parser.add_argument(
        "--audio-codec",
        choices=("libopus", "aac"),
        default="aac",
        help="HLS MPEG-TS carries AAC; libopus may not play in HLS players",
    )
    parser.add_argument("--no-audio", action="store_true")
    parser.add_argument(
        "--subtitles",
        help="local subtitle file; omit to burn the first text track in the input",
    )
    parser.add_argument(
        "--subtitle-stream",
        type=int,
        default=None,
        metavar="INDEX",
        help="0-based subtitle stream index to burn in",
    )
    parser.add_argument(
        "--no-subtitles",
        action="store_true",
        help="do not burn subtitles into the video",
    )
    parser.add_argument("--start", type=float, default=0.0, help="start position in seconds")
    parser.add_argument("--duration", type=float, default=0.0, help="stop after this many seconds")
    parser.add_argument(
        "--anime4k",
        action="store_true",
        help="Optional anime enhancement: upscale 2x then return to pipeline size before RIFE",
    )
    args = parser.parse_args()
    if args.perf_report:
        report = Path(args.perf_report).expanduser().resolve()
        if report.suffix.lower() != ".json" or report.exists():
            parser.error("--perf-report needs a new .json file (existing reports are preserved)")
        args.perf_report = str(report)
    return args


def prepare_input(args: argparse.Namespace) -> StreamInput:
    headers = normalize_headers(args.http_header_field)
    video = normalize_source(args.input, "Input")
    audio = normalize_source(args.audio_input, "Audio input") if args.audio_input else None
    title = args.title
    if args.ytdl_format:
        video, resolved_audio, headers, resolved_title = resolve_ytdlp(
            video, args.ytdl_format, args.ytdl_proxy, headers
        )
        video = normalize_source(video, "yt-dlp video")
        audio = audio or (
            normalize_source(resolved_audio, "yt-dlp audio") if resolved_audio else None
        )
        title = title or resolved_title
    if is_http_source(video) and not any(
        header.lower().startswith("user-agent:") for header in headers
    ):
        headers = [f"User-Agent: {DEFAULT_USER_AGENT}", *headers]
    info, tracks = probe_media(video, headers, args.http_proxy)
    rate = (
        Fraction(str(args.source_fps)).limit_denominator(1_000_000)
        if args.source_fps > 0
        else info.frame_rate
    )
    subtitles = resolve_subtitles(video, args, headers, args.http_proxy, tracks)
    return StreamInput(
        video,
        audio,
        headers,
        title,
        info,
        rate,
        subtitles.path,
        subtitles.index,
        subtitles.label,
        subtitles.fontsdir,
        subtitles.workdir,
    )


def anime4k_enabled(source: StreamInput, args: argparse.Namespace) -> bool:
    # Only the explicit user setting controls enhancement, at every resolution.
    return bool(args.anime4k)


def build_environment(
    source: StreamInput, args: argparse.Namespace, *, timeline: Timeline | None = None
) -> dict[str, str]:
    width, height = video_size(source.info, args.max_height)
    timeline = timeline or build_timeline(source, args)
    env = os.environ.copy()
    env.pop("RIFE_PERF_RAW", None)
    env.pop("RIFE_PERF_RUN_ID", None)
    env.pop("RIFE_VS_THREADS", None)
    env.pop("RIFE_PIPE_CACHE_AHEAD", None)
    concurrency = Concurrency.resolve(args)
    if getattr(args, "vs_threads", None) is not None:
        env["RIFE_VS_THREADS"] = str(concurrency.vs_threads)
    if getattr(args, "vs_threads", None) is not None or getattr(args, "raw_prefetch", None) is not None:
        old_prefetch = max(8, max(2, concurrency.gpu_threads) * 4)
        env["RIFE_PIPE_CACHE_AHEAD"] = str(
            old_prefetch if getattr(args, "raw_prefetch", None) is None else args.raw_prefetch)
    env.update(
        {
            "RIFE_FACTOR": str(timeline.factor),
            "RIFE_ANIME4K": "1" if anime4k_enabled(source, args) else "0",
            "RIFE_ENGINE_DIR": str(ENGINE_DIR),
            "RIFE_GPU": str(args.gpu),
            "RIFE_GPU_THREADS": str(args.gpu_threads),
            "RIFE_SCENE_MODE": str(args.scene_mode),
            "RIFE_WORKSPACE_MIB": str(args.workspace_mib),
            "RIFE_PIPE_WIDTH": str(width),
            "RIFE_PIPE_HEIGHT": str(height),
            "RIFE_PIPE_FRAMES": str(timeline.pipe_frames),
            "RIFE_PIPE_FPS_NUM": str(timeline.source_rate.numerator),
            "RIFE_PIPE_FPS_DEN": str(timeline.source_rate.denominator),
        }
    )
    return env


def build_vspipe_command(_source: StreamInput, args: argparse.Namespace) -> list[str]:
    return [
        str(VSPIPE),
        "--container",
        "y4m",
        "--requests",
        str(Concurrency.resolve(args).vs_requests),
        str(RIFE_SCRIPT),
        "-",
    ]


def build_decoder_command(
    source: StreamInput, args: argparse.Namespace, *, timeline: Timeline | None = None
) -> list[str]:
    timeline = timeline or build_timeline(source, args)
    command = [
        *FFMPEG_BASE,
        "-hwaccel",
        "cuda",
        "-hwaccel_device",
        str(args.gpu),
        "-hwaccel_output_format",
        "cuda",
        "-extra_hw_frames",
        "8",
        *ffmpeg_input_options(source.video, source.headers, args.http_proxy),
    ]
    if source.is_network and timeline.start > 0:
        command.extend(["-ss", timeline.start_text])
    command.extend(["-i", source.video])
    if not source.is_network and timeline.start > 0:
        command.extend(["-ss", timeline.start_text])
    if timeline.requested_duration > 0:
        command.extend(["-t", timeline.duration_text])
    command.extend(
        option_args(
            ("-map", "0:v:0"), ("-an",), ("-sn",), ("-dn",),
            ("-map_metadata", "-1"),
            ("-vf", decoder_scale_filter(source.info, args.max_height, timeline.source_rate)),
            ("-fps_mode", "cfr"), ("-pix_fmt", "yuv420p"),
            ("-f", "rawvideo"), ("pipe:1",),
        )
    )
    return command


def build_encoder_command(
    source: StreamInput, args: argparse.Namespace, *, timeline: Timeline | None = None
) -> list[str]:
    timeline = timeline or build_timeline(source, args)
    gop = encoder_gop(timeline.source_rate, timeline.factor, args.gop)
    command = [
        *FFMPEG_BASE,
        *option_args(
            ("-fflags", "+genpts"), ("-thread_queue_size", 128),
            ("-f", "yuv4mpegpipe"), ("-i", "pipe:0"),
        ),
    ]
    if not args.no_audio:
        audio_source = source.audio or source.video
        command.extend(["-thread_queue_size", "2048", "-readrate", "0"])
        if timeline.start > 0:
            command.extend(["-ss", timeline.start_text])
        command.extend(ffmpeg_input_options(audio_source, source.headers, args.http_proxy))
        command.extend(["-i", audio_source])
    command.extend(["-map", "0:v:0"])
    if not args.no_audio:
        command.extend(["-map", "1:a:0?"])
    command.extend(["-map_metadata", "-1"])
    if source.subtitle:
        command.extend(
            [
                "-vf",
                subtitle_filter(
                    source.subtitle,
                    source.subtitle_index,
                    float(timeline.start),
                    (source.info.width, source.info.height),
                    source.subtitle_fontsdir,
                ),
            ]
        )
    command.extend(
        option_args(
            ("-c:v", "h264_nvenc"), ("-gpu", getattr(args, "gpu", 0)),
            ("-preset", "p4"), ("-tune", "hq"),
            ("-profile:v", "high"), ("-rc", "vbr"), ("-cq", args.quality),
            ("-b:v", 0), ("-multipass", "qres"),
            ("-g", gop), ("-forced-idr", 1),
            ("-force_key_frames", force_key_frames_expr(gop)),
            ("-strict_gop", 1), ("-bf", 0),
            ("-rc-lookahead", 8), ("-spatial-aq", 1), ("-temporal-aq", 1),
            ("-aq-strength", 8),
            ("-pix_fmt", "yuv420p"), ("-fps_mode", "cfr"),
            ("-colorspace", "bt709"), ("-color_primaries", "bt709"),
            ("-color_trc", "bt709"),
        )
    )
    command.extend(
        ["-an"]
        if args.no_audio
        else [
            "-c:a",
            args.audio_codec,
            *(["-profile:a", "aac_low"] if args.audio_codec == "aac" else []),
            "-b:a",
            "160000",
            "-ar",
            "48000",
            "-ac",
            "2",
            "-af",
            "aresample=async=1:first_pts=0",
        ]
    )
    if timeline.requested_duration > 0:
        command.extend(["-t", timeline.duration_text])
    playlist = Path(args.publish_url)
    command.extend(
        [
            "-shortest",
            "-avoid_negative_ts",
            "make_zero",
            "-f",
            "hls",
            "-hls_time",
            str(HLS_SEGMENT_SECONDS),
            "-hls_list_size",
            "0",
            "-hls_flags",
            HLS_MUXER_FLAGS,
            "-hls_segment_type",
            "mpegts",
            "-hls_segment_filename",
            hls_segment_pattern(playlist),
            str(playlist),
        ]
    )
    return command


def cleanup_subtitles(source: StreamInput | None) -> None:
    if source is None or not source.subtitle_workdir:
        return
    shutil.rmtree(source.subtitle_workdir, ignore_errors=True)


def session_store() -> SessionStore:
    return SessionStore(STREAM_PID_FILE, STREAM_STATUS_FILE)


def owns_stream_process() -> bool:
    store = session_store()
    owner = store.read()
    if WORKER_SESSION_ID is not None:
        return store.matches(owner, WORKER_SESSION_ID, os.getpid())
    return owner is None and read_pid(STREAM_PID_FILE) == os.getpid()


def release_stream_files(playlist: Path, *, failed: bool) -> None:
    store = session_store()
    with store.locked():
        if not owns_stream_process():
            return
        if failed:
            clear_hls_output(playlist)
        if WORKER_SESSION_ID is not None:
            owner = store.read()
            owner.update(state="failed" if failed else "finished")
            atomic_json(store.path, owner)
        STREAM_PID_FILE.unlink(missing_ok=True)
        STREAM_STATUS_FILE.unlink(missing_ok=True)


def stop_process(process: subprocess.Popen[bytes] | None) -> None:
    if process is None:
        return
    if process.poll() is None:
        try:
            process.terminate()
        except ProcessLookupError:
            pass  # The child can exit between poll() and terminate().
    try:
        process.wait(timeout=5)
    except subprocess.TimeoutExpired:
        try:
            process.kill()
        except ProcessLookupError:
            pass
        process.wait(timeout=5)


def write_stream_status(source: StreamInput, start: float) -> bool:
    ensure_var()
    payload = {"duration": source.info.duration, "start": start, "started_at": time.time()}
    if WORKER_SESSION_ID is not None:
        return session_store().publish(WORKER_SESSION_ID, os.getpid(), payload)
    with session_store().locked() as store:
        if store.read() is not None:
            return False
        atomic_json(STREAM_STATUS_FILE, payload)
    return True


@dataclass(frozen=True)
class PipelineResult:
    reason: str
    returncode: int
    failed_stage: str | None
    exit_codes: dict[str, int | None]
    stopped: tuple[str, ...]
    cleanup_errors: tuple[str, ...]
    decoder_pipe_end: bool


class PipelineRunner:
    """Own only this worker's three direct children and parent pipe handles.

    Failure means the first polling snapshot with a nonzero child exit. If
    several fail together, upstream order is deterministic, not proof of cause.
    Children stopped by us are recorded separately from observed failures.
    """

    def __init__(self) -> None:
        self.processes: dict[str, subprocess.Popen[bytes]] = {}
        self.stopped: list[str] = []
        self.cleanup_errors: list[str] = []
        self.active_stage = "decoder"
        self.cancel_signal: int | None = None
        self.decoder_stderr = bytearray()
        self.decoder_stderr_thread: threading.Thread | None = None
        self.decoder_broken_pipe = False
        self.decoder_pipe_end = False
        self.performance: PerformanceRun | None = None

    def request_stop(self, signum: int, _frame) -> None:
        self.cancel_signal = signum

    def start(self, name: str, command: list[str], **kwargs) -> subprocess.Popen[bytes]:
        guard = session_store().locked() if WORKER_SESSION_ID is not None else nullcontext()
        with guard:
            if WORKER_SESSION_ID is not None and not owns_stream_process():
                raise RuntimeError("Playback session superseded")
            self.active_stage = name
            if name == "decoder":
                kwargs["stderr"] = subprocess.PIPE
            process = subprocess.Popen(command, cwd=ROOT, creationflags=PROCESS_FLAGS, **kwargs)
            self.processes[name] = process
            if name == "decoder" and process.stderr is not None:
                self.decoder_stderr_thread = threading.Thread(
                    target=self.read_decoder_stderr, args=(process,),
                    name="rife-decoder-stderr", daemon=True,
                )
                self.decoder_stderr_thread.start()
            return process

    def read_decoder_stderr(self, process: subprocess.Popen[bytes]) -> None:
        try:
            while True:
                chunk = process.stderr.read1(4096)
                if not chunk:
                    return
                self.decoder_stderr.extend(chunk)
                del self.decoder_stderr[:-16384]
                if b"broken pipe" in self.decoder_stderr.lower():
                    self.decoder_broken_pipe = True
                sys.stderr.write(chunk.decode("utf-8", errors="replace"))
                sys.stderr.flush()
        except (OSError, ValueError) as exc:
            self.cleanup_errors.append(f"decoder stderr: {exc}")

    def drain_decoder_stderr(self) -> None:
        if self.decoder_stderr_thread is not None:
            self.decoder_stderr_thread.join(timeout=1)

    def stop(self, name: str) -> None:
        process = self.processes[name]
        if process.poll() is None and name not in self.stopped:
            self.stopped.append(name)
        stop_process(process)

    def wait(self) -> tuple[str, int, str | None]:
        self.active_stage = "supervisor"
        while True:
            if WORKER_SESSION_ID is not None and not owns_stream_process():
                return "stopped", 143, None
            if self.cancel_signal is not None:
                return "stopped", 128 + self.cancel_signal, None
            if self.performance is not None:
                self.performance.observe()
            codes = {name: process.poll() for name, process in self.processes.items()}
            if codes["decoder"] not in (None, 0) and codes["vspipe"] == 0:
                self.drain_decoder_stderr()
                # The planned frame budget can end before decode does. Only a
                # confirmed broken-pipe diagnostic plus successful VSPipe EOF
                # makes the decoder's nonzero exit an expected downstream close.
                self.decoder_pipe_end = self.decoder_broken_pipe
            for name, code in codes.items():
                expected_pipe_end = name == "decoder" and self.decoder_pipe_end
                if code not in (None, 0) and name not in self.stopped and not expected_pipe_end:
                    return "failed", code if code > 0 else 1, name
            if codes["encoder"] == 0:
                # -shortest/-t may intentionally finish while upstream is alive.
                return "finished", 0, None
            if codes["vspipe"] == 0 and codes["decoder"] is None:
                # RIFE has consumed its planned budget; extra decode is not an error.
                self.stop("decoder")
            time.sleep(0.05)

    def cleanup(self) -> None:
        # Continue cleanup even if one child/pipe is already gone or refuses to stop.
        for name, process in reversed(list(self.processes.items())):
            try:
                self.stop(name)
            except (OSError, subprocess.TimeoutExpired) as exc:
                self.cleanup_errors.append(f"{name}: {exc}")
            if process.stdout is not None:
                try:
                    process.stdout.close()
                except OSError as exc:
                    self.cleanup_errors.append(f"{name} stdout: {exc}")

        self.drain_decoder_stderr()
        decoder = self.processes.get("decoder")
        if decoder is not None and decoder.stderr is not None:
            if self.decoder_stderr_thread is not None and self.decoder_stderr_thread.is_alive():
                self.cleanup_errors.append("decoder stderr reader did not reach EOF")
            else:
                try:
                    decoder.stderr.close()
                except (OSError, ValueError) as exc:
                    self.cleanup_errors.append(f"decoder stderr close: {exc}")

    def run(self, source: StreamInput, args: argparse.Namespace,
            timeline: Timeline) -> PipelineResult:
        reason, returncode, failed_stage = "failed", 1, None
        handle_sigterm = os.name != "nt" and threading.current_thread() is threading.main_thread()
        previous_sigterm = None
        if handle_sigterm:
            previous_sigterm = signal.signal(signal.SIGTERM, self.request_stop)
        try:
            decoder_command = build_decoder_command(source, args, timeline=timeline)
            encoder_command = build_encoder_command(source, args, timeline=timeline)
            environment = build_environment(source, args, timeline=timeline)
            if getattr(args, "perf_report", None):
                self.active_stage = "performance"
                width, height = video_size(source.info, args.max_height)
                report_path = Path(args.perf_report).expanduser().resolve()
                if report_path == Path(args.publish_url).expanduser().resolve():
                    raise ValueError("--perf-report must not overwrite the HLS playlist")
                self.performance = PerformanceRun(
                    report_path, session_id=WORKER_SESSION_ID,
                    concurrency=Concurrency.resolve(args),
                    configuration=dict(width=width, height=height,
                        raw_prefetch_frames=int(environment.get("RIFE_PIPE_CACHE_AHEAD",
                            max(8, Concurrency.resolve(args).vs_threads * 4))),
                        source_rate=str(timeline.source_rate), output_rate=str(timeline.output_rate),
                        factor=timeline.factor, start=timeline.start,
                        requested_duration=timeline.requested_duration, pipe_frames=timeline.pipe_frames,
                        gpu=args.gpu, quality=args.quality, anime4k=anime4k_enabled(source, args),
                        scene_mode=args.scene_mode, workspace_mib=args.workspace_mib,
                        no_audio=args.no_audio, audio_codec=args.audio_codec,
                        subtitles=bool(source.subtitle), gop=encoder_gop(timeline.source_rate, timeline.factor, args.gop)),
                )
                self.performance.playlist = Path(args.publish_url)
                decoder_command = self.performance.command("decoder", decoder_command)
                encoder_command = self.performance.command("encoder", encoder_command)
                environment = self.performance.environment(environment)
            decoder = self.start(
                "decoder", decoder_command,
                stdout=subprocess.PIPE, bufsize=8 * 1024 * 1024,
            )
            self.active_stage = "vspipe"
            vspipe = self.start(
                "vspipe", build_vspipe_command(source, args),
                env=environment,
                stdin=decoder.stdout, stdout=subprocess.PIPE, bufsize=8 * 1024 * 1024,
            )
            decoder.stdout.close()
            self.active_stage = "encoder"
            self.start(
                "encoder", encoder_command,
                stdin=vspipe.stdout,
            )
            vspipe.stdout.close()
            reason, returncode, failed_stage = self.wait()
        except KeyboardInterrupt:
            reason, returncode = "interrupted", 130
        except (OSError, RuntimeError, ValueError, subprocess.TimeoutExpired) as exc:
            failed_stage = self.active_stage
            print(f"Error: pipeline {failed_stage}: {exc}", file=sys.stderr, flush=True)
        finally:
            try:
                self.cleanup()
            finally:
                if handle_sigterm:
                    signal.signal(signal.SIGTERM, previous_sigterm)
        if self.cleanup_errors and returncode == 0:
            reason, returncode, failed_stage = "cleanup_failed", 1, "cleanup"
        result = PipelineResult(
            reason, returncode, failed_stage,
            {name: process.returncode for name, process in self.processes.items()},
            tuple(self.stopped), tuple(self.cleanup_errors), self.decoder_pipe_end,
        )
        if result.failed_stage is not None:
            print(f"Error: pipeline failed at {result.failed_stage}", file=sys.stderr, flush=True)
        print("Pipeline result: " + json.dumps({
            "session_id": WORKER_SESSION_ID,
            "reason": result.reason, "returncode": result.returncode,
            "failed_stage": result.failed_stage, "exit_codes": result.exit_codes,
            "stopped": result.stopped, "cleanup_errors": result.cleanup_errors,
            "decoder_pipe_end": result.decoder_pipe_end,
        }), file=sys.stderr, flush=True)
        if self.performance is not None:
            try:
                self.performance.finish(result)
                print(f"Performance: {self.performance.report}", file=sys.stderr, flush=True)
            except (OSError, ValueError, RuntimeError) as exc:
                print(f"Warning: performance report: {exc}", file=sys.stderr, flush=True)
        return result


def run_pipeline(
    source: StreamInput, args: argparse.Namespace, *, timeline: Timeline | None = None
) -> int:
    timeline = timeline or build_timeline(source, args)
    return PipelineRunner().run(source, args, timeline).returncode


def main() -> int:
    global WORKER_SESSION_ID
    args = parse_args()
    missing = next(
        (path for path in (VSPIPE, FFMPEG, FFPROBE, RIFE_SCRIPT) if not path.is_file()),
        None,
    )
    if missing:
        if args.session_id:
            with session_store().locked() as store:
                owner = store.read()
                if owner and owner.get("session_id") == args.session_id:
                    owner["state"] = "failed"
                    atomic_json(store.path, owner)
        print(f"Required file not found: {missing}", file=sys.stderr, flush=True)
        return 2
    ensure_var()
    WORKER_SESSION_ID = args.session_id
    if WORKER_SESSION_ID is None:
        try:
            replace_existing_stream()
            WORKER_SESSION_ID = session_store().reserve(None, args.start, args.duration)["session_id"]
        except (OSError, RuntimeError) as exc:
            print(f"Error: {exc}", file=sys.stderr, flush=True)
            return 1
    if not session_store().attach(WORKER_SESSION_ID, os.getpid()):
        print("Error: Playback session superseded before startup", file=sys.stderr, flush=True)
        return 1
    source = None
    try:
        source = prepare_input(args)
        timeline = build_timeline(source, args)
        with session_store().locked():
            if not owns_stream_process():
                raise RuntimeError("Playback session superseded during probe")
            reset_hls_output(Path(args.publish_url))
        ensure_hls_server()
    except (RuntimeError, ValueError) as exc:
        print(f"Error: {exc}", file=sys.stderr, flush=True)
        cleanup_subtitles(source)
        release_stream_files(Path(args.publish_url), failed=True)
        return 1
    if not write_stream_status(source, float(timeline.start)):
        cleanup_subtitles(source)
        return 1

    width, height = video_size(source.info, args.max_height)
    fps = float(timeline.source_rate)
    pipeline = "FFmpeg NVDEC"
    if anime4k_enabled(source, args):
        pipeline += " -> Anime4K 2x->down"
    pipeline += " -> RIFE -> NVENC -> HLS"
    print(f"Pipeline   : {pipeline}")
    print("RIFE model : 4.25 Lite (TensorRT)")
    print(f"Input      : {display_source(source.video)}")
    if source.title:
        print(f"Title      : {source.title}")
    print(f"Resolution : {source.info.width}x{source.info.height} -> {width}x{height}")
    if anime4k_enabled(source, args):
        print(f"Anime4K    : {width}x{height} -> {width * 2}x{height * 2} -> {width}x{height}")
    print(f"Output     : {args.publish_url}")
    print(f"Frame rate : {fps:.6g} x {timeline.factor} = {float(timeline.output_rate):.3f} fps")
    gop = encoder_gop(timeline.source_rate, timeline.factor, args.gop)
    print(f"HLS GOP    : {gop} frames (~{gop / float(timeline.output_rate):.3f}s IDR)")
    if args.no_audio:
        print("Audio      : none")
    else:
        print(f"Audio      : {args.audio_codec}")
        if args.audio_codec != "aac":
            print("Warning    : use AAC for HLS players; this codec may be silent")
    if source.subtitle:
        print(f"Subtitles  : burn {source.subtitle_label or source.subtitle}")
    else:
        print("Subtitles  : none")
    print("Stop       : Ctrl+C", flush=True)
    exit_code = 1
    try:
        exit_code = run_pipeline(source, args, timeline=timeline)
        return exit_code
    finally:
        cleanup_subtitles(source)
        release_stream_files(Path(args.publish_url), failed=exit_code != 0)


if __name__ == "__main__":
    raise SystemExit(main())
