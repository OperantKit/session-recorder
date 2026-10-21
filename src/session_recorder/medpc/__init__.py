"""Import MED-PC data files into OKL v1.

``read_medpc(path)`` parses a MED-PC IV / V file (FORMAT 1 Annotated or
FORMAT 4 Stripped with Variable Identification) into
:class:`MedPcSession` objects; ``medpc_to_okl(session, out_path,
protocol=...)`` writes one session as an OKL v1 log using a
:class:`Protocol` that gives the MSN program's event codes their
meaning.
"""

from __future__ import annotations

from .parse import MedPcSession, read_medpc, split_code
from .to_okl import (
    EVENT_TYPE_HEAD_ENTRY,
    EVENT_TYPE_HEAD_EXIT,
    MEDPC_CODEBOOK,
    PROTOCOLS,
    Converted,
    Protocol,
    Row,
    guess_protocol,
    medpc_to_okl,
)

__all__ = [
    "EVENT_TYPE_HEAD_ENTRY",
    "EVENT_TYPE_HEAD_EXIT",
    "MEDPC_CODEBOOK",
    "PROTOCOLS",
    "Converted",
    "MedPcSession",
    "Protocol",
    "Row",
    "guess_protocol",
    "medpc_to_okl",
    "read_medpc",
    "split_code",
]
