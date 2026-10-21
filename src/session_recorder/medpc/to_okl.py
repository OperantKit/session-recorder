"""Convert a :class:`MedPcSession` into an OKL v1 log.

MED-PC files carry no event semantics: what code ``.200`` or array
``B`` means is decided by the MSN program that wrote them. A
:class:`Protocol` supplies that meaning. Built-in protocols cover three
public datasets whose programs are published:

- ``bernardy-vdrl`` / ``bernardy-training`` — Bernardy (2025), nose-poke
  VDRL and VI training (array ``D`` / ``C``, 10 ms ticks).
- ``sosa-inh`` — Sosa et al. (2026), Pavlovian conditioned inhibition
  followed by DRL 10 s (array ``J``, 10 ms ticks).
- ``mccutcheon-prpr`` — McCutcheon (2022), FR / PR lever pressing
  (FORMAT 4, time stamps in seconds in ``B`` and ``D``).

Every source event becomes exactly one *primary* body line, or is
counted as unmapped. Lines the converter adds (session start/end that
the file does not record, phase and component boundaries) are
*synthesised* and counted separately, so that
``primary + unmapped == source`` can be checked against the file.
"""

from __future__ import annotations

import re
from collections import Counter
from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any, Final

from ..format import (
    CANONICAL_CODEBOOK,
    EVENT_TYPE_COMPONENT_CHANGE,
    EVENT_TYPE_PHASE_ENTER,
    EVENT_TYPE_PHASE_EXIT,
    EVENT_TYPE_REINFORCER_END,
    EVENT_TYPE_REINFORCER_START,
    EVENT_TYPE_RESPONSE,
    EVENT_TYPE_STATE_CHANGE,
    Field,
    encode_record,
    write_header,
)
from .parse import MedPcSession, split_code

EVENT_TYPE_HEAD_ENTRY: Final = "head_entry"
EVENT_TYPE_HEAD_EXIT: Final = "head_exit"

MEDPC_CODEBOOK: Final[dict[str, tuple[Field, ...]]] = {
    **CANONICAL_CODEBOOK,
    EVENT_TYPE_HEAD_ENTRY: (Field("id", "int", False),),
    EVENT_TYPE_HEAD_EXIT: (Field("id", "int", False),),
}


@dataclass(frozen=True)
class Row:
    """One OKL body line before encoding."""

    timestamp: float
    type: str
    args: dict[str, Any]
    synthesised: bool = False


@dataclass(frozen=True)
class Converted:
    """Rows and counts produced by a protocol for one session."""

    rows: list[Row]
    source_events: int
    unmapped: Counter[str]
    metadata: dict[str, str | int | float | bool]

    @property
    def primary(self) -> int:
        return sum(1 for r in self.rows if not r.synthesised)

    @property
    def synthesised(self) -> int:
        return sum(1 for r in self.rows if r.synthesised)


@dataclass(frozen=True)
class Protocol:
    """How to read one MSN program's output."""

    name: str
    convert: Callable[[MedPcSession], Converted]


class _Ids:
    def __init__(self) -> None:
        self._n: Counter[str] = Counter()

    def next(self, kind: str) -> int:
        self._n[kind] += 1
        return self._n[kind]

    def last(self, kind: str) -> int:
        return self._n[kind]


def _event_array(session: MedPcSession, letter: str) -> tuple[str, ...]:
    if letter in session.arrays:
        return session.arrays[letter]
    if letter in session.scalars:
        return (session.scalars[letter],)
    raise ValueError(f"{session.source}: event array {letter} not found")


def _state(t: float, frm: str, to: str, synth: bool = False) -> Row:
    return Row(t, EVENT_TYPE_STATE_CHANGE, {"from": frm, "to": to}, synth)


def _response(t: float, ids: _Ids, operandum: int | None) -> Row:
    return Row(t, EVENT_TYPE_RESPONSE, {"id": ids.next("response"), "operandum": operandum})


def _sr_start(t: float, ids: _Ids, operandum: int | None) -> Row:
    return Row(
        t,
        EVENT_TYPE_REINFORCER_START,
        {"id": ids.next("reinforcer"), "potency": 1.0, "operandum": operandum},
    )


