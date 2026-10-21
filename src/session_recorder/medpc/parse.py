"""Parse MED-PC IV / V data files.

Two of the four disk formats described in Appendix F of the MED-PC IV
User's Manual (Med Associates, DOC-010) are supported:

- **FORMAT 1, Annotated** — ``File:`` line, labelled header
  (``Start Date:`` ... ``MSN:``), simple variables as ``X: value`` in
  alphabetical order, arrays as ``X:`` followed by ``<index>: v v v``
  rows. A file may hold several sessions; each starts at ``Start Date:``.
- **FORMAT 4, Stripped with Variable Identification** — one value per
  line: 16 header lines, the number of simple variables, the number of
  arrays, a ``.3`` marker, the 26 element counts for A..Z, then the
  values of A..Z in order. Sessions may follow one another.

FORMAT 2 / 3 (stripped without identification) and the CONDENSED header
are rejected with :class:`ValueError`: the variable letters cannot be
recovered without the MSN program.

Values are kept as the text MED-PC wrote. Event codes are usually
packed into the fractional part (``3829.678`` = tick 3829, code
``678``); converting to float first would merge codes such as ``.1``
and ``.11`` under rounding, so use :func:`split_code` on the text.
"""

from __future__ import annotations

import re
from collections.abc import Sequence
from dataclasses import dataclass, field
from pathlib import Path
from typing import Final, Literal

MedPcFormat = Literal["annotated", "stripped-varid"]

LETTERS: Final = tuple("ABCDEFGHIJKLMNOPQRSTUVWXYZ")

_HEADER_LABELS: Final = {
    "Start Date": "start_date",
    "End Date": "end_date",
    "Subject": "subject",
    "Experiment": "experiment",
    "Group": "group",
    "Box": "box",
    "Start Time": "start_time",
    "End Time": "end_time",
    "MSN": "msn",
}

_VAR_RE: Final = re.compile(r"^([A-Z]):\s*(\S*)\s*$")
_ROW_RE: Final = re.compile(r"^\s*(\d+):\s*(.*)$")
_HEADER_RE: Final = re.compile(
    r"^(Start Date|End Date|Subject|Experiment|Group|Box|Start Time|End Time|MSN):(.*)$"
)


@dataclass(frozen=True)
class MedPcSession:
    """One session read from a MED-PC data file.

    Attributes
    ----------
    format:
        ``"annotated"`` (FORMAT 1) or ``"stripped-varid"`` (FORMAT 4).
    header:
        Header fields as text, keyed ``file`` (FORMAT 1 only),
        ``start_date``, ``end_date``, ``subject``, ``experiment``,
        ``group``, ``box``, ``start_time``, ``end_time``, ``msn``
        (FORMAT 1 only). Dates are ``M/D/YY``, times ``H:MM:SS``.
    scalars:
        Simple variables, letter -> value text.
    arrays:
        Arrays, letter -> tuple of value text. In FORMAT 4 every letter
        with more than one element is an array; a one-element array is
        indistinguishable from a simple variable and appears in
        ``scalars``.
    source:
        Path the session was read from.
    """

    format: MedPcFormat
    header: dict[str, str]
    scalars: dict[str, str]
    arrays: dict[str, tuple[str, ...]]
    source: Path
    declared: dict[str, int] = field(default_factory=dict)


def split_code(token: str) -> tuple[int, str]:
    """Split ``"3829.678"`` into ``(3829, "678")``.

    The code is the fractional digits as written (``DISKFORMAT`` decides
    how many). Values without a fractional part return code ``""``.
    """
    text = token.strip()
    if text.startswith("-"):
        raise ValueError(f"negative value cannot carry an event code: {token!r}")
    whole, _, frac = text.partition(".")
    return int(whole or "0"), frac


def read_medpc(path: str | Path) -> list[MedPcSession]:
    """Read every session in a MED-PC FORMAT 1 or FORMAT 4 data file."""
    p = Path(path)
    # MED-PC writes ASCII; latin-1 never fails on stray bytes.
    lines = p.read_text(encoding="latin-1").splitlines()
    content = [ln.strip() for ln in lines if ln.strip()]
    if not content:
        raise ValueError(f"{p}: empty MED-PC file")
    first = content[0]
    if first.startswith("File:") or first.startswith("Start Date:"):
        return _parse_annotated(lines, p)
    if first.upper().startswith("BOX:"):
        raise ValueError(f"{p}: CONDENSED MED-PC header is not supported")
    if _is_number(first):
        return _parse_stripped_varid([ln.strip() for ln in lines], p)
    raise ValueError(f"{p}: not a recognised MED-PC data file (first line {first!r})")


def _is_number(text: str) -> bool:
    try:
        float(text)
    except ValueError:
        return False
    return True


# --------------------------------------------------------------------------- #
# FORMAT 1
# --------------------------------------------------------------------------- #


