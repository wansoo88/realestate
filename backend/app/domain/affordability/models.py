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
