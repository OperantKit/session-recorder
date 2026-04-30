"""Tests for the OKL v1 reader."""

from __future__ import annotations

from pathlib import Path

import pytest
from experiment_core import ResponseEvent

from session_recorder import OklSink, SessionMeta, iter_records, read_log
from session_recorder.format import HEADER_TERMINATOR, MAGIC


@pytest.mark.unit
def test_read_log_round_trip(tmp_log: Path) -> None:
    sink = OklSink(tmp_log)
    sink.write_header(
        session_name="demo",
        clock_type="ManualClock",
        session_start=0.0,
        metadata={"dsl": "FR1"},
    )
    sink.emit(ResponseEvent(id=1, timestamp=0.5))
    sink.emit(ResponseEvent(id=2, timestamp=1.0))

    log = read_log(tmp_log)
    assert log.meta == SessionMeta(
        timestamp=0.0,
        clock_type="ManualClock",
        session_name="demo",
        metadata={"dsl": "FR1"},
    )
    assert log.events == [
        ResponseEvent(id=1, timestamp=0.5),
        ResponseEvent(id=2, timestamp=1.0),
    ]
    assert len(log.raw_records) == 2


@pytest.mark.unit
def test_meta_timestamp_is_session_start(tmp_log: Path) -> None:
    sink = OklSink(tmp_log)
    sink.write_header(session_name="demo", clock_type="X", session_start=42.0)
    log = read_log(tmp_log)
    assert log.meta.timestamp == 42.0


@pytest.mark.unit
def test_iter_records_skips_blank_body_lines(tmp_log: Path) -> None:
    sink = OklSink(tmp_log)
    sink.write_header(session_name="x", clock_type="x", session_start=0.0)
    sink.emit(ResponseEvent(id=1, timestamp=0.0))
    sink.emit(ResponseEvent(id=2, timestamp=0.5))
    # inject a blank line
    with tmp_log.open("a", encoding="utf-8") as f:
        f.write("\n")
    sink._lines.append("")  # keep mirror consistent for any future check

    records = list(iter_records(tmp_log))
    assert len(records) == 2


@pytest.mark.unit
def test_reader_accepts_crlf(tmp_log: Path) -> None:
    sink = OklSink(tmp_log)
    sink.write_header(session_name="x", clock_type="x", session_start=0.0)
    sink.emit(ResponseEvent(id=1, timestamp=0.0))
    # Rewrite the file with CRLF line endings
    text = tmp_log.read_text(encoding="utf-8")
    tmp_log.write_text(text.replace("\n", "\r\n"), encoding="utf-8")

    log = read_log(tmp_log)
    assert log.events == [ResponseEvent(id=1, timestamp=0.0)]


@pytest.mark.unit
def test_reader_warns_on_unknown_type_default(tmp_log: Path) -> None:
    # Hand-craft a file that contains an event type not in the codebook
    body = "\n".join(
        [
            MAGIC,
            '# session_name = "demo"',
            '# clock_type = "X"',
            "# session_start = 0.0",
            "# events:",
            "#   response          : id:int",
            HEADER_TERMINATOR,
            "0.0\tresponse\t1",
            "0.5\tnope\tx",  # type "nope" not in codebook
            "1.0\tresponse\t2",
            "",
        ]
    )
    tmp_log.write_text(body, encoding="utf-8")
    with pytest.warns(UserWarning, match="nope"):
        log = read_log(tmp_log)
    assert len(log.events) == 2
    assert log.unknown_types == frozenset({"nope"})


@pytest.mark.unit
def test_reader_errors_on_unknown_type_when_strict(tmp_log: Path) -> None:
    body = "\n".join(
        [
            MAGIC,
            '# session_name = "demo"',
            '# clock_type = "X"',
            "# session_start = 0.0",
            "# events:",
            "#   response          : id:int",
            HEADER_TERMINATOR,
            "0.0\tnope\tx",
            "",
        ]
    )
    tmp_log.write_text(body, encoding="utf-8")
    with pytest.raises(KeyError, match="nope"):
        read_log(tmp_log, on_unknown="error")


@pytest.mark.unit
def test_reader_silent_skip(tmp_log: Path) -> None:
    body = "\n".join(
        [
            MAGIC,
            '# session_name = "demo"',
            '# clock_type = "X"',
            "# session_start = 0.0",
            "# events:",
            "#   response          : id:int",
            HEADER_TERMINATOR,
            "0.0\tnope\tx",
            "0.5\tresponse\t1",
            "",
        ]
    )
    tmp_log.write_text(body, encoding="utf-8")
    log = read_log(tmp_log, on_unknown="skip")
    assert len(log.events) == 1
    assert log.unknown_types == frozenset({"nope"})


@pytest.mark.unit
def test_iter_records_yields_parsed_records(tmp_log: Path) -> None:
    sink = OklSink(tmp_log)
    sink.write_header(session_name="x", clock_type="x", session_start=0.0)
    sink.emit(ResponseEvent(id=1, timestamp=0.5))
    records = list(iter_records(tmp_log))
    assert len(records) == 1
    assert records[0].type == "response"
    assert records[0].args == {"id": 1, "operandum": None}
    assert records[0].timestamp == 0.5


@pytest.mark.unit
def test_torn_write_last_line_is_discarded(tmp_log: Path) -> None:
    """Per OKL v1 spec, a torn final line (no trailing LF) is discarded
    *before* parsing — without raising — and earlier records are
    preserved intact.
    """
    sink = OklSink(tmp_log)
    sink.write_header(session_name="x", clock_type="x", session_start=0.0)
    sink.emit(ResponseEvent(id=1, timestamp=0.0))
    sink.emit(ResponseEvent(id=2, timestamp=0.5))
    # Append a partial line (no LF) — simulate crash mid-write.
    with tmp_log.open("a", encoding="utf-8") as f:
        f.write("0.6\trespo")
    # Strict mode is fine because the torn line is discarded before parsing.
    log = read_log(tmp_log, on_unknown="error")
    ids = [r.args["id"] for r in log.raw_records]
    assert ids == [1, 2]


@pytest.mark.unit
def test_invalid_on_unknown_value_raises() -> None:
    with pytest.raises(ValueError, match="on_unknown"):
        list(iter_records("/nonexistent", on_unknown="bogus"))  # type: ignore[arg-type]
