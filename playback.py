import hashlib
import json
import os
from dataclasses import asdict
from datetime import datetime
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
import socket
import subprocess
import sys
import threading
import time
from typing import Any
from urllib.error import HTTPError
from urllib.request import Request, urlopen

ROOT = Path(__file__).resolve().parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
STREAM = ROOT / "stream.py"

from mpv_protocol import (
    LOG_FILE,
    PROXY_SCHEMES,
    MpvRequest,
    parse_header,
    validate_url,
)


HOST = "0.0.0.0"
PORT = 8090
PLAYER = ROOT / "player.html"
STATUS_FILE = ROOT / ".playback_status.json"
PATHS_API = "http://127.0.0.1:9997/v3/paths/list"
MAX_BODY = 256_000
SERVER_VERSION = hashlib.sha256(
    b"".join(
        (ROOT / name).read_bytes()
        for name in ("playback.py", "mpv_protocol.py", "stream.py")
    )
).hexdigest()[:16]


def request_from_json(value: Any) -> MpvRequest:
    if not isinstance(value, dict):
        raise ValueError("request must be an object")
    if not isinstance(value.get("video"), str):
        raise ValueError("video must be a string")
    headers = value.get("headers", [])
    if not isinstance(headers, list) or not all(isinstance(item, str) for item in headers):
        raise ValueError("headers must be a list of strings")
    optional = ("audio", "title", "http_proxy", "ytdl_proxy", "ytdl_format")
    for name in optional:
        if name in value and value[name] is not None and not isinstance(value[name], str):
            raise ValueError(f"{name} must be a string or null")
    start = value.get("start", 0)
    if not isinstance(start, (int, float)):
        raise ValueError("start must be numeric")
    request = MpvRequest(
        video=validate_url(value.get("video", ""), "video"),
        audio=validate_url(value["audio"], "audio") if value.get("audio") else None,
        title=value.get("title"),
        start=float(start),
        headers=[parse_header(item) for item in headers],
        http_proxy=value.get("http_proxy"),
        ytdl_proxy=value.get("ytdl_proxy"),
        ytdl_format=value.get("ytdl_format"),
    )
    if request.start < 0:
        raise ValueError("start cannot be negative")
    if request.http_proxy:
        validate_url(request.http_proxy, "HTTP proxy")
    if request.ytdl_proxy:
        validate_url(request.ytdl_proxy, "yt-dlp proxy", PROXY_SCHEMES)
    return request


def build_stream_command(
    request: MpvRequest, position: float, status_file: Path
) -> list[str]:
    command = [sys.executable, str(STREAM), request.video]
    for header in request.headers:
        command.extend(["--http-header-field", header])
    options = {
        "audio-input": request.audio,
        "http-proxy": request.http_proxy,
        "ytdl-proxy": request.ytdl_proxy,
        "ytdl-format": request.ytdl_format,
        "title": request.title,
        "start": format(position, ".12g"),
        "status-file": str(status_file),
    }
    for name, option in options.items():
        if option:
            command.extend([f"--{name}", option])
    return command


def stop_process_tree(process: subprocess.Popen[bytes] | None) -> None:
    if process is None or process.poll() is not None:
        return
    if os.name == "nt":
        subprocess.run(
            ["taskkill", "/PID", str(process.pid), "/T", "/F"],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            check=True,
            creationflags=subprocess.CREATE_NO_WINDOW,
        )
    else:
        process.terminate()
        try:
            process.wait(timeout=5)
        except subprocess.TimeoutExpired:
            process.kill()
            process.wait()


def source_id() -> str | None:
    try:
        with urlopen(PATHS_API, timeout=0.5) as response:
            value = json.load(response)
    except OSError:
        return None
    items = value.get("items")
    if not isinstance(items, list):
        raise ValueError("MediaMTX returned an invalid path list")
    path = next(
        (item for item in items if isinstance(item, dict) and item.get("name") == "rife"),
        None,
    )
    if path is None or path.get("online") is not True:
        return None
    source = path.get("source")
    if not isinstance(source, dict):
        raise ValueError("MediaMTX returned an invalid source")
    identifier = source.get("id")
    if not isinstance(identifier, str):
        raise ValueError("MediaMTX returned an invalid source ID")
    return identifier


