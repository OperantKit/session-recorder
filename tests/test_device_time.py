"""The optional ``device_time`` column of ``response`` lines."""

from __future__ import annotations

from pathlib import Path

import pytest

from session_recorder import OklSink, ResponseEvent, read_log
from session_recorder.format import (
    CANONICAL_CODEBOOK,
    EVENT_TYPE_RESPONSE,
    Field,
    encode_event,
    materialise,
    parse_event_line,
)


@pytest.mark.unit
def test_response_codebook_declares_optional_device_time_last() -> None:
    assert CANONICAL_CODEBOOK[EVENT_TYPE_RESPONSE][-1] == Field("device_time", "float", True)


@pytest.mark.unit
def test_encode_response_writes_device_time() -> None:
    line = encode_event(ResponseEvent(id=3, timestamp=2.0, operandum=0, device_time=324421.687))
    assert line == "2.0\tresponse\t3\t0\t324421.687"


@pytest.mark.unit
def test_encode_response_without_device_time_uses_absent_token() -> None:
    line = encode_event(ResponseEvent(id=3, timestamp=2.0))
    assert line == "2.0\tresponse\t3\t-\t-"


@pytest.mark.unit
def test_device_time_round_trips_through_materialise() -> None:
    event = ResponseEvent(id=3, timestamp=2.0, operandum=1, device_time=0.125)
    rec = parse_event_line(encode_event(event), CANONICAL_CODEBOOK)
    assert rec.args["device_time"] == 0.125
    assert materialise(rec) == event


@pytest.mark.unit
def test_read_log_keeps_device_time(tmp_path: Path) -> None:
    path = tmp_path / "s.txt"
    sink = OklSink(path)
    sink.write_header(session_name="demo", clock_type="ManualClock", session_start=0.0)
    sink.emit(ResponseEvent(id=1, timestamp=0.5, device_time=10.25))
    sink.emit(ResponseEvent(id=2, timestamp=1.0))

    events = read_log(path).events
    assert [e.device_time for e in events] == [10.25, None]


@pytest.mark.unit
def test_read_log_reads_a_log_written_before_the_column(tmp_path: Path) -> None:
    """A header without ``device_time`` still reads; the value comes back as None."""
    path = tmp_path / "old.txt"
    sink = OklSink(path)
    sink.write_header(session_name="demo", clock_type="ManualClock", session_start=0.0)
    text = path.read_text(encoding="utf-8")
    old_decl = "response          : id:int operandum:int?"
    assert old_decl in text
    # Drop the column from the declaration, as a writer without it produced.
    path.write_text(
        text.replace(f"{old_decl} device_time:float?", old_decl) + "0.5\tresponse\t1\t0\n",
        encoding="utf-8",
    )
    assert "device_time" not in path.read_text(encoding="utf-8")
    (event,) = read_log(path).events
    assert event == ResponseEvent(id=1, timestamp=0.5, operandum=0)
    assert event.device_time is None
