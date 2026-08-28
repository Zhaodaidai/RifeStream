import os
from pathlib import Path
import socket
import subprocess


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
MEDIAMTX_BINARY = ROOT / "mediamtx.exe"
MEDIAMTX_CONFIG = ROOT / "mediamtx.yml"
STREAM_PID_FILE = ROOT / ".stream.pid"
STREAM_STATUS_FILE = ROOT / ".stream.status.json"
MEDIAMTX_PID_FILE = ROOT / ".mediamtx.pid"
HLS_PROXY_PID_FILE = ROOT / ".hls_proxy.pid"
MEDIAMTX_LOG_FILE = ROOT / "mediamtx.log"
HLS_PROXY_LOG_FILE = ROOT / "hls_proxy.log"
PROTOCOL_LOG_FILE = ROOT / "mpv_protocol.log"
PLAYLIST_FILE = ROOT / ".playlist.json"
WEBUI_DIR = ROOT / "web"
WEBUI_LOG_FILE = ROOT / "webui.log"

PROCESS_FLAGS = subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0
HTTP_SCHEMES = {"http", "https"}
RTSP_PORT = 8554
HLS_PORT = 8888
HLS_MUXER_PORT = 8889
API_PORT = 9997
WEBUI_PORT = 10000


def port_open(port: int, timeout: float = 0.5) -> bool:
    try:
        with socket.create_connection(("127.0.0.1", port), timeout=timeout):
            return True
    except OSError:
        return False
