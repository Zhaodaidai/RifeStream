"""Small cross-process ownership transaction; never hold the lock while waiting on a child."""
from contextlib import contextmanager
import json
import os
from pathlib import Path
import tempfile
import threading
import time
import uuid

_LOCAL_LOCK = threading.RLock()


def read_json(path: Path) -> dict | None:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    return value if isinstance(value, dict) else None


def atomic_write(path: Path, data: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temporary = tempfile.mkstemp(prefix=path.name + ".", suffix=".tmp", dir=path.parent)
    try:
        with os.fdopen(descriptor, "wb") as output:
            output.write(data)
            output.flush()
        os.replace(temporary, path)
    finally:
        Path(temporary).unlink(missing_ok=True)


def atomic_json(path: Path, value: dict) -> None:
    atomic_write(path, json.dumps(value, ensure_ascii=False).encode("utf-8"))


class SessionStore:
    def __init__(self, pid_file: Path, status_file: Path):
        self.pid_file = pid_file
        self.status_file = status_file
        self.path = status_file.with_name("stream.session.json")
        self.lock_path = status_file.with_name("stream.session.lock")

    @contextmanager
    def locked(self):
        self.lock_path.parent.mkdir(parents=True, exist_ok=True)
        # OS locks are released on process death. The lock file is never unlinked.
        with _LOCAL_LOCK, self.lock_path.open("a+b") as lock:
            if os.name == "nt":
                import msvcrt
                if lock.seek(0, 2) == 0:
                    lock.write(b"\0")
                    lock.flush()
                lock.seek(0)
                msvcrt.locking(lock.fileno(), msvcrt.LK_LOCK, 1)
            else:
                import fcntl
                fcntl.flock(lock.fileno(), fcntl.LOCK_EX)
            try:
                yield self
            finally:
                if os.name == "nt":
                    lock.seek(0)
                    msvcrt.locking(lock.fileno(), msvcrt.LK_UNLCK, 1)
                else:
                    fcntl.flock(lock.fileno(), fcntl.LOCK_UN)

    def read(self) -> dict | None:
        return read_json(self.path)

    def matches(self, owner: dict | None, session_id: str, pid: int | None = None) -> bool:
        return bool(owner and owner.get("session_id") == session_id
                    and owner.get("state") not in {"stopped", "failed", "finished"}
                    and (pid is None or owner.get("pid") == pid))

    def reserve(self, item_id: str | None, start: float, duration: float) -> dict:
        with self.locked():
            current = self.read()
            if current and current.get("pid") is not None and current.get("state") in {"probing", "running"}:
                raise RuntimeError("Active playback session must be stopped before replacement")
            owner = dict(session_id=uuid.uuid4().hex, item_id=item_id, start=start,
                         duration=duration, pid=None, state="starting", created_at=time.time())
            atomic_json(self.path, owner)
            self.pid_file.unlink(missing_ok=True)
            self.status_file.unlink(missing_ok=True)
            return owner

    def attach(self, session_id: str, pid: int) -> bool:
        with self.locked():
            owner = self.read()
            if not self.matches(owner, session_id) or owner.get("pid") not in (None, pid):
                return False
            owner.update(pid=pid, state="probing")
            atomic_write(self.pid_file, str(pid).encode("ascii"))
            atomic_json(self.path, owner)
            return True

    def publish(self, session_id: str, pid: int, payload: dict) -> bool:
        with self.locked():
            owner = self.read()
            if not self.matches(owner, session_id, pid):
                return False
            status = dict(payload, session_id=session_id, item_id=owner.get("item_id"), pid=pid)
            atomic_json(self.status_file, status)
            owner.update(state="running")
            atomic_json(self.path, owner)
            return True

    def invalidate(self, expected: str | None = None) -> tuple[bool, dict | None]:
        """Revoke before signalling a process so its finalizer cannot touch shared files."""
        with self.locked():
            owner = self.read()
            if expected is not None and (not owner or owner.get("session_id") != expected):
                return False, owner
            if owner:
                owner["state"] = "stopped"
                atomic_json(self.path, owner)
            self.pid_file.unlink(missing_ok=True)
            self.status_file.unlink(missing_ok=True)
            return True, owner
