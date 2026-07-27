"""인메모리 리포지토리 — 테스트·로컬 개발용.

PostGIS 구현이 준비되기 전까지 API 계약을 검증하는 데 쓴다.
공간 필터는 단순 bbox 비교로 대체한다(실제 구현은 GiST 인덱스 + `&&` 연산자).
"""
from __future__ import annotations

import datetime as dt
import itertools
from typing import Any

from app.domain.location.models import BuildingLocationFact, LocationFacts
from app.domain.redevelopment.models import RedevProject
from app.domain.valuation.models import ListingRow, TradeRow
from app.repositories.base import (
    STATUS_APPROVED,
    BBox,
    ComplexSummary,
    JobRecord,
    LastAdminError,
    ProfileRecord,
    UserRecord,
)


def _within(c: ComplexSummary, bbox: BBox) -> bool:
    """단지가 bbox 안에 있나. **좌표가 없으면 False** (PostGIS `&&` 와 같은 결과).

    좌표 없는 단지를 여기서 통과시키면 인메모리 테스트만 초록불이 되고,
    실제 PostGIS 에서는 조용히 빠진다 — 가장 나쁜 종류의 불일치다.
    """
    if c.lon is None or c.lat is None:
        return False
    return (bbox.min_lon <= c.lon <= bbox.max_lon
            and bbox.min_lat <= c.lat <= bbox.max_lat)


