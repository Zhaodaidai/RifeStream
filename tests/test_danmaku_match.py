import io
import json
from pathlib import Path
import tempfile
import threading
import time
import unittest
from unittest.mock import patch
import zlib

from rife import danmaku, danmaku_match as dm, webui


XML = b'<i><d p="1,1,25,16777215">episode two</d></i>'


def search_result(title='凡人修仙传', season_id=28747):
    return {'code': 0, 'data': {'result': [
        {'result_type': 'video', 'data': [{'title': 'unrelated clip'}]},
        {'result_type': 'media_bangumi', 'data': [{'title': title, 'season_id': season_id}]}
    ]}}


def remote(url):
    if 'search/all/v2?' in url:
        return json.dumps(search_result()).encode()
    if 'season?season_id=' in url:
        return json.dumps({'code': 0, 'result': {'episodes': [
            {'id': 733316, 'cid': 11, 'title': '1'},
            {'id': 733317, 'cid': 22, 'title': '2', 'long_title': '第二集'},
            {'id': 999, 'cid': 33, 'title': 'PV'}]}}).encode()
    if url == 'https://comment.bilibili.com/22.xml':
        return XML
    raise AssertionError('wrong episode or unexpected URL: ' + url)


class AutoDanmakuTests(unittest.TestCase):
    def setUp(self):
        with dm._LOCK:
            dm._CACHE.clear()
            dm._CACHE_BYTES = 0

    def test_chinese_and_release_filenames(self):
        cases = [
            ('凡人修仙传第1集', ('凡人修仙传', 1, None)),
            ('凡人修仙传第２集.mp4', ('凡人修仙传', 2, None)),
            ('凡人修仙传第一百零二集', ('凡人修仙传', 102, None)),
            ('凡人修仙传第二〇一集', ('凡人修仙传', 201, None)),
            ('凡人修仙传第二季第十二集.mkv', ('凡人修仙传', 12, 2)),
            ('Frieren.S01E02.1080p.mkv', ('Frieren', 2, 1)),
            ('凡人修仙传S01E02.mkv', ('凡人修仙传', 2, 1)),
            ('[Group] Frieren - 02 [1080p].mkv', ('Frieren', 2, None)),
            ('Frieren EP02.mp4', ('Frieren', 2, None)),
            ('凡人修仙传第1集-国创-高清独家在线观看-bilibili-哔哩哔哩.mp4', ('凡人修仙传', 1, None)),
        ]
        for name, expected in cases:
            with self.subTest(name=name):
                q = dm.parse_media_query(name)
                self.assertEqual((q.title, q.episode, q.season), expected)

    def test_path_privacy_and_source_fallback(self):
        q = dm.parse_media_query('video.mp4', r'C:\private\account\凡人修仙传第2集.mp4')
        self.assertEqual(q, dm.MediaQuery('凡人修仙传', 2))
        q = dm.parse_media_query('', 'https://private.example/secret/凡人修仙传第2集.mp4?token=secret')
        self.assertEqual(q.title, '凡人修仙传')
        self.assertEqual(q.episode, 2)
        self.assertIsNone(dm.parse_media_query('video.mp4', 'https://example.com/index.m3u8?token=secret'))

    def test_do_not_guess_special_or_invalid_episode(self):
        for name in ['凡人修仙传第0集', '凡人修仙传第2集预告', '凡人修仙传第2集解说', '凡人修仙传 SP01', '02.mp4']:
            with self.subTest(name=name):
                self.assertIsNone(dm.parse_media_query(name))

    def test_missing_olink_searches_exact_second_episode(self):
        item = {'title': '凡人修仙传第2集.mp4', 'source': 'local.mkv', 'olink': None}
        with patch.object(dm, '_bilibili_read', side_effect=remote) as read:
            result = dm.load_item_danmaku(item)
        self.assertEqual(result['source_url'], 'https://www.bilibili.com/bangumi/play/ep733317')
        self.assertEqual(result['comments'][0]['text'], 'episode two')
        self.assertEqual(result['match']['cid'], 22)
        self.assertEqual(read.call_count, 3)
        self.assertEqual(item['olink'], None, 'matching is read-only')

    def test_explicit_source_is_not_replaced_even_when_empty(self):
        with patch.object(dm, 'load_danmaku', return_value=[]) as load, patch.object(dm, '_bilibili_read') as read:
            result = dm.load_item_danmaku({'title': '凡人修仙传第2集', 'olink': 'https://example.com/custom'})
        load.assert_called_once_with('https://example.com/custom')
        read.assert_not_called()
        self.assertEqual(result['source'], '自带弹幕')

    def test_same_episode_cached_and_different_episode_isolated(self):
        with patch.object(dm, '_bilibili_read', side_effect=remote) as read:
            a = dm.load_item_danmaku({'title': '凡人修仙传第2集'})
            b = dm.load_item_danmaku({'title': '凡人修仙传第2集.mkv'})
            c = dm.load_item_danmaku({'title': '凡人修仙传第3集'})
        self.assertEqual(a, b)
        self.assertEqual(len(c['comments']), 0)
        self.assertEqual(read.call_count, 5)

    def test_no_match_and_network_error_backoff(self):
        with patch.object(dm, '_bilibili_read', return_value=json.dumps(search_result('其他番剧')).encode()) as read:
            a = dm.load_item_danmaku({'title': '凡人修仙传第2集'})
            self.assertEqual(a['comments'], [])
            dm.load_item_danmaku({'title': '凡人修仙传第2集'})
            self.assertEqual(read.call_count, 1)
        self.setUp()
        with patch.object(dm, '_bilibili_read', side_effect=OSError('offline')) as read:
            for _ in range(2):
                with self.assertRaisesRegex(ValueError, 'offline'):
                    dm.load_item_danmaku({'title': '凡人修仙传第2集'})
            self.assertEqual(read.call_count, 1)

    def test_cache_expires(self):
        with patch.object(dm.time, 'monotonic', return_value=0), patch.object(dm, '_bilibili_read', side_effect=remote) as read:
            dm.load_item_danmaku({'title': '凡人修仙传第2集'})
        with patch.object(dm.time, 'monotonic', return_value=601), patch.object(dm, '_bilibili_read', side_effect=remote) as read:
            dm.load_item_danmaku({'title': '凡人修仙传第2集'})
            self.assertEqual(read.call_count, 3)

    def test_ambiguous_editions_and_dubbed_variants(self):
        payload = search_result()
        payload['data']['result'][1]['data'].append({'title': '凡人修仙传', 'season_id': 888})
        with patch.object(dm, '_bilibili_read', return_value=json.dumps(payload).encode()) as read:
            self.assertIsNone(dm._find_episode(dm.MediaQuery('凡人修仙传', 2)))
            self.assertEqual(read.call_count, 1)
        q = dm.MediaQuery('葬送的芙莉莲', 2)
        self.assertFalse(dm._show_matches('葬送的芙莉莲 中配版', q))
        self.assertTrue(dm._show_matches('<em>葬送的芙莉莲</em>', q))
        self.assertFalse(dm._show_matches('葬送的芙莉莲 第二季', q))
        self.assertTrue(dm._show_matches('葬送的芙莉莲 第二季', dm.MediaQuery(q.title, 2, 2)))

    def test_no_episode_does_not_choose_first_of_series(self):
        with patch.object(dm, '_bilibili_read', side_effect=remote):
            self.assertIsNone(dm._find_episode(dm.MediaQuery('凡人修仙传')))

    def test_single_episode_movie(self):
        responses = [json.dumps({'code': 0, 'data': {'result': [{'result_type': 'media_ft', 'data': [{'title': '测试电影', 'season_id': 9}]}]}}).encode(),
                     b'{"code":0,"result":{"episodes":[{"id":123,"cid":456,"title":"movie"}]}}', XML]
        with patch.object(dm, '_bilibili_read', side_effect=responses):
            self.assertEqual(dm.load_item_danmaku({'title': '测试电影.mp4'})['match']['ep_id'], 123)

    def test_malformed_and_api_error(self):
        for response in [b'not json', b'[]', b'{"code":-412}', b'{"code":0,"data":null}']:
            self.setUp()
            with self.subTest(response=response), patch.object(dm, '_bilibili_read', return_value=response):
                with self.assertRaises(ValueError):
                    dm.load_item_danmaku({'title': '凡人修仙传第2集'})
        self.assertFalse(dm._PENDING)

    def test_concurrent_requests_share_fetch(self):
        count = []
        def slow(url):
            count.append(url)
            time.sleep(.02)
            return remote(url)
        results = []
        errors = []
        def work():
            try:
                results.append(dm.load_item_danmaku({'title': '凡人修仙传第2集'}))
            except Exception as e:
                errors.append(e)
        with patch.object(dm, '_bilibili_read', side_effect=slow):
            threads = [threading.Thread(target=work) for _ in range(5)]
            for t in threads: t.start()
            for t in threads: t.join(2)
        self.assertEqual(errors, [])
        self.assertEqual(len(results), 5)
        self.assertEqual(len(count), 3)

    def test_cache_size_bound(self):
        with patch.object(dm, '_CACHE_LIMIT', 100), patch.object(dm, '_bilibili_read', side_effect=remote):
            dm.load_item_danmaku({'title': '凡人修仙传第2集'})
            self.assertEqual(dm._CACHE_BYTES, 0)
            self.assertEqual(len(dm._CACHE), 0)

    def test_compressed_xml_is_bounded(self):
        def read(data, encoding):
            class Response(io.BytesIO):
                url = 'https://comment.bilibili.com/22.xml'
                headers = {'Content-Encoding': encoding}
            class Opener:
                def open(self, *args, **kwargs): return Response(data)
            with patch.object(danmaku, 'build_opener', return_value=Opener()):
                return danmaku._bilibili_read(Response.url)
        for window, encoding in [(15, 'deflate'), (-15, 'deflate'), (31, 'gzip')]:
            z = zlib.compressobj(wbits=window)
            self.assertEqual(read(z.compress(XML) + z.flush(), encoding), XML)
        with self.assertRaises(ValueError):
            read(zlib.compress(b'a' * (danmaku.MAX_BYTES + 1)), 'deflate')

    def test_api_uses_playlist_item_and_does_not_mutate_state(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / 'playlist.json'
            payload = {'items': [{'id': 'second', 'source': r'C:\video\凡人修仙传第2集.mp4', 'title': '凡人修仙传第2集', 'kind': 'file'}], 'current_id': 'second'}
            path.write_text(json.dumps(payload), encoding='utf-8')
            before = path.read_bytes()
            playlist = webui.Playlist(path)
            handler = object.__new__(webui.WebHandler)
            handler.path = '/api/danmaku?id=second'
            handler.send_json = lambda data: setattr(handler, 'result', data)
            handler.send_danmaku_error = lambda msg: setattr(handler, 'error', msg)
            with patch.object(webui, 'PLAYLIST', playlist), patch.object(dm, '_bilibili_read', side_effect=remote):
                handler.do_GET()
            self.assertEqual(handler.result['match']['cid'], 22)
            self.assertEqual(handler.result['item_id'], 'second')
            self.assertEqual(path.read_bytes(), before)
            self.assertIsNone(playlist.state.last_error)
            handler.path = '/api/danmaku?id=unknown'
            with patch.object(webui, 'PLAYLIST', playlist), patch.object(webui, 'load_item_danmaku') as load:
                handler.do_GET()
                load.assert_not_called()
                self.assertEqual(handler.error, '播放条目不存在')

    def test_failed_auto_fetch_is_local_not_global_playback_error(self):
        item = {'id': 'second', 'title': '凡人修仙传第2集', 'olink': None}
        class Playlist:
            def refresh(self): pass
            def snapshot(self): return {'items': [item]}
        handler = object.__new__(webui.WebHandler)
        handler.path = '/api/danmaku?id=second'
        handler.send_danmaku_error = lambda msg: setattr(handler, 'error', msg)
        with patch.object(webui, 'PLAYLIST', Playlist()), patch.object(dm, '_bilibili_read', side_effect=OSError('offline')):
            handler.do_GET()
        self.assertIn('offline', handler.error)


if __name__ == '__main__':
    unittest.main()
