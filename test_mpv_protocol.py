import base64
import gzip
from pathlib import Path
import sys
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parent))

import mpv_protocol
import stream


def ush_uri(command: str, target: str = "MPV") -> str:
    payload = base64.b64encode(gzip.compress(command.encode("utf-8"))).decode("ascii")
    return f"ush://{target}?{payload}"


class MpvProtocolTests(unittest.TestCase):
    def test_external_player_command_is_mapped(self) -> None:
        command = " ".join(
            [
                '"https://cdn.example/video.m3u8?token=a+b"',
                '--audio-file="https://cdn.example/audio.m4a"',
                '--sub-file="https://cdn.example/sub.vtt"',
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

        request = mpv_protocol.parse_ush_uri(ush_uri(command))

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

        invocation = mpv_protocol.stream_command(request)
        self.assertEqual(Path(invocation[1]).name, "stream.py")
        self.assertIn("--audio-input", invocation)
        self.assertEqual(invocation.count("--http-header-field"), 3)
        self.assertIn("--start", invocation)

    def test_only_ush_mpv_is_accepted(self) -> None:
        uri = ush_uri('"https://example.com/video.mp4"')
        with self.assertRaises(mpv_protocol.ProtocolError):
            mpv_protocol.parse_ush_uri(uri.replace("ush://", "rife://", 1))
        with self.assertRaises(mpv_protocol.ProtocolError):
            mpv_protocol.parse_ush_uri(ush_uri('"https://example.com/video.mp4"', "PotPlayer"))

    def test_non_http_media_and_header_injection_are_rejected(self) -> None:
        with self.assertRaises(mpv_protocol.ProtocolError):
            mpv_protocol.parse_ush_uri(ush_uri('"C:\\private.mp4"'))
        with self.assertRaises(mpv_protocol.ProtocolError):
            mpv_protocol.parse_mpv_command(
                '"https://example.com/video.mp4" '
                '--http-header-fields="authorization: secret"'
            )
        with self.assertRaises(mpv_protocol.ProtocolError):
            mpv_protocol.parse_header("Referer: good\r\nInjected: bad")

    def test_bad_payload_is_rejected(self) -> None:
        with self.assertRaises(mpv_protocol.ProtocolError):
            mpv_protocol.parse_ush_uri("ush://MPV?not-base64")


class StreamInputTests(unittest.TestCase):
    def test_headers_are_deduplicated_case_insensitively(self) -> None:
        headers = stream.normalize_headers(
            ["Referer: https://first.example", "referer: https://last.example"]
        )
        self.assertEqual(headers, ["referer: https://last.example"])
        self.assertEqual(
            stream.ffmpeg_input_options(headers, None),
            ["-headers", "referer: https://last.example\r\n"],
        )

    def test_header_line_break_is_rejected(self) -> None:
        with self.assertRaises(ValueError):
            stream.normalize_headers(["Cookie: ok\nInjected: no"])

    def test_network_input_gets_a_default_user_agent(self) -> None:
        headers = stream.network_headers(["Referer: https://example.com/watch"])
        self.assertTrue(any(value.startswith("User-Agent: Mozilla/") for value in headers))
        self.assertEqual(headers[-1], "Referer: https://example.com/watch")


if __name__ == "__main__":
    unittest.main()
