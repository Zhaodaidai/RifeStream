# Findings: quality-safe RIFE speedups

## Landed
- Default `--gpu-threads` is 3 (choices 1–4); VSPipe `--requests` stays aligned
- Local and HTTP both: FFmpeg NVDEC → scale_cuda → hwdownload → raw pipe → RIFE
- 1910×1080 still pads to 1920 after CUDA scale (not stretched)
- Local `-ss` is after `-i` (accurate); network `-ss` stays before `-i`
- `rife_stream.vpy` is pipe-only; numpy gone; packed YUV copied with memoryview + buffer pool

## Pipeline
Local/HTTP: NVDEC + scale_cuda → raw YUV pipe → SCDetect → RGBH → TRT RIFE → Y4M → NVENC → HLS

## Remaining
- GPU round-trips across three processes
- TRT builder tactics / workspace
- `get_frame(0)` at RIFE_NV load
