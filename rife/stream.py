import argparse
from dataclasses import dataclass
from fractions import Fraction
import json
import math
import os
from pathlib import Path
import subprocess
import time
import sys
from urllib.parse import urlsplit, urlunsplit

from rife.mediamtx import start as start_mediamtx
from rife.paths import (
    API_PORT,
    FFMPEG,
    FFPROBE,
    HTTP_SCHEMES,
    PROCESS_FLAGS,
    RIFE_SCRIPT,
    ROOT,
    RTSP_PORT,
    STREAM_PID_FILE,
    STREAM_STATUS_FILE,
    VSPIPE,
    port_open,
)


DEFAULT_USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/138.0.0.0 Safari/537.36"
)
FFMPEG_BASE = [str(FFMPEG), "-hide_banner", "-nostdin", "-loglevel", "warning"]


@dataclass
class MediaInfo:
    frame_rate: Fraction
    width: int
    height: int
    duration: float | None


@dataclass
class StreamInput:
    video: str
    audio: str | None
    headers: list[str]
    title: str | None
    info: MediaInfo
    rate: Fraction

    @property
    def is_network(self) -> bool:
        return is_http_source(self.video)


def ensure_mediamtx() -> None:
    if port_open(RTSP_PORT) and port_open(API_PORT):
        return
    if start_mediamtx() != 0 or not (port_open(RTSP_PORT) and port_open(API_PORT)):
        raise RuntimeError("MediaMTX RTSP or control API is not available")


def is_http_source(source: str) -> bool:
    return urlsplit(source).scheme.lower() in HTTP_SCHEMES


def normalize_source(source: str, name: str) -> str:
    if is_http_source(source):
        if not urlsplit(source).netloc:
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
    if not max_height or height <= max_height:
        return width, height
    output_height = max_height // 2 * 2
    output_width = max(2, int(width * output_height / height) // 2 * 2)
    return output_width, output_height


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
    if is_http_source(source):
        options.extend(HTTP_RECONNECT_OPTIONS)
        if urlsplit(source).path.lower().endswith(".m3u8"):
            options.extend(["-http_persistent", "0"])
    if headers:
        options.extend(["-headers", "\r\n".join(headers) + "\r\n"])
    if proxy:
        options.extend(["-http_proxy", proxy])
    return options


def capture(command: list[str]) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        command,
        cwd=ROOT,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        check=False,
        creationflags=PROCESS_FLAGS,
    )


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
        description="VSPipe RIFE -> standalone FFmpeg NVENC -> MediaMTX"
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
    parser.add_argument("--publish-url", default="rtsp://127.0.0.1:8554/rife")
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
        "--gop", type=int, default=0, help="keyframe interval; 0 selects one second"
    )
    parser.add_argument("--audio-codec", choices=("libopus", "aac"), default="libopus")
    parser.add_argument("--no-audio", action="store_true")
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
    if is_http_source(video):
        if not any(header.lower().startswith("user-agent:") for header in headers):
            headers = merge_headers([f"User-Agent: {DEFAULT_USER_AGENT}"], headers)
    info = probe_video(video, headers, args.http_proxy)
    rate = (
        Fraction(str(args.source_fps)).limit_denominator(1_000_000)
        if args.source_fps > 0
        else info.frame_rate
    )
    return StreamInput(video, audio, headers, title, info, rate)


