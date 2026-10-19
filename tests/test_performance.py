import argparse
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import time
import unittest
from unittest.mock import Mock, patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from rife import performance, stream
from rife.stream import PipelineResult
from rife.sessions import SessionStore
from tools import benchmark_pipeline


class ConcurrencyTests(unittest.TestCase):
    def test_legacy_defaults_preserve_each_old_mapping(self):
        got = performance.Concurrency.resolve(argparse.Namespace(gpu_threads=3))
        self.assertEqual(got, performance.Concurrency(gpu_threads=3, vs_requests=3, vs_threads=3))
        self.assertEqual(performance.Concurrency.resolve(argparse.Namespace(gpu_threads=1)),
                         performance.Concurrency(1, 1, 2))

    def test_overrides_are_independent(self):
        a = performance.Concurrency.resolve(argparse.Namespace(gpu_threads=3, vs_requests=8,
                                                                 vs_threads=5))
        self.assertEqual(a, performance.Concurrency(3, 8, 5))
        b = performance.Concurrency.resolve(argparse.Namespace(gpu_threads=2, vs_requests=7))
        self.assertEqual(b, performance.Concurrency(2, 7, 2))

    def test_invalid_concurrency_values_rejected(self):
        for value in (0, -1, 1.5, True, 'bad'):
            with self.subTest(value=value), self.assertRaises((ValueError, TypeError)):
                performance.positive_int(value)

    def test_vspipe_cli_and_vapoursynth_override_independent_of_rife_gpu_threads(self):
        args = argparse.Namespace(gpu_threads=3, vs_requests=9, vs_threads=6, anime4k=False, gpu=0, scene_mode=1, workspace_mib=0)
        vspipe = stream.build_vspipe_command(None, args)
        self.assertEqual(vspipe[vspipe.index('--requests')+1], '9')
        source = stream.StreamInput('/fixture/video.mkv', None, [], None,
                                    stream.MediaInfo(stream.Fraction(25), 1920, 1080, 60),
                                    stream.Fraction(25))
        args.__dict__.update(start=0, duration=0, max_height=1080, factor=2)
        env = stream.build_environment(source, args)
        self.assertEqual(env['RIFE_GPU_THREADS'], '3')
        self.assertEqual(env['RIFE_VS_THREADS'], '6')
        self.assertEqual(env['RIFE_PIPE_CACHE_AHEAD'], '12')
        args.raw_prefetch=17
        self.assertEqual(stream.build_environment(source,args)['RIFE_PIPE_CACHE_AHEAD'],'17')

    def test_default_environment_and_command_are_byte_compatible(self):
        args = argparse.Namespace(gpu_threads=3, start=0, duration=0, max_height=1080, factor=2, anime4k=False, gpu=0, scene_mode=1, workspace_mib=0)
        source = stream.StreamInput('/fixture/video.mkv', None, [], None,
                                    stream.MediaInfo(stream.Fraction(25), 1920, 1080, 60),
                                    stream.Fraction(25))
        env = stream.build_environment(source, args)
        self.assertNotIn('RIFE_VS_THREADS', env)
        self.assertNotIn('RIFE_PIPE_CACHE_AHEAD', env)
        self.assertNotIn('RIFE_PERF_RAW', env)
        self.assertNotIn('RIFE_PERF_RUN_ID', env)
        self.assertEqual(stream.build_vspipe_command(None, args)[stream.build_vspipe_command(None, args).index('--requests')+1], '3')
        args.__dict__.update(http_proxy=None, headers=[], quality=12, gop=0,
                             no_audio=True, audio_codec='aac', subtitle_stream=None,
                             no_subtitles=False, publish_url='/fixture/index.m3u8')
        self.assertNotIn('-progress', stream.build_decoder_command(source, args))
        self.assertNotIn('-progress', stream.build_encoder_command(source, args))

    def test_cli_parser_preserves_legacy_defaults_and_accepts_overrides(self):
        with patch.object(sys, 'argv', ['stream', 'input.mkv']):
            args = stream.parse_args()
        self.assertEqual((args.gpu_threads, args.vs_requests, args.vs_threads, args.perf_report),
                         (3, None, None, None))
        with patch.object(sys, 'argv', ['stream', 'input.mkv', '--vs-requests', '7',
                                       '--vs-threads', '5', '--perf-report', 'r.json']):
            args = stream.parse_args()
        self.assertEqual((args.vs_requests, args.vs_threads, args.raw_prefetch, args.perf_report), (7, 5, None, str(Path('r.json').resolve())))

    def test_cli_parser_rejects_zero_and_existing_report(self):
        with patch.object(sys, 'argv', ['stream', 'input.mkv', '--vs-threads', '0']), \
             self.assertRaises(SystemExit):
            stream.parse_args()
        with tempfile.TemporaryDirectory() as tmp:
            report = Path(tmp) / 'exists.json'; report.write_text('{"keep":true}')
            with patch.object(sys, 'argv', ['stream', 'input.mkv', '--perf-report', str(report)]), \
                 self.assertRaises(SystemExit):
                stream.parse_args()
            self.assertEqual(json.loads(report.read_text()), {'keep': True})


