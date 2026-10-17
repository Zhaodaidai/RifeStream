import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from rife.webui import PLAYBACK, Playlist, hls_ready, playback_snapshot, reset_playback, seek_to


class EmbeddedPlaybackTests(unittest.TestCase):
    def tearDown(self):
        reset_playback()

    def test_readiness_rejects_previous_session(self):
        with tempfile.TemporaryDirectory() as folder:
            playlist = Path(folder) / 'index.m3u8'
            with patch('rife.webui.HLS_PLAYLIST', playlist):
                self.assertFalse(hls_ready(100, True))
                playlist.write_text('#EXTM3U')
                os.utime(playlist, (90, 90))
                self.assertFalse(hls_ready(100, True))
                os.utime(playlist, (110, 110))
                self.assertTrue(hls_ready(100, True))
                self.assertFalse(hls_ready(100, False))

    def test_snapshot_exposes_stable_session_and_start(self):
        PLAYBACK.spawned_at = 100
        PLAYBACK.start = 300
        payload = playback_snapshot(True, True, now=110, status=None)
        self.assertEqual(payload['playback_id'], 100)
        self.assertEqual(payload['start'], 300)

    def test_explicit_seek_not_ignored_near_transcode_wall_clock(self):
        with tempfile.TemporaryDirectory() as folder:
            playlist = Playlist(Path(folder) / 'playlist.json')
            playlist.add_sources(['https://example.com/ep1.mp4'])
            PLAYBACK.duration = 1000
            with patch('rife.webui.PLAYLIST', playlist), patch('rife.webui.stream_running', return_value=True), patch('rife.webui.read_stream_status', return_value=None), patch('rife.webui.spawn_stream') as spawn, patch('rife.webui.playback_snapshot', return_value={'position': 500}):
                seek_to(500)
                self.assertEqual(spawn.call_args.args[2], 500)
