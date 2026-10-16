# session-recorder

:jp: [日本語版 README](README.ja.md)

OKL v1 event format definition + writer/reader for OperantKit session
events.

## Role

`session-recorder` owns the canonical **wire format** for session
event persistence (the [OKL v1 schema](docs/en/format.md)), and a
Python **writer** + **reader** for that format. It does **not** drive
sessions, poll hardware, or parse a DSL — those concerns live
elsewhere:

| Concern | Package |
|---|---|
| Session lifecycle (events) | `experiment-core` |
| Driving a session (manual API) | `session-runner` |
| HAL Protocols + driving from hardware | `experiment-io` |
| DSL parsing | `contingency-dsl-py` |
| Schedule runtime | `contingency-py` |
| End-to-end CLI glue | `operantkit-cli` |

## Responsibilities

- **`OklSink`** — implements the
  `experiment_core.EventSink` Protocol; writes the OKL v1 header
  exactly once and then appends one TSV body line per emitted event.
- **`read_log` / `iter_records`** — read OKL v1 logs back into typed
  Python objects, with configurable handling of unknown event types
  (`on_unknown="warn" | "skip" | "error"`).
- **Format module** (`session_recorder.format`) — the source-of-truth
  serialiser/deserialiser between `experiment_core.SessionEvent` and
  the OKL v1 wire format.
- **Format docs** ([`docs/en/format.md`](docs/en/format.md)) —
  language-agnostic schema reference. Future Rust / TypeScript readers
  should match this byte-for-byte.

## Installation

```bash
pip install session-recorder
```

For development:

```bash
mise exec -- python -m venv .venv
mise exec -- .venv/bin/python -m pip install -e ../experiment-core
mise exec -- .venv/bin/python -m pip install -e '.[dev]'
```

`experiment-core` is path-installed to resolve the local dependency.

## Quick start

### Writing

```python
from session_recorder import OklSink
from experiment_core import ResponseEvent

sink = OklSink("session.txt")
sink.write_header(
    session_name="demo",
    clock_type="ManualClock",
    session_start=0.0,
    metadata={"dsl": "FR3"},
)
sink.emit(ResponseEvent(id=1, timestamp=0.5))
```

`OklSink` satisfies the `experiment_core.EventSink` Protocol so it
can be handed to any producer that emits session events (e.g. a
`session-runner.SessionRunner`).

### Reading

```python
from session_recorder import read_log

log = read_log("session.txt")
print(log.meta.session_name)
for event in log.events:
    print(event)
```

`session.txt` is plain UTF-8; `less`, `grep`, `awk` and Notepad open
it without preprocessing:

```bash
column -t -s $'\t' < session.txt
grep '^[0-9]' session.txt | awk -F'\t' '$2=="response"' | wc -l
```

## Development

```bash
.venv/bin/pytest
.venv/bin/pytest --cov=src --cov-report=term-missing
.venv/bin/ruff check src tests
.venv/bin/black --check src tests
```

## Format reference

See [`docs/en/format.md`](docs/en/format.md) for the OKL v1 schema.

## References

- Ferster, C. B., & Skinner, B. F. (1957). *Schedules of reinforcement*.
  Appleton-Century-Crofts.
