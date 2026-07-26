"""자금 계산 입출력 모델. 순수 데이터클래스 — DB·프레임워크 무관."""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass(frozen=True)
class Borrower:
    """차주 정보. 금액은 모두 **원 단위 정수**."""

    cash_krw: int
    annual_income_krw: int
    #: 기존 대출의 연간 원리금상환액 (DSR 계산에 들어간다)
    existing_annual_repayment_krw: int = 0
    #: 기존 대출의 연간 이자 (DTI 계산에 들어간다)
    existing_annual_interest_krw: int = 0
    owned_houses: int = 0
    household_size: int = 1

    def __post_init__(self) -> None:
        for name in ("cash_krw", "annual_income_krw",
                     "existing_annual_repayment_krw", "existing_annual_interest_krw"):
            if getattr(self, name) < 0:
                raise ValueError(f"{name} 는 음수일 수 없습니다")
        if self.owned_houses < 0:
            raise ValueError("owned_houses 는 음수일 수 없습니다")


@dataclass(frozen=True)
class LoanTerms:
    """대출 조건 가정. 실제 한도는 금융기관 심사로 달라진다 — 반드시 고지할 것."""

    annual_rate: float = 0.04     # 연 4.0%
    years: int = 30
    #: DTI 를 적용하지 않는 지역이면 None
    apply_dti: bool = False

    def __post_init__(self) -> None:
        if self.annual_rate < 0:
            raise ValueError("annual_rate 는 음수일 수 없습니다")
        if self.years <= 0:
            raise ValueError("years 는 1 이상이어야 합니다")


@dataclass(frozen=True)
class PropertyFacts:
    """대상 주택의 세율·대출한도 판정에 필요한 사실."""

    area_m2: float = 84.0
    is_regulated_area: bool = False
    purpose: str = "live"          # live | invest
    #: 수도권 여부. 6억 절대한도(6.27 대책)가 수도권 조건부라 이 사실이 있어야 매칭된다.
    #: ⚠️ **사용자(클라이언트)가 보내는 값이 아니다** — API 요청 스키마에 필드가 없다(CR10-1).
    #: 사용자가 바꿀 수 있으면 캡을 우회해 예산을 부풀릴 수 있어 G2 위반이기 때문이다.
    #: 서버가 판정한다: 대상지역이 수도권 전체라 **기본은 수도권**, 특정 단지를 다룰 땐
    #: 그 단지 법정동코드(PostGIS)로 채운다. 직접 `"수도권"`/`"비수도권"` 지정도 가능.
    region_group: str | None = None
    #: 법정동코드(앞 2자리로 region_group 파생). **서버가** 단지 좌표→법정동에서 채운다.
    target_region_code: str | None = None

    @staticmethod
    def region_group_from_code(code: str | None) -> str | None:
        """법정동코드 앞 2자리 → 권역. 11(서울)·41(경기)·28(인천) → 수도권, 그 외 → 비수도권.

        코드가 없으면 None → `effective_region_group` 이 안전기본(수도권)으로 메운다.
        """
        if not code:
            return None
        return "수도권" if str(code)[:2] in ("11", "41", "28") else "비수도권"

    @property
    def effective_region_group(self) -> str:
        """명시값 우선 → 코드 파생 → **기본 수도권(캡 적용)**.

        이 제품 대상지역이 수도권 전체다. 모를 때 캡을 끄면(무캡) 예산이 **과대 산정**돼
        고치려던 버그로 되돌아간다. 그래서 **안전한 기본은 캡 적용(수도권)** 이고,
        비수도권은 명시적 예외다. 서버 판정값이라 사용자가 유리하게 바꿀 수 없다(G2).
        """
        return (self.region_group
                or self.region_group_from_code(self.target_region_code)
                or "수도권")


@dataclass(frozen=True)
class CostBreakdown:
    acquisition_tax_krw: int
    brokerage_krw: int
    registration_krw: int
    total_krw: int


@dataclass(frozen=True)
class LoanLimits:
    ltv_krw: int
    dsr_krw: int
    dti_krw: int | None
    effective_krw: int
    binding: str                   # LTV | DSR | DTI | CAP
    #: 대출 절대한도(예: 수도권 주담대 6억). 해당 규칙이 없으면 None.
    cap_krw: int | None = None


