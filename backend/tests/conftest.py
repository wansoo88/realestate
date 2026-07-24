from pathlib import Path

import pytest

from app.domain.rules.loader import load_rules

FIXTURES = Path(__file__).parent / "fixtures"
REPO_ROOT = Path(__file__).resolve().parents[2]


@pytest.fixture(scope="session")
def test_rules():
    """테스트 전용 가상 세율. 실제 세율이 아니다."""
    return load_rules(FIXTURES / "tax_rules_test.yaml")


@pytest.fixture(scope="session")
def production_rules_path():
    return REPO_ROOT / "config" / "tax_rules.yaml"
