from pathlib import Path
import socket
import subprocess
import sys


ROOT = Path(__file__).resolve().parent


def check(name: str, ok: bool, detail: str) -> bool:
    state = "OK" if ok else "FAIL"
    print(f"[{state:4}] {name}: {detail}")
    return ok


def port_open(port: int) -> bool:
    try:
        with socket.create_connection(("127.0.0.1", port), timeout=0.5):
            return True
    except OSError:
        return False


def main() -> int:
    mpv = ROOT / "runtime" / "mpv.com"
    model = ROOT / "runtime" / "vs-plugins" / "models" / "rife_v2" / "rife_v4.25_lite.onnx"
    trt = ROOT / "runtime" / "vs-plugins" / "vstrt.dll"
    vsmlrt = ROOT / "runtime" / "vsmlrt.py"
    video = ROOT / "Smoking.Behind.the.Supermarket.with.You.S01E04.mp4"
    mediamtx = ROOT / "mediamtx.exe"

    results = [
        check("mpv/FFmpeg", mpv.is_file(), str(mpv)),
        check("RIFE model", model.is_file(), str(model)),
        check("TensorRT plugin", trt.is_file(), str(trt)),
        check("vs-mlrt", vsmlrt.is_file(), str(vsmlrt)),
        check("MediaMTX binary", mediamtx.is_file(), str(mediamtx)),
        check("test video", video.is_file(), str(video)),
    ]
    if mpv.is_file():
        video_encoders = subprocess.run(
            [str(mpv), "--no-config", "--ovc=help"], capture_output=True, text=True, errors="replace"
        ).stdout
        audio_encoders = subprocess.run(
            [str(mpv), "--no-config", "--oac=help"], capture_output=True, text=True, errors="replace"
        ).stdout
        results.append(check("NVENC", "h264_nvenc" in video_encoders, "h264_nvenc"))
        results.append(check("WebRTC audio", "libopus" in audio_encoders, "libopus"))
    for port, name in ((8554, "RTSP"), (8888, "HLS"), (8889, "WebRTC")):
        results.append(check(f"MediaMTX {name}", port_open(port), f"127.0.0.1:{port}"))
    print("\nSetup checks passed." if all(results) else "\nSetup has failures.")
    return 0 if all(results) else 1


if __name__ == "__main__":
    raise SystemExit(main())
