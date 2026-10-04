import base64
import gzip
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch
from urllib.parse import quote

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from rife.paths import CLI
from rife.protocol import (
    MpvRequest,
    ProtocolError,
    add_to_playlist,
    parse_mpv_command,
    parse_uri,
    register_playlist_item,
)


def ush_uri(command: str, target: str = "MPV") -> str:
    payload = base64.b64encode(gzip.compress(command.encode("utf-8"))).decode("ascii")
    return f"ush://{target}?{payload}"


class MpvProtocolTests(unittest.TestCase):
    def test_protocol_cli_runs_with_portable_python(self) -> None:
        result = subprocess.run(
            [
                str(Path(sys.executable)),
                "-P",
                str(CLI),
                "protocol",
                "decode",
                "mpv://https%3A%2F%2Fexample.com%2Fvideo.mp4",
            ],
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            check=False,
        )

        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertNotIn("No module named 'rife'", result.stderr)

    def test_external_player_command_is_mapped(self) -> None:
        command = " ".join(
            [
                '"https://cdn.example/video.m3u8?token=a+b"',
                '--audio-file="https://cdn.example/audio.m4a"',
                '--http-header-fields="origin: https://example.com"',
                '--http-header-fields="referer: https://example.com/watch?id=1"',
                '--http-header-fields="cookie: sid=abc; token=xyz"',
                '--http-proxy="http://127.0.0.1:7890"',
                '--ytdl-raw-options="proxy=[http://127.0.0.1:7890]"',
                '--ytdl-format="bestvideo[height<=?1080]+bestaudio/best"',
                '--script-opts-append="cid=123"',
                '--force-media-title="Example title"',
                '--start="12.5"',
            ]
        )

        request = parse_uri(ush_uri(command))

        self.assertEqual(request.video, "https://cdn.example/video.m3u8?token=a+b")
        self.assertEqual(request.audio, "https://cdn.example/audio.m4a")
        self.assertEqual(
            request.headers,
            [
                "Origin: https://example.com",
                "Referer: https://example.com/watch?id=1",
                "Cookie: sid=abc; token=xyz",
            ],
        )
        self.assertEqual(request.http_proxy, "http://127.0.0.1:7890")
        self.assertEqual(request.ytdl_proxy, "http://127.0.0.1:7890")
        self.assertEqual(request.ytdl_format, "bestvideo[height<=?1080]+bestaudio/best")
        self.assertEqual(request.title, "Example title")
        self.assertEqual(request.start, 12.5)

        self.assertEqual(request.start, 12.5)

    def test_only_ush_mpv_is_accepted(self) -> None:
        uri = ush_uri('"https://example.com/video.mp4"')
        with self.assertRaises(ProtocolError):
            parse_uri(uri.replace("ush://", "rife://", 1))
        with self.assertRaises(ProtocolError):
            parse_uri(ush_uri('"https://example.com/video.mp4"', "PotPlayer"))

    def test_percent_encoded_mpv_url_is_mapped(self) -> None:
        target = "http://192.168.10.1:5244/d/\u5938\u514b\u7f51\u76d8/video.mkv/"
        request = parse_uri(f"mpv://{quote(target, safe='')}")

        self.assertEqual(request, MpvRequest(target))

    def test_mpv_url_requires_an_encoded_http_target(self) -> None:
        with self.assertRaises(ProtocolError):
            parse_uri("mpv://")
        with self.assertRaises(ProtocolError):
            parse_uri("mpv://C%3A%5Cprivate.mkv")
        with self.assertRaises(ProtocolError):
            parse_uri("mpv://https%3A%2F%2Fexample.com%2Fvideo.mkv?raw=query")

    def test_non_http_media_and_unknown_headers_are_rejected(self) -> None:
        with self.assertRaises(ProtocolError):
            parse_uri(ush_uri('"C:\\private.mp4"'))
        with self.assertRaises(ProtocolError):
            parse_mpv_command(
                '"https://example.com/video.mp4" '
                '--http-header-fields="authorization: secret"'
            )

    def test_bad_payload_is_rejected(self) -> None:
        with self.assertRaises(ProtocolError):
            parse_uri("ush://MPV?not-base64")

    def test_protocol_item_is_registered_in_playlist(self) -> None:
        with tempfile.TemporaryDirectory() as folder:
            playlist = Path(folder) / "playlist.json"
            with patch("rife.protocol.PLAYLIST_FILE", playlist):
                register_playlist_item(MpvRequest("https://example.com/video.mp4"))
            data = json.loads(playlist.read_text(encoding="utf-8"))
            self.assertEqual(data["items"][0]["source"], "https://example.com/video.mp4")
            self.assertEqual(data["current_id"], data["items"][0]["id"])

    def test_protocol_item_does_not_replace_current_item(self) -> None:
        with tempfile.TemporaryDirectory() as folder:
            playlist = Path(folder) / "playlist.json"
            playlist.write_text(
                json.dumps(
                    {
                        "items": [
                            {
                                "id": "current",
                                "source": "https://example.com/current.mp4",
                                "title": "current.mp4",
                                "kind": "url",
                            }
                        ],
                        "current_id": "current",
                        "play_generation": 0,
                        "settings": {},
                    }
                ),
                encoding="utf-8",
            )
            with patch("rife.protocol.PLAYLIST_FILE", playlist):
                add_to_playlist(MpvRequest("https://example.com/video.mp4"))
            data = json.loads(playlist.read_text(encoding="utf-8"))
            self.assertEqual(data["current_id"], "current")


if __name__ == "__main__":
    unittest.main()
