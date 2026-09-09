# Task Plan: Land gpu-threads, NVDEC, pipe copy

## Goal
Raise default TensorRT streams to 3, decode local files with NVDEC like the network path, and replace numpy stdin copies—without dropping interpolation quality.

## Current Phase
Phase 5

## Phases

### Phase 1: Requirements & Discovery
- [x] Confirm defaults, decoder split, pipe ModifyFrame
- **Status:** complete

### Phase 2: Planning & Structure
- [x] Always FFmpeg CUDA decode; pad width after scale; memoryview pipe fill
- **Status:** complete

### Phase 3: Implementation
- [x] gpu-threads default 3, allow 4
- [x] Local NVDEC + scale_cuda + pad-to-32
- [x] Pipe path only; no numpy
- [x] Tests and README
- **Status:** complete

### Phase 4: Testing & Verification
- [x] `python -m unittest discover -s tests` — 60 OK
- **Status:** complete

### Phase 5: Delivery
- [x] Summarize what changed
- **Status:** complete

## Key Questions
1. Pad or stretch 1910→1920? Pad, matching old local AddBorders.
2. Local seek: `-ss` after `-i` for frame-accurate trim.

## Decisions Made
| Decision | Rationale |
|----------|-----------|
| Always raw YUV pipe into VS | One decode path; BestSource skipped in stream |
| Pad after hwdownload | Same pixels as AddBorders, not scale-stretch |
| memoryview fill, not a new plugin | No extra VS plugin in runtime |
| Default gpu-threads 3, max 4 | Occupancy only; fp16 model unchanged |

## Errors Encountered
| Error | Attempt | Resolution |
|-------|---------|------------|
