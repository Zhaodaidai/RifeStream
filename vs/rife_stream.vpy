import atexit
import ctypes
import os
import sys
from pathlib import Path

import vapoursynth as vs
from vapoursynth import core
import k7sfunc as k7f

# Portable Python uses an isolated ._pth; resolve from this script, not cwd.
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from rife.frame_pipe import FramePipeError, InterruptiblePipeReader, RawFramePipe


def env_value(name: str, default: int | float) -> int | float:
    raw = os.environ.get(name, str(default))
    try:
        return type(default)(raw)
    except ValueError as exc:
        raise vs.Error(f"{name} has an invalid value: {raw}") from exc


factor = env_value("RIFE_FACTOR", 2)
gpu = env_value("RIFE_GPU", 0)
gpu_threads = env_value("RIFE_GPU_THREADS", 3)
scene_mode = env_value("RIFE_SCENE_MODE", 1)
workspace = env_value("RIFE_WORKSPACE_MIB", 0)
vs_threads = env_value("RIFE_VS_THREADS", max(2, gpu_threads))
if vs_threads <= 0:
    raise vs.Error("RIFE_VS_THREADS must be positive")

core.num_threads = vs_threads

pipe_width = env_value("RIFE_PIPE_WIDTH", 0)
pipe_height = env_value("RIFE_PIPE_HEIGHT", 0)
pipe_frames = env_value("RIFE_PIPE_FRAMES", 0)
pipe_fps_num = env_value("RIFE_PIPE_FPS_NUM", 0)
pipe_fps_den = env_value("RIFE_PIPE_FPS_DEN", 1)
if min(pipe_width, pipe_height, pipe_frames, pipe_fps_num, pipe_fps_den) <= 0:
    raise vs.Error("The raw video pipe metadata is invalid")
if pipe_width % 2 or pipe_height % 2:
    raise vs.Error("The raw YUV420P8 pipe dimensions must be even")

source_fps = pipe_fps_num / pipe_fps_den
source = sys.stdin.buffer.raw
perf_raw_path = os.environ.get("RIFE_PERF_RAW", "").strip()
frame_size = pipe_width * pipe_height * 3 // 2
cache_ahead = env_value("RIFE_PIPE_CACHE_AHEAD", max(8, vs_threads * 4))
if cache_ahead <= 0:
    raise vs.Error("RIFE_PIPE_CACHE_AHEAD must be positive")
cache_keep = 4
plane_dims = (
    (pipe_width, pipe_height),
    (pipe_width // 2, pipe_height // 2),
    (pipe_width // 2, pipe_height // 2),
)
try:
    frame_pipe = RawFramePipe(
        InterruptiblePipeReader(source), frame_size, frame_count=pipe_frames,
        cache_ahead=cache_ahead, cache_keep=cache_keep,
        max_frames=cache_ahead + cache_keep,
        max_bytes=env_value("RIFE_PIPE_CACHE_MIB", 256) * 1024 * 1024,
        profile=bool(perf_raw_path),
    )
except (OSError, ValueError) as exc:
    raise vs.Error(f"Raw video pipe initialization failed: {exc}") from exc
atexit.register(frame_pipe.close)
if perf_raw_path:
    from rife.performance import FrameProfiler
    frame_profiler = FrameProfiler(frame_pipe, perf_raw_path, os.environ.get("RIFE_PERF_RUN_ID", ""))
    frame_pipe.observer = frame_profiler.emit
    atexit.register(frame_profiler.finish)


def copy_plane(
    frame: vs.VideoFrame,
    plane: int,
    source_pointer: int,
    source_offset: int,
    width: int,
    height: int,
) -> None:
    packed = width * height
    pointer = frame.get_write_ptr(plane)
    if isinstance(pointer, ctypes.c_void_p):
        pointer = pointer.value
    stride = frame.get_stride(plane)
    if stride == width:
        ctypes.memmove(pointer, source_pointer + source_offset, packed)
        return
    for row in range(height):
        ctypes.memmove(
            pointer + row * stride,
            source_pointer + source_offset + row * width,
            width,
        )


def fill_yuv420(output: vs.VideoFrame, data: memoryview) -> None:
    source_pointer = ctypes.addressof(ctypes.c_ubyte.from_buffer(data))
    offset = 0
    for plane, (width, height) in enumerate(plane_dims):
        packed = width * height
        copy_plane(output, plane, source_pointer, offset, width, height)
        offset += packed


template = core.std.BlankClip(
    width=pipe_width,
    height=pipe_height,
    format=vs.YUV420P8,
    length=pipe_frames,
    fpsnum=pipe_fps_num,
    fpsden=pipe_fps_den,
)
template = core.std.SetFrameProps(
    template,
    _Matrix=1,
    _Transfer=1,
    _Primaries=1,
    _ColorRange=1,
)


def read_pipe_frame(n: int, f: vs.VideoFrame) -> vs.VideoFrame:
    output = f.copy()
    try:
        with frame_pipe.borrow(n) as data:
            frame_pipe.copy_into(fill_yuv420, output, data)
    except FramePipeError as exc:
        raise vs.Error(str(exc)) from exc
    return output


clip = core.std.ModifyFrame(template, template, read_pipe_frame)
frame_pipe.start()

engine_dir = os.environ.get("RIFE_ENGINE_DIR", "").strip()
if engine_dir:
    import vsmlrt

    _trt = vsmlrt.BackendV2.TRT

    def trt_with_local_engines(*args, **kwargs):
        kwargs.setdefault("engine_folder", engine_dir)
        return _trt(*args, **kwargs)

    vsmlrt.BackendV2.TRT = staticmethod(trt_with_local_engines)

if int(env_value("RIFE_ANIME4K", 0)):
    # Optional enhancement: 2x then return to pipeline dimensions, before RIFE.
    if not hasattr(core, "anime4kcpp"):
        raise vs.Error("Anime4K enabled but anime4kcpp plugin is missing")
    clip = core.anime4kcpp.ACUpscale(
        clip, factor=2.0, processor="cuda", device=int(gpu), model="acnet-hdn0"
    )
    clip = core.resize.Lanczos(clip, width=pipe_width, height=pipe_height)

clip = k7f.RIFE_NV(
    clip,
    model=4251,
    int8_qnt=False,
    turbo=True,
    fps_in=source_fps,
    fps_num=factor,
    fps_den=1,
    sc_mode=scene_mode,
    gpu=gpu,
    gpu_t=gpu_threads,
    ws_size=workspace,
    vs_t=vs_threads,
)

clip.set_output()
