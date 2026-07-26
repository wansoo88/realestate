"""희망 매매가 기준 자금계획 (정방향) 테스트.

ORDER 2026-07-26 — "얼마나 더 필요하고, 얼마나 대출 받고, 얼마나 원리금 상환하나".

이 파일이 지키려는 것
---------------------
1. **월 원리금 공식이 맞다.** 상수를 적어 두고 그 상수를 확인하는 자기충족 테스트를
   피하려고, 기대값을 **두 가지 독립한 방법**으로 만든다:
     · 폐쇄형(닫힌 식)이 아니라 **할인계수의 합**으로 연금현가를 다시 구한다
     · 실제 **상환 스케줄을 360회 돌려** 잔액이 0 이 되는지 본다
   engine 의 식을 베껴 오면 engine 이 틀려도 테스트가 같이 틀린다.
2. **역방향(최대 구매가)과 정방향(자금계획)이 모순되지 않는다.**
       loan_feasible  ⟺  희망가 ≤ 최대 실구매 가능 금액
   두 계산이 서로 다른 규칙·세율을 쓰기 시작하면 여기서 깨진다.
3. **한도를 넘어도 계산을 멈추지 않는다.** "불가능"만 남기면 사용자는 얼마를 더
   모아야 하는지 알 수 없다.

⚠️ 운영 세율(config/tax_rules.yaml)을 쓰는 케이스는 그 사실을 함수명에 밝힌다.
"""
from __future__ import annotations

from pathlib import Path

import pytest

from app.domain.affordability.engine import (
    acquisition_cost,
    build_purchase_plan,
    compute_affordability,
    monthly_payment_krw,
    principal_from_annual_payment,
    total_interest_krw,
)
from app.domain.affordability.models import Borrower, LoanTerms, PropertyFacts
from app.domain.rules.loader import load_rules

REPO_ROOT = Path(__file__).resolve().parents[2]
OKU = 100_000_000


@pytest.fixture(scope="module")
def prod_rules():
    """운영 세율. 자금계획은 **실제 세율**로 검증해야 의미가 있다."""
    return load_rules(REPO_ROOT / "config" / "tax_rules.yaml")


#: 실증 시나리오 — 보유현금 3억 · 연소득 1억 (ORDER 지정)
def _borrower() -> Borrower:
    return Borrower(cash_krw=300_000_000, annual_income_krw=100_000_000)


def _prop() -> PropertyFacts:
    return PropertyFacts(area_m2=84.0)


# ---------------------------------------------------------------------------
# 월 원리금 — 독립 검산
# ---------------------------------------------------------------------------

def _annuity_payment_by_summation(principal: float, annual_rate: float,
                                  years: int) -> float:
    """engine 과 **다른 방법**으로 구한 월 상환액.

    폐쇄형 `i / (1 − (1+i)^−n)` 대신 할인계수를 하나씩 더해 연금현가계수를 만든다.
    두 방법이 같은 값을 내야 공식이 맞는 것이다(같은 식을 베끼면 검증이 아니다).
    """
    i = annual_rate / 12.0
    n = years * 12
    if i == 0:
        return principal / n
    present_value_factor = sum((1.0 + i) ** -k for k in range(1, n + 1))
    return principal / present_value_factor


@pytest.mark.parametrize(("principal", "rate", "years"), [
    (500_000_000, 0.04, 30),
    (330_500_000, 0.04, 30),
    (600_000_000, 0.05, 30),
    (200_000_000, 0.031, 15),
    (1_000_000_000, 0.065, 40),
])
def test_월원리금이_독립_산식과_일치한다(principal, rate, years):
    terms = LoanTerms(annual_rate=rate, years=years)
    expected = _annuity_payment_by_summation(principal, rate, years)
    # 반올림(원 단위) 오차만 허용한다. 1원 넘게 벌어지면 공식이 다른 것이다.
    assert abs(monthly_payment_krw(principal, terms) - expected) <= 1.0


