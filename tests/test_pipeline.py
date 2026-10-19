"""Lifecycle faults with real OS children; no GPU/media runtime required."""
import argparse
import contextlib
from fractions import Fraction
import io
import subprocess
import sys
import unittest
from unittest.mock import Mock, patch
from rife import stream


class PipelineLifecycleTests(unittest.TestCase):
    def setUp(self):
        self.source = stream.StreamInput('/fixture/video.mkv', None, [], None,
            stream.MediaInfo(Fraction(25), 1920, 1080, 60), Fraction(25))
        self.args = argparse.Namespace(start=0, duration=0, factor=2, gpu_threads=2)
        self.timeline = stream.build_timeline(self.source, self.args)

    def execute(self, decoder, vspipe, encoder, interrupt=False):
        runner = stream.PipelineRunner()
        command = lambda body: body if isinstance(body, list) else [sys.executable, '-u', '-c', body]
        stderr = io.StringIO()
        with patch.object(stream, 'build_decoder_command', return_value=command(decoder)), \
             patch.object(stream, 'build_vspipe_command', return_value=command(vspipe)), \
             patch.object(stream, 'build_encoder_command', return_value=command(encoder)), \
             patch.object(stream, 'build_environment', return_value=None), \
             contextlib.redirect_stderr(stderr):
            if interrupt:
                with patch.object(runner, 'wait', side_effect=KeyboardInterrupt):
                    result = runner.run(self.source, self.args, self.timeline)
            else:
                result = runner.run(self.source, self.args, self.timeline)
        for process in runner.processes.values():
            self.assertIsNotNone(process.poll(), 'live child leaked')
            if process.stdout is not None:
                self.assertTrue(process.stdout.closed, 'parent pipe leaked')
        self.assertIn('Pipeline result: ', stderr.getvalue())
        return result

    def test_natural_completion_drains_pipes(self):
        result = self.execute("import sys;sys.stdout.buffer.write(b'x'*4096)",
            'import sys,shutil;shutil.copyfileobj(sys.stdin.buffer,sys.stdout.buffer)',
            'import sys;assert len(sys.stdin.buffer.read())==4096')
        self.assertEqual((result.reason, result.returncode), ('finished', 0))
        self.assertEqual(result.exit_codes, {'decoder': 0, 'vspipe': 0, 'encoder': 0})

    def test_each_stage_failure_stops_remaining_children(self):
        for index, stage in enumerate(('decoder', 'vspipe', 'encoder')):
            with self.subTest(stage=stage):
                commands = ['import time;time.sleep(60)'] * 3
                commands[index] = f'raise SystemExit({7+index})'
                result = self.execute(*commands)
                self.assertEqual((result.reason, result.failed_stage, result.returncode), ('failed', stage, 7+index))
                self.assertEqual(result.exit_codes[stage], 7+index)
                self.assertEqual(set(result.stopped), {'decoder', 'vspipe', 'encoder'} - {stage})

    def test_encoder_early_success_is_not_upstream_failure(self):
        result = self.execute('import time;time.sleep(60)', 'import time;time.sleep(60)', 'pass')
        self.assertEqual((result.reason, result.returncode), ('finished', 0))
        self.assertEqual(set(result.stopped), {'decoder', 'vspipe'})
        self.assertTrue(all(code is not None for code in result.exit_codes.values()))

    def test_vspipe_budget_end_stops_decoder_while_encoder_finishes(self):
        result = self.execute('import time;time.sleep(60)', 'pass', 'import time;time.sleep(0.2)')
        self.assertEqual((result.reason, result.returncode), ('finished', 0))
        self.assertEqual(result.stopped, ('decoder',))

    def test_user_interrupt_reaps_all_children(self):
        result = self.execute(*(['import time;time.sleep(60)'] * 3), interrupt=True)
        self.assertEqual((result.reason, result.returncode), ('interrupted', 130))
        self.assertIsNone(result.failed_stage)
        self.assertEqual(set(result.stopped), {'decoder', 'vspipe', 'encoder'})

    def test_startup_failure_at_each_stage_cleans_started_children(self):
        for index, name in enumerate(('decoder', 'vspipe', 'encoder')):
            with self.subTest(stage=name):
                commands = ['import time;time.sleep(60)'] * 3
                commands[index] = ['/__missing_pipeline_executable__/never']
                result = self.execute(*commands)
                self.assertEqual((result.failed_stage, result.returncode), (name, 1))
                self.assertEqual(len(result.exit_codes), index)
                self.assertEqual(len(result.stopped), index)

    def test_upstream_failure_not_hidden_by_successful_encoder(self):
        runner = stream.PipelineRunner()
        for name, code in [('decoder', 7), ('vspipe', 0), ('encoder', 0)]:
            child = Mock(returncode=code);child.poll.return_value = code
            runner.processes[name] = child
        self.assertEqual(runner.wait(), ('failed', 7, 'decoder'))

    def test_signal_exit_maps_to_portable_nonzero(self):
        runner = stream.PipelineRunner()
        for name, code in [('decoder', -9), ('vspipe', None), ('encoder', None)]:
            child = Mock();child.poll.return_value = code
            runner.processes[name] = child
        self.assertEqual(runner.wait(), ('failed', 1, 'decoder'))

    def test_cleanup_continues_after_one_stop_error(self):
        runner = stream.PipelineRunner()
        for name in ('decoder', 'vspipe', 'encoder'):
            child = Mock();child.poll.return_value = None
            runner.processes[name] = child
        with patch.object(stream, 'stop_process', side_effect=[OSError('fixture'), None, None]) as stop:
            runner.cleanup()
        self.assertEqual(stop.call_count, 3)
        self.assertEqual(len(runner.cleanup_errors), 1)
        for child in runner.processes.values():
            child.stdout.close.assert_called_once()

    def test_stop_escalates_to_kill_with_bounded_reap(self):
        child = Mock();child.poll.return_value = None
        child.wait.side_effect = [subprocess.TimeoutExpired('fixture', 5), -9]
        stream.stop_process(child)
        child.terminate.assert_called_once();child.kill.assert_called_once()
        self.assertEqual([call.kwargs for call in child.wait.call_args_list], [{'timeout': 5}] * 2)

    def test_stop_handles_exit_between_poll_and_terminate(self):
        child = Mock();child.poll.return_value = None
        child.terminate.side_effect = ProcessLookupError;child.wait.return_value = 0
        stream.stop_process(child)
        child.wait.assert_called_once_with(timeout=5);child.kill.assert_not_called()

    def test_stop_reaps_child_already_exited(self):
        child = Mock();child.poll.return_value = 0
        stream.stop_process(child)
        child.wait.assert_called_once_with(timeout=5);child.terminate.assert_not_called()

    def test_stop_does_not_wait_forever_after_kill(self):
        child = Mock();child.poll.return_value = None
        child.wait.side_effect = subprocess.TimeoutExpired('fixture', 5)
        with self.assertRaises(subprocess.TimeoutExpired):
            stream.stop_process(child)
        self.assertEqual(child.wait.call_count, 2)


