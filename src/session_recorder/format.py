"""OKL v1 (OperantKitLog v1) wire format.

OKL v1 is a plain UTF-8 text format with the ``.txt`` extension. The
file consists of three parts:

1. Magic line: ``# OKL v1``
2. Header block: ``#`` prefixed lines carrying session metadata and an
   event codebook, terminated by a single ``# ---`` line.
3. Body: one TAB separated event line per record.
   ``timestamp<TAB>type<TAB>...payload-cols``

Newlines are LF (writer) but the reader also accepts CRLF (it strips
trailing ``\\r`` before parsing).

The codebook in the header declares, for every event type the file
contains, the names and types of the positional payload columns. This
makes the file *self describing*: a reader that has never heard of a
given event type can still (a) tell how many columns to consume per
line and (b) know what each column means.

Field types supported in the codebook:

- ``int``     — base 10 signed integer
- ``float``   — fixed or scientific notation real
- ``str``     — TSV escaped string
- ``bool``    — ``true`` / ``false``

Any field name may be suffixed ``?`` to mark it optional. An optional
value that is absent is written as a single ``-``.

Strings are TSV escaped: ``\\``, ``\\t``, ``\\n``, ``\\r``. The literal
single-character value ``-`` is escaped as ``\\-`` so it cannot be
confused with the absent marker.
"""

from __future__ import annotations

import re
import warnings
from collections.abc import Iterable
from dataclasses import dataclass
from datetime import datetime
from typing import Any, Final

from experiment_core import (
    ComponentChangeEvent,
    ReinforcerEndEvent,
    ReinforcerStartEvent,
    ResponseEvent,
    SessionEvent,
    SessionMeta,
    SessionState,
    StateChangeEvent,
)

MAGIC: Final = "# OKL v1"
HEADER_TERMINATOR: Final = "# ---"
ABSENT: Final = "-"

EVENT_TYPE_RESPONSE: Final = "response"
EVENT_TYPE_REINFORCER_START: Final = "reinforcer_start"
EVENT_TYPE_REINFORCER_END: Final = "reinforcer_end"
EVENT_TYPE_STATE_CHANGE: Final = "state_change"
EVENT_TYPE_COMPONENT_CHANGE: Final = "component_change"
EVENT_TYPE_PHASE_ENTER: Final = "phase_enter"
EVENT_TYPE_PHASE_EXIT: Final = "phase_exit"

PHASE_RECORD_TYPES: Final = frozenset({EVENT_TYPE_PHASE_ENTER, EVENT_TYPE_PHASE_EXIT})


@dataclass(frozen=True)
class Field:
    """One positional column declaration in the codebook."""

    name: str
    ty: str  # "int" | "float" | "str" | "bool"
    optional: bool


CANONICAL_CODEBOOK: Final[dict[str, tuple[Field, ...]]] = {
    EVENT_TYPE_RESPONSE: (
        Field("id", "int", False),
        Field("operandum", "int", True),
    ),
    EVENT_TYPE_REINFORCER_START: (
        Field("id", "int", False),
        Field("potency", "float", False),
        Field("operandum", "int", True),
    ),
    EVENT_TYPE_REINFORCER_END: (
        Field("id", "int", False),
        Field("operandum", "int", True),
    ),
    EVENT_TYPE_STATE_CHANGE: (
        Field("from", "str", False),
        Field("to", "str", False),
    ),
    EVENT_TYPE_COMPONENT_CHANGE: (
        Field("from", "str", False),
        Field("to", "str", False),
    ),
    EVENT_TYPE_PHASE_ENTER: (
        Field("label", "str", False),
        Field("name", "str", True),
        Field("time", "str", True),
        Field("location", "str", True),
        Field("cue", "str", True),
    ),
    EVENT_TYPE_PHASE_EXIT: (
        Field("label", "str", False),
    ),
}


# --------------------------------------------------------------------------- #
# TSV escape / unescape
# --------------------------------------------------------------------------- #

