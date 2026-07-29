from collections import OrderedDict
import os
import sys

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
gpu = env_value("RIFE_GPU", 0)
gpu_threads = env_value("RIFE_GPU_THREADS", 2)
scene_mode = env_value("RIFE_SCENE_MODE", 1)
workspace = env_value("RIFE_WORKSPACE_MIB", 0)
source_fps = env_value("RIFE_SOURCE_FPS", 0.0)
start_seconds = env_value("RIFE_START_SECONDS", 0.0)
duration_seconds = env_value("RIFE_DURATION_SECONDS", 0.0)
pipe_input = env_value("RIFE_PIPE_INPUT", 0) == 1

if factor < 2:
    raise vs.Error("RIFE_FACTOR must be at least 2")
if max_height < 0:
    raise vs.Error("RIFE_MAX_HEIGHT cannot be negative")
if gpu_threads < 1:
    raise vs.Error("RIFE_GPU_THREADS must be at least 1")
if scene_mode not in (0, 1, 2):
    raise vs.Error("RIFE_SCENE_MODE must be 0, 1, or 2")
if start_seconds < 0 or duration_seconds < 0:
    raise vs.Error("RIFE start and duration values cannot be negative")

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
    frame_cache: OrderedDict[int, bytes] = OrderedDict()
    next_frame = 0

    def read_exact(size: int) -> bytes:
        chunks = bytearray()
        while len(chunks) < size:
            chunk = source.read(size - len(chunks))
            if not chunk:
                break
            chunks.extend(chunk)
        return bytes(chunks)

    def get_raw_frame(n: int) -> bytes:
        global next_frame
        cached = frame_cache.get(n)
        if cached is not None:
            frame_cache.move_to_end(n)
            return cached
        if n < next_frame:
            raise vs.Error(f"Raw pipe frame {n} is no longer cached")
        while next_frame <= n:
            data = read_exact(frame_size)
            if len(data) != frame_size:
                raise vs.Error(f"Raw video pipe ended at frame {next_frame}")
            frame_cache[next_frame] = data
            next_frame += 1
            while len(frame_cache) > 8:
                frame_cache.popitem(last=False)
        return frame_cache[n]

    template = core.std.BlankClip(
        width=pipe_width,
        height=pipe_height,
        format=vs.YUV420P8,
        length=pipe_frames,
        fpsnum=pipe_fps_num,
        fpsden=pipe_fps_den,
    )

    def read_pipe_frame(n: int, f: vs.VideoFrame) -> vs.VideoFrame:
        data = get_raw_frame(n)
        output = f.copy()
        offset = 0
        for plane in range(3):
            plane_width = pipe_width if plane == 0 else pipe_width // 2
            plane_height = pipe_height if plane == 0 else pipe_height // 2
            size = plane_width * plane_height
            np.asarray(output[plane])[:] = np.frombuffer(
                data, dtype=np.uint8, count=size, offset=offset
            ).reshape(plane_height, plane_width)
            offset += size
        for prop in ("_Matrix", "_Transfer", "_Primaries", "_ColorRange"):
            output.props[prop] = 1
        return output

    clip = core.std.ModifyFrame(template, template, read_pipe_frame)
else:
    input_path = globals().get("input")
    if not input_path:
        raise vs.Error("Pass the input file with vspipe --arg input=<path>")
    if not hasattr(core, "bs"):
        raise vs.Error("BestSource is not loaded (core.bs.VideoSource is missing)")

    clip = core.bs.VideoSource(
        source=input_path,
        variableformat=0,
        cachemode=1,
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

# Keep the working resolution practical for real-time inference and force an
# encoder/browser-compatible 8-bit 4:2:0 output format.
clip = k7f.FMT_CTRL(clip, h_max=max_height or clip.height, fmt_pix=1)
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
)

clip.set_output()
