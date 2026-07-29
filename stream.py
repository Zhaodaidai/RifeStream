import argparse
import os
from pathlib import Path
import re
import socket
import subprocess
import sys


ROOT = Path(__file__).resolve().parent
MPV = ROOT / "runtime" / "mpv.com"
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


def probe_fps(input_file: Path) -> float:
    marker = "RIFE_PROBE_FPS="
    command = [
        str(MPV),
        "--no-config",
        "--frames=1",
        "--vo=null",
        "--no-audio",
        "--quiet",
        "--term-playing-msg=" + marker + "${container-fps}|${estimated-vf-fps}",
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
        raise RuntimeError("mpv could not probe the input frame rate")
    output = result.stdout + "\n" + result.stderr
    match = re.search(re.escape(marker) + r"([^\r\n]+)", output)
    if match:
        for candidate in match.group(1).split("|"):
            try:
                fps = float(candidate)
            except ValueError:
                continue
            if fps > 0:
                return fps
    raise RuntimeError("Input frame rate is unavailable; pass --source-fps")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Stream a video through VapourSynth RIFE and NVENC to MediaMTX"
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


def main() -> int:
    args = parse_args()
    input_file = args.input.expanduser().resolve()
    if not input_file.is_file():
        print(f"Input file not found: {input_file}", file=sys.stderr)
        return 2
    for required in (MPV, RIFE_SCRIPT):
        if not required.is_file():
            print(f"Required file not found: {required}", file=sys.stderr)
            return 2
    if args.max_height < 0 or args.workspace_mib < 0 or args.video_bitrate <= 0:
        print("Height, workspace, and bitrate arguments are invalid", file=sys.stderr)
        return 2

    try:
        ensure_mediamtx()
        source_fps = args.source_fps if args.source_fps > 0 else probe_fps(input_file)
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
        }
    )

    video_options = ",".join(
        (
            f"preset={args.preset}",
            "tune=ull",
            "profile=baseline",
            "rc=cbr",
            f"b={args.video_bitrate}",
            f"maxrate={args.video_bitrate}",
            f"bufsize={args.video_bitrate}",
            f"g={args.gop}",
            "bf=0",
            "rc-lookahead=0",
            "spatial-aq=1",
            "temporal-aq=1",
            "zerolatency=1",
            "forced-idr=1",
        )
    )
    command = [
        str(MPV),
        "--no-config",
        "--no-sub",
        "--msg-level=all=warn,encode=info,ffmpeg=warn,vf=info",
        f"--vf=vapoursynth=file={RIFE_SCRIPT.name}:buffered-frames=4:concurrent-frames={args.gpu_threads},lavfi=[realtime]",
        "--af=lavfi=[arealtime]",
        f"--o={args.publish_url}",
        "--of=rtsp",
        "--ofopts=rtsp_transport=tcp",
        "--ovc=h264_nvenc",
        f"--ovcopts={video_options}",
        f"--oac={args.audio_codec}",
        "--oacopts=b=160000,ar=48000",
        "--audio-channels=stereo",
        "--force-window=no",
        "--keep-open=no",
    ]
    if args.no_audio:
        command.append("--no-audio")
    if args.start > 0:
        command.append(f"--start={args.start}")
    if args.duration > 0:
        command.append(f"--end=+{args.duration}")
    command.append(str(input_file))

    print("RIFE model : 4.25 Lite (TensorRT)")
    print(f"Input      : {input_file}")
    print(f"Output     : {args.publish_url}")
    print(f"Frame rate : {source_fps:.6g} x {args.factor} = {source_fps * args.factor:.3f} fps")
    print("Stop       : Ctrl+C", flush=True)

    process = subprocess.Popen(command, cwd=ROOT, env=env)
    try:
        return process.wait()
    except KeyboardInterrupt:
        process.terminate()
        try:
            process.wait(timeout=5)
        except subprocess.TimeoutExpired:
            process.kill()
        return 130


if __name__ == "__main__":
    raise SystemExit(main())
