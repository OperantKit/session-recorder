"""Tests for the MED-PC -> OKL v1 importer.

Fixtures are real session files from three public datasets (see
``tests/fixtures/medpc/SOURCES.md``). Expected counts were taken by
counting the event codes in each file independently of the importer.
"""

from __future__ import annotations

from collections import Counter
from pathlib import Path

import pytest
from experiment_core import ReinforcerStartEvent, ResponseEvent

from session_recorder import read_log
from session_recorder.medpc import guess_protocol, medpc_to_okl, read_medpc, split_code

FIXTURES = Path(__file__).parent / "fixtures" / "medpc"
TRAINING = FIXTURES / "bernardy_training_vi30s_JL4.txt"
VDRL = FIXTURES / "bernardy_vdrl10s_JL1.txt"
INH = FIXTURES / "sosa_inh_R6_s13.txt"
PRPR_EMPTY = FIXTURES / "mccutcheon_prpr_PPR2.7_FR1_day5.txt"
PRPR_PR = FIXTURES / "mccutcheon_prpr_cPPR1.9_PR3_day2.4.txt"


def _types(path: Path) -> Counter[str]:
    lines = path.read_text(encoding="utf-8").splitlines()
    body = lines[lines.index("# ---") + 1 :]
    return Counter(line.split("\t")[1] for line in body)


def _body_lines(path: Path) -> int:
    lines = path.read_text(encoding="utf-8").splitlines()
    return len(lines) - lines.index("# ---") - 1


# --------------------------------------------------------------------------- #
# parsing
# --------------------------------------------------------------------------- #


@pytest.mark.unit
def test_split_code_keeps_codes_that_float_rounding_would_merge() -> None:
    assert split_code("2436.110") == (2436, "110")
    assert split_code("2432.100") == (2432, "100")
    assert split_code("0.999") == (0, "999")
    assert split_code("12") == (12, "")
    with pytest.raises(ValueError):
        split_code("-987.987")


@pytest.mark.unit
def test_annotated_header_with_mixed_line_endings() -> None:
    (s,) = read_medpc(TRAINING)
    assert s.format == "annotated"
    assert s.header["file"].endswith("Subject JL4")
    assert s.header["subject"] == "JL4"
    assert s.header["msn"] == "Training"
    assert s.header["start_time"] == "9:51:02"
    assert s.arrays["A"][1] == "270000.000"
    assert len(s.arrays["C"]) == 398  # DISKCOLUMNS = 1
    assert s.scalars["D"] == "0.000"


@pytest.mark.unit
def test_annotated_five_columns_and_empty_subject() -> None:
    (s,) = read_medpc(INH)
    assert s.header["subject"] == ""
    assert s.header["msn"] == "A inhibicion"
    assert len(s.arrays["J"]) == 631  # DISKCOLUMNS = 5
    assert s.arrays["J"][:3] == ("0.999", "2082.987", "2432.100")


@pytest.mark.unit
def test_annotated_multiple_sessions_and_comment(tmp_path: Path) -> None:
    body = (
        "File: C:\\MED-PC IV\\DATA\\demo\r\n\n\r\r\n"
        "Start Date: 5/8/21\r\nEnd Date: 5/8/21\r\nSubject: R1\r\nExperiment: x\r\n"
        "Group: \r\nBox: 1\r\nStart Time:  9:00:00\r\nEnd Time:  9:10:00\r\nMSN: demo\r\n"
        "B:       3.000\r\nC:\r\n     0:        1.200        5.200\r\n"
        "\r\n\r\n"
        "Start Date: 5/9/21\r\nEnd Date: 5/9/21\r\nSubject: R1\r\nExperiment: x\r\n"
        "Group: \r\nBox: 1\r\nStart Time: 10:00:00\r\nEnd Time: 10:10:00\r\nMSN: demo\r\n"
        "B:       0.000\r\nC:\r\n"
        "\\ a trailing comment\r\n"
    )
    p = tmp_path / "multi.txt"
    p.write_bytes(body.encode("ascii"))
    first, second = read_medpc(p)
    assert first.header["start_date"] == "5/8/21"
    assert first.arrays["C"] == ("1.200", "5.200")
    assert second.header["start_time"] == "10:00:00"
    assert second.header["file"] == "C:\\MED-PC IV\\DATA\\demo"
    assert second.arrays["C"] == ()


