"""Cooperative, crash-released OS file leases for native input devices."""
from __future__ import annotations
import os
from contextlib import contextmanager
from pathlib import Path
from .models import WorkflowError


@contextmanager
def device_lease(target: str):
    root = Path(os.environ.get("H2A_RUNTIME_DIR", str(Path.home()/".human2api")))
    if root.is_symlink():
        raise WorkflowError("native lock directory cannot be a symlink")
    root.mkdir(mode=0o700, parents=True, exist_ok=True)
    if os.name != "nt" and (root.stat().st_uid != os.getuid() or root.stat().st_mode & 0o077):
        raise WorkflowError("native lock directory must be owned by this user with mode 700")
    path = root / (target + ".lock")
    if path.is_symlink():
        raise WorkflowError("native device lock cannot be a symlink")
    fd = os.open(path, os.O_RDWR | os.O_CREAT | getattr(os, "O_NOFOLLOW", 0), 0o600)
    locked = False
    try:
        if os.name == "nt":
            import msvcrt
            if os.fstat(fd).st_size == 0:
                os.write(fd, b"0")
            os.lseek(fd, 0, os.SEEK_SET)
            try:
                msvcrt.locking(fd, msvcrt.LK_NBLCK, 1)
            except OSError as exc:
                raise WorkflowError(f"{target} device is busy in another process") from exc
        else:
            import fcntl
            try:
                fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
            except BlockingIOError as exc:
                raise WorkflowError(f"{target} device is busy in another process") from exc
        locked = True
        yield
    finally:
        if locked:
            if os.name == "nt":
                os.lseek(fd, 0, os.SEEK_SET)
                msvcrt.locking(fd, msvcrt.LK_UNLCK, 1)
            else:
                fcntl.flock(fd, fcntl.LOCK_UN)
        os.close(fd)  # Never unlink an active lock inode; OS releases it on a crash.
