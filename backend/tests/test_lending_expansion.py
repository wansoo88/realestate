"""대출·세율 규칙 확장 — engine 적용 검증 (ORDER 2026-07-25-14-domain).

계약: docs/domain/lending-rules-contract.md §3(엔진 연동) + §4(검산표)
re-review 사전지침(2026-07-25): 캡 기본=수도권(안전), region 은 서버 판정(사용자 입력 금지),
생성지점 전부 캡 적용.

⚠️ 세율은 tests/fixtures/tax_rules_capital_test.yaml 의 **가상값**이다.
"""
from __future__ import annotations

from pathlib import Path

import pytest

from app.domain.affordability.engine import acquisition_cost, compute_affordability
from app.domain.affordability.models import Borrower, LoanTerms, PropertyFacts
from app.domain.rules.loader import load_rules

FIXTURES = Path(__file__).parent / "fixtures"


@pytest.fixture(scope="module")
def capital_rules():
    return load_rules(FIXTURES / "tax_rules_capital_test.yaml")


# ---------------------------------------------------------------------------
# §1 — region_group 파생 + 안전 기본값(수도권)
# ---------------------------------------------------------------------------

def test_법정동코드로_권역이_파생된다():
    assert PropertyFacts.region_group_from_code("11110") == "수도권"   # 서울
    assert PropertyFacts.region_group_from_code("41135") == "수도권"   # 경기
    assert PropertyFacts.region_group_from_code("28110") == "수도권"   # 인천
    assert PropertyFacts.region_group_from_code("26110") == "비수도권"  # 부산
    assert PropertyFacts.region_group_from_code(None) is None
    assert PropertyFacts(target_region_code="26110").effective_region_group == "비수도권"


def test_기본_권역은_수도권이다():
    """대상지역이 수도권 전체 — 모를 때 캡을 끄면 과대산정으로 거꾸로 간다."""
    assert PropertyFacts().effective_region_group == "수도권"
    assert PropertyFacts(area_m2=84.0).effective_region_group == "수도권"
    # 명시 비수도권만 예외
    assert PropertyFacts(region_group="비수도권").effective_region_group == "비수도권"


# ---------------------------------------------------------------------------
# §3.1 — 6억 절대한도가 실구매 가능액을 낮춘다 (이 오더의 핵심 DoD)
# ---------------------------------------------------------------------------

def test_수도권_6억캡이_실구매가능액을_낮춘다(capital_rules):
    borrower = Borrower(cash_krw=1_000_000_000, annual_income_krw=300_000_000)
    capital = compute_affordability(
        borrower, capital_rules, prop=PropertyFacts(area_m2=84.0, region_group="수도권"))
    non_capital = compute_affordability(
        borrower, capital_rules, prop=PropertyFacts(area_m2=84.0, region_group="비수도권"))

    # 캡이 대출을 6억으로 묶고, 그래서 최대 구매가가 낮아진다.
    assert capital.limits.cap_krw == 600_000_000
    assert capital.binding_constraint == "CAP"
    assert capital.loan_krw <= 600_000_000
    assert capital.max_purchase_krw < non_capital.max_purchase_krw

    # 캡이 없으면(비수도권) 6억을 넘겨 빌리게 된다 — 이게 고치려던 과대산정이다.
    assert non_capital.limits.cap_krw is None
    assert non_capital.loan_krw > 600_000_000
    assert non_capital.binding_constraint != "CAP"


def test_기본값_무지정도_수도권캡이_적용된다(capital_rules):
    """region 을 안 넘겨도(제품 기본 경로) 캡이 걸려야 한다.

    re-review C-point: '단위테스트는 수도권 명시로 초록인데 제품만 무캡'(최악)을 막는다.
    """
    borrower = Borrower(cash_krw=1_000_000_000, annual_income_krw=300_000_000)
    default = compute_affordability(borrower, capital_rules,
                                    prop=PropertyFacts(area_m2=84.0))   # region 미지정
    explicit = compute_affordability(
        borrower, capital_rules, prop=PropertyFacts(area_m2=84.0, region_group="수도권"))

    assert default.limits.cap_krw == 600_000_000
    assert default.binding_constraint == "CAP"
    assert default.max_purchase_krw == explicit.max_purchase_krw