@pytest.mark.unit
def test_stripped_varid_layout() -> None:
    (s,) = read_medpc(PRPR_PR)
    assert s.format == "stripped-varid"
    assert s.header["subject"] == "cPPR1.9"
    assert s.header["experiment"] == "PR3_day2.4"
    assert s.header["start_time"] == "9:07:40"
    assert s.arrays["B"] == ("-1", "201.719000000000138")
    assert len(s.arrays["Z"]) == 184
    assert s.scalars["T"] == "2001.82100000000174"
    assert s.declared == {"scalars": 23, "arrays": 3}


@pytest.mark.unit
def test_stripped_without_marker_is_rejected(tmp_path: Path) -> None:
    values = ["1"] * 16 + ["24", "2", "7"] + ["1"] * 26 + ["0"] * 26
    p = tmp_path / "format2.txt"
    p.write_text("\r\n".join(values) + "\r\n")
    with pytest.raises(ValueError, match="FORMAT 2 / 3"):
        read_medpc(p)


@pytest.mark.unit
def test_condensed_header_is_rejected(tmp_path: Path) -> None:
    p = tmp_path / "condensed.txt"
    p.write_text("BOX: 1  SUBJECT: R1\nA: 0\n")
    with pytest.raises(ValueError, match="CONDENSED"):
        read_medpc(p)


@pytest.mark.unit
def test_array_row_index_gap_is_an_error(tmp_path: Path) -> None:
    p = tmp_path / "gap.txt"
    p.write_text("Start Date: 1/1/20\nSubject: x\nMSN: m\nC:\n     0:  1.0  2.0\n     5:  3.0\n")
    with pytest.raises(ValueError, match="row starts at 5"):
        read_medpc(p)


# --------------------------------------------------------------------------- #
# conversion — counts must match the source file
# --------------------------------------------------------------------------- #


@pytest.mark.integration
def test_bernardy_training_to_okl(tmp_path: Path) -> None:
    (s,) = read_medpc(TRAINING)
    assert guess_protocol(s) == "bernardy-training"
    out = tmp_path / "training.txt"
    conv = medpc_to_okl(s, out)
    # C: 1 x .111, 336 x .200, 60 x .400, 1 x .999 -> 398 events
    assert conv.source_events == 398
    assert conv.primary == 398 and conv.synthesised == 0 and not conv.unmapped
    assert _types(out) == Counter(state_change=2, response=336, reinforcer_start=60)
    assert _body_lines(out) == 398
    log = read_log(out)
    # B(1) and B(2) are the program's own response and reinforcer counters
    assert s.arrays["B"][1] == "336.000" and s.arrays["B"][2] == "60.000"
    assert log.meta.metadata["schedule.spec_dsl"] == "VI 30s"
    assert log.meta.subject_id == "JL4"
    assert log.events[1] == ResponseEvent(id=1, timestamp=27.42, operandum=0)


@pytest.mark.integration
def test_bernardy_vdrl_to_okl(tmp_path: Path) -> None:
    (s,) = read_medpc(VDRL)
    out = tmp_path / "vdrl.txt"
    conv = medpc_to_okl(s, out)
    # D: .123 1, .200 41, .210 2, .300 24, .310 24, .678 25, .789 1 -> 118
    assert conv.source_events == 118
    assert conv.unmapped == Counter({"678": 25})
    assert conv.primary == 93 and conv.synthesised == 0
    assert _types(out) == Counter(
        state_change=2, response=43, reinforcer_start=24, reinforcer_end=24
    )
    meta = read_log(out).meta.metadata
    assert meta["medpc.unmapped_codes"] == ".678:25"
    assert meta["medpc.source_events"] == 118
    assert "schedule.spec_dsl" not in meta  # VDRL has no DSL form


