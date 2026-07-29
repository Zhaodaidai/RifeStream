import argparse
from fractions import Fraction
import json
import os
from pathlib import Path
import socket
import subprocess
import sys


ROOT = Path(__file__).resolve().parent
VSPIPE = ROOT / "runtime" / "VSPipe.exe"
FFMPEG = ROOT / "runtime" / "ffmpeg" / "ffmpeg.exe"
FFPROBE = ROOT / "runtime" / "ffmpeg" / "ffprobe.exe"
RIFE_SCRIPT = ROOT / "rife_stream.vpy"
DEFAULT_INPUT = ROOT / "Smoking.Behind.the.Supermarket.with.You.S01E04.mp4"


def port_open(port: int, timeout: float = 0.5) -> bool:
    try:
        with socket.create_connection(("127.0.0.1", port), timeout=timeout):
            return True
    except OSError:
        return False


def ensure_mediamtx() -> None:
    if port_open(8554):
        return
    result = subprocess.run([sys.executable, str(ROOT / "mediamtx.py"), "start"], cwd=ROOT)
    if result.returncode != 0 or not port_open(8554):
        raise RuntimeError("MediaMTX is not available on RTSP port 8554")


def probe_video(input_file: Path) -> tuple[float, int, int]:
    command = [
        str(FFPROBE),
        "-v",
        "error",
        "-select_streams",
        "v:0",
        "-show_entries",
        "stream=width,height,avg_frame_rate,r_frame_rate",
        "-of",
        "json",
        str(input_file),
    ]
    result = subprocess.run(
        command,
        cwd=ROOT,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        check=False,
    )
    if result.returncode != 0:
        raise RuntimeError("ffprobe could not inspect the input video")
    try:
        stream = json.loads(result.stdout)["streams"][0]
        width = int(stream["width"])
        height = int(stream["height"])
        for key in ("avg_frame_rate", "r_frame_rate"):
            rate = Fraction(stream.get(key, "0/1"))
            if rate > 0:
                return float(rate), width, height
    except (KeyError, IndexError, TypeError, ValueError, ZeroDivisionError) as exc:
        raise RuntimeError("ffprobe returned invalid video metadata") from exc
    raise RuntimeError("Input frame rate is unavailable; pass --source-fps")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="VSPipe RIFE -> standalone FFmpeg NVENC -> MediaMTX"
    )
    parser.add_argument("input", nargs="?", type=Path, default=DEFAULT_INPUT)
    parser.add_argument("--publish-url", default="rtsp://127.0.0.1:8554/rife")
    parser.add_argument("--factor", type=int, choices=(2, 3, 4), default=2)
    parser.add_argument("--max-height", type=int, default=1080)
    parser.add_argument("--gpu", type=int, choices=(0, 1, 2), default=0)
    parser.add_argument("--gpu-threads", type=int, choices=(1, 2, 3), default=2)
    parser.add_argument("--scene-mode", type=int, choices=(0, 1, 2), default=1)
    parser.add_argument("--workspace-mib", type=int, default=0)
    parser.add_argument("--source-fps", type=float, default=0.0)
    parser.add_argument("--video-bitrate", type=int, default=10_000_000)
    parser.add_argument("--gop", type=int, default=120)
    parser.add_argument("--preset", choices=tuple(f"p{i}" for i in range(1, 8)), default="p4")
    parser.add_argument("--audio-codec", choices=("libopus", "aac"), default="libopus")
    parser.add_argument("--no-audio", action="store_true")
    parser.add_argument("--start", type=float, default=0.0, help="start position in seconds")
    parser.add_argument("--duration", type=float, default=0.0, help="stop after this many seconds")
    return parser.parse_args()


def stop_process(process: subprocess.Popen[bytes] | None) -> None:
    if process is None or process.poll() is not None:
        return
    process.terminate()
    try:
        process.wait(timeout=5)
    except subprocess.TimeoutExpired:
        process.kill()