@pytest.mark.parametrize(("principal", "rate", "years"), [
    (500_000_000, 0.04, 30),
    (630_000_000, 0.04, 30),
    (150_000_000, 0.072, 20),
])
def test_상환스케줄을_끝까지_돌리면_잔액이_0이_된다(principal, rate, years):
    """공식이 아니라 **행동**을 검증한다 — 매달 이자를 붙이고 상환액을 빼면 잔액이 사라져야 한다.

    상환액이 조금이라도 작으면 잔액이 남고, 크면 음수로 넘어간다. 원 단위 반올림이
    360회 누적되는 몫(수백 원)만 허용한다.
    """
    m = monthly_payment_krw(principal, LoanTerms(annual_rate=rate, years=years))
    i = rate / 12.0
    balance = float(principal)
    for _ in range(years * 12):
        balance = balance * (1.0 + i) - m
    assert abs(balance) < 2_000, f"만기 후 잔액 {balance:,.0f}원 — 상환액이 틀렸다"


def test_손계산_대조_5억_4퍼센트_30년():
    """ORDER 검산값: 원금 5억 · 연 4% · 30년 → 약 238만원."""
    m = monthly_payment_krw(500_000_000, LoanTerms(annual_rate=0.04, years=30))
    assert 2_380_000 <= m <= 2_395_000, m
    # 총이자도 같은 가정에서 상식적인 범위여야 한다(원금의 70~75%).
    interest = total_interest_krw(500_000_000, LoanTerms(annual_rate=0.04, years=30))
    assert m * 360 - 500_000_000 == interest
    assert 0.70 < interest / 500_000_000 < 0.75


def test_정방향과_역방향은_서로의_역함수다():
    """월 상환액 → 원금 → 월 상환액 이 제자리로 돌아와야 한다."""
    terms = LoanTerms(annual_rate=0.045, years=25)
    for principal in (100_000_000, 350_000_000, 780_000_000):
        annual = monthly_payment_krw(principal, terms) * 12
        assert principal_from_annual_payment(annual, terms) == pytest.approx(
            principal, rel=1e-5)


def test_무이자면_원금을_개월수로_나눈다():
    terms = LoanTerms(annual_rate=0.0, years=10)
    assert monthly_payment_krw(120_000_000, terms) == 1_000_000
    assert total_interest_krw(120_000_000, terms) == 0


def test_원금이_없으면_상환액도_0():
    terms = LoanTerms()
    assert monthly_payment_krw(0, terms) == 0
    assert monthly_payment_krw(-1, terms) == 0
    assert total_interest_krw(0, terms) == 0


def test_금리가_오르면_월상환액이_오른다():
    p = 500_000_000
    low = monthly_payment_krw(p, LoanTerms(annual_rate=0.04, years=30))
    high = monthly_payment_krw(p, LoanTerms(annual_rate=0.05, years=30))
    assert high > low
    # 4%→5% 는 "조금"이 아니다. 최소 10% 이상 뛴다 — 가정을 노출해야 하는 이유.
    assert high / low > 1.10


def test_만기가_길어지면_월상환액은_줄고_총이자는_는다():
    p = 500_000_000
    short = LoanTerms(annual_rate=0.04, years=15)
    long = LoanTerms(annual_rate=0.04, years=30)
    assert monthly_payment_krw(p, long) < monthly_payment_krw(p, short)
    assert total_interest_krw(p, long) > total_interest_krw(p, short)


# ---------------------------------------------------------------------------
# 자금계획 — 운영 세율
# ---------------------------------------------------------------------------

def test_운영세율_6억_부대비용은_법정요율과_일치한다(prod_rules):
    """엔진을 믿지 않고 **법령 요율**로 직접 검산한다.

    6억 · 84㎡ · 무주택 → 취득세 1.0% + 지방교육세 0.1% = 6,600,000원
                          중개보수 상한 0.4% = 2,400,000원
                          등기·법무 1,500,000원 (fixed_costs)
    """
    plan = build_purchase_plan(6 * OKU, _borrower(), prod_rules, prop=_prop())
    assert plan.costs.acquisition_tax_krw == 6_600_000
    assert plan.costs.brokerage_krw == 2_400_000
    assert plan.costs.registration_krw == 1_500_000
    assert plan.total_needed_krw == 6 * OKU + 10_500_000


