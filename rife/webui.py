from __future__ import annotations

import argparse
from dataclasses import asdict, dataclass, field
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
import math
import os
from pathlib import Path
import posixpath
import socket
import subprocess
import sys
import threading
from typing import Any
from urllib.parse import unquote, urlsplit
import uuid
import time

from rife.paths import (
    HLS_PORT,
    HTTP_SCHEMES,
    PLAYLIST_FILE,
    PROCESS_FLAGS,
    ROOT,
    STREAM_CLI,
    STREAM_PID_FILE,
    STREAM_STATUS_FILE,
    WEBUI_DIR,
    WEBUI_LOG_FILE,
    WEBUI_PORT,
)
from rife.stream import ensure_mediamtx, is_http_source, replace_existing_stream


@dataclass
class Playback:
    item_id: str | None = None
    start: float = 0.0
    spawned_at: float | None = None
    duration: float | None = None


PLAYBACK = Playback()
FILE_SCHEMES = {"file"}


@dataclass
class SkipSettings:
    intro: float = 0.0
    outro: float = 0.0
    skip_intro: bool = False
    skip_outro: bool = False


@dataclass
class PlaylistItem:
    id: str
    source: str
    title: str
    kind: str


@dataclass
class PlayerState:
    items: list[PlaylistItem] = field(default_factory=list)
    current_id: str | None = None
    play_generation: int = 0
    last_error: str | None = None
    settings: SkipSettings = field(default_factory=SkipSettings)


