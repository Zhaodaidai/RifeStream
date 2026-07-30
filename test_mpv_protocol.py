import argparse
import base64
from fractions import Fraction
import gzip
from pathlib import Path
import subprocess
import sys
import threading
import unittest
from unittest.mock import patch
from urllib.parse import quote

sys.path.insert(0, str(Path(__file__).resolve().parent))

import mpv_protocol
import playback
import stream


def ush_uri(command: str, target: str = "MPV") -> str:
    payload = base64.b64encode(gzip.compress(command.encode("utf-8"))).decode("ascii")
    return f"ush://{target}?{payload}"


class MpvProtocolTests(unittest.TestCase):
    def test_protocol_cli_runs_with_portable_python(self) -> None:
        result = subprocess.run(
            [
                str(Path(sys.executable)),
                str(Path(mpv_protocol.__file__)),
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

        request = mpv_protocol.parse_uri(ush_uri(command))

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

        invocation = playback.build_stream_command(request, request.start, Path("status.json"))
        self.assertEqual(Path(invocation[1]).name, "stream.py")
        self.assertIn("--audio-input", invocation)
        self.assertEqual(invocation.count("--http-header-field"), 3)
        self.assertIn("--start", invocation)

    def test_only_ush_mpv_is_accepted(self) -> None:
        uri = ush_uri('"https://example.com/video.mp4"')
        with self.assertRaises(mpv_protocol.ProtocolError):
            mpv_protocol.parse_uri(uri.replace("ush://", "rife://", 1))
        with self.assertRaises(mpv_protocol.ProtocolError):
            mpv_protocol.parse_uri(ush_uri('"https://example.com/video.mp4"', "PotPlayer"))

    def test_percent_encoded_mpv_url_is_mapped(self) -> None:
        target = "http://192.168.10.1:5244/d/\u5938\u514b\u7f51\u76d8/video.mkv/"
        request = mpv_protocol.parse_uri(f"mpv://{quote(target, safe='')}")

        self.assertEqual(request, mpv_protocol.MpvRequest(target))

    def test_mpv_url_requires_an_encoded_http_target(self) -> None:
        with self.assertRaises(mpv_protocol.ProtocolError):
            mpv_protocol.parse_uri("mpv://")
        with self.assertRaises(mpv_protocol.ProtocolError):
            mpv_protocol.parse_uri("mpv://C%3A%5Cprivate.mkv")
        with self.assertRaises(mpv_protocol.ProtocolError):
            mpv_protocol.parse_uri("mpv://https%3A%2F%2Fexample.com%2Fvideo.mkv?raw=query")

    def test_non_http_media_and_header_injection_are_rejected(self) -> None:
        with self.assertRaises(mpv_protocol.ProtocolError):
            mpv_protocol.parse_uri(ush_uri('"C:\\private.mp4"'))
        with self.assertRaises(mpv_protocol.ProtocolError):
            mpv_protocol.parse_mpv_command(
                '"https://example.com/video.mp4" '
                '--http-header-fields="authorization: secret"'
            )
        with self.assertRaises(mpv_protocol.ProtocolError):
            mpv_protocol.parse_header("Referer: good\r\nInjected: bad")

    def test_bad_payload_is_rejected(self) -> None:
        with self.assertRaises(mpv_protocol.ProtocolError):
            mpv_protocol.parse_uri("ush://MPV?not-base64")

    def test_seek_override_and_status_file_are_forwarded(self) -> None:
        request = mpv_protocol.MpvRequest("https://example.com/video.mp4", start=2)
        invocation = playback.build_stream_command(request, 42.5, Path("status.json"))

        self.assertEqual(invocation[invocation.index("--start") + 1], "42.5")
        self.assertEqual(
            invocation[invocation.index("--status-file") + 1], "status.json"
        )

    def test_playback_load_request_is_revalidated(self) -> None:
        request = playback.request_from_json(
            {
                "video": "https://example.com/video.mp4",
                "headers": ["Referer: https://example.com/watch"],
                "start": 3,
            }
        )
        self.assertEqual(request.start, 3)
        with self.assertRaises(ValueError):
            playback.request_from_json(
                {"video": "https://example.com/video.mp4", "headers": "bad"}
            )

    def test_seek_near_end_keeps_an_hls_generation_window(self) -> None:
        session = playback.PlaybackSession()
        session.request = mpv_protocol.MpvRequest("https://example.com/video.mp4")
        session.duration = 10

        with patch.object(session, "_restart", return_value={}) as restart:
            session.seek(9.9)

        restart.assert_called_once_with(session.request, 7)

    def test_outdated_playback_server_is_stopped(self) -> None:
        session = playback.PlaybackSession()
        with patch.object(playback, "SERVER_VERSION", "old"):
            server = playback.PlaybackServer(("127.0.0.1", 0), session)

        def serve() -> None:
            try:
                server.serve_forever()
            finally:
                server.server_close()

        thread = threading.Thread(target=serve)
        thread.start()

        with (
            patch.object(playback, "PORT", server.server_port),
            patch.object(playback, "SERVER_VERSION", "new"),
        ):
            accepted = playback.submit_to_existing(
                mpv_protocol.MpvRequest("https://example.com/video.mp4")
            )

        thread.join(timeout=2)
        self.assertFalse(accepted)
        self.assertFalse(thread.is_alive())


class StreamInputTests(unittest.TestCase):
    def test_headers_are_deduplicated_case_insensitively(self) -> None:
        headers = stream.normalize_headers(
            ["Referer: https://first.example", "referer: https://last.example"]
        )
        self.assertEqual(headers, ["referer: https://last.example"])
        self.assertEqual(
            stream.ffmpeg_input_options("https://example.com/video.mp4", headers, None),
            ["-headers", "referer: https://last.example\r\n"],
        )

    def test_header_line_break_is_rejected(self) -> None:
        with self.assertRaises(ValueError):
            stream.normalize_headers(["Cookie: ok\nInjected: no"])

    def test_hls_input_disables_persistent_http_connections(self) -> None:
        options = stream.ffmpeg_input_options(
            "https://example.com/video.m3u8?token=value", [], None
        )

        self.assertEqual(options, ["-http_persistent", "0"])

    def test_network_input_is_scaled_before_the_raw_pipe(self) -> None:
        info = stream.MediaInfo(Fraction(25), 3840, 2160, 60)
        source = stream.StreamInput(
            "https://example.com/video.m3u8", None, [], None, info, Fraction(25)
        )
        args = argparse.Namespace(
            max_height=1080,
            http_proxy=None,
            start=0,
            duration=0,
        )

        command = stream.build_decoder_command(source, args)

        self.assertEqual(stream.video_size(info, 1080), (1920, 1080))
        self.assertIn("fps=25/1,scale=1920:1080,format=yuv420p", command)

    def test_encoder_uses_visually_lossless_constant_quality(self) -> None:
        source = stream.StreamInput(
            "https://example.com/video.mp4",
            None,
            [],
            None,
            stream.MediaInfo(Fraction(25), 1920, 1080, 60),
            Fraction(25),
        )
        args = argparse.Namespace(
            gop=0,
            factor=2,
            no_audio=True,
            start=0,
            http_proxy=None,
            quality=16,
            audio_codec="libopus",
            duration=0,
            publish_url="rtsp://127.0.0.1:8554/rife",
        )

        command = stream.build_encoder_command(source, args)

        for option in (
            ["-preset", "p7"],
            ["-tune", "hq"],
            ["-profile:v", "high"],
            ["-rc", "vbr"],
            ["-cq", "16"],
            ["-multipass", "fullres"],
        ):
            index = command.index(option[0])
            self.assertEqual(command[index : index + 2], option)
        self.assertNotIn("cbr", command)


if __name__ == "__main__":
    unittest.main()
