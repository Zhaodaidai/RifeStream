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
                playlist.write_text('#EXTM3U\n#EXTINF:2,\nseg0.ts\n')
                (playlist.parent / 'seg0.ts').write_bytes(b'complete')
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
            with patch('rife.webui.PLAYLIST', playlist), patch('rife.webui.stream_running', return_value=True), patch('rife.webui.read_stream_status', return_value=None), patch('rife.webui.spawn_stream') as spawn, patch('rife.webui.playback_snapshot', return_value={'position': 500, 'duration': 1000}):
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

    def test_timeline_inside_video_stage_and_playlist_separate_sidebar(self):
        root = Path(__file__).resolve().parent.parent
        html = (root / 'web/index.html').read_text()
        viewer = html.split('<section class="viewer card"', 1)[1].split('</section>', 1)[0]
        for name in ['introSeconds', 'skipIntro', 'anime4k']:
            self.assertIn('id="' + name + '"', viewer)
        self.assertIn('anime4k.addEventListener("change", saveSettings)', (root / 'web/app.js').read_text())
        self.assertNotIn('id="anime4k" checked', html)
        stage = viewer.split('<div class="video-stage">', 1)[1].split('<div class="playback-controls"', 1)[0]
        self.assertIn('id="timeline"', stage)
        self.assertIn('id="episodeProgress"', stage)
        self.assertEqual(html.count('id="timeline"'), 1)
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


class PlyrIntegrationTests(unittest.TestCase):
    def test_local_assets_and_load_order(self):
        root = Path(__file__).resolve().parent.parent
        html = (root / 'web/index.html').read_text()
        self.assertLess(html.index('/vendor/plyr.css'), html.index('/styles.css'))
        self.assertLess(html.index('/vendor/plyr.min.js'), html.index('/player.js'))
        for name in ['plyr.min.js', 'plyr.css', 'plyr.svg', 'plyr.LICENSE']:
            self.assertGreater((root / 'web/vendor' / name).stat().st_size, 100)
        self.assertIn('MIT', (root / 'web/vendor/plyr.LICENSE').read_text())

    def test_plyr_keeps_business_timeline_and_local_resources(self):
        root = Path(__file__).resolve().parent.parent
        script = (root / 'web/player.js').read_text()
        self.assertIn('new window.Plyr(video', script)
        self.assertIn('iconUrl: "/vendor/plyr.svg"', script)
        self.assertIn('blankVideo: "data:video/mp4;base64,', script)
        self.assertIn('this.hls = new window.Hls', script)
        self.assertIn('this.seek(seconds)', script)
        self.assertIn('this.state?.start', script)
        self.assertNotIn('--plyr-color-main: var(--accent)', (root / 'web/styles.css').read_text())


class EpisodeNavigationTests(unittest.TestCase):
    def test_external_transport_removed(self):
        root = Path(__file__).resolve().parent.parent
        html = (root / 'web/index.html').read_text()
        script = (root / 'web/app.js').read_text()
        for name in ['prevBtn', 'nextBtn', 'playBtn']:
            self.assertNotIn('id="' + name + '"', html)
            self.assertNotIn('getElementById("' + name + '")', script)
        self.assertIn('id="stopBtn"', html)
        self.assertIn('onNavigate: (offset) => play({ offset })', script)
        self.assertIn('onPlayRequest: () => play({})', script)

    def test_navigation_uses_plyr_controls_and_server_availability(self):
        root = Path(__file__).resolve().parent.parent
        script = (root / 'web/player.js').read_text()
        self.assertIn('controls.insertBefore(this.previousButton, playButton)', script)
        self.assertIn('controls.insertBefore(this.nextButton, playButton.nextSibling)', script)
        self.assertIn('this.state?.has_prev', script)
        self.assertIn('this.state?.has_next', script)
        self.assertIn('button.hidden = hidden', script)
        self.assertIn('this.onNavigate?.(offset)', script)
        self.assertIn('play: () => this.handlePlayRequest()', script)


