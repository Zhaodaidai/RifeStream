from collections import OrderedDict
import os
import sys
import threading

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
gpu = env_value("RIFE_GPU", 0)
gpu_threads = env_value("RIFE_GPU_THREADS", 3)
scene_mode = env_value("RIFE_SCENE_MODE", 1)
workspace = env_value("RIFE_WORKSPACE_MIB", 0)
vs_threads = max(2, gpu_threads)

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
source = sys.stdin.buffer
frame_size = pipe_width * pipe_height * 3 // 2
cache_lock = threading.Condition()
frame_cache: OrderedDict[int, memoryview] = OrderedDict()
buffer_pool: list[memoryview] = []
next_frame = 0
last_requested = 0
cache_ahead = max(8, vs_threads * 4)
cache_keep = 4
pipe_error: BaseException | None = None
prefetch_stop = threading.Event()
plane_dims = (
    (pipe_width, pipe_height),
    (pipe_width // 2, pipe_height // 2),
    (pipe_width // 2, pipe_height // 2),
)


def alloc_buffer() -> memoryview:
    return buffer_pool.pop() if buffer_pool else memoryview(bytearray(frame_size))


def read_exact(view: memoryview) -> bool:
    offset = 0
    while offset < frame_size:
        n = source.readinto(view[offset:])
        if not n:
            return False
        offset += n
    return True


def store_frame(index: int, data: memoryview) -> None:
    frame_cache[index] = data
    while len(frame_cache) > cache_ahead + cache_keep:
        oldest = next(iter(frame_cache))
        if oldest >= last_requested - 1:
            break
        buffer_pool.append(frame_cache.popitem(last=False)[1])


def read_next_locked() -> None:
    global next_frame, pipe_error
    if pipe_error is not None:
        raise pipe_error
    data = alloc_buffer()
    if not read_exact(data):
        buffer_pool.append(data)
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


def copy_plane(dest: memoryview, src: memoryview, width: int, height: int) -> None:
    packed = width * height
    if dest.contiguous and dest.nbytes == packed:
        dest.cast("B")[:packed] = src
        return
    if dest.ndim == 1:
        dest_b = dest.cast("B")
        stride = dest.nbytes // height
        offset = 0
        for row in range(height):
            start = row * stride
            dest_b[start : start + width] = src[offset : offset + width]
            offset += width
        return
    offset = 0
    for row in range(height):
        memoryview(dest[row]).cast("B")[:width] = src[offset : offset + width]
        offset += width


def fill_yuv420(output: vs.VideoFrame, data: memoryview) -> None:
    offset = 0
    for plane, (width, height) in enumerate(plane_dims):
        packed = width * height
        copy_plane(memoryview(output[plane]), data[offset : offset + packed], width, height)
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
    fill_yuv420(output, get_raw_frame(n))
    return output


clip = core.std.ModifyFrame(template, template, read_pipe_frame)
threading.Thread(target=prefetch_frames, name="rife-pipe-prefetch", daemon=True).start()

engine_dir = os.environ.get("RIFE_ENGINE_DIR", "").strip()
if engine_dir:
    import vsmlrt

    _trt = vsmlrt.BackendV2.TRT

    def trt_with_local_engines(*args, **kwargs):
        kwargs.setdefault("engine_folder", engine_dir)
        return _trt(*args, **kwargs)

    vsmlrt.BackendV2.TRT = staticmethod(trt_with_local_engines)

anime4k = int(env_value("RIFE_ANIME4K", 0))
out_width = int(env_value("RIFE_OUT_WIDTH", pipe_width))
out_height = int(env_value("RIFE_OUT_HEIGHT", pipe_height))

if anime4k:
    # Mode A for 1080→4K: Restore + Upscale×2. ACUpscale cannot run at 1×, so
    # acnet-hdn0 2× covers Restore+Upscale to 4K; then downscale back for RIFE/HLS.
    # (A second Upscale would go to 8K — not used when the working target is 4K.)
    if not hasattr(core, "anime4kcpp"):
        raise vs.Error(
            "Anime4K is enabled but the anime4kcpp plugin is missing "
            "(expected runtime/vs-plugins/ac_filter_avs_vs.dll)"
        )
    clip = core.anime4kcpp.ACUpscale(
        clip,
        factor=2.0,
        processor="cuda",
        device=int(gpu),
        model="acnet-hdn0",
    )
    if clip.width != out_width or clip.height != out_height:
        clip = core.resize.Lanczos(clip, width=out_width, height=out_height)

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
