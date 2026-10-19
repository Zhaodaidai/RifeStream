"""Run a fixed local clip repeatedly; first-in-batch is NOT guaranteed cold."""
import argparse
import hashlib
import json
from pathlib import Path
import statistics
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from rife.performance import positive_int
from rife.paths import STREAM_PID_FILE, pid_is_running, read_pid
from rife.sessions import SessionStore, atomic_json


def positive_seconds(text):
    import math
    value = float(text)
    if not math.isfinite(value) or value <= 0:
        raise argparse.ArgumentTypeError("must be a finite positive number")
    return value


def parse_args(argv=None):
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("input", type=Path)
    p.add_argument("--output-dir", type=Path, required=True, help="new output directory")
    p.add_argument("--label", required=True, help="human label; no cold/warm guarantee")
    p.add_argument("--start", type=float, default=0)
    p.add_argument("--duration", type=positive_seconds, default=30)
    p.add_argument("--runs", type=positive_int, default=3)
    p.add_argument("--gpu-threads", type=int, choices=(1, 2, 3, 4), default=3)
    p.add_argument("--vs-requests", type=positive_int)
    p.add_argument("--vs-threads", type=positive_int)
    p.add_argument("--raw-prefetch", type=positive_int)
    p.add_argument("--factor", type=int, choices=(2, 3, 4), default=2)
    p.add_argument("--gpu", type=int, choices=(0, 1, 2), default=0)
    p.add_argument("--max-height", type=int, default=1080)
    p.add_argument("--quality", type=int, choices=range(1, 31), default=12)
    p.add_argument("--anime4k", action="store_true")
    p.add_argument("--no-audio", action="store_true")
    p.add_argument("--no-subtitles", action="store_true")
    p.add_argument("--dry-run", action="store_true", help="write the real plan, do not start workers")
    args = p.parse_args(argv)
    import math
    if not math.isfinite(args.start) or args.start < 0 or args.max_height < 0:
        p.error("--start and --max-height must be finite/nonnegative")
    if not args.input.is_file():
        p.error("input must be an existing local video file")
    return args


def assert_idle():
    pid = read_pid(STREAM_PID_FILE)
    if pid is not None and pid_is_running(pid):
        raise RuntimeError("Stop current playback before benchmarking; no worker was replaced")
    # An in-flight pending startup may not have written a PID yet.
    from rife.stream import session_store
    owner = session_store().read()
    if owner and owner.get("state") in ("starting", "probing", "running"):
        raise RuntimeError("An active/pending playback session exists; stop it before benchmarking")


