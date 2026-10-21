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
- **MED-PC importer** (`session_recorder.medpc`) — reads MED-PC IV / V
  data files (FORMAT 1 Annotated, FORMAT 4 Stripped with Variable
  Identification) and writes them as OKL v1 logs.
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

## 30-second example

Write a short FR 3 session to an OKL v1 file and read it back as typed events:

```python
from experiment_core import ReinforcerEndEvent, ReinforcerStartEvent, ResponseEvent
from session_recorder import OklSink, read_log

sink = OklSink("fr3.okl")
sink.write_header(session_name="demo", clock_type="VirtualClock", session_start=0.0,
                  metadata={"dsl": "FR 3"})
for i, t in enumerate([1.0, 2.0, 3.0], start=1):
    sink.emit(ResponseEvent(id=i, timestamp=t))
sink.emit(ReinforcerStartEvent(id=1, timestamp=3.0))
sink.emit(ReinforcerEndEvent(id=1, timestamp=6.0))  # 3-s reinforcer access

print(open("fr3.okl", encoding="utf-8").read().split("# ---\n")[1], end="")
# 1.0	response	1	-
# 2.0	response	2	-
# 3.0	response	3	-
# 3.0	reinforcer_start	1	1.0	-
# 6.0	reinforcer_end	1	-

log = read_log("fr3.okl")
print(log.meta.session_name, log.meta.metadata, [type(e).__name__ for e in log.events][-2:])
# demo {'dsl': 'FR 3'} ['ReinforcerStartEvent', 'ReinforcerEndEvent']
```

The file starts with a commented header (session name, clock, metadata, and a codebook that declares each event type and its columns) followed by one tab-separated line per event, so `grep` and `awk` work on it directly. In a real session the events come from [session-runner](https://github.com/OperantKit/session-runner) (`pip install session-runner`): pass `OklSink` as its `sink`, or combine it with other sinks through `tee`.

## Why not a 50-line hand-written logger?

A CSV writer or `json.dumps` per event loses what makes a session log reusable:

- **Self-describing files.** The header carries the session name, clock type, start time, free-form metadata (for example the DSL source), and a codebook of event types with typed columns; a reader does not need this package to interpret the body.
- **Round trip to typed events.** `read_log` / `iter_records` turn each line back into the `experiment_core` event classes (`ResponseEvent`, `ReinforcerStartEvent`, ...), including the operandum and reinforcer potency.
- **Unknown events are handled explicitly.** Event types not in the codebook are warned about, skipped, or raised as errors (`on_unknown="warn" | "skip" | "error"`) instead of being misparsed.
- **Escaping and absent values.** Tabs, newlines, and backslashes in string columns are escaped, and a missing optional value is written as `-`, so every line has a fixed number of columns.
- **Header written once, at byte 0.** `OklSink` refuses to write a second header or to prepend a header to a non-empty file, and refuses events before the header.
- **Phase markers.** `write_phase_enter` / `write_phase_exit` label baseline, extinction, and test phases inside one log.
- **Specified format.** The format is defined in [OperantKitLog](https://github.com/OperantKit/OperantKitLog) (grammar, header, codebook, wire format) with 10 valid and invalid conformance files that this package's tests parse.

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

### Importing MED-PC data

```python
from pathlib import Path

from session_recorder import read_log
from session_recorder.medpc import medpc_to_okl, read_medpc

Path("JL4.txt").write_text(  # a MED-PC FORMAT 1 (Annotated) file
    "Start Date: 08/19/24\nEnd Date: 08/19/24\nSubject: JL4\nExperiment: VDRL\n"
    "Group: 1\nBox: 4\nStart Time:  9:51:02\nEnd Time: 11:08:00\nMSN: Training\n"
    "A:\n     0:  0.000  270000.000  60.000  3.000  30.000\n"
    "C:\n     0:  0.111  2742.200  5763.400  27000.999\n"
)
for i, session in enumerate(read_medpc("JL4.txt")):
    result = medpc_to_okl(session, f"session_{i}.txt")  # protocol guessed from MSN
    assert result.primary + sum(result.unmapped.values()) == result.source_events

log = read_log("session_0.txt")
print(log.meta.metadata["schedule.spec_dsl"], [type(e).__name__ for e in log.events])
# VI 30s ['StateChangeEvent', 'ResponseEvent', 'ReinforcerStartEvent', 'StateChangeEvent']
```

A MED-PC file does not say what its event codes mean; the MSN program
does. `medpc_to_okl` therefore takes a `protocol` naming one of
`session_recorder.medpc.PROTOCOLS`. Built-in protocols cover three
public datasets whose programs are published (`bernardy-vdrl`,
`bernardy-training`, `sosa-inh`, `mccutcheon-prpr`); annotated files are
matched by their `MSN:` line, FORMAT 4 files need `protocol=` because
they carry no MSN name. To read another program, write a function that
turns a `MedPcSession` into a `Converted` and register it as a
`Protocol`.

Each source event becomes one body line or is counted as unmapped
(`medpc.unmapped_codes` in the header); lines the converter adds, such
as a session start the file does not record, are counted in
`medpc.synthesised_lines`. Food-cup entries and exits are written as the
extension types `head_entry` / `head_exit`; `read_log` keeps them in
`raw_records` and leaves them out of `events`.

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
