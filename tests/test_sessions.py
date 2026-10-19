"""Session ownership, atomic publication and delayed worker boundaries; no GPU needed."""
import argparse
from contextlib import ExitStack
from fractions import Fraction
import io
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import threading
import unittest
from unittest.mock import Mock, patch

from rife import paths, stream, webui
from rife.sessions import SessionStore, atomic_json


class SessionTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.pid = self.root/'stream.pid'
        self.status = self.root/'status.json'
        self.manifest = self.root/'index.m3u8'
        self.store = SessionStore(self.pid, self.status)
        self.patches = ExitStack()
        for module in (stream, webui, paths):
            self.patches.enter_context(patch.object(module, 'STREAM_PID_FILE', self.pid))
            self.patches.enter_context(patch.object(module, 'STREAM_STATUS_FILE', self.status))
        self.patches.enter_context(patch.object(stream, 'WORKER_SESSION_ID', None))
        self.patches.enter_context(patch.object(webui, 'PLAYBACK', webui.Playback()))
        self.patches.enter_context(patch.object(webui, 'STREAM_PROCESS', None))
        self.patches.enter_context(patch.object(webui, 'HLS_PLAYLIST', self.manifest))
        self.patches.enter_context(patch.object(webui, 'WEBUI_LOG_FILE', self.root/'web.log'))
        self.playlist = webui.Playlist(self.root/'playlist.json')
        self.items = self.playlist.add_sources(['https://example.com/one', 'https://example.com/two'])
        self.patches.enter_context(patch.object(webui, 'PLAYLIST', self.playlist))

    def tearDown(self):
        self.patches.close()
        self.temp.cleanup()

    def reserve(self, item='item', start=0, pid=12345):
        owner = self.store.reserve(item, start, 0)
        self.assertTrue(self.store.attach(owner['session_id'], pid))
        return owner['session_id']

    def test_every_reservation_has_unique_id_even_with_same_clock_and_item(self):
        with patch('rife.sessions.time.time', return_value=100):
            sessions = [self.store.reserve('same', 0, 0)['session_id'] for _ in range(30)]
        self.assertEqual(len(set(sessions)), 30)

    def test_reserve_if_idle_rejects_starting_probing_and_running_owners(self):
        for state in ('starting','probing','running'):
            with self.subTest(state=state):
                owner=self.store.reserve('item',0,1)
                with self.store.locked():
                    current=self.store.read();current['state']=state
                    atomic_json(self.store.path,current)
                with self.assertRaisesRegex(RuntimeError,'active playback'):
                    self.store.reserve_if_idle(None,0,1)
                self.store.invalidate(owner['session_id'])
        owner=self.store.reserve_if_idle(None,0,1)
        self.assertEqual(self.store.read()['session_id'],owner['session_id'])

    def test_replaced_pending_worker_cannot_attach_or_publish(self):
        old = self.store.reserve('old', 0, 0)['session_id']
        new = self.store.reserve('new', 0, 0)['session_id']
        self.assertFalse(self.store.attach(old, 111))
        self.assertTrue(self.store.attach(new, 222))
        self.assertFalse(self.store.publish(old, 111, {'duration': 1}))
        self.assertEqual(self.pid.read_text(), '222')
        self.assertEqual(self.store.read()['session_id'], new)

    def test_old_worker_cannot_clean_successor_even_when_pid_is_reused(self):
        old = self.reserve(pid=os.getpid())
        self.store.invalidate(old)
        new = self.reserve('new', pid=os.getpid())
        self.assertTrue(self.store.publish(new, os.getpid(), {'duration': 200}))
        self.manifest.write_text('new manifest')
        segment = self.root/'seg0.ts';segment.write_bytes(b'new')
        before = {p:p.read_bytes() for p in (self.pid,self.status,self.store.path,self.manifest,segment)}
        with patch.object(stream,'WORKER_SESSION_ID',old):
            self.assertFalse(stream.write_stream_status(self.source(), 88))
            stream.release_stream_files(self.manifest,failed=True)
        self.assertEqual(before, {p:p.read_bytes() for p in before})

    def source(self):
        return stream.StreamInput('/fixture/v',None,[],None,stream.MediaInfo(Fraction(25),2,2,100),Fraction(25))

    def test_current_completion_preserves_hls_and_marks_finished(self):
        session = self.reserve(pid=os.getpid())
        self.manifest.write_text('complete')
        with patch.object(stream,'WORKER_SESSION_ID',session):
            self.assertTrue(stream.write_stream_status(self.source(),12))
            stream.release_stream_files(self.manifest,failed=False)
        self.assertEqual(self.store.read()['state'],'finished')
        self.assertFalse(self.pid.exists());self.assertFalse(self.status.exists())
        self.assertEqual(self.manifest.read_text(),'complete')

    def test_current_failure_cleans_only_while_still_owner(self):
        session = self.reserve(pid=os.getpid())
        self.manifest.write_text('partial');(self.root/'seg0.ts').write_bytes(b'x')
        with patch.object(stream,'WORKER_SESSION_ID',session):
            stream.release_stream_files(self.manifest,failed=True)
        self.assertEqual(self.store.read()['state'],'failed')
        self.assertFalse(self.manifest.exists());self.assertFalse((self.root/'seg0.ts').exists())

    def test_old_status_ignored_even_with_identical_timestamp(self):
        new = self.reserve()
        webui.PLAYBACK.session_id = new
        webui.PLAYBACK.spawned_at = 100
        atomic_json(self.status,dict(session_id='old',duration=1,start=90,started_at=100,pid=12345))
        self.assertIsNone(webui.read_stream_status())
        snapshot = webui.playback_snapshot(True,now=110)
        self.assertIsNone(snapshot['duration'])
        self.assertEqual(snapshot['session_id'],new)

    def test_status_accepts_only_current_session_and_pid(self):
        session = self.reserve()
        webui.PLAYBACK.session_id=session
        self.store.publish(session,12345,dict(duration=200,start=12,started_at=100))
        payload=webui.playback_snapshot(True,now=110)
        self.assertEqual(payload['duration'],200)
        self.assertEqual(payload['position'],22)
        self.assertEqual(payload['playback_id'],100)
        status=json.loads(self.status.read_text());status['pid']=99;atomic_json(self.status,status)
        self.assertIsNone(webui.read_stream_status())

    def test_unowned_tagged_status_is_not_adopted(self):
        atomic_json(self.status,dict(session_id='orphan',duration=1))
        self.assertIsNone(webui.read_stream_status())

    def test_restart_recovers_current_session_but_not_another_item(self):
        item=self.playlist.current()
        session=self.reserve(item.id)
        self.store.publish(session,12345,dict(duration=200,start=12,started_at=100))
        payload=webui.playback_snapshot(True,now=110)
        self.assertEqual(payload['session_id'],session)
        self.assertEqual(webui.PLAYBACK.session_id,session)
        webui.reset_playback()
        self.playlist.select(self.items[1].id)
        self.assertIsNone(webui.read_stream_status())

    def test_old_session_log_cannot_set_error_even_with_same_process_object(self):
        session=self.reserve()
        webui.PLAYBACK.session_id=session
        process=object()
        with patch.object(webui,'STREAM_PROCESS',process),patch('sys.stderr',io.StringIO()):
            webui.relay_stream_output(io.StringIO('Error: old\n'),'header\n',process,'old')
            self.assertIsNone(self.playlist.state.last_error)
            webui.relay_stream_output(io.StringIO('Error: current\n'),'header\n',process,session)
        self.assertEqual(self.playlist.state.last_error,'Error: current')
        log=(self.root/'web.log').read_text()
        self.assertIn('[session=old] Error: old',log)
        self.assertIn(f'[session={session}] Error: current',log)

    def test_external_successor_manifest_is_not_loaded_as_old_item(self):
        old=self.reserve(self.items[0].id)
        self.store.invalidate(old)
        self.reserve(self.items[1].id,pid=222)
        webui.PLAYBACK.session_id=old
        webui.PLAYBACK.duration=200
        with patch.object(webui,'hls_ready',return_value=True):
            payload=webui.playback_snapshot(False,now=110)
        self.assertFalse(payload['hls_ready'])
        self.assertFalse(payload['seekable'])

    def test_external_successor_blocks_old_error_and_old_stop(self):
        old=self.reserve()
        self.store.invalidate(old)
        new=self.reserve('new',pid=222)
        webui.PLAYBACK.session_id=old
        self.store.publish(new,222,dict(duration=200))
        self.manifest.write_text('successor')
        process=Mock();process.poll.return_value=0
        with patch.object(webui,'STREAM_PROCESS',process),patch('sys.stderr',io.StringIO()),patch.object(webui,'stop_pid_tree') as stop:
            webui.relay_stream_output(io.StringIO('Error: delayed\n'),'header\n',process,old)
            self.assertIsNone(self.playlist.state.last_error)
            webui.stop_stream()
            stop.assert_not_called()
        self.assertEqual(self.store.read()['session_id'],new)
        self.assertEqual(self.store.read()['state'],'running')
        self.assertEqual(self.manifest.read_text(),'successor')
        self.assertEqual(self.pid.read_text(),'222')

    def test_request_with_stale_session_rejected_before_seek(self):
        handler=object.__new__(webui.WebHandler);handler.path='/api/seek';handler.headers={}
        responses=[];handler.send_json=lambda payload,status=200:responses.append((payload,status))
        with patch.object(webui,'read_json',return_value={'seconds':42,'session_id':'old'}),patch.object(webui,'playback_snapshot',return_value={'session_id':'new'}),patch.object(webui,'stream_running',return_value=True),patch.object(webui,'seek_to') as seek:
            handler.do_POST();seek.assert_not_called()
        self.assertEqual(responses[0][1],400)

    def test_pipeline_refuses_launch_after_session_revocation(self):
        old=self.reserve(pid=os.getpid())
        self.store.invalidate(old)
        with patch.object(stream,'WORKER_SESSION_ID',old),patch.object(stream.subprocess,'Popen') as spawn:
            with self.assertRaisesRegex(RuntimeError,'superseded'):
                stream.PipelineRunner().start('decoder',['fixture'])
            spawn.assert_not_called()
            self.assertEqual(stream.PipelineRunner().wait(),('stopped',143,None))

    def test_atomic_write_failure_preserves_previous_complete_json_and_cleans_temp(self):
        session=self.reserve()
        self.store.publish(session,12345,dict(duration=200))
        before=self.status.read_bytes()
        with patch('rife.sessions.os.replace',side_effect=OSError('fixture replace failure')):
            with self.assertRaises(OSError):
                self.store.publish(session,12345,dict(duration=999))
        self.assertEqual(self.status.read_bytes(),before)
        self.assertFalse(list(self.root.glob('*.tmp')))

    def test_concurrent_reader_never_observes_partial_json(self):
        session=self.reserve()
        self.store.publish(session,12345,dict(duration=0))
        failures=[]
        def reader():
            for _ in range(100):
                try:json.loads(self.status.read_bytes())
                except Exception as exc:failures.append(str(exc))
        thread=threading.Thread(target=reader);thread.start()
        for i in range(50):self.store.publish(session,12345,dict(duration=i,padding='x'*4096))
        thread.join();self.assertEqual(failures,[])

    def test_process_lock_blocks_stale_publication_until_new_owner_is_visible(self):
        old=self.reserve()
        code=r'''
import sys
from pathlib import Path
from rife.sessions import SessionStore
store=SessionStore(Path(sys.argv[1]),Path(sys.argv[2]))
print('ready',flush=True)
print('published='+str(store.publish(sys.argv[3],12345,{'duration':1})),flush=True)
'''
        child=None
        try:
            with self.store.locked():
                child=subprocess.Popen([sys.executable,'-B','-c',code,str(self.pid),str(self.status),old],stdout=subprocess.PIPE,stderr=subprocess.PIPE,text=True)
                self.assertEqual(child.stdout.readline().strip(),'ready')
                self.assertIsNone(child.poll())
                owner=self.store.read();owner['session_id']='successor'
                atomic_json(self.store.path,owner)
            stdout,stderr=child.communicate(timeout=10)
            self.assertEqual(child.returncode,0,stderr)
            self.assertIn('published=False',stdout)
            self.assertFalse(self.status.exists())
        finally:
            if child is not None:
                if child.poll() is None:child.kill()
                child.communicate(timeout=5)

    def test_spawn_assigns_session_item_and_marks_launch_failure(self):
        with patch.object(webui,'stream_command',return_value=['fixture']),patch.object(webui.subprocess,'Popen',side_effect=OSError('fixture launch')):
            with self.assertRaises(OSError):webui.spawn_stream('fixture','title',12,0,item_id=self.items[0].id)
        owner=self.store.read()
        self.assertEqual(owner['state'],'failed')
        self.assertEqual(owner['item_id'],self.items[0].id)
        self.assertEqual(owner['start'],12)
        self.assertEqual(owner['session_id'],webui.PLAYBACK.session_id)

    def test_abnormal_exit_notification_marks_only_current_session_failed(self):
        session=self.reserve(pid=222)
        self.store.publish(session,222,dict(duration=200))
        webui.PLAYBACK.session_id=session
        process=Mock(pid=222);process.wait.return_value=9
        with patch.object(webui,'STREAM_PROCESS',process):
            webui.finalize_stream_output(process,'retired')
            self.assertEqual(self.store.read()['state'],'running')
            webui.finalize_stream_output(process,session)
        self.assertEqual(self.store.read()['state'],'failed')
        self.assertFalse(self.pid.exists());self.assertFalse(self.status.exists())
        self.assertIn('code 9',self.playlist.state.last_error)

    def test_late_exit_notification_does_not_touch_successor(self):
        session=self.reserve(pid=222)
        webui.PLAYBACK.session_id=session
        process=Mock(pid=111);process.wait.return_value=9
        before=self.store.path.read_bytes()
        with patch.object(webui,'STREAM_PROCESS',process):
            webui.finalize_stream_output(process,'retired')
        self.assertEqual(self.store.path.read_bytes(),before)
        self.assertIsNone(self.playlist.state.last_error)

    def test_replacing_finished_owner_does_not_signal_its_old_pid(self):
        session=self.reserve(pid=222)
        with self.store.locked():
            owner=self.store.read();owner['state']='finished';atomic_json(self.store.path,owner)
            self.pid.unlink()
        with patch('rife.paths.os.kill') as kill,patch.object(paths,'stop_pid_tree') as kill_tree:
            paths.replace_existing_stream()
            kill.assert_not_called();kill_tree.assert_not_called()

    def test_retiring_worker_must_exit_before_shared_hls_reuse(self):
        with patch.object(paths,'pid_is_running',side_effect=[True,False]),patch.object(paths.time,'sleep') as sleep:
            paths.wait_for_stream_exit(999999999)
            sleep.assert_called_once_with(0.05)

    def test_retirement_timeout_refuses_hls_reuse(self):
        with patch.object(paths,'pid_is_running',return_value=True),patch.object(paths.time,'monotonic',side_effect=[0,6]):
            with self.assertRaisesRegex(RuntimeError,'refusing to reuse HLS'):
                paths.wait_for_stream_exit(999999999)

    def test_paths_replacement_revokes_before_signalling(self):
        session=self.reserve(pid=222)
        def killed(pid,signal):
            self.assertEqual(pid,222)
            self.assertEqual(self.store.read()['state'],'stopped')
            self.assertFalse(self.pid.exists())
        with patch('rife.paths.os.kill',side_effect=killed),patch.object(paths,'stop_pid_tree',side_effect=lambda pid: killed(pid,15)),patch.object(paths,'pid_is_running',return_value=False):
            paths.replace_existing_stream()
        self.assertEqual(self.store.read()['session_id'],session)
        self.assertFalse(self.store.publish(session,222,dict(duration=1)))


