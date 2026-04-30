"""Tests for :class:`session_recorder.OklSink`."""

from __future__ import annotations

from pathlib import Path

import pytest
from experiment_core import (
    EventSink,
    ReinforcerEndEvent,
    ReinforcerStartEvent,
    ResponseEvent,
    SessionState,
    StateChangeEvent,
)

from session_recorder import OklSink
from session_recorder.format import HEADER_TERMINATOR, MAGIC


def body_lines(path: Path) -> list[str]:
    """Return body lines (everything after the header terminator)."""
    text = path.read_text(encoding="utf-8")
    _, _, body = text.partition(HEADER_TERMINATOR + "\n")
    return [line for line in body.splitlines() if line]


@pytest.mark.unit
def test_oklsink_satisfies_event_sink_protocol(tmp_log: Path) -> None:
    sink = OklSink(tmp_log)
    assert isinstance(sink, EventSink)


@pytest.mark.unit
def test_emit_appends_one_line_per_event(tmp_log: Path) -> None:
    sink = OklSink(tmp_log)
    sink.write_header(session_name="demo", clock_type="ManualClock", session_start=0.0)
    sink.emit(ResponseEvent(id=1, timestamp=0.5))
    sink.emit(ResponseEvent(id=2, timestamp=1.5))
    lines = body_lines(tmp_log)
    assert len(lines) == 2
    assert all(line.split("\t")[1] == "response" for line in lines)


@pytest.mark.unit
def test_emit_serialises_each_event_type(tmp_log: Path) -> None:
    sink = OklSink(tmp_log)
    sink.write_header(session_name="demo", clock_type="ManualClock", session_start=0.0)
    sink.emit(ResponseEvent(id=1, timestamp=0.0))
    sink.emit(ReinforcerStartEvent(id=1, timestamp=1.0, operandum=0, potency=1.0))
    sink.emit(ReinforcerEndEvent(id=1, timestamp=1.5, operandum=0))
    sink.emit(
        StateChangeEvent(
            from_state=SessionState.RUNNING,
            to_state=SessionState.FINISHED,
            timestamp=2.0,
        )
    )
    types = [line.split("\t")[1] for line in body_lines(tmp_log)]
    assert types == ["response", "reinforcer_start", "reinforcer_end", "state_change"]


@pytest.mark.unit
def test_write_header_emits_magic_and_terminator(tmp_log: Path) -> None:
    sink = OklSink(tmp_log)
    sink.write_header(
        session_name="demo",
        clock_type="ManualClock",
        session_start=0.0,
        metadata={"dsl": "FR3"},
    )
    text = tmp_log.read_text(encoding="utf-8")
    assert text.startswith(MAGIC + "\n")
    assert HEADER_TERMINATOR + "\n" in text
    assert '# session_name = "demo"' in text


@pytest.mark.unit
def test_emit_before_header_raises(tmp_log: Path) -> None:
    sink = OklSink(tmp_log)
    with pytest.raises(RuntimeError, match="write_header"):
        sink.emit(ResponseEvent(id=1, timestamp=0.0))


@pytest.mark.unit
def test_double_write_header_raises(tmp_log: Path) -> None:
    sink = OklSink(tmp_log)
    sink.write_header(session_name="demo", clock_type="X", session_start=0.0)
    with pytest.raises(RuntimeError, match="already written"):
        sink.write_header(session_name="demo", clock_type="X", session_start=0.0)


@pytest.mark.unit
def test_write_header_refuses_non_empty_file(tmp_log: Path) -> None:
    tmp_log.write_text("garbage\n")
    sink = OklSink(tmp_log)
    with pytest.raises(RuntimeError, match="byte 0"):
        sink.write_header(session_name="demo", clock_type="X", session_start=0.0)


@pytest.mark.unit
def test_lines_property_mirrors_disk(tmp_log: Path) -> None:
    sink = OklSink(tmp_log)
    sink.write_header(session_name="demo", clock_type="X", session_start=0.0)
    sink.emit(ResponseEvent(id=1, timestamp=0.1))
    on_disk = tmp_log.read_text(encoding="utf-8").splitlines()
    assert sink.lines == on_disk


@pytest.mark.unit
def test_lines_returns_a_copy(tmp_log: Path) -> None:
    sink = OklSink(tmp_log)
    sink.write_header(session_name="demo", clock_type="X", session_start=0.0)
    sink.emit(ResponseEvent(id=1, timestamp=0.0))
    snapshot = sink.lines
    snapshot.append("tampered")
    assert "tampered" not in sink.lines


@pytest.mark.unit
def test_creates_parent_directory(tmp_path: Path) -> None:
    nested = tmp_path / "nested" / "dir" / "session.txt"
    OklSink(nested)
    assert nested.parent.is_dir()


@pytest.mark.unit
def test_bare_filename_does_not_raise(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.chdir(tmp_path)
    OklSink("bare.txt")  # no directory component


@pytest.mark.unit
def test_phase_helpers_append_lines(tmp_log: Path) -> None:
    sink = OklSink(tmp_log)
    sink.write_header(session_name="aba", clock_type="X", session_start=0.0)
    sink.write_phase_enter(timestamp=0.0, label="Train", context={"name": "A"})
    sink.emit(ResponseEvent(id=1, timestamp=1.0))
    sink.write_phase_exit(timestamp=10.0, label="Train")
    types = [line.split("\t")[1] for line in body_lines(tmp_log)]
    assert types == ["phase_enter", "response", "phase_exit"]
