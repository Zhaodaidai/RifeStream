"""Bounded, single-reader raw-frame transport, independent of VapourSynth.

Borrowed views are valid only inside ``with pipe.borrow(index)``. Cache, pooled,
borrowed and in-flight frame buffers share one allocation budget. A generic
source must provide blocking readinto; cancellable sources also expose cancel().
No source handle is owned/closed by this module.
"""
from collections import Counter, OrderedDict
from contextlib import contextmanager
from dataclasses import dataclass
import os
import select
import threading
import time


class FramePipeError(RuntimeError):
    pass


class PipeEOF(FramePipeError):
    pass


class TruncatedFrame(FramePipeError):
    pass


class PipeReadError(FramePipeError):
    pass


class PipeCancelled(FramePipeError):
    pass


class FrameUnavailable(FramePipeError):
    pass


class InterruptiblePipeReader:
    """Cancellable unbuffered pipe IO; no extra Windows polling on the hot path.

    POSIX uses readiness before each raw read. Windows uses raw readinto plus
    CancelIoEx on this exclusively-read borrowed handle. close() retries cancel
    until the producer exits, covering the check-before-read cancellation race.
    A cancellation request alone is NOT proof of IO completion: join is required.
    """
    def __init__(self, raw, poll_interval=0.05):
        if poll_interval <= 0:
            raise ValueError("poll_interval must be positive")
        self.raw = raw
        self.fd = raw.fileno()
        self.poll_interval = poll_interval
        self._cancel = threading.Event()
        self._cancel_io = None
        if os.name == "nt":
            import ctypes
            from ctypes import wintypes
            import msvcrt
            self._ctypes = ctypes
            self._handle = msvcrt.get_osfhandle(self.fd)
            self._cancel_io = ctypes.WinDLL("kernel32", use_last_error=True).CancelIoEx
            self._cancel_io.argtypes = [wintypes.HANDLE, wintypes.LPVOID]
            self._cancel_io.restype = wintypes.BOOL

    def cancel(self):
        self._cancel.set()
        if self._cancel_io is not None and not self._cancel_io(self._handle, None):
            error = self._ctypes.get_last_error()
            if error != 1168:  # ERROR_NOT_FOUND: between IO calls; close retries.
                raise self._ctypes.WinError(error)

    def readinto(self, view):
        while not self._cancel.is_set():
            if os.name == "nt":
                return self.raw.readinto(view)
            ready, _, _ = select.select([self.fd], [], [], self.poll_interval)
            if ready:
                if self._cancel.is_set():
                    break
                return self.raw.readinto(view)
        raise PipeCancelled("Raw video pipe cancelled")


@dataclass
class _Frame:
    data: bytearray
    pins: int = 0


