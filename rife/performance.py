"""Opt-in pipeline measurements. Wall-clock waiting is NOT GPU kernel time."""
from dataclasses import dataclass, asdict
import json
import math
from pathlib import Path
import tempfile
import threading
import time
import uuid

from rife.sessions import atomic_json


def positive_int(text):
    if isinstance(text, bool) or (isinstance(text, float) and not text.is_integer()):
        raise ValueError("must be a positive integer")
    try:
        value = int(text)
    except (TypeError, ValueError, OverflowError) as exc:
        raise ValueError("must be a positive integer") from exc
    if isinstance(text, str) and not text.strip().isdigit():
        raise ValueError("must be a positive integer")
    if value <= 0:
        raise ValueError("must be a positive integer")
    return value


@dataclass(frozen=True)
class Concurrency:
    gpu_threads: int
    vs_requests: int
    vs_threads: int

    @classmethod
    def resolve(cls, args):
        gpu = positive_int(args.gpu_threads)
        requests = getattr(args, "vs_requests", None)
        threads = getattr(args, "vs_threads", None)
        return cls(gpu, positive_int(gpu if requests is None else requests),
                   positive_int(max(2, gpu) if threads is None else threads))


def read_progress(path):
    """Last complete FFmpeg -progress block, bounded to a 64KiB tail."""
    try:
        with Path(path).open("rb") as f:
            f.seek(0, 2)
            start = max(0, f.tell() - 65536)
            f.seek(start)
            data = f.read(65536).decode("utf-8", errors="replace")
        if start:
            data = data.partition("\n")[2]
    except OSError:
        return None
    current, last = {}, None
    for line in data.splitlines():
        key, sep, value = line.partition("=")
        if sep:
            current[key.strip()] = value.strip()
            if key == "progress" and value in ("continue", "end"):
                last, current = current, {}
    if last is None:
        return None
    result = {"progress": last["progress"]}
    for key in ("frame", "out_time_us", "total_size"):
        try:
            value = int(last[key])
            if value >= 0:
                result[key] = value
        except (KeyError, ValueError):
            pass
    for key in ("fps", "speed"):
        try:
            value = float(last[key].rstrip("x"))
            if math.isfinite(value) and value >= 0:
                result[key] = value
        except (KeyError, ValueError):
            pass
    return result


def hls_ready(playlist):
    """A local published manifest referring to a nonempty completed segment."""
    playlist = Path(playlist)
    try:
        with playlist.open("r", encoding="utf-8") as f:
            text = f.read(65536)
        if not text.startswith("#EXTM3U"):
            return False
        after_extinf = False
        for line in text.splitlines():
            line = line.strip()
            if line.startswith("#EXTINF:"):
                after_extinf = True
            elif line and not line.startswith("#") and after_extinf:
                segment = (playlist.parent / line).resolve()
                if segment.parent == playlist.parent.resolve() and segment.suffix == ".ts":
                    if segment.is_file() and segment.stat().st_size > 0:
                        return True
                after_extinf = False
    except (OSError, ValueError):
        pass
    return False


class FrameProfiler:
    """Background sampler; frame callbacks only signal an Event (no disk IO)."""
    def __init__(self, pipe, path, run_id):
        self.pipe, self.path, self.run_id = pipe, Path(path), run_id
        self._lock = threading.Lock()
        self._changed = threading.Event()
        self._stop = threading.Event()
        self.error = None
        self._thread = threading.Thread(target=self._sample, name="rife-perf-sampler", daemon=True)
        self._thread.start()

    def emit(self, *, final=False, reader_stopped=None):
        # Kept as the RawFramePipe observer: only a nonblocking signal here.
        self._changed.set()

    def _write(self, *, final=False, reader_stopped=None):
        with self._lock:
            try:
                atomic_json(self.path, dict(run_id=self.run_id, snapshot_final=final,
                                           reader_stopped=reader_stopped, raw=self.pipe.stats))
            except Exception as exc:
                self.error = str(exc)

    def _sample(self):
        while not self._stop.is_set():
            self._changed.wait(1.0)
            self._changed.clear()
            if not self._stop.is_set():
                self._write()

    def finish(self):
        try:
            stopped = self.pipe.close()
        except Exception as exc:
            self.error = str(exc)
            stopped = False
        self._stop.set()
        self._changed.set()
        self._thread.join(timeout=2)
        self._write(final=True, reader_stopped=stopped)