class _Builder:
    def __init__(self, file_line: str | None) -> None:
        self.header: dict[str, str] = {}
        if file_line is not None:
            self.header["file"] = file_line
        self.scalars: dict[str, str] = {}
        self.arrays: dict[str, list[str]] = {}
        self.current: str | None = None

    def build(self, source: Path) -> MedPcSession:
        return MedPcSession(
            format="annotated",
            header=dict(self.header),
            scalars=dict(self.scalars),
            arrays={k: tuple(v) for k, v in self.arrays.items()},
            source=source,
        )


def _parse_annotated(lines: Sequence[str], source: Path) -> list[MedPcSession]:
    sessions: list[MedPcSession] = []
    file_line: str | None = None
    b = _Builder(None)
    for lineno, raw in enumerate(lines, start=1):
        line = raw.strip()
        if not line or line.startswith("\\"):
            continue
        if line.startswith("File:"):
            file_line = line[len("File:") :].strip()
            b.header["file"] = file_line
            continue
        hm = _HEADER_RE.match(line)
        if hm:
            label, value = hm.group(1), hm.group(2).strip()
            if label == "Start Date" and ("start_date" in b.header or b.scalars or b.arrays):
                sessions.append(b.build(source))
                b = _Builder(file_line)
            b.header[_HEADER_LABELS[label]] = value
            b.current = None
            continue
        vm = _VAR_RE.match(line)
        if vm:
            letter, value = vm.group(1), vm.group(2)
            if value:
                b.scalars[letter] = value
                b.current = None
            else:
                b.arrays[letter] = []
                b.current = letter
            continue
        rm = _ROW_RE.match(raw)
        if rm and b.current is not None:
            index = int(rm.group(1))
            values = b.arrays[b.current]
            if index != len(values):
                raise ValueError(
                    f"{source}:{lineno}: array {b.current} row starts at {index}, "
                    f"expected {len(values)}"
                )
            values.extend(rm.group(2).split())
            continue
        raise ValueError(f"{source}:{lineno}: unexpected line {line!r}")
    if "start_date" not in b.header:
        raise ValueError(f"{source}: no 'Start Date:' header found")
    sessions.append(b.build(source))
    return sessions


# --------------------------------------------------------------------------- #
# FORMAT 4
# --------------------------------------------------------------------------- #

_STRIPPED_HEADER: Final = (
    "start_month",
    "start_day",
    "start_year",
    "end_month",
    "end_day",
    "end_year",
    "subject",
    "experiment",
    "group",
    "box",
    "start_hour",
    "start_minute",
    "start_second",
    "end_hour",
    "end_minute",
    "end_second",
)


def _parse_stripped_varid(values: Sequence[str], source: Path) -> list[MedPcSession]:
    sessions: list[MedPcSession] = []
    pos = 0
    while True:
        # Blank lines may separate sessions; inside a session every line
        # counts (an empty Subject is still one line).
        while pos < len(values) and not values[pos]:
            pos += 1
        if pos >= len(values):
            break
        if len(values) - pos < 45:
            raise ValueError(f"{source}: truncated FORMAT 4 session at value {pos + 1}")
        head = dict(zip(_STRIPPED_HEADER, values[pos : pos + 16], strict=True))
        n_scalars = int(float(values[pos + 16]))
        n_arrays = int(float(values[pos + 17]))
        marker = values[pos + 18]
        if not _is_number(marker) or float(marker) != 0.3:
            raise ValueError(
                f"{source}: no '.3' marker at line {pos + 19}; FORMAT 2 / 3 "
                "(stripped without variable identification) is not supported"
            )
        if n_scalars + n_arrays != 26:
            raise ValueError(f"{source}: {n_scalars} simple variables + {n_arrays} arrays != 26")
        counts = [int(float(v)) for v in values[pos + 19 : pos + 45]]
        pos += 45
        scalars: dict[str, str] = {}
        arrays: dict[str, tuple[str, ...]] = {}
        for letter, count in zip(LETTERS, counts, strict=True):
            chunk = tuple(values[pos : pos + count])
            if len(chunk) != count:
                raise ValueError(f"{source}: variable {letter} truncated")
            pos += count
            if count == 1:
                scalars[letter] = chunk[0]
            else:
                arrays[letter] = chunk
        header = {
            "start_date": f"{head['start_month']}/{head['start_day']}/{head['start_year']}",
            "end_date": f"{head['end_month']}/{head['end_day']}/{head['end_year']}",
            "subject": head["subject"],
            "experiment": head["experiment"],
            "group": head["group"],
            "box": head["box"],
            "start_time": f"{head['start_hour']}:{head['start_minute']}:{head['start_second']}",
            "end_time": f"{head['end_hour']}:{head['end_minute']}:{head['end_second']}",
        }
        sessions.append(
            MedPcSession(
                format="stripped-varid",
                header=header,
                scalars=scalars,
                arrays=arrays,
                source=source,
                declared={"scalars": n_scalars, "arrays": n_arrays},
            )
        )
    return sessions