class PipelineResultTests(unittest.TestCase):
    def run_with_cleanup_error(self, initial):
        source = stream.StreamInput('/fixture/v', None, [], None,
            stream.MediaInfo(Fraction(25), 2, 2, 1), Fraction(25))
        args = argparse.Namespace(start=0, duration=0, factor=2, gpu_threads=2)
        runner = stream.PipelineRunner()
        children = [Mock(returncode=0) for _ in range(3)]
        for child in children:
            child.poll.return_value = 0
            child.stderr = None
        def cleanup():
            runner.cleanup_errors.append('fixture cleanup failure')
        with patch.object(stream, 'build_decoder_command', return_value=['fixture']), \
             patch.object(stream, 'build_vspipe_command', return_value=['fixture']), \
             patch.object(stream, 'build_encoder_command', return_value=['fixture']), \
             patch.object(stream, 'build_environment', return_value={}), \
             patch.object(stream.subprocess, 'Popen', side_effect=children), \
             patch.object(runner, 'wait', return_value=initial), \
             patch.object(runner, 'cleanup', side_effect=cleanup), \
             contextlib.redirect_stderr(io.StringIO()):
            return runner.run(source, args, stream.build_timeline(source, args))

    def test_cleanup_failure_is_not_reported_as_success(self):
        result = self.run_with_cleanup_error(('finished', 0, None))
        self.assertEqual((result.reason, result.returncode, result.failed_stage), ('cleanup_failed', 1, 'cleanup'))

    def test_cleanup_failure_does_not_replace_original_stage_failure(self):
        result = self.run_with_cleanup_error(('failed', 7, 'decoder'))
        self.assertEqual((result.reason, result.returncode, result.failed_stage), ('failed', 7, 'decoder'))
        self.assertEqual(result.cleanup_errors, ('fixture cleanup failure',))

    def test_stop_request_precedes_shutdown_exit_codes(self):
        runner = stream.PipelineRunner()
        runner.request_stop(15, None)
        self.assertEqual(runner.wait(), ('stopped', 143, None))

    @unittest.skipIf(sys.platform == 'win32', 'POSIX SIGTERM delivery')
    def test_sigterm_reaps_children_and_restores_handler_in_isolated_worker(self):
        code = r'''
import argparse,contextlib,io,os,signal,sys,threading
from fractions import Fraction
from unittest.mock import patch
from rife import stream
source=stream.StreamInput('/fixture/v',None,[],None,stream.MediaInfo(Fraction(25),2,2,1),Fraction(25))
args=argparse.Namespace(start=0,duration=0,factor=2,gpu_threads=2)
runner=stream.PipelineRunner()
previous=signal.getsignal(signal.SIGTERM)
original_wait=runner.wait
signal_sent=False
def wait():
    # Send a real signal only after the runner has installed its scoped handler.
    os.kill(os.getpid(),signal.SIGTERM)
    return original_wait()
command=[sys.executable,'-c','import time;time.sleep(60)']
with patch.object(stream,'build_decoder_command',return_value=command),patch.object(stream,'build_vspipe_command',return_value=command),patch.object(stream,'build_encoder_command',return_value=command),patch.object(stream,'build_environment',return_value=None),patch.object(runner,'wait',side_effect=wait):
    result=runner.run(source,args,stream.build_timeline(source,args))
assert result.reason=='stopped' and result.returncode==143,result
assert signal.getsignal(signal.SIGTERM)==previous
assert len(result.exit_codes)==3
assert all(p.poll() is not None for p in runner.processes.values())
assert all(p.stdout is None or p.stdout.closed for p in runner.processes.values())
print('SIGTERM: stopped=143; three children reaped; pipes closed; handler restored')
'''
        child = subprocess.run([sys.executable, '-B', '-c', code], capture_output=True, text=True, timeout=15)
        self.assertEqual(child.returncode, 0, child.stdout + child.stderr)
        self.assertIn('three children reaped', child.stdout)