def _array_meta(session: MedPcSession, letters: tuple[str, ...]) -> dict[str, str]:
    return {f"medpc.array.{k}": " ".join(session.arrays[k]) for k in letters if k in session.arrays}


# --------------------------------------------------------------------------- #
# Bernardy (2025) — VDRL and VI training
# --------------------------------------------------------------------------- #


def _convert_bernardy_vdrl(session: MedPcSession) -> Converted:
    ids = _Ids()
    rows: list[Row] = []
    unmapped: Counter[str] = Counter()
    source = _event_array(session, "D")
    for token in source:
        tick, code = split_code(token)
        t = tick / 100.0
        if code == "123":
            rows.append(_state(t, "IDLE", "RUNNING"))
        elif code in ("200", "210"):
            rows.append(_response(t, ids, 0))
        elif code == "300":
            rows.append(_sr_start(t, ids, 0))
        elif code == "310":
            rows.append(
                Row(t, EVENT_TYPE_REINFORCER_END, {"id": ids.last("reinforcer"), "operandum": 0})
            )
        elif code == "789":
            rows.append(_state(t, "RUNNING", "FINISHED"))
        else:
            unmapped[code] += 1
    meta: dict[str, str | int | float | bool] = {
        "medpc.tick_s": 0.01,
        "medpc.reinforcement_period_s": 3.0,
        "operandum_labels.0": "nose poke",
        **_array_meta(session, ("A", "L")),
    }
    a = session.arrays.get("A")
    if a and len(a) > 2:
        meta["medpc.schedule"] = f"VDRL (scale A(2) = {a[2]} s)"
    return Converted(rows, len(source), unmapped, meta)


def _convert_bernardy_training(session: MedPcSession) -> Converted:
    ids = _Ids()
    rows: list[Row] = []
    unmapped: Counter[str] = Counter()
    source = _event_array(session, "C")
    for token in source:
        tick, code = split_code(token)
        t = tick / 100.0
        if code == "111":
            rows.append(_state(t, "IDLE", "RUNNING"))
        elif code == "200":
            rows.append(_response(t, ids, 0))
        elif code == "400":
            rows.append(_sr_start(t, ids, 0))
        elif code == "999":
            rows.append(_state(t, "RUNNING", "FINISHED"))
        else:
            unmapped[code] += 1
    meta: dict[str, str | int | float | bool] = {
        "medpc.tick_s": 0.01,
        "operandum_labels.0": "nose poke",
        **_array_meta(session, ("A", "I")),
    }
    # I is a fixed interval list with mean 100 in every file; the VI value
    # is A(4), which matches the dataset's VI10s / VI30s folders.
    a = session.arrays.get("A")
    if a and len(a) > 4 and float(a[4]) > 0:
        meta["schedule.spec_dsl"] = f"VI {float(a[4]):g}s"
    return Converted(rows, len(source), unmapped, meta)


# --------------------------------------------------------------------------- #
# Sosa et al. (2026) — Pavlovian conditioned inhibition then DRL 10 s
# --------------------------------------------------------------------------- #