def encode_str(value: str) -> str:
    """Escape a string for use as a TSV column."""
    out = (
        value.replace("\\", "\\\\")
        .replace("\t", "\\t")
        .replace("\n", "\\n")
        .replace("\r", "\\r")
    )
    if out == ABSENT:
        return "\\-"
    return out


_DECODE_RE = re.compile(r"\\(.)")
_DECODE_MAP = {"\\": "\\", "t": "\t", "n": "\n", "r": "\r", "-": "-"}


def decode_str(token: str) -> str:
    """Inverse of :func:`encode_str`. Unknown ``\\X`` escapes pass through."""
    return _DECODE_RE.sub(lambda m: _DECODE_MAP.get(m.group(1), m.group(0)), token)


# --------------------------------------------------------------------------- #
# Header
# --------------------------------------------------------------------------- #

def _toml_quote(value: str) -> str:
    """Produce a TOML basic-string literal."""
    escaped = (
        value.replace("\\", "\\\\")
        .replace('"', '\\"')
        .replace("\n", "\\n")
        .replace("\r", "\\r")
        .replace("\t", "\\t")
    )
    return f'"{escaped}"'


def _toml_format(value: Any) -> str:
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, int):
        return str(value)
    if isinstance(value, float):
        return repr(value)
    if isinstance(value, str):
        return _toml_quote(value)
    raise TypeError(
        f"unsupported metadata value type: {type(value).__name__} "
        "(OKL v1 metadata must be str/int/float/bool)"
    )


_TOML_KV_RE = re.compile(r'^\s*([A-Za-z_][\w.-]*)\s*=\s*(.+?)\s*$')


def _parse_toml_value(token: str) -> Any:
    if token == "true":
        return True
    if token == "false":
        return False
    if token.startswith('"') and token.endswith('"'):
        # basic-string. Reverse of _toml_quote.
        body = token[1:-1]
        out = []
        i = 0
        while i < len(body):
            c = body[i]
            if c == "\\" and i + 1 < len(body):
                nxt = body[i + 1]
                out.append(
                    {"\\": "\\", '"': '"', "n": "\n", "r": "\r", "t": "\t"}.get(nxt, nxt)
                )
                i += 2
            else:
                out.append(c)
                i += 1
        return "".join(out)
    # Try int, then float
    try:
        return int(token)
    except ValueError:
        pass
    try:
        return float(token)
    except ValueError:
        pass
    raise ValueError(f"unparseable header value: {token!r}")


