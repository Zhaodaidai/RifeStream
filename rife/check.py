from rife.paths import (
    FFMPEG,
    FFPROBE,
    HLS_PORT,
    HLS_SERVER_PID_FILE,
    PROBE_SCRIPT,
    PROTOCOL_CLI,
    PYTHON,
    ROOT,
    RUNTIME,
    VSPIPE,
    capture,
    port_open,
)


def check(name: str, ok: bool, detail: str) -> bool:
    state = "OK" if ok else "FAIL"
    print(f"[{state:4}] {name}: {detail}")
    return ok


def main() -> int:
    bestsource = RUNTIME / "vs-plugins" / "BestSource.dll"
    model = RUNTIME / "vs-plugins" / "models" / "rife_v2" / "rife_v4.25_lite.onnx"
    trt = RUNTIME / "vs-plugins" / "vstrt.dll"
    vsmlrt = RUNTIME / "vs-plugins" / "vsmlrt.py"
    mpv_files = (RUNTIME / "mpv.exe", RUNTIME / "mpv.com")

    required = {
        "VSPipe": VSPIPE,
        "FFmpeg": FFMPEG,
        "FFprobe": FFPROBE,
        "BestSource": bestsource,
        "RIFE model": model,
        "TensorRT plugin": trt,
        "vs-mlrt": vsmlrt,
        "MPV protocol receiver": PROTOCOL_CLI,
    }
    results = [check(name, path.is_file(), str(path)) for name, path in required.items()]
    results.append(
        check(
            "mpv removed",
            not any(path.exists() for path in mpv_files),
            "no mpv executable in runtime",
        )
    )
    ytdlp = capture([str(PYTHON), "-c", "import yt_dlp; print(yt_dlp.version.__version__)"])
    results.append(
        check(
            "yt-dlp",
            ytdlp.returncode == 0,
            ytdlp.stdout.strip() if ytdlp.returncode == 0 else "not installed",
        )
    )
    if FFMPEG.is_file():
        encoders = capture([str(FFMPEG), "-hide_banner", "-encoders"])
        encoder_output = encoders.stdout + encoders.stderr
        results.append(check("NVENC", "h264_nvenc" in encoder_output, "h264_nvenc"))
        results.append(check("AAC audio", "aac" in encoder_output.lower(), "aac"))
        filters = capture([str(FFMPEG), "-hide_banner", "-filters"])
        filter_output = filters.stdout + filters.stderr
        results.append(check("CUDA scaling", "scale_cuda" in filter_output, "scale_cuda"))
    if VSPIPE.is_file():
        source_probe = capture(
            [str(VSPIPE), "--info", str(PROBE_SCRIPT), "-"], cwd=ROOT
        )
        detail = (
            "core.bs.VideoSource"
            if source_probe.returncode == 0
            else source_probe.stderr.strip()
        )
        results.append(check("BestSource load", source_probe.returncode == 0, detail))
    listening = port_open(HLS_PORT)
    results.append(
        check(
            "HLS server",
            listening,
            f"127.0.0.1:{HLS_PORT}"
            + ("" if not HLS_SERVER_PID_FILE.is_file() else f" ({HLS_SERVER_PID_FILE.name})"),
        )
    )
    print("\nSetup checks passed." if all(results) else "\nSetup has failures.")
    return 0 if all(results) else 1


if __name__ == "__main__":
    raise SystemExit(main())