def _convert_sosa_inh(session: MedPcSession) -> Converted:
    # Codes follow the MSN program, not the dataset README, which swaps
    # trial onset (.3/.4) and offset (.23/.24).
    ids = _Ids()
    rows: list[Row] = []
    unmapped: Counter[str] = Counter()
    component = "ITI"
    source = _event_array(session, "J")

    def change(t: float, to: str, synth: bool) -> None:
        nonlocal component
        rows.append(Row(t, EVENT_TYPE_COMPONENT_CHANGE, {"from": component, "to": to}, synth))
        component = to

    for token in source:
        tick, code = split_code(token)
        t = tick / 100.0
        if code == "999":
            rows.append(_state(t, "IDLE", "RUNNING"))
            rows.append(Row(t, EVENT_TYPE_PHASE_ENTER, {"label": "PCI"}, True))
        elif code == "987":
            change(t, "preCS", False)
        elif code == "300":
            change(t, "A+", False)
        elif code == "400":
            change(t, "AX-", False)
        elif code == "200":
            rows.append(_sr_start(t, ids, None))
            # A+ offset is not recorded (it shares a tick with the first
            # food delivery); the first delivery closes the trial.
            if component == "A+":
                change(t, "ITI", True)
        elif code == "240":
            change(t, "ITI", False)
        elif code == "100":
            rows.append(Row(t, EVENT_TYPE_HEAD_ENTRY, {"id": ids.next(EVENT_TYPE_HEAD_ENTRY)}))
        elif code == "110":
            rows.append(Row(t, EVENT_TYPE_HEAD_EXIT, {"id": ids.next(EVENT_TYPE_HEAD_EXIT)}))
        elif code == "998":
            rows.append(Row(t, EVENT_TYPE_PHASE_EXIT, {"label": "PCI"}))
        elif code == "531":
            rows.append(Row(t, EVENT_TYPE_PHASE_ENTER, {"label": "DRL"}))
            change(t, "DRL", True)
        elif code in ("307", "310"):
            rows.append(_response(t, ids, 0))
        elif code == "218":
            rows.append(_sr_start(t, ids, 0))
        elif code in ("155", "154"):
            rows.append(Row(t, EVENT_TYPE_PHASE_EXIT, {"label": "DRL"}))
            rows.append(_state(t, "RUNNING", "FINISHED", True))
        else:
            unmapped[code] += 1
    meta: dict[str, str | int | float | bool] = {
        "medpc.tick_s": 0.01,
        "medpc.reinforcement_period_s.PCI": 0.02,
        "medpc.reinforcement_period_s.DRL": 4.0,
        "schedule.spec_dsl": "DRL 10s",
        "operandum_labels.0": "left lever",
        **_array_meta(session, ("A",)),
    }
    return Converted(rows, len(source), unmapped, meta)


# --------------------------------------------------------------------------- #
# McCutcheon (2022) — FR / PR, FORMAT 4, seconds
# --------------------------------------------------------------------------- #


def _times(session: MedPcSession, letter: str) -> list[float]:
    values = list(_event_array(session, letter))
    if values and float(values[0]) < 0:
        values = values[1:]  # start-of-array marker written by the MSN program
    return [float(v) for v in values]


def _convert_mccutcheon_prpr(session: MedPcSession) -> Converted:
    ids = _Ids()
    experiment = session.header.get("experiment", "").upper()
    end = session.scalars.get("T")
    if experiment.startswith("MAG"):
        # Magazine training records counts only (no time stamps).
        rows = [_state(0.0, "IDLE", "RUNNING", True)]
        if end is not None:
            rows.append(_state(float(end), "RUNNING", "FINISHED", True))
        counts = {f"medpc.var.{k}": session.scalars[k] for k in ("A", "C") if k in session.scalars}
        return Converted(rows, 0, Counter(), {"medpc.tick_s": 1.0, **counts})
    presses = _times(session, "B")
    deliveries = _times(session, "D")
    for letter, times in (("A", presses), ("C", deliveries)):
        declared = session.scalars.get(letter)
        if declared is not None and int(float(declared)) != len(times):
            raise ValueError(
                f"{session.source}: {letter} = {declared} but {len(times)} time stamps"
            )
    merged = sorted(
        [(t, 0) for t in presses] + [(t, 1) for t in deliveries], key=lambda x: (x[0], x[1])
    )
    rows: list[Row] = [_state(0.0, "IDLE", "RUNNING", True)]
    for t, kind in merged:
        rows.append(_response(t, ids, 0) if kind == 0 else _sr_start(t, ids, 0))
    if end is not None:
        rows.append(_state(float(end), "RUNNING", "FINISHED", True))
    meta: dict[str, str | int | float | bool] = {
        "medpc.tick_s": 1.0,
        "operandum_labels.0": "lever",
    }
    if "X" in session.scalars:
        meta["medpc.var.X"] = session.scalars["X"]
    fr = re.match(r"FR(\d)(?!\d)", experiment)
    if fr:
        meta["schedule.spec_dsl"] = f"FR {fr.group(1)}"
    ratios = session.arrays.get("Z")
    if experiment.startswith("PR") and ratios and len(ratios) > 1:
        meta["medpc.pr.start"] = ratios[0]
        meta["medpc.pr.step"] = f"{float(ratios[1]) - float(ratios[0]):g}"
    return Converted(rows, len(presses) + len(deliveries), Counter(), meta)


