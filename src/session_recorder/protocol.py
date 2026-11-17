"""The :class:`EventSink` Protocol.

Anything that accepts session events as they are emitted satisfies it:
:class:`session_recorder.OklSink` writes them to an OKL v1 file; a
session engine (``experiment-core``) hands events to any sink it is
given.
"""

from __future__ import annotations

from typing import Protocol, runtime_checkable

from .events import SessionEvent


@runtime_checkable
class EventSink(Protocol):
    """Accepts session events as they are emitted."""

    def emit(self, event: SessionEvent) -> None:  # pragma: no cover
        ...
