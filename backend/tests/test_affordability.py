"""실구매 가능 금액 계산 테스트.

⚠️ 여기 쓰인 세율은 **테스트용 가상값**이다(tests/fixtures/tax_rules_test.yaml).
   실제 세율 검증은 config/tax_rules.yaml 을 채운 뒤 위택스·국세청 계산기와 대조한다.

이 테스트가 지키려는 것
-----------------------
가장 중요한 건 **"대출한도가 집값의 함수"** 라는 사실이 코드에 반영됐는지다.
이걸 놓치면 예산이 과대 산정되고, 사용자는 살 수 없는 집을 보게 된다.
그래서 결과값 하드코딩보다 **불변식(invariant)** 을 검증한다.
"""
from __future__ import annotations

import pytest

from app.domain.affordability.engine import (
    acquisition_cost,
    compute_affordability,
    dsr_limit,
    principal_from_annual_payment,
)
from app.domain.affordability.models import Borrower, LoanTerms, PropertyFacts

MAN = 10_000  # 만원


# ---------------------------------------------------------------------------
# 원리금 환산
# ---------------------------------------------------------------------------

def test_무이자면_단순_곱셈():
    terms = LoanTerms(annual_rate=0.0, years=10)
    assert principal_from_annual_payment(12_000_000, terms) == 120_000_000


def test_연금현가_공식_검산():
    """월이율 1%(연 12%), 12개월. 연금현가계수 = (1-1.01^-12)/0.01 = 11.2551."""
    terms = LoanTerms(annual_rate=0.12, years=1)
    p = principal_from_annual_payment(12_000_000, terms)
    assert p == pytest.approx(11_255_077, rel=1e-4)


def test_상환액이_0이하면_대출_불가():
    terms = LoanTerms()
    assert principal_from_annual_payment(0, terms) == 0
    assert principal_from_annual_payment(-1_000_000, terms) == 0


def test_기존대출이_DSR한도를_깎는다(test_rules):
    terms = LoanTerms()
    no_debt = Borrower(cash_krw=0, annual_income_krw=100_000_000)
    with_debt = Borrower(cash_krw=0, annual_income_krw=100_000_000,
                         existing_annual_repayment_krw=20_000_000)

    assert dsr_limit(with_debt, terms, 40.0) < dsr_limit(no_debt, terms, 40.0)


def test_기존대출이_소득의_DSR한도를_넘으면_0(test_rules):
    terms = LoanTerms()
    b = Borrower(cash_krw=0, annual_income_krw=50_000_000,
                 existing_annual_repayment_krw=30_000_000)  # 40% = 2천만 < 3천만
    assert dsr_limit(b, terms, 40.0) == 0


# ---------------------------------------------------------------------------
# 취득 부대비용
# ---------------------------------------------------------------------------

def test_취득비용_계산(test_rules):
    """5억 · 1주택 · 84㎡ → 취득세 1.1% + 중개보수 0.4% + 등기 100만."""
    b = Borrower(cash_krw=0, annual_income_krw=0, owned_houses=0)
    cost = acquisition_cost(500_000_000, test_rules, b, PropertyFacts(area_m2=84.0))

    assert cost.acquisition_tax_krw == 5_500_000        # 5억 × 1.1%
    assert cost.brokerage_krw == 2_000_000              # 5억 × 0.4%
    assert cost.registration_krw == 1_000_000
    assert cost.total_krw == 8_500_000


def test_중개보수_상한이_적용된다(test_rules):
    """30억 × 0.4% = 1,200만이지만 상한 800만."""
    b = Borrower(cash_krw=0, annual_income_krw=0, owned_houses=0)
    cost = acquisition_cost(3_000_000_000, test_rules, b, PropertyFacts(area_m2=84.0))
    assert cost.brokerage_krw == 8_000_000