def test_부대비용은_기존_엔진과_같은_값이다(prod_rules):
    """자금계획이 세금을 **다시 계산하지 않는다**는 것을 못박는다(계산식 두 벌 금지)."""
    b, prop = _borrower(), _prop()
    for target in (6 * OKU, 9 * OKU, 15 * OKU):
        plan = build_purchase_plan(target, b, prod_rules, prop=prop)
        assert plan.costs == acquisition_cost(target, prod_rules, b, prop)


def test_총필요자금은_매매가_더하기_부대비용이다(prod_rules):
    for target in (4 * OKU, 6 * OKU, 9 * OKU, 15 * OKU):
        plan = build_purchase_plan(target, _borrower(), prod_rules, prop=_prop())
        assert plan.total_needed_krw == target + plan.costs.total_krw
        assert plan.shortfall_krw == plan.total_needed_krw - plan.own_cash_krw
        assert plan.required_loan_krw == plan.shortfall_krw


def test_내현금은_최대구매가_계산과_같은_값을_쓴다(prod_rules):
    """화면에 '내 돈'이 두 개 뜨면 안 된다 — breakdown 과 plan 이 같은 값이어야 한다."""
    r = compute_affordability(_borrower(), prod_rules, prop=_prop(),
                              target_price_krw=9 * OKU)
    payload = r.to_api()
    assert payload["plan"]["own_cash_krw"] == payload["breakdown"]["own_cash_krw"]
    assert r.plan.own_cash_krw == r.usable_cash_krw


@pytest.mark.parametrize("target_oku", [6, 9, 15])
def test_희망가별_계획이_나온다(prod_rules, target_oku):
    plan = build_purchase_plan(target_oku * OKU, _borrower(), prod_rules, prop=_prop())
    assert plan.target_price_krw == target_oku * OKU
    assert plan.required_loan_krw > 0
    assert plan.monthly_payment_krw > 0
    assert plan.limits.binding in {"LTV", "DSR", "DTI", "CAP"}


def test_희망가가_오르면_필요대출과_월상환액이_함께_오른다(prod_rules):
    """6억 / 9억 / 15억 — 숫자가 상식적으로 움직이는지."""
    plans = [build_purchase_plan(oku * OKU, _borrower(), prod_rules, prop=_prop())
             for oku in (6, 9, 15)]
    loans = [p.required_loan_krw for p in plans]
    payments = [p.monthly_payment_krw for p in plans]
    assert loans == sorted(loans) and len(set(loans)) == 3
    assert payments == sorted(payments) and len(set(payments)) == 3
    # 대출이 커지면 월 상환액도 **비례해서** 커진다(같은 금리·기간이므로).
    assert loans[1] / loans[0] == pytest.approx(payments[1] / payments[0], rel=1e-3)


def test_한도를_넘어도_계산을_멈추지_않는다(prod_rules):
    """15억: 못 산다고만 하지 않고 '얼마가 모자란지'를 준다."""
    plan = build_purchase_plan(15 * OKU, _borrower(), prod_rules, prop=_prop())
    assert plan.loan_feasible is False
    assert plan.over_limit_krw is not None and plan.over_limit_krw > 0
    # 초과분 = 필요대출 − 한도. 이 등식이 곧 "얼마를 더 모아야 하는가"다.
    assert plan.over_limit_krw == plan.required_loan_krw - plan.limits.effective_krw
    assert plan.feasible_loan_krw == plan.limits.effective_krw
    # 한도까지만 빌렸을 때의 상환액도 함께 준다(그래야 대안을 볼 수 있다).
    assert 0 < plan.monthly_payment_feasible_krw < plan.monthly_payment_krw
    assert plan.limits.binding in {"LTV", "DSR", "DTI", "CAP"}