@dataclass(frozen=True)
class PurchasePlan:
    """**희망 매매가 기준** 자금계획.

    `AffordabilityResult` 가 "최대 얼마까지 살 수 있나"(역방향)라면 이쪽은
    "이 가격이면 얼마가 더 필요하고 매달 얼마를 갚나"(정방향)다. 둘은 **같은 부등식**의
    양쪽 끝이라 서로 모순될 수 없어야 한다 —

        loan_feasible  ⟺  target_price ≤ max_purchase_krw

    두 값이 어긋나면 어느 한쪽이 틀린 것이다(테스트가 이 등가를 못박는다).

    ⚠️ 한도를 넘어도 **계산은 끝까지 한다.** "불가능합니다"만 띄우면 사용자는
    *얼마를 더 모아야 하는지* 알 수 없다. 그래서 `over_limit_krw`(모자란 현금)와
    `binding`(무엇이 막았는가)을 함께 준다.
    """

    target_price_krw: int
    costs: CostBreakdown
    #: 매매가 + 취득 부대비용 (실제로 준비해야 하는 총액)
    total_needed_krw: int
    #: 내가 지금 낼 수 있는 현금 = 보유현금 − 이사·수리 예비비.
    #: `AffordabilityResult.usable_cash_krw` 와 **반드시 같은 값**이다 —
    #: 화면에 "내 돈"이 두 개 뜨면 사용자는 어느 쪽을 믿어야 할지 모른다.
    own_cash_krw: int
    #: 더 필요한 돈 (= total_needed − own_cash, 음수는 0 으로 자른다)
    shortfall_krw: int
    #: 필요 대출 (부족분 전액을 대출로 메운다는 전제)
    required_loan_krw: int
    limits: LoanLimits
    loan_feasible: bool
    #: 한도 초과분(불가일 때만). **이 금액만큼 현금이 더 필요하다**는 뜻이다.
    over_limit_krw: int | None
    #: 한도 안에서 실제로 받을 수 있는 금액 = min(필요대출, 한도).
    #: 계약 필수 필드는 아니지만 이게 없으면 "그래서 얼마는 빌릴 수 있는데?"에 답을 못 한다.
    feasible_loan_krw: int
    #: 필요 대출 전액을 빌렸다고 가정한 월 원리금(원리금균등·거치 없음).
    monthly_payment_krw: int
    #: 한도까지만 빌렸을 때의 월 원리금. 한도 안이면 `monthly_payment_krw` 와 같다.
    monthly_payment_feasible_krw: int
    #: 만기까지 낼 이자 총액(필요 대출 기준). 금리 가정이 바뀌면 크게 움직인다.
    total_interest_krw: int
    terms: LoanTerms

    def to_api(self) -> dict[str, Any]:
        return {
            "target_price_krw": self.target_price_krw,
            "total_needed_krw": self.total_needed_krw,
            "cost_breakdown": {
                "tax": self.costs.acquisition_tax_krw,
                "brokerage": self.costs.brokerage_krw,
                # 계약상 키는 `etc` 다. 내부 이름(registration)과 다르지만 여기서만 바꾼다 —
                # 등기·법무 외 항목이 늘어도 응답 키가 흔들리지 않게 하려는 것이다.
                "etc": self.costs.registration_krw,
                "total": self.costs.total_krw,
            },
            "own_cash_krw": self.own_cash_krw,
            "shortfall_krw": self.shortfall_krw,
            "required_loan_krw": self.required_loan_krw,
            "loan_feasible": self.loan_feasible,
            "loan_limit_krw": self.limits.effective_krw,
            "over_limit_krw": self.over_limit_krw,
            "binding_constraint": self.limits.binding,
            "feasible_loan_krw": self.feasible_loan_krw,
            "monthly_payment_krw": self.monthly_payment_krw,
            "monthly_payment_feasible_krw": self.monthly_payment_feasible_krw,
            "total_interest_krw": self.total_interest_krw,
            "terms": {
                # 요청은 소수(0.04), 응답은 퍼센트(4.0)다 — 단위를 응답 필드명에 박아
                # 프론트가 100 을 곱할지 말지 헷갈리지 않게 한다.
                "annual_rate_pct": round(self.terms.annual_rate * 100, 4),
                "years": self.terms.years,
                "repayment": "equal_total",   # 원리금균등
                "grace_months": 0,            # 거치기간 없음(가정)
            },
        }


@dataclass(frozen=True)
class AffordabilityResult:
    """`POST /affordability` 응답의 원천."""

    max_purchase_krw: int
    usable_cash_krw: int
    loan_krw: int
    limits: LoanLimits
    costs: CostBreakdown
    binding_constraint: str
    assumptions: list[str] = field(default_factory=list)
    evidence: list[dict[str, Any]] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    #: 희망 매매가를 준 경우에만 채워진다. 안 주면 None → 응답에 `plan` 키가 없다.
    plan: PurchasePlan | None = None

    def to_api(self) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "max_purchase_krw": self.max_purchase_krw,
            "breakdown": {
                "own_cash_krw": self.usable_cash_krw,
                "max_loan_krw": self.loan_krw,
                "ltv_limit_krw": self.limits.ltv_krw,
                "dsr_limit_krw": self.limits.dsr_krw,
                "dti_limit_krw": self.limits.dti_krw,
                "absolute_cap_krw": self.limits.cap_krw,
                "binding_constraint": self.binding_constraint,
            },
            "acquisition_cost_krw": {
                "tax": self.costs.acquisition_tax_krw,
                "brokerage": self.costs.brokerage_krw,
                "registration": self.costs.registration_krw,
                "total": self.costs.total_krw,
            },
            "assumptions": self.assumptions,
            "evidence": self.evidence,
            "warnings": self.warnings,
            "disclaimer": "실제 한도는 금융기관 심사에 따라 달라집니다. "
                          "투자 권유가 아니며 개인 판단을 돕는 참고 자료입니다.",
        }
        # 희망가를 안 줬으면 키 자체를 넣지 않는다. `"plan": null` 로 내보내면
        # "계획이 없다"와 "계획이 실패했다"를 프론트가 구분할 수 없다.
        if self.plan is not None:
            payload["plan"] = self.plan.to_api()
        return payload
