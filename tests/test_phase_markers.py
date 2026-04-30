"""Tests for phase_enter / phase_exit records and reader integration."""

from __future__ import annotations

from pathlib import Path

import pytest
from experiment_core import ResponseEvent

from session_recorder import (
    EVENT_TYPE_PHASE_ENTER,
    EVENT_TYPE_PHASE_EXIT,
    OklSink,
    PhaseMarker,
    read_log,
)
from session_recorder.format import (
    CANONICAL_CODEBOOK,
    encode_phase_enter,
    encode_phase_exit,
    parse_event_line,
)


@pytest.mark.unit
def test_phase_enter_minimal_round_trip() -> None:
    line = encode_phase_enter(timestamp=1.5, label="Acquisition")
    rec = parse_event_line(line, CANONICAL_CODEBOOK)
    assert rec.type == EVENT_TYPE_PHASE_ENTER
    assert rec.timestamp == 1.5
    assert rec.args["label"] == "Acquisition"
    assert rec.args["name"] is None


@pytest.mark.unit
def test_phase_enter_with_context() -> None:
    line = encode_phase_enter(
        timestamp=10.0,
        label="Test",
        context={"name": "A", "location": "room_a", "cue": None, "time": "morning"},
    )
    rec = parse_event_line(line, CANONICAL_CODEBOOK)
    assert rec.args["name"] == "A"
    assert rec.args["time"] == "morning"
    assert rec.args["location"] == "room_a"
    assert rec.args["cue"] is None


@pytest.mark.unit
def test_phase_exit_round_trip() -> None:
    line = encode_phase_exit(timestamp=20.0, label="Acquisition")
    rec = parse_event_line(line, CANONICAL_CODEBOOK)
    assert rec.type == EVENT_TYPE_PHASE_EXIT
    assert rec.args == {"label": "Acquisition"}


@pytest.mark.unit
def test_reader_round_trip_with_phase_markers(tmp_log: Path) -> None:
    sink = OklSink(tmp_log)
    sink.write_header(session_name="aba", clock_type="ManualClock", session_start=0.0)
    sink.write_phase_enter(timestamp=0.0, label="Train", context={"name": "A"})
    sink.emit(ResponseEvent(id=1, timestamp=1.0))
    sink.write_phase_exit(timestamp=10.0, label="Train")
    sink.write_phase_enter(timestamp=10.0, label="Extinct", context={"name": "B"})
    sink.emit(ResponseEvent(id=2, timestamp=11.0))
    sink.write_phase_exit(timestamp=20.0, label="Extinct")
    sink.write_phase_enter(timestamp=20.0, label="Test", context={"name": "A"})
    sink.emit(ResponseEvent(id=3, timestamp=21.0))

    log = read_log(tmp_log)
    assert log.meta is not None
    assert log.meta.session_name == "aba"
    assert len(log.events) == 3
    assert all(isinstance(e, ResponseEvent) for e in log.events)
    assert len(log.phase_markers) == 5
    enters = [m for m in log.phase_markers if m.kind == "enter"]
    assert [m.label for m in enters] == ["Train", "Extinct", "Test"]
    assert enters[0].context == {"name": "A"}
    assert enters[2].context == {"name": "A"}


@pytest.mark.unit
def test_reader_log_without_phase_markers(tmp_log: Path) -> None:
    sink = OklSink(tmp_log)
    sink.write_header(session_name="legacy", clock_type="ManualClock", session_start=0.0)
    sink.emit(ResponseEvent(id=1, timestamp=1.0))
    log = read_log(tmp_log)
    assert log.phase_markers == []
    assert len(log.events) == 1


@pytest.mark.unit
def test_phase_marker_dataclass() -> None:
    m = PhaseMarker(kind="enter", timestamp=0.0, label="X", context={"name": "A"})
    assert m.kind == "enter"
    assert m.context == {"name": "A"}