class RawFramePipe:
    def __init__(self, source, frame_size: int, *, frame_count: int,
                 cache_ahead: int = 12, cache_keep: int = 4,
                 max_frames: int = 16, max_bytes: int = 256 * 1024 * 1024,
                 profile: bool = False):
        values = (frame_size, frame_count, max_frames, max_bytes)
        if any(not isinstance(v, int) or isinstance(v, bool) or v <= 0 for v in values):
            raise ValueError("Frame size/count and buffer budgets must be positive integers")
        if any(not isinstance(v, int) or isinstance(v, bool) or v < 0
               for v in (cache_ahead, cache_keep)):
            raise ValueError("Cache lookahead/retention must be nonnegative integers")
        self.capacity = min(max_frames, max_bytes // frame_size)
        if self.capacity < 1:
            raise ValueError("Raw pipe byte budget cannot hold one frame")
        self.profile_enabled = bool(profile)
        self.observer = None
        self._metrics = dict(borrow_calls=0, delivered_frames=0, cache_hits=0, cache_misses=0,
                             borrow_wait_seconds=0.0, borrow_cache_wait_seconds=0.0, raw_read_seconds=0.0, raw_frame_read_attempts=0, source_readinto_calls=0,
                             copy_calls=0, copy_failures=0, copy_seconds=0.0,
                             buffer_backpressure_seconds=0.0)
        self.source = source
        self.frame_size = frame_size
        self.frame_count = frame_count
        self.cache_ahead = cache_ahead
        self.cache_keep = min(cache_keep, self.capacity - 1)
        self.max_bytes = max_bytes
        self._condition = threading.Condition()
        self._cancelled = threading.Event()
        self._cache = OrderedDict()
        self._pool = []
        self._pending = Counter()
        self._next = 0
        self._last_requested = 0
        self._allocated = 0
        self._peak = 0
        self._peak_cached = 0
        self._peak_pinned = 0
        self._state = "running"
        self._error = None
        self._thread = None

    def start(self):
        with self._condition:
            if self._thread is None and self._state == "running":
                try:
                    self._thread = threading.Thread(target=self._run, name="rife-pipe-reader",
                                                    daemon=True)
                    self._thread.start()
                except Exception as exc:
                    self._thread = None
                    self._state = "failed"
                    self._error = PipeReadError(f"Raw video pipe reader failed to start: {exc}")
                    self._error.__cause__ = exc
                    self._condition.notify_all()
        return self

    @property
    def stats(self):
        with self._condition:
            return dict(profile=dict(enabled=self.profile_enabled, **self._metrics),
                        state=self._state, next_frame=self._next,
                        allocated_frames=self._allocated,
                        allocated_bytes=self._allocated * self.frame_size,
                        peak_bytes=self._peak * self.frame_size,
                        cached_frames=len(self._cache),
                        pinned_frames=sum(e.pins > 0 for e in self._cache.values()),
                        pending_requests=sum(self._pending.values()),
                        peak_cached_frames=self._peak_cached,
                        peak_pinned_frames=self._peak_pinned,
                        reader_alive=self._thread is not None and self._thread.is_alive())

    def _buffer_locked(self):
        if self._pool:
            return self._pool.pop()
        if self._allocated < self.capacity:
            data = bytearray(self.frame_size)
            self._allocated += 1
            self._peak = max(self._peak, self._allocated)
            return data
        # Retain recent history; never evict a requested or borrowed frame.
        cutoff = self._last_requested - self.cache_keep + 1
        for index, frame in self._cache.items():
            if index < cutoff and not frame.pins and not self._pending[index]:
                del self._cache[index]
                return frame.data
        return None

    def copy_into(self, copier, output, data):
        if not self.profile_enabled:
            return copier(output, data)
        started = time.perf_counter()
        success = False
        try:
            result = copier(output, data)
            success = True
            return result
        finally:
            elapsed = time.perf_counter() - started
            with self._condition:
                self._metrics["copy_seconds"] += elapsed
                self._metrics["copy_calls"] += 1
                self._metrics["copy_failures"] += not success

    def _read_exact(self, data, index):
        if not self.profile_enabled:
            return self._read_bytes(data, index)
        started = time.perf_counter()
        try:
            return self._read_bytes(data, index)
        finally:
            elapsed = time.perf_counter() - started
            with self._condition:
                self._metrics["raw_read_seconds"] += elapsed
                self._metrics["raw_frame_read_attempts"] += 1

    def _read_bytes(self, data, index):
        with memoryview(data) as view:
            offset = 0
            while offset < self.frame_size:
                if self._cancelled.is_set():
                    raise PipeCancelled("Raw video pipe cancelled")
                n = self.source.readinto(view[offset:])
                if self.profile_enabled:
                    with self._condition:
                        self._metrics["source_readinto_calls"] += 1
                if n == 0:
                    if offset:
                        raise TruncatedFrame(
                            f"Raw video pipe truncated at frame {index}: "
                            f"{offset}/{self.frame_size} bytes")
                    raise PipeEOF(f"Raw video pipe ended at frame {index}")
                if not isinstance(n, int) or n < 0 or n > self.frame_size - offset:
                    raise PipeReadError(f"Invalid raw pipe readinto result: {n!r}")
                offset += n

    def _run(self):
        data = None
        try:
            while True:
                with self._condition:
                    while self._state == "running":
                        if self._next == self.frame_count:
                            self._state = "complete"
                            self._condition.notify_all()
                            return
                        if self._next <= self._last_requested + self.cache_ahead:
                            data = self._buffer_locked()
                            if data is not None:
                                break
                        if self.profile_enabled and self._next <= self._last_requested + self.cache_ahead:
                            started = time.perf_counter()
                            self._condition.wait()
                            self._metrics["buffer_backpressure_seconds"] += time.perf_counter() - started
                        else:
                            self._condition.wait()
                    if self._state != "running":
                        return
                    index = self._next
                # The single producer is the only reader; no state lock spans IO.
                self._read_exact(data, index)
                with self._condition:
                    if self._state == "cancelled":
                        self._pool.append(data)
                        data = None
                        return
                    self._cache[index] = _Frame(data)
                    self._peak_cached = max(self._peak_cached, len(self._cache))
                    data = None
                    self._next += 1
                    self._condition.notify_all()
        except BaseException as exc:
            with self._condition:
                if data is not None:
                    self._pool.append(data)
                if self._state != "cancelled":
                    if isinstance(exc, FramePipeError):
                        self._error = exc
                    else:
                        self._error = PipeReadError(f"Raw video pipe read failed: {exc}")
                        self._error.__cause__ = exc
                    self._state = ("eof" if isinstance(exc, PipeEOF) else
                                   "truncated" if isinstance(exc, TruncatedFrame) else "failed")
                self._condition.notify_all()

    @contextmanager
    def borrow(self, index: int):
        if not isinstance(index, int) or isinstance(index, bool) or not 0 <= index < self.frame_count:
            raise IndexError(f"Raw pipe frame outside declared range: {index!r}")
        started = time.perf_counter() if self.profile_enabled else None
        self.start()
        with self._condition:
            self._last_requested = max(self._last_requested, index)
            self._pending[index] += 1
            if self.profile_enabled:
                self._metrics["borrow_calls"] += 1
                self._metrics["cache_hits" if index in self._cache else "cache_misses"] += 1
            self._condition.notify_all()
            try:
                while True:
                    if self._state == "cancelled":
                        raise self._error
                    frame = self._cache.get(index)
                    if frame is not None:
                        view = memoryview(frame.data)
                        frame.pins += 1
                        self._peak_pinned = max(self._peak_pinned,
                            sum(entry.pins > 0 for entry in self._cache.values()))
                        if self.profile_enabled:
                            self._metrics["delivered_frames"] += 1
                        break
                    if index < self._next:
                        raise FrameUnavailable(f"Raw pipe frame {index} is no longer cached")
                    if self._error is not None:
                        raise self._error
                    wait_started = time.perf_counter() if self.profile_enabled else None
                    self._condition.wait()
                    if self.profile_enabled:
                        self._metrics["borrow_cache_wait_seconds"] += time.perf_counter() - wait_started
            finally:
                if self.profile_enabled:
                    self._metrics["borrow_wait_seconds"] += time.perf_counter() - started
                self._pending[index] -= 1
                if not self._pending[index]:
                    del self._pending[index]
                self._condition.notify_all()
        try:
            yield view
        finally:
            view.release()
            with self._condition:
                frame.pins -= 1
                self._condition.notify_all()
            if self.observer is not None:
                self.observer()

    def close(self, timeout: float = 1.0) -> bool:
        """Cancel waiters and bounded-join the producer; return whether it stopped.

        Generic blocking readers without cancel() may outlive the timeout until
        upstream closes. InterruptiblePipeReader used by VSPipe avoids that case.
        This never closes stdin or any borrowed handle.
        """
        with self._condition:
            if self._state == "running":
                self._state = "cancelled"
                self._error = PipeCancelled("Raw video pipe cancelled")
            self._cancelled.set()
            self._condition.notify_all()
            thread = self._thread
        cancel = getattr(self.source, "cancel", None)
        if thread is None:
            return True
        if thread is threading.current_thread():
            return False
        deadline = time.monotonic() + max(0.0, timeout)
        while thread.is_alive():
            if cancel is not None:
                cancel()
            thread.join(min(0.02, max(0.0, deadline - time.monotonic())))
            if thread.is_alive() and time.monotonic() >= deadline:
                return False
        return True
