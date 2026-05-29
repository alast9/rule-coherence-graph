from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]


@pytest.fixture
def gemini_incident_path() -> Path:
    return REPO_ROOT / "examples" / "gemini_incident"
