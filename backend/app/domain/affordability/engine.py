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

from dataclasses import dataclass, replace
from typing import Any

from app.domain.rules.loader import Bracket, LendingCap, LendingStress, RuleSet
from app.domain.affordability.models import (
    AffordabilityResult,
    Borrower,
    CostBreakdown,
    LoanLimits,
    LoanTerms,
    PropertyFacts,
    PurchasePlan,
)

#: 이분탐색 상한 (원). 개인 주택 구매에서 이 위는 의미 없다.
_UPPER_BOUND_KRW = 100_000_000_000


# ---------------------------------------------------------------------------
# 대출 원금 ↔ 상환액 환산 (원리금균등 · 월납 · 거치기간 없음)
#
# 두 함수는 **같은 식의 양방향**이다. 하나만 고치면 예산과 상환계획이 조용히 어긋난다.
#
#     M = P · i / (1 − (1+i)^−n)          (정방향: 원금 → 월 상환액)
#     P = M · (1 − (1+i)^−n) / i          (역방향: 월 상환액 → 원금)
#
# ⚠️ 거치기간(이자만 내는 기간)은 **가정하지 않는다.** 거치를 넣으면 초기 상환액이
#    작아 보이지만 총이자가 늘고 DSR 산정도 달라진다 — 상품마다 달라서 우리가 정할 값이 아니다.
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


def monthly_payment_krw(principal_krw: int, terms: LoanTerms) -> int:
    """대출 원금 → **월 원리금**(원리금균등, 월납).

        M = P · i / (1 − (1+i)^−n)

    `principal_from_annual_payment` 의 역함수다(반올림 오차 범위 안에서 왕복한다).

    왜 이게 필요한가: 지금까지는 "연 상환액 → 원금"만 있었다(한도 산정용). 그런데
    사용자가 실제로 묻는 건 **"이 집을 사면 매달 얼마를 내나"** 이고, 그건 반대 방향이다.
    """
    if principal_krw <= 0:
        return 0
    n = terms.years * 12
    i = terms.annual_rate / 12.0
    if i == 0:
        # 무이자면 원금을 개월수로 나눈다. 여기서 0 나눗셈이 나면 LoanTerms 가 막는다(years ≥ 1).
        return int(round(principal_krw / n))
    factor = i / (1.0 - (1.0 + i) ** (-n))
    return int(round(principal_krw * factor))


def total_interest_krw(principal_krw: int, terms: LoanTerms) -> int:
    """만기까지 낼 **이자 총액**. 월 상환액 × 회차 − 원금.

    ⚠️ 이 값은 금리 가정에 극도로 민감하다(4%→5% 면 30년 총이자가 30% 넘게 뛴다).
    그래서 응답에는 반드시 `terms` 를 함께 실어 어떤 가정의 숫자인지 밝힌다.
    """
    if principal_krw <= 0:
        return 0
    return max(0, monthly_payment_krw(principal_krw, terms) * terms.years * 12
               - principal_krw)


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

#: 취득세 규칙이 면적을 볼 때 쓰는 사실 이름. `engine` 이 `area=prop.area_m2` 로 넘긴다.
_AREA_FACT = "area"


