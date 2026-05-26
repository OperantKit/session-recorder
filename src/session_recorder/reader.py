"""Read OKL v1 session logs back into Python objects.

The reader is the canonical inverse of
:class:`session_recorder.sink.OklSink`. Downstream packages
(``session-analyzer``, ``aba-advisor``, ``session-visualizer``, ...)
consume session data through these helpers rather than re-parsing OKL
v1 by hand.

The default policy for unknown event types is ``"warn"``: a warning is
emitted once per type and the offending records are skipped. Set
``on_unknown="error"`` to opt into strict behaviour or
``on_unknown="skip"`` to silently drop them.
"""

from __future__ import annotations

import warnings
from collections.abc import Iterator
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Literal

from experiment_core import SessionEvent, SessionMeta

from .format import (
    EVENT_TYPE_PHASE_ENTER,
    EVENT_TYPE_PHASE_EXIT,
    Field,
    ParsedRecord,
    materialise,
    parse_event_line,
    parse_header,
)

OnUnknown = Literal["warn", "error", "skip"]


@dataclass(frozen=True)
class PhaseMarker:
    """One phase boundary (enter or exit).

    Attributes
    ----------
    kind : ``"enter"`` or ``"exit"``
    timestamp : float
    label : str
        Human-readable phase label (e.g. ``"Acquisition"``).
    context : dict[str, str]
        Foundations-of-context coordinates. Possible keys: ``name``,
        ``time``, ``location``, ``cue``. Empty for ``exit`` markers and
        for phases without associated context.
    """

    kind: str
    timestamp: float
    label: str
    context: dict[str, str]


@dataclass(frozen=True)
class SessionLog:
    """All records read from an OKL v1 session log.

    Attributes
    ----------
    meta:
        The parsed header. Always present in OKL v1.
    events:
        Every :class:`~experiment_core.events.SessionEvent` in emission
        order.
    raw_records:
        Every body record (excluding phase markers and unknown skipped
        records) as a :class:`~session_recorder.format.ParsedRecord`,
        in emission order.
    phase_markers:
        Every ``phase_enter`` / ``phase_exit`` record in emission
        order.
    unknown_types:
        Set of event types that were encountered but not declared in
        the codebook; reported only when ``on_unknown="warn"``.
    """

    meta: SessionMeta
    events: list[SessionEvent]
    raw_records: list[ParsedRecord]
    phase_markers: list[PhaseMarker]
    unknown_types: frozenset[str] = field(default_factory=frozenset)


def _phase_context(parsed: ParsedRecord) -> dict[str, str]:
    out: dict[str, str] = {}
    for key in ("name", "time", "location", "cue"):
        value = parsed.args.get(key)
        if value is not None:
            out[key] = str(value)
    return out


def iter_records(
    path: str | Path,
    *,
    on_unknown: OnUnknown = "warn",
) -> Iterator[ParsedRecord]:
    """Yield :class:`ParsedRecord` instances for every body line.

    The header is consumed transparently; consumers that need it should
    call :func:`read_log` instead.

    Lines whose type is not declared in the file's own codebook are
    handled per ``on_unknown``:

    - ``"warn"`` (default): emit a :class:`UserWarning` once per type and
      skip the record.
    - ``"skip"``: silently skip.
    - ``"error"``: raise :class:`KeyError`.
    """
    if on_unknown not in ("warn", "skip", "error"):
        raise ValueError(f"on_unknown must be 'warn'|'skip'|'error', got {on_unknown!r}")

    p = Path(path)
    if _is_empty_file(p):
        return

    body_lines = _read_framed_lines(p)
    if not body_lines:
        return
    parsed_header, header_consumed = parse_header(iter(body_lines))
    codebook = parsed_header.codebook
    warned: set[str] = set()
    for line in body_lines[header_consumed:]:
        stripped = line.rstrip("\r\n").rstrip("\r")
        if not stripped or not stripped.strip():
            continue
        try:
            yield parse_event_line(stripped, codebook)
        except KeyError as e:
            type_name = e.args[0] if e.args else "?"
            if on_unknown == "error":
                raise KeyError(
                    f"unknown event type {type_name!r} (not declared in codebook)"
                ) from None
            if on_unknown == "warn" and type_name not in warned:
                warned.add(type_name)
                warnings.warn(
                    f"OKL v1 reader: skipping unknown event type {type_name!r}",
                    UserWarning,
                    stacklevel=2,
                )
            continue


