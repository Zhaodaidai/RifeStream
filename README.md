# RIFE MediaMTX Stream

Pipeline:

```text
video file -> VapourSynth -> RIFE 4.25 Lite TensorRT
           -> FFmpeg h264_nvenc + Opus -> MediaMTX -> phone
```

All entry points are Python programs. The portable Python interpreter is stored
under `runtime`, so no system Python installation is required.

## Start streaming

The default input is:

```text
D:\rife\Smoking.Behind.the.Supermarket.with.You.S01E04.mp4
```

Run:

```bat
cd /d D:\rife
runtime\python.exe stream.py
```

Use another video:

```bat
runtime\python.exe stream.py "D:\video\input.mkv"
```

The script starts the local `mediamtx.exe` automatically when RTSP port 8554 is
not open. Press `Ctrl+C` to stop the video stream. MediaMTX remains available for
the next stream.

## Phone URLs

The current PC LAN address is `192.168.10.218`:

- WebRTC, lower latency: `http://192.168.10.218:8889/rife`
- HLS, more reliable: `http://192.168.10.218:8888/rife`
- VLC / RTSP: `rtsp://192.168.10.218:8554/rife`
- HLS playlist: `http://192.168.10.218:8888/rife/index.m3u8`

The phone and PC must be connected to the same LAN. Windows Firewall must allow
`mediamtx.exe` on the private network.

## Useful commands

```bat
rem Check the complete environment
runtime\python.exe check_setup.py

rem Check MediaMTX
runtime\python.exe mediamtx.py status

rem Restart MediaMTX from this directory
runtime\python.exe mediamtx.py restart --replace

rem Run only 10 seconds for testing
runtime\python.exe stream.py --duration 10

rem Lower RIFE working resolution when 1080p cannot stay real-time
runtime\python.exe stream.py --max-height 720 --video-bitrate 6000000

rem Use AAC when only HLS compatibility matters
runtime\python.exe stream.py --audio-codec aac
```

## Verified result

The provided test video was processed at `1920x1080`, from `23.976 fps` to
`47.952 fps`. RIFE, NVENC, Opus, RTSP publishing, HLS, and WebRTC all completed
successfully. During the live test, both phone web pages and the HLS playlist
returned HTTP 200.

The first run at a new resolution can pause while TensorRT builds an engine.
Later runs reuse the engine cache under
`runtime\vs-plugins\models\rife_v2`.
