"""Paths used for generated artifacts in this repository workspace."""
from __future__ import annotations

from pathlib import Path

WORKSPACE_ROOT = Path(__file__).resolve().parent.parent


def workspace_temp_dir() -> Path:
    """Return an ignored, repository-local directory for transient work files."""
    path = WORKSPACE_ROOT / ".agent_tmp"
    path.mkdir(parents=True, exist_ok=True)
    return path


def workspace_output_dir(*parts: str) -> Path:
    """Return a persistent generated-output directory inside the repository."""
    path = WORKSPACE_ROOT / "motor" / "cikti" / Path(*parts)
    path.mkdir(parents=True, exist_ok=True)
    return path
