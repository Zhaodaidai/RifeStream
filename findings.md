# Findings

## GPU copies
vs-mlrt RIFE always uploads RGBH and downloads YUV. FFmpeg has a vapoursynth *demuxer*, not a parallel filter. `getFrame` there is sequential, so replacing vspipe would cap TensorRT at one request.

Left in place: NVDEC scale_cuda → one hwdownload → pipe → RIFE H2D/D2H → Y4M → NVENC upload.

## Landed
NVENC `-gpu` uses the same device as RIFE.
