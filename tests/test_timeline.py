"""Shared timebase contracts without FFmpeg, VapourSynth or GPU dependencies."""
import argparse
from dataclasses import FrozenInstanceError
from fractions import Fraction
import math
import unittest
from unittest.mock import Mock, patch

from rife import stream


class TimelineTests(unittest.TestCase):
    def source(self, duration=60, network=True):
        return stream.StreamInput(
            'https://example.com/video.mp4' if network else '/tmp/video.mkv',
            None, [], None,
            stream.MediaInfo(Fraction(24000, 1001), 1920, 1080, duration),
            Fraction(24000, 1001), subtitle='/tmp/sub.ass',
        )

    def args(self, **changes):
        values = dict(start=12.5, duration=10.25, factor=2, max_height=1080,
                      gpu=0, gpu_threads=2, scene_mode=1, workspace_mib=0,
                      anime4k=False, http_proxy=None, no_audio=False, gop=0,
                      quality=12, audio_codec='aac', publish_url='/tmp/index.m3u8')
        values.update(changes)
        return argparse.Namespace(**values)

    def test_fractional_rate_and_remaining_duration(self):
        t = stream.build_timeline(self.source(), self.args(duration=0))
        self.assertEqual(t.duration, 47.5)
        self.assertEqual(t.output_rate, Fraction(48000, 1001))
        self.assertEqual(t.pipe_frames, math.floor(47.5 * float(t.source_rate)) - 1)

    def test_explicit_duration_keeps_existing_limit_even_past_media_end(self):
        t = stream.build_timeline(self.source(1), self.args(duration=10.25))
        self.assertEqual(t.duration, 10.25)
        self.assertEqual(t.requested_duration, 10.25)
        self.assertEqual(t.duration_text, '10.25')

    def test_unknown_duration_preserves_pipe_ceiling(self):
        t = stream.build_timeline(self.source(None), self.args(duration=0))
        self.assertIsNone(t.duration)
        self.assertEqual(t.pipe_frames, 2_000_000_000)
        explicit = stream.build_timeline(self.source(None), self.args(duration=1))
        self.assertEqual(explicit.pipe_frames, 22)

    def test_short_empty_and_seek_past_end_preserve_minimum_frame(self):
        for total, start, duration in [(0, 0, 0), (60, 60, 0), (60, 70, 0),
                                       (60, 0, 0.001)]:
            with self.subTest(total=total, start=start, duration=duration):
                t = stream.build_timeline(self.source(total), self.args(start=start, duration=duration))
                self.assertEqual(t.pipe_frames, 1)

    def test_frame_budget_matches_legacy_float_policy(self):
        for rate in (Fraction(25), Fraction(24000, 1001), Fraction(30000, 1001)):
            for start in (0, 0.1, 12.5, 60, 70):
                for duration in (0, 0.001, 0.3, 10.25):
                    effective = duration or max(0, 60 - start)
                    t = stream.Timeline.resolve(rate, 2, start, duration, 60)
                    self.assertEqual(t.pipe_frames, max(1, math.floor(effective * float(rate)) - 1))

    def test_source_fps_override_uses_resolved_rate_not_probe_rate(self):
        source = self.source()
        source.rate = Fraction(25)
        t = stream.build_timeline(source, self.args(factor=3))
        self.assertEqual(t.source_rate, Fraction(25))
        self.assertEqual(t.output_rate, Fraction(75))

    def test_immutable_and_invalid_times_rejected(self):
        t = stream.build_timeline(self.source(), self.args())
        with self.assertRaises(FrozenInstanceError):
            t.start = 1
        for field in ('start', 'duration'):
            for value in (-1, float('nan'), float('inf')):
                with self.subTest(field=field, value=value), self.assertRaises(ValueError):
                    stream.build_timeline(self.source(), self.args(**{field: value}))
        for rate, factor in [(Fraction(0), 2), (Fraction(-1), 2), (Fraction(25), 0)]:
            with self.assertRaises(ValueError):
                stream.Timeline.resolve(rate, factor, 0, 0, 60)

    def test_same_timeline_controls_video_audio_subtitle_and_environment(self):
        source, args = self.source(), self.args()
        t = stream.build_timeline(source, args)
        # Conflicting CLI values must not override the already resolved timeline.
        args.start, args.duration, args.factor = 99, 98, 4
        source.rate = Fraction(60)
        decoder = stream.build_decoder_command(source, args, timeline=t)
        encoder = stream.build_encoder_command(source, args, timeline=t)
        env = stream.build_environment(source, args, timeline=t)
        for command in (decoder, encoder):
            self.assertEqual(command[command.index('-ss') + 1], '12.5')
            self.assertEqual(command[command.index('-t') + 1], '10.25')
        self.assertIn('fps=24000/1001', decoder[decoder.index('-vf') + 1])
        self.assertIn('setpts=PTS+12.5/TB', encoder[encoder.index('-vf') + 1])
        self.assertEqual(encoder[encoder.index('-g') + 1], '95')
        self.assertEqual(env['RIFE_FACTOR'], '2')
        self.assertEqual(env['RIFE_PIPE_FPS_NUM'], '24000')
        self.assertEqual(env['RIFE_PIPE_FPS_DEN'], '1001')
        self.assertEqual(env['RIFE_PIPE_FRAMES'], str(t.pipe_frames))

    def test_pipeline_passes_identical_timeline_to_all_builders(self):
        source, args = self.source(), self.args()
        timeline = stream.build_timeline(source, args)
        children = [Mock(), Mock(), Mock()]
        for child in children:
            child.wait.return_value = 0
            child.poll.return_value = 0
            child.returncode = 0
            child.stderr = None
        with patch.object(stream.subprocess, 'Popen', side_effect=children), \
             patch.object(stream, 'stop_process'), \
             patch.object(stream, 'build_decoder_command', return_value=['decoder']) as dec, \
             patch.object(stream, 'build_encoder_command', return_value=['encoder']) as enc, \
             patch.object(stream, 'build_environment', return_value={}) as env:
            self.assertEqual(stream.run_pipeline(source, args, timeline=timeline), 0)
            for builder in (dec, enc, env):
                self.assertIs(builder.call_args.kwargs['timeline'], timeline)


if __name__ == '__main__':
    unittest.main()
