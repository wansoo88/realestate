"""실구매 가능 금액 계산 엔진.

설계 근거: docs/02-design/agents/02-finance-tax-advisor.md

⛔ 이 모듈은 LLM 을 쓰지 않는다. 전부 결정론적 계산이다.
   세율을 LLM 에 물어보면 그럴듯하게 틀리고, 그 오류는 수천만 원 단위다.

핵심 — 왜 단순 덧셈이 아닌가
----------------------------
    가용현금 + 대출한도  ≥  집값 + 취득부대비용

여기서 **대출한도가 집값의 함수**다. LTV 한도는 `집값 × LTV%` 이기 때문이다.
그래서 `현금 + 한도` 를 먼저 더하고 거기서 세금을 빼는 방식은 **예산을 과대 산정**한다.
아래처럼 부등식을 만족하는 최대 P 를 이분탐색으로 찾아야 한다.

    f(P) = P + cost(P) − min(P×LTV, DSR한도, DTI한도)  ≤  가용현금

f(P) 는 P 에 대해 단조 비감소(세율 구간 점프 포함)이므로 이분탐색이 성립한다.

퍼센트 규약
-----------
설정의 모든 `rate_pct` 와 `extras.*_pct` 는 **거래금액 대비 퍼센트**로 통일한다.
(취득세 1.0% + 지방교육세 0.1% = 실효 1.1% 처럼 합산해서 쓴다.)
이렇게 하지 않으면 "지방교육세가 취득세의 10%인지 집값의 0.1%인지" 가 애매해져
계산이 조용히 틀어진다.
"""
from __future__ import annotations

from typing import Any

from app.domain.rules.loader import Bracket, RuleSet
from app.domain.affordability.models import (
    AffordabilityResult,
    Borrower,
    CostBreakdown,
    LoanLimits,
    LoanTerms,
    PropertyFacts,
)

#: 이분탐색 상한 (원). 개인 주택 구매에서 이 위는 의미 없다.
_UPPER_BOUND_KRW = 100_000_000_000


# ---------------------------------------------------------------------------
# 대출 원금 환산
# ---------------------------------------------------------------------------

def principal_from_annual_payment(annual_payment_krw: float, terms: LoanTerms) -> int:
    """연간 원리금상환액으로 감당 가능한 **대출 원금**(원리금균등, 월납).

        M = P · i / (1 − (1+i)^−n)      →      P = M · (1 − (1+i)^−n) / i
    """
    if annual_payment_krw <= 0:
        return 0
    monthly = annual_payment_krw / 12.0
    n = terms.years * 12
    i = terms.annual_rate / 12.0
    if i == 0:
        return int(monthly * n)
    factor = (1.0 - (1.0 + i) ** (-n)) / i
    return int(monthly * factor)


def dsr_limit(borrower: Borrower, terms: LoanTerms, dsr_pct: float) -> int:
    """DSR: 모든 대출의 연간 원리금상환액 / 연소득 ≤ 상한."""
    allowed = borrower.annual_income_krw * (dsr_pct / 100.0) - borrower.existing_annual_repayment_krw
    return principal_from_annual_payment(allowed, terms)


def dti_limit(borrower: Borrower, terms: LoanTerms, dti_pct: float) -> int:
    """DTI: 주담대 원리금 + 기타대출 **이자** / 연소득 ≤ 상한."""
    allowed = borrower.annual_income_krw * (dti_pct / 100.0) - borrower.existing_annual_interest_krw
    return principal_from_annual_payment(allowed, terms)


# ---------------------------------------------------------------------------
# 취득 부대비용
# ---------------------------------------------------------------------------

def _pct_total(bracket: Bracket) -> float:
    """본세율 + 부가세율(모두 거래금액 대비 %)."""
    return bracket.rate_pct + sum(
        v for k, v in bracket.extras.items() if k.endswith("_pct")
    )


def acquisition_cost(price_krw: int, rules: RuleSet, borrower: Borrower,
                     prop: PropertyFacts) -> CostBreakdown:
    """취득세 + 중개보수 + 등기·법무. 구간을 못 찾으면 추정하지 않고 예외를 던진다."""
    houses_after = borrower.owned_houses + 1
    acq = rules.acquisition_bracket(
        houses_owned=houses_after,
        price=price_krw,
        area=prop.area_m2,
        regulated=prop.is_regulated_area,
    )
    tax = int(price_krw * _pct_total(acq) / 100.0)

    brk = rules.brokerage_bracket(price=price_krw)
    fee = int(price_krw * brk.rate_pct / 100.0)
    cap = brk.extras.get("cap_krw")
    if cap is not None:
        fee = min(fee, int(cap))

    registration = int(rules.fixed_costs.get("registration_krw", 0))
    return CostBreakdown(
        acquisition_tax_krw=tax,
        brokerage_krw=fee,
        registration_krw=registration,
        total_krw=tax + fee + registration,
    )