def test_한도초과가_경고문에_금액과_이유로_남는다(prod_rules):
    r = compute_affordability(_borrower(), prod_rules, prop=_prop(),
                              target_price_krw=15 * OKU)
    joined = " ".join(r.warnings)
    assert f"{r.plan.over_limit_krw:,}" in joined
    assert r.plan.limits.binding in joined


def test_한도_안이면_경고가_붙지_않는다(prod_rules):
    r = compute_affordability(_borrower(), prod_rules, prop=_prop(),
                              target_price_krw=6 * OKU)
    assert r.plan.loan_feasible is True
    assert r.plan.over_limit_krw is None
    assert not [w for w in r.warnings if "초과" in w]


def test_가능여부는_최대_실구매가능금액과_일치한다(prod_rules):
    """정방향·역방향 모순 금지.

    최대 구매가에서는 반드시 가능해야 하고, 거기서 1,000만원만 올려도 불가능해야 한다.
    (두 계산이 서로 다른 한도·세율을 쓰기 시작하면 여기서 깨진다.)
    """
    b, prop = _borrower(), _prop()
    base = compute_affordability(b, prod_rules, prop=prop)
    at_max = build_purchase_plan(base.max_purchase_krw, b, prod_rules, prop=prop)
    above = build_purchase_plan(base.max_purchase_krw + 10_000_000, b, prod_rules,
                                prop=prop)
    assert at_max.loan_feasible is True
    assert above.loan_feasible is False


def test_현금이_충분하면_대출이_필요없다(prod_rules):
    rich = Borrower(cash_krw=2_000_000_000, annual_income_krw=100_000_000)
    plan = build_purchase_plan(6 * OKU, rich, prod_rules, prop=_prop())
    assert plan.required_loan_krw == 0
    assert plan.shortfall_krw == 0          # 남는 현금을 '음수 부족액'으로 쓰지 않는다
    assert plan.monthly_payment_krw == 0
    assert plan.loan_feasible is True
    assert plan.over_limit_krw is None


def test_소득이_없으면_대출한도가_0이라_그_사실이_드러난다(prod_rules):
    poor = Borrower(cash_krw=100_000_000, annual_income_krw=0)
    plan = build_purchase_plan(6 * OKU, poor, prod_rules, prop=_prop())
    assert plan.limits.dsr_krw == 0
    assert plan.loan_feasible is False
    assert plan.over_limit_krw == plan.required_loan_krw   # 한도 0 → 전액이 초과분


def test_LTV는_여유로워도_DSR이_막으면_불가다(prod_rules):
    """현금은 많고 소득이 적은 사람 — 담보는 되는데 **갚을 능력**이 안 된다.

    ⚠️ 이 케이스가 없으면 "가능 여부를 LTV 한도로만 판정"하는 버그가 **테스트를 통과한다**
    (변이 테스트에서 실제로 살아남았다). 담보가 충분하다고 대출이 나오지 않는다.
    """
    b = Borrower(cash_krw=600_000_000, annual_income_krw=50_000_000)
    plan = build_purchase_plan(9 * OKU, b, prod_rules, prop=_prop())

    assert plan.required_loan_krw < plan.limits.ltv_krw, "LTV 로만 보면 통과하는 구간이어야 한다"
    assert plan.loan_feasible is False
    assert plan.limits.binding == "DSR"
    assert plan.over_limit_krw == plan.required_loan_krw - plan.limits.dsr_krw


def test_LTV_DSR이_여유로워도_6억_절대한도가_막으면_불가다(prod_rules):
    """소득·담보 다 되는데 수도권 주담대 6억 캡이 막는 경우(6.27 대책)."""
    b = Borrower(cash_krw=500_000_000, annual_income_krw=500_000_000)
    plan = build_purchase_plan(12 * OKU, b, prod_rules, prop=_prop())

    assert plan.required_loan_krw < plan.limits.ltv_krw
    assert plan.required_loan_krw < plan.limits.dsr_krw
    assert plan.loan_feasible is False
    assert plan.limits.binding == "CAP"
    assert plan.limits.effective_krw == 600_000_000


