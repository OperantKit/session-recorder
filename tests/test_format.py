"""Tests for the OKL v1 wire format (encode / decode round-trip)."""

from __future__ import annotations

import io
from datetime import UTC

import pytest
from experiment_core import (
    ComponentChangeEvent,
    ReinforcerEndEvent,
    ReinforcerStartEvent,
    ResponseEvent,
    SessionState,
    StateChangeEvent,
)

from session_recorder.format import (
    ABSENT,
    CANONICAL_CODEBOOK,
    EVENT_TYPE_PHASE_ENTER,
    EVENT_TYPE_PHASE_EXIT,
    EVENT_TYPE_REINFORCER_END,
    EVENT_TYPE_REINFORCER_START,
    EVENT_TYPE_RESPONSE,
    EVENT_TYPE_STATE_CHANGE,
    HEADER_TERMINATOR,
    MAGIC,
    Field,
    decode_str,
    encode_event,
    encode_phase_enter,
    encode_phase_exit,
    encode_str,
    materialise,
    parse_event_line,
    parse_header,
    write_header,
)

# --------------------------------------------------------------------------- #
# TSV escape
# --------------------------------------------------------------------------- #

@pytest.mark.unit
@pytest.mark.parametrize(
    "raw,encoded",
    [
        ("plain", "plain"),
        ("with space", "with space"),
        ("tab\there", "tab\\there"),
        ("nl\nhere", "nl\\nhere"),
        ("cr\rhere", "cr\\rhere"),
        ("back\\slash", "back\\\\slash"),
        ("-", "\\-"),
        ("--", "--"),
        ("", ""),
    ],
)
def test_encode_decode_roundtrip(raw: str, encoded: str) -> None:
    assert encode_str(raw) == encoded
    assert decode_str(encoded) == raw


# --------------------------------------------------------------------------- #
# Event encode
# --------------------------------------------------------------------------- #

@pytest.mark.unit
def test_encode_response_event_without_operandum_uses_absent_token() -> None:
    line = encode_event(ResponseEvent(id=7, timestamp=1.5))
    assert line == "1.5\tresponse\t7\t-"


@pytest.mark.unit
def test_encode_response_event_with_operandum() -> None:
    line = encode_event(ResponseEvent(id=7, timestamp=1.5, operandum=1))
    assert line == "1.5\tresponse\t7\t1"


@pytest.mark.unit
def test_encode_reinforcer_start_with_operandum() -> None:
    line = encode_event(
        ReinforcerStartEvent(id=2, timestamp=10.0, operandum=1, potency=0.8)
    )
    assert line == "10.0\treinforcer_start\t2\t0.8\t1"


@pytest.mark.unit
def test_encode_reinforcer_start_without_operandum_uses_absent_token() -> None:
    line = encode_event(ReinforcerStartEvent(id=1, timestamp=3.14, potency=1.0))
    assert line == "3.14\treinforcer_start\t1\t1.0\t-"


@pytest.mark.unit
def test_encode_reinforcer_end_round_trip() -> None:
    line = encode_event(ReinforcerEndEvent(id=5, timestamp=20.0, operandum=0))
    assert line == "20.0\treinforcer_end\t5\t0"


@pytest.mark.unit
def test_encode_state_change() -> None:
    line = encode_event(
        StateChangeEvent(
            from_state=SessionState.IDLE,
            to_state=SessionState.RUNNING,
            timestamp=0.0,
        )
    )
    assert line == "0.0\tstate_change\tIDLE\tRUNNING"


@pytest.mark.unit
def test_encode_component_change() -> None:
    event = ComponentChangeEvent(from_component="C1", to_component="C2", timestamp=12.5)
    line = encode_event(event)
    assert line == "12.5\tcomponent_change\tC1\tC2"
    rec = parse_event_line(line, CANONICAL_CODEBOOK)
    assert materialise(rec) == event


@pytest.mark.unit
def test_encode_component_change_with_empty_string_components() -> None:
    event = ComponentChangeEvent(from_component="", to_component="C1", timestamp=0.0)
    line = encode_event(event)
    rec = parse_event_line(line, CANONICAL_CODEBOOK)
    assert materialise(rec) == event


@pytest.mark.unit
def test_encode_event_rejects_unknown() -> None:
    class Bogus:
        pass

    with pytest.raises(TypeError, match="unknown session event"):
        encode_event(Bogus())  # type: ignore[arg-type]


# --------------------------------------------------------------------------- #
# Phase markers
# --------------------------------------------------------------------------- #