def test_다주택은_취득세가_뛴다(test_rules):
    prop = PropertyFacts(area_m2=84.0)
    first = Borrower(cash_krw=0, annual_income_krw=0, owned_houses=0)
    multi = Borrower(cash_krw=0, annual_income_krw=0, owned_houses=1)

    c1 = acquisition_cost(500_000_000, test_rules, first, prop)
    c2 = acquisition_cost(500_000_000, test_rules, multi, prop)
    assert c2.acquisition_tax_krw > c1.acquisition_tax_krw * 5


# ---------------------------------------------------------------------------
# 핵심: 실구매 가능 금액
# ---------------------------------------------------------------------------

def _shortfall(result, rules, borrower, prop, terms):
    """결과 가격에서 부등식이 실제로 성립하는지 다시 계산해 확인."""
    from app.domain.affordability.engine import _limits_at
    cost = acquisition_cost(result.max_purchase_krw, rules, borrower, prop)
    limits = _limits_at(result.max_purchase_krw, borrower, terms, rules,
                        rules.lending_rule("ltv").rate_pct,
                        rules.lending_rule("dsr").rate_pct, None)
    return (result.max_purchase_krw + cost.total_krw
            - limits.effective_krw - result.usable_cash_krw)


def test_불변식_최대가격에서_부등식이_성립한다(test_rules):
    """max_purchase 에서는 감당 가능하고, 거기서 더 올리면 감당 불가여야 한다."""
    borrower = Borrower(cash_krw=300_000_000, annual_income_krw=200_000_000)
    prop = PropertyFacts(area_m2=84.0)
    terms = LoanTerms()

    r = compute_affordability(borrower, test_rules, terms=terms, prop=prop)

    assert _shortfall(r, test_rules, borrower, prop, terms) <= 0, "최대가격이 감당 불가"

    # 1,000만 더 올리면 반드시 초과해야 한다 (만원 단위 내림 여유 감안)
    from app.domain.affordability.engine import _limits_at
    higher = r.max_purchase_krw + 10_000_000
    cost = acquisition_cost(higher, test_rules, borrower, prop)
    limits = _limits_at(higher, borrower, terms, test_rules, 70.0, 40.0, None)
    assert higher + cost.total_krw - limits.effective_krw - r.usable_cash_krw > 0


def test_LTV가_묶는_경우(test_rules):
    """소득이 높으면 DSR 은 여유롭고 LTV 가 한도를 묶는다."""
    borrower = Borrower(cash_krw=300_000_000, annual_income_krw=200_000_000)
    r = compute_affordability(borrower, test_rules, prop=PropertyFacts(area_m2=84.0))

    assert r.binding_constraint == "LTV"
    assert r.limits.ltv_krw < r.limits.dsr_krw


def test_DSR이_묶는_경우(test_rules):
    """현금은 많고 소득이 낮으면 DSR 이 한도를 묶는다."""
    borrower = Borrower(cash_krw=1_500_000_000, annual_income_krw=40_000_000)
    r = compute_affordability(borrower, test_rules, prop=PropertyFacts(area_m2=84.0))

    assert r.binding_constraint == "DSR"
    assert r.limits.dsr_krw < r.limits.ltv_krw


def test_소득이_없으면_대출이_0이고_현금_범위만(test_rules):
    borrower = Borrower(cash_krw=500_000_000, annual_income_krw=0)
    r = compute_affordability(borrower, test_rules, prop=PropertyFacts(area_m2=84.0))

    assert r.loan_krw == 0
    assert r.usable_cash_krw == 480_000_000          # 5억 − 예비비 2천만
    # 1.5% 부대비용 + 등기 100만을 빼고 남는 만큼만 살 수 있다
    assert 470_000_000 < r.max_purchase_krw < 480_000_000


