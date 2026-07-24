"""API 요청·응답 스키마."""
from __future__ import annotations

from typing import Any

from pydantic import BaseModel, EmailStr, Field


class RegisterIn(BaseModel):
    email: EmailStr
    password: str = Field(min_length=12, max_length=256)


class LoginIn(BaseModel):
    email: EmailStr
    password: str


class TokenOut(BaseModel):
    access_token: str
    refresh_token: str
    expires_in: int


class RefreshIn(BaseModel):
    refresh_token: str


class ProfileIn(BaseModel):
    """자산 정보. 이 모델의 값은 **로그에 남기지 않는다** (security.md §3.3)."""

    cash_krw: int = Field(ge=0, le=10**15)
    income_krw: int = Field(ge=0, le=10**15)
    existing_loan_krw: int = Field(default=0, ge=0, le=10**15)
    existing_annual_repayment_krw: int = Field(default=0, ge=0, le=10**15)
    existing_annual_interest_krw: int = Field(default=0, ge=0, le=10**15)
    owned_houses: int = Field(default=0, ge=0, le=100)
    household_size: int = Field(default=1, ge=1, le=20)


class ProfileOut(ProfileIn):
    pass


class PreferencesIn(BaseModel):
    prefer: dict[str, Any] = Field(default_factory=dict)
    avoid: dict[str, Any] = Field(default_factory=dict)
    weights: dict[str, float] = Field(default_factory=dict)


class AffordabilityIn(BaseModel):
    target_region_code: str | None = None
    purpose: str = Field(default="live", pattern="^(live|invest)$")
    area_m2: float = Field(default=84.0, gt=0, le=1000)
    is_regulated_area: bool = False
    annual_rate: float = Field(default=0.04, ge=0, le=0.3)
    years: int = Field(default=30, ge=1, le=50)
    apply_dti: bool = False


class RecommendationIn(BaseModel):
    region_codes: list[str] = Field(default_factory=list, max_length=50)
    purpose: str = Field(default="live", pattern="^(live|invest)$")
    budget_override_krw: int | None = Field(default=None, ge=0)
    agents: list[str] | None = None
    top_n: int = Field(default=10, ge=1, le=50)
