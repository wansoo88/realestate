"""데이터 접근 인터페이스.

왜 Protocol 로 감싸나
---------------------
로컬에 Docker 가 없어 PostGIS 를 띄울 수 없다(implementation-plan.md §0).
DB 접근을 인터페이스 뒤에 두면 **가짜 구현으로 API 전체를 테스트**할 수 있다.
배포 시 PostGIS 구현으로 갈아끼우기만 하면 된다.

⚠️ IDOR 방지 규약 (security.md §2.2)
------------------------------------
사용자 자원을 다루는 모든 메서드는 **`user_id` 를 필수 인자로 받는다.**
`get_job(job_id)` 같은 시그니처는 만들지 않는다 — 만들 수 있으면 언젠가 쓰이고,
그 순간 남의 추천 결과가 새어나간다.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Protocol, runtime_checkable


@dataclass
class UserRecord:
    id: int
    email: str
    password_hash: str


@dataclass
class ProfileRecord:
    """자산 3종은 **암호문(bytes)** 으로만 오간다. 평문 int 를 담지 않는다."""

    user_id: int
    cash_krw_enc: bytes | None = None
    income_krw_enc: bytes | None = None
    existing_loan_krw_enc: bytes | None = None
    owned_houses: int = 0
    household_size: int = 1


@dataclass
class ComplexSummary:
    id: int
    name: str
    lon: float
    lat: float
    region_code: str
    built_year: int | None = None
    total_households: int | None = None
    recent_price_krw: int | None = None
    price_as_of: str | None = None
    active_listings: int = 0


@dataclass
class JobRecord:
    id: str
    user_id: int
    criteria_snapshot: dict[str, Any] = field(default_factory=dict)
    status: str = "queued"
    items: list[dict[str, Any]] = field(default_factory=list)


@runtime_checkable
class UserRepository(Protocol):
    def create_user(self, email: str, password_hash: str) -> UserRecord: ...
    def get_user_by_email(self, email: str) -> UserRecord | None: ...
    def get_user(self, user_id: int) -> UserRecord | None: ...


@runtime_checkable
class ProfileRepository(Protocol):
    def get_profile(self, user_id: int) -> ProfileRecord | None: ...
    def upsert_profile(self, profile: ProfileRecord) -> ProfileRecord: ...
    def get_preferences(self, user_id: int) -> dict[str, Any]: ...
    def set_preferences(self, user_id: int, prefs: dict[str, Any]) -> dict[str, Any]: ...


@runtime_checkable
class MapRepository(Protocol):
    def complexes_in_bbox(
        self,
        *,
        min_lon: float, min_lat: float, max_lon: float, max_lat: float,
        max_price_krw: int | None = None,
        area_min_m2: float | None = None,
        area_max_m2: float | None = None,
        built_after: int | None = None,
        limit: int = 500,
    ) -> list[ComplexSummary]: ...


@runtime_checkable
class JobRepository(Protocol):
    def create_job(self, job_id: str, user_id: int,
                   criteria: dict[str, Any]) -> JobRecord: ...
    #: user_id 필수 — 소유권 검증 없이 조회할 방법을 만들지 않는다
    def get_job(self, job_id: str, user_id: int) -> JobRecord | None: ...
