import json
import io
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from rife import danmaku_match as dm, webui

URL = 'https://www.bilibili.com/bangumi/play/ep3854813'


class ManualDanmakuTests(unittest.TestCase):
    def make_playlist(self, folder):
        path = Path(folder) / 'playlist.json'
        payload = {'items': [
            {'id': 'one', 'title': '凡人修仙传第1集', 'source': 'one.mp4', 'kind': 'file', 'olink': 'https://example.com/original'},
            {'id': 'two', 'title': '凡人修仙传第2集', 'source': 'two.mp4', 'kind': 'file'}], 'current_id': 'two', 'play_generation': 18}
        path.write_text(json.dumps(payload), encoding='utf-8')
        return webui.Playlist(path)

    def test_url_validation_and_canonicalization(self):
        self.assertEqual(dm.canonical_bilibili_episode_url('  '+URL+'?from=share#part '), URL)
        self.assertEqual(dm.canonical_bilibili_episode_url('http://m.bilibili.com/bangumi/play/ep3854813/'), URL)
        self.assertIsNone(dm.canonical_bilibili_episode_url(' '))
        for value in [None, [], 123, 'https://127.0.0.1/ep3854813', 'file:///etc/passwd', 'javascript:alert(1)',
                      'https://www.bilibili.com.evil.test/bangumi/play/ep3854813', 'https://evil.test/?url='+URL,
                      'https://user:pass@www.bilibili.com/bangumi/play/ep3854813', 'https://www.bilibili.com:123/bangumi/play/ep3854813',
                      'https://www.bilibili.com:bad/bangumi/play/ep3854813', 'https://www.bilibili.com/video/BV123',
                      'https://www.bilibili.com/bangumi/play/ep0', 'https://www.bilibili.com/bangumi/play/ep-1', URL+'/more', 'x'*2049]:
            with self.subTest(value=value):
                with self.assertRaises(ValueError): dm.canonical_bilibili_episode_url(value)

    def test_priority_manual_then_provided_then_auto(self):
        item = {'title': '凡人修仙传第1集', 'olink': 'https://example.com/original', 'danmaku_url': URL}
        with patch.object(dm, 'load_danmaku', return_value=[]) as load, patch.object(dm, '_cached_auto', return_value={'comments': [], 'source': 'auto'}) as auto:
            result = dm.load_item_danmaku(item)
            load.assert_called_once_with(URL)
            self.assertEqual(result['source'], '手动指定 · Bilibili')
            auto.assert_not_called()
            item['danmaku_url'] = None
            result = dm.load_item_danmaku(item)
            self.assertEqual(result['source'], '自带弹幕')
            load.assert_called_with(item['olink'])
            item['olink'] = None
            self.assertEqual(dm.load_item_danmaku(item)['source'], 'auto')
            auto.assert_called_once()

    def test_invalid_or_failed_manual_source_does_not_silently_fallback(self):
        with patch.object(dm, 'load_danmaku', side_effect=OSError('offline')), patch.object(dm, '_cached_auto') as auto:
            with self.assertRaises(OSError):dm.load_item_danmaku({'danmaku_url':URL})
            with self.assertRaises(ValueError):dm.load_item_danmaku({'danmaku_url':'https://evil.test'})
            auto.assert_not_called()

    def test_per_item_persistence_clear_and_unchanged_playback(self):
        with tempfile.TemporaryDirectory() as folder:
            p = self.make_playlist(folder)
            p.state.last_error = 'existing playback error'
            p.set_danmaku_source('one', URL)
            self.assertEqual(p.state.last_error, 'existing playback error')
            loaded = webui.Playlist(p.path)
            self.assertEqual(loaded.item('one').danmaku_url, URL)
            self.assertIsNone(loaded.item('two').danmaku_url)
            self.assertEqual(loaded.state.current_id, 'two')
            self.assertEqual(loaded.state.play_generation, 18)
            self.assertEqual(loaded.item('one').source, 'one.mp4')
            self.assertEqual(loaded.item('one').olink, 'https://example.com/original')
            loaded.set_danmaku_source('one', '')
            self.assertIsNone(webui.Playlist(p.path).item('one').danmaku_url)
            self.assertEqual(loaded.state.current_id, 'two')
            self.assertEqual(loaded.state.play_generation, 18)

    def test_missing_item_and_invalid_url_do_not_write(self):
        with tempfile.TemporaryDirectory() as folder:
            p=self.make_playlist(folder);before=p.path.read_bytes()
            with self.assertRaises(ValueError):p.set_danmaku_source('missing',URL)
            with self.assertRaises(ValueError):p.set_danmaku_source('one','https://evil.test')
            self.assertEqual(p.path.read_bytes(),before)

    def test_disk_failure_restores_in_memory_value(self):
        with tempfile.TemporaryDirectory() as folder:
            p=self.make_playlist(folder)
            with patch.object(p,'save',side_effect=OSError('disk full')):
                with self.assertRaises(OSError):p.set_danmaku_source('one',URL)
            self.assertIsNone(p.item('one').danmaku_url)

    def test_source_update_refreshes_latest_playlist_before_saving(self):
        with tempfile.TemporaryDirectory() as folder:
            p=self.make_playlist(folder)
            data=json.loads(p.path.read_text());data['play_generation']=99;data['items'].append({'id':'three','title':'third','source':'three.mp4','kind':'file'})
            p.path.write_text(json.dumps(data))
            p.set_danmaku_source('one',URL)
            self.assertEqual(p.state.play_generation,99)
            self.assertIsNotNone(p.item('three'))

    def test_post_route_saves_without_playback_or_remote_fetch(self):
        with tempfile.TemporaryDirectory() as folder:
            p=self.make_playlist(folder);h=object.__new__(webui.WebHandler);h.path='/api/danmaku/source';replies=[]
            h.send_json=lambda body,status=200:replies.append((body,status))
            with patch.object(webui,'PLAYLIST',p),patch.object(webui,'read_json',return_value={'item_id':'two','url':URL}),patch.object(webui,'spawn_stream') as spawn,patch.object(dm,'_bilibili_read') as read:
                h.do_POST()
                spawn.assert_not_called();read.assert_not_called()
            self.assertEqual(replies[-1],({'item_id':'two','danmaku_url':URL},200))
            self.assertIsNone(p.state.last_error)
            self.assertEqual(p.state.play_generation,18)

    def test_real_error_serializer_does_not_poison_playback(self):
        with tempfile.TemporaryDirectory() as folder:
            p = self.make_playlist(folder)
            p.state.last_error = 'existing playback error'
            h = object.__new__(webui.WebHandler)
            h.path = '/api/danmaku/source'
            h.send_response = lambda status: None
            h.send_header = lambda *args: None
            h.end_headers = lambda: None
            h.wfile = io.BytesIO()
            with patch.object(webui, 'PLAYLIST', p), patch('sys.stderr', new=io.StringIO()):
                h.send_json({'error': 'invalid link'}, 400)
                h.send_json({'error': 'disk full'}, 500)
            self.assertEqual(p.state.last_error, 'existing playback error')

    def test_post_validation_and_disk_errors_are_local(self):
        with tempfile.TemporaryDirectory() as folder:
            p=self.make_playlist(folder);h=object.__new__(webui.WebHandler);h.path='/api/danmaku/source';replies=[]
            h.send_json=lambda body,status=200:replies.append((body,status))
            for body in [{},{'item_id':'two'},{'item_id':None,'url':URL},{'item_id':'two','url':None},{'item_id':'two','url':'https://evil.test'},{'item_id':'missing','url':URL}]:
                with patch.object(webui,'PLAYLIST',p),patch.object(webui,'read_json',return_value=body):h.do_POST()
                self.assertEqual(replies[-1][1],400)
            with patch.object(webui,'PLAYLIST',p),patch.object(webui,'read_json',return_value={'item_id':'two','url':URL}),patch.object(p,'save',side_effect=OSError('disk full')):
                h.do_POST()
            self.assertEqual(replies[-1][1],500)
            self.assertIn('无法保存',replies[-1][0]['error'])
            self.assertIsNone(p.state.last_error)


if __name__ == '__main__': unittest.main()
