"""Serve FFmpeg HLS files on the LAN."""

from __future__ import annotations

import argparse
import errno
from io import BytesIO
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
WIN_SHARING_VIOLATION = 32
WIN_LOCK_VIOLATION = 33
WIN_ACCESS_DENIED = 5
WIN_FILE_NOT_FOUND = 2
WIN_PATH_NOT_FOUND = 3
_PLAYLIST_CACHE: dict[str, bytes] = {}


def retryable_os_error(exc: OSError) -> bool:
    winerror = getattr(exc, "winerror", None)
    if winerror is None and len(exc.args) > 3 and isinstance(exc.args[3], int):
        winerror = exc.args[3]
    if winerror in {WIN_SHARING_VIOLATION, WIN_LOCK_VIOLATION, WIN_ACCESS_DENIED}:
        return True
    return exc.errno in {errno.EACCES, errno.EAGAIN, errno.EBUSY}


def missing_os_error(exc: OSError) -> bool:
    winerror = getattr(exc, "winerror", None)
    if winerror in {WIN_FILE_NOT_FOUND, WIN_PATH_NOT_FOUND}:
        return True
    return exc.errno in {errno.ENOENT}


def playlist_is_usable(data: bytes) -> bool:
    return data.startswith(b"#EXTM3U") and data.endswith(b"\n")


def read_shared(path: str) -> bytes:
    if os.name != "nt":
        with open(path, "rb") as handle:
            return handle.read()
    import ctypes
    import msvcrt
    from ctypes import wintypes

    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    kernel32.CreateFileW.restype = wintypes.HANDLE
    kernel32.CreateFileW.argtypes = [
        wintypes.LPCWSTR,
        wintypes.DWORD,
        wintypes.DWORD,
        wintypes.LPVOID,
        wintypes.DWORD,
        wintypes.DWORD,
        wintypes.HANDLE,
    ]
    handle = kernel32.CreateFileW(
        path,
        0x80000000,
        0x00000007,
        None,
        3,
        0x80,
        None,
    )
    if handle in (wintypes.HANDLE(-1).value, 0):
        last_error = ctypes.get_last_error()
        raise OSError(0, "CreateFileW failed", path, last_error)
    try:
        fd = msvcrt.open_osfhandle(int(handle), os.O_RDONLY)
    except OSError:
        kernel32.CloseHandle(handle)
        raise
    with os.fdopen(fd, "rb") as file:
        return file.read()


def read_hls_bytes(path: str, attempts: int = 10) -> bytes:
    last_error: OSError | None = None
    for _ in range(attempts):
        try:
            data = read_shared(path)
            if path.lower().endswith(".ts") and len(data) != os.path.getsize(path):
                time.sleep(0.05)
                continue
            return data
        except OSError as exc:
            last_error = exc
            if missing_os_error(exc):
                raise
            if retryable_os_error(exc):
                time.sleep(0.05)
                continue
            raise
    if last_error is not None:
        raise last_error
    raise OSError("failed to read HLS file")


def load_playlist(path: str) -> bytes:
    data: bytes | None = None
    try:
        data = read_hls_bytes(path)
    except OSError:
        data = None
    if data and playlist_is_usable(data):
        _PLAYLIST_CACHE[path] = data
        return data
    cached = _PLAYLIST_CACHE.get(path)
    if cached:
        return cached
    if data:
        return data
    raise FileNotFoundError(path)


class HlsHandler(SimpleHTTPRequestHandler):
    protocol_version = "HTTP/1.1"

    def __init__(self, *args, **kwargs):
        super().__init__(*args, directory=str(HLS_DIR), **kwargs)

    def send_head(self):
        path = self.translate_path(self.path)
        lowered = path.lower()
        if lowered.endswith(".m3u8"):
            try:
                data = load_playlist(path)
            except OSError:
                self.send_error(404, "File not found")
                return None
            return self._send_bytes(path, data)
        if lowered.endswith(".ts"):
            try:
                data = read_hls_bytes(path)
            except OSError as exc:
                if missing_os_error(exc):
                    self.send_error(404, "File not found")
                    return None
                self.send_response(503)
                self.send_header("Retry-After", "1")
                self.send_header("Content-Length", "0")
                self.end_headers()
                return None
            return self._send_bytes(path, data)
        return super().send_head()

    def _send_bytes(self, path: str, data: bytes) -> BytesIO:
        self.send_response(200)
        self.send_header("Content-type", self.guess_type(path))
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        return BytesIO(data)

    def end_headers(self) -> None:
        self.send_header("Access-Control-Allow-Origin", "*")
        if urlsplit(self.path).path.endswith(".m3u8"):
            self.send_header("Cache-Control", "no-store, max-age=0")
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
