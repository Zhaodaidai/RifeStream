import os
from pathlib import Path
import socket
import subprocess
import tempfile


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


def windows_hls_dir() -> Path:
    base = os.environ.get("LOCALAPPDATA") or tempfile.gettempdir()
    return Path(base) / "rife" / "hls"


def default_hls_dir(_root: Path = ROOT) -> Path:
    # Always local NTFS on Windows. Z: and UNC cannot rename HLS playlists,
    # and a server started from the share would keep serving stale .ts names.
    if os.name == "nt":
        return windows_hls_dir()
    return _root / ".hls"


HLS_DIR = default_hls_dir()
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


def port_open(port: int, timeout: float = 0.5) -> bool:
    try:
        with socket.create_connection(("127.0.0.1", port), timeout=timeout):
            return True
    except OSError:
        return False
