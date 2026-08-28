from __future__ import annotations

import argparse
import csv
import io
import os
import subprocess
import sys
import time

from rife.paths import (
    API_PORT,
    HLS_MUXER_PORT,
    HLS_PORT,
    HLS_PROXY_LOG_FILE,
    HLS_PROXY_PID_FILE,
    MEDIAMTX_BINARY,
    MEDIAMTX_CONFIG,
    MEDIAMTX_LOG_FILE,
    MEDIAMTX_PID_FILE,
    PROCESS_FLAGS,
    ROOT,
    RTSP_PORT,
    port_open,
)

HLS_PROXY_SCRIPT = ROOT / "rife" / "hls_proxy.py"


def mediamtx_pids() -> list[int]:
    result = subprocess.run(
        ["tasklist", "/FI", "IMAGENAME eq mediamtx.exe", "/FO", "CSV", "/NH"],
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        check=True,
        creationflags=PROCESS_FLAGS,
    )
    pids: list[int] = []
    for row in csv.reader(io.StringIO(result.stdout)):
        if len(row) >= 2 and row[0].lower() == "mediamtx.exe":
            pids.append(int(row[1]))
    return pids


def _creation_flags() -> int:
    if os.name != "nt":
        return 0
    return (
        subprocess.CREATE_NEW_PROCESS_GROUP
        | subprocess.DETACHED_PROCESS
        | subprocess.CREATE_NO_WINDOW
    )


def _read_pid(path) -> int | None:
    if not path.is_file():
        return None
    try:
        return int(path.read_text(encoding="ascii").strip())
    except ValueError:
        path.unlink(missing_ok=True)
        return None


def _stop_pid(pid: int) -> tuple[bool, str]:
    if os.name == "nt":
        result = subprocess.run(
            ["taskkill", "/PID", str(pid), "/T", "/F"],
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            check=False,
            creationflags=PROCESS_FLAGS,
        )
        if result.returncode == 0:
            return True, ""
        return False, result.stderr.strip() or result.stdout.strip()
    try:
        os.kill(pid, 15)
        return True, ""
    except ProcessLookupError:
        return True, ""
    except OSError as exc:
        return False, str(exc)


def start_hls_proxy() -> int:
    if port_open(HLS_PORT):
        if not port_open(HLS_MUXER_PORT):
            print(
                "Port 8888 is still the live muxer; run: python mediamtx.py restart --replace",
                file=sys.stderr,
            )
            return 1
        print("HLS proxy is already running")
        return 0
    deadline = time.monotonic() + 5
    while time.monotonic() < deadline and not port_open(HLS_MUXER_PORT):
        time.sleep(0.1)
    if not port_open(HLS_MUXER_PORT):
        print(
            "HLS muxer is not on 127.0.0.1:8889; restart MediaMTX to pick up mediamtx.yml",
            file=sys.stderr,
        )
        return 1
    if not HLS_PROXY_SCRIPT.is_file():
        print(f"Missing HLS proxy: {HLS_PROXY_SCRIPT}", file=sys.stderr)
        return 1

    with HLS_PROXY_LOG_FILE.open("ab", buffering=0) as log:
        process = subprocess.Popen(
            [sys.executable, str(HLS_PROXY_SCRIPT)],
            cwd=ROOT,
            stdin=subprocess.DEVNULL,
            stdout=log,
            stderr=subprocess.STDOUT,
            creationflags=_creation_flags(),
            close_fds=True,
            start_new_session=os.name != "nt",
        )
    HLS_PROXY_PID_FILE.write_text(str(process.pid), encoding="ascii")

    deadline = time.monotonic() + 5
    while time.monotonic() < deadline:
        if process.poll() is not None:
            print(f"HLS proxy exited with code {process.returncode}", file=sys.stderr)
            print(f"See log: {HLS_PROXY_LOG_FILE}", file=sys.stderr)
            return 1
        if port_open(HLS_PORT):
            print(f"HLS proxy started: PID {process.pid}")
            return 0
        time.sleep(0.1)

    print(f"HLS proxy did not open port {HLS_PORT}; see {HLS_PROXY_LOG_FILE}", file=sys.stderr)
    process.terminate()
    process.wait()
    HLS_PROXY_PID_FILE.unlink(missing_ok=True)
    return 1


def stop_hls_proxy() -> int:
    pid = _read_pid(HLS_PROXY_PID_FILE)
    if pid is None:
        if port_open(HLS_PORT) and not port_open(HLS_MUXER_PORT):
            print("HLS port 8888 is occupied by an unmanaged process", file=sys.stderr)
            return 1
        HLS_PROXY_PID_FILE.unlink(missing_ok=True)
        return 0
    ok, message = _stop_pid(pid)
    HLS_PROXY_PID_FILE.unlink(missing_ok=True)
    if ok:
        print(f"Stopped HLS proxy PID {pid}")
        return 0
    print(f"Could not stop HLS proxy PID {pid}: {message}", file=sys.stderr)
    return 1


