"""Wait for a file written by another process/container to become visible and non-empty."""

from __future__ import annotations

import time
from pathlib import Path


def wait_until_file_ready(
    path: Path | str,
    *,
    timeout_sec: float = 120.0,
    poll_sec: float = 0.2,
    min_size: int = 1,
) -> bool:
    """
    Poll until ``path`` exists, is a regular file, and has size >= ``min_size``.

    Cross-container bind mounts can lag briefly; fsync on the writer reduces but
    does not always eliminate the need for a short wait on the reader.
    """
    p = Path(path)
    deadline = time.monotonic() + timeout_sec
    while time.monotonic() < deadline:
        try:
            if p.is_file():
                st = p.stat()
                if st.st_size >= min_size:
                    return True
        except OSError:
            pass
        time.sleep(poll_sec)
    return False
