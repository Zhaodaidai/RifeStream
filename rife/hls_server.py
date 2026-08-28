"""Serve FFmpeg HLS files on the LAN."""

from __future__ import annotations

import argparse
import os
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
import subprocess
import sys
import time
from urllib.parse import urlsplit

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from rife.paths import (
    HLS_DIR,
    HLS_PORT,
    HLS_SERVER_LOG_FILE,
    HLS_SERVER_PID_FILE,
    PROCESS_FLAGS,
    port_open,
)

HLS_SERVER_SCRIPT = ROOT / "rife" / "hls_server.py"


class HlsHandler(SimpleHTTPRequestHandler):
    protocol_version = "HTTP/1.1"

    def __init__(self, *args, **kwargs):
        super().__init__(*args, directory=str(HLS_DIR), **kwargs)

    def end_headers(self) -> None:
        self.send_header("Access-Control-Allow-Origin", "*")
        if urlsplit(self.path).path.endswith(".m3u8"):
            self.send_header("Cache-Control", "no-store")
        super().end_headers()

    def guess_type(self, path: str) -> str:
        lowered = path.lower()
        if lowered.endswith(".m3u8"):
            return "application/vnd.apple.mpegurl"
        if lowered.endswith(".ts"):
            return "video/mp2t"
        return super().guess_type(path)

    def do_OPTIONS(self) -> None:
        self.send_response(204)
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Methods", "GET, HEAD, OPTIONS")
        self.send_header("Access-Control-Allow-Headers", "*")
        self.send_header("Content-Length", "0")
        self.end_headers()

    def log_message(self, format: str, *args: object) -> None:
        sys.stderr.write("%s - %s\n" % (self.address_string(), format % args))


def _creation_flags() -> int:
    if os.name != "nt":
        return 0
    return (
        subprocess.CREATE_NEW_PROCESS_GROUP
        | subprocess.DETACHED_PROCESS
        | subprocess.CREATE_NO_WINDOW
    )


def _read_pid(path: Path) -> int | None:
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


def serve() -> int:
    HLS_DIR.mkdir(parents=True, exist_ok=True)
    server = ThreadingHTTPServer(("0.0.0.0", HLS_PORT), HlsHandler)
    server.serve_forever()
    return 0


def start() -> int:
    pid = _read_pid(HLS_SERVER_PID_FILE)
    if pid is not None and port_open(HLS_PORT):
        print("HLS server is already running")
        return 0
    if port_open(HLS_PORT):
        print(f"Port {HLS_PORT} is occupied by another process", file=sys.stderr)
        return 1

    with HLS_SERVER_LOG_FILE.open("ab", buffering=0) as log:
        process = subprocess.Popen(
            [sys.executable, str(HLS_SERVER_SCRIPT), "serve"],
            cwd=ROOT,
            stdin=subprocess.DEVNULL,
            stdout=log,
            stderr=subprocess.STDOUT,
            creationflags=_creation_flags(),
            close_fds=True,
            start_new_session=os.name != "nt",
        )
    HLS_SERVER_PID_FILE.write_text(str(process.pid), encoding="ascii")

    deadline = time.monotonic() + 5
    while time.monotonic() < deadline:
        if process.poll() is not None:
            print(f"HLS server exited with code {process.returncode}", file=sys.stderr)
            print(f"See log: {HLS_SERVER_LOG_FILE}", file=sys.stderr)
            HLS_SERVER_PID_FILE.unlink(missing_ok=True)
            return 1
        if port_open(HLS_PORT):
            print(f"HLS server started: PID {process.pid}")
            return 0
        time.sleep(0.1)

    print(f"HLS server did not open port {HLS_PORT}; see {HLS_SERVER_LOG_FILE}", file=sys.stderr)
    process.terminate()
    process.wait()
    HLS_SERVER_PID_FILE.unlink(missing_ok=True)
    return 1


def stop() -> int:
    pid = _read_pid(HLS_SERVER_PID_FILE)
    if pid is None:
        if port_open(HLS_PORT):
            print(f"HLS port {HLS_PORT} is occupied by an unmanaged process", file=sys.stderr)
            return 1
        print("HLS server is not running")
        HLS_SERVER_PID_FILE.unlink(missing_ok=True)
        return 0
    ok, message = _stop_pid(pid)
    HLS_SERVER_PID_FILE.unlink(missing_ok=True)
    if ok:
        print(f"Stopped HLS server PID {pid}")
        return 0
    print(f"Could not stop HLS server PID {pid}: {message}", file=sys.stderr)
    return 1


def status() -> int:
    state = "open" if port_open(HLS_PORT) else "closed"
    print(f"HLS  127.0.0.1:{HLS_PORT}: {state}")
    return 0 if port_open(HLS_PORT) else 1


def main() -> int:
    parser = argparse.ArgumentParser(description="Serve local HLS output")
    parser.add_argument(
        "command",
        choices=("serve", "start", "stop", "status", "restart"),
        nargs="?",
        default="serve",
    )
    args = parser.parse_args()
    if args.command == "serve":
        return serve()
    if args.command == "start":
        return start()
    if args.command == "status":
        return status()
    if args.command == "stop":
        return stop()
    result = stop()
    if result != 0:
        return result
    return start()


if __name__ == "__main__":
    raise SystemExit(main())