def test_다주택이면_세금이_늘어_필요자금이_커진다(prod_rules):
    first = build_purchase_plan(6 * OKU, _borrower(), prod_rules, prop=_prop())
    multi = build_purchase_plan(
        6 * OKU, Borrower(cash_krw=300_000_000, annual_income_krw=100_000_000,
                          owned_houses=2),
        prod_rules, prop=_prop())
    assert multi.total_needed_krw > first.total_needed_krw
    assert multi.required_loan_krw > first.required_loan_krw


# ---------------------------------------------------------------------------
# 가정 노출 (G2)
# ---------------------------------------------------------------------------

def test_응답에_금리_만기_가정이_실린다(prod_rules):
    payload = compute_affordability(_borrower(), prod_rules, prop=_prop(),
                                    target_price_krw=9 * OKU).to_api()
    terms = payload["plan"]["terms"]
    assert terms["annual_rate_pct"] == 4.0        # 요청은 0.04, 응답은 4.0 (퍼센트)
    assert terms["years"] == 30
    assert terms["repayment"] == "equal_total"    # 원리금균등
    assert terms["grace_months"] == 0             # 거치기간 없음


def test_금리를_바꾸면_상환액과_terms가_함께_바뀐다(prod_rules):
    b, prop = _borrower(), _prop()
    base = build_purchase_plan(6 * OKU, b, prod_rules, prop=prop,
                               terms=LoanTerms(annual_rate=0.04, years=30))
    higher = build_purchase_plan(6 * OKU, b, prod_rules, prop=prop,
                                 terms=LoanTerms(annual_rate=0.05, years=30))
    assert higher.monthly_payment_krw > base.monthly_payment_krw
    assert higher.to_api()["terms"]["annual_rate_pct"] == 5.0
    # 대출 원금은 그대로다 — 금리는 '얼마를 빌리나'가 아니라 '얼마를 갚나'를 바꾼다.
    # (한도는 줄어들 수 있다: DSR 은 상환액 기준이므로.)
    assert higher.required_loan_krw == base.required_loan_krw


def test_금리_민감도가_숫자로_고지된다(prod_rules):
    """'4%는 가정입니다'로 끝내지 않고 1%p 올랐을 때의 금액을 실제로 보여준다."""
    r = compute_affordability(_borrower(), prod_rules, prop=_prop(),
                              target_price_krw=6 * OKU)
    stressed = monthly_payment_krw(r.plan.required_loan_krw,
                                   LoanTerms(annual_rate=0.05, years=30))
    joined = " ".join(r.assumptions)
    assert f"{stressed:,}" in joined, joined
    assert "희망 매매가" in joined


def test_희망가_취득세_근거가_따로_실린다(prod_rules):
    """희망가가 최대 구매가와 다른 세율 구간일 수 있다 — 그 구간의 출처를 준다."""
    r = compute_affordability(_borrower(), prod_rules, prop=_prop(),
                              target_price_krw=15 * OKU)
    claims = [e["claim"] for e in r.evidence]
    assert any("희망 매매가" in c and "취득세" in c for c in claims), claims
    assert any("중개보수" in c for c in claims), claims
    for ev in r.evidence:
        assert ev["source"] and ev["as_of"], f"출처·기준일자 누락: {ev}"


def test_희망가를_안_주면_plan이_없다(prod_rules):
    r = compute_affordability(_borrower(), prod_rules, prop=_prop())
    assert r.plan is None
    assert "plan" not in r.to_api()


def test_희망가는_최대구매가를_바꾸지_않는다(prod_rules):
    """계획을 얹는 것이지 예산을 늘리는 게 아니다(사용자 입력으로 한도가 움직이면 G2 위반)."""
    b, prop = _borrower(), _prop()
    base = compute_affordability(b, prod_rules, prop=prop)
    for target in (1 * OKU, 9 * OKU, 90 * OKU):
        got = compute_affordability(b, prod_rules, prop=prop, target_price_krw=target)
        assert got.max_purchase_krw == base.max_purchase_krw
        assert got.limits.effective_krw == base.limits.effective_krw