class InMemoryRepository:
    """UserRepository · ProfileRepository · MapRepository · JobRepository 를 모두 구현."""

    def __init__(self) -> None:
        self._users: dict[int, UserRecord] = {}
        self._by_email: dict[str, int] = {}
        #: 상태 변경 이력(append-only). PostGIS 의 `user_status_event` 에 대응한다.
        self._status_events: list[dict[str, Any]] = []
        self._profiles: dict[int, ProfileRecord] = {}
        self._prefs: dict[int, dict[str, Any]] = {}
        self._complexes: list[ComplexSummary] = []
        self._jobs: dict[str, JobRecord] = {}
        self._location: dict[int, LocationFacts] = {}
        self._buildings: dict[int, list[BuildingLocationFact]] = {}
        self._listings: dict[int, list[ListingRow]] = {}
        self._trades: dict[int, list[TradeRow]] = {}
        self._redev: dict[int, RedevProject] = {}
        self._ids = itertools.count(1)

    # -- 사용자 -----------------------------------------------------------
    def create_user(self, email: str, password_hash: str) -> UserRecord:
        key = email.strip().lower()
        if key in self._by_email:
            raise ValueError("이미 등록된 이메일입니다")
        # 상태 기본값은 UserRecord 가 'pending' 으로 갖는다(migrations/009 의 DEFAULT 와 동일).
        # 여기서 approved 를 넣는 지름길을 만들지 않는다.
        user = UserRecord(id=next(self._ids), email=key, password_hash=password_hash,
                          created_at=dt.datetime.now(dt.timezone.utc))
        self._users[user.id] = user
        self._by_email[key] = user.id
        self._status_events.append({
            "user_id": user.id, "event": "registered", "actor": "self",
            "actor_user_id": None, "reason": None,
            "created_at": user.created_at,
        })
        return user

    def get_user_by_email(self, email: str) -> UserRecord | None:
        uid = self._by_email.get(email.strip().lower())
        return self._users.get(uid) if uid else None

    def get_user(self, user_id: int) -> UserRecord | None:
        return self._users.get(user_id)

    # -- 사용자 승인 (관리자) ---------------------------------------------
    def list_users(self, *, status: str | None = None,
                   limit: int = 100) -> list[UserRecord]:
        rows = [u for u in self._users.values() if status is None or u.status == status]
        # 오래 기다린 사람이 위로. PostGIS 구현과 같은 정렬이어야 한다.
        rows.sort(key=lambda u: (u.created_at or dt.datetime.min, u.id))
        return rows[:limit]

    def count_active_admins(self) -> int:
        return sum(1 for u in self._users.values() if u.can_administer)

    def _guard_last_admin(self, target: UserRecord, *, still_admin: bool) -> None:
        """이 변경 뒤에도 승인된 관리자가 남는가. 안 남으면 거절한다."""
        if not target.can_administer or still_admin:
            return
        others = sum(1 for u in self._users.values()
                     if u.id != target.id and u.can_administer)
        if others == 0:
            raise LastAdminError(
                "마지막 관리자입니다. 다른 관리자를 먼저 지정한 뒤에 바꾸세요")

    def set_user_status(self, user_id: int, status: str, *, actor: str,
                        actor_user_id: int | None = None,
                        reason: str | None = None) -> UserRecord | None:
        user = self._users.get(user_id)
        if user is None:
            return None
        # 승인 취소·거부는 관리자 자격도 함께 잃게 한다(can_administer 가 approved 를 요구).
        self._guard_last_admin(user, still_admin=(status == STATUS_APPROVED))
        now = dt.datetime.now(dt.timezone.utc)
        user.status = status
        user.status_changed_at = now
        user.status_changed_by = actor_user_id
        user.status_reason = reason
        self._status_events.append({
            "user_id": user.id, "event": status, "actor": actor,
            "actor_user_id": actor_user_id, "reason": reason, "created_at": now,
        })
        return user

    def set_user_admin(self, user_id: int, is_admin: bool, *, actor: str,
                       actor_user_id: int | None = None) -> UserRecord | None:
        user = self._users.get(user_id)
        if user is None:
            return None
        self._guard_last_admin(user, still_admin=is_admin)
        user.is_admin = is_admin
        self._status_events.append({
            "user_id": user.id,
            "event": "admin_granted" if is_admin else "admin_revoked",
            "actor": actor, "actor_user_id": actor_user_id, "reason": None,
            "created_at": dt.datetime.now(dt.timezone.utc),
        })
        return user

    def status_events(self, user_id: int) -> list[dict[str, Any]]:
        """감사 이력 조회 — 테스트·검증용(PostGIS 는 user_status_event 테이블)."""
        return [e for e in self._status_events if e["user_id"] == user_id]

    # -- 프로필 -----------------------------------------------------------
    def get_profile(self, user_id: int) -> ProfileRecord | None:
        return self._profiles.get(user_id)

    def upsert_profile(self, profile: ProfileRecord) -> ProfileRecord:
        self._profiles[profile.user_id] = profile
        return profile

    def get_preferences(self, user_id: int) -> dict[str, Any]:
        return self._prefs.get(user_id, {"prefer": {}, "avoid": {}, "weights": {}})

    def set_preferences(self, user_id: int, prefs: dict[str, Any]) -> dict[str, Any]:
        self._prefs[user_id] = prefs
        return prefs

    # -- 지도 -------------------------------------------------------------
    def add_complex(self, c: ComplexSummary) -> ComplexSummary:
        self._complexes.append(c)
        return c

    def complexes_in_bbox(
        self, *, min_lon: float, min_lat: float, max_lon: float, max_lat: float,
        max_price_krw: int | None = None,
        area_min_m2: float | None = None,
        area_max_m2: float | None = None,
        built_after: int | None = None,
        limit: int = 500,
    ) -> list[ComplexSummary]:
        box = BBox(min_lon, min_lat, max_lon, max_lat)
        out: list[ComplexSummary] = []
        for c in self._complexes:
            # 좌표 없는 단지는 지도에 찍을 수 없다 → 자연히 빠진다(PostGIS `&&` 와 동일).
            if not _within(c, box):
                continue
            if built_after is not None and (c.built_year or 0) < built_after:
                continue
            # 예산 초과 단지는 **제외하지 않고** 호출부가 흐리게 표시하도록 그대로 넘긴다
            # (ux/README.md §4 — 왜 후보에 없는지 보이게 한다).
            out.append(c)
            if len(out) >= limit:
                break
        return out

    # -- 입지 (스텁) -------------------------------------------------------
    # 공간연산이 없으므로 **테스트가 넣어준 사실만 돌려준다.**
    # 좌표로 거리를 흉내 내지 않는다 — 가짜 거리로 통과한 입지 로직은
    # 실제 PostGIS 위에서 처음 틀린 걸 알게 된다.

    def set_location_facts(self, complex_id: int, facts: LocationFacts) -> LocationFacts:
        self._location[complex_id] = facts
        return facts

    def set_building_location_facts(
        self, complex_id: int, facts: list[BuildingLocationFact],
    ) -> list[BuildingLocationFact]:
        self._buildings[complex_id] = list(facts)
        return self._buildings[complex_id]

    def location_facts(self, complex_id: int) -> LocationFacts | None:
        return self._location.get(complex_id)

    def building_location_facts(self, complex_id: int) -> list[BuildingLocationFact]:
        return list(self._buildings.get(complex_id, ()))

    # -- 정비사업(재건축) --------------------------------------------------
    # 입지와 같은 규칙이다: **테스트가 넣어준 사실만** 돌려주고, 좌표·연식으로
    # "재건축 같다"를 추정하지 않는다. 넣은 적이 없으면 None = **모른다**
    # (PostGIS 구현의 `redevelopment_for_complex` 와 같은 계약).
    #
    # ⚠️ 이 자리가 비어 있는 동안 재건축 가중치는 API 전 구간에서 증명할 수 없었다 —
    #    인메모리에는 정비사업 사실을 넣을 방법 자체가 없어 그 축이 항상 '근거 없음'
    #    이었기 때문이다. 증명할 수 없는 축은 "반영된다"고 말할 자격이 없다.

    def set_redevelopment(self, complex_id: int,
                          project: RedevProject | None) -> RedevProject | None:
        if project is None:
            self._redev.pop(complex_id, None)
        else:
            self._redev[complex_id] = project
        return project

    def redevelopment_for_complex(self, complex_id: int) -> RedevProject | None:
        return self._redev.get(complex_id)

    # -- 추천 작업 ---------------------------------------------------------
    def create_job(self, job_id: str, user_id: int, criteria: dict[str, Any]) -> JobRecord:
        job = JobRecord(id=job_id, user_id=user_id, criteria_snapshot=criteria)
        self._jobs[job_id] = job
        return job

    def get_job(self, job_id: str, user_id: int) -> JobRecord | None:
        """소유권 검증을 리포지토리 안에서 강제한다 (IDOR 방지)."""
        job = self._jobs.get(job_id)
        if job is None or job.user_id != user_id:
            return None
        return job

    def save_job_result(self, job_id: str, user_id: int, *, status: str,
                        items: list[dict[str, Any]],
                        excluded: list[dict[str, Any]] | None = None,
                        notes: list[str] | None = None) -> None:
        """BackgroundTask 가 분석 결과를 되쓴다. 소유권을 다시 확인한다(IDOR).

        `excluded`(제외 후보와 사유)·`notes` 도 함께 남긴다 — PostGIS 구현과 **같은
        응답**이 나와야 인메모리 테스트가 프로덕션을 대표한다.
        """
        job = self._jobs.get(job_id)
        if job is None or job.user_id != user_id:
            return
        job.status = status
        job.items = list(items)
        job.excluded = list(excluded or [])
        job.notes = list(notes or [])

    # -- 추천 후보 조회 (BackgroundTask 러너용) ----------------------------
    # ⚠️ PostGIS 구현(re-arch)이 아래 3종을 같은 시그니처로 제공해야 프로덕션에서 동작한다.
    #    인메모리 구현은 테스트가 넣어준 매물·실거래만 돌려준다(공간·가격 근사 없음).

    def add_listings(self, complex_id: int, listings: list[ListingRow]) -> None:
        self._listings.setdefault(complex_id, []).extend(listings)

    def add_trades(self, complex_id: int, trades: list[TradeRow]) -> None:
        self._trades.setdefault(complex_id, []).extend(trades)

    #: 면적 근거로 볼 실거래 창(일). PostGIS 구현(`_CANDIDATE_TRADE_WINDOW_DAYS`)과 같다 —
    #: 여기만 넓으면 인메모리 테스트가 프로덕션보다 관대해져 회귀를 못 잡는다.
    _AREA_TRADE_WINDOW_DAYS = 36 * 30

    def _area_evidence(self, complex_id: int) -> list[float]:
        """이 단지에서 **실제로 확인된 면적들**(활성 호가 + 최근 실거래).

        PostGIS 구현은 여기에 `unit_type` 도 본다. 인메모리에는 타입 테이블이 없어
        후보를 세우는 근거(호가·실거래)만 본다 — 판정 **의미**는 같다.
        """
        cutoff = dt.date.today() - dt.timedelta(days=self._AREA_TRADE_WINDOW_DAYS)
        areas = [li.area_m2 for li in self._listings.get(complex_id, ())
                 if li.status == "active" and li.area_m2]
        areas += [t.area_m2 for t in self._trades.get(complex_id, ())
                  if t.area_m2 and not t.is_cancelled and t.contract_date >= cutoff]
        return [float(a) for a in areas]

    def _area_ok(self, complex_id: int, area_min: float | None,
                 area_max: float | None) -> bool:
        """조건에 맞는 면적 근거가 **하나라도** 있나. 근거가 없으면 False(미상은 통과 아님)."""
        if area_min is None and area_max is None:
            return True
        for a in self._area_evidence(complex_id):
            if (area_min is None or a >= area_min) and (area_max is None or a <= area_max):
                return True
        return False

    @staticmethod
    def _built_ok(c: ComplexSummary, built_after: int | None) -> bool:
        if built_after is None:
            return True
        return c.built_year is not None and c.built_year >= built_after

    @staticmethod
    def _households_ok(c: ComplexSummary, min_households: int | None) -> bool:
        if min_households is None:
            return True
        return (c.total_households is not None
                and c.total_households >= min_households)

    def recommendation_candidates(
        self, *, region_codes: list[str], max_price_krw: int | None = None,
        limit: int = 50, bbox: BBox | None = None,
        area_min_m2: float | None = None, area_max_m2: float | None = None,
        built_after: int | None = None, min_households: int | None = None,
    ) -> list[ComplexSummary]:
        """조건에 맞는 후보 단지. 예산으로 **걸러내지 않는다** — 초과 단지도 넘기고
        파이프라인이 사유와 함께 제외한다(ux/README.md §4).

        `region_codes` 와 `bbox` 가 둘 다 오면 **교집합**이다(PostGIS 구현과 동일).
        ⚠️ bbox 는 **좌표가 있는 단지만** 찾는다 — geom NULL 인 단지가 PostGIS 에서
        `&&` 로 자연히 빠지는 것과 같게, 여기서도 lon/lat 이 None 이면 뺀다.
        (여기서만 통과시키면 인메모리 테스트가 프로덕션을 대표하지 못한다.)

        ⚠️ **내 조건(평수·연식·세대수)은 예산과 달리 여기서 거른다.** 미상은 통과시키지
        않는다 — PostGIS 구현과 같은 규칙이어야 테스트가 프로덕션을 대표한다.
        """
        wanted = {r for r in (region_codes or [])}
        out: list[ComplexSummary] = []
        for c in self._complexes:
            if wanted and not any(str(c.region_code or "").startswith(r) for r in wanted):
                continue
            if bbox is not None and not _within(c, bbox):
                continue
            if not self._built_ok(c, built_after):
                continue
            if not self._households_ok(c, min_households):
                continue
            if not self._area_ok(c.id, area_min_m2, area_max_m2):
                continue
            out.append(c)
            if len(out) >= limit:
                break
        return out

    def candidate_scope_stats(
        self, *, region_codes: list[str] | None = None, bbox: BBox | None = None,
        area_min_m2: float | None = None, area_max_m2: float | None = None,
        built_after: int | None = None, min_households: int | None = None,
    ) -> dict[str, int]:
        """조건 때문에 조회에서 빠진 단지 수(PostGIS 구현과 같은 키·같은 판정)."""
        wanted = {r for r in (region_codes or [])}
        stats = {"scope_total": 0, "area_dropped": 0, "built_dropped": 0,
                 "built_unknown": 0, "households_dropped": 0,
                 "households_unknown": 0}
        for c in self._complexes:
            if wanted and not any(str(c.region_code or "").startswith(r) for r in wanted):
                continue
            if bbox is not None and not _within(c, bbox):
                continue
            stats["scope_total"] += 1
            if not self._area_ok(c.id, area_min_m2, area_max_m2):
                stats["area_dropped"] += 1
            if not self._built_ok(c, built_after):
                stats["built_dropped"] += 1
            if built_after is not None and c.built_year is None:
                stats["built_unknown"] += 1
            if not self._households_ok(c, min_households):
                stats["households_dropped"] += 1
            if min_households is not None and c.total_households is None:
                stats["households_unknown"] += 1
        return stats

    def geocode_coverage(
        self, *, region_codes: list[str] | None = None) -> tuple[int, int]:
        """(좌표 있는 단지 수, 전체 단지 수). bbox 검색에서 빠지는 몫을 세는 데 쓴다."""
        wanted = {r for r in (region_codes or [])}
        total = with_geom = 0
        for c in self._complexes:
            if wanted and not any(str(c.region_code or "").startswith(r) for r in wanted):
                continue
            total += 1
            if c.lon is not None and c.lat is not None:
                with_geom += 1
        return with_geom, total

    def listings_for_complex(self, complex_id: int) -> list[ListingRow]:
        return list(self._listings.get(complex_id, ()))

    def trades_for_complex(self, complex_id: int) -> list[TradeRow]:
        return list(self._trades.get(complex_id, ()))
