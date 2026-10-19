import ast
import ctypes
import io
import os
from pathlib import Path
import subprocess
import sys
import threading
import time
from types import SimpleNamespace
import unittest
from unittest.mock import patch

from rife.frame_pipe import (FrameUnavailable, InterruptiblePipeReader, PipeCancelled,
                             PipeEOF, PipeReadError, RawFramePipe, TruncatedFrame)


def wait_for(predicate, timeout=3):
    deadline = time.monotonic() + timeout
    while not predicate():
        if time.monotonic() >= deadline:
            raise AssertionError("condition timed out")
        time.sleep(0.002)


class ChunkReader:
    def __init__(self, payload, chunk=1):
        self.stream = io.BytesIO(payload)
        self.chunk = chunk
        self.readers = set()
        self.calls = 0

    def readinto(self, view):
        self.readers.add(threading.get_ident())
        self.calls += 1
        return self.stream.readinto(view[:self.chunk])


class GatedReader:
    def __init__(self):
        self.entered = threading.Event()
        self.release = threading.Event()

    def readinto(self, view):
        self.entered.set()
        if not self.release.wait(3):
            raise TimeoutError("gated reader not released")
        return 0

    def cancel(self):
        self.release.set()


class FramePipeTests(unittest.TestCase):
    def pipe(self, data=bytes(range(80)), size=4, **kwargs):
        opts = dict(frame_count=(len(data) // size if not hasattr(data, "readinto") else 20), cache_ahead=2, cache_keep=1,
                    max_frames=4, max_bytes=16)
        opts.update(kwargs)
        source = data if hasattr(data, 'readinto') else io.BytesIO(data)
        p = RawFramePipe(source, size, **opts)
        self.addCleanup(p.close)
        return p

    def test_partial_reads_reconstruct_all_bytes(self):
        data = bytes(range(80))
        source = ChunkReader(data)
        p = self.pipe(source, frame_count=20)
        result = []
        for i in range(20):
            with p.borrow(i) as view:
                result.append(bytes(view))
        self.assertEqual(b''.join(result), data)
        self.assertEqual(len(source.readers), 1)
        self.assertEqual(source.calls, 80)
        wait_for(lambda: p.stats['state'] == 'complete')
        self.assertFalse(p.stats['reader_alive'])

    def test_borrow_is_pinned_while_future_frame_evicts(self):
        p = self.pipe(cache_keep=0, max_frames=3, max_bytes=12)
        with p.borrow(0) as first:
            original = bytes(first)
            with p.borrow(18) as later:
                self.assertEqual(bytes(later), bytes(range(72, 76)))
            self.assertEqual(bytes(first), original)
            self.assertEqual(p.stats['pinned_frames'], 1)
        self.assertEqual(p.stats['pinned_frames'], 0)
        self.assertLessEqual(p.stats['peak_bytes'], 12)

    def test_lease_released_on_copy_exception(self):
        p = self.pipe()
        with self.assertRaisesRegex(ValueError, 'copy failed'):
            with p.borrow(0) as view:
                raise ValueError('copy failed')
        self.assertEqual(p.stats['pinned_frames'], 0)
        with self.assertRaises(ValueError):
            bytes(view)
        with p.borrow(19) as final:
            self.assertEqual(bytes(final), bytes(range(76, 80)))

    def test_two_borrows_of_same_frame_have_independent_lifetimes(self):
        p = self.pipe()
        with p.borrow(0) as first:
            with p.borrow(0) as second:
                self.assertEqual(bytes(first), bytes(second))
            self.assertEqual(bytes(first), bytes(range(4)))
            self.assertEqual(p.stats['pinned_frames'], 1)
        self.assertEqual(p.stats['pinned_frames'], 0)

    def test_byte_budget_is_stricter_than_frame_budget(self):
        p = self.pipe(max_frames=100, max_bytes=10)
        for i in range(20):
            with p.borrow(i):
                pass
        self.assertEqual(p.capacity, 2)
        self.assertEqual(p.stats['peak_bytes'], 8)

    def test_frame_budget_is_stricter_than_byte_budget(self):
        p = self.pipe(max_frames=2, max_bytes=4096)
        for i in range(20):
            with p.borrow(i):
                pass
        self.assertEqual(p.stats['peak_bytes'], 8)

    def test_one_buffer_budget_progresses_without_deadlock(self):
        p = self.pipe(max_frames=1, max_bytes=4)
        for i in range(20):
            with p.borrow(i) as view:
                self.assertEqual(bytes(view), bytes(range(i*4, (i+1)*4)))
        self.assertEqual(p.stats['peak_bytes'], 4)

    def test_all_pinned_causes_backpressure_then_resumes(self):
        p = self.pipe(max_frames=1, max_bytes=4)
        got = threading.Event()
        errors = []
        def later():
            try:
                with p.borrow(1) as view:
                    self.assertEqual(bytes(view), bytes(range(4, 8)))
                    got.set()
            except BaseException as exc:
                errors.append(exc)
        with p.borrow(0):
            t = threading.Thread(target=later)
            t.start()
            wait_for(lambda: p.stats['pending_requests'] == 1)
            self.assertFalse(got.wait(.03))
            self.assertEqual(p.stats['allocated_bytes'], 4)
        t.join(3)
        self.assertFalse(t.is_alive())
        self.assertFalse(errors)
        self.assertTrue(got.is_set())

    def test_history_out_of_order_in_retained_window(self):
        p = self.pipe(max_frames=6, max_bytes=24, cache_keep=3)
        for i in (0, 1, 2, 3, 2, 1, 3):
            with p.borrow(i) as view:
                self.assertEqual(bytes(view), bytes(range(i*4, (i+1)*4)))

    def test_evicted_frame_fails_instead_of_wrong_content(self):
        p = self.pipe()
        with p.borrow(19):
            pass
        with self.assertRaisesRegex(FrameUnavailable, 'frame 0.*no longer cached'):
            with p.borrow(0):
                pass

    def test_multiple_pending_frames_are_not_evicted(self):
        p = self.pipe(cache_ahead=8, cache_keep=0, max_frames=2, max_bytes=8)
        for base in range(0, 20, 2):
            errors = []
            barrier = threading.Barrier(2)
            def consume(i):
                try:
                    barrier.wait(3)
                    with p.borrow(i) as view:
                        time.sleep(.002)
                        self.assertEqual(bytes(view), bytes(range(i*4, (i+1)*4)))
                except BaseException as exc:
                    errors.append(exc)
            threads = [threading.Thread(target=consume, args=(i,)) for i in (base, base+1)]
            for t in threads:
                t.start()
            for t in threads:
                t.join(3)
                self.assertFalse(t.is_alive())
            # Requests may arrive after a frame was already evicted; only
            # explicitly unavailable is legal, never corrupt/silently wrong data.
            self.assertTrue(all(isinstance(e, FrameUnavailable) for e in errors), errors)

    def test_clean_eof_is_distinct_and_cached_frame_remains_readable(self):
        p = self.pipe(b'abcd', frame_count=3)
        with p.borrow(0) as view:
            self.assertEqual(bytes(view), b'abcd')
        with self.assertRaisesRegex(PipeEOF, 'ended at frame 1'):
            with p.borrow(1):
                pass
        self.assertEqual(p.stats['state'], 'eof')
        with p.borrow(0) as view:
            self.assertEqual(bytes(view), b'abcd')

    def test_truncated_frame_reports_index_and_byte_count(self):
        p = self.pipe(b'abcdef', frame_count=3)
        with self.assertRaisesRegex(TruncatedFrame, 'frame 1: 2/4 bytes'):
            with p.borrow(1):
                pass
        self.assertEqual(p.stats['state'], 'truncated')

    def test_reader_exception_is_propagated_with_original_cause(self):
        class Broken:
            def readinto(self, view):
                raise OSError('decoder lost')
        p = self.pipe(Broken(), frame_count=3)
        with self.assertRaisesRegex(PipeReadError, 'decoder lost') as ctx:
            with p.borrow(0):
                pass
        self.assertIsInstance(ctx.exception.__cause__, OSError)
        self.assertEqual(p.stats['state'], 'failed')

    def test_background_exception_wakes_all_waiters(self):
        s = GatedReader()
        p = self.pipe(s, frame_count=20)
        errors = []
        def borrow(i):
            try:
                with p.borrow(i):
                    pass
            except BaseException as exc:
                errors.append(exc)
        threads = [threading.Thread(target=borrow, args=(i,)) for i in range(6)]
        for t in threads:
            t.start()
        wait_for(lambda: p.stats['pending_requests'] == 6)
        s.release.set()
        for t in threads:
            t.join(3)
            self.assertFalse(t.is_alive())
        self.assertEqual(len(errors), 6)
        self.assertTrue(all(isinstance(e, PipeEOF) for e in errors))

    def test_read_does_not_hold_state_lock(self):
        s = GatedReader()
        p = self.pipe(s, frame_count=1).start()
        self.assertTrue(s.entered.wait(3))
        completed = threading.Event()
        t = threading.Thread(target=lambda: (p.stats, completed.set()))
        t.start()
        self.assertTrue(completed.wait(.3))
        t.join(3)
        self.assertTrue(p.close())

    def test_cancel_wakes_waiters_and_joins_cancellable_reader(self):
        s = GatedReader()
        p = self.pipe(s, frame_count=3)
        errors = []
        def borrow():
            try:
                with p.borrow(2):
                    pass
            except BaseException as exc:
                errors.append(exc)
        t = threading.Thread(target=borrow)
        t.start()
        self.assertTrue(s.entered.wait(3))
        self.assertTrue(p.close())
        t.join(3)
        self.assertFalse(t.is_alive())
        self.assertIsInstance(errors[0], PipeCancelled)
        self.assertEqual(p.stats['state'], 'cancelled')
        self.assertTrue(p.close())

    def test_generic_uncancellable_reader_is_bounded_and_reports_not_joined(self):
        s = GatedReader()
        source = SimpleNamespace(readinto=s.readinto)
        p = self.pipe(source, frame_count=1).start()
        self.assertTrue(s.entered.wait(3))
        try:
            self.assertFalse(p.close(timeout=.01))
            self.assertEqual(p.stats['state'], 'cancelled')
        finally:
            s.release.set()
        self.assertTrue(p.close())

    def test_cancel_does_not_recycle_active_borrow(self):
        p = self.pipe()
        with p.borrow(0) as view:
            expected = bytes(view)
            self.assertTrue(p.close())
            self.assertEqual(bytes(view), expected)
            with self.assertRaises(PipeCancelled):
                with p.borrow(0):
                    pass
        self.assertEqual(p.stats['pinned_frames'], 0)

    def test_close_preserves_completed_and_failed_terminal_states(self):
        complete = RawFramePipe(io.BytesIO(b'abcd'), 4, frame_count=1)
        with complete.borrow(0): pass
        wait_for(lambda: complete.stats['state'] == 'complete')
        self.assertTrue(complete.close())
        self.assertEqual(complete.stats['state'], 'complete')
        failed = RawFramePipe(io.BytesIO(b'a'), 4, frame_count=1)
        with self.assertRaises(TruncatedFrame):
            with failed.borrow(0): pass
        self.assertTrue(failed.close())
        self.assertEqual(failed.stats['state'], 'truncated')

    def test_cancel_before_start_does_not_spawn_thread(self):
        p = self.pipe()
        self.assertTrue(p.close())
        p.start()
        self.assertFalse(p.stats['reader_alive'])
        with self.assertRaises(PipeCancelled):
            with p.borrow(0):
                pass

    def test_declared_frame_count_does_not_overread(self):
        source = ChunkReader(bytes(range(80)), chunk=4)
        p = self.pipe(source, frame_count=2)
        with p.borrow(1) as view:
            self.assertEqual(bytes(view), bytes(range(4, 8)))
        wait_for(lambda: not p.stats['reader_alive'])
        self.assertEqual(source.calls, 2)
        self.assertEqual(p.stats['state'], 'complete')

    def test_invalid_parameters_and_indices(self):
        for opts in (dict(frame_size=0), dict(frame_count=0), dict(max_frames=0),
                     dict(max_bytes=3), dict(cache_keep=-1), dict(cache_ahead=-1),
                     dict(max_frames=True), dict(frame_count=1.5)):
            args = dict(frame_size=4, frame_count=2)
            args.update(opts)
            with self.subTest(opts=opts), self.assertRaises(ValueError):
                RawFramePipe(io.BytesIO(), **args)
        p = self.pipe()
        for n in (-1, 20, True, 0.5):
            with self.subTest(n=n), self.assertRaises(IndexError):
                with p.borrow(n):
                    pass

    def test_invalid_readinto_result_is_failure_not_eof(self):
        for result in (None, -1, 5):
            p = self.pipe(SimpleNamespace(readinto=lambda view: result), frame_count=1)
            with self.subTest(result=result), self.assertRaises(PipeReadError):
                with p.borrow(0):
                    pass

    def test_actual_os_pipe_short_reads_and_natural_eof(self):
        r, w = os.pipe()
        with os.fdopen(r, 'rb', buffering=0) as reader:
            p = self.pipe(InterruptiblePipeReader(reader), frame_count=3)
            def write():
                with os.fdopen(w, 'wb', buffering=0) as writer:
                    for piece in (b'a', b'bcd', b'ef', b'gh'):
                        writer.write(piece)
                        time.sleep(.002)
            t = threading.Thread(target=write)
            t.start()
            for i, expected in enumerate((b'abcd', b'efgh')):
                with p.borrow(i) as view:
                    self.assertEqual(bytes(view), expected)
            with self.assertRaises(PipeEOF):
                with p.borrow(2):
                    pass
            self.assertTrue(p.close())
            self.assertFalse(reader.closed)
            t.join(3)
            self.assertFalse(t.is_alive())

    def test_actual_os_pipe_cancel_while_upstream_stays_open(self):
        r, w = os.pipe()
        with os.fdopen(r, 'rb', buffering=0) as reader, os.fdopen(w, 'wb', buffering=0):
            p = self.pipe(InterruptiblePipeReader(reader), frame_count=1).start()
            time.sleep(.02)
            self.assertTrue(p.close(timeout=.5))
            self.assertFalse(p.stats['reader_alive'])
            self.assertFalse(reader.closed)

    def test_long_stream_is_byte_identical_and_memory_bounded(self):
        count = 1000
        data = b''.join(i.to_bytes(4, 'little') for i in range(count))
        p = self.pipe(data, frame_count=count, max_frames=3, max_bytes=12)
        for i in range(count):
            with p.borrow(i) as view:
                self.assertEqual(bytes(view), i.to_bytes(4, 'little'))
        self.assertLessEqual(p.stats['peak_bytes'], 12)
        self.assertTrue(p.close())

    def test_concurrent_copy_pinned_bytes_remain_stable(self):
        p = self.pipe(cache_keep=0)
        with p.borrow(0) as first:
            errors = []
            def copy_later():
                try:
                    for i in range(1, 20):
                        with p.borrow(i) as view:
                            self.assertEqual(bytes(view), bytes(range(i*4, (i+1)*4)))
                except BaseException as e:
                    errors.append(e)
            t = threading.Thread(target=copy_later)
            t.start()
            while t.is_alive():
                self.assertEqual(bytes(first), bytes(range(4)))
                time.sleep(.001)
            t.join(3)
            self.assertEqual(errors, [])


class VpyIntegrationTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.script = Path(__file__).resolve().parents[1] / 'vs/rife_stream.vpy'
        cls.text = cls.script.read_text()
        cls.tree = ast.parse(cls.text)

    def callback(self, pipe, fill):
        func = next(n for n in self.tree.body if isinstance(n, ast.FunctionDef)
                    and n.name == 'read_pipe_frame')
        namespace = dict(vs=SimpleNamespace(VideoFrame=object, Error=RuntimeError),
                         frame_pipe=pipe, fill_yuv420=fill, FramePipeError=__import__(
                             'rife.frame_pipe', fromlist=['FramePipeError']).FramePipeError)
        exec(compile(ast.Module(body=[func], type_ignores=[]), str(self.script), 'exec'), namespace)
        return namespace['read_pipe_frame']

    def test_production_callback_pins_until_all_planes_copied(self):
        p = RawFramePipe(io.BytesIO(bytes(range(40))), 4, frame_count=10,
                         max_frames=2, max_bytes=8, cache_keep=0)
        self.addCleanup(p.close)
        copied = []
        def fill(output, data):
            self.assertEqual(p.stats['pinned_frames'], 1)
            with p.borrow(9):
                pass
            copied.append(bytes(data))
        output = object()
        result = self.callback(p, fill)(0, SimpleNamespace(copy=lambda: output))
        self.assertIs(result, output)
        self.assertEqual(copied, [bytes(range(4))])
        self.assertEqual(p.stats['pinned_frames'], 0)

    def test_production_callback_exposes_truncated_message_as_vs_error(self):
        p = RawFramePipe(io.BytesIO(b'ab'), 4, frame_count=1)
        self.addCleanup(p.close)
        with self.assertRaisesRegex(RuntimeError, 'truncated at frame 0: 2/4 bytes'):
            self.callback(p, lambda *args: None)(0, SimpleNamespace(copy=lambda: object()))

    def test_production_callback_releases_on_copy_failure(self):
        p = RawFramePipe(io.BytesIO(b'abcd'), 4, frame_count=1)
        self.addCleanup(p.close)
        def fail(*args):
            raise ValueError('bad output stride')
        with self.assertRaises(ValueError):
            self.callback(p, fail)(0, SimpleNamespace(copy=lambda: object()))
        self.assertEqual(p.stats['pinned_frames'], 0)

    def test_portable_import_is_independent_of_current_directory(self):
        # Exercise the exact path/import statements of the .vpy in isolated mode.
        nodes = [n for n in self.tree.body if
                 (isinstance(n, ast.Expr) and isinstance(n.value, ast.Call)
                  and ast.unparse(n.value.func) == 'sys.path.insert') or
                 (isinstance(n, ast.ImportFrom) and n.module == 'rife.frame_pipe')]
        code = 'import sys\nfrom pathlib import Path\n__file__=' + repr(str(self.script)) + '\n'
        code += ast.unparse(ast.Module(body=nodes, type_ignores=[]))
        code += '\nprint(RawFramePipe.__module__)'
        result = subprocess.run([sys.executable, '-I', '-B', '-c', code], cwd='/tmp',
                                capture_output=True, text=True)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(result.stdout, 'rife.frame_pipe\n')


class AdditionalTransportTests(unittest.TestCase):
    def test_registered_out_of_order_requests_cannot_be_evicted(self):
        gate = threading.Event()
        entered = threading.Event()
        stream = io.BytesIO(b''.join(bytes([i])*4 for i in range(10)))
        def readinto(view):
            entered.set()
            if not gate.wait(3):
                raise TimeoutError('gate timed out')
            return stream.readinto(view)
        p = RawFramePipe(SimpleNamespace(readinto=readinto, cancel=gate.set), 4,
                         frame_count=10, max_frames=2, max_bytes=8, cache_keep=0)
        self.addCleanup(p.close)
        errors, outputs = [], {}
        def consume(i):
            try:
                with p.borrow(i) as view:
                    time.sleep(.002)
                    outputs[i] = bytes(view)
            except BaseException as exc:
                errors.append(exc)
        threads = [threading.Thread(target=consume, args=(i,)) for i in (3, 1, 7)]
        for t in threads:
            t.start()
        self.assertTrue(entered.wait(3))
        wait_for(lambda: p.stats['pending_requests'] == 3)
        gate.set()
        for t in threads:
            t.join(3)
            self.assertFalse(t.is_alive())
        self.assertEqual(errors, [])
        self.assertEqual(outputs, {i: bytes([i])*4 for i in (3, 1, 7)})
        self.assertEqual(p.stats['peak_bytes'], 8)

    def test_metrics_are_opt_in_and_copy_counts_are_separate(self):
        payload = bytes(range(16))
        plain = RawFramePipe(io.BytesIO(payload), 4, frame_count=4, max_frames=2, max_bytes=8)
        self.addCleanup(plain.close)
        self.assertFalse(plain.stats['profile']['enabled'])
        self.assertEqual(plain.stats['profile']['copy_calls'], 0)
        self.assertIsNone(plain.observer)
        profiled = RawFramePipe(io.BytesIO(payload), 4, frame_count=4, max_frames=2,
                                max_bytes=8, profile=True)
        self.addCleanup(profiled.close)
        copied = []
        def copier(output, data):
            copied.append(bytes(data))
            return 'done'
        with profiled.borrow(0) as data:
            self.assertEqual(profiled.copy_into(copier, None, data), 'done')
        self.assertEqual(copied, [bytes(range(4))])
        metrics = profiled.stats['profile']
        self.assertTrue(metrics['enabled'])
        self.assertEqual(metrics['borrow_calls'], 1)
        self.assertEqual(metrics['delivered_frames'], 1)
        self.assertEqual(metrics['copy_calls'], 1)
        self.assertGreaterEqual(metrics['copy_seconds'], 0)
        self.assertGreaterEqual(metrics['borrow_cache_wait_seconds'], 0)
        self.assertGreaterEqual(profiled.stats['peak_cached_frames'], 1)
        self.assertGreaterEqual(profiled.stats['peak_pinned_frames'], 1)
        with profiled.borrow(0):
            pass
        self.assertGreaterEqual(profiled.stats['profile']['cache_hits'], 1)

    def test_profiled_copy_failure_is_counted_and_raised(self):
        p = RawFramePipe(io.BytesIO(b'abcd'), 4, frame_count=1, profile=True)
        self.addCleanup(p.close)
        def fail(*args): raise ValueError('copy')
        with self.assertRaisesRegex(ValueError, 'copy'):
            p.copy_into(fail, None, memoryview(b'abcd'))
        self.assertEqual(p.stats['profile']['copy_failures'], 1)

    def test_reader_thread_start_failure_is_reported_without_hanging(self):
        p = RawFramePipe(io.BytesIO(b'abcd'), 4, frame_count=1)
        self.addCleanup(p.close)
        with patch('rife.frame_pipe.threading.Thread.start', side_effect=RuntimeError('no thread')):
            with self.assertRaisesRegex(PipeReadError, 'failed to start: no thread'):
                with p.borrow(0):
                    pass
        self.assertEqual(p.stats['state'], 'failed')
        self.assertFalse(p.stats['reader_alive'])
        with self.assertRaises(PipeReadError):
            with p.borrow(0):
                pass

    def test_producer_internal_failure_wakes_consumer(self):
        p = RawFramePipe(io.BytesIO(b'abcd'), 4, frame_count=1)
        self.addCleanup(p.close)
        with patch.object(p, '_buffer_locked', side_effect=RuntimeError('allocator failed')):
            with self.assertRaisesRegex(PipeReadError, 'allocator failed'):
                with p.borrow(0):
                    pass
        self.assertEqual(p.stats['state'], 'failed')

    def test_complete_yuv420_copy_preserves_padding_and_frame_content(self):
        root = Path(__file__).resolve().parents[1]
        tree = ast.parse((root / 'vs/rife_stream.vpy').read_text())
        functions = [n for n in tree.body if isinstance(n, ast.FunctionDef)
                     and n.name in ('copy_plane', 'fill_yuv420')]
        ns = dict(ctypes=ctypes, vs=SimpleNamespace(VideoFrame=object),
                  plane_dims=((4, 4), (2, 2), (2, 2)))
        exec(compile(ast.Module(body=functions, type_ignores=[]), 'rife_stream.vpy', 'exec'), ns)
        arrays = [bytearray([255] * 24), bytearray([255] * 8), bytearray([255] * 8)]
        frame = SimpleNamespace(get_stride=lambda plane: (6, 4, 4)[plane],
                                get_write_ptr=lambda plane: ctypes.addressof(
                                    ctypes.c_ubyte.from_buffer(arrays[plane])))
        p = RawFramePipe(io.BytesIO(bytes(range(24))), 24, frame_count=1)
        self.addCleanup(p.close)
        with p.borrow(0) as view:
            ns['fill_yuv420'](frame, view)
        self.assertEqual(arrays[0], b''.join(bytes(range(i, i+4))+b'\xff\xff'
                                          for i in range(0, 16, 4)))
        self.assertEqual(arrays[1], b'\x10\x11\xff\xff\x12\x13\xff\xff')
        self.assertEqual(arrays[2], b'\x14\x15\xff\xff\x16\x17\xff\xff')

    def windows_reader(self, source, cancel, error=1168):
        # Exercise Windows branch policy without claiming actual Win32 IO.
        reader = InterruptiblePipeReader.__new__(InterruptiblePipeReader)
        reader.raw = source
        reader._cancel = threading.Event()
        reader._handle = 42
        reader._ctypes = SimpleNamespace(get_last_error=lambda: error,
                                         WinError=lambda n: OSError(n, 'Win32 fixture'))
        reader._cancel_io = cancel
        return reader

    def test_windows_read_has_no_peek_or_timed_poll_mocked(self):
        source = io.BytesIO(b'abcdefgh')
        reader = self.windows_reader(source, lambda *args: True)
        buffer = bytearray(8)
        with patch('rife.frame_pipe.os.name', 'nt'):
            self.assertEqual(reader.readinto(memoryview(buffer)), 8)
        self.assertEqual(buffer, b'abcdefgh')
        self.assertFalse(source.closed)

    def test_windows_cancel_targets_borrowed_handle_without_closing_mocked(self):
        calls = []
        source = io.BytesIO()
        reader = self.windows_reader(source, lambda *args: calls.append(args) or True)
        reader.cancel()
        self.assertEqual(calls, [(42, None)])
        self.assertFalse(source.closed)
        with patch('rife.frame_pipe.os.name', 'nt'), self.assertRaises(PipeCancelled):
            reader.readinto(memoryview(bytearray(4)))

    def test_windows_cancel_not_found_is_benign_and_retried_mocked(self):
        calls = []
        reader = self.windows_reader(None, lambda *args: calls.append(args) or False)
        reader.cancel()
        reader.cancel()
        self.assertEqual(len(calls), 2)

    def test_windows_cancel_other_error_is_reported_mocked(self):
        reader = self.windows_reader(None, lambda *args: False, error=6)
        with self.assertRaises(OSError) as ctx:
            reader.cancel()
        self.assertEqual(ctx.exception.errno, 6)

    def test_close_retries_cancel_to_cover_check_before_read_race(self):
        reader = GatedReader()
        calls = []
        def cancel():
            calls.append(1)
            # First cancellation occurred before a pending read was registered.
            if len(calls) >= 2:
                reader.release.set()
        p = RawFramePipe(SimpleNamespace(readinto=reader.readinto, cancel=cancel),
                         4, frame_count=1).start()
        self.addCleanup(p.close)
        self.assertTrue(reader.entered.wait(3))
        self.assertTrue(p.close(timeout=.5))
        self.assertGreaterEqual(len(calls), 2)
        self.assertFalse(p.stats['reader_alive'])


class FullScriptTests(unittest.TestCase):
    def test_actual_vpy_graph_with_mock_plugins_keeps_metadata_and_bytes(self):
        from unittest.mock import Mock
        script = Path(__file__).resolve().parents[1] / 'vs/rife_stream.vpy'
        content = bytes(range(72))
        r, w = os.pipe()
        os.write(w, content)
        os.close(w)
        outputs, callbacks, closers = [], [], []
        class Frame:
            def __init__(self):
                self.planes = [bytearray(16), bytearray(4), bytearray(4)]
            def copy(self):
                return Frame()
            def get_stride(self, plane):
                return (4, 2, 2)[plane]
            def get_write_ptr(self, plane):
                return ctypes.addressof(ctypes.c_ubyte.from_buffer(self.planes[plane]))
        def set_output():
            for n in range(3):
                frame = callbacks[0](n, Frame())
                outputs.append(b''.join(frame.planes))
        clip = SimpleNamespace(set_output=set_output)
        blank = Mock(return_value=clip)
        props = Mock(return_value=clip)
        def modify(template, source, callback):
            callbacks.append(callback)
            return clip
        core = SimpleNamespace(std=SimpleNamespace(BlankClip=blank, SetFrameProps=props,
                                                   ModifyFrame=modify))
        rife = Mock(return_value=clip)
        environment = dict(RIFE_PIPE_WIDTH='4', RIFE_PIPE_HEIGHT='4', RIFE_PIPE_FRAMES='3',
                           RIFE_PIPE_FPS_NUM='24000', RIFE_PIPE_FPS_DEN='1001',
                           RIFE_FACTOR='3', RIFE_GPU_THREADS='2',
                           RIFE_VS_THREADS='7', RIFE_PIPE_CACHE_AHEAD='13')
        namespace = dict(__file__=str(script))
        with os.fdopen(r, 'rb', buffering=0) as raw:
            with patch.dict(sys.modules, vapoursynth=SimpleNamespace(core=core, YUV420P8=8,
                            VideoFrame=Frame, Error=RuntimeError),
                            k7sfunc=SimpleNamespace(RIFE_NV=rife)), \
                 patch.dict(os.environ, environment, clear=True), \
                 patch.object(sys, 'stdin', SimpleNamespace(buffer=SimpleNamespace(raw=raw))), \
                 patch('atexit.register', side_effect=closers.append):
                try:
                    exec(compile(script.read_text(), str(script), 'exec'), namespace)
                finally:
                    for close in closers:
                        self.assertTrue(close())
            self.assertFalse(raw.closed)
        self.assertEqual(b''.join(outputs), content)
        self.assertEqual(blank.call_args.kwargs, dict(width=4, height=4, format=8,
                         length=3, fpsnum=24000, fpsden=1001))
        self.assertEqual(props.call_args.kwargs,
                         dict(_Matrix=1, _Transfer=1, _Primaries=1, _ColorRange=1))
        self.assertEqual(namespace['vs_threads'], 7)
        self.assertEqual(namespace['cache_ahead'], 13)
        self.assertEqual(core.num_threads, 7)
        self.assertEqual(rife.call_args.kwargs, dict(model=4251, int8_qnt=False,
                         turbo=True, fps_in=24000/1001, fps_num=3, fps_den=1,
                         sc_mode=1, gpu=0, gpu_t=2, ws_size=0, vs_t=7))
        self.assertFalse(namespace['frame_pipe'].stats['reader_alive'])


if __name__ == '__main__':
    unittest.main()
