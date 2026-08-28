"""Serve MediaMTX HLS on the public port with EVENT playlists."""

from __future__ import annotations

from http.client import HTTPConnection
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from rife.hls import as_event_playlist
from rife.paths import HLS_MUXER_PORT, HLS_PORT

HOP_BY_HOP = {
    "connection",
    "keep-alive",
    "proxy-authenticate",
    "proxy-authorization",
    "te",
    "trailers",
    "transfer-encoding",
    "upgrade",
}


class HlsProxyHandler(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"

    def do_OPTIONS(self) -> None:
        self.send_response(204)
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Methods", "GET, HEAD, OPTIONS")
        self.send_header("Access-Control-Allow-Headers", "*")
        self.send_header("Content-Length", "0")
        self.end_headers()

    def do_HEAD(self) -> None:
        self._proxy()

    def do_GET(self) -> None:
        self._proxy()

    def log_message(self, format: str, *args: object) -> None:
        return

    def _proxy(self) -> None:
        header_tuples = [
            (key, value)
            for key, value in self.headers.items()
            if key.lower() not in HOP_BY_HOP and key.lower() != "host"
        ]
        connection = HTTPConnection("127.0.0.1", HLS_MUXER_PORT, timeout=30)
        try:
            connection.request(self.command, self.path, headers=dict(header_tuples))
            upstream = connection.getresponse()
            payload = upstream.read()
        except OSError:
            self.send_error(502, "HLS muxer unavailable")
            return
        finally:
            connection.close()

        content_type = upstream.getheader("Content-Type", "")
        rewrite = self.command != "HEAD" and (
            "mpegurl" in content_type.lower() or self.path.split("?", 1)[0].endswith(".m3u8")
        )
        if rewrite:
            payload = as_event_playlist(payload.decode("utf-8", "replace")).encode("utf-8")

        self.send_response(upstream.status)
        self.send_header("Access-Control-Allow-Origin", "*")
        for key, value in upstream.getheaders():
            lowered = key.lower()
            if lowered in HOP_BY_HOP or lowered in {"content-length", "access-control-allow-origin"}:
                continue
            if rewrite and lowered == "content-encoding":
                continue
            self.send_header(key, value)
        if self.command == "HEAD":
            length = upstream.getheader("Content-Length", "0")
            self.send_header("Content-Length", length)
            self.end_headers()
            return
        self.send_header("Content-Length", str(len(payload)))
        self.end_headers()
        self.wfile.write(payload)


def main() -> int:
    server = ThreadingHTTPServer(("0.0.0.0", HLS_PORT), HlsProxyHandler)
    server.serve_forever()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
