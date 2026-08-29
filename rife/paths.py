import os
from pathlib import Path
import socket
import subprocess
import tempfile
from urllib.parse import urlsplit


ROOT = Path(__file__).resolve().parent.parent
RUNTIME = ROOT / "runtime"
VSPIPE = RUNTIME / "VSPipe.exe"
FFMPEG = RUNTIME / "ffmpeg" / "ffmpeg.exe"
FFPROBE = RUNTIME / "ffmpeg" / "ffprobe.exe"
PYTHON = RUNTIME / "python.exe"
RIFE_SCRIPT = ROOT / "vs" / "rife_stream.vpy"
PROBE_SCRIPT = ROOT / "vs" / "probe_plugins.vpy"
STREAM_CLI = ROOT / "stream.py"
PROTOCOL_CLI = ROOT / "mpv_protocol.py"
STREAM_PID_FILE = ROOT / ".stream.pid"
STREAM_STATUS_FILE = ROOT / ".stream.status.json"
HLS_SERVER_PID_FILE = ROOT / ".hls_server.pid"
HLS_SERVER_DIR_FILE = ROOT / ".hls_server.dir"
HLS_SERVER_LOG_FILE = ROOT / "hls_server.log"


def windows_rife_dir() -> Path:
    base = os.environ.get("LOCALAPPDATA") or tempfile.gettempdir()
    return Path(base) / "rife"


def windows_hls_dir() -> Path:
    return windows_rife_dir() / "hls"


def default_hls_dir(_root: Path = ROOT) -> Path:
    # Always local NTFS on Windows. Z: and UNC cannot rename HLS playlists,
    # and a server started from the share would keep serving stale .ts names.
    if os.name == "nt":
        return windows_hls_dir()
    return _root / ".hls"


def default_engine_dir(_root: Path = ROOT) -> Path:
    # TensorRT cannot reliably read/write *.engine.cache on UNC/Z: shares
    # (mixed separators like //host/share/runtime/vs-plugins\models\...).
    if os.name == "nt":
        return windows_rife_dir() / "engines"
    return _root / ".engines"


HLS_DIR = default_hls_dir()
ENGINE_DIR = default_engine_dir()
HLS_PLAYLIST = HLS_DIR / "rife" / "index.m3u8"
PROTOCOL_LOG_FILE = ROOT / "mpv_protocol.log"
PLAYLIST_FILE = ROOT / ".playlist.json"
WEBUI_DIR = ROOT / "web"
WEBUI_LOG_FILE = ROOT / "webui.log"

if os.name == "nt":
    PROCESS_FLAGS = subprocess.CREATE_NO_WINDOW
    DETACHED_FLAGS = (
        PROCESS_FLAGS
        | subprocess.CREATE_NEW_PROCESS_GROUP
        | subprocess.DETACHED_PROCESS
    )
else:
    PROCESS_FLAGS = 0
    DETACHED_FLAGS = 0
HTTP_SCHEMES = {"http", "https"}
HLS_PORT = 8888
WEBUI_PORT = 10000


def is_http_source(source: str) -> bool:
    return urlsplit(source).scheme.lower() in HTTP_SCHEMES


def port_open(port: int, timeout: float = 0.5) -> bool:
    try:
        with socket.create_connection(("127.0.0.1", port), timeout=timeout):
            return True
    except OSError:
        return False


def capture(
    command: list[str], *, cwd: Path | None = ROOT
) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        command,
        cwd=cwd,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        check=False,
        creationflags=PROCESS_FLAGS,
    )


def read_pid(path: Path, *, unlink_invalid: bool = False) -> int | None:
    if not path.is_file():
        return None
    try:
        return int(path.read_text(encoding="ascii").strip())
    except ValueError:
        if unlink_invalid:
            path.unlink(missing_ok=True)
        return None


def pid_is_running(pid: int) -> bool:
    if os.name == "nt":
        result = capture(
            ["tasklist", "/FI", f"PID eq {pid}", "/FO", "CSV", "/NH"], cwd=None
        )
        return str(pid) in result.stdout
    try:
        os.kill(pid, 0)
    except OSError:
        return False
    return True


def stop_pid_tree(pid: int) -> tuple[bool, str]:
    if os.name == "nt":
        result = capture(["taskkill", "/PID", str(pid), "/T", "/F"], cwd=None)
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


def replace_existing_stream() -> None:
    if not STREAM_PID_FILE.is_file():
        return
    pid = read_pid(STREAM_PID_FILE)
    if pid is None:
        STREAM_PID_FILE.unlink(missing_ok=True)
        STREAM_STATUS_FILE.unlink(missing_ok=True)
        return
    if pid != os.getpid():
        if os.name == "nt":
            stop_pid_tree(pid)
        else:
            try:
                os.kill(pid, 15)
            except ProcessLookupError:
                pass
    STREAM_PID_FILE.unlink(missing_ok=True)
    STREAM_STATUS_FILE.unlink(missing_ok=True)
