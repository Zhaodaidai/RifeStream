# Findings & Decisions

## Requirements
- Root should not mix CLI stubs, logs, pid files, and package code
- Windows protocol handler must still find `rife` when cwd is not the repo
- Existing `stream` / `webui` / `hls` / `protocol` / `check` behavior stays the same

## Research Findings
- Root wrappers only insert `ROOT` on `sys.path` and call `rife.*.main`
- `STREAM_CLI` / `PROTOCOL_CLI` are those wrapper paths; protocol registry embeds `mpv_protocol.py`
- HLS already launches `rife/hls_server.py` with its own bootstrap
- Logs, `.hls_server.*`, `.playlist.json` currently live in `ROOT`

## Technical Decisions
| Decision | Rationale | Alternatives considered |
|----------|-----------|------------------------|
| `run.py` dispatcher | One file; protocol can quote a stable path | Five `scripts/` stubs; `python -m rife.*` (breaks when cwd is wrong) |
| Not named `rife.py` | Would shadow or fight the `rife/` package | |
| `var/` state dir | Runtime files are not project source | `%LOCALAPPDATA%\rife` for logs too (HLS already uses that for segments) |

## Issues Encountered
-

## Resources
- `rife/paths.py` owns ROOT and state paths
- `tests/test_protocol.py` asserts CLI script path in `build_stream_command`