def test_단순합산보다_반드시_작다(test_rules):
    """예산 과대 산정 회귀 방지.

    흔한 오류: `현금 / (1 − LTV)` 로 최대가를 잡고 세금을 잊는 것.
    실제로는 취득비용만큼 더 못 산다.
    """
    borrower = Borrower(cash_krw=300_000_000, annual_income_krw=200_000_000)
    r = compute_affordability(borrower, test_rules, prop=PropertyFacts(area_m2=84.0))

    naive = int(r.usable_cash_krw / (1 - 0.70))       # 부대비용 무시한 값
    assert r.max_purchase_krw < naive
    assert naive - r.max_purchase_krw > 10_000_000, "부대비용이 반영되지 않은 것 같다"


def test_기존대출이_있으면_한도가_준다(test_rules):
    base = Borrower(cash_krw=1_500_000_000, annual_income_krw=60_000_000)
    burdened = Borrower(cash_krw=1_500_000_000, annual_income_krw=60_000_000,
                        existing_annual_repayment_krw=15_000_000)

    r1 = compute_affordability(base, test_rules, prop=PropertyFacts(area_m2=84.0))
    r2 = compute_affordability(burdened, test_rules, prop=PropertyFacts(area_m2=84.0))
    assert r2.max_purchase_krw < r1.max_purchase_krw


def test_DTI_적용시_한도가_같거나_준다(test_rules):
    borrower = Borrower(cash_krw=1_000_000_000, annual_income_krw=50_000_000,
                        existing_annual_interest_krw=5_000_000)

    without = compute_affordability(borrower, test_rules,
                                    terms=LoanTerms(apply_dti=False),
                                    prop=PropertyFacts(area_m2=84.0))
    with_dti = compute_affordability(borrower, test_rules,
                                     terms=LoanTerms(apply_dti=True),
                                     prop=PropertyFacts(area_m2=84.0))
    assert with_dti.max_purchase_krw <= without.max_purchase_krw


def test_돈이_없으면_0을_반환한다(test_rules):
    borrower = Borrower(cash_krw=1_000_000, annual_income_krw=0)
    r = compute_affordability(borrower, test_rules, prop=PropertyFacts(area_m2=84.0))
    assert r.max_purchase_krw == 0


def test_만원단위로_내림한다(test_rules):
    borrower = Borrower(cash_krw=300_000_000, annual_income_krw=200_000_000)
    r = compute_affordability(borrower, test_rules, prop=PropertyFacts(area_m2=84.0))
    assert r.max_purchase_krw % 10_000 == 0


# ---------------------------------------------------------------------------
# 출력 계약 (G2 근거 감사 대비)
# ---------------------------------------------------------------------------

def test_모든_세율에_출처가_붙어_나온다(test_rules):
    borrower = Borrower(cash_krw=300_000_000, annual_income_krw=200_000_000)
    r = compute_affordability(borrower, test_rules, prop=PropertyFacts(area_m2=84.0))

    assert r.evidence, "근거 없는 금액은 내보내면 안 된다"
    for ev in r.evidence:
        assert ev["source"] and ev["as_of"], f"출처·기준일자 누락: {ev}"


def test_가정이_사용자에게_노출된다(test_rules):
    borrower = Borrower(cash_krw=300_000_000, annual_income_krw=200_000_000)
    r = compute_affordability(borrower, test_rules, prop=PropertyFacts(area_m2=84.0))

    joined = " ".join(r.assumptions)
    assert "금리" in joined and "만기" in joined
    assert "예비비" in joined


def test_API_응답에_면책고지가_포함된다(test_rules):
    borrower = Borrower(cash_krw=300_000_000, annual_income_krw=200_000_000)
    payload = compute_affordability(
        borrower, test_rules, prop=PropertyFacts(area_m2=84.0)).to_api()

    assert "disclaimer" in payload
    assert "투자 권유가 아니" in payload["disclaimer"]
    assert payload["breakdown"]["binding_constraint"] in {"LTV", "DSR", "DTI", "CASH"}


def test_음수_입력은_거부한다():
    with pytest.raises(ValueError):
        Borrower(cash_krw=-1, annual_income_krw=0)
    with pytest.raises(ValueError):
        Borrower(cash_krw=0, annual_income_krw=-1)