# ---------------------------------------------------------------------------
# 본 계산
# ---------------------------------------------------------------------------

def _limits_at(price_krw: int, borrower: Borrower, terms: LoanTerms,
               rules: RuleSet, ltv_pct: float, dsr_pct: float,
               dti_pct: float | None) -> LoanLimits:
    ltv = int(price_krw * ltv_pct / 100.0)
    dsr = dsr_limit(borrower, terms, dsr_pct)
    dti = dti_limit(borrower, terms, dti_pct) if dti_pct is not None else None

    candidates: list[tuple[str, int]] = [("LTV", ltv), ("DSR", dsr)]
    if dti is not None:
        candidates.append(("DTI", dti))
    binding, effective = min(candidates, key=lambda kv: kv[1])
    return LoanLimits(ltv_krw=ltv, dsr_krw=dsr, dti_krw=dti,
                      effective_krw=effective, binding=binding)


def compute_affordability(
    borrower: Borrower,
    rules: RuleSet,
    *,
    terms: LoanTerms | None = None,
    prop: PropertyFacts | None = None,
) -> AffordabilityResult:
    """부등식을 만족하는 최대 구매가를 이분탐색으로 구한다."""
    terms = terms or LoanTerms()
    prop = prop or PropertyFacts()

    ltv_rule = rules.lending_rule("ltv")
    dsr_rule = rules.lending_rule("dsr")
    dti_rule = rules.lending.get("dti") if terms.apply_dti else None

    ltv_pct = ltv_rule.rate_pct
    dsr_pct = dsr_rule.rate_pct
    dti_pct = dti_rule.rate_pct if dti_rule else None

    reserve = int(rules.fixed_costs.get("moving_reserve_krw", 0))
    usable_cash = max(0, borrower.cash_krw - reserve)

    def shortfall(price: int) -> int:
        """f(P) − 가용현금. 0 이하이면 감당 가능."""
        cost = acquisition_cost(price, rules, borrower, prop)
        limits = _limits_at(price, borrower, terms, rules, ltv_pct, dsr_pct, dti_pct)
        return price + cost.total_krw - limits.effective_krw - usable_cash

    # 이분탐색: shortfall(P) <= 0 인 최대 P
    lo, hi = 0, _UPPER_BOUND_KRW
    if shortfall(1) > 0:
        max_price = 0
    else:
        while lo < hi:
            mid = (lo + hi + 1) // 2
            if shortfall(mid) <= 0:
                lo = mid
            else:
                hi = mid - 1
        max_price = lo

    # 만원 단위로 내림 — 원 단위 정밀도는 의미가 없고 과대 표기로 보인다
    max_price = (max_price // 10_000) * 10_000

    if max_price <= 0:
        costs = CostBreakdown(0, 0, 0, 0)
        limits = _limits_at(0, borrower, terms, rules, ltv_pct, dsr_pct, dti_pct)
        loan = 0
        binding = "CASH"
    else:
        costs = acquisition_cost(max_price, rules, borrower, prop)
        limits = _limits_at(max_price, borrower, terms, rules, ltv_pct, dsr_pct, dti_pct)
        loan = max(0, max_price + costs.total_krw - usable_cash)
        loan = min(loan, limits.effective_krw)
        # 대출을 한도까지 안 쓰고도 살 수 있으면 현금이 아니라 한도가 아닌 게 제약
        binding = limits.binding if loan >= limits.effective_krw - 10_000 else "CASH"

    evidence: list[dict[str, Any]] = []
    for label, rule in (("취득세", rules.acquisition_bracket(
                            houses_owned=borrower.owned_houses + 1,
                            price=max(max_price, 1),
                            area=prop.area_m2,
                            regulated=prop.is_regulated_area) if max_price > 0 else None),
                        ("LTV 상한", ltv_rule), ("DSR 상한", dsr_rule),
                        ("DTI 상한", dti_rule)):
        if rule is None or rule.provenance is None:
            continue
        pct = _pct_total(rule) if label == "취득세" else rule.rate_pct
        evidence.append(rule.provenance.to_evidence(f"{label} {pct}%"))

    assumptions = [
        f"금리 연 {terms.annual_rate * 100:.2f}% · 만기 {terms.years}년 원리금균등 가정",
        f"이사·수리 예비비 {reserve:,}원을 가용현금에서 제외",
        f"세율 설정 버전 {rules.version}",
    ]
    if not terms.apply_dti:
        assumptions.append("DTI 미적용 지역으로 가정")

    warnings: list[str] = []
    stale = rules.stale_rules()
    if stale:
        warnings.append("기준일자가 오래된 규칙이 있습니다: " + ", ".join(stale))

    return AffordabilityResult(
        max_purchase_krw=max_price,
        usable_cash_krw=usable_cash,
        loan_krw=loan,
        limits=limits,
        costs=costs,
        binding_constraint=binding,
        assumptions=assumptions,
        evidence=evidence,
        warnings=warnings,
    )