def test_캡_근거가_출처와_함께_나온다(capital_rules):
    borrower = Borrower(cash_krw=1_000_000_000, annual_income_krw=300_000_000)
    r = compute_affordability(borrower, capital_rules,
                              prop=PropertyFacts(area_m2=84.0, region_group="수도권"))
    cap_ev = [e for e in r.evidence if "절대한도" in e["claim"]]
    assert cap_ev and cap_ev[0]["source"] and cap_ev[0]["as_of"]
    assert any("절대한도" in a for a in r.assumptions)
    # to_api 로도 캡이 드러난다(UI 노출용).
    assert r.to_api()["breakdown"]["absolute_cap_krw"] == 600_000_000


# ---------------------------------------------------------------------------
# §3.2 — 스트레스 DSR 은 한도만 낮춘다(실제 상환금리 아님)
# ---------------------------------------------------------------------------

def test_스트레스DSR가_DSR한도를_낮춘다(capital_rules):
    """수도권 1.5%p > 비수도권 0.75%p → 수도권 DSR 한도(원금)가 더 작다."""
    borrower = Borrower(cash_krw=2_000_000_000, annual_income_krw=50_000_000)
    capital = compute_affordability(
        borrower, capital_rules, prop=PropertyFacts(area_m2=84.0, region_group="수도권"))
    non_capital = compute_affordability(
        borrower, capital_rules, prop=PropertyFacts(area_m2=84.0, region_group="비수도권"))

    assert capital.limits.dsr_krw < non_capital.limits.dsr_krw


def test_스트레스금리는_가정으로만_표기된다(capital_rules):
    """한도 산정용 가정임을 사용자에게 명시 — 실제 상환액을 부풀리지 않는다."""
    borrower = Borrower(cash_krw=2_000_000_000, annual_income_krw=50_000_000)
    r = compute_affordability(borrower, capital_rules,
                              prop=PropertyFacts(area_m2=84.0, region_group="수도권"))
    joined = " ".join(r.assumptions)
    assert "스트레스 DSR" in joined and "실제 상환금리 아님" in joined
    assert any("스트레스 DSR" in e["claim"] for e in r.evidence)


# ---------------------------------------------------------------------------
# §3.3 / §4 — 6~9억 연속 누진 취득세 검산표
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("price,expected_tax", [
    (600_000_000, 6_600_000),    # 1.100% (경계 — 아래 고정구간과 연속)
    (650_000_000, 9_533_333),    # 1.467%
    (750_000_000, 16_500_000),   # 2.200%
    (850_000_000, 24_933_333),   # 2.933%
    (900_000_000, 29_700_000),   # 3.300% (경계 — 위 구간과 연속)
])
def test_6_9억_누진_취득세_검산(capital_rules, price, expected_tax):
    b = Borrower(cash_krw=0, annual_income_krw=0, owned_houses=0)
    cost = acquisition_cost(price, capital_rules, b, PropertyFacts(area_m2=84.0))
    assert cost.acquisition_tax_krw == expected_tax


def test_누진_취득세는_클램프된다(capital_rules):
    """산식 결과가 6억↓·9억↑ 경계 밖으로 나가지 않는다(음수·과대 세율 방지)."""
    b = Borrower(cash_krw=0, annual_income_krw=0, owned_houses=0)
    # 6억 경계: 본세 1.0% 클램프 → 합계 1.1%
    at6 = acquisition_cost(600_000_001, capital_rules, b, PropertyFacts(area_m2=84.0))
    assert at6.acquisition_tax_krw == pytest.approx(600_000_001 * 0.011, rel=1e-6)
    # 9억 경계: 본세 3.0% 클램프 → 합계 3.3%
    at9 = acquisition_cost(900_000_000, capital_rules, b, PropertyFacts(area_m2=84.0))
    assert at9.acquisition_tax_krw == 29_700_000


# ---------------------------------------------------------------------------
# 하위호환 — 캡/스트레스 규칙이 없는 설정은 이전과 동일
# ---------------------------------------------------------------------------

def test_캡_규칙이_없으면_이전과_같다(test_rules):
    """공유 픽스처(캡·스트레스 없음)는 수도권 기본이어도 캡/가산이 안 생긴다(하위호환)."""
    borrower = Borrower(cash_krw=1_000_000_000, annual_income_krw=300_000_000)
    r = compute_affordability(borrower, test_rules, prop=PropertyFacts(area_m2=84.0))
    assert r.limits.cap_krw is None
    assert r.binding_constraint != "CAP"
    assert not any("스트레스" in a for a in r.assumptions)
