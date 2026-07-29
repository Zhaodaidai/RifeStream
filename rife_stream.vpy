import os

import vapoursynth as vs
from vapoursynth import core
import k7sfunc as k7f


def env_int(name: str, default: int) -> int:
    raw = os.environ.get(name, str(default))
    try:
        return int(raw)
    except ValueError as exc:
        raise vs.Error(f"{name} must be an integer, got: {raw}") from exc


def env_float(name: str, default: float) -> float:
    raw = os.environ.get(name, str(default))
    try:
        return float(raw)
    except ValueError as exc:
        raise vs.Error(f"{name} must be a number, got: {raw}") from exc


factor = env_int("RIFE_FACTOR", 2)
max_height = env_int("RIFE_MAX_HEIGHT", 1080)
gpu = env_int("RIFE_GPU", 0)
gpu_threads = env_int("RIFE_GPU_THREADS", 2)
scene_mode = env_int("RIFE_SCENE_MODE", 1)
workspace = env_int("RIFE_WORKSPACE_MIB", 0)
source_fps = env_float("RIFE_SOURCE_FPS", 0.0)
start_seconds = env_float("RIFE_START_SECONDS", 0.0)
duration_seconds = env_float("RIFE_DURATION_SECONDS", 0.0)

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
clip = k7f.FMT_CTRL(
    clip,
    h_max=max_height if max_height > 0 else clip.height,
    fmt_pix=1,
)
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