def start() -> int:
    if port_open(RTSP_PORT):
        if port_open(API_PORT):
            print("MediaMTX is already running")
            return start_hls_proxy()
        print("RTSP port 8554 is occupied by an incompatible service", file=sys.stderr)
        return 1
    if not MEDIAMTX_BINARY.is_file():
        print(f"Missing MediaMTX binary: {MEDIAMTX_BINARY}", file=sys.stderr)
        return 1
    if not MEDIAMTX_CONFIG.is_file():
        print(f"Missing MediaMTX config: {MEDIAMTX_CONFIG}", file=sys.stderr)
        return 1

    with MEDIAMTX_LOG_FILE.open("ab", buffering=0) as log:
        process = subprocess.Popen(
            [str(MEDIAMTX_BINARY), str(MEDIAMTX_CONFIG)],
            cwd=ROOT,
            stdin=subprocess.DEVNULL,
            stdout=log,
            stderr=subprocess.STDOUT,
            creationflags=_creation_flags(),
            close_fds=True,
            start_new_session=os.name != "nt",
        )
    MEDIAMTX_PID_FILE.write_text(str(process.pid), encoding="ascii")

    deadline = time.monotonic() + 5
    while time.monotonic() < deadline:
        if process.poll() is not None:
            print(f"MediaMTX exited with code {process.returncode}", file=sys.stderr)
            print(f"See log: {MEDIAMTX_LOG_FILE}", file=sys.stderr)
            return 1
        if port_open(RTSP_PORT) and port_open(API_PORT) and port_open(HLS_MUXER_PORT):
            print(f"MediaMTX started: PID {process.pid}")
            return start_hls_proxy()
        time.sleep(0.1)

    if port_open(RTSP_PORT) and port_open(API_PORT):
        print(f"MediaMTX started: PID {process.pid}")
        return start_hls_proxy()

    print(f"MediaMTX did not open RTSP port 8554; see {MEDIAMTX_LOG_FILE}", file=sys.stderr)
    process.terminate()
    process.wait()
    return 1


def stop(replace: bool = False) -> int:
    proxy_result = stop_hls_proxy()
    pids: list[int] = []
    if replace:
        pids = mediamtx_pids()
    elif MEDIAMTX_PID_FILE.is_file():
        pid = _read_pid(MEDIAMTX_PID_FILE)
        if pid is None:
            print(f"Invalid MediaMTX PID file: {MEDIAMTX_PID_FILE}", file=sys.stderr)
            return 1
        pids = [pid]
        if os.name == "nt" and pids[0] not in mediamtx_pids():
            pids = []

    if not pids:
        if port_open(RTSP_PORT):
            print("MediaMTX is running but is not managed by this directory.")
            print("Use: python mediamtx.py restart --replace")
            return 1
        print("MediaMTX is not running")
        MEDIAMTX_PID_FILE.unlink(missing_ok=True)
        return proxy_result

    failed = False
    for pid in pids:
        ok, message = _stop_pid(pid)
        if ok:
            print(f"Stopped MediaMTX PID {pid}")
        else:
            failed = True
            print(f"Could not stop PID {pid}: {message}", file=sys.stderr)
    MEDIAMTX_PID_FILE.unlink(missing_ok=True)
    return int(failed) or proxy_result


def status() -> int:
    pids = mediamtx_pids() if os.name == "nt" else []
    print(f"Processes: {', '.join(map(str, pids)) if pids else 'none'}")
    for port, name in (
        (RTSP_PORT, "RTSP"),
        (HLS_MUXER_PORT, "muxer"),
        (HLS_PORT, "HLS"),
        (API_PORT, "API"),
    ):
        state = "open" if port_open(port) else "closed"
        print(f"{name:6} 127.0.0.1:{port}: {state}")
    return 0 if port_open(RTSP_PORT) else 1


def main() -> int:
    parser = argparse.ArgumentParser(description="Manage the local MediaMTX service")
    subparsers = parser.add_subparsers(dest="command", required=True)
    subparsers.add_parser("start")
    subparsers.add_parser("status")
    stop_parser = subparsers.add_parser("stop")
    stop_parser.add_argument(
        "--replace", action="store_true", help="stop every mediamtx.exe process"
    )
    restart_parser = subparsers.add_parser("restart")
    restart_parser.add_argument(
        "--replace", action="store_true", help="replace an existing external instance"
    )
    args = parser.parse_args()

    if args.command == "start":
        return start()
    if args.command == "status":
        return status()
    if args.command == "stop":
        return stop(args.replace)
    if args.command == "restart":
        result = stop(args.replace)
        if result != 0:
            return result
        return start()
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
