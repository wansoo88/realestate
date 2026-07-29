"""인메모리 리포지토리 — 테스트·로컬 개발용.

PostGIS 구현이 준비되기 전까지 API 계약을 검증하는 데 쓴다.
공간 필터는 단순 bbox 비교로 대체한다(실제 구현은 GiST 인덱스 + `&&` 연산자).
"""
from __future__ import annotations

import dataclasses
import datetime as dt
import itertools
from typing import Any

from app.domain.location.models import BuildingLocationFact, LocationFacts
from app.domain.redevelopment.models import RedevProject
from app.domain.valuation.models import ListingRow, TradeRow
from app.repositories.base import (
    LISTING_SOURCE_USER,
    MAX_USER_LISTINGS,
    STATUS_APPROVED,
    BBox,
    ComplexSummary,
    JobRecord,
    LastAdminError,
    ProfileRecord,
    UserListingRecord,
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
        #: 시장 가격지수 (migrations/015 · 시점 보정). (region_code, scope) → MarketIndex.
        self._market_indexes: dict[tuple[str, str], Any] = {}
        #: 사용자 수동 입력 호가 (migrations/016). id → 레코드.
        #: 수집 호가(`_listings`)와 **따로 보관한다** — 한 통에 넣으면 소유자 필터를
        #: 한 번만 잊어도 남의 입력이 섞여 나간다. 저장소 수준에서 분리해 둔다.
        self._user_listings: dict[int, UserListingRecord] = {}
        self._ids = itertools.count(1)
        #: 호가 id 시퀀스. 단지·사용자 id 와 겹치지 않게 별도로 센다.
        self._listing_ids = itertools.count(1)

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

    def listings_for_complex(self, complex_id: int,
                             user_id: int | None = None) -> list[ListingRow]:
        """수집 호가 + (user_id 를 주면) **그 사용자의** 수동 입력 호가.

        ⚠️ `user_id` 가 없으면 사용자 입력은 **한 건도** 나오지 않는다. PostGIS 구현과
        같은 규칙이어야 인메모리 테스트가 프로덕션을 대표한다(base.py 의 계약 주석).
        낡은 입력(as_of > LISTING_STALE_DAYS)·비활성 상태도 여기서 빠진다 —
        호출부가 거르기를 기대하지 않는다.
        """
        rows = list(self._listings.get(complex_id, ()))
        if user_id is None:
            return rows
        rows += [
            _to_listing_row(rec)
            for rec in self._user_listings.values()
            if rec.user_id == user_id and rec.complex_id == complex_id and rec.usable()
        ]
        return rows

    def trades_for_complex(self, complex_id: int) -> list[TradeRow]:
        return list(self._trades.get(complex_id, ()))

    # -- 시장 가격지수(시점 보정) ------------------------------------------
    #
    # ★ CR36-2 의 나머지 절반. `complex_region_code` 만 채워도 지수를 조회할 **함수가
    #   없으면**(`load_market_indexes` → `getattr(repo, "market_index", None)` → None)
    #   시점 보정은 여전히 한 번도 돌지 않는다. 두 메서드가 다 있어야 API 경로가
    #   PostGIS 와 같은 분기를 밟는다.
    #
    # ⚠️ 값을 **지어내지 않는다.** 테스트가 `set_market_index` 로 넣어준 것만 돌려주고,
    #    넣은 적이 없으면 PostGIS 와 같은 모양의 **빈 지수**(points={})다 —
    #    "조회했는데 없었다"와 "조회조차 못 했다"의 구분을 인메모리에서도 유지한다.

    def set_market_index(self, index: Any) -> Any:
        self._market_indexes[(index.region_code, index.scope)] = index
        return index

    def market_index(self, region_code: str, scope: str) -> Any:
        from app.domain.valuation.timeadjust import MarketIndex

        found = self._market_indexes.get((region_code, scope))
        if found is not None:
            return found
        return MarketIndex(region_code=region_code, scope=scope, points={})

    def complex_region_code(self, complex_id: int) -> str | None:
        """이 단지의 법정동코드. 없거나 미상이면 **None** (PostGIS 구현과 같은 계약).

        ★ CR36-2. **이 메서드가 없어서 API 경로 전체가 다른 분기를 밟고 있었다.**
        `complex_reference_price` 는 이 값이 있어야 시장지수를 찾아 밴드를 시점
        보정한다(`recommend._complex_region_code` 는 메서드가 없으면 조용히 None 을
        쓴다 — 추천을 죽이지 않으려는 설계다). 그래서 인메모리를 쓰는 **모든 API
        테스트에서 자금계획은 언제나 `trade_band`(보정 없음)로 떨어졌고**, "추천 카드와
        자금계획이 같은 값"이라는 명제(CR35-4)는 API 경로에서 한 번도 실행되지 않았다.
        실측 격차: 529,699,059(추천) vs 500,000,000(자금계획) — 5.6%.

        빈 문자열은 돌려주지 않는다(PostGIS 와 같은 규칙) — 빈 코드로 지수를 찾으면
        엉뚱한 지역이 걸린다.
        """
        for c in self._complexes:
            if c.id == complex_id:
                return (str(c.region_code or "").strip() or None)
        return None

    # -- 사용자 수동 입력 호가 (migrations/016) ----------------------------
    #
    # 소유자 스코프를 **저장소 안에서** 강제한다. 라우터가 한 번 잊어도 남의 입력이
    # 나가지 않도록, 모든 읽기/쓰기가 user_id 로 먼저 걸러진다(security.md §2.2).

    def complex_name(self, complex_id: int) -> str | None:
        for c in self._complexes:
            if c.id == complex_id:
                return c.name
        return None

    def add_user_listing(self, user_id: int, *, complex_id: int,
                         ask_price_krw: int, area_m2: float, as_of: dt.date,
                         floor: int | None = None, apt_dong: str | None = None,
                         note: str | None = None) -> UserListingRecord:
        now = dt.datetime.now(dt.timezone.utc)
        rec = UserListingRecord(
            id=next(self._listing_ids), user_id=user_id, complex_id=complex_id,
            ask_price_krw=int(ask_price_krw), area_m2=float(area_m2), as_of=as_of,
            floor=floor, apt_dong=apt_dong, note=note, status="active",
            source=LISTING_SOURCE_USER, complex_name=self.complex_name(complex_id),
            created_at=now, updated_at=now,
        )
        self._user_listings[rec.id] = rec
        return rec

    def list_user_listings(self, user_id: int, *, complex_id: int | None = None,
                           limit: int = MAX_USER_LISTINGS) -> list[UserListingRecord]:
        rows = [r for r in self._user_listings.values()
                if r.user_id == user_id
                and (complex_id is None or r.complex_id == complex_id)]
        # 최근에 본 것부터. PostGIS 구현과 같은 정렬이어야 한다.
        rows.sort(key=lambda r: (r.as_of, r.id), reverse=True)
        return rows[:limit]

    def get_user_listing(self, listing_id: int,
                         user_id: int) -> UserListingRecord | None:
        rec = self._user_listings.get(listing_id)
        # 남의 것과 없는 것은 **같은 None** 이다 — 구분하면 그 차이가 정보가 된다.
        if rec is None or rec.user_id != user_id:
            return None
        return rec

    #: 수정 가능한 필드. 여기 없는 키는 조용히 무시하지 않고 **거절**한다 —
    #: 오타(`price_krw`)가 조용히 무시되면 사용자는 고쳤다고 믿는다.
    _UPDATABLE = ("ask_price_krw", "area_m2", "floor", "apt_dong",
                  "as_of", "note", "status")

    def update_user_listing(self, listing_id: int, user_id: int,
                            **fields: Any) -> UserListingRecord | None:
        unknown = [k for k in fields if k not in self._UPDATABLE]
        if unknown:
            raise ValueError(f"수정할 수 없는 필드입니다: {', '.join(sorted(unknown))}")
        rec = self.get_user_listing(listing_id, user_id)
        if rec is None:
            return None
        updated = dataclasses.replace(
            rec, **fields, updated_at=dt.datetime.now(dt.timezone.utc))
        self._user_listings[listing_id] = updated
        return updated

    def delete_user_listing(self, listing_id: int, user_id: int) -> bool:
        if self.get_user_listing(listing_id, user_id) is None:
            return False
        del self._user_listings[listing_id]
        return True


def _to_listing_row(rec: UserListingRecord) -> ListingRow:
    """사용자 입력 → 분석 계층이 읽는 `ListingRow`.

    ⚠️ **`listed_at` 에 as_of 를 넣지 않는다.** `listed_at` 은 '매물이 포털에 올라온 날'
       이고 사용자는 그걸 모른다. 거기에 '내가 본 날'을 넣으면 `dedup.trust_score` 가
       "등록 N일 경과"라며 감점하는데, 그건 매물이 안 팔린 기간이 아니라 **사용자가
       입력을 미룬 기간**이다. 없는 값은 None 으로 둔다.
    ⚠️ `collected_at` 에는 as_of 를 넣는다 — 우리가 이 호가의 존재를 **확인한 시점**이
       맞고, 낡은 정도를 하류에서 다시 셀 수 있는 유일한 값이다.

    ⚠️ `source`·`as_of` 를 **반드시 싣는다.** 이게 빠지면 분석 계층에서 출처 구분이
       끊기고, 사용자가 적은 한 건이 `dedup.trust_score` 만점(= 리스크 축 100점)을
       받는다 — 비싼 매물을 입력할수록 총점이 오르는 형태다(차단 ①).
    """
    return ListingRow(
        id=rec.id,
        ask_price_krw=rec.ask_price_krw,
        area_m2=rec.area_m2,
        floor=rec.floor,
        listed_at=None,
        collected_at=rec.as_of,
        building_id=None,
        agency=None,
        status=rec.status,
        source=rec.source,
        as_of=rec.as_of,
    )
