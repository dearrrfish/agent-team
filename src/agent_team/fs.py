from __future__ import annotations

import os
import tempfile
from pathlib import Path


def atomic_write(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temporary_name = tempfile.mkstemp(prefix=f".{path.name}.", dir=path.parent)
    temporary = Path(temporary_name)
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8", newline="\n") as handle:
            handle.write(content)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, path)
    finally:
        if temporary.exists():
            temporary.unlink()


def non_directory_parent(root: Path, destination: Path) -> Path | None:
    """Return the first existing non-directory on destination's contained path."""
    current = root
    if current.exists() and not current.is_dir():
        return current
    for part in destination.relative_to(root).parts[:-1]:
        current /= part
        if current.exists() and not current.is_dir():
            return current
    return None