@pytest.mark.unit
def test_encode_phase_enter_minimal() -> None:
    line = encode_phase_enter(timestamp=1.5, label="Acquisition")
    # 4 trailing absent markers for name/time/location/cue
    assert line == "1.5\tphase_enter\tAcquisition\t-\t-\t-\t-"


@pytest.mark.unit
def test_encode_phase_enter_with_partial_context() -> None:
    line = encode_phase_enter(
        timestamp=10.0,
        label="Test",
        context={"name": "A", "location": "room_a", "cue": None, "time": "morning"},
    )
    # Order is name, time, location, cue
    assert line == "10.0\tphase_enter\tTest\tA\tmorning\troom_a\t-"


@pytest.mark.unit
def test_encode_phase_exit() -> None:
    assert encode_phase_exit(timestamp=20.0, label="Acquisition") == "20.0\tphase_exit\tAcquisition"


# --------------------------------------------------------------------------- #
# Body line decode
# --------------------------------------------------------------------------- #

@pytest.mark.unit
def test_parse_event_line_response() -> None:
    rec = parse_event_line("1.5\tresponse\t7\t-", CANONICAL_CODEBOOK)
    assert rec.timestamp == 1.5
    assert rec.type == EVENT_TYPE_RESPONSE
    assert rec.args == {"id": 7, "operandum": None}


@pytest.mark.unit
def test_parse_event_line_response_with_operandum() -> None:
    rec = parse_event_line("1.5\tresponse\t7\t1", CANONICAL_CODEBOOK)
    assert rec.args == {"id": 7, "operandum": 1}


@pytest.mark.unit
def test_parse_event_line_reinforcer_start_optional() -> None:
    rec = parse_event_line("3.14\treinforcer_start\t1\t1.0\t-", CANONICAL_CODEBOOK)
    assert rec.args == {"id": 1, "potency": 1.0, "operandum": None}


@pytest.mark.unit
def test_parse_event_line_unknown_type_raises_keyerror() -> None:
    with pytest.raises(KeyError):
        parse_event_line("1.0\tnope\tx", CANONICAL_CODEBOOK)


@pytest.mark.unit
def test_parse_event_line_wrong_column_count() -> None:
    with pytest.raises(ValueError, match="payload cols"):
        # missing the operandum column
        parse_event_line("3.14\treinforcer_start\t1\t1.0", CANONICAL_CODEBOOK)


@pytest.mark.unit
def test_parse_event_line_required_field_absent_raises() -> None:
    with pytest.raises(ValueError, match="required field"):
        # response.id is required; absent token "-" must raise
        parse_event_line("1.0\tresponse\t-\t-", CANONICAL_CODEBOOK)


# --------------------------------------------------------------------------- #
# materialise
# --------------------------------------------------------------------------- #

@pytest.mark.unit
def test_materialise_response_round_trip() -> None:
    event = ResponseEvent(id=1, timestamp=0.5)
    rec = parse_event_line(encode_event(event), CANONICAL_CODEBOOK)
    assert materialise(rec) == event


@pytest.mark.unit
def test_materialise_response_round_trip_preserves_operandum() -> None:
    event = ResponseEvent(id=42, timestamp=2.5, operandum=1)
    rec = parse_event_line(encode_event(event), CANONICAL_CODEBOOK)
    materialised = materialise(rec)
    assert materialised == event
    assert materialised.operandum == 1


@pytest.mark.unit
def test_materialise_state_change_round_trip() -> None:
    event = StateChangeEvent(
        from_state=SessionState.RUNNING,
        to_state=SessionState.FINISHED,
        timestamp=2.0,
    )
    rec = parse_event_line(encode_event(event), CANONICAL_CODEBOOK)
    assert materialise(rec) == event


@pytest.mark.unit
def test_materialise_rejects_phase_markers() -> None:
    rec = parse_event_line(encode_phase_exit(timestamp=1.0, label="X"), CANONICAL_CODEBOOK)
    with pytest.raises(ValueError, match="cannot materialise"):
        materialise(rec)


# --------------------------------------------------------------------------- #
# Header
# --------------------------------------------------------------------------- #

@pytest.mark.unit
def test_write_header_minimal() -> None:
    buf = io.StringIO()
    write_header(buf, session_name="demo", clock_type="ManualClock", session_start=0.0)
    rendered = buf.getvalue()
    assert rendered.startswith(MAGIC + "\n")
    assert rendered.endswith(HEADER_TERMINATOR + "\n")
    assert '# session_name = "demo"' in rendered
    assert "# events:" in rendered
    # codebook contains every canonical type
    for tn in CANONICAL_CODEBOOK:
        assert tn in rendered


