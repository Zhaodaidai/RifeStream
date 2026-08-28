import argparse
from fractions import Fraction
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from rife.stream import (
    HTTP_RECONNECT_OPTIONS,
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
            [*HTTP_RECONNECT_OPTIONS, "-headers", "referer: https://last.example\r\n"],
        )

    def test_mp4_http_input_does_not_pass_hls_only_options(self) -> None:
        options = ffmpeg_input_options("https://example.com/video.mp4", [], None)
        self.assertEqual(options, list(HTTP_RECONNECT_OPTIONS))
        self.assertNotIn("-http_persistent", options)

    def test_hls_input_disables_persistent_http_connections(self) -> None:
        options = ffmpeg_input_options(
            "https://example.com/video.m3u8?token=value", [], None
        )

        self.assertEqual(options, [*HTTP_RECONNECT_OPTIONS, "-http_persistent", "0"])

    def test_local_input_does_not_enable_http_reconnect(self) -> None:
        self.assertEqual(ffmpeg_input_options("/tmp/video.mp4", [], None), [])

    def test_decoder_seeks_network_input_before_open(self) -> None:
        info = MediaInfo(Fraction(25), 1920, 1080, 600)
        source = StreamInput(
            "https://example.com/video.mp4", None, [], None, info, Fraction(25)
        )
        args = argparse.Namespace(
            max_height=1080,
            gpu=0,
            http_proxy=None,
            start=123.5,
            duration=0,
        )

        command = build_decoder_command(source, args)

        self.assertEqual(command[command.index("-ss") + 1], "123.5")
        self.assertLess(command.index("-ss"), command.index("-i"))

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
            publish_url="/tmp/rife/index.m3u8",
        )

        command = build_encoder_command(source, args)

        for option in (
            ["-preset", "p4"],
            ["-tune", "hq"],
            ["-profile:v", "high"],
            ["-rc", "vbr"],
            ["-cq", "16"],
            ["-multipass", "qres"],
            ["-g", "100"],
            ["-forced-idr", "1"],
            ["-force_key_frames", "expr:gte(n,n_forced*100)"],
            ["-strict_gop", "1"],
            ["-rc-lookahead", "8"],
            ["-bf", "0"],
            ["-fps_mode", "cfr"],
            ["-avoid_negative_ts", "make_zero"],
            ["-hls_playlist_type", "event"],
            ["-hls_list_size", "0"],
            ["-hls_segment_type", "mpegts"],
            ["-hls_flags", "independent_segments+temp_file"],
        ):
            index = command.index(option[0])
            self.assertEqual(command[index : index + 2], option)
        hls_time = command.index("-hls_time")
        self.assertEqual(command[hls_time - 2 : hls_time], ["-f", "hls"])
        self.assertTrue(command[-1].endswith("index.m3u8"))
        self.assertIn("seg%d.ts", command[command.index("-hls_segment_filename") + 1])
        video_input = command.index("-i")
        self.assertEqual(command[video_input - 2 : video_input + 2],
                         ["-f", "yuv4mpegpipe", "-i", "pipe:0"])
        self.assertNotIn("-re", command)
        self.assertNotIn("fullres", command)
        self.assertNotIn("cbr", command)
        self.assertNotIn("rtsp", command)

    def test_encoder_gop_never_exceeds_two_seconds(self) -> None:
        source = StreamInput(
            "https://example.com/video.mp4",
            None,
            [],
            None,
            MediaInfo(Fraction(24_000, 1001), 1920, 1080, 60),
            Fraction(24_000, 1001),
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
            publish_url="/tmp/rife/index.m3u8",
        )

        command = build_encoder_command(source, args)
        gop = int(command[command.index("-g") + 1])
        output_fps = 48_000 / 1001
        self.assertEqual(gop, 95)
        self.assertLessEqual(gop / output_fps, 2.0)
        self.assertEqual(
            command[command.index("-force_key_frames") + 1],
            "expr:gte(n,n_forced*95)",
        )

    def test_encoder_aligns_audio_to_paced_video(self) -> None:
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
            no_audio=False,
            start=0,
            http_proxy=None,
            quality=16,
            audio_codec="aac",
            duration=0,
            publish_url="/tmp/rife/index.m3u8",
        )

        command = build_encoder_command(source, args)

        self.assertEqual(command[command.index("-c:a") + 1], "aac")
        self.assertEqual(command[command.index("-profile:a") + 1], "aac_low")
        self.assertEqual(
            command[command.index("-af") : command.index("-af") + 2],
            ["-af", "aresample=async=1:first_pts=0"],
        )
        audio_input = command.index("-i", command.index("-i") + 1)
        self.assertEqual(
            command[command.index("-readrate") : command.index("-readrate") + 2],
            ["-readrate", "0"],
        )
        self.assertLess(command.index("-readrate"), audio_input)
        self.assertNotIn("-re", command)
        self.assertIn("-shortest", command)

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