def acquisition_area_class(rules: RuleSet, area_m2: float) -> tuple[Any, ...]:
    """**세율이 같아지는 면적끼리 묶는 키.**

    최대 구매가능 금액이 면적에 의존하는 경로는 취득세 하나뿐이다
    (`acquisition_cost` 만 `prop.area_m2` 를 쓴다 — 대출 한도는 면적을 안 본다).
    그리고 취득세 구간은 `when` 의 `area`·`area_max`·`area_min` 으로만 면적을 본다.
    따라서 **모든 구간에서 같은 판정을 받는 두 면적**은 어떤 가격·주택수·규제
    조합에서도 같은 구간이 잡히고, 한도도 같다.

    쓰는 곳: 지도(`/map/complexes`)는 한 화면에서 최대 500단지의 한도를 **면적별로**
    계산해야 한다. 면적마다 이분탐색을 새로 돌리면 실측 0.75ms × 500 = 375ms 로
    지도 응답(SQL 125~157ms)보다 오래 걸린다. 이 키로 묶으면 운영 세율에서는
    계산이 **2회**(85㎡ 이하 / 초과)로 줄어든다.

    ⚠️ **모르면 묶지 않는다.** 다음 두 경우에는 면적 자체를 키에 넣어 캐시를 끈다 —
       ① 누진 산식의 기준(`progressive.basis`)이 면적인 규칙이 있다(세율이 면적에
          **연속으로** 달라져 구간 판정이 같아도 세율이 다르다),
       ② `when` 에 우리가 모르는 면적 조건 문법(`area_*`)이 있다(로더가 문법을
          늘리면 이 함수가 조용히 낡는다 — 낡은 채 묶는 것보다 안 묶는 게 낫다).
    """
    flags: list[Any] = []
    unbucketable = False
    for bracket in rules.acquisition_tax:
        for key, expected in bracket.when.items():
            if key == _AREA_FACT:
                flags.append(area_m2 == expected)
            elif key == f"{_AREA_FACT}_max":
                flags.append(area_m2 <= expected)
            elif key == f"{_AREA_FACT}_min":
                flags.append(area_m2 >= expected)
            elif key.startswith(_AREA_FACT):
                unbucketable = True
        if bracket.progressive is not None and bracket.progressive.basis == _AREA_FACT:
            unbucketable = True
    if unbucketable:
        flags.append(("exact", area_m2))
    return tuple(flags)


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


@dataclass(frozen=True)
class _LendingSetup:
    """규칙 조회 결과를 한 번만 뽑아 들고 다니는 묶음.

    **왜 묶는가**: 최대 구매가(역방향)와 희망가 자금계획(정방향)이 각자 규칙을 조회하면
    LTV·DSR·6억캡·스트레스금리가 두 벌이 된다. 그러면 언젠가 한쪽만 바뀌어
    "최대 8.4억까지 가능"이라면서 "8.4억은 대출 한도 초과"라고 말하는 화면이 나온다.
    한도를 만드는 곳은 여기 하나뿐이어야 한다.
    """

    rules: RuleSet
    terms: LoanTerms
    #: DSR **한도 산정 전용** 금리(실제 금리 + 스트레스 가산). 상환액 계산엔 쓰지 않는다.
    stress_terms: LoanTerms
    region_group: str
    ltv_pct: float
    dsr_pct: float
    dti_pct: float | None
    cap_krw: int | None
    stress_pct: float
    ltv_rule: Bracket
    dsr_rule: Bracket
    dti_rule: Bracket | None
    cap_rule: LendingCap | None
    stress_rule: LendingStress | None

    def limits_at(self, price_krw: int, borrower: Borrower) -> LoanLimits:
        return _limits_at(price_krw, borrower, self.terms, self.rules,
                          self.ltv_pct, self.dsr_pct, self.dti_pct,
                          stress_terms=self.stress_terms, cap_krw=self.cap_krw)


def _lending_setup(rules: RuleSet, terms: LoanTerms,
                   prop: PropertyFacts) -> _LendingSetup:
    ltv_rule = rules.lending_rule("ltv")
    dsr_rule = rules.lending_rule("dsr")
    dti_rule = rules.lending.get("dti") if terms.apply_dti else None

    # 권역은 서버 판정(사용자 입력 아님). 대상지역이 수도권 전체라 기본이 수도권=캡 적용.
    region_group = prop.effective_region_group
    cap_facts = dict(region_group=region_group, regulated=prop.is_regulated_area,
                     purpose=prop.purpose)
    cap_rule = rules.absolute_cap(**cap_facts)
    stress_rule = rules.stress_rule(**cap_facts)
    stress_pct = stress_rule.stress_rate_pct if stress_rule else 0.0

    return _LendingSetup(
        rules=rules,
        terms=terms,
        # 스트레스 DSR: 한도 산정용 **가정 금리**. 실제 상환금리가 아니다
        # (둘을 섞으면 사용자에게 보여줄 월 상환액이 실제보다 커진다).
        stress_terms=replace(terms, annual_rate=terms.annual_rate + stress_pct / 100.0),
        region_group=region_group,
        ltv_pct=ltv_rule.rate_pct,
        dsr_pct=dsr_rule.rate_pct,
        dti_pct=dti_rule.rate_pct if dti_rule else None,
        cap_krw=cap_rule.cap_krw if cap_rule else None,
        stress_pct=stress_pct,
        ltv_rule=ltv_rule,
        dsr_rule=dsr_rule,
        dti_rule=dti_rule,
        cap_rule=cap_rule,
        stress_rule=stress_rule,
    )