class RealKillTests(unittest.TestCase):
    @unittest.skipIf(sys.platform == 'win32', 'POSIX ignored SIGTERM')
    def test_uncooperative_child_is_killed_and_reaped(self):
        child = subprocess.Popen([
            sys.executable, '-u', '-c',
            "import signal,time;signal.signal(signal.SIGTERM,signal.SIG_IGN);print('ready',flush=True);time.sleep(60)"
        ], stdout=subprocess.PIPE)
        try:
            self.assertEqual(child.stdout.readline(), b'ready\n')
            stream.stop_process(child)
            self.assertIsNotNone(child.poll())
            self.assertNotEqual(child.returncode, 0)
        finally:
            if child.poll() is None:
                child.kill()
                child.wait(timeout=5)
            child.stdout.close()


class PipeBoundaryTests(unittest.TestCase):
    def test_planned_consumer_end_preserves_decoder_broken_pipe_as_expected(self):
        source = stream.StreamInput('/fixture/v', None, [], None,
            stream.MediaInfo(Fraction(25), 2, 2, 1), Fraction(25))
        args = argparse.Namespace(start=0, duration=0, factor=2, gpu_threads=2)
        commands = [
            "import os;data=b'x'*65536\nwhile True: os.write(1,data)",
            "import sys;sys.stdin.buffer.read(1);sys.stdout.buffer.write(b'x');sys.stdout.flush()",
            "import sys;assert sys.stdin.buffer.read()==b'x'",
        ]
        runner = stream.PipelineRunner()
        with patch.object(stream, 'build_decoder_command', return_value=[sys.executable,'-u','-c',commands[0]]), \
             patch.object(stream, 'build_vspipe_command', return_value=[sys.executable,'-u','-c',commands[1]]), \
             patch.object(stream, 'build_encoder_command', return_value=[sys.executable,'-u','-c',commands[2]]), \
             patch.object(stream, 'build_environment', return_value=None), \
             contextlib.redirect_stderr(io.StringIO()):
            result = runner.run(source, args, stream.build_timeline(source,args))
        self.assertEqual((result.reason, result.returncode), ('finished', 0))
        self.assertTrue(result.decoder_pipe_end or 'decoder' in result.stopped)
        for child in runner.processes.values():
            self.assertIsNotNone(child.poll())
            for pipe in (child.stdout, child.stderr):
                if pipe is not None:
                    self.assertTrue(pipe.closed)
        if runner.decoder_stderr_thread is not None:
            self.assertFalse(runner.decoder_stderr_thread.is_alive())
        self.assertLessEqual(len(runner.decoder_stderr), 16384)

    def test_decoder_stderr_is_teed_with_bounded_diagnostic_memory(self):
        runner = stream.PipelineRunner()
        data = b'a'*4090 + b'Broken pipe' + b'b'*40000
        child = Mock(stderr=io.BytesIO(data))
        output = io.StringIO()
        with contextlib.redirect_stderr(output):
            runner.read_decoder_stderr(child)
        self.assertTrue(runner.decoder_broken_pipe)
        self.assertEqual(len(runner.decoder_stderr), 16384)
        self.assertEqual(output.getvalue(), data.decode())

    def test_decoder_exit_one_without_broken_pipe_is_still_failure(self):
        runner = stream.PipelineRunner()
        for name, code in [('decoder',1),('vspipe',0),('encoder',0)]:
            child=Mock();child.poll.return_value=code
            runner.processes[name]=child
        self.assertEqual(runner.wait(), ('failed',1,'decoder'))
        self.assertFalse(runner.decoder_pipe_end)


if __name__ == '__main__':
    unittest.main()
