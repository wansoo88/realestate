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

import datetime as dt
from dataclasses import dataclass, field
from typing import Any, Protocol, runtime_checkable

from app.domain.location.models import BuildingLocationFact, LocationFacts

# --- 가입 승인 상태 (migrations/009) ---------------------------------------
#: 기본값. 가입은 되지만 **로그인은 안 된다** — 관리자가 검토할 때까지.
STATUS_PENDING = "pending"
STATUS_APPROVED = "approved"
STATUS_REJECTED = "rejected"
USER_STATUSES = (STATUS_PENDING, STATUS_APPROVED, STATUS_REJECTED)


class LastAdminError(Exception):
    """마지막 관리자를 거부·강등하려 했다.

    관리자가 0명이 되면 **어떤 신규 가입도 승인할 수 없는 상태**가 되고,
    복구하려면 서버에 SSH 로 들어가 CLI 를 돌리는 수밖에 없다.
    실수 한 번으로 그 상태에 빠지지 않게 리포지토리가 거절한다.
    """


@dataclass
class UserRecord:
    """사용자.

    ⚠️ `status`·`is_admin` 은 **서버 DB 가 진실 소스**다. JWT 에 담지 않는다 —
    토큰에 실으면 클라이언트가 주장하는 값이 되고, 그 순간 위조 표면이 생긴다
    (security.md §2.2 와 같은 강도).
    """

    id: int
    email: str
    password_hash: str
    #: 'pending' | 'approved' | 'rejected'. 기본은 승인 대기다.
    status: str = STATUS_PENDING
    is_admin: bool = False
    created_at: dt.datetime | None = None
    # -- 감사 흔적 (누가 언제 왜 상태를 바꿨나) --
    status_changed_at: dt.datetime | None = None
    status_changed_by: int | None = None
    status_reason: str | None = None

    @property
    def is_approved(self) -> bool:
        return self.status == STATUS_APPROVED

    @property
    def can_administer(self) -> bool:
        """관리자 권한의 **유일한 판정식.**

        승인되지 않은 관리자는 관리자가 아니다 — 거부된 계정에 남아 있던
        `is_admin` 이 되살아나는 경로를 만들지 않는다.
        """
        return self.is_admin and self.is_approved


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
    #: 제외된 후보와 사유. **추천 목록의 반쪽**이다 — "왜 이건 안 나왔지"에 답하는 자리.
    #: 비어 있는 것과 저장 경로가 없어 사라진 것은 다르다(후자는 사용자가 결과를 못 믿는다).
    excluded: list[dict[str, Any]] = field(default_factory=list)
    #: 결과 전체에 붙는 단서(추정 표기·미구현 기능 고지 등).
    notes: list[str] = field(default_factory=list)


@runtime_checkable
class UserRepository(Protocol):
    def create_user(self, email: str, password_hash: str) -> UserRecord: ...
    def get_user_by_email(self, email: str) -> UserRecord | None: ...
    def get_user(self, user_id: int) -> UserRecord | None: ...


@runtime_checkable
class UserAdminRepository(Protocol):
    """관리자 승인 (migrations/009).

    ⚠️ **마지막 관리자 보호는 여기서 한다.** 라우터에서만 검사하면 CLI 가 그 검사를
    비켜가고, CLI 에서만 검사하면 API 가 비켜간다. 상태를 바꾸는 **단 하나의 길목**인
    리포지토리가 거절해야 두 경로 모두 막힌다(`LastAdminError`).
    """

    def list_users(self, *, status: str | None = None,
                   limit: int = 100) -> list[UserRecord]: ...

    #: 상태 변경 + 감사 기록을 **한 트랜잭션**으로. 대상이 없으면 None.
    def set_user_status(self, user_id: int, status: str, *,
                        actor: str, actor_user_id: int | None = None,
                        reason: str | None = None) -> UserRecord | None: ...

    def set_user_admin(self, user_id: int, is_admin: bool, *,
                       actor: str, actor_user_id: int | None = None) -> UserRecord | None: ...

    #: 승인된 관리자 수. 0명이 되는 변경을 막는 데 쓴다.
    def count_active_admins(self) -> int: ...


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


@runtime_checkable
class RecommendationRepository(Protocol):
    """추천 러너가 쓰는 조회·저장 (docs/domain/recommendation-execution.md §repo인터페이스).

    러너는 이 메서드들을 **duck-typing 으로** 부른다 — 없으면 경고 후 빈 결과로
    degrade 한다. 즉 시그니처가 어긋나도 크래시하지 않고 **추천이 조용히 비어** 버린다.
    그 침묵이 위험해서 Protocol 로 박아 둔다: 두 구현 모두 `isinstance` 로 검증한다.
    """

    def recommendation_candidates(
        self, *, region_codes: list[str], max_price_krw: int | None = None,
        limit: int = 50,
    ) -> list[ComplexSummary]: ...

    #: 활성 호가. **중복 포함** — 대표건 선정은 러너의 group_duplicates 몫이다.
    def listings_for_complex(self, complex_id: int) -> list[Any]: ...

    #: 실거래. **해제건 포함** — 제외 여부는 통계 계층이 정한다.
    def trades_for_complex(self, complex_id: int) -> list[Any]: ...

    #: user_id 필수 — 결과를 되쓸 때도 소유권을 다시 확인한다(IDOR).
    #:
    #: ⚠️ `excluded`·`notes` 는 **선택 인자가 아니라 계약의 일부**다. 구현이 이 인자를
    #:    받지 않으면 러너의 호출이 TypeError 로 죽어 결과가 통째로 사라진다. 기본값을
    #:    둔 것은 옛 호출부(테스트)를 위해서지 "안 실어도 된다"는 뜻이 아니다 —
    #:    저장하지 않으면 사용자는 "왜 이건 안 나왔지"에 답을 받지 못한다.
    def save_job_result(self, job_id: str, user_id: int, *, status: str,
                        items: list[dict[str, Any]],
                        excluded: list[dict[str, Any]] | None = None,
                        notes: list[str] | None = None) -> None: ...


@runtime_checkable
class LocationRepository(Protocol):
    """입지 사실 조립 — `location-analyst`(re-domain) 의 입력을 만든다.

    경계 (domain/location/models.py 의 규약과 짝을 이룬다)
    -----------------------------------------------------
    **공간 판정은 전부 여기서 한다.** 학구도 포함 여부(`ST_Contains`),
    역·POI·유해요소 최단거리(`ST_Distance`)를 DB 에서 계산해 사실만 넘기고,
    그걸 점수·근거로 바꾸는 일은 도메인 계층이 한다. 반대 방향으로 새면 안 된다 —
    리포지토리가 점수를 매기기 시작하면 근거 감사(G2)가 두 곳을 봐야 한다.

    ⚠️ 데이터가 없으면 **추정하지 않고 비운다.**
    학구도가 없으면 `SchoolFact.district_data_available=False` 로 넘기고,
    최근접 학교 거리로 배정을 대체하지 않는다(배정과 거리는 다른 개념).
    거리를 모르면 `None` 이다 — 0 이나 임의값으로 채우지 않는다.
    """

    def location_facts(self, complex_id: int) -> LocationFacts | None: ...

    #: 동(棟)별 좌표 사실. 실거래에 동 정보가 없어 **추정 입력**으로만 쓰인다(F4 §D).
    def building_location_facts(self, complex_id: int) -> list[BuildingLocationFact]: ...
