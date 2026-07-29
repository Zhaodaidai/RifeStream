import base64
from collections import deque
from dataclasses import dataclass, field
from datetime import datetime
import gzip
import io
from pathlib import Path
import shlex
import subprocess
import sys
from urllib.parse import unquote, urlsplit


ROOT = Path(__file__).resolve().parent
STREAM = ROOT / "stream.py"
LOG_FILE = ROOT / "mpv_protocol.log"
MAX_URI_LENGTH = 1_000_000
MAX_COMMAND_LENGTH = 256_000
HTTP_SCHEMES = {"http", "https"}
PROXY_SCHEMES = HTTP_SCHEMES | {"socks4", "socks4a", "socks5", "socks5h"}
HEADER_NAMES = {
    "origin": "Origin",
    "referer": "Referer",
    "cookie": "Cookie",
    "user-agent": "User-Agent",
}


class ProtocolError(ValueError):
    pass


@dataclass
class MpvRequest:
    video: str
    audio: str | None = None
    title: str | None = None
    start: float = 0.0
    headers: list[str] = field(default_factory=list)
    http_proxy: str | None = None
    ytdl_proxy: str | None = None
    ytdl_format: str | None = None


def decode_payload(payload: str) -> str:
    try:
        compressed = base64.b64decode(unquote(payload), validate=True)
        with gzip.GzipFile(fileobj=io.BytesIO(compressed)) as archive:
            decoded = archive.read(MAX_COMMAND_LENGTH + 1)
    except (OSError, ValueError) as exc:
        raise ProtocolError("The MPV payload is not valid gzip/Base64 data") from exc
    if len(decoded) > MAX_COMMAND_LENGTH:
        raise ProtocolError("The decoded MPV command is too large")
    try:
        return decoded.decode("utf-8")
    except UnicodeDecodeError as exc:
        raise ProtocolError("The decoded MPV command is not UTF-8") from exc


def validate_url(
    value: str, field_name: str, schemes: set[str] = HTTP_SCHEMES
) -> str:
    parsed = urlsplit(value)
    if parsed.scheme.lower() not in schemes or not parsed.netloc or any(
        char in value for char in "\r\n"
    ):
        allowed = "/".join(sorted(schemes))
        raise ProtocolError(f"{field_name} must be a valid {allowed} URL")
    return value


def parse_header(value: str) -> str:
    name, separator, header_value = value.partition(":")
    name = name.strip().lower()
    header_value = header_value.strip()
    if not separator or name not in HEADER_NAMES or not header_value:
        raise ProtocolError(f"Unsupported HTTP header: {name or value}")
    if any(char in header_value for char in "\r\n"):
        raise ProtocolError("HTTP headers cannot contain line breaks")
    return f"{HEADER_NAMES[name]}: {header_value}"


def parse_mpv_command(command: str) -> MpvRequest:
    try:
        arguments = shlex.split(command, posix=True)
    except ValueError as exc:
        raise ProtocolError(f"Invalid MPV command quoting: {exc}") from exc
    if not arguments:
        raise ProtocolError("The MPV command does not contain a video URL")

    request = MpvRequest(video=validate_url(arguments[0], "video"))
    for argument in arguments[1:]:
        if not argument.startswith("--"):
            continue
        name, separator, value = argument[2:].partition("=")
        name = name.lower()
        if not separator or not value:
            continue
        if name == "audio-file" and value:
            request.audio = validate_url(value, "audio")
        elif name == "sub-file" and value:
            validate_url(value, "subtitle")
        elif name == "http-header-fields" and value:
            request.headers.append(parse_header(value))
        elif name == "http-proxy" and value:
            request.http_proxy = validate_url(value, "HTTP proxy")
        elif name == "ytdl-format" and value:
            request.ytdl_format = value
        elif name == "ytdl-raw-options" and value.startswith("proxy=[") and value.endswith("]"):
            request.ytdl_proxy = validate_url(value[7:-1], "yt-dlp proxy", PROXY_SCHEMES)
        elif name == "force-media-title" and value:
            request.title = value
        elif name == "start" and value:
            try:
                request.start = float(value)
            except ValueError as exc:
                raise ProtocolError("MPV start time must be numeric") from exc
            if request.start < 0:
                raise ProtocolError("MPV start time cannot be negative")
    return request