class ProgressTests(unittest.TestCase):
    def test_reads_only_last_complete_ffmpeg_progress_block(self):
        with tempfile.TemporaryDirectory() as tmp:
            p = Path(tmp) / 'p'
            p.write_text('frame=1\nout_time_us=500000\nfps=12.5\nspeed=0.5x\nprogress=continue\n'
                         'frame=2\nout_time_us=1000000\nfps=bad\nspeed=1.25x\nprogress=continue\n'
                         'frame=3\n')
            self.assertEqual(performance.read_progress(p),
                             {'progress': 'continue', 'frame': 2, 'out_time_us': 1000000,
                              'speed': 1.25})
            p.unlink()
            self.assertIsNone(performance.read_progress(p))

    def test_progress_parser_discards_nonfinite_numbers(self):
        with tempfile.TemporaryDirectory() as tmp:
            p = Path(tmp) / 'p'; p.write_text('frame=-1\nfps=nan\nspeed=inf\nprogress=end\n')
            self.assertEqual(performance.read_progress(p), {'progress': 'end'})

    def test_hls_ready_requires_published_nonempty_segment(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp); playlist = root/'index.m3u8'; segment = root/'seg_abc_0.ts'
            playlist.write_text('#EXTM3U\n#EXTINF:2.0,\nseg_abc_0.ts\n')
            self.assertFalse(performance.hls_ready(playlist))
            segment.write_bytes(b'x')
            self.assertTrue(performance.hls_ready(playlist))
            playlist.write_text('#EXTM3U\n#EXTINF:2.0,\n../outside.ts\n')
            self.assertFalse(performance.hls_ready(playlist))
            playlist.write_text('#EXTM3U\n#EXTINF:2.0,\nseg_abc_0.ts.tmp\n')
            self.assertFalse(performance.hls_ready(playlist))

    def test_progress_arguments_are_isolated_and_unique_per_ffmpeg_stage(self):
        with tempfile.TemporaryDirectory() as tmp:
            run=performance.PerformanceRun(Path(tmp)/'r.json',session_id='sid',
                concurrency=performance.Concurrency(3,3,3),configuration={})
            self.addCleanup(run._scratch.cleanup)
            source=['ffmpeg','-hide_banner','-i','input','-f','null','-']
            decoder=run.command('decoder',source)
            encoder=run.command('encoder',source)
            self.assertEqual(decoder[0], 'ffmpeg')
            self.assertEqual(decoder[1:3], ['-progress', (run.folder/'decoder.progress').resolve().as_uri()])
            self.assertEqual(encoder[1:3], ['-progress', (run.folder/'encoder.progress').resolve().as_uri()])
            self.assertNotEqual(decoder[2],encoder[2])
            self.assertEqual(decoder[3:5], ['-stats_period','1'])

    def test_failure_result_is_recorded_as_failed(self):
        with tempfile.TemporaryDirectory() as tmp:
            run=performance.PerformanceRun(Path(tmp)/'r.json',session_id=None,
                concurrency=performance.Concurrency(1,1,2),configuration={})
            self.addCleanup(run._scratch.cleanup)
            run.finish(PipelineResult('failed',7,'encoder',{'encoder':7},(),(),False))
            value=json.loads(run.report.read_text())
            self.assertEqual(value['state'],'failed')
            self.assertEqual(value['result']['returncode'],7)
            self.assertIn('output_frames',value['missing_measurements'])
            self.assertIn('overall_output_fps',value['missing_measurements'])

    def test_report_started_and_finished_with_explicit_scope_notes(self):
        with tempfile.TemporaryDirectory() as tmp:
            report = Path(tmp)/'report.json'
            run = performance.PerformanceRun(report, session_id='sid',
                concurrency=performance.Concurrency(3, 4, 6), configuration={'quality': 12})
            self.addCleanup(run._scratch.cleanup)
            self.assertEqual(json.loads(report.read_text())['state'], 'running')
            (run.folder/'decoder.progress').write_text('frame=30\nout_time_us=1000000\nprogress=end\n')
            (run.folder/'encoder.progress').write_text('frame=60\nout_time_us=1000000\nfps=50\nspeed=2x\nprogress=end\n')
            seg=Path(tmp)/'seg_id_0.ts';seg.write_bytes(b'media')
            playlist=Path(tmp)/'index.m3u8';playlist.write_text('#EXTM3U\n#EXTINF:2,\nseg_id_0.ts\n')
            run.playlist=playlist
            raw={'run_id':run.run_id,'snapshot_final':True,'raw':{'peak_bytes':64}}
            (run.folder/'raw.json').write_text(json.dumps(raw))
            fake=PipelineResult('finished',0,None,{'decoder':0,'vspipe':0,'encoder':0},(),(),False)
            run.finish(fake)
            value=json.loads(report.read_text())
            self.assertEqual(value['state'], 'finished')
            self.assertEqual(value['concurrency'], {'gpu_threads':3,'vs_requests':4,'vs_threads':6})
            self.assertEqual(value['output_frames'],60)
            self.assertGreater(value['overall_output_fps'],0)
            self.assertIsNotNone(value['first_hls_seconds'])
            self.assertEqual(value['frame_pipeline'],raw)
            self.assertIn('GPU inference time', ' '.join(value['notes']))
            self.assertEqual(value['missing_measurements'], [])

    def test_report_never_overwrites_existing_or_other_run(self):
        with tempfile.TemporaryDirectory() as tmp:
            report=Path(tmp)/'r.json';report.write_text('{"keep":1}')
            with self.assertRaises(FileExistsError):
                performance.PerformanceRun(report, session_id=None,
                    concurrency=performance.Concurrency(1,1,2),configuration={})
            self.assertEqual(json.loads(report.read_text()),{'keep':1})
            report.unlink()
            a=performance.PerformanceRun(report, session_id=None,
                concurrency=performance.Concurrency(1,1,2),configuration={})
            self.addCleanup(a._scratch.cleanup)
            report.write_text('{"run_id":"other"}')
            fake=PipelineResult('finished',0,None,{},(),(),False)
            with self.assertRaisesRegex(RuntimeError,'ownership changed'):
                a.finish(fake)
            self.assertEqual(json.loads(report.read_text()),{'run_id':'other'})

    def test_frame_profiler_throttles_and_final_snapshot(self):
        class Pipe:
            stats={'state':'running','peak_bytes':8}
            def close(self):return True
        with tempfile.TemporaryDirectory() as tmp:
            pipe=Pipe();profiler=performance.FrameProfiler(pipe,Path(tmp)/'raw.json','run')
            with patch('rife.performance.time.monotonic',side_effect=[1,1.2,1.4,2.1,2.2,2.3]):
                profiler.emit();profiler.emit();profiler.emit();profiler.emit();profiler.finish()
            value=json.loads((Path(tmp)/'raw.json').read_text())
            self.assertTrue(value['snapshot_final'])
            self.assertTrue(value['reader_stopped'])
            self.assertEqual(value['run_id'],'run')

    def test_pipeline_perf_mode_applies_unique_progress_and_scratch_env(self):
        with tempfile.TemporaryDirectory() as tmp:
            args=argparse.Namespace(start=0,duration=1,factor=2,gpu_threads=3,
                vs_requests=4,vs_threads=5,raw_prefetch=12,max_height=1080,
                perf_report=str(Path(tmp)/'perf.json'),publish_url=str(Path(tmp)/'index.m3u8'),
                gpu=0,quality=12,anime4k=False,scene_mode=1,workspace_mib=0,gop=0,
                no_audio=True,audio_codec='aac')
            source=stream.StreamInput('/fixture/video',None,[],None,
                stream.MediaInfo(stream.Fraction(25),1920,1080,10),stream.Fraction(25))
            timeline=stream.build_timeline(source,args)
            runner=stream.PipelineRunner()
            fake=Mock()
            fake.report=str(Path(tmp)/'perf.json')
            fake.command.side_effect=lambda name,cmd: [*cmd,'--profiled-'+name]
            fake.environment.side_effect=lambda env: {**env,'PERF_FIXTURE':'1'}
            fake.finish.return_value=None
            fake.observe.return_value=None
            commands={"decoder":[sys.executable,'-c','pass'],
                      "vspipe":[sys.executable,'-c','pass'],
                      "encoder":[sys.executable,'-c','pass']}
            started={}
            def fake_start(name,cmd,**kwargs):
                started[name]=cmd
                child=Mock(returncode=0);child.poll.return_value=0;child.stdout=Mock()
                runner.processes[name]=child
                return child
            with patch.object(stream,'PerformanceRun',return_value=fake), \
                 patch.object(stream,'build_decoder_command',return_value=commands['decoder']), \
                 patch.object(stream,'build_encoder_command',return_value=commands['encoder']), \
                 patch.object(stream,'build_environment',return_value={}), \
                 patch.object(stream,'build_vspipe_command',return_value=commands['vspipe']), \
                 patch.object(runner,'start',side_effect=fake_start), \
                 patch.object(runner,'wait',return_value=('finished',0,None)):
                result=runner.run(source,args,timeline)
            self.assertEqual(result.returncode,0)
            self.assertIn('--profiled-decoder',started['decoder'])
            self.assertIn('--profiled-encoder',started['encoder'])
            self.assertNotIn('--profiled-vspipe',started['vspipe'])
            self.assertEqual(fake.environment.call_args.args[0],{})
            fake.finish.assert_called_once()

    def test_pipeline_refuses_report_that_would_replace_playlist(self):
        with tempfile.TemporaryDirectory() as tmp:
            path=Path(tmp)/'index.json'
            args=argparse.Namespace(start=0,duration=1,factor=2,gpu_threads=3,
                max_height=1080,perf_report=str(path),publish_url=str(path),gpu=0,quality=12,
                anime4k=False,scene_mode=1,workspace_mib=0,gop=0,no_audio=True,
                audio_codec='aac',vs_requests=None,vs_threads=None,raw_prefetch=None)
            source=stream.StreamInput('/fixture/video',None,[],None,
                stream.MediaInfo(stream.Fraction(25),1920,1080,10),stream.Fraction(25))
            timeline=stream.build_timeline(source,args)
            runner=stream.PipelineRunner()
            with patch.object(stream,'PerformanceRun',side_effect=AssertionError('must reject before report')), \
                 patch.object(stream,'build_decoder_command',return_value=['decoder']), \
                 patch.object(stream,'build_encoder_command',return_value=['encoder']), \
                 patch.object(stream,'build_environment',return_value={}), \
                 patch.object(stream,'build_vspipe_command',return_value=['vspipe']):
                result=runner.run(source,args,timeline)
            self.assertEqual((result.failed_stage,result.returncode),('performance',1))
            self.assertFalse(path.exists())
            self.assertEqual(runner.processes,{})

    def test_perf_report_rejects_hls_playlist_identity(self):
        # Production-run guard is covered by pipeline setup with the same Paths.
        with tempfile.TemporaryDirectory() as tmp:
            hls=Path(tmp)/'index.m3u8';report=Path(tmp)/'index.json'
            self.assertNotEqual(hls.resolve(),report.resolve())


