# session-recorder

:jp: [日本語版 README](README.ja.md)

session-recorder saves the events of an operant session (responses, reinforcer deliveries, state changes, phases) to a plain-text log file and reads such files back into Python. It is for anyone who runs sessions with [OperantKit](https://github.com/OperantKit) and wants a session record that people and programs can both read. In OperantKit it sits between the program that runs a session ([session-runner](https://github.com/OperantKit/session-runner)) and the analysis ([session-analyzer](https://github.com/OperantKit/session-analyzer)).

- **One file per session that you can read in a text editor.** A short header, then one tab-separated line per event.
- **The file describes itself.** The header names the session, the clock, any notes, and declares every event type with typed columns.
- **Old MED-PC data can join in.** MED-PC IV / V data files convert to the same format.

The log format is called OKL (OperantKitLog). Its specification is in the [OperantKitLog](https://github.com/OperantKit/OperantKitLog) repository; notes for AI coding agents are in [AGENTS.md](AGENTS.md).

## Installation

Python 3.11 or newer. session-recorder is not on PyPI yet, so `pip install session-recorder` does not work today. Install it and the OperantKit packages it needs from GitHub without dependency resolution:

```bash
G=git+https://github.com/OperantKit
pip install --no-deps $G/contingency-dsl-py $G/contingency-py $G/experiment-core $G/session-recorder
```

No third-party libraries are needed. `pip check` reports version mismatches between these development builds; they do not affect the examples below.

## Example

Write a short FR 3 session (one reinforcer after the third response) to a log file and read it back:

```python
from experiment_core import ReinforcerEndEvent, ReinforcerStartEvent, ResponseEvent
from session_recorder import OklSink, read_log

sink = OklSink("fr3.txt")
sink.write_header(session_name="demo", clock_type="VirtualClock", session_start=0.0,
                  metadata={"dsl": "FR 3"})
for i, t in enumerate([1.0, 2.0, 3.0], start=1):
    sink.emit(ResponseEvent(id=i, timestamp=t))
sink.emit(ReinforcerStartEvent(id=1, timestamp=3.0))
sink.emit(ReinforcerEndEvent(id=1, timestamp=6.0))  # 3-s reinforcer access

log = read_log("fr3.txt")
print(log.meta.session_name, log.meta.metadata, [type(e).__name__ for e in log.events])
# demo {'dsl': 'FR 3'} ['ResponseEvent', 'ResponseEvent', 'ResponseEvent', 'ReinforcerStartEvent', 'ReinforcerEndEvent']
```

The file `fr3.txt` it writes:

```text
# OKL v1
# session_name = "demo"
# clock_type = "VirtualClock"
# session_start = 0.0
# meta:
#   dsl = "FR 3"
# events:
#   response          : id:int operandum:int?
#   reinforcer_start  : id:int potency:float operandum:int?
#   reinforcer_end    : id:int operandum:int?
#   state_change      : from:str to:str
#   component_change  : from:str to:str
#   phase_enter       : label:str name:str? time:str? location:str? cue:str?
#   phase_exit        : label:str
# ---
1.0	response	1	-
2.0	response	2	-
3.0	response	3	-
3.0	reinforcer_start	1	1.0	-
6.0	reinforcer_end	1	-
```

Each body line is a time in seconds, the event type, and the columns the header declares for it; `-` marks an empty optional column (here, no operandum, the lever or key the response was made on). Standard tools work on it directly:

```bash
grep -v '^#' fr3.txt | awk -F'\t' '$2 == "response"' | wc -l   # 3
```

In a real session the events come from [session-runner](https://github.com/OperantKit/session-runner): pass an `OklSink` as its `sink`.

## What is inside

- **`OklSink`** writes the header once, at the start of an empty file, then one line per event. It refuses a second header and events before the header. `write_phase_enter` / `write_phase_exit` mark baseline, extinction, or test phases inside one log. It implements the `EventSink` protocol of [experiment-core](https://github.com/OperantKit/experiment-core), so any OperantKit program that emits session events can write through it.
- **`read_log` / `iter_records`** read a log back as typed `experiment_core` events. Event types missing from the header are warned about, skipped, or raised as errors (`on_unknown="warn" | "skip" | "error"`).
- **`session_recorder.format`** is the source-of-truth serialiser between `experiment_core.SessionEvent` and the OKL v1 wire format.
- **`session_recorder.medpc`** converts MED-PC IV / V data files (FORMAT 1 Annotated, FORMAT 4 Stripped with Variable Identification) to OKL logs.
- **[Format reference](docs/en/format.md):** session-recorder owns the canonical wire format for session event persistence; this page is its language-agnostic schema reference.

### Converting MED-PC data

A MED-PC data file does not say what its event codes mean; the MSN program that wrote it does. `medpc_to_okl` therefore takes a protocol, one of `session_recorder.medpc.PROTOCOLS`. The four built-in protocols (`bernardy-vdrl`, `bernardy-training`, `sosa-inh`, `mccutcheon-prpr`) cover the published programs of three public datasets (Bernardy, 2025; McCutcheon, 2022; Sosa et al., 2026). Annotated files are matched to a protocol by their `MSN:` line; FORMAT 4 files carry no program name and need `protocol=`.

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

Every source event becomes one line or is counted as unmapped (`medpc.unmapped_codes` in the header); lines the converter adds, such as a session start the file does not record, are counted in `medpc.synthesised_lines`. To read another MSN program, write a function that turns a `MedPcSession` into a `Converted` and register it as a `Protocol`.

## Limitations

- Python only. Readers in other languages have to be written against the [OperantKitLog](https://github.com/OperantKit/OperantKitLog) specification.
- One session per file; OKL does not concatenate sessions in one file.
- The MED-PC importer reads only programs with a protocol. Food-cup entries and exits from those programs are written as the extension types `head_entry` / `head_exit`; `read_log` keeps them in `raw_records`, not in `events`.

## Development

```bash
python -m venv .venv
.venv/bin/python -m pip install -e ".[dev]"
.venv/bin/pytest
```

Every `python` block in this README and `README.ja.md` is run by `tests/test_readme_examples.py`.

## References

- Bernardy, J. L. (2025). *Supplemental material: Feedback function and performance on variable differential reinforcement of low rates: Tempus urgit vel abundat?* [Data set]. Harvard Dataverse. https://doi.org/10.7910/DVN/BXVB2F
- McCutcheon, J. (2022). *Progressive ratio in protein-restricted vs. non-restricted rats* [Data set]. Zenodo. https://doi.org/10.5281/zenodo.5409201
- Sosa, R., Mata-Luévanos, J., Tapia-de-Jesús, A., Saavedra, P., & Buenrostro-Jáuregui, M. (2026). *Longitudinal association between different indices of behavioral inhibition* [Data set]. Zenodo. https://doi.org/10.5281/zenodo.19164959

## License

MIT. See [LICENSE](LICENSE).
