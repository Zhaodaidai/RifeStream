# Task Plan: GPU passthrough (reduced scope)

## Goal
Cut avoidable GPU copies without rewriting vs-mlrt or serializing TensorRT.

## Current Phase
Phase 5

## Phases

### Phase 1: Requirements & Discovery
- [x] vs-mlrt needs CPU RGBH; FFmpeg vapoursynth demuxer getFrame is serial
- **Status:** complete

### Phase 2: Planning & Structure
- [x] Do not host RIFE inside `ffmpeg -f vapoursynth` (would stall `--gpu-threads`)
- [x] Pin NVENC to the same GPU as TRT
- **Status:** complete

### Phase 3: Implementation
- [x] Encoder `-gpu` matches `--gpu`
- **Status:** complete

### Phase 4: Testing & Verification
- [x] unittest
- **Status:** complete

### Phase 5: Delivery
- [x] Explain what was left on the table
- **Status:** complete

## Key Questions
1. Can TRT consume NVDEC CUDA frames? Not through vs-mlrt.
2. Can one FFmpeg process replace vspipe? Demuxer is serial; no parallel vapoursynth filter.

## Decisions Made
| Decision | Rationale |
|----------|-----------|
| Keep decoder \| vspipe \| encoder | Parallel TRT requests |
| NVENC `-gpu` | Avoid cross-GPU copies |
| No custom CUDA RIFE/NVENC graph | Too much for the remaining copies |

## Errors Encountered
| Error | Attempt | Resolution |
|-------|---------|------------|
