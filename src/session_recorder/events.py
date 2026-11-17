"""Session event dataclasses, the :data:`SessionEvent` union, and
:class:`SessionMeta`.

These are the record types that OKL v1 (OperantKitLog v1) writes; this
package owns them so that writing or reading a log does not pull in a
session engine. All time values are canonical seconds (float).

The role-named types (:class:`ReinforcerStartEvent`,
:class:`ReinforcerEndEvent`, ``SessionState.REINFORCING``) are the
frozen legacy of OKL v1. New record types added here carry no theory's
role name: a stimulus presentation is written with
:meth:`session_recorder.OklSink.write_stimulus_on` /
:meth:`~session_recorder.OklSink.write_stimulus_off`.
"""

from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from typing import Any


class SessionState(Enum):
    """Lifecycle states of a session (driven by ``experiment-core``'s ``Session``)."""

    IDLE = 0
    RUNNING = 1
    REINFORCING = 2
    PAUSED = 3
    FINISHED = 4


@dataclass
class ResponseEvent:
    """A single subject response.

    ``operandum`` distinguishes which key/lever produced the response in
    multi-operandum schedules (concurrent or multiple). ``None`` is the
    convention for single-operandum sessions.

    ``timestamp`` is the session time: the clock the schedule, the
    reinforcer events and the exit conditions run on. ``device_time``
    is the time the apparatus itself stamped on the response, kept for
    the record only (it does not drive the schedule). ``None`` means
    the source has no clock of its own (virtual subjects, manual input).
    """

    id: int
    timestamp: float
    operandum: int | None = None
    device_time: float | None = None


@dataclass
class ReinforcerStartEvent:
    """Emitted when a reinforcer is scheduled for delivery.

    ``potency`` reflects the delay-discounted strength of the reinforcer at
    the moment of delivery.
    """

    id: int
    timestamp: float
    operandum: int | None = None
    potency: float = 1.0


@dataclass
class ReinforcerEndEvent:
    """Emitted when a reinforcer delivery completes."""

    id: int
    timestamp: float
    operandum: int | None = None


@dataclass
class StateChangeEvent:
    """Emitted when the session transitions between :class:`SessionState` values."""

    from_state: SessionState
    to_state: SessionState
    timestamp: float


@dataclass
class ComponentChangeEvent:
    """Emitted when a multiple-schedule component (or ICI) becomes active.

    Components are identified by string keys chosen by the producer
    (e.g. ``"C1"``, ``"C2"``, ``"ICI"``). The empty string for
    ``from_component`` is the canonical session-start convention; the
    final transition into a terminal phase may use the empty string for
    ``to_component``.

    This event is distinct from :class:`StateChangeEvent`: state-changes
    track the session lifecycle (``IDLE / RUNNING / REINFORCING / ...``),
    whereas component-changes track the discriminative-stimulus context
    that gates subject responding.
    """

    from_component: str
    to_component: str
    timestamp: float


SessionEvent = (
    ResponseEvent
    | ReinforcerStartEvent
    | ReinforcerEndEvent
    | StateChangeEvent
    | ComponentChangeEvent
)


@dataclass
class SessionMeta:
    """Canonical session metadata.

    Owns the *identity* (``subject_id`` / ``replication_index``),
    *protocol label* (``experiment_name`` / ``protocol_id`` /
    ``task_file_hash``), *wall-clock anchor* (``wall_clock_start``), and
    *post-hoc notes* of a single session. The ``timestamp`` field is the
    session origin in canonical seconds; ``wall_clock_start``, when
    provided, lets a consumer map ``timestamp == 0.0`` to a real
    datetime (``timezone``-aware values are recommended).

    ``notes`` is a list of free-form post-hoc annotations recorded by the
    experimenter after the session. It is **not** intended for real-time
    program-emitted messages — those should go through
    :class:`ResponseEvent` / :class:`ReinforcerStartEvent` / etc., or a
    future ``CustomEvent`` if domain-specific.

    ``metadata`` is a free-form bag for producer-supplied key/value
    pairs. Recommended keys (informal convention, not enforced):

    - ``schedule.spec_dsl`` (str): the contingency-DSL source string.
    - ``schedule.parameters`` (dict): structured schedule parameters.
    - ``operandum_labels`` (``dict[int, str]``): human names for the
      integer ``operandum`` indices used on response/reinforcer events
      (e.g. ``{0: "left", 1: "right"}``).
    - ``subject.{weight_g, deprivation_level, drug_condition, species}``.
    - ``apparatus.{device_id, chamber, firmware_version}``.

    Wire-format adapters are responsible for translating these fields to
    their respective serialisation conventions.
    """

    timestamp: float
    clock_type: str
    session_name: str
    subject_id: str | None = None
    replication_index: int | None = None
    experiment_name: str | None = None
    protocol_id: str | None = None
    task_file_hash: str | None = None
    wall_clock_start: datetime | None = None
    notes: list[str] = field(default_factory=list)
    metadata: dict[str, Any] = field(default_factory=dict)