def parse_ush_uri(uri: str) -> MpvRequest:
    if len(uri) > MAX_URI_LENGTH:
        raise ProtocolError("The ush URI is too large")
    parsed = urlsplit(uri)
    if parsed.scheme.lower() != "ush":
        raise ProtocolError("Only the ush protocol is supported")
    if parsed.netloc.lower() != "mpv":
        raise ProtocolError("Only ush://MPV is supported")
    if not parsed.query:
        raise ProtocolError("The ush://MPV URI has no payload")
    return parse_mpv_command(decode_payload(parsed.query))


def stream_command(request: MpvRequest) -> list[str]:
    command = [sys.executable, str(STREAM), request.video]
    for header in request.headers:
        command.extend(["--http-header-field", header])
    options = {
        "audio-input": request.audio,
        "http-proxy": request.http_proxy,
        "ytdl-proxy": request.ytdl_proxy,
        "ytdl-format": request.ytdl_format,
        "title": request.title,
        "start": format(request.start, ".12g") if request.start > 0 else None,
    }
    for name, value in options.items():
        if value:
            command.extend([f"--{name}", value])
    return command


def show_error(message: str) -> None:
    print(message, file=sys.stderr)
    if sys.platform == "win32":
        try:
            import ctypes

            ctypes.windll.user32.MessageBoxW(0, message, "RIFE MPV Receiver", 0x10)
        except OSError:
            pass


def run_stream(request: MpvRequest) -> int:
    command = stream_command(request)
    recent_output: deque[str] = deque(maxlen=20)
    with LOG_FILE.open("w", encoding="utf-8", errors="replace") as log:
        log.write(f"Started: {datetime.now().isoformat(timespec='seconds')}\n")
        log.write(f"Video: {request.video}\n")
        if request.audio:
            log.write(f"Audio: {request.audio}\n")
        log.write(f"HTTP headers: {len(request.headers)}\n")
        log.write(f"yt-dlp: {'yes' if request.ytdl_format else 'no'}\n\n")
        log.flush()
        try:
            process = subprocess.Popen(
                command,
                cwd=ROOT,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                text=True,
                encoding="utf-8",
                errors="replace",
            )
        except OSError as exc:
            message = f"Could not start the RIFE stream:\n{exc}\n\nLog: {LOG_FILE}"
            log.write(message + "\n")
            show_error(message)
            return 1
        for line in process.stdout or ():
            print(line, end="")
            log.write(line)
            log.flush()
            stripped = line.strip()
            if stripped:
                recent_output.append(stripped)
        exit_code = process.wait()
        log.write(f"\nExit code: {exit_code}\n")
    if exit_code != 0:
        summary = "\n".join(recent_output) or "No diagnostic output was produced."
        show_error(
            f"RIFE stream exited with code {exit_code}.\n\n{summary}\n\nLog: {LOG_FILE}"
        )
    return exit_code


def registry_command() -> str:
    return f'"{sys.executable}" "{Path(__file__).resolve()}" "%1"'