class PlaybackSession:
    def __init__(self) -> None:
        self.lock = threading.RLock()
        self.request: MpvRequest | None = None
        self.process: subprocess.Popen[bytes] | None = None
        self.generation = 0
        self.offset = 0.0
        self.duration: float | None = None
        self.title: str | None = None
        self.state = "idle"
        self.error: str | None = None
        self.stream_started_at = 0.0

    def load(self, request: MpvRequest) -> dict[str, Any]:
        with self.lock:
            self.request = request
            self.duration = None
            self.title = request.title
            LOG_FILE.write_text(
                f"Started: {datetime.now().isoformat(timespec='seconds')}\n"
                f"Video: {request.video}\n"
                f"HTTP headers: {len(request.headers)}\n"
                f"yt-dlp: {'yes' if request.ytdl_format else 'no'}\n",
                encoding="utf-8",
            )
            return self._restart(request, request.start)

    def seek(self, position: float) -> dict[str, Any]:
        if position < 0:
            raise ValueError("position cannot be negative")
        with self.lock:
            if self.request is None:
                raise ValueError("no media is loaded")
            if self.duration is not None:
                position = min(position, max(0.0, self.duration - 3.0))
            return self._restart(self.request, position)

    def stop(self) -> dict[str, Any]:
        with self.lock:
            self._freeze_position()
            self.generation += 1
            stop_process_tree(self.process)
            self.process = None
            STATUS_FILE.unlink(missing_ok=True)
            self.state = "stopped"
            self.error = None
            return self.status()

    def _restart(self, request: MpvRequest, position: float) -> dict[str, Any]:
        old_source_id = source_id()
        stop_process_tree(self.process)
        self.process = None
        STATUS_FILE.unlink(missing_ok=True)
        self.generation += 1
        generation = self.generation
        self.offset = position
        self.stream_started_at = 0.0
        self.state = "starting"
        self.error = None

        command = build_stream_command(request, position, STATUS_FILE)
        creation_flags = 0
        if os.name == "nt":
            creation_flags = subprocess.CREATE_NEW_PROCESS_GROUP | subprocess.CREATE_NO_WINDOW
        with LOG_FILE.open("ab", buffering=0) as log:
            log.write(f"\nSeek: {position:.3f}s (generation {generation})\n".encode())
            self.process = subprocess.Popen(
                command,
                cwd=ROOT,
                stdout=log,
                stderr=subprocess.STDOUT,
                creationflags=creation_flags,
            )
        threading.Thread(
            target=self._monitor,
            args=(self.process, generation, old_source_id),
            daemon=True,
        ).start()
        return self.status()

    def _monitor(
        self,
        process: subprocess.Popen[bytes],
        generation: int,
        old_source_id: str | None,
    ) -> None:
        while process.poll() is None:
            try:
                current_source_id = source_id()
            except ValueError as exc:
                stop_process_tree(process)
                with self.lock:
                    if generation == self.generation:
                        self.process = None
                        self.state = "error"
                        self.error = str(exc)
                return
            if current_source_id is not None and current_source_id != old_source_id:
                with self.lock:
                    if generation == self.generation and self.state == "starting":
                        self.state = "streaming"
                        self.stream_started_at = time.monotonic()
                break
            time.sleep(0.25)
        exit_code = process.wait()
        with self.lock:
            if generation != self.generation:
                return
            self._freeze_position()
            self.process = None
            if exit_code == 0:
                self.state = "ended"
            else:
                self.state = "error"
                self.error = self._log_tail() or f"RIFE exited with code {exit_code}"

    def _refresh_metadata(self) -> None:
        if not STATUS_FILE.is_file():
            return
        value = json.loads(STATUS_FILE.read_text(encoding="utf-8"))
        duration = value.get("duration")
        if isinstance(duration, (int, float)) and duration > 0:
            self.duration = float(duration)
        if not self.title and isinstance(value.get("title"), str):
            self.title = value["title"]

    def _current_position(self) -> float:
        position = self.offset
        if self.stream_started_at:
            position += max(0.0, time.monotonic() - self.stream_started_at)
        return min(position, self.duration) if self.duration is not None else position

    def _freeze_position(self) -> None:
        self.offset = self._current_position()
        self.stream_started_at = 0.0

    @staticmethod
    def _log_tail() -> str | None:
        if not LOG_FILE.is_file():
            return None
        lines = [
            line.strip()
            for line in LOG_FILE.read_text(
                encoding="utf-8", errors="replace"
            ).splitlines()
            if line.strip()
        ]
        return " | ".join(lines[-3:]) or None

    def status(self) -> dict[str, Any]:
        with self.lock:
            self._refresh_metadata()
            return {
                "state": self.state,
                "generation": self.generation,
                "position": self._current_position(),
                "offset": self.offset,
                "duration": self.duration,
                "title": self.title or "RIFE",
                "error": self.error,
            }

    def close(self) -> None:
        with self.lock:
            stop_process_tree(self.process)
            self.process = None