class WorkerBoundaryTests(unittest.TestCase):
    setUp = SessionTests.setUp
    tearDown = SessionTests.tearDown
    reserve = SessionTests.reserve
    source = SessionTests.source
    def main_args(self, session):
        with patch('sys.argv',['stream','fixture','--session-id',session,'--publish-url',str(self.manifest)]):
            return stream.parse_args()

    def required_tools(self, stack):
        tool=self.root/'tool';tool.touch()
        for name in ('VSPIPE','FFMPEG','FFPROBE','RIFE_SCRIPT'):
            stack.enter_context(patch.object(stream,name,tool))
        stack.enter_context(patch.object(stream,'ensure_var'))
        stack.enter_context(patch.object(stream,'ensure_hls_server'))

    def test_delayed_startup_never_replaces_successor(self):
        old=self.store.reserve('old',0,0)['session_id']
        new=self.store.reserve('new',0,0)['session_id']
        args=self.main_args(old)
        with ExitStack() as stack:
            self.required_tools(stack)
            stack.enter_context(patch.object(stream,'parse_args',return_value=args))
            prepare=stack.enter_context(patch.object(stream,'prepare_input'))
            replace=stack.enter_context(patch.object(stream,'replace_existing_stream'))
            stack.enter_context(patch('sys.stderr',io.StringIO()))
            self.assertEqual(stream.main(),1)
            prepare.assert_not_called();replace.assert_not_called()
        self.assertEqual(self.store.read()['session_id'],new)
        self.assertEqual(self.store.read()['state'],'starting')

    def test_superseded_probe_cannot_reset_manifest_or_launch_pipeline(self):
        old=self.store.reserve('old',0,0)['session_id']
        args=self.main_args(old)
        self.manifest.write_text('successor media')
        def probe(_):
            self.store.invalidate(old)
            self.store.reserve('new',0,0)
            return self.source()
        with ExitStack() as stack:
            self.required_tools(stack)
            stack.enter_context(patch.object(stream,'parse_args',return_value=args))
            stack.enter_context(patch.object(stream,'prepare_input',side_effect=probe))
            reset=stack.enter_context(patch.object(stream,'reset_hls_output'))
            run=stack.enter_context(patch.object(stream,'run_pipeline'))
            stack.enter_context(patch('sys.stderr',io.StringIO()))
            self.assertEqual(stream.main(),1)
            reset.assert_not_called();run.assert_not_called()
        self.assertEqual(self.manifest.read_text(),'successor media')
        self.assertNotEqual(self.store.read()['session_id'],old)

    def test_current_worker_main_finishes_with_tagged_state(self):
        session=self.store.reserve('item',12,0)['session_id']
        args=self.main_args(session)
        def pipeline(*args,**kwargs):
            status=json.loads(self.status.read_text())
            self.assertEqual(status['session_id'],session)
            self.assertEqual(status['pid'],os.getpid())
            self.assertEqual(self.store.read()['state'],'running')
            self.manifest.write_text('complete')
            return 0
        with ExitStack() as stack:
            self.required_tools(stack)
            stack.enter_context(patch.object(stream,'parse_args',return_value=args))
            stack.enter_context(patch.object(stream,'prepare_input',return_value=self.source()))
            stack.enter_context(patch.object(stream,'run_pipeline',side_effect=pipeline))
            stack.enter_context(patch('sys.stdout',io.StringIO()))
            self.assertEqual(stream.main(),0)
        self.assertEqual(self.store.read()['state'],'finished')
        self.assertEqual(self.manifest.read_text(),'complete')

    def test_missing_runtime_marks_only_matching_pending_session_failed(self):
        session=self.store.reserve('item',0,0)['session_id']
        args=self.main_args(session)
        with patch.object(stream,'parse_args',return_value=args),patch.object(stream,'VSPIPE',self.root/'missing'),patch('sys.stderr',io.StringIO()):
            self.assertEqual(stream.main(),2)
        self.assertEqual(self.store.read()['state'],'failed')

    def test_live_owner_cannot_be_replaced_without_revocation(self):
        session=self.reserve()
        with self.assertRaisesRegex(RuntimeError,'must be stopped'):
            self.store.reserve('successor',0,0)
        self.assertEqual(self.store.read()['session_id'],session)

    def test_real_retired_worker_cannot_clear_or_publish_after_successor(self):
        session=self.store.reserve('old',0,0)['session_id']
        code=r'''
import os,sys
from pathlib import Path
from rife import stream
from rife.sessions import SessionStore
stream.STREAM_PID_FILE=Path(sys.argv[1]);stream.STREAM_STATUS_FILE=Path(sys.argv[2])
stream.WORKER_SESSION_ID=sys.argv[3]
store=SessionStore(stream.STREAM_PID_FILE,stream.STREAM_STATUS_FILE)
assert store.attach(sys.argv[3],os.getpid())
print('ready',flush=True)
sys.stdin.readline()
print('published='+str(store.publish(sys.argv[3],os.getpid(),{'duration':1})),flush=True)
stream.release_stream_files(Path(sys.argv[4]),failed=True)
print('retired cleanup done',flush=True)
'''
        child=subprocess.Popen([sys.executable,'-B','-c',code,str(self.pid),str(self.status),session,str(self.manifest)],stdin=subprocess.PIPE,stdout=subprocess.PIPE,stderr=subprocess.PIPE,text=True)
        try:
            self.assertEqual(child.stdout.readline().strip(),'ready')
            self.store.invalidate(session)
            successor=self.reserve('new',pid=222)
            self.store.publish(successor,222,dict(duration=200))
            self.manifest.write_text('successor')
            before={p:p.read_bytes() for p in (self.store.path,self.pid,self.status,self.manifest)}
            stdout,stderr=child.communicate('finish\n',timeout=10)
            self.assertEqual(child.returncode,0,stderr)
            self.assertIn('published=False',stdout)
            self.assertIn('retired cleanup done',stdout)
            self.assertEqual(before,{p:p.read_bytes() for p in before})
        finally:
            if child.poll() is None:child.kill()
            child.communicate(timeout=5)

    def test_rapid_real_spawn_and_seek_create_unique_sessions(self):
        # Real child acknowledges each session, then waits until WebUI retires it.
        code=r'''
import os,sys,time
from pathlib import Path
from rife.sessions import SessionStore
store=SessionStore(Path(sys.argv[1]),Path(sys.argv[2]))
sid=sys.argv[sys.argv.index('--session-id')+1]
assert store.attach(sid,os.getpid())
store.publish(sid,os.getpid(),{'duration':200,'start':0,'started_at':time.time()})
while True:time.sleep(1)
'''
        import time
        children=[];sessions=[]
        def command(*args,**kwargs):
            return [sys.executable,'-B','-u','-c',code,str(self.pid),str(self.status)]
        with patch.object(webui,'stream_command',side_effect=command),patch('sys.stderr',io.StringIO()):
            try:
                for i in range(6):
                    if i%2==0:webui.start_item(self.items[(i//2)%2].id)
                    else:webui.seek_to(10*i)
                    session=webui.PLAYBACK.session_id;sessions.append(session)
                    children.append(webui.STREAM_PROCESS)
                    deadline=time.monotonic()+5
                    while self.store.read()['state']!='running' and time.monotonic()<deadline:
                        time.sleep(0.01)
                    owner=self.store.read()
                    self.assertEqual(owner['state'],'running')
                    self.assertEqual(owner['session_id'],session)
                    self.assertEqual(owner['item_id'],self.playlist.current().id)
                    self.assertEqual(webui.read_stream_status()['session_id'],session)
                self.assertEqual(len(set(sessions)),6)
            finally:
                webui.stop_stream()
        self.assertTrue(all(child.poll() is not None for child in children))
        self.assertEqual(self.store.read()['state'],'stopped')
        self.assertFalse(self.status.exists())


if __name__=='__main__':
    unittest.main()