@pytest.mark.unit
def test_write_header_with_metadata() -> None:
    buf = io.StringIO()
    write_header(
        buf,
        session_name="demo",
        clock_type="ManualClock",
        session_start=0.0,
        metadata={"dsl": "FR3", "subject_id": "rat-001"},
    )
    rendered = buf.getvalue()
    assert "# meta:" in rendered
    assert '#   dsl = "FR3"' in rendered
    assert '#   subject_id = "rat-001"' in rendered


@pytest.mark.unit
def test_write_header_rejects_bad_metadata_types() -> None:
    with pytest.raises(TypeError, match="unsupported metadata"):
        write_header(
            io.StringIO(),
            session_name="x",
            clock_type="x",
            session_start=0.0,
            metadata={"bad": [1, 2]},  # list not allowed
        )


@pytest.mark.unit
def test_parse_header_round_trip() -> None:
    buf = io.StringIO()
    write_header(
        buf,
        session_name="demo",
        clock_type="ManualClock",
        session_start=0.0,
        metadata={"dsl": "FR3"},
    )
    parsed, consumed = parse_header(buf.getvalue().splitlines())
    assert parsed.session_name == "demo"
    assert parsed.clock_type == "ManualClock"
    assert parsed.session_start == 0.0
    assert parsed.metadata == {"dsl": "FR3"}
    assert EVENT_TYPE_RESPONSE in parsed.codebook
    assert EVENT_TYPE_PHASE_ENTER in parsed.codebook
    # consumed = magic + 3 top-level + 1 meta header + 1 meta line + 1 events header + 6 type rows + terminator
    assert consumed == 1 + 3 + 2 + 1 + len(CANONICAL_CODEBOOK) + 1


@pytest.mark.unit
def test_parse_header_rejects_missing_required_key() -> None:
    body = "\n".join(
        [
            MAGIC,
            '# session_name = "demo"',
            '# clock_type = "ManualClock"',
            HEADER_TERMINATOR,
        ]
    )
    with pytest.raises(ValueError, match="missing required keys"):
        parse_header(body.splitlines())


@pytest.mark.unit
def test_parse_header_rejects_wrong_magic() -> None:
    with pytest.raises(ValueError, match="OKL v1"):
        parse_header(["# OKL v9", HEADER_TERMINATOR])


@pytest.mark.unit
def test_parse_header_supports_unknown_event_type_in_codebook() -> None:
    # A consumer-defined custom type can be declared in the codebook
    body = "\n".join(
        [
            MAGIC,
            '# session_name = "demo"',
            '# clock_type = "X"',
            "# session_start = 0.0",
            "# events:",
            "#   note          : severity:str text:str",
            HEADER_TERMINATOR,
        ]
    )
    parsed, _ = parse_header(body.splitlines())
    assert "note" in parsed.codebook
    note = parsed.codebook["note"]
    assert note == (Field("severity", "str", False), Field("text", "str", False))


# --------------------------------------------------------------------------- #
# Constants present
# --------------------------------------------------------------------------- #

@pytest.mark.unit
def test_event_type_constants() -> None:
    assert EVENT_TYPE_RESPONSE == "response"
    assert EVENT_TYPE_REINFORCER_START == "reinforcer_start"
    assert EVENT_TYPE_REINFORCER_END == "reinforcer_end"
    assert EVENT_TYPE_STATE_CHANGE == "state_change"
    assert EVENT_TYPE_PHASE_ENTER == "phase_enter"
    assert EVENT_TYPE_PHASE_EXIT == "phase_exit"
    assert ABSENT == "-"


# --------------------------------------------------------------------------- #
# Edge cases (filling test gaps from the code review)
# --------------------------------------------------------------------------- #

@pytest.mark.unit
def test_negative_int_id_round_trip() -> None:
    event = ResponseEvent(id=-1, timestamp=0.5)
    rec = parse_event_line(encode_event(event), CANONICAL_CODEBOOK)
    assert materialise(rec) == event


@pytest.mark.unit
def test_extreme_floats_round_trip() -> None:
    big = ResponseEvent(id=1, timestamp=1e308)
    small = ResponseEvent(id=2, timestamp=1e-300)
    for ev in (big, small):
        rec = parse_event_line(encode_event(ev), CANONICAL_CODEBOOK)
        assert materialise(rec) == ev


