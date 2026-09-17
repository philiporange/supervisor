"""
Incremental reading of the supervisor's own log file.

The dashboard polls this file every few seconds. Instead of rereading the
whole file each time, read_since returns only the bytes appended after a
byte offset the client sends back, and falls back to a tail read of the last
N lines when there is no offset or the file has shrunk (rotation). The tail
read seeks to a bounded window near the end of the file rather than
scanning from the start, so cost is independent of file size.
"""

from pathlib import Path

TAIL_WINDOW_BYTES = 512 * 1024


def tail_lines(path: Path, n: int) -> tuple[list[str], int]:
    """Return the last n lines (with line endings) and the file size in bytes."""
    try:
        with open(path, "rb") as f:
            f.seek(0, 2)
            size = f.tell()
            start = max(0, size - TAIL_WINDOW_BYTES)
            f.seek(start)
            data = f.read()
    except FileNotFoundError:
        return [], 0
    text = data.decode("utf-8", errors="replace")
    lines = text.splitlines(keepends=True)
    if start > 0 and lines:
        lines = lines[1:]
    return lines[-n:], size


def read_since(path: Path, offset: int | None, n: int) -> dict:
    """Lines appended after offset, or a tail read when offset is missing or stale.

    Returns {"lines", "offset", "reset"}. reset is True when the client must
    replace its view rather than prepend, because the file was reread in full.
    """
    if offset is None:
        lines, size = tail_lines(path, n)
        return {"lines": lines, "offset": size, "reset": True}
    try:
        with open(path, "rb") as f:
            f.seek(0, 2)
            size = f.tell()
            if size < offset:
                lines, size = tail_lines(path, n)
                return {"lines": lines, "offset": size, "reset": True}
            f.seek(offset)
            data = f.read()
    except FileNotFoundError:
        return {"lines": [], "offset": 0, "reset": True}
    lines = data.decode("utf-8", errors="replace").splitlines(keepends=True)
    if lines and not lines[-1].endswith("\n"):
        # Hold back a partial trailing line until it is complete.
        size -= len(lines[-1].encode("utf-8"))
        lines = lines[:-1]
    return {"lines": lines[-n:], "offset": size, "reset": False}
