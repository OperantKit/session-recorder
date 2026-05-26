# OKL v1 — OperantKitLog v1

This document is the canonical specification of the wire format that
`session-recorder` writes and reads. It is **language-agnostic**: any
implementation (Python / Rust / TypeScript / ...) that produces or
consumes session logs must conform to this schema byte-for-byte.

## Why a new format

The previous wire format (JSONL) was inherited from the first
implementation and was never compared against alternatives. OKL v1 is
the result of a from-scratch redesign that targets three audiences in
one file:

- **Bench researchers** opening output in Notepad / `less` / `grep`
  during a wet-lab run.
- **Pipeline authors** writing Python / Rust readers for downstream
  analysis (`session-analyzer`, `aba-advisor`, `session-visualizer`, ...).
- **HIL benchmark engineers** appending ms-resolution events from a hot
  path with crash-safe semantics.

OKL v1 wins against JSONL on **human readability**, **bare-tool
opening** (Windows clean-install Notepad opens `.txt` out of the box),
and **schema evolution + self-description** (the codebook is embedded
in the file header), at the cost of slightly higher per-line redundancy
that gzip recovers.

## File layout

A session log is a **UTF-8 text file** with the `.txt` extension. The
file consists of three parts in order:

1. **Magic line** — exactly `# OKL v1` followed by `\n`.
2. **Header block** — one or more `#`-prefixed lines, terminated by a
   single `# ---` line.
3. **Body** — one TAB-separated event line per record.

Newlines are **LF (`\n`)** when written. Readers must additionally
accept CRLF (`\r\n`) and SHOULD strip any trailing `\r` before
parsing. There is **no BOM**: writers MUST NOT emit one and readers
MUST reject a file whose first line begins with `U+FEFF` with an
explicit error rather than the generic "magic mismatch".

## Header

The header carries:

