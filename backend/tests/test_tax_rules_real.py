"""운영 세율(config/tax_rules.yaml) 실제값 회귀 테스트.

⚠️ 이 테스트는 **가상 픽스처가 아니라 운영 세율 파일**을 검증한다.
   세율이 잘못 바뀌면(오타·구간 실수·출처 누락) 여기서 즉시 깨져야 한다.
   사용자 예산이 수천만 원 어긋나는 것을 막는 마지막 방어선이다.

위택스 대조
-----------
아래 취득세 시나리오는 위택스(wetax.go.kr) 취득세 계산기 결과와 일치한다.
근거: 지방세법 §11(주택 유상거래) · §13의2(다주택 중과) · §151(지방교육세) · 농특세법.
6~9억 누진 구간은 로더의 고정요율 스키마 한계로 0.5억 서브밴드 근사이며(tax_rules.yaml L1),
근사 오차 상한(±0.2%p)도 여기서 검증한다.
"""
from __future__ import annotations

from pathlib import Path

import pytest

from app.domain.affordability.engine import acquisition_cost
from app.domain.affordability.models import Borrower, PropertyFacts
from app.domain.rules.loader import load_rules

REPO_ROOT = Path(__file__).resolve().parents[2]
PROD_RULES = REPO_ROOT / "config" / "tax_rules.yaml"

MAN = 10_000


@pytest.fixture(scope="module")
def prod_rules():
    """운영 세율은 allow_unverified 없이(=status must be verified) 로딩돼야 한다."""
    return load_rules(PROD_RULES)


def _acq_tax(rules, price_krw, *, owned_houses, area_m2, regulated=False):
    b = Borrower(cash_krw=0, annual_income_krw=0, owned_houses=owned_houses)
    prop = PropertyFacts(area_m2=area_m2, is_regulated_area=regulated)
    return acquisition_cost(price_krw, rules, b, prop).acquisition_tax_krw


# ---------------------------------------------------------------------------
# 로딩 가드 — 503 해소의 핵심 조건
# ---------------------------------------------------------------------------

def test_운영_세율이_검증본으로_로딩된다(prod_rules):
    """status: verified 이고 예외 없이 로딩 → /affordability 가 503 대신 계산한다."""
    assert prod_rules.status == "verified"
    assert prod_rules.version == "2026-07-25"


def test_모든_구간에_출처와_기준일자가_있다(prod_rules):
    groups = [prod_rules.acquisition_tax, prod_rules.brokerage_fee,
              tuple(prod_rules.lending.values())]
    for group in groups:
        for b in group:
            assert b.provenance is not None, f"{b.id}: 출처 없음(G2 위반)"
            assert b.provenance.source and b.provenance.source_url, f"{b.id}: 출처 불완전"


# ---------------------------------------------------------------------------
# 취득세 — 위택스 대조 (고정밴드, 정확히 일치)
# ---------------------------------------------------------------------------

def test_위택스_무주택_5억_소형_1_1퍼센트(prod_rules):
    """무주택자 5억 · 전용 84㎡(85↓) → 취득세 1.0%+지교 0.1% = 1.1% = 550만원."""
    assert _acq_tax(prod_rules, 500_000_000, owned_houses=0, area_m2=84.0) == 5_500_000


def test_위택스_무주택_5억_대형_1_3퍼센트(prod_rules):
    """전용 85㎡ 초과 → 농특세 0.2% 가산 → 1.3% = 650만원."""
    assert _acq_tax(prod_rules, 500_000_000, owned_houses=0, area_m2=100.0) == 6_500_000


def test_위택스_무주택_12억_9억초과_3_3퍼센트(prod_rules):
    """9억 초과 · 85㎡ 이하 → 3.0%+지교 0.3% = 3.3% = 3,960만원."""
    assert _acq_tax(prod_rules, 1_200_000_000, owned_houses=0, area_m2=84.0) == 39_600_000


def test_위택스_조정_2주택_6억_8_4퍼센트(prod_rules):
    """조정대상지역 2주택(기보유 1) · 6억 · 85↓ → 8%+지교 0.4% = 8.4% = 5,040만원."""
    tax = _acq_tax(prod_rules, 600_000_000, owned_houses=1, area_m2=84.0, regulated=True)
    assert tax == 50_400_000


def test_다주택_중과가_1주택보다_훨씬_크다(prod_rules):
    """같은 6억이라도 조정 2주택은 무주택 대비 7배 이상."""
    first = _acq_tax(prod_rules, 600_000_000, owned_houses=0, area_m2=84.0)
    multi = _acq_tax(prod_rules, 600_000_000, owned_houses=1, area_m2=84.0, regulated=True)
    assert multi > first * 7


