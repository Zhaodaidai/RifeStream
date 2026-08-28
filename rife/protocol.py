import base64
from dataclasses import dataclass, field
import gzip
import io
from pathlib import Path
import shlex
import subprocess
import sys
from urllib.parse import unquote, urlsplit

from rife.paths import DETACHED_FLAGS, HTTP_SCHEMES, PROTOCOL_LOG_FILE, ROOT, STREAM_CLI


PROXY_SCHEMES = HTTP_SCHEMES | {"socks4", "socks4a", "socks5", "socks5h"}
HEADER_NAMES = {
    "origin": "Origin",
    "referer": "Referer",
    "cookie": "Cookie",
    "user-agent": "User-Agent",
}
PROTOCOL_NAMES = {
    "ush": "USH MPV Protocol",
    "mpv": "MPV URL Protocol",
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
            decoded = archive.read()
    except (OSError, ValueError) as exc:
        raise ProtocolError("The MPV payload is not valid gzip/Base64 data") from exc
    try:
        return decoded.decode("utf-8")
    except UnicodeDecodeError as exc:
        raise ProtocolError("The decoded MPV command is not UTF-8") from exc


def validate_url(
    value: str, field_name: str, schemes: set[str] = HTTP_SCHEMES
) -> str:
    parsed = urlsplit(value)
    if parsed.scheme.lower() not in schemes or not parsed.netloc:
        allowed = "/".join(sorted(schemes))
        raise ProtocolError(f"{field_name} must be a valid {allowed} URL")
    return value


def parse_header(value: str) -> str:
    name, separator, header_value = value.partition(":")
    name = name.strip().lower()
    header_value = header_value.strip()
    if not separator or name not in HEADER_NAMES or not header_value:
        raise ProtocolError(f"Unsupported HTTP header: {name or value}")
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
        if name == "audio-file":
            request.audio = validate_url(value, "audio")
        elif name == "http-header-fields":
            request.headers.append(parse_header(value))
        elif name == "http-proxy":
            request.http_proxy = validate_url(value, "HTTP proxy")
        elif name == "ytdl-format":
            request.ytdl_format = value
        elif name == "ytdl-raw-options" and value.startswith("proxy=[") and value.endswith("]"):
            request.ytdl_proxy = validate_url(value[7:-1], "yt-dlp proxy", PROXY_SCHEMES)
        elif name == "force-media-title":
            request.title = value
        elif name == "start":
            try:
                request.start = float(value)
            except ValueError as exc:
                raise ProtocolError("MPV start time must be numeric") from exc
    return request


def parse_uri(uri: str) -> MpvRequest:
    parsed = urlsplit(uri)
    scheme = parsed.scheme.lower()
    if scheme == "ush":
        if parsed.netloc.lower() != "mpv":
            raise ProtocolError("Only ush://MPV is supported")
        if not parsed.query:
            raise ProtocolError("The ush://MPV URI has no payload")
        return parse_mpv_command(decode_payload(parsed.query))
    if scheme != "mpv":
        raise ProtocolError("Only ush://MPV and mpv:// are supported")
    if parsed.query or parsed.fragment:
        raise ProtocolError("The complete target URL must be percent-encoded")
    payload = parsed.netloc + parsed.path
    if not payload:
        raise ProtocolError("The mpv URI has no target URL")
    try:
        target = unquote(payload, errors="strict")
    except UnicodeDecodeError as exc:
        raise ProtocolError("The mpv target URL is not valid UTF-8") from exc
    return MpvRequest(video=validate_url(target, "video"))


def build_stream_command(request: MpvRequest) -> list[str]:
    command = [sys.executable, str(STREAM_CLI), request.video]
    for header in request.headers:
        command.extend(["--http-header-field", header])
    options = {
        "audio-input": request.audio,
        "http-proxy": request.http_proxy,
        "ytdl-proxy": request.ytdl_proxy,
        "ytdl-format": request.ytdl_format,
        "title": request.title,
        "start": format(request.start, ".12g") if request.start else None,
    }
    for name, option in options.items():
        if option:
            command.extend([f"--{name}", option])
    return command


def start_stream(request: MpvRequest) -> int:
    interpreter = Path(sys.executable)
    pythonw = interpreter.with_name("pythonw.exe")
    if sys.platform == "win32" and pythonw.is_file():
        interpreter = pythonw
    command = build_stream_command(request)
    command[0] = str(interpreter)
    with PROTOCOL_LOG_FILE.open("ab", buffering=0) as log:
        log.write(f"\nStart: {request.video}\n".encode())
        subprocess.Popen(
            command,
            cwd=ROOT,
            stdin=subprocess.DEVNULL,
            stdout=log,
            stderr=subprocess.STDOUT,
            creationflags=DETACHED_FLAGS,
            close_fds=True,
        )
    return 0


def report_error(message: str) -> None:
    print(message, file=sys.stderr)
    with PROTOCOL_LOG_FILE.open("a", encoding="utf-8") as log:
        log.write(f"\n{message}\n")


def registry_command() -> str:
    interpreter = Path(sys.executable)
    pythonw = interpreter.with_name("pythonw.exe")
    if sys.platform == "win32" and pythonw.is_file():
        interpreter = pythonw
    return f'"{interpreter}" "{ROOT / "mpv_protocol.py"}" "%1"'


def install_protocol(force: bool) -> int:
    if sys.platform != "win32":
        print("Protocol registration is only available on Windows", file=sys.stderr)
        return 2
    import winreg

    ours = registry_command()
    existing_commands = {}
    for scheme in PROTOCOL_NAMES:
        command_path = rf"Software\Classes\{scheme}\shell\open\command"
        try:
            with winreg.OpenKey(winreg.HKEY_CURRENT_USER, command_path) as key:
                existing_commands[scheme] = winreg.QueryValueEx(key, "")[0]
        except FileNotFoundError:
            existing_commands[scheme] = None

    conflicts = {
        scheme: command
        for scheme, command in existing_commands.items()
        if command and command != ours
    }
    if conflicts and not force:
        for scheme, command in conflicts.items():
            print(f"Another {scheme} handler is already registered:", file=sys.stderr)
            print(command, file=sys.stderr)
        print("Run 'mpv_protocol.py install --force' to replace them.", file=sys.stderr)
        return 2

    for scheme, name in PROTOCOL_NAMES.items():
        protocol_path = rf"Software\Classes\{scheme}"
        command_path = protocol_path + r"\shell\open\command"
        existing = existing_commands[scheme]
        with winreg.CreateKey(winreg.HKEY_CURRENT_USER, protocol_path) as key:
            winreg.SetValueEx(key, "", 0, winreg.REG_SZ, f"URL:{name}")
            winreg.SetValueEx(key, "URL Protocol", 0, winreg.REG_SZ, "")
            if existing and existing != ours:
                winreg.SetValueEx(
                    key, "RifePreviousCommand", 0, winreg.REG_SZ, existing
                )
        with winreg.CreateKey(winreg.HKEY_CURRENT_USER, command_path) as key:
            winreg.SetValueEx(key, "", 0, winreg.REG_SZ, ours)
    print("Registered ush://MPV and mpv:// for this Windows user.")
    print(ours)
    return 0


def uninstall_protocol() -> int:
    if sys.platform != "win32":
        print("Protocol registration is only available on Windows", file=sys.stderr)
        return 2
    import winreg

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

    registered = {}
    ours = registry_command()
    for scheme in PROTOCOL_NAMES:
        command_path = rf"Software\Classes\{scheme}\shell\open\command"
        try:
            with winreg.OpenKey(winreg.HKEY_CURRENT_USER, command_path) as key:
                registered[scheme] = winreg.QueryValueEx(key, "")[0]
        except FileNotFoundError:
            registered[scheme] = None
    foreign = [
        scheme for scheme, command in registered.items() if command and command != ours
    ]
    if foreign:
        print(
            f"The current {', '.join(foreign)} handler does not belong to this program.",
            file=sys.stderr,
        )
        return 2

    changed = False
    for scheme, current in registered.items():
        if not current:
            continue
        changed = True
        protocol_path = rf"Software\Classes\{scheme}"
        command_path = protocol_path + r"\shell\open\command"
        previous = None
        try:
            with winreg.OpenKey(winreg.HKEY_CURRENT_USER, protocol_path) as root_key:
                previous = winreg.QueryValueEx(root_key, "RifePreviousCommand")[0]
        except FileNotFoundError:
            pass
        if not previous:
            delete_tree(protocol_path)
            print(f"Removed this {scheme} handler.")
            continue
        with winreg.OpenKey(
            winreg.HKEY_CURRENT_USER, command_path, 0, winreg.KEY_SET_VALUE
        ) as key:
            winreg.SetValueEx(key, "", 0, winreg.REG_SZ, previous)
        with winreg.OpenKey(
            winreg.HKEY_CURRENT_USER, protocol_path, 0, winreg.KEY_SET_VALUE
        ) as key:
            winreg.DeleteValue(key, "RifePreviousCommand")
        print(f"Restored the previous {scheme} handler.")
    if not changed:
        print("No protocol handler is registered for this program.")
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
            "Usage: mpv_protocol.py <ush://MPV?... | mpv://...> | decode <URI> | "
            "install [--force] | uninstall",
            file=sys.stderr,
        )
        return 2
    try:
        request = parse_uri(uri)
    except ProtocolError as exc:
        message = f"Invalid media protocol request:\n{exc}\n\nLog: {PROTOCOL_LOG_FILE}"
        report_error(message)
        return 2
    if decode_only:
        print(request)
        return 0
    try:
        return start_stream(request)
    except OSError as exc:
        report_error(f"Could not start stream:\n{exc}\n\nLog: {PROTOCOL_LOG_FILE}")
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
