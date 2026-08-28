import base64
import gzip
from pathlib import Path
import subprocess
import sys
import unittest
from urllib.parse import quote

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from rife.paths import PROTOCOL_CLI, STREAM_CLI
from rife.protocol import MpvRequest, ProtocolError, build_stream_command, parse_header, parse_mpv_command, parse_uri


def ush_uri(command: str, target: str = "MPV") -> str:
    payload = base64.b64encode(gzip.compress(command.encode("utf-8"))).decode("ascii")
    return f"ush://{target}?{payload}"


class MpvProtocolTests(unittest.TestCase):
    def test_protocol_cli_runs_with_portable_python(self) -> None:
        result = subprocess.run(
            [
                str(Path(sys.executable)),
                "-P",
                str(PROTOCOL_CLI),
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

        invocation = build_stream_command(request)
        self.assertEqual(Path(invocation[1]).resolve(), STREAM_CLI.resolve())
        self.assertIn("--audio-input", invocation)
        self.assertEqual(invocation.count("--http-header-field"), 3)
        self.assertIn("--start", invocation)

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

    def test_non_http_media_and_header_injection_are_rejected(self) -> None:
        with self.assertRaises(ProtocolError):
            parse_uri(ush_uri('"C:\\private.mp4"'))
        with self.assertRaises(ProtocolError):
            parse_mpv_command(
                '"https://example.com/video.mp4" '
                '--http-header-fields="authorization: secret"'
            )
        with self.assertRaises(ProtocolError):
            parse_header("Referer: good\r\nInjected: bad")

    def test_bad_payload_is_rejected(self) -> None:
        with self.assertRaises(ProtocolError):
            parse_uri("ush://MPV?not-base64")

    def test_start_is_forwarded_to_stream(self) -> None:
        request = MpvRequest("https://example.com/video.mp4", start=42.5)
        invocation = build_stream_command(request)

        self.assertEqual(invocation[invocation.index("--start") + 1], "42.5")


if __name__ == "__main__":
    unittest.main()
