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

from dataclasses import replace
from typing import Any

from app.domain.rules.loader import RuleSet
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
    # 누진 밴드(6~9억)면 산식으로, 고정구간이면 기존과 같은 값. `total_rate_pct` 가
    # 본세 + 정률부가세(extras.*_pct) + 본세연동부가세(extras_ratio)를 전부 합산한다.
    tax = int(price_krw * acq.total_rate_pct(
        price=price_krw, area=prop.area_m2,
        houses_owned=houses_after, regulated=prop.is_regulated_area) / 100.0)

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
               dti_pct: float | None, *,
               stress_terms: LoanTerms | None = None,
               cap_krw: int | None = None) -> LoanLimits:
    ltv = int(price_krw * ltv_pct / 100.0)
    # DSR 한도는 **스트레스 금리**로 산정한다(더 보수적). 실제 상환액 계산엔 쓰지 않는다.
    dsr = dsr_limit(borrower, stress_terms or terms, dsr_pct)
    dti = dti_limit(borrower, terms, dti_pct) if dti_pct is not None else None

    candidates: list[tuple[str, int]] = [("LTV", ltv), ("DSR", dsr)]
    if dti is not None:
        candidates.append(("DTI", dti))
    if cap_krw is not None:
        # 절대한도도 경합 후보 — 가장 작은 게 실제 제약이다.
        # 큰 쪽을 고르면 빌릴 수 없는 금액을 빌릴 수 있다고 말하게 된다.
        candidates.append(("CAP", cap_krw))
    binding, effective = min(candidates, key=lambda kv: kv[1])
    return LoanLimits(ltv_krw=ltv, dsr_krw=dsr, dti_krw=dti, cap_krw=cap_krw,
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

    # 권역은 서버 판정(사용자 입력 아님). 대상지역이 수도권 전체라 기본이 수도권=캡 적용.
    region_group = prop.effective_region_group
    cap_facts = dict(region_group=region_group, regulated=prop.is_regulated_area,
                     purpose=prop.purpose)
    cap_rule = rules.absolute_cap(**cap_facts)
    cap_krw = cap_rule.cap_krw if cap_rule else None

    # 스트레스 DSR: 한도 산정용 **가정 금리**. 실제 상환금리가 아니다(둘을 섞으면 상환액이 커 보인다).
    stress_rule = rules.stress_rule(**cap_facts)
    stress_pct = stress_rule.stress_rate_pct if stress_rule else 0.0
    stress_terms = replace(terms, annual_rate=terms.annual_rate + stress_pct / 100.0)

    def limits_at(price: int) -> LoanLimits:
        return _limits_at(price, borrower, terms, rules, ltv_pct, dsr_pct, dti_pct,
                          stress_terms=stress_terms, cap_krw=cap_krw)

    reserve = int(rules.fixed_costs.get("moving_reserve_krw", 0))
    usable_cash = max(0, borrower.cash_krw - reserve)

    def shortfall(price: int) -> int:
        """f(P) − 가용현금. 0 이하이면 감당 가능."""
        cost = acquisition_cost(price, rules, borrower, prop)
        return price + cost.total_krw - limits_at(price).effective_krw - usable_cash

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
        limits = limits_at(0)
        loan = 0
        binding = "CASH"
    else:
        costs = acquisition_cost(max_price, rules, borrower, prop)
        limits = limits_at(max_price)
        loan = max(0, max_price + costs.total_krw - usable_cash)
        loan = min(loan, limits.effective_krw)
        # 대출을 한도까지 안 쓰고도 살 수 있으면 현금이 아니라 한도가 아닌 게 제약
        binding = limits.binding if loan >= limits.effective_krw - 10_000 else "CASH"

    evidence: list[dict[str, Any]] = []
    if max_price > 0:
        acq_rule = rules.acquisition_bracket(
            houses_owned=borrower.owned_houses + 1, price=max_price,
            area=prop.area_m2, regulated=prop.is_regulated_area)
        if acq_rule.provenance is not None:
            acq_pct = acq_rule.total_rate_pct(
                price=max_price, area=prop.area_m2,
                houses_owned=borrower.owned_houses + 1,
                regulated=prop.is_regulated_area)
            evidence.append(acq_rule.provenance.to_evidence(f"취득세 {acq_pct:.3f}%"))
    for label, rule in (("LTV 상한", ltv_rule), ("DSR 상한", dsr_rule),
                        ("DTI 상한", dti_rule)):
        if rule is None or rule.provenance is None:
            continue
        evidence.append(rule.provenance.to_evidence(f"{label} {rule.rate_pct}%"))
    if cap_rule is not None and cap_rule.provenance is not None:
        evidence.append(cap_rule.provenance.to_evidence(
            f"주담대 절대한도 {cap_rule.cap_krw:,}원"))
    if stress_rule is not None and stress_rule.provenance is not None:
        evidence.append(stress_rule.provenance.to_evidence(
            f"스트레스 DSR 가산 {stress_rule.stress_rate_pct}%p"))

    assumptions = [
        f"금리 연 {terms.annual_rate * 100:.2f}% · 만기 {terms.years}년 원리금균등 가정",
        f"이사·수리 예비비 {reserve:,}원을 가용현금에서 제외",
        f"세율 설정 버전 {rules.version}",
    ]
    if stress_pct > 0:
        assumptions.append(
            f"스트레스 DSR {stress_pct}%p 가산 적용(한도 산정용 가정 금리, 실제 상환금리 아님)")
    if cap_krw is not None:
        assumptions.append(f"{region_group} 주담대 절대한도 {cap_krw:,}원 적용")
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
