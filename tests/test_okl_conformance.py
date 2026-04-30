"""OKL v1 conformance test runner.

Drives the canonical golden fixtures in
``OperantKitLog/spec/conformance/`` through this package's parser to
ensure the Python implementation conforms to the spec.

The fixture directory is located relative to this test file by walking
up to the monorepo root. The location is intentionally not made
configurable: the spec is the single source of truth, and conformance
is a property of *that* fixture set, not of an arbitrary one a CI
operator might point at.

If the fixture directory is missing (e.g. this package is being built
in isolation outside the monorepo) the conformance runner is skipped.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from session_recorder.format import (
    CANONICAL_CODEBOOK,
    HEADER_TERMINATOR,
    MAGIC,
    parse_event_line,
    parse_header,
)


def _conformance_root() -> Path | None:
    """Locate ``OperantKitLog/spec/conformance/`` by walking up from this
    test file. Returns ``None`` if the spec is not co-located."""
    here = Path(__file__).resolve()
    for parent in here.parents:
        candidate = parent / "OperantKitLog" / "spec" / "conformance"
        if candidate.is_dir():
            return candidate
    return None


_CONFORMANCE_ROOT = _conformance_root()


def _fixtures(kind: str) -> list[Path]:
    if _CONFORMANCE_ROOT is None:
        return []
    return sorted((_CONFORMANCE_ROOT / kind).glob("*.txt"))


_VALID = _fixtures("valid")
_INVALID = _fixtures("invalid")


def _ids(paths: list[Path]) -> list[str]:
    return [p.name for p in paths]


@pytest.mark.skipif(
    _CONFORMANCE_ROOT is None,
    reason="OperantKitLog/spec/conformance/ not co-located with this package",
)
class TestOklConformance:
    @pytest.mark.parametrize("path", _VALID, ids=_ids(_VALID))
    def test_valid_fixture_parses(self, path: Path) -> None:
        text = path.read_text(encoding="utf-8")
        # Sanity: every conformance fixture (valid or invalid) starts
        # with the magic line.
        first_line = text.splitlines()[0] if text else ""
        assert first_line.startswith("# OKL"), (
            f"{path.name}: first line is not an OKL magic line: {first_line!r}"
        )

        lines = text.splitlines()
        header, consumed = parse_header(iter(lines))
        # Required keys are present (parse_header guarantees this).
        assert header.session_name
        assert header.clock_type is not None
        assert header.session_start is not None
        # Body lines parse against the file's own codebook.
        for line in lines[consumed:]:
            stripped = line.strip()
            if not stripped:
                continue
            parse_event_line(stripped, header.codebook)

    @pytest.mark.parametrize("path", _INVALID, ids=_ids(_INVALID))
    def test_invalid_fixture_rejected(self, path: Path) -> None:
        text = path.read_text(encoding="utf-8")
        lines = text.splitlines()

        with pytest.raises((ValueError, KeyError)):
            header, consumed = parse_header(iter(lines))
            for line in lines[consumed:]:
                stripped = line.strip()
                if not stripped:
                    continue
                parse_event_line(stripped, header.codebook)


@pytest.mark.skipif(
    _CONFORMANCE_ROOT is None,
    reason="OperantKitLog/spec/conformance/ not co-located with this package",
)
def test_conformance_directory_non_empty() -> None:
    """Guard rail: the spec must ship at least one fixture of each
    kind. A drop to zero fixtures is almost certainly a bug in either
    the spec layout or this runner's path resolution."""
    assert _VALID, "no valid conformance fixtures found"
    assert _INVALID, "no invalid conformance fixtures found"


@pytest.mark.unit
def test_constants_match_spec() -> None:
    """The implementation's magic / terminator literals must match the
    spec wording verbatim."""
    assert MAGIC == "# OKL v1"
    assert HEADER_TERMINATOR == "# ---"
    # The seven canonical event types listed in spec/codebook.md §2:
    expected_canonical = {
        "response",
        "reinforcer_start",
        "reinforcer_end",
        "state_change",
        "component_change",
        "phase_enter",
        "phase_exit",
    }
    assert set(CANONICAL_CODEBOOK) == expected_canonical
