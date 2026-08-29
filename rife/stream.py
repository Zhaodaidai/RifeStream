import argparse
from dataclasses import dataclass
from fractions import Fraction
import json
import math
import os
from pathlib import Path
import shutil
import subprocess
import tempfile
import time
import sys
from urllib.parse import urlsplit, urlunsplit

from rife.hls import (
    HLS_MUXER_FLAGS,
    HLS_SEGMENT_SECONDS,
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
    is_http_source,
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


def video_size(info: MediaInfo, max_height: int) -> tuple[int, int]:
    width = info.width // 2 * 2
    height = info.height // 2 * 2
    if max_height and height > max_height:
        height = max_height // 2 * 2
        width = max(2, int(info.width * height / info.height) // 2 * 2)
    # Pad width to 32 so 1910x1080 reuses a 1920x1080 TensorRT engine.
    width = max(2, (width + 31) // 32 * 32)
    return width, height


HTTP_RECONNECT_OPTIONS = [
    "-reconnect",
    "1",
    "-reconnect_streamed",
    "1",
    "-reconnect_at_eof",
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


def probe_video(
    input_source: str, headers: list[str], proxy: str | None
) -> MediaInfo:
    command = [
        str(FFPROBE),
        "-v",
        "error",
        *ffmpeg_input_options(input_source, headers, proxy),
        "-select_streams",
        "v:0",
        "-show_entries",
        "stream=width,height,avg_frame_rate,r_frame_rate,duration:format=duration",
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
        stream = document["streams"][0]
        width = int(stream["width"])
        height = int(stream["height"])
        for key in ("avg_frame_rate", "r_frame_rate"):
            rate = Fraction(stream.get(key, "0/1"))
            if rate > 0:
                duration = safe_float(stream.get("duration"))
                if duration is None:
                    duration = safe_float(document.get("format", {}).get("duration"))
                return MediaInfo(rate, width, height, duration)
    except (KeyError, IndexError, TypeError, ValueError, ZeroDivisionError) as exc:
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
    parser.add_argument("--gpu-threads", type=int, choices=(1, 2, 3), default=2)
    parser.add_argument("--scene-mode", type=int, choices=(0, 1, 2), default=1)
    parser.add_argument("--workspace-mib", type=int, default=0)
    parser.add_argument("--source-fps", type=float, default=0.0)
    parser.add_argument(
        "--quality",
        type=int,
        choices=range(1, 31),
        default=16,
        help="NVENC constant quality; lower values preserve more detail",
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
    return parser.parse_args()


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
    info = probe_video(video, headers, args.http_proxy)
    rate = (
        Fraction(str(args.source_fps)).limit_denominator(1_000_000)
        if args.source_fps > 0
        else info.frame_rate
    )
    subtitles = resolve_subtitles(video, args, headers, args.http_proxy)
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


def build_environment(source: StreamInput, args: argparse.Namespace) -> dict[str, str]:
    width, height = video_size(source.info, args.max_height)
    env = os.environ.copy()
    env.update(
        {
            "RIFE_FACTOR": str(args.factor),
            "RIFE_MAX_HEIGHT": str(args.max_height),
            "RIFE_OUT_WIDTH": str(width),
            "RIFE_OUT_HEIGHT": str(height),
            "RIFE_ENGINE_DIR": str(ENGINE_DIR),
            "RIFE_GPU": str(args.gpu),
            "RIFE_GPU_THREADS": str(args.gpu_threads),
            "RIFE_SCENE_MODE": str(args.scene_mode),
            "RIFE_WORKSPACE_MIB": str(args.workspace_mib),
            "RIFE_SOURCE_FPS": format(float(source.rate), ".12g"),
            "RIFE_START_SECONDS": format(0 if source.is_network else args.start, ".12g"),
            "RIFE_DURATION_SECONDS": format(0 if source.is_network else args.duration, ".12g"),
            "RIFE_PIPE_INPUT": str(int(source.is_network)),
        }
    )
    if source.is_network:
        duration = args.duration or (
            max(0.0, source.info.duration - args.start)
            if source.info.duration is not None
            else None
        )
        frames = (
            max(1, math.floor(duration * float(source.rate)) - 1)
            if duration is not None
            else 2_000_000_000
        )
        env.update(
            {
                "RIFE_PIPE_WIDTH": str(width),
                "RIFE_PIPE_HEIGHT": str(height),
                "RIFE_PIPE_FRAMES": str(frames),
                "RIFE_PIPE_FPS_NUM": str(source.rate.numerator),
                "RIFE_PIPE_FPS_DEN": str(source.rate.denominator),
            }
        )
    return env


def build_vspipe_command(source: StreamInput, args: argparse.Namespace) -> list[str]:
    command = [str(VSPIPE), "--container", "y4m", "--requests", str(args.gpu_threads)]
    if not source.is_network:
        command.extend(["--arg", f"input={source.video}"])
    return [*command, str(RIFE_SCRIPT), "-"]


def build_decoder_command(
    source: StreamInput, args: argparse.Namespace
) -> list[str] | None:
    if not source.is_network:
        return None
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
    if args.start > 0:
        command.extend(["-ss", format(args.start, ".12g")])
    command.extend(["-i", source.video])
    if args.duration > 0:
        command.extend(["-t", format(args.duration, ".12g")])
    rate = f"{source.rate.numerator}/{source.rate.denominator}"
    width, height = video_size(source.info, args.max_height)
    command.extend(
        option_args(
            ("-map", "0:v:0"), ("-an",), ("-sn",), ("-dn",),
            (
                "-vf",
                f"scale_cuda={width}:{height}:format=yuv420p:interp_algo=bilinear,"
                f"hwdownload,format=yuv420p,fps={rate}",
            ),
            ("-fps_mode", "cfr"), ("-pix_fmt", "yuv420p"),
            ("-f", "rawvideo"), ("pipe:1",),
        )
    )
    return command


def build_encoder_command(source: StreamInput, args: argparse.Namespace) -> list[str]:
    gop = encoder_gop(source.rate, args.factor, args.gop)
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
        if args.start > 0:
            command.extend(["-ss", format(args.start, ".12g")])
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
                    args.start,
                    (source.info.width, source.info.height),
                    source.subtitle_fontsdir,
                ),
            ]
        )
    command.extend(
        option_args(
            ("-c:v", "h264_nvenc"), ("-preset", "p4"), ("-tune", "hq"),
            ("-profile:v", "high"), ("-rc", "vbr"), ("-cq", args.quality),
            ("-b:v", 0), ("-multipass", "qres"),
            ("-g", gop), ("-forced-idr", 1),
            ("-force_key_frames", force_key_frames_expr(gop)),
            ("-strict_gop", 1), ("-bf", 0),
            ("-rc-lookahead", 8), ("-spatial-aq", 1), ("-aq-strength", 8),
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
    if args.duration > 0:
        command.extend(["-t", format(args.duration, ".12g")])
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


def stop_process(process: subprocess.Popen[bytes] | None) -> None:
    if process is None or process.poll() is not None:
        return
    process.terminate()
    try:
        process.wait(timeout=5)
    except subprocess.TimeoutExpired:
        process.kill()
        process.wait()


def write_stream_status(source: StreamInput, start: float) -> None:
    STREAM_STATUS_FILE.write_text(
        json.dumps(
            {
                "duration": source.info.duration,
                "start": start,
                "started_at": time.time(),
            }
        ),
        encoding="utf-8",
    )


def run_pipeline(source: StreamInput, args: argparse.Namespace) -> int:
    decoder: subprocess.Popen[bytes] | None = None
    vspipe: subprocess.Popen[bytes] | None = None
    encoder: subprocess.Popen[bytes] | None = None
    try:
        decoder_command = build_decoder_command(source, args)
        if decoder_command:
            decoder = subprocess.Popen(
                decoder_command,
                cwd=ROOT,
                stdout=subprocess.PIPE,
                bufsize=8 * 1024 * 1024,
                creationflags=PROCESS_FLAGS,
            )
        vspipe = subprocess.Popen(
            build_vspipe_command(source, args),
            cwd=ROOT,
            env=build_environment(source, args),
            stdin=decoder.stdout if decoder else None,
            stdout=subprocess.PIPE,
            bufsize=8 * 1024 * 1024,
            creationflags=PROCESS_FLAGS,
        )
        if decoder and decoder.stdout:
            decoder.stdout.close()
        encoder = subprocess.Popen(
            build_encoder_command(source, args),
            cwd=ROOT,
            stdin=vspipe.stdout,
            creationflags=PROCESS_FLAGS,
        )
        vspipe.stdout.close()
        encoder_exit = encoder.wait()
        vspipe_exit = vspipe.poll()
        stop_process(vspipe)
        stop_process(decoder)
        return encoder_exit or vspipe_exit or 0
    except KeyboardInterrupt:
        for process in (encoder, vspipe, decoder):
            stop_process(process)
        return 130
    except (OSError, RuntimeError) as exc:
        print(f"Error: {exc}", file=sys.stderr, flush=True)
        for process in (encoder, vspipe, decoder):
            stop_process(process)
        return 1


def main() -> int:
    args = parse_args()
    missing = next(
        (path for path in (VSPIPE, FFMPEG, FFPROBE, RIFE_SCRIPT) if not path.is_file()),
        None,
    )
    if missing:
        print(f"Required file not found: {missing}", file=sys.stderr, flush=True)
        return 2
    replace_existing_stream()
    STREAM_PID_FILE.write_text(str(os.getpid()), encoding="ascii")
    source = None
    try:
        source = prepare_input(args)
        reset_hls_output(Path(args.publish_url))
        ensure_hls_server()
    except (RuntimeError, ValueError) as exc:
        print(f"Error: {exc}", file=sys.stderr, flush=True)
        cleanup_subtitles(source)
        STREAM_PID_FILE.unlink(missing_ok=True)
        STREAM_STATUS_FILE.unlink(missing_ok=True)
        return 1
    write_stream_status(source, args.start)

    width, height = video_size(source.info, args.max_height)
    fps = float(source.rate)
    print("Pipeline   : VSPipe -> RIFE -> FFmpeg NVENC -> HLS")
    print("RIFE model : 4.25 Lite (TensorRT)")
    print(f"Input      : {display_source(source.video)}")
    if source.title:
        print(f"Title      : {source.title}")
    print(
        f"Resolution : {source.info.width}x{source.info.height} -> {width}x{height}"
    )
    print(f"Output     : {args.publish_url}")
    print(f"Frame rate : {fps:.6g} x {args.factor} = {fps * args.factor:.3f} fps")
    gop = encoder_gop(source.rate, args.factor, args.gop)
    print(f"HLS GOP    : {gop} frames (~{gop / (fps * args.factor):.3f}s IDR)")
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
    try:
        return run_pipeline(source, args)
    finally:
        cleanup_subtitles(source)
        STREAM_PID_FILE.unlink(missing_ok=True)
        STREAM_STATUS_FILE.unlink(missing_ok=True)


if __name__ == "__main__":
    raise SystemExit(main())
