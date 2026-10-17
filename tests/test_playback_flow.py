"""Session boundaries: HTTP control -> subprocess -> complete HLS media, without GPU requirements."""
from pathlib import Path
import io
import sys
import tempfile
import threading
import time
import unittest
from unittest.mock import patch

from rife import webui
from rife.hls import STUB_PLAYLIST, clear_hls_output, hls_segment_pattern


class PlaybackFlowTests(unittest.TestCase):
    def tearDown(self):
        webui.reset_playback()

    def test_stub_missing_empty_and_complete_first_segment(self):
        with tempfile.TemporaryDirectory() as d:
            p = Path(d) / 'index.m3u8'
            with patch.object(webui, 'HLS_PLAYLIST', p):
                p.write_bytes(STUB_PLAYLIST)
                self.assertFalse(webui.hls_ready(None, True))
                p.write_text('#EXTM3U\n#EXTINF:2,\nseg0.ts\n')
                self.assertFalse(webui.hls_ready(None, True))
                (p.parent / 'seg0.ts').touch()
                self.assertFalse(webui.hls_ready(None, True))
                (p.parent / 'seg0.ts').write_bytes(b'complete')
                self.assertTrue(webui.hls_ready(None, True))
                self.assertFalse(webui.hls_ready(time.time() + 20, True))
                self.assertFalse(webui.hls_ready(None, False))

    def test_segment_paths_never_alias_across_encodes_and_cleanup_accepts_both(self):
        with tempfile.TemporaryDirectory() as d:
            p = Path(d) / 'index.m3u8'
            a, b = hls_segment_pattern(p), hls_segment_pattern(p)
            self.assertNotEqual(a, b)
            self.assertRegex(a, r'seg_[0-9a-f]{32}_%d\.ts$')
            paths = [Path(a.replace('%d', '0')), Path(b.replace('%d', '0') + '.tmp'), p.parent/'seg0.ts']
            for path in paths:
                path.write_bytes(b'ts')
            (p.parent/'keep.ts').write_bytes(b'keep')
            clear_hls_output(p)
            self.assertTrue(all(not path.exists() for path in paths))
            self.assertTrue((p.parent/'keep.ts').exists())

    def test_startup_child_can_be_stopped_before_pid_file_exists(self):
        # Actual OS process, deliberately never publishes stream.pid.
        with tempfile.TemporaryDirectory() as d:
            p = Path(d)
            with patch.object(webui, 'STREAM_PROCESS', None), patch.object(webui, 'STREAM_PID_FILE', p/'none.pid'), patch.object(webui, 'HLS_PLAYLIST', p/'index.m3u8'), patch.object(webui, 'WEBUI_LOG_FILE', p/'web.log'), patch.object(webui, 'replace_existing_stream'), patch.object(webui, 'stream_command', return_value=[sys.executable, '-u', '-c', 'import time;time.sleep(60)']):
                try:
                    webui.spawn_stream('fixture', 'fixture')
                    child = webui.STREAM_PROCESS
                    self.assertIsNotNone(child)
                    self.assertTrue(webui.stream_running())
                    time.sleep(.02)
                    webui.stop_stream()
                    self.assertIsNotNone(child.poll())
                    self.assertFalse(webui.stream_running())
                    self.assertIsNone(webui.STREAM_PROCESS)
                finally:
                    if webui.STREAM_PROCESS is not None:
                        webui.stop_stream()

    def test_control_transactions_do_not_interleave_selected_item_and_spawn(self):
        with tempfile.TemporaryDirectory() as d:
            playlist = webui.Playlist(Path(d)/'playlist.json')
            items = playlist.add_sources(['https://example.com/one', 'https://example.com/two'])
            calls = []
            def spawn(source, *args, **kw):
                before = playlist.current().id
                time.sleep(.015)
                calls.append((before, playlist.current().id, source))
            with patch.object(webui, 'PLAYLIST', playlist), patch.object(webui, 'spawn_stream', side_effect=spawn):
                threads = [threading.Thread(target=webui.start_item, args=(item.id,)) for item in items]
                for thread in threads: thread.start()
                for thread in threads: thread.join()
            self.assertEqual(len(calls), 2)
            self.assertTrue(all(a == b for a, b, _ in calls))
            self.assertEqual({c[2] for c in calls}, {i.source for i in items})

    def test_state_poll_is_read_only_even_when_encode_wall_clock_passes_outro(self):
        with tempfile.TemporaryDirectory() as d:
            playlist = webui.Playlist(Path(d)/'playlist.json')
            playlist.add_sources(['https://example.com/one', 'https://example.com/two'])
            playlist.update_settings({'skip_outro': True, 'outro': 20})
            handler = object.__new__(webui.WebHandler)
            with patch.object(webui, 'PLAYLIST', playlist), patch.object(webui, 'stream_running', return_value=True), patch.object(webui, 'playback_snapshot', return_value={'position': 999, 'duration': 100}), patch.object(webui, 'start_item') as start, patch.object(webui, 'stop_stream') as stop:
                handler.state_payload()
                start.assert_not_called()
                stop.assert_not_called()

    def test_old_process_log_cannot_set_new_session_error(self):
        with tempfile.TemporaryDirectory() as d:
            playlist = webui.Playlist(Path(d)/'playlist.json')
            with patch.object(webui, 'PLAYLIST', playlist), patch.object(webui, 'WEBUI_LOG_FILE', Path(d)/'log'), patch.object(webui, 'STREAM_PROCESS', object()), patch('sys.stderr', io.StringIO()):
                webui.relay_stream_output(io.StringIO('Error: old process\n'), '', object())
                self.assertIsNone(playlist.state.last_error)
                webui.relay_stream_output(io.StringIO('Error: active process\n'), '', webui.STREAM_PROCESS)
                self.assertEqual(playlist.state.last_error, 'Error: active process')

    def test_seek_rejects_old_session_before_touching_transcoder(self):
        # Execute actual handler dispatch with in-memory request/response, no socket or production state.
        handler = object.__new__(webui.WebHandler)
        handler.path = '/api/seek'
        handler.headers = {}
        responses = []
        handler.send_json = lambda body, status=200: responses.append((body, status))
        with patch.object(webui, 'read_json', return_value={'seconds': 42, 'playback_id': 1}), patch.object(webui, 'playback_snapshot', return_value={'playback_id': 2}), patch.object(webui, 'stream_running', return_value=True), patch.object(webui, 'seek_to') as seek:
            handler.do_POST()
            seek.assert_not_called()
        self.assertEqual(responses[0][1], 400)
        self.assertIn('session changed', responses[0][0]['error'])
    def test_seek_does_not_inherit_duration_from_previous_session_status(self):
        with tempfile.TemporaryDirectory() as d:
            playlist=webui.Playlist(Path(d)/'playlist.json')
            item=playlist.add_sources(['https://example.com/current'])[0]
            webui.PLAYBACK.item_id=item.id;webui.PLAYBACK.spawned_at=100;webui.PLAYBACK.duration=None
            with patch.object(webui,'PLAYLIST',playlist), patch.object(webui,'read_stream_status',return_value={'started_at':90,'duration':10}), patch.object(webui,'stream_running',return_value=True), patch.object(webui,'spawn_stream') as spawn:
                webui.seek_to(40)
            self.assertEqual(spawn.call_args.args[2],40,'stale 10sec duration cannot clamp new session seek')


