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
    """대상 주택의 세율 판정에 필요한 사실."""

    area_m2: float = 84.0
    is_regulated_area: bool = False
    purpose: str = "live"          # live | invest

    @property
    def houses_after_purchase(self) -> int:  # 편의용 — 호출부에서 owned_houses+1
        raise NotImplementedError


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
    binding: str                   # LTV | DSR | DTI


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

    def to_api(self) -> dict[str, Any]:
        return {
            "max_purchase_krw": self.max_purchase_krw,
            "breakdown": {
                "own_cash_krw": self.usable_cash_krw,
                "max_loan_krw": self.loan_krw,
                "ltv_limit_krw": self.limits.ltv_krw,
                "dsr_limit_krw": self.limits.dsr_krw,
                "dti_limit_krw": self.limits.dti_krw,
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
