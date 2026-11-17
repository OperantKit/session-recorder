"""session-recorder owns the record types and the EventSink Protocol,
and writes stimulus presentations without naming a theory's role."""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

import session_recorder
from session_recorder import (
    EVENT_TYPE_STIMULUS_OFF,
    EVENT_TYPE_STIMULUS_ON,
    EventSink,
    OklSink,
    ResponseEvent,
    read_log,
)


def test_import_does_not_load_a_session_engine() -> None:
    code = (
        "import sys, session_recorder\n"
        "bad = sorted(m for m in sys.modules "
        "if m.split('.')[0] in {'experiment_core', 'contingency', 'contingency_dsl'})\n"
        "print(','.join(bad))\n"
    )
    out = subprocess.run(
        [sys.executable, "-c", code], capture_output=True, text=True, check=True
    )
    assert out.stdout.strip() == ""


def test_record_types_are_defined_here() -> None:
    assert ResponseEvent.__module__ == "session_recorder.events"
    assert EventSink.__module__ == "session_recorder.protocol"
    assert session_recorder.SessionMeta.__module__ == "session_recorder.events"


def test_okl_sink_satisfies_event_sink(tmp_path: Path) -> None:
    assert isinstance(OklSink(tmp_path / "s.txt"), EventSink)


def test_stimulus_round_trip(tmp_path: Path) -> None:
    path = tmp_path / "delay.txt"
    sink = OklSink(path)
    sink.write_header(session_name="delay", clock_type="ManualClock", session_start=0.0)
    sink.write_stimulus_on(timestamp=10.0, stimulus="tone")
    sink.write_stimulus_on(timestamp=19.5, stimulus="food")
    sink.emit(ResponseEvent(id=0, timestamp=19.7))
    sink.write_stimulus_off(timestamp=20.0, stimulus="tone")
    sink.write_stimulus_off(timestamp=20.0, stimulus="food")

    assert sink.lines[-1] == "20.0\tstimulus_off\tfood"
    log = read_log(path, on_unknown="error")
    assert [type(e).__name__ for e in log.events] == ["ResponseEvent"]
    stim = [(r.timestamp, r.type, r.args["stimulus"]) for r in log.raw_records
            if r.type in (EVENT_TYPE_STIMULUS_ON, EVENT_TYPE_STIMULUS_OFF)]
    assert stim == [
        (10.0, "stimulus_on", "tone"),
        (19.5, "stimulus_on", "food"),
        (20.0, "stimulus_off", "tone"),
        (20.0, "stimulus_off", "food"),
    ]


def test_stimulus_before_header_is_refused(tmp_path: Path) -> None:
    import pytest

    sink = OklSink(tmp_path / "s.txt")
    with pytest.raises(RuntimeError):
        sink.write_stimulus_on(timestamp=0.0, stimulus="tone")


def test_foreign_event_class_names_the_upgrade() -> None:
    import pytest

    from session_recorder import encode_event

    Old = type("ResponseEvent", (), {"__module__": "experiment_core.events"})
    with pytest.raises(TypeError, match="experiment-core >= 0.2"):
        encode_event(Old())
