"""Shared fixtures for session-recorder tests."""

from __future__ import annotations

from pathlib import Path

import pytest


@pytest.fixture
def tmp_log(tmp_path: Path) -> Path:
    """Return a path for a per-test OKL v1 log file."""
    return tmp_path / "session.txt"