class Playlist:
    def __init__(self, path: Path = PLAYLIST_FILE) -> None:
        self.path = path
        self._lock = threading.Lock()
        self.state = PlayerState()
        self.load()

    def load(self) -> None:
        if not self.path.is_file():
            return
        try:
            data = json.loads(self.path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return
        items = [
            PlaylistItem(
                id=str(item.get("id") or uuid.uuid4()),
                source=str(item["source"]),
                title=str(item.get("title") or display_title(item["source"])),
                kind=str(item.get("kind") or source_kind(item["source"])),
            )
            for item in data.get("items", [])
            if isinstance(item, dict) and item.get("source")
        ]
        current = data.get("current_id")
        if current not in {item.id for item in items}:
            current = items[0].id if items else None
        self.state = PlayerState(
            items,
            current,
            int(data.get("play_generation") or 0),
            settings=parse_settings(data.get("settings")),
        )

    def save(self) -> None:
        payload = {
            "items": [asdict(item) for item in self.state.items],
            "current_id": self.state.current_id,
            "play_generation": self.state.play_generation,
            "settings": asdict(self.state.settings),
        }
        self.path.write_text(
            json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8"
        )

    def snapshot(self) -> dict[str, Any]:
        with self._lock:
            current = self.current()
            index = self.index_of(self.state.current_id)
            return {
                "items": [asdict(item) for item in self.state.items],
                "current_id": self.state.current_id,
                "current": asdict(current) if current else None,
                "index": index,
                "total": len(self.state.items),
                "has_prev": index is not None and index > 0,
                "has_next": index is not None and index < len(self.state.items) - 1,
                "play_generation": self.state.play_generation,
                "streaming": stream_running(),
                "last_error": self.state.last_error,
                "hls_url": hls_playlist_url(),
                "settings": asdict(self.state.settings),
                **playback_snapshot(stream_running(), current is not None),
            }

    def current(self) -> PlaylistItem | None:
        return self.item(self.state.current_id)

    def item(self, item_id: str | None) -> PlaylistItem | None:
        if not item_id:
            return None
        return next((item for item in self.state.items if item.id == item_id), None)

    def index_of(self, item_id: str | None) -> int | None:
        if not item_id:
            return None
        for index, item in enumerate(self.state.items):
            if item.id == item_id:
                return index
        return None

    def add_sources(self, sources: list[str]) -> list[PlaylistItem]:
        added: list[PlaylistItem] = []
        errors: list[str] = []
        with self._lock:
            existing = {item.source for item in self.state.items}
            for raw in sources:
                try:
                    source = normalize_playlist_source(raw)
                except ValueError as exc:
                    errors.append(str(exc))
                    continue
                if source in existing:
                    continue
                item = PlaylistItem(
                    id=str(uuid.uuid4()),
                    source=source,
                    title=display_title(source),
                    kind=source_kind(source),
                )
                self.state.items.append(item)
                existing.add(source)
                added.append(item)
            if not added and errors:
                raise ValueError(errors[0])
            if added and self.state.current_id is None:
                self.state.current_id = added[0].id
            self.state.last_error = errors[0] if errors else None
            self.save()
        return added

    def remove(self, item_id: str) -> None:
        with self._lock:
            self.state.items = [item for item in self.state.items if item.id != item_id]
            if self.state.current_id == item_id:
                self.state.current_id = (
                    self.state.items[0].id if self.state.items else None
                )
            self.save()

    def clear(self) -> None:
        with self._lock:
            settings = self.state.settings
            self.state = PlayerState(settings=settings)
            self.save()

    def update_settings(self, payload: dict[str, Any]) -> SkipSettings:
        with self._lock:
            self.state.settings = parse_settings(payload, self.state.settings, strict=True)
            self.save()
            return self.state.settings

    def settings(self) -> SkipSettings:
        with self._lock:
            return self.state.settings

    def select(self, item_id: str | None = None, offset: int = 0) -> PlaylistItem:
        with self._lock:
            if item_id:
                item = self.item(item_id)
                if item is None:
                    raise ValueError("Playlist item not found")
            else:
                index = self.index_of(self.state.current_id)
                if index is None:
                    if not self.state.items:
                        raise ValueError("Playlist is empty")
                    index = 0
                index += offset
                if index < 0 or index >= len(self.state.items):
                    raise ValueError("No more items in that direction")
                item = self.state.items[index]
            self.state.current_id = item.id
            self.state.play_generation += 1
            self.state.last_error = None
            self.save()
            return item

    def set_error(self, message: str) -> None:
        with self._lock:
            self.state.last_error = message
            self.save()


def display_title(source: str) -> str:
    parsed = urlsplit(source)
    if parsed.scheme.lower() in HTTP_SCHEMES:
        name = unquote(posixpath.basename(parsed.path.rstrip("/")))
        return name or parsed.netloc or source
    return Path(source).name or source


def source_kind(source: str) -> str:
    return "url" if is_http_source(source) else "file"


def is_loopback_host(host: str) -> bool:
    value = host.strip("[]").lower()
    return (
        not value
        or value in {"localhost", "0.0.0.0", "::", "::1"}
        or value.startswith("127.")
    )


def lan_ipv4() -> str:
    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        sock.connect(("8.8.8.8", 80))
        ip = sock.getsockname()[0]
    except OSError:
        ip = "127.0.0.1"
    finally:
        sock.close()
    return ip if ip and not is_loopback_host(ip) else "127.0.0.1"


def hls_playlist_url(_host_header: str | None = None) -> str:
    return f"http://{lan_ipv4()}:{HLS_PORT}/rife/index.m3u8"


def parse_sources(text: str) -> list[str]:
    sources: list[str] = []
    for line in text.replace("\r", "\n").split("\n"):
        line = line.strip().strip('"').strip("'")
        if line:
            sources.append(line)
    return sources


def normalize_playlist_source(source: str) -> str:
    source = source.strip().strip('"').strip("'")
    parsed = urlsplit(source)
    scheme = parsed.scheme.lower()
    if scheme in HTTP_SCHEMES:
        if not parsed.netloc:
            raise ValueError(f"Invalid URL: {source}")
        return source
    if scheme in FILE_SCHEMES:
        source = unquote(parsed.path)
        if os.name == "nt" and source.startswith("/") and len(source) > 2 and source[2] == ":":
            source = source[1:]
    path = Path(source).expanduser()
    if not path.is_absolute():
        path = (Path.cwd() / path).resolve()
    else:
        path = path.resolve()
    if not path.is_file():
        raise ValueError(f"File not found: {path}")
    return str(path)


def stream_running() -> bool:
    if not STREAM_PID_FILE.is_file():
        return False
    try:
        pid = int(STREAM_PID_FILE.read_text(encoding="ascii").strip())
    except ValueError:
        return False
    if os.name == "nt":
        result = subprocess.run(
            ["tasklist", "/FI", f"PID eq {pid}", "/FO", "CSV", "/NH"],
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            check=False,
            creationflags=PROCESS_FLAGS,
        )
        return str(pid) in result.stdout
    try:
        os.kill(pid, 0)
    except OSError:
        return False
    return True


def read_stream_status() -> dict[str, Any] | None:
    if not STREAM_STATUS_FILE.is_file():
        return None
    try:
        data = json.loads(STREAM_STATUS_FILE.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    return data if isinstance(data, dict) else None


def finite_seconds(value: object) -> float | None:
    try:
        result = float(value)
    except (TypeError, ValueError):
        return None
    return result if math.isfinite(result) else None


def parse_settings(
    payload: object,
    current: SkipSettings | None = None,
    *,
    strict: bool = False,
) -> SkipSettings:
    base = current or SkipSettings()
    if not isinstance(payload, dict):
        if strict:
            raise ValueError("Settings object required")
        return SkipSettings(base.intro, base.outro, base.skip_intro, base.skip_outro)

    def seconds(key: str, fallback: float) -> float:
        if key not in payload:
            return fallback
        value = finite_seconds(payload.get(key))
        if value is None or value < 0:
            if strict:
                raise ValueError(f"{key} must be a non-negative number of seconds")
            return fallback
        return value

    def flag(key: str, fallback: bool) -> bool:
        if key not in payload:
            return fallback
        value = payload.get(key)
        if isinstance(value, bool):
            return value
        if strict:
            raise ValueError(f"{key} must be a boolean")
        return bool(value)

    return SkipSettings(
        intro=seconds("intro", base.intro),
        outro=seconds("outro", base.outro),
        skip_intro=flag("skip_intro", base.skip_intro),
        skip_outro=flag("skip_outro", base.skip_outro),
    )


def effective_start(requested: float, settings: SkipSettings) -> float:
    start = max(0.0, requested)
    if start == 0 and settings.skip_intro and settings.intro > 0:
        return settings.intro
    return start


def encode_duration(start: float, duration: float | None, settings: SkipSettings) -> float:
    if not settings.skip_outro or settings.outro <= 0 or duration is None or duration <= 0:
        return 0.0
    end = max(0.0, duration - settings.outro)
    if end <= start:
        return 0.0
    return end - start


def outro_reached(position: float, duration: float | None, settings: SkipSettings) -> bool:
    if not settings.skip_outro or settings.outro <= 0 or duration is None or duration <= 0:
        return False
    # Wall-clock UI position runs even while RIFE is behind; wait extra so
    # skip-outro does not kill the current encode and look like a restart.
    return position >= max(0.0, duration - settings.outro) + 20.0


def estimate_position(
    start: float,
    spawned_at: float | None,
    now: float,
    duration: float | None,
    streaming: bool,
) -> float:
    position = start
    if streaming and spawned_at is not None:
        position = start + max(0.0, now - spawned_at)
    if duration is not None:
        position = min(position, duration)
    return max(0.0, position)


def clamp_seek(seconds: float, duration: float | None) -> float:
    if not math.isfinite(seconds) or seconds < 0:
        raise ValueError("Seek position must be a non-negative number")
    if duration is not None and duration > 0:
        return min(seconds, max(0.0, duration - 0.25))
    return seconds


def remember_playback(item_id: str, start: float) -> None:
    if PLAYBACK.item_id != item_id:
        PLAYBACK.duration = None
    PLAYBACK.item_id = item_id
    PLAYBACK.start = start
    PLAYBACK.spawned_at = time.time()


def reset_playback() -> None:
    PLAYBACK.item_id = None
    PLAYBACK.start = 0.0
    PLAYBACK.spawned_at = None
    PLAYBACK.duration = None


def playback_snapshot(
    streaming: bool,
    has_current: bool = True,
    now: float | None = None,
) -> dict[str, Any]:
    now = time.time() if now is None else now
    start = PLAYBACK.start
    spawned_at = PLAYBACK.spawned_at
    duration = PLAYBACK.duration
    status = read_stream_status()
    if status:
        status_started = finite_seconds(status.get("started_at"))
        if (
            spawned_at is not None
            and status_started is not None
            and status_started + 0.05 < spawned_at
        ):
            status = None
    if status:
        status_duration = finite_seconds(status.get("duration"))
        if duration is None and status_duration is not None:
            duration = status_duration
            PLAYBACK.duration = duration
        if spawned_at is None:
            status_start = finite_seconds(status.get("start"))
            if status_start is not None:
                start = max(0.0, status_start)
            spawned_at = finite_seconds(status.get("started_at"))
    position = estimate_position(start, spawned_at, now, duration, streaming)
    return {
        "duration": duration,
        "position": position,
        "start": start,
        "seekable": has_current and duration is not None and duration > 0,
    }


PLAYBACK_ERROR_PREFIXES = ("Error:", "Required file not found:")


def stream_command(
    source: str,
    title: str | None,
    start: float = 0.0,
    duration: float = 0.0,
) -> list[str]:
    command = [sys.executable, "-u", str(STREAM_CLI), source]
    if title:
        command.extend(["--title", title])
    if start > 0:
        command.extend(["--start", format(start, ".12g")])
    if duration > 0:
        command.extend(["--duration", format(duration, ".12g")])
    return command


def relay_stream_output(pipe: Any, header: str) -> None:
    WEBUI_LOG_FILE.parent.mkdir(parents=True, exist_ok=True)
    with WEBUI_LOG_FILE.open("a", encoding="utf-8", errors="replace") as log:
        log.write(header)
        log.flush()
        sys.stderr.write(header)
        sys.stderr.flush()
        if pipe is None:
            return
        while True:
            line = pipe.readline()
            if line == "":
                break
            if not line.endswith("\n"):
                line += "\n"
            log.write(line)
            log.flush()
            sys.stderr.write(line)
            sys.stderr.flush()
            stripped = line.strip()
            if stripped.startswith(PLAYBACK_ERROR_PREFIXES):
                PLAYLIST.set_error(stripped)


def spawn_stream(
    source: str,
    title: str | None,
    start: float = 0.0,
    duration: float = 0.0,
) -> None:
    command = stream_command(source, title, start, duration)
    flags = 0
    extra: dict[str, Any] = {}
    if os.name == "nt":
        flags = (
            subprocess.CREATE_NEW_PROCESS_GROUP
            | subprocess.DETACHED_PROCESS
            | subprocess.CREATE_NO_WINDOW
        )
    else:
        extra["start_new_session"] = True
    process = subprocess.Popen(
        command,
        cwd=ROOT,
        stdin=subprocess.DEVNULL,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        creationflags=flags,
        close_fds=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        bufsize=1,
        **extra,
    )
    threading.Thread(
        target=relay_stream_output,
        args=(process.stdout, f"\nPlay: {source} start={start}\n"),
        daemon=True,
        name="rife-stream-log",
    ).start()


def stop_stream() -> None:
    PLAYBACK.spawned_at = None
    replace_existing_stream()


def read_json(handler: BaseHTTPRequestHandler) -> dict[str, Any]:
    length = int(handler.headers.get("Content-Length") or 0)
    if length <= 0:
        return {}
    payload = handler.rfile.read(length)
    if not payload:
        return {}
    data = json.loads(payload.decode("utf-8"))
    if not isinstance(data, dict):
        raise ValueError("JSON object required")
    return data


def content_type(path: Path) -> str:
    suffix = path.suffix.lower()
    return {
        ".css": "text/css; charset=utf-8",
        ".html": "text/html; charset=utf-8",
        ".js": "text/javascript; charset=utf-8",
        ".svg": "image/svg+xml",
        ".json": "application/json; charset=utf-8",
    }.get(suffix, "application/octet-stream")


PLAYLIST = Playlist()


class WebHandler(BaseHTTPRequestHandler):
    server_version = "RifeWebUI/1.0"

    def log_message(self, format: str, *args: object) -> None:
        message = "%s - %s\n" % (self.address_string(), format % args)
        with WEBUI_LOG_FILE.open("a", encoding="utf-8") as log:
            log.write(message)

    def do_GET(self) -> None:
        parsed = urlsplit(self.path)
        path = unquote(parsed.path)
        if path == "/api/state":
            self.send_json(self.state_payload())
            return
        self.serve_static(path)

    def do_POST(self) -> None:
        parsed = urlsplit(self.path)
        path = unquote(parsed.path)
        try:
            body = read_json(self)
        except (ValueError, json.JSONDecodeError) as exc:
            self.send_json({"error": str(exc)}, 400)
            return
        try:
            if path == "/api/items":
                sources = body.get("sources")
                if isinstance(sources, str):
                    sources = parse_sources(sources)
                if not isinstance(sources, list) or not sources:
                    raise ValueError("Provide at least one file path or URL")
                added = PLAYLIST.add_sources([str(item) for item in sources])
                play = bool(body.get("play"))
                if play and added:
                    start_item(added[0].id)
                self.send_json({"added": [asdict(item) for item in added], **self.state_payload()})
                return
            if path == "/api/play":
                item_id = body.get("id")
                offset = int(body.get("offset") or 0)
                start = finite_seconds(body.get("start")) or 0.0
                item = start_item(str(item_id) if item_id else None, offset, start)
                self.send_json({"playing": asdict(item), **self.state_payload()})
                return
            if path == "/api/seek":
                seconds = finite_seconds(body.get("seconds"))
                if seconds is None:
                    raise ValueError("Seek position is required")
                item = seek_to(seconds)
                self.send_json({"seeking": asdict(item), **self.state_payload()})
                return
            if path == "/api/stop":
                stop_stream()
                self.send_json(self.state_payload())
                return
            if path == "/api/settings":
                PLAYLIST.update_settings(body)
                self.send_json(self.state_payload())
                return
            if path == "/api/clear":
                stop_stream()
                reset_playback()
                PLAYLIST.clear()
                self.send_json(self.state_payload())
                return
        except ValueError as exc:
            self.send_json({"error": str(exc)}, 400)
            return
        self.send_json({"error": "Not found"}, 404)

    def do_DELETE(self) -> None:
        parsed = urlsplit(self.path)
        path = unquote(parsed.path)
        prefix = "/api/items/"
        if not path.startswith(prefix):
            self.send_json({"error": "Not found"}, 404)
            return
        item_id = path[len(prefix) :]
        current = PLAYLIST.current()
        PLAYLIST.remove(item_id)
        if current and current.id == item_id:
            stop_stream()
            reset_playback()
        self.send_json(self.state_payload())

    def serve_static(self, path: str) -> None:
        if path == "/":
            path = "/index.html"
        relative = path.lstrip("/")
        file_path = (WEBUI_DIR / relative).resolve()
        if WEBUI_DIR.resolve() not in file_path.parents and file_path != WEBUI_DIR.resolve():
            self.send_json({"error": "Not found"}, 404)
            return
        if not file_path.is_file():
            self.send_json({"error": "Not found"}, 404)
            return
        data = file_path.read_bytes()
        self.send_response(200)
        self.send_header("Content-Type", content_type(file_path))
        self.send_header("Content-Length", str(len(data)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(data)

    def state_payload(self) -> dict[str, Any]:
        maybe_skip_outro()
        payload = PLAYLIST.snapshot()
        payload["hls_url"] = hls_playlist_url()
        return payload

    def send_json(self, payload: dict[str, Any], status: int = 200) -> None:
        if status >= 400:
            path = unquote(urlsplit(self.path).path)
            message = str(payload.get("error") or payload)
            if path.startswith("/api/"):
                print(message, file=sys.stderr, flush=True)
                PLAYLIST.set_error(message)
        data = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(data)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(data)


def start_item(item_id: str | None, offset: int = 0, start: float = 0.0) -> PlaylistItem:
    item = PLAYLIST.select(item_id, offset)
    settings = PLAYLIST.settings()
    duration = PLAYBACK.duration if PLAYBACK.item_id == item.id else None
    start = clamp_seek(effective_start(start, settings), duration)
    remember_playback(item.id, start)
    spawn_stream(
        item.source,
        item.title,
        start,
        encode_duration(start, duration, settings),
    )
    return item


def seek_to(seconds: float) -> PlaylistItem:
    item = PLAYLIST.current()
    if item is None:
        raise ValueError("No media selected")
    settings = PLAYLIST.settings()
    duration = PLAYBACK.duration
    if duration is None:
        status = read_stream_status()
        if status:
            duration = finite_seconds(status.get("duration"))
    seconds = clamp_seek(seconds, duration)
    current_position = playback_snapshot(stream_running(), True)["position"]
    if abs(seconds - current_position) < 2.0:
        return item
    remember_playback(item.id, seconds)
    spawn_stream(
        item.source,
        item.title,
        seconds,
        encode_duration(seconds, duration, settings),
    )
    return item


def maybe_skip_outro() -> None:
    settings = PLAYLIST.settings()
    if not settings.skip_outro or settings.outro <= 0:
        return
    if not stream_running() or PLAYLIST.current() is None:
        return
    snapshot = playback_snapshot(True, True)
    if not outro_reached(snapshot["position"], snapshot["duration"], settings):
        return
    try:
        start_item(None, offset=1)
    except ValueError:
        stop_stream()


def ensure_services() -> None:
    ensure_mediamtx()


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="RIFE playlist web UI")
    parser.add_argument("--host", default="0.0.0.0")
    parser.add_argument("--port", type=int, default=WEBUI_PORT)
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    if not WEBUI_DIR.is_dir():
        print(f"Missing web files: {WEBUI_DIR}", file=sys.stderr)
        return 2
    try:
        ensure_services()
    except (OSError, RuntimeError) as exc:
        print(f"Warning: MediaMTX is not available ({exc})", file=sys.stderr)
    server = ThreadingHTTPServer((args.host, args.port), WebHandler)
    lan = lan_ipv4()
    print(f"Web UI : http://127.0.0.1:{args.port}")
    print(f"LAN    : http://{lan}:{args.port}")
    print(f"HLS    : http://{lan}:{HLS_PORT}/rife/index.m3u8")
    print("Stop   : Ctrl+C", flush=True)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print()
        return 0
    finally:
        server.server_close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