class StreamOwnershipTests(unittest.TestCase):
    def test_old_worker_cannot_clear_successor_pid_status_or_media(self):
        from rife import stream
        with tempfile.TemporaryDirectory() as d:
            p = Path(d);pid=p/'stream.pid';status=p/'status.json';manifest=p/'index.m3u8'
            pid.write_text('222');status.write_text('new session');manifest.write_text('new manifest')
            with patch.object(stream,'STREAM_PID_FILE',pid), patch.object(stream,'STREAM_STATUS_FILE',status), patch('rife.stream.os.getpid',return_value=111):
                stream.release_stream_files(manifest,failed=True)
            self.assertEqual(pid.read_text(),'222');self.assertTrue(status.exists());self.assertTrue(manifest.exists())
            with patch.object(stream,'STREAM_PID_FILE',pid), patch.object(stream,'STREAM_STATUS_FILE',status), patch('rife.stream.os.getpid',return_value=222):
                stream.release_stream_files(manifest,failed=False)
            self.assertFalse(pid.exists());self.assertFalse(status.exists());self.assertTrue(manifest.exists(),'finished encode remains watchable')

    def test_failed_current_worker_clears_its_own_hls(self):
        from rife import stream
        with tempfile.TemporaryDirectory() as d:
            p=Path(d);pid=p/'stream.pid';status=p/'status.json';manifest=p/'index.m3u8'
            pid.write_text('111');status.write_text('failed');manifest.write_text('stub');(p/'seg0.ts').write_bytes(b'ts')
            with patch.object(stream,'STREAM_PID_FILE',pid), patch.object(stream,'STREAM_STATUS_FILE',status), patch('rife.stream.os.getpid',return_value=111):
                stream.release_stream_files(manifest,failed=True)
            self.assertFalse(pid.exists());self.assertFalse(status.exists());self.assertFalse(manifest.exists());self.assertFalse((p/'seg0.ts').exists())


if __name__ == '__main__':
    unittest.main()