def build_environment(source: StreamInput, args: argparse.Namespace) -> dict[str, str]:
    env = os.environ.copy()
    env.update(
        {
            "RIFE_FACTOR": str(args.factor),
            "RIFE_MAX_HEIGHT": str(args.max_height),
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
        width, height = video_size(source.info, args.max_height)
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
    gop = args.gop or max(1, round(float(source.rate) * args.factor))
    command = [
        *FFMPEG_BASE,
        *option_args(
            ("-fflags", "+genpts"), ("-thread_queue_size", 128),
            ("-f", "yuv4mpegpipe"), ("-i", "pipe:0"),
        ),
    ]
    if not args.no_audio:
        audio_source = source.audio or source.video
        command.extend(["-thread_queue_size", "512"])
        if args.start > 0:
            command.extend(["-ss", format(args.start, ".12g")])
        command.extend(ffmpeg_input_options(audio_source, source.headers, args.http_proxy))
        command.extend(["-i", audio_source])
    command.extend(["-map", "0:v:0"])
    if not args.no_audio:
        command.extend(["-map", "1:a:0?"])
    command.extend(
        option_args(
            ("-c:v", "h264_nvenc"), ("-preset", "p4"), ("-tune", "hq"),
            ("-profile:v", "high"), ("-rc", "vbr"), ("-cq", args.quality),
            ("-b:v", 0), ("-multipass", "qres"), ("-g", gop), ("-bf", 0),
            ("-rc-lookahead", 8), ("-spatial-aq", 1), ("-aq-strength", 8),
            ("-pix_fmt", "yuv420p"),
            ("-colorspace", "bt709"), ("-color_primaries", "bt709"),
            ("-color_trc", "bt709"),
        )
    )
    command.extend(
        ["-an"]
        if args.no_audio
        else ["-c:a", args.audio_codec, "-b:a", "160000", "-ar", "48000", "-ac", "2"]
    )
    if args.duration > 0:
        command.extend(["-t", format(args.duration, ".12g")])
    return [
        *command,
        "-shortest",
        "-f",
        "rtsp",
        "-rtsp_transport",
        "tcp",
        "-pkt_size",
        "1400",
        args.publish_url,
    ]


def stop_process(process: subprocess.Popen[bytes] | None) -> None:
    if process is None or process.poll() is not None:
        return
    process.terminate()
    try:
        process.wait(timeout=5)
    except subprocess.TimeoutExpired:
        process.kill()
        process.wait()


def stop_process_tree(pid: int) -> None:
    if os.name == "nt":
        subprocess.run(
            ["taskkill", "/PID", str(pid), "/T", "/F"],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            check=False,
            creationflags=PROCESS_FLAGS,
        )
        return
    try:
        os.kill(pid, 15)
    except ProcessLookupError:
        return


def replace_existing_stream() -> None:
    if not STREAM_PID_FILE.is_file():
        return
    try:
        pid = int(STREAM_PID_FILE.read_text(encoding="ascii").strip())
    except ValueError:
        STREAM_PID_FILE.unlink(missing_ok=True)
        STREAM_STATUS_FILE.unlink(missing_ok=True)
        return
    if pid != os.getpid():
        stop_process_tree(pid)
    STREAM_PID_FILE.unlink(missing_ok=True)
    STREAM_STATUS_FILE.unlink(missing_ok=True)


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
    try:
        source = prepare_input(args)
        ensure_mediamtx()
    except (RuntimeError, ValueError) as exc:
        print(f"Error: {exc}", file=sys.stderr, flush=True)
        STREAM_PID_FILE.unlink(missing_ok=True)
        STREAM_STATUS_FILE.unlink(missing_ok=True)
        return 1
    write_stream_status(source, args.start)

    width, height = video_size(source.info, args.max_height)
    fps = float(source.rate)
    print("Pipeline   : VSPipe -> RIFE -> FFmpeg NVENC -> MediaMTX")
    print("RIFE model : 4.25 Lite (TensorRT)")
    print(f"Input      : {display_source(source.video)}")
    if source.title:
        print(f"Title      : {source.title}")
    print(
        f"Resolution : {source.info.width}x{source.info.height} -> {width}x{height}"
    )
    print(f"Output     : {args.publish_url}")
    print(f"Frame rate : {fps:.6g} x {args.factor} = {fps * args.factor:.3f} fps")
    print("Stop       : Ctrl+C", flush=True)
    try:
        return run_pipeline(source, args)
    finally:
        STREAM_PID_FILE.unlink(missing_ok=True)
        STREAM_STATUS_FILE.unlink(missing_ok=True)


if __name__ == "__main__":
    raise SystemExit(main())