def write_header(
    file: Any,
    *,
    session_name: str,
    clock_type: str,
    session_start: float,
    subject_id: str | None = None,
    replication_index: int | None = None,
    experiment_name: str | None = None,
    protocol_id: str | None = None,
    task_file_hash: str | None = None,
    wall_clock_start: datetime | None = None,
    notes: list[str] | None = None,
    metadata: dict[str, Any] | None = None,
    codebook: dict[str, tuple[Field, ...]] | None = None,
) -> None:
    """Write the OKL v1 magic + header block + terminator.

    Parameters
    ----------
    file:
        Anything with a ``write(str)`` method.
    session_name, clock_type, session_start:
        Required producer-supplied identity.
    subject_id, replication_index, experiment_name, protocol_id, task_file_hash:
        Optional :class:`experiment_core.SessionMeta` fields. Each is
        emitted as a top-level ``# key = value`` line when not ``None``.
    wall_clock_start:
        Optional timezone-aware datetime; serialised as an ISO 8601
        basic-string.
    notes:
        Optional list of free-form post-hoc annotations. Each item is
        emitted as one ``#   "<note>"`` line under a ``# notes:`` block.
    metadata:
        Optional flat dict of free-form key/value pairs (str/int/float/bool).
    codebook:
        Optional override of the event codebook. Defaults to
        :data:`CANONICAL_CODEBOOK`.
    """
    cb = codebook or CANONICAL_CODEBOOK
    file.write(MAGIC + "\n")
    file.write(f"# session_name = {_toml_quote(session_name)}\n")
    file.write(f"# clock_type = {_toml_quote(clock_type)}\n")
    file.write(f"# session_start = {_toml_format(session_start)}\n")
    if subject_id is not None:
        file.write(f"# subject_id = {_toml_quote(subject_id)}\n")
    if replication_index is not None:
        file.write(f"# replication_index = {_toml_format(int(replication_index))}\n")
    if experiment_name is not None:
        file.write(f"# experiment_name = {_toml_quote(experiment_name)}\n")
    if protocol_id is not None:
        file.write(f"# protocol_id = {_toml_quote(protocol_id)}\n")
    if task_file_hash is not None:
        file.write(f"# task_file_hash = {_toml_quote(task_file_hash)}\n")
    if wall_clock_start is not None:
        file.write(f"# wall_clock_start = {_toml_quote(wall_clock_start.isoformat())}\n")
    if notes:
        file.write("# notes:\n")
        for n in notes:
            file.write(f"#   {_toml_quote(n)}\n")
    if metadata:
        file.write("# meta:\n")
        for key, value in metadata.items():
            file.write(f"#   {key} = {_toml_format(value)}\n")
    file.write("# events:\n")
    for type_name, fields in cb.items():
        rendered = " ".join(_render_field(f) for f in fields)
        file.write(f"#   {type_name:<18}: {rendered}\n")
    file.write(HEADER_TERMINATOR + "\n")


def _render_field(field: Field) -> str:
    suffix = "?" if field.optional else ""
    return f"{field.name}:{field.ty}{suffix}"


_FIELD_RE = re.compile(r"^([A-Za-z_]\w*)\s*:\s*(int|float|str|bool)(\?)?$")


def _parse_field(token: str) -> Field:
    m = _FIELD_RE.match(token.strip())
    if not m:
        raise ValueError(f"malformed codebook field: {token!r}")
    return Field(name=m.group(1), ty=m.group(2), optional=m.group(3) == "?")


_RECOGNISED_TOP_KEYS: Final = frozenset(
    {
        "session_name",
        "clock_type",
        "session_start",
        "subject_id",
        "replication_index",
        "experiment_name",
        "protocol_id",
        "task_file_hash",
        "wall_clock_start",
    }
)


@dataclass(frozen=True)
class ParsedHeader:
    """Result of :func:`parse_header`.

    The fields mirror :class:`experiment_core.SessionMeta` so a
    consumer can do ``SessionMeta(**parsed.as_session_meta_kwargs())``
    or call :meth:`session_meta` directly.
    """

    session_name: str
    clock_type: str
    session_start: float
    subject_id: str | None
    replication_index: int | None
    experiment_name: str | None
    protocol_id: str | None
    task_file_hash: str | None
    wall_clock_start: datetime | None
    notes: list[str]
    metadata: dict[str, Any]
    codebook: dict[str, tuple[Field, ...]]

    def session_meta(self) -> SessionMeta:
        """Build a :class:`experiment_core.SessionMeta` from the parsed
        header. Note that ``timestamp`` on ``SessionMeta`` corresponds
        to ``session_start`` here."""
        return SessionMeta(
            timestamp=self.session_start,
            clock_type=self.clock_type,
            session_name=self.session_name,
            subject_id=self.subject_id,
            replication_index=self.replication_index,
            experiment_name=self.experiment_name,
            protocol_id=self.protocol_id,
            task_file_hash=self.task_file_hash,
            wall_clock_start=self.wall_clock_start,
            notes=list(self.notes),
            metadata=dict(self.metadata),
        )


