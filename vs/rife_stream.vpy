from collections import OrderedDict
import os
import sys
import threading

import numpy as np
import vapoursynth as vs
from vapoursynth import core
import k7sfunc as k7f


def env_value(name: str, default: int | float) -> int | float:
    raw = os.environ.get(name, str(default))
    try:
        return type(default)(raw)
    except ValueError as exc:
        raise vs.Error(f"{name} has an invalid value: {raw}") from exc


factor = env_value("RIFE_FACTOR", 2)
max_height = env_value("RIFE_MAX_HEIGHT", 1080)
out_width = int(env_value("RIFE_OUT_WIDTH", 0))
out_height = int(env_value("RIFE_OUT_HEIGHT", 0))
gpu = env_value("RIFE_GPU", 0)
gpu_threads = env_value("RIFE_GPU_THREADS", 2)
scene_mode = env_value("RIFE_SCENE_MODE", 1)
workspace = env_value("RIFE_WORKSPACE_MIB", 0)
source_fps = env_value("RIFE_SOURCE_FPS", 0.0)
start_seconds = env_value("RIFE_START_SECONDS", 0.0)
duration_seconds = env_value("RIFE_DURATION_SECONDS", 0.0)
pipe_input = env_value("RIFE_PIPE_INPUT", 0) == 1
vs_threads = max(2, gpu_threads)

core.num_threads = vs_threads


def prepare_clip(clip: vs.VideoNode) -> vs.VideoNode:
    width, height = clip.width, clip.height
    if out_width > 0 and out_height > 0:
        width, height = out_width, out_height
    elif max_height and height > max_height:
        height = max_height // 2 * 2
        width = max(2, int(clip.width * height / clip.height) // 2 * 2)
        width = max(2, (width + 31) // 32 * 32)
    else:
        width = max(2, (width // 2 * 2 + 31) // 32 * 32)
        height = height // 2 * 2
    if height != clip.height or width < clip.width:
        clip = core.resize.Bilinear(clip, width=width, height=height)
    elif width > clip.width:
        clip = core.std.AddBorders(clip, right=width - clip.width)
    if clip.format.id != vs.YUV420P8:
        clip = core.resize.Bilinear(clip, format=vs.YUV420P8)
    return clip


if pipe_input:
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
    source = sys.stdin.buffer
    frame_size = pipe_width * pipe_height * 3 // 2
    cache_lock = threading.Condition()
    frame_cache: OrderedDict[int, memoryview] = OrderedDict()
    next_frame = 0
    last_requested = 0
    cache_ahead = max(8, vs_threads * 4)
    cache_keep = 4
    pipe_error: BaseException | None = None
    prefetch_stop = threading.Event()

    def read_exact(size: int) -> memoryview | None:
        buf = bytearray(size)
        view = memoryview(buf)
        offset = 0
        while offset < size:
            n = source.readinto(view[offset:])
            if not n:
                return None
            offset += n
        return view

    def store_frame(index: int, data: memoryview) -> None:
        frame_cache[index] = data
        while len(frame_cache) > cache_ahead + cache_keep:
            oldest = next(iter(frame_cache))
            if oldest >= last_requested - 1:
                break
            frame_cache.popitem(last=False)

    def read_next_locked() -> None:
        global next_frame, pipe_error
        if pipe_error is not None:
            raise pipe_error
        data = read_exact(frame_size)
        if data is None or len(data) != frame_size:
            pipe_error = vs.Error(f"Raw video pipe ended at frame {next_frame}")
            raise pipe_error
        store_frame(next_frame, data)
        next_frame += 1
        cache_lock.notify_all()

    def get_raw_frame(n: int) -> memoryview:
        global last_requested
        with cache_lock:
            last_requested = max(last_requested, n)
            cache_lock.notify_all()
            cached = frame_cache.get(n)
            if cached is not None:
                frame_cache.move_to_end(n)
                return cached
            if n < next_frame:
                raise vs.Error(f"Raw pipe frame {n} is no longer cached")
            while next_frame <= n:
                read_next_locked()
            return frame_cache[n]

    def prefetch_frames() -> None:
        try:
            while not prefetch_stop.is_set():
                with cache_lock:
                    if pipe_error is not None:
                        return
                    while (
                        not prefetch_stop.is_set()
                        and pipe_error is None
                        and next_frame > last_requested + cache_ahead
                    ):
                        cache_lock.wait(timeout=0.05)
                    if prefetch_stop.is_set() or pipe_error is not None:
                        return
                    read_next_locked()
        except BaseException:
            return

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
    plane_sizes = (
        pipe_width * pipe_height,
        (pipe_width // 2) * (pipe_height // 2),
        (pipe_width // 2) * (pipe_height // 2),
    )

    def read_pipe_frame(n: int, f: vs.VideoFrame) -> vs.VideoFrame:
        data = get_raw_frame(n)
        output = f.copy()
        offset = 0
        for plane, size in enumerate(plane_sizes):
            dest = np.asarray(output[plane])
            np.copyto(
                dest,
                np.frombuffer(data, dtype=np.uint8, count=size, offset=offset).reshape(
                    dest.shape
                ),
                casting="no",
            )
            offset += size
        return output

    clip = core.std.ModifyFrame(template, template, read_pipe_frame)
    threading.Thread(target=prefetch_frames, name="rife-pipe-prefetch", daemon=True).start()
else:
    input_path = globals().get("input")
    if not input_path:
        raise vs.Error("Pass the input file with vspipe --arg input=<path>")
    if not hasattr(core, "bs"):
        raise vs.Error("BestSource is not loaded (core.bs.VideoSource is missing)")

    clip = core.bs.VideoSource(
        source=input_path,
        variableformat=0,
        cachemode=0,
        showprogress=False,
    )
    if source_fps <= 0:
        if clip.fps_den <= 0 or clip.fps_num <= 0:
            raise vs.Error("The source frame rate is unknown; pass RIFE_SOURCE_FPS")
        source_fps = clip.fps_num / clip.fps_den

    start_frame = round(start_seconds * source_fps)
    end_frame = clip.num_frames
    if duration_seconds > 0:
        end_frame = min(end_frame, start_frame + round(duration_seconds * source_fps))
    if start_frame >= end_frame:
        raise vs.Error("The requested start/duration range contains no frames")
    clip = clip[start_frame:end_frame]
    clip = prepare_clip(clip)

engine_dir = os.environ.get("RIFE_ENGINE_DIR", "").strip()
if engine_dir:
    import vsmlrt

    _trt = vsmlrt.BackendV2.TRT

    def trt_with_local_engines(*args, **kwargs):
        kwargs.setdefault("engine_folder", engine_dir)
        return _trt(*args, **kwargs)

    vsmlrt.BackendV2.TRT = staticmethod(trt_with_local_engines)

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