# ---------------------------------------------------------------------------
# 희망 매매가 기준 자금계획 (정방향)
# ---------------------------------------------------------------------------

def _build_plan(target_price_krw: int, borrower: Borrower, rules: RuleSet,
                prop: PropertyFacts, setup: _LendingSetup,
                usable_cash_krw: int) -> PurchasePlan:
    """희망가 하나에 대한 자금계획. **부대비용은 기존 엔진(`acquisition_cost`)을 그대로 쓴다.**

    여기서 세금·중개보수를 다시 계산하지 않는 이유: 두 벌이 되는 순간 한쪽만 세법 개정을
    따라가고, 최대 구매가와 자금계획이 서로 다른 세율을 쓰는 화면이 만들어진다.
    """
    costs = acquisition_cost(target_price_krw, rules, borrower, prop)
    total_needed = target_price_krw + costs.total_krw

    # 부족분은 0 에서 자른다 — 현금이 남는 건 '음수 부족액'이 아니라 '대출 불필요'다.
    shortfall = max(0, total_needed - usable_cash_krw)
    required_loan = shortfall

    limits = setup.limits_at(target_price_krw, borrower)
    feasible = required_loan <= limits.effective_krw
    # 한도를 넘어도 멈추지 않는다. 얼마가 모자란지를 숫자로 준다.
    over_limit = None if feasible else required_loan - limits.effective_krw
    feasible_loan = min(required_loan, limits.effective_krw)

    return PurchasePlan(
        target_price_krw=target_price_krw,
        costs=costs,
        total_needed_krw=total_needed,
        own_cash_krw=usable_cash_krw,
        shortfall_krw=shortfall,
        required_loan_krw=required_loan,
        limits=limits,
        loan_feasible=feasible,
        over_limit_krw=over_limit,
        feasible_loan_krw=feasible_loan,
        # 실제 상환액은 **계약 금리**로 계산한다(스트레스 금리는 한도 산정용일 뿐).
        monthly_payment_krw=monthly_payment_krw(required_loan, setup.terms),
        monthly_payment_feasible_krw=monthly_payment_krw(feasible_loan, setup.terms),
        total_interest_krw=total_interest_krw(required_loan, setup.terms),
        terms=setup.terms,
    )


def build_purchase_plan(target_price_krw: int, borrower: Borrower, rules: RuleSet,
                        *, terms: LoanTerms | None = None,
                        prop: PropertyFacts | None = None) -> PurchasePlan:
    """희망 매매가 기준 자금계획을 단독으로 계산한다(도메인 공개 API).

    `compute_affordability(target_price_krw=...)` 가 같은 함수를 호출하므로
    두 경로의 숫자는 정의상 동일하다.
    """
    terms = terms or LoanTerms()
    prop = prop or PropertyFacts()
    setup = _lending_setup(rules, terms, prop)
    reserve = int(rules.fixed_costs.get("moving_reserve_krw", 0))
    usable_cash = max(0, borrower.cash_krw - reserve)
    return _build_plan(target_price_krw, borrower, rules, prop, setup, usable_cash)