def parse_header(lines: Iterable[str]) -> tuple[ParsedHeader, int]:
    """Parse the magic + header block out of an iterable of lines.

    Returns a tuple of the :class:`ParsedHeader` and the **count of
    lines consumed** (including magic and terminator). The caller is
    expected to feed the remaining lines through :func:`parse_event_line`.

    Unknown top-level keys produce a :class:`UserWarning` (once per
    key) and the value is preserved under the same key inside
    ``metadata`` so the file still round-trips. Required keys missing
    raises :class:`ValueError`.
    """
    it = iter(lines)
    consumed = 0

    def _next() -> str:
        nonlocal consumed
        try:
            line = next(it)
        except StopIteration as e:
            raise ValueError("unexpected EOF in header") from e
        consumed += 1
        line = line.rstrip("\r\n").rstrip("\r")
        # Strip BOM if it appears on the very first line; raise a clear
        # error rather than the cryptic "expected '# OKL v1'" failure.
        if consumed == 1 and line.startswith("﻿"):
            raise ValueError(
                "OKL v1: file starts with a UTF-8 BOM. "
                "Save the file as UTF-8 without BOM and try again."
            )
        return line

    first = _next()
    if first != MAGIC:
        raise ValueError(f"expected {MAGIC!r} as first line, got {first!r}")

    session_name: str | None = None
    clock_type: str | None = None
    session_start: float | None = None
    subject_id: str | None = None
    replication_index: int | None = None
    experiment_name: str | None = None
    protocol_id: str | None = None
    task_file_hash: str | None = None
    wall_clock_start: datetime | None = None
    notes: list[str] = []
    metadata: dict[str, Any] = {}
    codebook: dict[str, tuple[Field, ...]] = {}

    section: str | None = None
    while True:
        raw = _next()
        if raw == HEADER_TERMINATOR:
            break
        if not raw.startswith("#"):
            raise ValueError(f"unexpected non-header line during header: {raw!r}")
        body = raw[1:].lstrip()
        if not body:
            continue
        if body.startswith("meta:"):
            section = "meta"
            continue
        if body.startswith("notes:"):
            section = "notes"
            continue
        if body.startswith("events:"):
            section = "events"
            continue
        # Indented continuation of the current section. Header lines are
        # always "# <text>". Section continuations are written with two
        # extra spaces of indent, which after lstrip leaves a normal
        # ``key = ...`` (or, for ``notes:``, just a quoted string).
        if section == "meta":
            m = _TOML_KV_RE.match(body)
            if not m:
                raise ValueError(f"malformed meta line: {raw!r}")
            metadata[m.group(1)] = _parse_toml_value(m.group(2))
            continue
        if section == "notes":
            # A notes entry is just a TOML basic-string on its own line.
            notes.append(_parse_toml_value(body))
            continue
        if section == "events":
            # Format: ``<type-name> : <field> <field> ...``
            type_name, _, rest = body.partition(":")
            type_name = type_name.strip()
            if not type_name:
                raise ValueError(f"malformed events line: {raw!r}")
            tokens = rest.strip().split()
            codebook[type_name] = tuple(_parse_field(t) for t in tokens)
            continue
        # Top-level key=value
        m = _TOML_KV_RE.match(body)
        if not m:
            raise ValueError(f"malformed header line: {raw!r}")
        key, value_token = m.group(1), m.group(2)
        value = _parse_toml_value(value_token)
        if key == "session_name":
            session_name = str(value)
        elif key == "clock_type":
            clock_type = str(value)
        elif key == "session_start":
            session_start = float(value)
        elif key == "subject_id":
            subject_id = str(value)
        elif key == "replication_index":
            replication_index = int(value)
        elif key == "experiment_name":
            experiment_name = str(value)
        elif key == "protocol_id":
            protocol_id = str(value)
        elif key == "task_file_hash":
            task_file_hash = str(value)
        elif key == "wall_clock_start":
            wall_clock_start = datetime.fromisoformat(str(value))
        else:
            # Unknown top-level key — likely a typo. Preserve flat in
            # ``metadata`` (so the file round-trips) and warn once so
            # producers notice.
            warnings.warn(
                f"OKL v1 header: unknown top-level key {key!r} "
                "(preserved under metadata; check for typos)",
                UserWarning,
                stacklevel=2,
            )
            metadata[key] = value

    if session_name is None or clock_type is None or session_start is None:
        missing = [
            name
            for name, val in (
                ("session_name", session_name),
                ("clock_type", clock_type),
                ("session_start", session_start),
            )
            if val is None
        ]
        raise ValueError(f"OKL v1 header missing required keys: {missing}")

    return (
        ParsedHeader(
            session_name=session_name,
            clock_type=clock_type,
            session_start=session_start,
            subject_id=subject_id,
            replication_index=replication_index,
            experiment_name=experiment_name,
            protocol_id=protocol_id,
            task_file_hash=task_file_hash,
            wall_clock_start=wall_clock_start,
            notes=notes,
            metadata=metadata,
            codebook=codebook,
        ),
        consumed,
    )


