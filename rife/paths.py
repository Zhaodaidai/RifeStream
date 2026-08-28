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
HLS_SERVER_LOG_FILE = ROOT / "hls_server.log"


def is_remote_path(path: Path) -> bool:
    text = os.fspath(path)
    if text.startswith("\\\\") or text.startswith("//"):
        return True
    if os.name != "nt" or len(text) < 2 or text[1] != ":":
        return False
    try:
        import ctypes

        return ctypes.windll.kernel32.GetDriveTypeW(text[:2] + "\\") == 4
    except Exception:
        return False


def default_hls_dir(root: Path = ROOT) -> Path:
    if is_remote_path(root):
        base = os.environ.get("LOCALAPPDATA") or tempfile.gettempdir()
        return Path(base) / "rife" / "hls"
    return root / ".hls"


HLS_DIR = default_hls_dir()
HLS_PLAYLIST = HLS_DIR / "rife" / "index.m3u8"
PROTOCOL_LOG_FILE = ROOT / "mpv_protocol.log"
PLAYLIST_FILE = ROOT / ".playlist.json"
WEBUI_DIR = ROOT / "web"
WEBUI_LOG_FILE = ROOT / "webui.log"

PROCESS_FLAGS = subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0
HTTP_SCHEMES = {"http", "https"}
HLS_PORT = 8888
WEBUI_PORT = 10000


def port_open(port: int, timeout: float = 0.5) -> bool:
    try:
        with socket.create_connection(("127.0.0.1", port), timeout=timeout):
            return True
    except OSError:
        return False