def compute_affordability(
    borrower: Borrower,
    rules: RuleSet,
    *,
    terms: LoanTerms | None = None,
    prop: PropertyFacts | None = None,
    target_price_krw: int | None = None,
) -> AffordabilityResult:
    """부등식을 만족하는 최대 구매가를 이분탐색으로 구한다.

    `target_price_krw`(희망 매매가)를 주면 **같은 규칙·같은 부대비용 엔진**으로
    그 가격의 자금계획(`result.plan`)을 함께 만든다. 안 주면 기존 동작 그대로다.
    """
    terms = terms or LoanTerms()
    prop = prop or PropertyFacts()

    setup = _lending_setup(rules, terms, prop)
    ltv_rule, dsr_rule, dti_rule = setup.ltv_rule, setup.dsr_rule, setup.dti_rule
    cap_rule, stress_rule = setup.cap_rule, setup.stress_rule
    cap_krw, stress_pct, region_group = setup.cap_krw, setup.stress_pct, setup.region_group

    def limits_at(price: int) -> LoanLimits:
        return setup.limits_at(price, borrower)

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

    # 희망 매매가 자금계획 — 최대 구매가와 **같은 setup·같은 부대비용 엔진**을 쓴다.
    plan = (None if target_price_krw is None else
            _build_plan(target_price_krw, borrower, rules, prop, setup, usable_cash))

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
    if plan is not None:
        # 희망가는 최대 구매가와 **다른 세율 구간**일 수 있다(6억/9억 경계). 위 근거를
        # 그대로 두면 화면의 세금 숫자와 출처가 어긋나므로, 희망가 구간 근거를 따로 싣는다.
        plan_rule = rules.acquisition_bracket(
            houses_owned=borrower.owned_houses + 1, price=plan.target_price_krw,
            area=prop.area_m2, regulated=prop.is_regulated_area)
        if plan_rule.provenance is not None:
            plan_pct = plan_rule.total_rate_pct(
                price=plan.target_price_krw, area=prop.area_m2,
                houses_owned=borrower.owned_houses + 1,
                regulated=prop.is_regulated_area)
            evidence.append(plan_rule.provenance.to_evidence(
                f"희망 매매가 {plan.target_price_krw:,}원 취득세 {plan_pct:.3f}%"))
        brk_rule = rules.brokerage_bracket(price=plan.target_price_krw)
        if brk_rule.provenance is not None:
            evidence.append(brk_rule.provenance.to_evidence(
                f"중개보수 상한 {brk_rule.rate_pct}%"))
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

    if plan is not None:
        assumptions.extend(_plan_assumptions(plan, terms))
        if not plan.loan_feasible:
            # ⚠️ "불가능합니다"로 끝내지 않는다. 얼마가 모자란지·무엇이 막는지를 같이 말한다.
            warnings.append(
                f"희망 매매가 {plan.target_price_krw:,}원에 필요한 대출 "
                f"{plan.required_loan_krw:,}원이 한도 {plan.limits.effective_krw:,}원"
                f"({plan.limits.binding} 기준)을 {plan.over_limit_krw:,}원 초과합니다 — "
                f"현금 {plan.over_limit_krw:,}원을 더 준비하거나 희망가를 낮춰야 합니다")

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
        plan=plan,
    )


#: 금리 민감도를 보여줄 때 더하는 폭(%p). "4%는 가정"이라고 문장으로만 말하면
#: 사용자는 그게 얼마나 큰 차이인지 감이 없다 — **숫자로** 보여준다.
RATE_SENSITIVITY_PCT = 1.0


def _plan_assumptions(plan: PurchasePlan, terms: LoanTerms) -> list[str]:
    """자금계획에 붙는 가정. **금리·만기가 가정이라는 사실**을 숫자로 만든다(G2)."""
    out = [
        f"희망 매매가 {plan.target_price_krw:,}원 기준 자금계획입니다 "
        f"— '최대 실구매 가능 금액'과는 별개 계산입니다",
        f"월 원리금은 연 {terms.annual_rate * 100:.2f}% · {terms.years}년 "
        f"원리금균등·거치기간 없음 가정입니다(실제 금리는 계약 시점에 확정됩니다)",
    ]
    if plan.required_loan_krw > 0:
        stressed = replace(terms,
                           annual_rate=terms.annual_rate + RATE_SENSITIVITY_PCT / 100.0)
        out.append(
            f"금리 가정이 {RATE_SENSITIVITY_PCT:g}%p 오르면"
            f"(연 {stressed.annual_rate * 100:.2f}%) 월 원리금은 "
            f"{monthly_payment_krw(plan.required_loan_krw, stressed):,}원이 됩니다")
    return out