# --------------------------------------------------------------------------- #
# Event line: encode
# --------------------------------------------------------------------------- #

def _encode_value(value: Any, field: Field) -> str:
    if value is None:
        if not field.optional:
            raise ValueError(f"required field {field.name!r} is None")
        return ABSENT
    # Reject silent ``bool``-as-``int`` coercion: ``isinstance(True, int)``
    # is True in Python, so without this check, ``True`` would be written
    # as ``"1"`` for an ``int`` field. That kind of silent coercion is
    # debug-hostile when downstream codebooks add bool fields.
    if isinstance(value, bool) and field.ty != "bool":
        raise TypeError(
            f"field {field.name!r} is declared {field.ty!r} but got bool {value!r}"
        )
    if field.ty == "int":
        return str(int(value))
    if field.ty == "float":
        return repr(float(value))
    if field.ty == "bool":
        if not isinstance(value, bool):
            raise TypeError(
                f"field {field.name!r} is declared bool but got "
                f"{type(value).__name__} {value!r}"
            )
        return "true" if value else "false"
    if field.ty == "str":
        return encode_str(str(value))
    raise ValueError(f"unknown field type: {field.ty}")


def _encode_line(timestamp: float, type_name: str, args: dict[str, Any]) -> str:
    fields = CANONICAL_CODEBOOK[type_name]
    cols = [repr(float(timestamp)), type_name]
    for f in fields:
        cols.append(_encode_value(args.get(f.name), f))
    return "\t".join(cols)


def encode_event(event: SessionEvent) -> str:
    """Encode a :class:`SessionEvent` as a single OKL v1 body line
    (no trailing newline)."""
    if isinstance(event, ResponseEvent):
        return _encode_line(
            event.timestamp,
            EVENT_TYPE_RESPONSE,
            {"id": event.id, "operandum": event.operandum},
        )
    if isinstance(event, ReinforcerStartEvent):
        return _encode_line(
            event.timestamp,
            EVENT_TYPE_REINFORCER_START,
            {"id": event.id, "potency": event.potency, "operandum": event.operandum},
        )
    if isinstance(event, ReinforcerEndEvent):
        return _encode_line(
            event.timestamp,
            EVENT_TYPE_REINFORCER_END,
            {"id": event.id, "operandum": event.operandum},
        )
    if isinstance(event, StateChangeEvent):
        return _encode_line(
            event.timestamp,
            EVENT_TYPE_STATE_CHANGE,
            {"from": event.from_state.name, "to": event.to_state.name},
        )
    if isinstance(event, ComponentChangeEvent):
        return _encode_line(
            event.timestamp,
            EVENT_TYPE_COMPONENT_CHANGE,
            {"from": event.from_component, "to": event.to_component},
        )
    raise TypeError(f"unknown session event type: {type(event).__name__}")


