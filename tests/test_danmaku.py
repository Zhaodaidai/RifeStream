import io
import base64
import gzip
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
from rife.danmaku import MAX_BYTES, SafeRedirect, load_danmaku, parse_danmaku, validate_source
from rife.protocol import MpvRequest, ProtocolError, parse_mpv_command, parse_uri, register_playlist_item
from rife.webui import Playlist


class DanmakuTests(unittest.TestCase):
    def test_olink_protocol_roundtrip_and_existing_item_update(self):
        request = parse_mpv_command('"https://example.com/ep.mp4" --olink="https://example.com/d.xml?a=1&b=2"')
        self.assertEqual(request.olink, "https://example.com/d.xml?a=1&b=2")
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder)/'playlist.json'
            with patch('rife.protocol.PLAYLIST_FILE', path):
                register_playlist_item(request)
                request.olink = 'https://example.com/updated.json'
                register_playlist_item(request)
            playlist = Playlist(path)
            self.assertEqual(playlist.current().olink, request.olink)
            playlist.save()
            self.assertEqual(Playlist(path).snapshot(streaming=False)['current']['olink'], request.olink)
            self.assertEqual(len(playlist.state.items), 1)

    def test_exact_compressed_ush_payload_preserves_olink(self):
        command = '"https://example.com/episode.mp4" --force-media-title="Episode 1" --start="120" --olink="https://example.com/comments.xml"'
        payload = base64.b64encode(gzip.compress(command.encode())).decode()
        request = parse_uri('ush://mpv?' + payload)
        self.assertEqual(request.olink, 'https://example.com/comments.xml')
        self.assertEqual(request.start, 120)
        self.assertEqual(request.title, 'Episode 1')

    def test_old_playlist_without_olink_remains_compatible(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder)/'playlist.json'
            path.write_text(json.dumps({'items':[{'id':'a','source':'https://example.com/a'}]}))
            self.assertIsNone(Playlist(path).current().olink)

    def test_olink_invalid_scheme_rejected(self):
        for url in ['file:///etc/passwd','javascript:alert(1)','ftp://example.com/a']:
            with self.assertRaises(ProtocolError):
                parse_mpv_command(f'"https://example.com/a" --olink="{url}"')

    def test_bilibili_xml_modes_colors_sort_and_untrusted_text(self):
        data = b'<i><d p="10,5,25,255">top</d><d p="2.5,4,25,0">&lt;script&gt;literal&lt;/script&gt;</d><d p="nan,1,25,1">bad</d></i>'
        result = parse_danmaku(data)
        self.assertEqual([c['time'] for c in result], [2.5,10])
        self.assertEqual(result[0]['text'], '<script>literal</script>')
        self.assertEqual(result[0]['mode'], 4)
        self.assertEqual(result[1]['color'], 255)

    def test_json_normalized_and_p_m_formats(self):
        for payload in [[{'time':1,'text':' hi ','mode':5}],{'comments':[{'p':'1,5,16777215,0','m':'hi'}]}]:
            result = parse_danmaku(json.dumps(payload).encode())
            self.assertEqual(result, [{'time':1.0,'text':'hi','mode':5,'color':16777215}])

    def test_invalid_records_skipped_and_text_bounded(self):
        data = [{'time':-1,'text':'a'},{'time':'nan','text':'b'}, {'time':2,'text':'x'*500}, {'text':'no time'}, None]
        result = parse_danmaku(json.dumps(data).encode())
        self.assertEqual(len(result),1)
        self.assertEqual(len(result[0]['text']),500)

    def test_empty_file_supported_and_bad_sources_rejected(self):
        self.assertEqual(parse_danmaku(b'<i/>'),[])
        for raw in [b'<html>not danmaku</html>',b'<!DOCTYPE i [<!ENTITY x "oops">]><i/>',b'<i>',b'no json',b'{}',b'\xff']:
            with self.assertRaises(ValueError): parse_danmaku(raw)

    def test_plain_and_external_doctype_ignored_without_fetching(self):
        for declaration in ['<!DOCTYPE i>', '<!DOCTYPE i SYSTEM "https://example.invalid/d.dtd">', "<!DOCTYPE i SYSTEM 'file:///etc/passwd'>", '<!DOCTYPE i PUBLIC "id" "https://example.invalid/d.dtd">']:
            xml = ('<?xml version="1.0"?>'+declaration+'<i><d p="1,1,25,16777215">ok</d></i>').encode()
            with patch('urllib.request.urlopen', side_effect=AssertionError('must not fetch')):
                self.assertEqual(parse_danmaku(xml)[0]['text'], 'ok')

    def test_internal_and_external_entity_definitions_remain_rejected(self):
        for declaration in ['<!DOCTYPE i [<!ENTITY x "boom">]>', '<!DOCTYPE i [<!ENTITY x SYSTEM "file:///etc/passwd">]>']:
            with self.assertRaises(ValueError):parse_danmaku((declaration+'<i><d p="1,1,25,1">&x;</d></i>').encode())

    def test_html_doctype_reports_webpage_instead_of_entity_error(self):
        with self.assertRaisesRegex(ValueError, "HTML 网页"):
            parse_danmaku(b'<!DOCTYPE html><html><body>source page</body></html>')

    def test_resolver_url_encodes_entire_olink_and_array_json(self):
        from urllib.parse import parse_qs, urlsplit
        seen = []
        payload = {"danmuku": [[2,"right","#ffffff","","hello"], [3,"top","#ff0000","","top"], [4,"bottom","#000000","","bottom"], [], [6,"top","#FFFFFF","",""]]}
        class Response(io.BytesIO):
            url = "https://dmku.byteamone.cn/dmku/class/barrage.php"
        class Opener:
            def open(self, request, timeout):
                seen.append(request.full_url)
                return Response(json.dumps(payload).encode())
        url = "https://v.qq.com/x/cover/id/episode.html?x=1&name=中文#part"
        with patch('rife.danmaku.build_opener', return_value=Opener()):
            result = load_danmaku(url)
        self.assertEqual(parse_qs(urlsplit(seen[0]).query)['url'], [url])
        self.assertTrue(seen[0].startswith('https://dmku.byteamone.cn/dmku/class/barrage.php?url='))
        self.assertEqual([c['mode'] for c in result], [1,5,4])
        self.assertEqual(result[1]['color'], 16711680)
        with patch('rife.danmaku.build_opener', return_value=Opener()):
            load_danmaku(seen[0])
        self.assertEqual(seen[0],seen[1])

    def test_image_markup_preserved_for_safe_frontend_rendering(self):
        from rife.danmaku import normalize
        markup = '<img src="https://example.com/emoji.png" style="height:1.5rem"> 二刷'
        self.assertEqual(normalize(1, markup)['text'], markup)
        self.assertEqual(normalize(1, '<img src="https://example.com/e.png">')['text'], '<img src="https://example.com/e.png">')
        self.assertEqual(len(normalize(1, 'x'*5000)['text']), 4096)

    def test_limits(self):
        with self.assertRaises(ValueError):parse_danmaku(b' '* (MAX_BYTES+1))
        with self.assertRaises(ValueError):parse_danmaku(json.dumps([{}]*50001).encode())

    def test_network_loader_timeout_and_size_bound(self):
        class Response(io.BytesIO):
            url = 'https://example.com/d.json'
        opener = type('Opener', (), {'open':lambda self,req,timeout:Response(b'[{"time":1,"text":"ok"}]')})()
        with patch('rife.danmaku.build_opener', return_value=opener):
            self.assertEqual(load_danmaku(Response.url)[0]['text'],'ok')
        for url in ['file:///tmp/a','https://user:pass@example.com/a','ftp://example.com/a']:
            with self.assertRaises(ValueError):validate_source(url)
        with self.assertRaises(ValueError):
            SafeRedirect().redirect_request(None,None,302,'',{},'file:///etc/passwd')

    def test_byteam_top_level_array_retains_image_emoji(self):
        payload = [[1,"right","#ffffff","","hello"], [2,"top","#ff0000","",'<img src="https://example.com/e.png">'], [3,"bottom","#000000","","bottom"], []]
        result = parse_danmaku(json.dumps(payload).encode())
        self.assertEqual([v['mode'] for v in result], [1,5,4])
        self.assertIn('<img src=',result[1]['text'])