@pytest.mark.unit
def test_phase_enter_with_all_four_context_fields() -> None:
    line = encode_phase_enter(
        timestamp=0.0,
        label="Test",
        context={"name": "A", "time": "morning", "location": "room_a", "cue": "tone"},
    )
    rec = parse_event_line(line, CANONICAL_CODEBOOK)
    assert rec.args["name"] == "A"
    assert rec.args["time"] == "morning"
    assert rec.args["location"] == "room_a"
    assert rec.args["cue"] == "tone"


@pytest.mark.unit
def test_str_field_with_literal_dash_round_trips_through_body() -> None:
    # The literal single-character "-" must NOT be confused with the
    # absent marker. Use a phase_enter context cue of "-".
    line = encode_phase_enter(timestamp=0.0, label="X", context={"name": "-"})
    rec = parse_event_line(line, CANONICAL_CODEBOOK)
    assert rec.args["name"] == "-"


@pytest.mark.unit
def test_str_field_with_tab_and_newline_round_trip() -> None:
    line = encode_phase_enter(
        timestamp=0.0, label="X", context={"name": "a\tb\nc"}
    )
    rec = parse_event_line(line, CANONICAL_CODEBOOK)
    assert rec.args["name"] == "a\tb\nc"


@pytest.mark.unit
def test_bool_value_in_int_field_raises() -> None:
    # Without the explicit guard, ``bool`` would be silently coerced
    # to 0/1 because ``isinstance(True, int) is True``.
    line_template = encode_event(ResponseEvent(id=1, timestamp=0.0))
    assert "1" in line_template  # sanity
    # Direct test via the encoding helper:
    from session_recorder.format import _encode_value

    field_int = Field("id", "int", optional=False)
    with pytest.raises(TypeError, match="declared 'int' but got bool"):
        _encode_value(True, field_int)


@pytest.mark.unit
def test_bool_value_in_bool_field_round_trips() -> None:
    custom_codebook = {
        "demo": (Field("flag", "bool", optional=False),),
    }
    line = "0.0\tdemo\ttrue"
    rec = parse_event_line(line, custom_codebook)
    assert rec.args == {"flag": True}


@pytest.mark.unit
def test_bom_in_first_line_raises_with_clear_message() -> None:
    body = "﻿" + MAGIC + "\n# session_name = \"x\"\n# clock_type = \"X\"\n# session_start = 0.0\n# events:\n# ---\n"
    with pytest.raises(ValueError, match="UTF-8 BOM"):
        parse_header(body.splitlines())


@pytest.mark.unit
def test_unknown_top_level_key_warns_and_preserves(recwarn) -> None:
    body = "\n".join(
        [
            MAGIC,
            '# session_name = "demo"',
            '# clock_type = "X"',
            "# session_start = 0.0",
            '# bogus_key = "garbage"',
            HEADER_TERMINATOR,
        ]
    )
    parsed, _ = parse_header(body.splitlines())
    assert parsed.metadata.get("bogus_key") == "garbage"
    # Exactly one UserWarning about the unknown key.
    msgs = [str(w.message) for w in recwarn.list if issubclass(w.category, UserWarning)]
    assert any("bogus_key" in m for m in msgs)


@pytest.mark.unit
def test_full_session_meta_header_round_trip() -> None:
    import io
    from datetime import datetime

    buf = io.StringIO()
    write_header(
        buf,
        session_name="demo",
        clock_type="ManualClock",
        session_start=0.0,
        subject_id="rat-001",
        replication_index=2,
        experiment_name="fr_baseline",
        protocol_id="proto-001",
        task_file_hash="abc123",
        wall_clock_start=datetime(2026, 4, 27, 14, 3, 11, tzinfo=UTC),
        notes=["operator note one", "operator note two"],
        metadata={"dsl": "FR3"},
    )
    parsed, _ = parse_header(buf.getvalue().splitlines())
    assert parsed.subject_id == "rat-001"
    assert parsed.replication_index == 2
    assert parsed.experiment_name == "fr_baseline"
    assert parsed.protocol_id == "proto-001"
    assert parsed.task_file_hash == "abc123"
    assert parsed.wall_clock_start == datetime(
        2026, 4, 27, 14, 3, 11, tzinfo=UTC
    )
    assert parsed.notes == ["operator note one", "operator note two"]
    assert parsed.metadata == {"dsl": "FR3"}

    meta = parsed.session_meta()
    assert meta.subject_id == "rat-001"
    assert meta.notes == ["operator note one", "operator note two"]
