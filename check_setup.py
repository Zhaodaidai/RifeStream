from pathlib import Path
import socket
import subprocess


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
    runtime = ROOT / "runtime"
    vspipe = runtime / "VSPipe.exe"
    ffmpeg = runtime / "ffmpeg" / "ffmpeg.exe"
    ffprobe = runtime / "ffmpeg" / "ffprobe.exe"
    bestsource = runtime / "vs-plugins" / "BestSource.dll"
    model = runtime / "vs-plugins" / "models" / "rife_v2" / "rife_v4.25_lite.onnx"
    trt = runtime / "vs-plugins" / "vstrt.dll"
    vsmlrt = runtime / "vsmlrt.py"
    video = ROOT / "Smoking.Behind.the.Supermarket.with.You.S01E04.mp4"
    mediamtx = ROOT / "mediamtx.exe"
    mpv_files = (runtime / "mpv.exe", runtime / "mpv.com")

    results = [
        check("VSPipe", vspipe.is_file(), str(vspipe)),
        check("FFmpeg", ffmpeg.is_file(), str(ffmpeg)),
        check("FFprobe", ffprobe.is_file(), str(ffprobe)),
        check("BestSource", bestsource.is_file(), str(bestsource)),
        check("RIFE model", model.is_file(), str(model)),
        check("TensorRT plugin", trt.is_file(), str(trt)),
        check("vs-mlrt", vsmlrt.is_file(), str(vsmlrt)),
        check("MediaMTX binary", mediamtx.is_file(), str(mediamtx)),
        check("test video", video.is_file(), str(video)),
        check(
            "mpv removed",
            not any(path.exists() for path in mpv_files),
            "no mpv executable in runtime",
        ),
    ]
    if ffmpeg.is_file():
        encoders = subprocess.run(
            [str(ffmpeg), "-hide_banner", "-encoders"],
            capture_output=True,
            text=True,
            errors="replace",
        )
        encoder_output = encoders.stdout + encoders.stderr
        results.append(check("NVENC", "h264_nvenc" in encoder_output, "h264_nvenc"))
        results.append(check("WebRTC audio", "libopus" in encoder_output, "libopus"))
    if vspipe.is_file() and video.is_file():
        source_probe = subprocess.run(
            [
                str(vspipe),
                "--info",
                "--arg",
                f"input={video}",
                str(ROOT / "probe_source.vpy"),
                "-",
            ],
            cwd=ROOT,
            capture_output=True,
            text=True,
            errors="replace",
        )
        detail = "core.bs.VideoSource" if source_probe.returncode == 0 else source_probe.stderr.strip()
        results.append(check("BestSource load", source_probe.returncode == 0, detail))
    for port, name in ((8554, "RTSP"), (8888, "HLS"), (8889, "WebRTC")):
        results.append(check(f"MediaMTX {name}", port_open(port), f"127.0.0.1:{port}"))
    print("\nSetup checks passed." if all(results) else "\nSetup has failures.")
    return 0 if all(results) else 1


if __name__ == "__main__":
    raise SystemExit(main())