def encode_phase_enter(
    *,
    timestamp: float,
    label: str,
    context: dict[str, Any] | None = None,
) -> str:
    ctx = {k: v for k, v in (context or {}).items() if v is not None}
    return _encode_line(
        timestamp,
        EVENT_TYPE_PHASE_ENTER,
        {
            "label": label,
            "name": ctx.get("name"),
            "time": ctx.get("time"),
            "location": ctx.get("location"),
            "cue": ctx.get("cue"),
        },
    )


def encode_phase_exit(*, timestamp: float, label: str) -> str:
    return _encode_line(timestamp, EVENT_TYPE_PHASE_EXIT, {"label": label})


# --------------------------------------------------------------------------- #
# Event line: decode
# --------------------------------------------------------------------------- #

def _decode_value(token: str, field: Field) -> Any:
    if token == ABSENT:
        if field.optional:
            return None
        raise ValueError(f"required field {field.name!r} got absent token")
    if field.ty == "int":
        return int(token)
    if field.ty == "float":
        return float(token)
    if field.ty == "bool":
        if token == "true":
            return True
        if token == "false":
            return False
        raise ValueError(f"bool field {field.name!r} got: {token!r}")
    if field.ty == "str":
        return decode_str(token)
    raise ValueError(f"unknown field type: {field.ty}")


@dataclass(frozen=True)
class ParsedRecord:
    """Result of :func:`parse_event_line`. ``args`` is keyed by the
    codebook field name."""

    timestamp: float
    type: str
    args: dict[str, Any]


def parse_event_line(
    line: str, codebook: dict[str, tuple[Field, ...]]
) -> ParsedRecord:
    """Parse one body line according to ``codebook``.

    Raises :class:`ValueError` if the type is not in the codebook or if
    the column count / types do not match.
    """
    stripped = line.rstrip("\r\n").rstrip("\r")
    if not stripped:
        raise ValueError("empty event line")
    cols = stripped.split("\t")
    if len(cols) < 2:
        raise ValueError(f"event line needs at least 2 columns: {line!r}")
    timestamp = float(cols[0])
    type_name = cols[1]
    if type_name not in codebook:
        raise KeyError(type_name)
    fields = codebook[type_name]
    payload = cols[2:]
    if len(payload) != len(fields):
        raise ValueError(
            f"event {type_name!r}: expected {len(fields)} payload cols, got {len(payload)}"
        )
    args = {
        f.name: _decode_value(tok, f) for f, tok in zip(fields, payload, strict=True)
    }
    return ParsedRecord(timestamp=timestamp, type=type_name, args=args)


def materialise(record: ParsedRecord) -> SessionEvent:
    """Build a :class:`SessionEvent` from a :class:`ParsedRecord` of one
    of the four canonical event types.

    Raises :class:`ValueError` for phase markers (use the dedicated
    accessor) or unknown types.
    """
    if record.type == EVENT_TYPE_RESPONSE:
        return ResponseEvent(
            id=record.args["id"],
            timestamp=record.timestamp,
            operandum=record.args.get("operandum"),
        )
    if record.type == EVENT_TYPE_REINFORCER_START:
        return ReinforcerStartEvent(
            id=record.args["id"],
            timestamp=record.timestamp,
            potency=record.args["potency"],
            operandum=record.args.get("operandum"),
        )
    if record.type == EVENT_TYPE_REINFORCER_END:
        return ReinforcerEndEvent(
            id=record.args["id"],
            timestamp=record.timestamp,
            operandum=record.args.get("operandum"),
        )
    if record.type == EVENT_TYPE_STATE_CHANGE:
        return StateChangeEvent(
            from_state=SessionState[record.args["from"]],
            to_state=SessionState[record.args["to"]],
            timestamp=record.timestamp,
        )
    if record.type == EVENT_TYPE_COMPONENT_CHANGE:
        return ComponentChangeEvent(
            from_component=str(record.args["from"]),
            to_component=str(record.args["to"]),
            timestamp=record.timestamp,
        )
    raise ValueError(f"cannot materialise type {record.type!r} as SessionEvent")
