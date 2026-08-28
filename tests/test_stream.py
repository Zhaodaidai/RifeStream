import argparse
from fractions import Fraction
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from rife.stream import (
    MediaInfo,
    StreamInput,
    build_decoder_command,
    build_encoder_command,
    build_environment,
    build_vspipe_command,
    ffmpeg_input_options,
    normalize_headers,
    video_size,
)


class StreamInputTests(unittest.TestCase):
    def test_headers_are_deduplicated_case_insensitively(self) -> None:
        headers = normalize_headers(
            ["Referer: https://first.example", "referer: https://last.example"]
        )
        self.assertEqual(headers, ["referer: https://last.example"])
        self.assertEqual(
            ffmpeg_input_options("https://example.com/video.mp4", headers, None),
            ["-headers", "referer: https://last.example\r\n"],
        )

    def test_hls_input_disables_persistent_http_connections(self) -> None:
        options = ffmpeg_input_options(
            "https://example.com/video.m3u8?token=value", [], None
        )

        self.assertEqual(options, ["-http_persistent", "0"])

    def test_network_input_is_scaled_before_the_raw_pipe(self) -> None:
        info = MediaInfo(Fraction(25), 3840, 2160, 60)
        source = StreamInput(
            "https://example.com/video.m3u8", None, [], None, info, Fraction(25)
        )
        args = argparse.Namespace(
            max_height=1080,
            gpu=0,
            http_proxy=None,
            start=0,
            duration=0,
        )

        command = build_decoder_command(source, args)

        self.assertEqual(video_size(info, 1080), (1920, 1080))
        self.assertIn("-hwaccel", command)
        self.assertIn("cuda", command)
        self.assertIn(
            "scale_cuda=1920:1080:format=yuv420p:interp_algo=bilinear,"
            "hwdownload,format=yuv420p,fps=25/1",
            command,
        )
        self.assertIn("-extra_hw_frames", command)

    def test_network_frame_count_does_not_overrun_the_decoder(self) -> None:
        source = StreamInput(
            "https://example.com/video.mp4",
            None,
            [],
            None,
            MediaInfo(Fraction(24_000, 1001), 1920, 1080, 98.596),
            Fraction(24_000, 1001),
        )
        args = argparse.Namespace(
            factor=2,
            max_height=1080,
            gpu=0,
            gpu_threads=2,
            scene_mode=1,
            workspace_mib=0,
            start=0,
            duration=0,
        )

        environment = build_environment(source, args)

        self.assertEqual(environment["RIFE_PIPE_FRAMES"], "2362")

    def test_encoder_uses_realtime_constant_quality(self) -> None:
        source = StreamInput(
            "https://example.com/video.mp4",
            None,
            [],
            None,
            MediaInfo(Fraction(25), 1920, 1080, 60),
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

        command = build_encoder_command(source, args)

        for option in (
            ["-preset", "p4"],
            ["-tune", "hq"],
            ["-profile:v", "high"],
            ["-rc", "vbr"],
            ["-cq", "16"],
            ["-multipass", "qres"],
            ["-rc-lookahead", "8"],
            ["-bf", "0"],
            ["-pkt_size", "1400"],
        ):
            index = command.index(option[0])
            self.assertEqual(command[index : index + 2], option)
        self.assertNotIn("-re", command)
        self.assertNotIn("fullres", command)
        self.assertNotIn("cbr", command)

    def test_vspipe_requests_match_tensorrt_streams(self) -> None:
        source = StreamInput(
            "https://example.com/video.mp4",
            None,
            [],
            None,
            MediaInfo(Fraction(25), 1920, 1080, 60),
            Fraction(25),
        )
        args = argparse.Namespace(gpu_threads=2)

        command = build_vspipe_command(source, args)

        self.assertEqual(
            command[command.index("--requests") : command.index("--requests") + 2],
            ["--requests", "2"],
        )
        self.assertNotIn("--arg", command)


if __name__ == "__main__":
    unittest.main()