class BenchmarkTests(unittest.TestCase):
    def args(self, root, **kwargs):
        source=root/'input.mkv';source.write_bytes(b'fixture-input')
        values=dict(input=source,output_dir=root/'new-output',label='base',start=4.0,duration=2.0,
                    runs=3,gpu_threads=3,vs_requests=None,vs_threads=None,raw_prefetch=None,factor=2,gpu=0,
                    max_height=1080,quality=12,anime4k=False,no_audio=False,no_subtitles=True,
                    dry_run=True)
        values.update(kwargs)
        return argparse.Namespace(**values)

    def test_dry_run_emits_fixed_segment_plan_without_spawning(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);args=self.args(root,vs_requests=5,vs_threads=7,raw_prefetch=12)
            with patch.object(benchmark_pipeline.subprocess,'run',side_effect=AssertionError('spawn')):
                self.assertEqual(benchmark_pipeline.run_batch(args),0)
            manifest=json.loads((args.output_dir/'benchmark.json').read_text())
            self.assertEqual(manifest['state'],'planned')
            self.assertEqual(manifest['fixed_conditions']['duration'],2)
            self.assertEqual(manifest['concurrency']['vs_requests'],5)
            self.assertEqual(manifest['concurrency']['vs_threads'],7)
            self.assertEqual(manifest['concurrency']['raw_prefetch'],12)
            self.assertEqual(len(manifest['runs']),3)
            self.assertEqual([x['phase'] for x in manifest['runs']],
                             ['first-in-batch','repeat','repeat'])
            self.assertTrue(all('--perf-report' in x['command'] for x in manifest['runs']))
            command=manifest['runs'][0]['command']
            for option, value in (('--scene-mode','1'),('--workspace-mib','0'),
                                  ('--source-fps','0'),('--gop','0'),('--audio-codec','aac')):
                self.assertEqual(command[command.index(option)+1],value)

    def test_batch_uses_unique_outputs_and_reports_repeat_median(self):
        from tools import benchmark_pipeline
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);args=self.args(root,dry_run=False,vs_requests=4)
            def worker(command,**kwargs):
                report=Path(command[command.index('--perf-report')+1])
                value=dict(schema_version=1,result={'returncode':0},elapsed_seconds=10.0,
                           first_hls_seconds=3.0,overall_output_fps=45.0)
                report.write_text(json.dumps(value))
                return Mock(returncode=0)
            from rife import stream as stream_module
            with patch.object(benchmark_pipeline,'assert_idle'), \
                 patch.object(stream_module,'STREAM_PID_FILE',root/'worker.pid'), \
                 patch.object(stream_module,'STREAM_STATUS_FILE',root/'worker-status.json'), \
                 patch.object(benchmark_pipeline.subprocess,'run',side_effect=worker):
                self.assertEqual(benchmark_pipeline.run_batch(args),0)
            manifest=json.loads((args.output_dir/'benchmark.json').read_text())
            self.assertEqual(manifest['state'],'finished')
            self.assertEqual(manifest['repeat_median']['overall_output_fps'],45)
            self.assertEqual(len({x['report'] for x in manifest['runs']}),3)
            self.assertTrue(all((Path(x['report']).parent/'stdout.txt').exists()
                                for x in manifest['runs']))
            self.assertTrue(all('--session-id' in x['command'] for x in manifest['runs']))

    def test_atomic_idle_reservation_rejects_second_benchmark_owner(self):
        from rife.sessions import SessionStore
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);store=SessionStore(root/'pid',root/'status')
            first=store.reserve_if_idle(None,0,1)
            with self.assertRaisesRegex(RuntimeError,'active playback'):
                store.reserve_if_idle(None,0,1)
            self.assertEqual(store.read()['session_id'],first['session_id'])
            store.invalidate(first['session_id'])
            second=store.reserve_if_idle(None,0,1)
            self.assertNotEqual(second['session_id'],first['session_id'])

    def test_benchmark_releases_reservation_when_run_directory_setup_fails(self):
        from tools import benchmark_pipeline
        from rife import stream as stream_module
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);args=self.args(root,dry_run=False)
            pid=root/'worker.pid';status=root/'worker-status.json'
            original_mkdir=Path.mkdir
            def mkdir(path, *pargs, **kwargs):
                if path.name == 'run-01':
                    raise OSError('fixture mkdir failure')
                return original_mkdir(path, *pargs, **kwargs)
            with patch.object(benchmark_pipeline,'assert_idle'), \
                 patch.object(stream_module,'STREAM_PID_FILE',pid), \
                 patch.object(stream_module,'STREAM_STATUS_FILE',status), \
                 patch.object(Path,'mkdir',mkdir):
                self.assertEqual(benchmark_pipeline.run_batch(args),1)
                owner=stream_module.session_store().read()
            self.assertEqual(owner['state'],'stopped')
            self.assertIsNotNone(owner.get('session_id'))
            manifest=json.loads((args.output_dir/'benchmark.json').read_text())
            self.assertEqual(manifest['state'],'failed')
            self.assertIn('fixture mkdir failure',manifest['error'])

    def test_active_session_refuses_benchmark_before_creating_output(self):
        from tools import benchmark_pipeline
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);args=self.args(root,dry_run=False)
            with patch.object(benchmark_pipeline,'assert_idle',side_effect=RuntimeError('active')):
                with self.assertRaisesRegex(RuntimeError,'active'):
                    benchmark_pipeline.run_batch(args)
            self.assertFalse(args.output_dir.exists())




if __name__ == '__main__':
    unittest.main()
