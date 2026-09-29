from pathlib import Path

import pytest
import yaml

ROOT = Path(__file__).resolve().parents[1]
FIXTURES = ROOT / "tests" / "fixtures"
EXAMPLE_BANK = ROOT / "examples" / "experience_bank.example.yaml"
EDGE_BANK = ROOT / "tests" / "banks" / "edge_cases.yaml"


def load(path: Path) -> dict:
    return yaml.safe_load(path.read_text(encoding="utf-8"))


@pytest.fixture
def example_bank() -> dict:
    return load(EXAMPLE_BANK)


@pytest.fixture
def edge_bank() -> dict:
    return load(EDGE_BANK)