- `# session_name = "<basic-string>"` — required producer label.
- `# clock_type = "<basic-string>"` — required clock identifier.
- `# session_start = <number>` — required session-start timestamp
  (seconds in the producer's clock).
- Optional top-level keys (mirror `experiment_core.SessionMeta`):
  - `# subject_id = "<str>"`
  - `# replication_index = <int>`
  - `# experiment_name = "<str>"`
  - `# protocol_id = "<str>"`
  - `# task_file_hash = "<str>"`
  - `# wall_clock_start = "<ISO-8601 datetime>"` — recommended timezone-aware.
- Optional `# notes:` block, followed by `#   "<note>"` lines —
  free-form post-hoc annotations recorded by the experimenter.
- Optional `# meta:` block, followed by `#   <key> = <value>` lines.
  Free-form metadata. Keys may contain dots for namespacing
  (e.g. `subject.weight_g = 320`).
- Required `# events:` block, followed by `#   <type-name>          : <field>...` lines
  declaring the **codebook**: which event types this file may contain
  and what the positional payload columns mean for each.

A reader that encounters an **unknown** top-level key MUST preserve it
under `metadata` (so the file round-trips) and SHOULD emit a warning
once. This is forward-compatible: spec extensions can add new keys
without breaking older readers.

Header values use TOML basic-string / number / bool literals:

- `"text"` — UTF-8 string with `\` `\"` `\n` `\r` `\t` escapes.
- `42` — integer.
- `3.14` / `1e6` — float.
- `true` / `false` — bool.

### Codebook field syntax

Each entry in `# events:` has the form

```
<type-name>          : <field>:<ty>[?] <field>:<ty>[?] ...
```

where `<ty>` is one of `int`, `float`, `str`, `bool` and a `?` suffix
declares the field optional. Optional fields, when absent, are written
as a single `-` in the body.

### Canonical codebook

Writers MUST emit at least the following types in the codebook (extras
are permitted):

```
# events:
#   response          : id:int
#   reinforcer_start  : id:int potency:float operandum:int?
#   reinforcer_end    : id:int operandum:int?
#   state_change      : from:str to:str
#   component_change  : from:str to:str
#   phase_enter       : label:str name:str? time:str? location:str? cue:str?
#   phase_exit        : label:str
```

## Body

Body lines are pure TSV — no JSON, no quoting, no escaping beyond TSV
conventions. Each line has at least two columns: `timestamp` and `type`,
followed by the per-type payload columns declared in the codebook in
the **same order**.

```
<timestamp>\t<type>\t<col1>\t<col2>\t...
```

Strings are TSV-escaped:

| Literal       | On the wire |
|---------------|-------------|
| `\` (backslash) | `\\`      |
| `\t` (tab)    | `\t`        |
| `\n` (newline)| `\n`        |
| `\r`          | `\r`        |
| `-` (alone)   | `\-`        |

The bare token `-` in any column means "absent" and is permitted only
where the codebook declares the field optional. To write a literal
single-character `-`, the producer escapes it as `\-`.

A reader encountering an **undefined** escape sequence (e.g. `\q`) MUST
preserve it verbatim (i.e. emit `\q` as the two-character output). This
forward-compat hedge lets future spec versions add escapes without
breaking older readers; producers MUST NOT rely on this leniency to
smuggle non-canonical encodings.

### Examples

```
# OKL v1
# session_name = "demo"
# clock_type = "ManualClock"
# session_start = 0.0
# subject_id = "rat-001"
# experiment_name = "fr_baseline"
# wall_clock_start = "2026-04-27T14:03:11+09:00"
# notes:
#   "operator note"
# meta:
#   dsl = "FR3"
# events:
#   response          : id:int
#   reinforcer_start  : id:int potency:float operandum:int?
#   reinforcer_end    : id:int operandum:int?
#   state_change      : from:str to:str
#   component_change  : from:str to:str
#   phase_enter       : label:str name:str? time:str? location:str? cue:str?
#   phase_exit        : label:str
# ---
0.0	state_change	IDLE	RUNNING
0.523	response	1
1.014	response	2
1.502	response	3
1.502	reinforcer_start	1	1.0	0
2.002	reinforcer_end	1	0
```

`column -t -s $'\t' < session.txt` produces a perfectly aligned table.
`grep '^[0-9]' session.txt | awk -F'\t' '$2=="response"' | wc -l`
returns the response count without preprocessing.

## Crash safety

The writer appends one body line at a time and flushes per write. A
crash mid-write leaves a torn final line that lacks a terminating `\n`.
Readers MUST treat the prefix up to the last fully-framed line as
canonical and ignore the torn fragment.

## Schema evolution

### Adding a new event type

Producers add a new entry to the `# events:` codebook. Readers that do
not know the new type rely on the `on_unknown` policy of the reference
reader (`"warn"` / `"skip"` / `"error"`); the default `"warn"` skips
the unknown lines and reports them once.

### Removing or renaming a type

This is a breaking change. Bump the magic to a future major version
when it happens; readers MUST refuse to parse a file whose magic
declares a higher major than they understand.

### Adding a column to an existing type

This is also breaking — old readers will compute the wrong column
count. Either bump the magic or introduce a new event type.

## Conformance

A round-trip test for any reader implementation: write each event type
through `OklSink`, parse the resulting file, and check that the
resulting in-memory event objects compare equal to the originals. The
Python reference implementation's
`tests/test_format.py::test_*_round_trip` exercises this.

Additionally, conforming readers MUST:

- Accept both LF and CRLF line endings.
- Skip blank body lines.
- Reject files whose first line is not exactly `# OKL v1`.
- Reject lines whose `type` is not declared in the codebook
  (subject to the `on_unknown` policy).
- Treat a torn final line (missing `\n`) as discardable.

## Filename convention

Producers SHOULD use the `.txt` extension. Suggested base name:
`<session_name>.<YYYYMMDD>.txt` or `<subject_id>.<session_name>.txt`.
Multiple sessions go in multiple files; OKL v1 does not support
in-file session concatenation.