def run_batch(args, runner=None):
    if runner is None:
        runner = subprocess.run
    if not args.dry_run:
        assert_idle()
    source = args.input.expanduser().resolve()
    initial = source.stat()
    sha = hashlib.sha256()
    with source.open('rb') as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b''):
            sha.update(chunk)
    hashed = source.stat()
    if (initial.st_size, initial.st_mtime_ns) != (hashed.st_size, hashed.st_mtime_ns):
        raise RuntimeError('Input changed while hashing')
    folder = args.output_dir.expanduser().resolve()
    folder.mkdir(parents=True, exist_ok=False)
    base = [sys.executable, '-B', str(ROOT / 'run.py'), 'stream', str(source),
            '--start', str(args.start), '--duration', str(args.duration),
            '--gpu-threads', str(args.gpu_threads), '--gpu', str(args.gpu),
            '--factor', str(args.factor), '--max-height', str(args.max_height),
            '--quality', str(args.quality), '--scene-mode', '1',
            '--workspace-mib', '0', '--source-fps', '0', '--gop', '0',
            '--audio-codec', 'aac']
    for key in ('vs_requests', 'vs_threads', 'raw_prefetch'):
        value = getattr(args, key)
        if value is not None:
            base += ['--' + key.replace('_', '-'), str(value)]
    for key in ('anime4k', 'no_audio', 'no_subtitles'):
        if getattr(args, key):
            base += ['--' + key.replace('_', '-')]
    common = dict(input_sha256=sha.hexdigest(), start=args.start, duration=args.duration,
                  factor=args.factor, gpu=args.gpu, max_height=args.max_height,
                  quality=args.quality, anime4k=args.anime4k,
                  scene_mode=1, workspace_mib=0, audio_codec='aac', gop=0,
                  source_fps='auto', no_audio=args.no_audio, no_subtitles=args.no_subtitles)
    group = hashlib.sha256(json.dumps(common, sort_keys=True).encode()).hexdigest()
    jobs = []
    for i in range(args.runs):
        job_folder = folder / f'run-{i+1:02d}'
        jobs.append(dict(index=i+1, phase='first-in-batch' if i == 0 else 'repeat',
                         command=base + ['--publish-url', str(job_folder / 'index.m3u8'),
                                         '--perf-report', str(job_folder / 'report.json')],
                         report=str(job_folder / 'report.json')))
    payload = dict(schema_version=1, label=args.label, comparison_group=group,
                   fixed_conditions=common,
                   concurrency=dict(gpu_threads=args.gpu_threads, vs_requests=args.vs_requests,
                                    vs_threads=args.vs_threads, raw_prefetch=args.raw_prefetch),
                   state='planned' if args.dry_run else 'running', runs=jobs,
                   notes=['First-in-batch does not imply cold engine/disk/driver caches.',
                          'Input SHA256 is read before timing; this can warm the filesystem cache.',
                          'Use identical environment/material and only change one concurrency override.',
                          'Stop WebUI playback first; benchmark never deliberately replaces an active session.',
                          'Reports measure pipeline wall time, not isolated GPU inference.'])
    manifest = folder / 'benchmark.json'
    atomic_json(manifest, payload)
    if args.dry_run:
        print(manifest)
        return 0
    try:
        for job in jobs:
            from rife.stream import session_store
            store = session_store()
            try:
                owner = store.reserve_if_idle(None, args.start, args.duration)
            except RuntimeError:
                raise RuntimeError("An active/pending playback session exists; stop it before benchmarking")
            try:
                job['session_id'] = owner['session_id']
                command = list(job['command'])
                command += ['--session-id', owner['session_id']]
                job['command'] = command
                atomic_json(manifest, payload)
                current = source.stat()
                if (current.st_size, current.st_mtime_ns) != (initial.st_size, initial.st_mtime_ns):
                    raise RuntimeError('Input changed during benchmark')
                Path(job['report']).parent.mkdir()
                # Native stdout/stderr are preserved per run, not buffered in RAM.
                with (Path(job['report']).parent / 'stdout.txt').open('wb') as out, \
                     (Path(job['report']).parent / 'stderr.txt').open('wb') as err:
                    result = runner(command, cwd=ROOT, stdout=out, stderr=err)
            finally:
                store.abandon_if_active(owner['session_id'])
            job['exit_status'] = result.returncode
            if result.returncode != 0:
                payload['state'] = 'failed'
                atomic_json(manifest, payload)
                return result.returncode
            report = json.loads(Path(job['report']).read_text(encoding='utf-8'))
            if report.get('schema_version') != 1 or report.get('result', {}).get('returncode') != 0:
                raise RuntimeError('Worker report missing successful result')
            job['metrics'] = {key: report.get(key) for key in
                              ('elapsed_seconds', 'first_hls_seconds', 'overall_output_fps')}
            atomic_json(manifest, payload)
        payload['state'] = 'finished'
        repeats = [job['metrics'] for job in jobs[1:]]
        payload['repeat_median'] = {
            key: statistics.median([m[key] for m in repeats if isinstance(m.get(key), (float, int))])
            if any(isinstance(m.get(key), (float, int)) for m in repeats) else None
            for key in ('elapsed_seconds', 'first_hls_seconds', 'overall_output_fps')}
        return 0
    except KeyboardInterrupt:
        payload['state'] = 'interrupted'
        return 130
    except (OSError, ValueError, RuntimeError) as exc:
        payload.update(state='failed', error=str(exc))
        return 1
    finally:
        atomic_json(manifest, payload)
        print(manifest)


def main():
    try:
        return run_batch(parse_args())
    except (OSError, ValueError, RuntimeError) as exc:
        print(f'Error: {exc}', file=sys.stderr)
        return 1


if __name__ == '__main__':
    raise SystemExit(main())
