"""Durable file writes for hand-off to Celery / other processes (flush + fsync + atomic replace)."""

from __future__ import annotations

import os
from pathlib import Path


def write_bytes_atomically_and_sync(dest: Path, data: bytes) -> None:
    """
    Write ``data`` to ``dest`` via a staging file + ``os.replace``, then fsync.

    Reduces races where another process sees a missing or truncated file.
    """
    dest = Path(dest).resolve()
    dest.parent.mkdir(parents=True, exist_ok=True)
    staging = dest.with_name(dest.name + ".~tmp")
    try:
        with open(staging, "wb") as f:
            f.write(data)
            f.flush()
            os.fsync(f.fileno())
        os.replace(staging, dest)
        with open(dest, "rb") as f:
            os.fsync(f.fileno())
    except Exception:
        try:
            if staging.exists():
                staging.unlink()
        except OSError:
            pass
        raise

    try:
        if os.name != "nt":
            dir_fd = os.open(str(dest.parent), os.O_RDONLY)
            try:
                os.fsync(dir_fd)
            finally:
                os.close(dir_fd)
    except OSError:
        pass