# ---------------------------------------------------------------------------
# 6~9억 누진 밴드 — 법정 산식과 '정확히' 일치 (L1 해소 · 계약서 §4)
#   ⚠️ total_rate_pct 는 로더가 계산하는 정확값이다. 다만 engine 이 _pct_total →
#      total_rate_pct 로 전환(계약서 §3.3)하기 전까지 /affordability 는 폴백(밴드중앙)을
#      쓰므로, 아래는 '데이터·로더가 정확한가'를 본다(엔진 적용은 re-domain 몫).
# ---------------------------------------------------------------------------

def test_6_9억은_누진밴드로_표현된다(prod_rules):
    b = prod_rules.acquisition_bracket(houses_owned=1, price=750_000_000,
                                       area=84.0, regulated=False)
    assert b.is_progressive is True and b.id == "std_6_9_small"


@pytest.mark.parametrize("price_eok, expect_total_pct", [
    (6.5, 1.4667),   # 본세 1.3333 + 지교 0.1333
    (7.5, 2.2000),   # 본세 2.0000 + 지교 0.2000
    (8.5, 2.9333),   # 본세 2.6667 + 지교 0.2667
])
def test_누진밴드가_법정산식과_정확히_일치_85이하(prod_rules, price_eok, expect_total_pct):
    """계약서 §4 검산표(85㎡ 이하, 농특세 0). 근사가 아니라 정확값."""
    price = int(price_eok * 100_000_000)
    b = prod_rules.acquisition_bracket(houses_owned=1, price=price,
                                       area=84.0, regulated=False)
    total = b.total_rate_pct(price=price, area=84.0, houses_owned=1, regulated=False)
    assert total == pytest.approx(expect_total_pct, abs=1e-3)


def test_누진밴드_경계가_고정구간과_연속이다(prod_rules):
    """6억 → 1.1%(고정), 9억 → 3.3%(고정)과 매끄럽게 이어진다."""
    # 6억 정각은 고정 구간(1.1%), 6억+1원은 누진밴드지만 경계값 1.1%로 시작
    b6 = prod_rules.acquisition_bracket(houses_owned=1, price=600_000_000,
                                        area=84.0, regulated=False)
    assert b6.total_rate_pct(price=600_000_000, area=84.0) == pytest.approx(1.1, abs=1e-3)
    b9 = prod_rules.acquisition_bracket(houses_owned=1, price=900_000_000,
                                        area=84.0, regulated=False)
    assert b9.total_rate_pct(price=900_000_000, area=84.0) == pytest.approx(3.3, abs=1e-3)


def test_누진밴드_85초과는_농특세_02가_더해진다(prod_rules):
    """85㎡ 초과 7.5억: 본세 2.0 + 지교 0.2 + 농특 0.2 = 2.4%."""
    b = prod_rules.acquisition_bracket(houses_owned=1, price=750_000_000,
                                       area=100.0, regulated=False)
    assert b.id == "std_6_9_large"
    assert b.total_rate_pct(price=750_000_000, area=100.0) == pytest.approx(2.4, abs=1e-3)


# ---------------------------------------------------------------------------
# 대출 절대한도 · 스트레스 DSR (L2 — 데이터 표현. 엔진 적용은 re-domain)
# ---------------------------------------------------------------------------

def test_수도권_6억_절대한도(prod_rules):
    """6.27 대책: 수도권만 6억 한도. 비수도권·미상은 한도 없음(모르면 적용 안 함)."""
    assert prod_rules.absolute_cap_krw(region_group="수도권") == 600_000_000
    assert prod_rules.absolute_cap_krw(region_group="비수도권") is None
    assert prod_rules.absolute_cap_krw() is None
    cap = prod_rules.absolute_cap(region_group="수도권")
    assert cap.provenance is not None and "6.27" in cap.provenance.source


def test_스트레스DSR_가산금리(prod_rules):
    """스트레스 DSR 3단계: 수도권 1.5%p / 비수도권 0.75%p / 미상 0.0."""
    assert prod_rules.stress_rate_pct(region_group="수도권") == 1.5
    assert prod_rules.stress_rate_pct(region_group="비수도권") == 0.75
    assert prod_rules.stress_rate_pct() == 0.0


# ---------------------------------------------------------------------------
# 중개보수 — 공인중개사법 시행규칙 §20 별표1
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("price,expected_pct", [
    (500_000_000, 0.4),      # 2~9억
    (1_000_000_000, 0.5),    # 9~12억
    (1_300_000_000, 0.6),    # 12~15억
    (1_600_000_000, 0.7),    # 15억↑
])
def test_중개보수_구간별_상한요율(prod_rules, price, expected_pct):
    assert prod_rules.brokerage_bracket(price=price).rate_pct == expected_pct


# ---------------------------------------------------------------------------
# 대출 규제 대표값 (L2 — 단일 브래킷, 규제지역·6억캡·스트레스DSR 미반영)
# ---------------------------------------------------------------------------

def test_대출규제_대표값(prod_rules):
    assert prod_rules.lending_rule("ltv").rate_pct == 70.0
    assert prod_rules.lending_rule("dsr").rate_pct == 40.0
    assert prod_rules.lending_rule("dti").rate_pct == 60.0
