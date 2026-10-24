"""Compare the examples in ``docs/*/format.md`` with what ``OklSink`` writes.

The canonical codebook block and the full example file in each language
must match, byte for byte, the output of the writer for the same inputs.
"""

from __future__ import annotations

import re
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest
from experiment_core import (
    ReinforcerEndEvent,
    ReinforcerStartEvent,
    ResponseEvent,
    SessionState,
    StateChangeEvent,
)

from session_recorder import OklSink

ROOT = Path(__file__).resolve().parent.parent
DOCS = ("docs/en/format.md", "docs/ja/format.md")
_BLOCK = re.compile(r"```\n(.*?)```", re.DOTALL)


def _write_example(path: Path) -> list[str]:
    sink = OklSink(path)
    sink.write_header(
        session_name="demo",
        clock_type="ManualClock",
        session_start=0.0,
        subject_id="rat-001",
        experiment_name="fr_baseline",
        wall_clock_start=datetime(2026, 4, 27, 14, 3, 11, tzinfo=timezone(timedelta(hours=9))),
        notes=["operator note"],
        metadata={"dsl": "FR3"},
    )
    sink.emit(StateChangeEvent(SessionState.IDLE, SessionState.RUNNING, 0.0))
    for i, t in enumerate((0.523, 1.014, 1.502), start=1):
        sink.emit(ResponseEvent(id=i, timestamp=t, operandum=0))
    sink.emit(ReinforcerStartEvent(id=1, timestamp=1.502, operandum=0, potency=1.0))
    sink.emit(ReinforcerEndEvent(id=1, timestamp=2.002, operandum=0))
    return path.read_text(encoding="utf-8").splitlines()


def _blocks(name: str) -> list[list[str]]:
    text = (ROOT / name).read_text(encoding="utf-8")
    return [block.splitlines() for block in _BLOCK.findall(text)]


@pytest.mark.parametrize("name", DOCS)
def test_canonical_codebook_matches_writer(name: str, tmp_path: Path) -> None:
    written = _write_example(tmp_path / "s.txt")
    start = written.index("# events:")
    codebook = written[start : written.index("# ---")]
    documented = [b for b in _blocks(name) if b and b[0] == "# events:"]
    assert documented == [codebook]


@pytest.mark.parametrize("name", DOCS)
def test_example_file_matches_writer(name: str, tmp_path: Path) -> None:
    written = _write_example(tmp_path / "s.txt")
    documented = [b for b in _blocks(name) if b and b[0] == "# OKL v1"]
    assert documented == [written]