@pytest.mark.integration
def test_sosa_inh_to_okl(tmp_path: Path) -> None:
    (s,) = read_medpc(INH)
    out = tmp_path / "inh.txt"
    conv = medpc_to_okl(s, out)
    assert conv.source_events == 631
    assert conv.primary == 631 and not conv.unmapped
    # synthesised: phase_enter PCI, 16 A+ offsets, component -> DRL, FINISHED
    assert conv.synthesised == 19
    assert _types(out) == Counter(
        response=121,  # .307
        reinforcer_start=86,  # .2 (32) + .218 (54)
        head_entry=170,
        head_exit=170,
        component_change=32 + 16 + 16 + 16 + 16 + 1,
        phase_enter=2,
        phase_exit=2,
        state_change=2,
    )
    assert _body_lines(out) == 650
    log = read_log(out, on_unknown="error")
    assert [(m.kind, m.label) for m in log.phase_markers] == [
        ("enter", "PCI"),
        ("exit", "PCI"),
        ("enter", "DRL"),
        ("exit", "DRL"),
    ]
    # head entries stay out of SessionEvent-based analysis
    assert sum(isinstance(e, ResponseEvent) for e in log.events) == 121
    assert log.meta.subject_id == "R6"
    pavlovian = [e for e in log.events if isinstance(e, ReinforcerStartEvent)][0]
    assert pavlovian.operandum is None


@pytest.mark.integration
def test_mccutcheon_pr_to_okl(tmp_path: Path) -> None:
    (s,) = read_medpc(PRPR_PR)
    assert guess_protocol(s) is None
    out = tmp_path / "pr.txt"
    conv = medpc_to_okl(s, out, protocol="mccutcheon-prpr")
    assert conv.source_events == 2  # B and D without the leading -1
    assert conv.primary == 2 and conv.synthesised == 2
    log = read_log(out)
    assert log.events[1] == ResponseEvent(id=1, timestamp=201.719000000000138, operandum=0)
    assert log.events[-1].timestamp == pytest.approx(2001.821)
    assert log.meta.metadata["medpc.pr.step"] == "3"
    assert log.meta.subject_id == "cPPR1.9"


@pytest.mark.integration
def test_mccutcheon_session_without_events(tmp_path: Path) -> None:
    (s,) = read_medpc(PRPR_EMPTY)
    out = tmp_path / "fr1.txt"
    conv = medpc_to_okl(s, out, protocol="mccutcheon-prpr")
    assert conv.source_events == 0
    assert _types(out) == Counter(state_change=2)
    assert read_log(out).meta.metadata["schedule.spec_dsl"] == "FR 1"


@pytest.mark.unit
def test_stripped_needs_explicit_protocol(tmp_path: Path) -> None:
    (s,) = read_medpc(PRPR_PR)
    with pytest.raises(ValueError, match="cannot infer a protocol"):
        medpc_to_okl(s, tmp_path / "x.txt")
    with pytest.raises(ValueError, match="unknown protocol"):
        medpc_to_okl(s, tmp_path / "x.txt", protocol="nope")


@pytest.mark.integration
def test_mccutcheon_magazine_training_has_no_time_stamps(tmp_path: Path) -> None:
    values = (
        ["11", "1", "19", "11", "1", "19", "cPPR1.16", "mag_train_1", "0", "1"]
        + ["12", "06", "00", "12", "40", "00", "26", "0", ".3"]
        + ["1"] * 26
        + ["50", "50"]
        + ["0"] * 17
        + ["2040.5"]
        + ["0"] * 6
    )
    p = tmp_path / "mag.txt"
    p.write_text("\r\n".join(values) + "\r\n")
    (s,) = read_medpc(p)
    conv = medpc_to_okl(s, tmp_path / "mag_okl.txt", protocol="mccutcheon-prpr")
    assert conv.source_events == 0
    assert _types(tmp_path / "mag_okl.txt") == Counter(state_change=2)
    meta = read_log(tmp_path / "mag_okl.txt").meta.metadata
    assert meta["medpc.var.A"] == "50"


@pytest.mark.unit
def test_inh_box_variant_uses_same_protocol() -> None:
    (s,) = read_medpc(INH)
    variant = type(s)(
        s.format, {**s.header, "msn": "A inhibicion c7"}, s.scalars, s.arrays, s.source
    )
    assert guess_protocol(variant) == "sosa-inh"