class PerformanceRun:
    """One report/run identity and private progress files; no global status edits."""
    def __init__(self, report, *, session_id, concurrency, configuration):
        self.report = Path(report).expanduser().resolve()
        if self.report.suffix.lower() != ".json":
            raise ValueError("--perf-report must end in .json")
        self.report.parent.mkdir(parents=True, exist_ok=True)
        self.run_id = uuid.uuid4().hex
        self.started = time.monotonic()
        self.first_hls = None
        self._last_hls_poll = 0.0
        self.playlist = None
        self.payload = dict(schema_version=1, run_id=self.run_id, session_id=session_id,
                            state="running", timing_origin="pipeline_start_before_decoder",
                            concurrency=asdict(concurrency), configuration=configuration)
        # Exclusive reservation protects earlier reports, even concurrent callers.
        with self.report.open("x", encoding="utf-8") as f:
            json.dump(self.payload, f, ensure_ascii=False)
        try:
            self._scratch = tempfile.TemporaryDirectory(prefix=".rife-perf-", dir=self.report.parent)
        except BaseException:
            self.report.unlink(missing_ok=True)
            raise
        self.folder = Path(self._scratch.name)

    def command(self, name, command):
        # FFmpeg global options must precede input/output options. A unique
        # progress file avoids blocking or contaminating the normal log stream.
        return [command[0], "-progress", (self.folder / (name + ".progress")).resolve().as_uri(),
                "-stats_period", "1", *command[1:]]

    def environment(self, env):
        return {**env, "RIFE_PERF_RAW": str(self.folder / "raw.json"),
                "RIFE_PERF_RUN_ID": self.run_id}

    def observe(self):
        now = time.monotonic()
        if self.first_hls is None and self.playlist is not None and now - self._last_hls_poll >= 0.25:
            self._last_hls_poll = now
            if hls_ready(self.playlist):
                self.first_hls = now - self.started

    def finish(self, result):
        try:
            self.observe()
            elapsed = time.monotonic() - self.started
            decoder = read_progress(self.folder / "decoder.progress")
            encoder = read_progress(self.folder / "encoder.progress")
            raw = None
            try:
                candidate = json.loads((self.folder / "raw.json").read_text(encoding="utf-8"))
                if candidate.get("run_id") == self.run_id:
                    raw = candidate
            except (OSError, ValueError, AttributeError):
                pass
            frames = encoder.get("frame") if encoder else None
            payload = dict(self.payload, state=("finished" if result.returncode == 0 else "failed"), result=asdict(result),
                           elapsed_seconds=elapsed, first_hls_seconds=self.first_hls,
                           hls_poll_interval_seconds=0.25,
                           output_frames=frames,
                           overall_output_fps=frames / elapsed if frames is not None and elapsed > 0 else None,
                           decoder_progress=decoder, encoder_progress=encoder, frame_pipeline=raw,
                           missing_measurements=[name for name, value in
                               (("decoder_progress", decoder), ("encoder_progress", encoder),
                                ("output_frames", frames),
                                ("overall_output_fps", frames / elapsed if frames is not None and elapsed > 0 else None),
                                ("frame_pipeline", raw), ("first_hls_seconds", self.first_hls))
                               if value is None],
                           notes=["Wall time includes process/model startup, upstream starvation and cleanup; excludes input probing.",
                                  "raw_read_seconds includes waiting for upstream; borrow_cache_wait_seconds is time awaiting the requested frame; borrow_wait_seconds also includes scheduling/lock overhead.",
                                  "Concurrent callback time sums are not elapsed pipeline time or GPU inference time.",
                                  "overall_output_fps uses encoder frame count / pipeline wall time; encoder fps is not isolated encode speed.",
                                  "Raw buffer bytes exclude VapourSynth frames, Python RSS and GPU memory.",
                                  "A non-final raw snapshot may undercount work if VSPipe was terminated.",
                                  "first_hls_seconds is polled at approximately 250ms intervals, not browser first-paint."])
            # A retired run must not overwrite a report replaced by another owner.
            current = json.loads(self.report.read_text(encoding="utf-8"))
            if not isinstance(current, dict) or current.get("run_id") != self.run_id:
                raise RuntimeError("Performance report ownership changed")
            atomic_json(self.report, payload)
        finally:
            self._scratch.cleanup()
