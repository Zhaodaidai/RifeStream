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


class PlayerLayoutTests(unittest.TestCase):
    def test_manual_seek_controls_and_bindings_removed(self):
        root = Path(__file__).resolve().parent.parent
        html = (root / 'web/index.html').read_text()
        script = (root / 'web/app.js').read_text()
        for name in ['jumpTo', 'jumpBtn', 'jumpLabel']:
            self.assertNotIn(name, html)
            self.assertNotIn(name, script)
        self.assertIn('async function seekSeconds', script)
        self.assertIn('introSeconds.addEventListener', script)

    def test_controls_above_timeline_and_playlist_separate_sidebar(self):
        root = Path(__file__).resolve().parent.parent
        html = (root / 'web/index.html').read_text()
        viewer = html.split('<section class="viewer card"', 1)[1].split('</section>', 1)[0]
        for name in ['prevBtn', 'nextBtn', 'introSeconds', 'skipIntro', 'anime4k']:
            self.assertLess(viewer.index('id="' + name + '"'), viewer.index('id="timeline"'))
        self.assertNotIn('id="playlist"', viewer)
        sidebar = html.split('<aside class="sidebar card"', 1)[1].split('</aside>', 1)[0]
        self.assertIn('id="playlist"', sidebar)


class AddLinksDialogTests(unittest.TestCase):
    def test_add_links_form_is_only_inside_dialog(self):
        root = Path(__file__).resolve().parent.parent
        html = (root / 'web/index.html').read_text()
        self.assertNotIn('class="sources card"', html)
        self.assertNotIn('id="addPlayBtn"', html)
        sidebar = html.split('<aside class="sidebar card"', 1)[1].split('</aside>', 1)[0]
        self.assertIn('id="openAddBtn"', sidebar)
        self.assertIn('id="clearBtn"', sidebar)
        dialog = html.split('<dialog id="addDialog"', 1)[1].split('</dialog>', 1)[0]
        for name in ['sourceInput', 'addForm', 'finishAddBtn', 'cancelAddBtn', 'addError']:
            self.assertIn('id="' + name + '"', dialog)
        self.assertEqual(html.count('id="sourceInput"'), 1)

    def test_dialog_submits_without_starting_playback(self):
        root = Path(__file__).resolve().parent.parent
        script = (root / 'web/app.js').read_text()
        self.assertIn('JSON.stringify({ sources, play: false })', script)
        self.assertIn('addForm.addEventListener("submit", addSources)', script)
        self.assertIn('if (addingSources) return;', script)
        self.assertIn('addDialog.showModal()', script)
        self.assertNotIn('getElementById("addPlayBtn")', script)