def main() -> int:
    args = parse_args()
    input_file = args.input.expanduser().resolve()
    if not input_file.is_file():
        print(f"Input file not found: {input_file}", file=sys.stderr)
        return 2
    for required in (VSPIPE, FFMPEG, FFPROBE, RIFE_SCRIPT):
        if not required.is_file():
            print(f"Required file not found: {required}", file=sys.stderr)
            return 2
    if args.max_height < 0 or args.workspace_mib < 0 or args.video_bitrate <= 0:
        print("Height, workspace, and bitrate arguments are invalid", file=sys.stderr)
        return 2
    if args.start < 0 or args.duration < 0:
        print("Start and duration cannot be negative", file=sys.stderr)
        return 2

    try:
        ensure_mediamtx()
        detected_fps, width, height = probe_video(input_file)
        source_fps = args.source_fps if args.source_fps > 0 else detected_fps
    except RuntimeError as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 1

    env = os.environ.copy()
    env.update(
        {
            "RIFE_FACTOR": str(args.factor),
            "RIFE_MAX_HEIGHT": str(args.max_height),
            "RIFE_GPU": str(args.gpu),
            "RIFE_GPU_THREADS": str(args.gpu_threads),
            "RIFE_SCENE_MODE": str(args.scene_mode),
            "RIFE_WORKSPACE_MIB": str(args.workspace_mib),
            "RIFE_SOURCE_FPS": format(source_fps, ".12g"),
            "RIFE_START_SECONDS": format(args.start, ".12g"),
            "RIFE_DURATION_SECONDS": format(args.duration, ".12g"),
        }
    )

    vspipe_command = [
        str(VSPIPE),
        "--container",
        "y4m",
        "--arg",
        f"input={input_file}",
        str(RIFE_SCRIPT),
        "-",
    ]

    ffmpeg_command = [
        str(FFMPEG),
        "-hide_banner",
        "-nostdin",
        "-loglevel",
        "info",
        "-fflags",
        "+genpts",
        "-thread_queue_size",
        "16",
        "-re",
        "-f",
        "yuv4mpegpipe",
        "-i",
        "pipe:0",
    ]
    if not args.no_audio:
        ffmpeg_command.extend(["-thread_queue_size", "512", "-re"])
        if args.start > 0:
            ffmpeg_command.extend(["-ss", format(args.start, ".12g")])
        ffmpeg_command.extend(["-i", str(input_file)])

    ffmpeg_command.extend(["-map", "0:v:0"])
    if not args.no_audio:
        ffmpeg_command.extend(["-map", "1:a:0?"])
    ffmpeg_command.extend(
        [
            "-c:v",
            "h264_nvenc",
            "-preset",
            args.preset,
            "-tune",
            "ull",
            "-profile:v",
            "baseline",
            "-rc",
            "cbr",
            "-b:v",
            str(args.video_bitrate),
            "-maxrate",
            str(args.video_bitrate),
            "-bufsize",
            str(args.video_bitrate),
            "-g",
            str(args.gop),
            "-bf",
            "0",
            "-rc-lookahead",
            "0",
            "-spatial-aq",
            "1",
            "-temporal-aq",
            "1",
            "-zerolatency",
            "1",
            "-forced-idr",
            "1",
            "-pix_fmt",
            "yuv420p",
            "-colorspace",
            "bt709",
            "-color_primaries",
            "bt709",
            "-color_trc",
            "bt709",
        ]
    )
    if args.no_audio:
        ffmpeg_command.append("-an")
    else:
        ffmpeg_command.extend(
            ["-c:a", args.audio_codec, "-b:a", "160000", "-ar", "48000", "-ac", "2"]
        )
    if args.duration > 0:
        ffmpeg_command.extend(["-t", format(args.duration, ".12g")])
    ffmpeg_command.extend(
        ["-shortest", "-f", "rtsp", "-rtsp_transport", "tcp", args.publish_url]
    )

    output_height = min(height, args.max_height) if args.max_height > 0 else height
    print("Pipeline   : VSPipe -> RIFE -> FFmpeg NVENC -> MediaMTX")
    print("RIFE model : 4.25 Lite (TensorRT)")
    print(f"Input      : {input_file}")
    print(f"Resolution : {width}x{height} -> max height {output_height}")
    print(f"Output     : {args.publish_url}")
    print(f"Frame rate : {source_fps:.6g} x {args.factor} = {source_fps * args.factor:.3f} fps")
    print("Stop       : Ctrl+C", flush=True)

    vspipe: subprocess.Popen[bytes] | None = None
    ffmpeg: subprocess.Popen[bytes] | None = None
    try:
        vspipe = subprocess.Popen(
            vspipe_command,
            cwd=ROOT,
            env=env,
            stdout=subprocess.PIPE,
            bufsize=0,
        )
        if vspipe.stdout is None:
            raise RuntimeError("VSPipe stdout pipe was not created")
        ffmpeg = subprocess.Popen(ffmpeg_command, cwd=ROOT, stdin=vspipe.stdout)
        vspipe.stdout.close()
        ffmpeg_exit = ffmpeg.wait()
        if vspipe.poll() is None and ffmpeg_exit != 0:
            stop_process(vspipe)
        vspipe_exit = vspipe.wait()
        if ffmpeg_exit != 0:
            return ffmpeg_exit
        return vspipe_exit
    except KeyboardInterrupt:
        stop_process(ffmpeg)
        stop_process(vspipe)
        return 130
    except RuntimeError as exc:
        print(f"Error: {exc}", file=sys.stderr)
        stop_process(ffmpeg)
        stop_process(vspipe)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
