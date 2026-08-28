import argparse
import csv
import io
import os
import subprocess
import sys
import time

from rife.paths import (
    API_PORT,
    HLS_PORT,
    MEDIAMTX_BINARY,
    MEDIAMTX_CONFIG,
    MEDIAMTX_LOG_FILE,
    MEDIAMTX_PID_FILE,
    PROCESS_FLAGS,
    ROOT,
    RTSP_PORT,
    port_open,
)


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


def start() -> int:
    if port_open(RTSP_PORT):
        if port_open(API_PORT):
            print("MediaMTX is already running")
            return 0
        print("RTSP port 8554 is occupied by an incompatible service", file=sys.stderr)
        return 1
    if not MEDIAMTX_BINARY.is_file():
        print(f"Missing MediaMTX binary: {MEDIAMTX_BINARY}", file=sys.stderr)
        return 1
    if not MEDIAMTX_CONFIG.is_file():
        print(f"Missing MediaMTX config: {MEDIAMTX_CONFIG}", file=sys.stderr)
        return 1

    creation_flags = 0
    if os.name == "nt":
        creation_flags = (
            subprocess.CREATE_NEW_PROCESS_GROUP
            | subprocess.DETACHED_PROCESS
            | subprocess.CREATE_NO_WINDOW
        )

    with MEDIAMTX_LOG_FILE.open("ab", buffering=0) as log:
        process = subprocess.Popen(
            [str(MEDIAMTX_BINARY), str(MEDIAMTX_CONFIG)],
            cwd=ROOT,
            stdin=subprocess.DEVNULL,
            stdout=log,
            stderr=subprocess.STDOUT,
            creationflags=creation_flags,
            close_fds=True,
        )
    MEDIAMTX_PID_FILE.write_text(str(process.pid), encoding="ascii")

    deadline = time.monotonic() + 5
    while time.monotonic() < deadline:
        if process.poll() is not None:
            print(f"MediaMTX exited with code {process.returncode}", file=sys.stderr)
            print(f"See log: {MEDIAMTX_LOG_FILE}", file=sys.stderr)
            return 1
        if port_open(RTSP_PORT) and port_open(API_PORT):
            print(f"MediaMTX started: PID {process.pid}")
            return 0
        time.sleep(0.1)

    print(f"MediaMTX did not open RTSP port 8554; see {MEDIAMTX_LOG_FILE}", file=sys.stderr)
    process.terminate()
    process.wait()
    return 1


def stop(replace: bool = False) -> int:
    pids: list[int] = []
    if replace:
        pids = mediamtx_pids()
    elif MEDIAMTX_PID_FILE.is_file():
        try:
            pids = [int(MEDIAMTX_PID_FILE.read_text(encoding="ascii").strip())]
        except ValueError:
            print(f"Invalid MediaMTX PID file: {MEDIAMTX_PID_FILE}", file=sys.stderr)
            return 1
        if pids[0] not in mediamtx_pids():
            pids = []

    if not pids:
        if port_open(RTSP_PORT):
            print("MediaMTX is running but is not managed by this directory.")
            print("Use: python mediamtx.py restart --replace")
            return 1
        print("MediaMTX is not running")
        MEDIAMTX_PID_FILE.unlink(missing_ok=True)
        return 0

    failed = False
    for pid in pids:
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
            print(f"Stopped MediaMTX PID {pid}")
        else:
            failed = True
            message = result.stderr.strip() or result.stdout.strip()
            print(f"Could not stop PID {pid}: {message}", file=sys.stderr)
    MEDIAMTX_PID_FILE.unlink(missing_ok=True)
    return int(failed)


def status() -> int:
    pids = mediamtx_pids()
    print(f"Processes: {', '.join(map(str, pids)) if pids else 'none'}")
    for port, name in (
        (RTSP_PORT, "RTSP"),
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