def install_protocol(force: bool) -> int:
    if sys.platform != "win32":
        print("Protocol registration is only available on Windows", file=sys.stderr)
        return 2
    import winreg

    protocol_path = r"Software\Classes\ush"
    command_path = protocol_path + r"\shell\open\command"
    existing = None
    try:
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, command_path) as key:
            existing = winreg.QueryValueEx(key, "")[0]
    except FileNotFoundError:
        pass
    ours = registry_command()
    if existing and existing != ours and not force:
        print("Another ush handler is already registered:", file=sys.stderr)
        print(existing, file=sys.stderr)
        print("Run 'mpv_protocol.py install --force' to replace it.", file=sys.stderr)
        return 2

    with winreg.CreateKey(winreg.HKEY_CURRENT_USER, protocol_path) as key:
        winreg.SetValueEx(key, "", 0, winreg.REG_SZ, "URL:USH MPV Protocol")
        winreg.SetValueEx(key, "URL Protocol", 0, winreg.REG_SZ, "")
        winreg.SetValueEx(key, "RifeHandler", 0, winreg.REG_DWORD, 1)
        if existing and existing != ours:
            winreg.SetValueEx(key, "RifePreviousCommand", 0, winreg.REG_SZ, existing)
    with winreg.CreateKey(winreg.HKEY_CURRENT_USER, command_path) as key:
        winreg.SetValueEx(key, "", 0, winreg.REG_SZ, ours)
    print("Registered ush://MPV for this Windows user.")
    print(ours)
    return 0


def uninstall_protocol() -> int:
    if sys.platform != "win32":
        print("Protocol registration is only available on Windows", file=sys.stderr)
        return 2
    import winreg

    protocol_path = r"Software\Classes\ush"
    command_path = protocol_path + r"\shell\open\command"

    def delete_tree(path: str) -> None:
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, path, 0, winreg.KEY_READ) as key:
            children = []
            index = 0
            while True:
                try:
                    children.append(winreg.EnumKey(key, index))
                    index += 1
                except OSError:
                    break
        for child in children:
            delete_tree(path + "\\" + child)
        winreg.DeleteKey(winreg.HKEY_CURRENT_USER, path)

    try:
        with winreg.OpenKey(
            winreg.HKEY_CURRENT_USER,
            command_path,
            0,
            winreg.KEY_WRITE | winreg.KEY_READ,
        ) as key:
            current = winreg.QueryValueEx(key, "")[0]
            if current != registry_command():
                print("The current ush handler does not belong to this program.", file=sys.stderr)
                return 2
            previous = None
            try:
                with winreg.OpenKey(winreg.HKEY_CURRENT_USER, protocol_path) as root_key:
                    previous = winreg.QueryValueEx(root_key, "RifePreviousCommand")[0]
            except FileNotFoundError:
                pass
            if previous:
                winreg.SetValueEx(key, "", 0, winreg.REG_SZ, previous)
        if not previous:
            delete_tree(protocol_path)
            print("Removed this ush handler.")
            return 0
        with winreg.OpenKey(
            winreg.HKEY_CURRENT_USER, protocol_path, 0, winreg.KEY_SET_VALUE
        ) as key:
            for name in ("RifeHandler", "RifePreviousCommand"):
                try:
                    winreg.DeleteValue(key, name)
                except FileNotFoundError:
                    pass
    except FileNotFoundError:
        print("ush://MPV is not registered for this program.")
        return 0
    print("Restored the previous ush handler.")
    return 0


def main() -> int:
    arguments = sys.argv[1:]
    if arguments and arguments[0] == "install":
        if len(arguments) > 2 or (len(arguments) == 2 and arguments[1] != "--force"):
            print("Usage: mpv_protocol.py install [--force]", file=sys.stderr)
            return 2
        return install_protocol("--force" in arguments)
    if arguments == ["uninstall"]:
        return uninstall_protocol()
    decode_only = len(arguments) == 2 and arguments[0] == "decode"
    if decode_only:
        uri = arguments[1]
    elif len(arguments) == 1:
        uri = arguments[0]
    else:
        print(
            "Usage: mpv_protocol.py <ush://MPV?...> | decode <URI> | "
            "install [--force] | uninstall",
            file=sys.stderr,
        )
        return 2
    try:
        request = parse_ush_uri(uri)
    except ProtocolError as exc:
        message = f"Invalid ush://MPV request:\n{exc}\n\nLog: {LOG_FILE}"
        LOG_FILE.write_text(message + "\n", encoding="utf-8")
        show_error(message)
        return 2
    if decode_only:
        print(request)
        return 0
    return run_stream(request)


if __name__ == "__main__":
    raise SystemExit(main())
