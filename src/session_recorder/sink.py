"""OKL v1 :class:`~experiment_core.EventSink` implementation.

:class:`OklSink` accepts :class:`~experiment_core.events.SessionEvent`
instances via :meth:`emit` and serialises each to a single TSV body
line using the OKL v1 wire format defined in
:mod:`session_recorder.format`. Files are opened append-mode and
flushed per event so every line that reaches disk is durable across
crashes.

The header (magic line + session metadata + event codebook) must be
written exactly once via :meth:`write_header` *before* the first
``emit()``. Phase markers are emitted via dedicated helpers since they
are not :class:`SessionEvent` instances.
"""

from __future__ import annotations

from datetime import datetime
from pathlib import Path
from typing import Any

from experiment_core import SessionEvent, SessionMeta

from .format import (
    encode_event,
    encode_phase_enter,
    encode_phase_exit,
    write_header,
)


class OklSink:
    """OKL v1 file sink.

    Implements the :class:`experiment_core.EventSink` Protocol: any
    caller that wants to fan out events to a file simply hands an
    :class:`OklSink` to the producer.

    Parameters
    ----------
    output_path:
        Destination ``.txt`` file. Parent directories are created on
        demand when the sink is constructed.
    """

    def __init__(self, output_path: str | Path) -> None:
        self.output_path = Path(output_path)
        parent = self.output_path.parent
        if str(parent) not in ("", "."):
            parent.mkdir(parents=True, exist_ok=True)
        self._lines: list[str] = []
        self._header_written = False

    @property
    def lines(self) -> list[str]:
        """In-memory mirror of every line this sink wrote (no trailing
        newlines), in emission order. Returns a fresh copy."""
        return list(self._lines)

    def write_header(
        self,
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
    ) -> None:
        """Write the OKL v1 magic + header + codebook + terminator.

        Must be called exactly once per file, before any
        :meth:`emit`-ted body line. Refuses to write into a file that
        already has any content on disk (the header MUST be at byte 0
        per the OKL v1 spec). The keyword-only fields mirror
        :class:`experiment_core.SessionMeta`; see also
        :meth:`write_header_from_meta` for a one-shot variant.
        """
        if self._header_written:
            raise RuntimeError("OKL v1 header already written")
        if self.output_path.exists() and self.output_path.stat().st_size > 0:
            raise RuntimeError(
                f"OKL v1 header must be at byte 0; {self.output_path} is non-empty. "
                "Write to a fresh path or truncate before re-running."
            )
        before = self._byte_offset()
        with self.output_path.open("a", encoding="utf-8", newline="") as f:
            write_header(
                f,
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
            )
        after = self._byte_offset()
        # Mirror only the bytes we just produced, decoded once.
        with self.output_path.open("rb") as f:
            f.seek(before)
            new_bytes = f.read(after - before)
        self._lines.extend(new_bytes.decode("utf-8").splitlines())
        self._header_written = True

    def write_header_from_meta(self, meta: SessionMeta) -> None:
        """Write the OKL v1 header from a :class:`SessionMeta` object."""
        self.write_header(
            session_name=meta.session_name,
            clock_type=meta.clock_type,
            session_start=meta.timestamp,
            subject_id=meta.subject_id,
            replication_index=meta.replication_index,
            experiment_name=meta.experiment_name,
            protocol_id=meta.protocol_id,
            task_file_hash=meta.task_file_hash,
            wall_clock_start=meta.wall_clock_start,
            notes=list(meta.notes) if meta.notes else None,
            metadata=dict(meta.metadata) if meta.metadata else None,
        )

    def _byte_offset(self) -> int:
        return self.output_path.stat().st_size if self.output_path.exists() else 0

    def emit(self, event: SessionEvent) -> None:
        """Serialise ``event`` and append it as one OKL v1 body line."""
        self._require_header()
        self._append(encode_event(event))

    def write_phase_enter(
        self,
        *,
        timestamp: float,
        label: str,
        context: dict[str, Any] | None = None,
    ) -> None:
        """Append a ``phase_enter`` body line."""
        self._require_header()
        self._append(encode_phase_enter(timestamp=timestamp, label=label, context=context))

    def write_phase_exit(self, *, timestamp: float, label: str) -> None:
        """Append a ``phase_exit`` body line."""
        self._require_header()
        self._append(encode_phase_exit(timestamp=timestamp, label=label))

    def _require_header(self) -> None:
        if not self._header_written:
            raise RuntimeError(
                "OklSink: write_header(...) must be called before emit()/write_phase_*()"
            )

    def _append(self, line: str) -> None:
        self._lines.append(line)
        with self.output_path.open("a", encoding="utf-8", newline="") as f:
            f.write(line + "\n")