class EpisodeTimelineTests(unittest.TestCase):
    def test_external_player_ui_and_copy_bindings_removed(self):
        root = Path(__file__).resolve().parent.parent
        html = (root / 'web/index.html').read_text()
        script = (root / 'web/app.js').read_text()
        css = (root / 'web/styles.css').read_text()
        for name in ['copyBtn', 'hlsUrl', 'hlsHint', 'stream-address', 'navigator.clipboard']:
            self.assertNotIn(name, html + script + css)
        self.assertNotIn('外部播放器', html)
        self.assertNotIn('timeline-label', html + css)

    def test_episode_clock_remains_business_driven_inside_plyr(self):
        root = Path(__file__).resolve().parent.parent
        script = (root / 'web/player.js').read_text()
        self.assertIn('controls.insertBefore(progress, controls.querySelector', script)
        self.assertIn('this.state?.start', script)
        self.assertIn('this.seek(seconds)', script)
        self.assertIn('aria-valuetext', script)


class PlayerHeadingTests(unittest.TestCase):
    def test_selected_title_is_only_in_viewer_header(self):
        root = Path(__file__).resolve().parent.parent
        html = (root / 'web/index.html').read_text()
        header = html.split('<div class="viewer-head">', 1)[1].split('</div>', 1)[0]
        self.assertIn('id="nowPlaying"', header)
        self.assertEqual(html.count('id="nowPlaying"'), 1)
        for obsolete in ['media-meta', 'section-kicker', 'format-tag', 'HLS STREAM']:
            self.assertNotIn(obsolete, html)
        script = (root / 'web/app.js').read_text()
        self.assertIn('nowPlaying.textContent = current?.title', script)
        self.assertIn('nowPlaying.title = current?.title', script)
        self.assertNotIn('已选择', script)

    def test_player_hint_follows_stop_in_same_group(self):
        root = Path(__file__).resolve().parent.parent
        html = (root / 'web/index.html').read_text()
        group = html.split('<div class="stop-status">', 1)[1].split('</div>', 1)[0]
        self.assertLess(group.index('id="stopBtn"'), group.index('id="playerHint"'))
        self.assertEqual(html.count('id="playerHint"'), 1)
        self.assertIn('role="status"', group)


class NativePlyrStyleTests(unittest.TestCase):
    def test_time_precedes_progress_and_theme_does_not_override_buttons(self):
        root = Path(__file__).resolve().parent.parent
        html = (root / 'web/index.html').read_text()
        self.assertLess(html.index('id="playbackTime"'), html.index('id="timeline"'))
        css = (root / 'web/styles.css').read_text()
        for override in ['--plyr-control-radius:', '--plyr-video-control-color-hover:', '--plyr-menu-background:', '--plyr-color-main: var(--accent)', '.plyr__control--overlaid { color:']:
            self.assertNotIn(override, css)
        self.assertIn('grid-template-columns: auto minmax(0, 1fr)', css)


class ThemeManagementTests(unittest.TestCase):
    def test_colors_centralized_and_plyr_linked(self):
        import re
        root = Path(__file__).resolve().parent.parent
        theme = (root / 'web/theme.css').read_text()
        css = (root / 'web/styles.css').read_text()
        html = (root / 'web/index.html').read_text()
        self.assertLess(html.index('/theme.css'), html.index('/styles.css'))
        self.assertIn('--accent: #00b2ff;', theme)
        self.assertIn('--plyr-color-main: var(--accent)', theme)
        self.assertFalse(re.search(r'#[0-9a-fA-F]{3,8}\b', css))
        names = re.findall(r'(--[\w-]+)\s*:', theme)
        self.assertEqual(len(names), len(set(names)))
        used = set(re.findall(r'var\((--[\w-]+)', css))
        self.assertFalse(used - set(names) - {'--episode-progress', '--frame-width', '--frame-height', '--landscape-width', '--landscape-height'})
