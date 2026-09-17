"""Tests for incremental and tail reads of the supervisor log."""

from supervisor import logtail


def test_tail_and_incremental(tmp_path):
    log = tmp_path / "s.log"
    log.write_text("a\nb\nc\n")
    first = logtail.read_since(log, None, 2)
    assert first["lines"] == ["b\n", "c\n"] and first["reset"]
    same = logtail.read_since(log, first["offset"], 2)
    assert same["lines"] == [] and not same["reset"]
    log.write_text("a\nb\nc\nd\npart")
    more = logtail.read_since(log, first["offset"], 2)
    assert more["lines"] == ["d\n"] and more["offset"] == len("a\nb\nc\nd\n")


def test_rotation_resets(tmp_path):
    log = tmp_path / "s.log"
    log.write_text("x" * 100 + "\n")
    off = logtail.read_since(log, None, 5)["offset"]
    log.write_text("new\n")
    res = logtail.read_since(log, off, 5)
    assert res["reset"] and res["lines"] == ["new\n"]


def test_missing_file(tmp_path):
    assert logtail.read_since(tmp_path / "none.log", None, 5) == {"lines": [], "offset": 0, "reset": True}
