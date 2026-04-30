"""OKL v1 persistence for OperantKit session events.

Defines the canonical OKL v1 wire format (see
:mod:`session_recorder.format`) and provides:

- :class:`OklSink` — implements :class:`experiment_core.EventSink` by
  writing an OKL v1 header then appending each event as a TSV body
  line.
- :func:`read_log` / :func:`iter_records` — read OKL v1 logs back into
  Python objects.
- :class:`SessionLog` / :class:`SessionMeta` / :class:`PhaseMarker` —
  typed views over a parsed log.

Driving a session is *not* this package's responsibility — see
``session-runner``. Hardware orchestration is *not* either — see
``experiment-io``.
"""

from __future__ import annotations

from experiment_core import SessionMeta

from .format import (
    CANONICAL_CODEBOOK,
    EVENT_TYPE_COMPONENT_CHANGE,
    EVENT_TYPE_PHASE_ENTER,
    EVENT_TYPE_PHASE_EXIT,
    EVENT_TYPE_REINFORCER_END,
    EVENT_TYPE_REINFORCER_START,
    EVENT_TYPE_RESPONSE,
    EVENT_TYPE_STATE_CHANGE,
    HEADER_TERMINATOR,
    MAGIC,
    PHASE_RECORD_TYPES,
    Field,
    ParsedHeader,
    ParsedRecord,
    encode_event,
    encode_phase_enter,
    encode_phase_exit,
    materialise,
    parse_event_line,
    parse_header,
    write_header,
)
from .reader import (
    OnUnknown,
    PhaseMarker,
    SessionLog,
    iter_records,
    read_log,
)
from .sink import OklSink

__version__ = "0.0.0"
__all__ = [
    "CANONICAL_CODEBOOK",
    "EVENT_TYPE_COMPONENT_CHANGE",
    "EVENT_TYPE_PHASE_ENTER",
    "EVENT_TYPE_PHASE_EXIT",
    "EVENT_TYPE_REINFORCER_END",
    "EVENT_TYPE_REINFORCER_START",
    "EVENT_TYPE_RESPONSE",
    "EVENT_TYPE_STATE_CHANGE",
    "Field",
    "HEADER_TERMINATOR",
    "MAGIC",
    "PHASE_RECORD_TYPES",
    "OnUnknown",
    "OklSink",
    "ParsedHeader",
    "ParsedRecord",
    "PhaseMarker",
    "SessionLog",
    "SessionMeta",
    "__version__",
    "encode_event",
    "encode_phase_enter",
    "encode_phase_exit",
    "iter_records",
    "materialise",
    "parse_event_line",
    "parse_header",
    "read_log",
    "write_header",
]
