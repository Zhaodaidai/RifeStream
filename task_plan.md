# Task Plan: Tidy the repository root

## Goal
Leave the project root with only launchers and docs; one CLI entry, runtime junk in `var/`.

## Current Phase
Phase 5

## Phases

### Phase 1: Requirements & Discovery
- [x] List root files and how CLI / state paths are used
- [x] Document why wrappers exist (protocol handler cwd)
- **Status:** complete

### Phase 2: Planning & Structure
- [x] Single `run.py` dispatcher (not `rife.py`, package name collision)
- [x] State and logs under `var/`
- **Status:** complete

### Phase 3: Implementation
- [x] Add `run.py`, point STREAM_CLI at it
- [x] Move pid/log/playlist paths to `var/`
- [x] Update bats, README, check, protocol registry, tests
- [x] Delete five root wrappers
- **Status:** complete

### Phase 4: Testing & Verification
- [x] `python -m unittest discover -s tests` — 57 OK
- **Status:** complete

### Phase 5: Delivery
- [x] Summarize new root layout and commands
- **Status:** complete

## Key Questions
1. Can wrappers be deleted if protocol cwd is System32? Yes — `run.py` inserts ROOT via `__file__`.
2. Name the dispatcher `rife.py`? No — collides with the `rife/` package.

## Decisions Made
| Decision | Rationale |
|----------|-----------|
| `run.py` instead of `rife.py` | Same-directory package/module name clash |
| `var/` for pid, logs, playlist | Root stays a launch surface, not a dump |
| Keep two `.bat` files at root | Windows double-click launchers |

## Errors Encountered
| Error | Attempt | Resolution |
|-------|---------|------------|
