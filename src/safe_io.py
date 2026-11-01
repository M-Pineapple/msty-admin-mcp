"""0700 directories and 0600 files, without following a pre-planted symlink."""

from __future__ import annotations

import os
import stat
from pathlib import Path
from typing import Union

_NOFOLLOW = getattr(os, "O_NOFOLLOW", 0)


def secure_mkdir(path: Path) -> Path:
    path.mkdir(mode=0o700, parents=True, exist_ok=True)
    try:
        os.chmod(path, 0o700)
    except OSError:
        pass
    return path


def secure_write(path: Path, data: Union[str, bytes]) -> Path:
    """Create or replace ``path`` as mode 0600. Fails if ``path`` is a symlink."""
    secure_mkdir(path.parent)
    raw = data.encode("utf-8") if isinstance(data, str) else data
    flags = os.O_WRONLY | os.O_CREAT | os.O_TRUNC | _NOFOLLOW
    fd = os.open(str(path), flags, 0o600)
    try:
        os.write(fd, raw)
        os.fchmod(fd, 0o600)
    finally:
        os.close(fd)
    return path


def is_owner_only(path: Path) -> bool:
    mode = path.stat().st_mode
    return stat.S_IMODE(mode) & (stat.S_IRWXG | stat.S_IRWXO) == 0
