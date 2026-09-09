import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

COMMANDS = {
    "stream": "rife.stream",
    "webui": "rife.webui",
    "hls": "rife.hls_server",
    "protocol": "rife.protocol",
    "check": "rife.check",
}


def main() -> int:
    if len(sys.argv) < 2 or sys.argv[1] not in COMMANDS:
        names = "|".join(COMMANDS)
        print(f"Usage: run.py {{{names}}} ...", file=sys.stderr)
        return 2
    module = __import__(COMMANDS[sys.argv.pop(1)], fromlist=["main"])
    return int(module.main())


if __name__ == "__main__":
    raise SystemExit(main())