def read_log(
    path: str | Path,
    *,
    on_unknown: OnUnknown = "warn",
) -> SessionLog:
    """Read an entire OKL v1 session log into a :class:`SessionLog`."""
    if on_unknown not in ("warn", "skip", "error"):
        raise ValueError(f"on_unknown must be 'warn'|'skip'|'error', got {on_unknown!r}")

    p = Path(path)
    if _is_empty_file(p):
        meta = SessionMeta(
            timestamp=0.0,
            clock_type="",
            session_name="",
        )
        return SessionLog(
            meta=meta,
            events=[],
            raw_records=[],
            phase_markers=[],
            unknown_types=frozenset(),
        )

    body_lines = _read_framed_lines(p)
    header, header_consumed = parse_header(iter(body_lines))

    events: list[SessionEvent] = []
    raw_records: list[ParsedRecord] = []
    phase_markers: list[PhaseMarker] = []
    warned: set[str] = set()
    unknown: set[str] = set()

    for line in body_lines[header_consumed:]:
        stripped = line.rstrip("\r\n").rstrip("\r")
        if not stripped or not stripped.strip():
            continue
        try:
            rec = parse_event_line(stripped, header.codebook)
        except KeyError as e:
            type_name = e.args[0] if e.args else "?"
            unknown.add(type_name)
            if on_unknown == "error":
                raise KeyError(
                    f"unknown event type {type_name!r} (not declared in codebook)"
                ) from None
            if on_unknown == "warn" and type_name not in warned:
                warned.add(type_name)
                warnings.warn(
                    f"OKL v1 reader: skipping unknown event type {type_name!r}",
                    UserWarning,
                    stacklevel=2,
                )
            continue

        if rec.type == EVENT_TYPE_PHASE_ENTER:
            phase_markers.append(
                PhaseMarker(
                    kind="enter",
                    timestamp=rec.timestamp,
                    label=str(rec.args["label"]),
                    context=_phase_context(rec),
                )
            )
        elif rec.type == EVENT_TYPE_PHASE_EXIT:
            phase_markers.append(
                PhaseMarker(
                    kind="exit",
                    timestamp=rec.timestamp,
                    label=str(rec.args["label"]),
                    context={},
                )
            )
        else:
            raw_records.append(rec)
            events.append(materialise(rec))

    meta = header.session_meta()
    return SessionLog(
        meta=meta,
        events=events,
        raw_records=raw_records,
        phase_markers=phase_markers,
        unknown_types=frozenset(unknown),
    )


def _read_framed_lines(p: Path) -> list[str]:
    """Return the file's content split into fully-framed lines.

    The OKL v1 spec mandates that readers treat a trailing line without
    a terminating ``\\n`` as a torn write and discard it. We implement
    that here by reading the raw bytes and slicing off any tail after
    the last LF.
    """
    raw = p.read_bytes()
    if not raw:
        return []
    last_lf = raw.rfind(b"\n")
    if last_lf == -1:
        # No complete line at all
        return []
    framed = raw[: last_lf + 1].decode("utf-8")
    # splitlines() on text honors any line terminator; we then re-strip
    # later in the body loop.
    return framed.splitlines()


def _iter_lines(f: Any) -> Iterator[str]:
    """Yield raw lines from a text file, accepting both LF and CRLF."""
    yield from f


def _is_empty_file(p: Path) -> bool:
    """Return True if ``p`` does not exist, is zero-byte, or contains
    only whitespace.

    OKL v1 readers treat such files as logs with no header and no
    events (a defensible relaxation for CLIs that may pre-create
    output files before the producer starts writing).
    """
    if not p.exists():
        return True
    if p.stat().st_size == 0:
        return True
    return p.read_text(encoding="utf-8").strip() == ""


__all__ = [
    "OnUnknown",
    "PhaseMarker",
    "SessionLog",
    "SessionMeta",
    "iter_records",
    "read_log",
]


# Keep Field re-exported here for downstream codebook introspection.
_ = Field