PROTOCOLS: Final[dict[str, Protocol]] = {
    p.name: p
    for p in (
        Protocol("bernardy-vdrl", _convert_bernardy_vdrl),
        Protocol("bernardy-training", _convert_bernardy_training),
        Protocol("sosa-inh", _convert_sosa_inh),
        Protocol("mccutcheon-prpr", _convert_mccutcheon_prpr),
    )
}

_BY_MSN: Final = {
    "VDRL": "bernardy-vdrl",
    "Training": "bernardy-training",
    "A inhibicion": "sosa-inh",
    # Same event codes and arrays; used for one box in every session.
    "A inhibicion c7": "sosa-inh",
}


def guess_protocol(session: MedPcSession) -> str | None:
    """Return the built-in protocol name for an annotated session's MSN,
    or ``None``. FORMAT 4 files carry no MSN, so they always need an
    explicit protocol."""
    return _BY_MSN.get(session.header.get("msn", ""))


# --------------------------------------------------------------------------- #
# Writing
# --------------------------------------------------------------------------- #


def _wall_clock(session: MedPcSession) -> datetime | None:
    date, clock = session.header.get("start_date"), session.header.get("start_time")
    if not date or not clock:
        return None
    try:
        return datetime.strptime(f"{date} {clock.strip()}", "%m/%d/%y %H:%M:%S")
    except ValueError:
        return None


def _subject(session: MedPcSession) -> str | None:
    subject = session.header.get("subject", "").strip()
    if subject:
        return subject
    # MED-PC's default file name ends in "Subject <id>"; the INH dataset
    # names files "R<n>_inh_s<k>".
    stem = session.source.stem
    m = re.search(r"Subject\s*(\S+)$", stem) or re.search(r"(?:^|_)(R\d+)(?:_|$)", stem)
    return m.group(1) if m else None


def medpc_to_okl(
    session: MedPcSession,
    out_path: str | Path,
    protocol: str | None = None,
) -> Converted:
    """Write ``session`` as an OKL v1 log at ``out_path``.

    ``protocol`` names an entry of :data:`PROTOCOLS`; when omitted it is
    guessed from the MSN name (annotated files only). Returns the
    :class:`Converted` result so callers can check the event counts.
    """
    name = protocol or guess_protocol(session)
    if name is None:
        raise ValueError(
            f"{session.source}: cannot infer a protocol; pass one of {sorted(PROTOCOLS)}"
        )
    if name not in PROTOCOLS:
        raise ValueError(f"unknown protocol {name!r}; known: {sorted(PROTOCOLS)}")
    converted = PROTOCOLS[name].convert(session)
    if converted.primary + sum(converted.unmapped.values()) != converted.source_events:
        raise AssertionError(
            f"{session.source}: {converted.primary} primary + "
            f"{sum(converted.unmapped.values())} unmapped != {converted.source_events} source"
        )

    metadata: dict[str, str | int | float | bool] = {
        "medpc.protocol": name,
        "medpc.format": session.format,
        "medpc.source_events": converted.source_events,
        "medpc.synthesised_lines": converted.synthesised,
    }
    for key in ("file", "box", "group", "end_date", "end_time"):
        value = session.header.get(key)
        if value:
            metadata[f"medpc.{key}"] = value
    if converted.unmapped:
        metadata["medpc.unmapped_codes"] = " ".join(
            f".{code}:{n}" for code, n in sorted(converted.unmapped.items())
        )
    metadata.update(converted.metadata)

    msn = session.header.get("msn") or session.header.get("experiment") or name
    out = Path(out_path)
    out.parent.mkdir(parents=True, exist_ok=True)
    with out.open("w", encoding="utf-8", newline="") as f:
        write_header(
            f,
            session_name=msn,
            clock_type="MED-PC",
            session_start=0.0,
            subject_id=_subject(session),
            experiment_name=session.header.get("experiment") or None,
            protocol_id=msn,
            wall_clock_start=_wall_clock(session),
            metadata=metadata,
            codebook=MEDPC_CODEBOOK,
        )
        for row in converted.rows:
            f.write(encode_record(row.timestamp, row.type, row.args, MEDPC_CODEBOOK) + "\n")
    return converted