class PlaybackHandler(BaseHTTPRequestHandler):
    server: "PlaybackServer"

    def log_message(self, _format: str, *_args: object) -> None:
        pass

    def send_json(self, value: Any, status: int = 200) -> None:
        content = json.dumps(value, ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Cache-Control", "no-store")
        self.send_header("Content-Length", str(len(content)))
        self.end_headers()
        self.wfile.write(content)

    def read_json(self) -> Any:
        try:
            length = int(self.headers.get("Content-Length", "0"))
        except ValueError as exc:
            raise ValueError("invalid content length") from exc
        if length <= 0 or length > MAX_BODY:
            raise ValueError("invalid request size")
        return json.loads(self.rfile.read(length))

    def do_GET(self) -> None:
        path = self.path.partition("?")[0]
        if path == "/api/status":
            self.send_json(self.server.session.status())
            return
        if path not in {"/", "/player.html"}:
            self.send_error(404)
            return
        try:
            content = PLAYER.read_bytes()
        except OSError as exc:
            self.send_error(500, str(exc))
            return
        self.send_response(200)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Cache-Control", "no-store")
        self.send_header("Content-Length", str(len(content)))
        self.end_headers()
        self.wfile.write(content)

    def do_POST(self) -> None:
        try:
            local = self.client_address[0] in {"127.0.0.1", "::1"}
            if self.path == "/api/shutdown" and local:
                self.send_json({"state": "stopping"})
                self.server.shutdown()
                return
            value = self.read_json()
            if self.path == "/api/seek":
                result = self.server.session.seek(float(value["position"]))
            elif self.path == "/api/stop":
                result = self.server.session.stop()
            elif self.path == "/api/load" and local:
                if self.headers.get("X-RIFE-Version") != self.server.version:
                    self.send_json({"error": "playback control is outdated"}, 409)
                    return
                result = self.server.session.load(request_from_json(value))
            else:
                self.send_error(404)
                return
            self.send_json(result)
        except (KeyError, TypeError, ValueError, json.JSONDecodeError) as exc:
            self.send_json({"error": str(exc)}, 400)
        except OSError as exc:
            self.send_json({"error": str(exc)}, 500)


class PlaybackServer(ThreadingHTTPServer):
    daemon_threads = True
    allow_reuse_address = False

    def __init__(self, address: tuple[str, int], session: PlaybackSession) -> None:
        self.session = session
        self.version = SERVER_VERSION
        super().__init__(address, PlaybackHandler)


def submit_to_existing(request: MpvRequest) -> bool:
    data = json.dumps(asdict(request)).encode("utf-8")
    http_request = Request(
        f"http://127.0.0.1:{PORT}/api/load",
        data=data,
        headers={"Content-Type": "application/json", "X-RIFE-Version": SERVER_VERSION},
        method="POST",
    )
    try:
        with urlopen(http_request, timeout=10) as response:
            return response.status == 200
    except HTTPError as exc:
        if exc.code != 409:
            return False
        shutdown_request = Request(
            f"http://127.0.0.1:{PORT}/api/shutdown",
            data=b"{}",
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        try:
            with urlopen(shutdown_request, timeout=5):
                pass
        except OSError as shutdown_error:
            raise OSError("outdated playback control could not be stopped") from shutdown_error
        deadline = time.monotonic() + 5
        while time.monotonic() < deadline:
            try:
                connection = socket.create_connection(("127.0.0.1", PORT), timeout=0.2)
                connection.close()
            except OSError:
                return False
            time.sleep(0.05)
        raise OSError("outdated playback control did not release its port")
    except OSError:
        return False


def run_or_update(request: MpvRequest) -> int:
    if submit_to_existing(request):
        return 0
    interpreter = Path(sys.executable)
    pythonw = interpreter.with_name("pythonw.exe")
    if os.name == "nt" and pythonw.is_file():
        interpreter = pythonw
    flags = 0
    if os.name == "nt":
        flags = (
            subprocess.CREATE_NEW_PROCESS_GROUP
            | subprocess.DETACHED_PROCESS
            | subprocess.CREATE_NO_WINDOW
        )
    subprocess.Popen(
        [str(interpreter), str(Path(__file__).resolve())],
        cwd=ROOT,
        stdin=subprocess.DEVNULL,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        creationflags=flags,
        close_fds=True,
    )
    deadline = time.monotonic() + 5
    while time.monotonic() < deadline:
        if submit_to_existing(request):
            return 0
        time.sleep(0.1)
    raise OSError(f"playback control did not open port {PORT}")


if __name__ == "__main__":
    session = PlaybackSession()
    server = PlaybackServer((HOST, PORT), session)
    print(f"Playback control: http://127.0.0.1:{PORT}")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        session.close()
        server.server_close()
