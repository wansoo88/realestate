"""PostGIS 리포지토리 — `base.py` 의 Protocol 4종을 실제 DB 위에서 구현한다.

왜 ORM 이 아니라 SQL 인가
--------------------------
스키마의 단일 진실 소스는 `migrations/001_init.sql` 이다.
ORM 모델을 따로 두면 두 벌이 되고, 언젠가 반드시 어긋난다 —
그리고 어긋난 걸 알게 되는 시점은 배포 직후다.
여기서는 SQLAlchemy 를 **연결·트랜잭션·파라미터 바인딩**에만 쓰고
쿼리는 SQL 로 적는다. 공간 연산자(`&&`)와 LATERAL 은 어차피 ORM 으로 표현할 게 없다.

공간 쿼리 규약 (erd.md §3.1)
----------------------------
지도 범위 조회는 반드시 `geom && ST_MakeEnvelope(...)` 로 시작한다.
`ST_Intersects` 를 먼저 태우면 GiST 인덱스를 못 쓰고 전건 스캔이 된다.
정밀 판정이 필요하면 `&&` 로 후보를 줄인 **뒤에** 얹는다.

⚠️ IDOR 방지 규약 (security.md §2.2)
------------------------------------
사용자 자원 쿼리에는 예외 없이 `user_id` 조건이 들어간다.
`get_job` 은 job_id 만으로 조회할 방법을 제공하지 않는다.
"""
from __future__ import annotations

import json
import logging
from decimal import Decimal
from typing import Any

from sqlalchemy import text
from sqlalchemy.engine import Engine
from sqlalchemy.exc import IntegrityError

# 반경·유해요소 기준은 **도메인이 소유한다**(re-domain). 여기서 숫자를 새로 만들지 않고
# 가져다 쓴다 — 두 곳에 적으면 언젠가 리포지토리가 넘긴 사실과 도메인의 판정 기준이
# 어긋나고, 그러면 "왜 이 단지가 감점됐는지"를 아무도 설명할 수 없게 된다.
from app.domain.location.analysis import HAZARD_RADIUS_M, PROXIMITY_BANDS
from app.domain.location.models import (
    BuildingLocationFact,
    HazardFact,
    LocationFacts,
    PoiFact,
    SchoolFact,
    StationFact,
    TransitPlan,
)
from app.repositories.base import (
    ComplexSummary,
    JobRecord,
    ProfileRecord,
    UserRecord,
)

logger = logging.getLogger("app.repositories.postgis")

#: PostgreSQL unique_violation
_UNIQUE_VIOLATION = "23505"

# --- 공간 탐색 상수 -------------------------------------------------------
#: 위경도 → 미터 근사. 북위 37.5°(수도권)에서 **경도** 1도가 약 88.3km 로 가장 짧다.
#: 88,000 으로 나누면 bbox 가 넉넉해진다(위도 쪽은 과대 포함). 좁게 잡으면 후보를
#: 놓치는데, ST_Expand 는 GiST 인덱스를 태우기 위한 1차 필터일 뿐이고
#: 정밀 판정은 뒤의 geography 거리 계산이 하므로 넉넉한 쪽이 안전하다.
_M_PER_DEG = 88_000.0

#: 역 탐색 반경. 점수 밴드(worst=1500m)보다 **넓게** 잡는다 —
#: "최근접 역이 2.4km" 도 엄연한 사실이고, 안 넘기면 도메인이 '정보 없음'으로 처리해
#: 역이 먼 단지와 역 데이터가 없는 단지가 구분되지 않는다.
_STATION_RADIUS_M = 3_000.0
_STATION_LIMIT = 5

#: 생활 인프라 탐색 반경 = 도메인 근접 밴드의 worst 값.
_MART_RADIUS_M = float(PROXIMITY_BANDS["mart"][1])
_PARK_RADIUS_M = float(PROXIMITY_BANDS["park"][1])
_HOSPITAL_RADIUS_M = float(PROXIMITY_BANDS["hospital_er"][1])

#: 유해요소는 도메인이 '존재'로 보는 반경 안의 것만 넘긴다(models.py HazardFact).
_HAZARD_SCAN_RADIUS_M = float(max(HAZARD_RADIUS_M.values()))

#: 동별 간선도로 거리 밴드가 (30,300)m 라 그보다 넉넉히 본다.
_BUILDING_ROAD_RADIUS_M = 1_000.0

#: 이 반경 안에 학구도 폴리곤이 하나도 없으면 "학구도 미확보"로 본다.
#: 포함이 아닌 것과 데이터가 없는 것은 다르다 — 도메인이 이 둘을 다르게 처리한다.
_DISTRICT_DATA_RADIUS_M = 5_000.0

# --- poi.category 규약 ----------------------------------------------------
# erd.md 의 `poi` 주석: school/subway/mart/hospital/park/hazard/road
# ⚠️ **re-data 와의 데이터 계약이다.** 아래 category·attrs 키를 채우지 않으면
#    입지 분석은 조용히 빈 결과를 낸다(틀린 값을 내지는 않는다).
_CAT_SUBWAY = "subway"
_CAT_MART = "mart"
_CAT_PARK = "park"
_CAT_HOSPITAL = "hospital"
_HAZARD_CATEGORIES = ["hazard", "road"]

#: category → HazardFact.kind 유추. `attrs->>'hazard_kind'` 가 우선이다.
#: 둘 다 없으면 그 행은 **버린다** — 도메인은 "알 수 없는 종류는 존재 자체로 본다"라
#: 종류 미상 행을 넘기면 근거 없는 감점이 생긴다.
_CATEGORY_TO_HAZARD = {"road": "main_road_noise"}

#: 통학로 횡단 판정에 쓰는 도로 등급(003 `road_segment`).
#: 이면도로까지 넣으면 모든 단지가 '대로 횡단'이 돼 판정이 무의미해진다.
_MAIN_ROAD_CLASSES = ["고속도로", "자동차전용", "간선"]

#: attrs 에서 참으로 읽을 값들(더러운 데이터에 캐스팅 예외로 죽지 않게).
_TRUTHY_SQL = "('true','t','1','y','yes')"


def create_db_engine(settings, **kwargs: Any) -> Engine:
    """설정에서 엔진을 만든다.

    `pool_pre_ping` 은 필수다. VPS 단일 서버라 DB 재시작·네트워크 끊김이
    그대로 죽은 커넥션으로 남고, 그러면 첫 요청이 원인 모를 500 이 된다.
    """
    from sqlalchemy import create_engine

    kwargs.setdefault("pool_pre_ping", True)
    kwargs.setdefault("pool_size", 5)
    kwargs.setdefault("max_overflow", 5)
    return create_engine(settings.database_url, **kwargs)


def _is_unique_violation(exc: IntegrityError) -> bool:
    return getattr(getattr(exc, "orig", None), "sqlstate", None) == _UNIQUE_VIOLATION


def _as_bytes(value: Any) -> bytes | None:
    """bytea 는 드라이버에 따라 memoryview 로 올 수 있다. 항상 bytes 로 맞춘다."""
    if value is None:
        return None
    return bytes(value)


def _as_float(value: Any) -> float | None:
    if value is None:
        return None
    return float(value) if isinstance(value, Decimal) else value


def _deg(radius_m: float) -> float:
    """미터 반경 → `ST_Expand` 용 도(degree). 넉넉히 잡는다(위 `_M_PER_DEG` 주석)."""
    return radius_m / _M_PER_DEG


def _opt_float(value: Any) -> float | None:
    """attrs 의 문자열 수치를 float 로. 못 읽으면 **추정하지 않고 None**."""
    if value in (None, ""):
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _norm_email(email: str) -> str:
    # 컬럼은 citext 라 DB 가 대소문자를 무시하지만, 반환값 표기를 인메모리 구현과
    # 똑같이 맞춰 둔다(둘 사이에서 테스트가 갈리지 않게).
    return email.strip().lower()


class PostgisRepository:
    """UserRepository · ProfileRepository · MapRepository · JobRepository 구현.

    메서드마다 트랜잭션을 연다. 요청 하나가 여러 메서드를 부르는 경우가 없고,
    커넥션을 요청 수명에 묶으면 `get_repo` 부터 다시 짜야 한다.
    """

    def __init__(self, engine: Engine) -> None:
        self._engine = engine

    def close(self) -> None:
        self._engine.dispose()

    # -- 사용자 -----------------------------------------------------------

    def create_user(self, email: str, password_hash: str) -> UserRecord:
        sql = text("""
            INSERT INTO app_user (email, password_hash)
            VALUES (:email, :password_hash)
            RETURNING id, email::text AS email, password_hash
        """)
        try:
            with self._engine.begin() as conn:
                row = conn.execute(
                    sql, {"email": _norm_email(email), "password_hash": password_hash}
                ).one()
        except IntegrityError as exc:
            if _is_unique_violation(exc):
                # 라우터가 409 로 바꾼다. 인메모리 구현과 같은 예외를 던져야
                # 리포지토리를 갈아끼워도 API 동작이 바뀌지 않는다.
                raise ValueError("이미 등록된 이메일입니다") from exc
            raise
        return UserRecord(id=row.id, email=row.email, password_hash=row.password_hash)

    def get_user_by_email(self, email: str) -> UserRecord | None:
        sql = text("""
            SELECT id, email::text AS email, password_hash
            FROM app_user WHERE email = :email
        """)
        with self._engine.connect() as conn:
            row = conn.execute(sql, {"email": _norm_email(email)}).one_or_none()
        if row is None:
            return None
        return UserRecord(id=row.id, email=row.email, password_hash=row.password_hash)

    def get_user(self, user_id: int) -> UserRecord | None:
        sql = text("""
            SELECT id, email::text AS email, password_hash
            FROM app_user WHERE id = :user_id
        """)
        with self._engine.connect() as conn:
            row = conn.execute(sql, {"user_id": user_id}).one_or_none()
        if row is None:
            return None
        return UserRecord(id=row.id, email=row.email, password_hash=row.password_hash)

    # -- 프로필 (민감) -----------------------------------------------------
    # 금액 3종은 **암호문 bytea 로만** 오간다. 이 클래스는 평문을 본 적이 없다.

    def get_profile(self, user_id: int) -> ProfileRecord | None:
        sql = text("""
            SELECT user_id, cash_krw_enc, income_krw_enc, existing_loan_krw_enc,
                   owned_houses, household_size
            FROM user_profile WHERE user_id = :user_id
        """)
        with self._engine.connect() as conn:
            row = conn.execute(sql, {"user_id": user_id}).one_or_none()
        if row is None:
            return None
        return ProfileRecord(
            user_id=row.user_id,
            cash_krw_enc=_as_bytes(row.cash_krw_enc),
            income_krw_enc=_as_bytes(row.income_krw_enc),
            existing_loan_krw_enc=_as_bytes(row.existing_loan_krw_enc),
            owned_houses=row.owned_houses,
            # 컬럼은 NULL 을 허용하지만 도메인 기본값은 1인 가구다.
            household_size=row.household_size if row.household_size is not None else 1,
        )

    def upsert_profile(self, profile: ProfileRecord) -> ProfileRecord:
        sql = text("""
            INSERT INTO user_profile (
                user_id, cash_krw_enc, income_krw_enc, existing_loan_krw_enc,
                owned_houses, household_size, updated_at)
            VALUES (:user_id, :cash, :income, :loan, :owned, :household, now())
            ON CONFLICT (user_id) DO UPDATE SET
                cash_krw_enc          = EXCLUDED.cash_krw_enc,
                income_krw_enc        = EXCLUDED.income_krw_enc,
                existing_loan_krw_enc = EXCLUDED.existing_loan_krw_enc,
                owned_houses          = EXCLUDED.owned_houses,
                household_size        = EXCLUDED.household_size,
                updated_at            = now()
        """)
        with self._engine.begin() as conn:
            conn.execute(sql, {
                "user_id": profile.user_id,
                "cash": profile.cash_krw_enc,
                "income": profile.income_krw_enc,
                "loan": profile.existing_loan_krw_enc,
                "owned": profile.owned_houses,
                "household": profile.household_size,
            })
        return profile

    def get_preferences(self, user_id: int) -> dict[str, Any]:
        # 002 이후 사용자당 1행이 보장되지만, 002 미적용 DB 에서 MultipleResultsFound 로
        # 터지는 대신 예전과 같은 행(가장 오래된 행)을 읽도록 LIMIT 1 을 남겨 둔다.
        sql = text("""
            SELECT prefer, avoid, weights
            FROM user_preference WHERE user_id = :user_id
            ORDER BY id LIMIT 1
        """)
        with self._engine.connect() as conn:
            row = conn.execute(sql, {"user_id": user_id}).one_or_none()
        if row is None:
            return {"prefer": {}, "avoid": {}, "weights": {}}
        return {"prefer": row.prefer, "avoid": row.avoid, "weights": row.weights}

    def set_preferences(self, user_id: int, prefs: dict[str, Any]) -> dict[str, Any]:
        """사용자당 1세트 upsert. `UNIQUE (user_id)` 전제 — 002 마이그레이션 필요."""
        sql = text("""
            INSERT INTO user_preference (user_id, prefer, avoid, weights)
            VALUES (:user_id, CAST(:prefer AS jsonb), CAST(:avoid AS jsonb),
                    CAST(:weights AS jsonb))
            ON CONFLICT (user_id) DO UPDATE SET
                prefer  = EXCLUDED.prefer,
                avoid   = EXCLUDED.avoid,
                weights = EXCLUDED.weights
        """)
        with self._engine.begin() as conn:
            conn.execute(sql, {
                "user_id": user_id,
                "prefer": json.dumps(prefs.get("prefer") or {}, ensure_ascii=False),
                "avoid": json.dumps(prefs.get("avoid") or {}, ensure_ascii=False),
                "weights": json.dumps(prefs.get("weights") or {}, ensure_ascii=False),
            })
        return prefs

    # -- 지도 (F1) ---------------------------------------------------------

    #: `&&` 가 GiST(idx_complex_geom)를 탄다. ST_Intersects 를 앞에 두지 말 것.
    #: geom 이 NULL 인 단지는 `&&` 가 NULL 을 내며 자연히 빠진다 —
    #: 좌표 없는 단지는 지도에 찍을 수 없으므로 그게 맞다.
    _BBOX_SQL = text("""
        SELECT c.id,
               c.name,
               ST_X(c.geom)      AS lon,
               ST_Y(c.geom)      AS lat,
               c.region_code,
               c.built_year,
               c.total_households,
               t.price_krw       AS recent_price_krw,
               t.contract_date   AS price_as_of,
               COALESCE(l.active_listings, 0) AS active_listings
        FROM complex c
        LEFT JOIN LATERAL (
            -- idx_trade_complex_date (complex_id, contract_date DESC)
            -- 해제된 거래는 시세가 아니다. 통계에서 뺀다.
            SELECT tr.price_krw, tr.contract_date
            FROM trade tr
            WHERE tr.complex_id = c.id AND NOT tr.is_cancelled
            ORDER BY tr.contract_date DESC
            LIMIT 1
        ) t ON true
        LEFT JOIN LATERAL (
            -- idx_listing_active (complex_id) WHERE status='active'
            -- 중복 매물(duplicate_of)은 대표건만 센다 — 같은 물건이 3건으로 보이면 안 된다.
            SELECT count(*) AS active_listings
            FROM listing li
            WHERE li.complex_id = c.id
              AND li.status = 'active'
              AND li.duplicate_of IS NULL
        ) l ON true
        WHERE c.geom && ST_MakeEnvelope(
                  CAST(:min_lon AS double precision),
                  CAST(:min_lat AS double precision),
                  CAST(:max_lon AS double precision),
                  CAST(:max_lat AS double precision), 4326)
          AND (CAST(:built_after AS int) IS NULL
               OR c.built_year >= CAST(:built_after AS int))
          AND (
                (CAST(:area_min AS numeric) IS NULL AND CAST(:area_max AS numeric) IS NULL)
                OR EXISTS (
                    SELECT 1 FROM unit_type u
                    WHERE u.complex_id = c.id
                      AND (CAST(:area_min AS numeric) IS NULL
                           OR u.area_m2 >= CAST(:area_min AS numeric))
                      AND (CAST(:area_max AS numeric) IS NULL
                           OR u.area_m2 <= CAST(:area_max AS numeric))
                )
              )
        ORDER BY c.id
        LIMIT CAST(:limit AS int)
    """)

    def complexes_in_bbox(
        self, *, min_lon: float, min_lat: float, max_lon: float, max_lat: float,
        max_price_krw: int | None = None,
        area_min_m2: float | None = None,
        area_max_m2: float | None = None,
        built_after: int | None = None,
        limit: int = 500,
    ) -> list[ComplexSummary]:
        # max_price_krw 로 **걸러내지 않는다.** 예산을 넘는 단지도 그대로 넘기고
        # 호출부가 흐리게 표시한다 — 왜 후보에 없는지 보이게 하려는 것(ux/README.md §4).
        params = {
            "min_lon": min_lon, "min_lat": min_lat,
            "max_lon": max_lon, "max_lat": max_lat,
            "built_after": built_after,
            "area_min": area_min_m2,
            "area_max": area_max_m2,
            "limit": limit,
        }
        with self._engine.connect() as conn:
            rows = conn.execute(self._BBOX_SQL, params).all()

        return [
            ComplexSummary(
                id=row.id,
                name=row.name,
                lon=row.lon,
                lat=row.lat,
                # region_code 는 char(10) 이라 공백 패딩이 붙어 올 수 있다.
                region_code=(row.region_code or "").rstrip(),
                built_year=row.built_year,
                total_households=row.total_households,
                recent_price_krw=row.recent_price_krw,
                # 신고 지연이 있으므로 '언제 거래된 값인지'를 반드시 같이 보낸다.
                price_as_of=row.price_as_of.isoformat() if row.price_as_of else None,
                active_listings=row.active_listings,
            )
            for row in rows
        ]

    # -- 추천 작업 ---------------------------------------------------------

    def create_job(self, job_id: str, user_id: int,
                   criteria: dict[str, Any]) -> JobRecord:
        sql = text("""
            INSERT INTO recommendation_job (id, user_id, criteria_snapshot, status)
            VALUES (:job_id, :user_id, CAST(:criteria AS jsonb), 'queued')
        """)
        with self._engine.begin() as conn:
            conn.execute(sql, {
                "job_id": job_id,
                "user_id": user_id,
                # criteria_snapshot 은 재현성 근거다(G2). 원문 그대로 남긴다.
                "criteria": json.dumps(criteria, ensure_ascii=False, default=str),
            })
        return JobRecord(id=job_id, user_id=user_id, criteria_snapshot=criteria)

    def get_job(self, job_id: str, user_id: int) -> JobRecord | None:
        """소유권 검증을 쿼리 안에서 강제한다 (IDOR 방지).

        `user_id` 를 WHERE 에서 빼는 순간 남의 추천 결과가 새어나간다.
        """
        job_sql = text("""
            SELECT id, user_id, criteria_snapshot, status
            FROM recommendation_job
            WHERE id = :job_id AND user_id = :user_id
        """)
        # rank 는 SQL 함수명과 겹치므로 전부 테이블 별칭을 붙여 둔다.
        items_sql = text("""
            SELECT ri.id, ri.complex_id, ri.building_id, ri.unit_type_id, ri.rank,
                   ri.total_score, ri.est_price_krw, ri.timing_signal
            FROM recommendation_item ri
            WHERE ri.job_id = :job_id
            ORDER BY ri.rank NULLS LAST, ri.id
        """)
        with self._engine.connect() as conn:
            job = conn.execute(job_sql, {"job_id": job_id, "user_id": user_id}).one_or_none()
            if job is None:
                return None
            items = conn.execute(items_sql, {"job_id": job_id}).all()

        return JobRecord(
            id=job.id,
            user_id=job.user_id,
            criteria_snapshot=job.criteria_snapshot or {},
            status=job.status,
            items=[
                {
                    "id": it.id,
                    "complex_id": it.complex_id,
                    "building_id": it.building_id,
                    "unit_type_id": it.unit_type_id,
                    "rank": it.rank,
                    "total_score": _as_float(it.total_score),
                    "est_price_krw": it.est_price_krw,
                    "timing_signal": it.timing_signal,
                }
                for it in items
            ],
        )

    # -- 입지 (location-analyst 입력) --------------------------------------
    #
    # 공간 판정은 전부 여기서 끝낸다. 도메인에는 **사실만** 넘어간다.
    # 모든 쿼리가 같은 형태다: `&&` + ST_Expand 로 GiST 인덱스를 태워 후보를 줄이고
    # (erd.md §3.1), 그 다음 geography 로 정확한 미터 거리를 잰다.
    # geom 이 4326(도) 이라 ST_Distance 를 그냥 쓰면 결과가 '도' 로 나온다 — 반드시
    # ::geography 캐스팅. 이걸 빠뜨리면 거리가 조용히 10만배쯤 틀린다.

    #: 003 이후 `sd.as_of` 가 기준연도의 정본이다. 없으면 poi.attrs 로 폴백한다
    #: (003 적용 전 적재분 호환). 둘 다 없으면 기준일자 미상 → 근거로 쓰지 않는다.
    _SCHOOL_SQL = text("""
        SELECT p.name,
               ST_Distance(p.geom::geography, c.geom::geography) AS distance_m,
               p.attrs,
               sd.as_of AS district_as_of,
               -- 통학로가 간선급 도로를 건너는가. 단지→학교 직선과 도로 선형의 교차.
               -- road_segment 에 데이터가 없으면 false 가 아니라 **NULL(모름)** 이어야
               -- 하므로 EXISTS 를 쓰지 않고 데이터 유무를 따로 센다.
               (SELECT count(*) FROM road_segment r
                 WHERE r.road_class = ANY(CAST(:main_road_classes AS text[]))
                   AND r.geom && ST_Expand(c.geom, CAST(:road_deg AS double precision))
               ) AS road_rows_nearby,
               (SELECT count(*) FROM road_segment r
                 WHERE r.road_class = ANY(CAST(:main_road_classes AS text[]))
                   AND r.geom && ST_MakeLine(c.geom, p.geom)
                   AND ST_Intersects(r.geom, ST_MakeLine(c.geom, p.geom))
               ) AS road_crossings
        FROM complex c
        JOIN school_district sd
          ON sd.geom && c.geom                 -- GiST 먼저
         AND ST_Contains(sd.geom, c.geom)      -- 그 다음 정밀 포함 판정
        JOIN poi p ON p.id = sd.school_poi_id
        WHERE c.id = :complex_id
        ORDER BY distance_m NULLS LAST
        LIMIT 1
    """)

    _DISTRICT_AVAILABLE_SQL = text("""
        SELECT EXISTS (
            SELECT 1
            FROM complex c
            JOIN school_district sd
              ON sd.geom && ST_Expand(c.geom, CAST(:deg AS double precision))
            WHERE c.id = :complex_id
        ) AS available
    """)

    _STATIONS_SQL = text("""
        SELECT p.name,
               ST_Distance(p.geom::geography, c.geom::geography) AS distance_m,
               p.attrs
        FROM complex c
        JOIN poi p
          ON p.category = :category
         AND p.geom && ST_Expand(c.geom, CAST(:deg AS double precision))
        WHERE c.id = :complex_id
          AND ST_DWithin(p.geom::geography, c.geom::geography,
                         CAST(:radius AS double precision))
        ORDER BY distance_m
        LIMIT CAST(:limit AS int)
    """)

    #: 마트·공원·병원(전체)·병원(응급실). 병원을 둘로 나눠 뽑는 이유는
    #: 도메인이 `nearest("hospital", er=True)` 와 `nearest("hospital")` 을 **따로**
    #: 묻기 때문이다. 가장 가까운 병원에 응급실이 없으면 둘은 다른 곳이다.
    _POIS_SQL = text(f"""
        SELECT m.name  AS mart_name,  m.distance_m  AS mart_distance_m,
               pk.name AS park_name,  pk.distance_m AS park_distance_m,
               h.name  AS hosp_name,  h.distance_m  AS hosp_distance_m,
               h.has_er AS hosp_has_er,
               er.name AS er_name,    er.distance_m AS er_distance_m
        -- 단지 한 행으로 먼저 좁힌 뒤 LATERAL 을 태운다. WHERE 를 뒤에 두면
        -- 플래너가 전 단지에 대해 LATERAL 을 돌릴 여지를 남긴다.
        FROM (SELECT geom FROM complex WHERE id = :complex_id) c
        LEFT JOIN LATERAL (
            SELECT p.name, ST_Distance(p.geom::geography, c.geom::geography) AS distance_m
            FROM poi p
            WHERE p.category = :mart_category
              AND p.geom && ST_Expand(c.geom, CAST(:mart_deg AS double precision))
              AND ST_DWithin(p.geom::geography, c.geom::geography,
                             CAST(:mart_radius AS double precision))
            ORDER BY distance_m LIMIT 1
        ) m ON true
        LEFT JOIN LATERAL (
            SELECT p.name, ST_Distance(p.geom::geography, c.geom::geography) AS distance_m
            FROM poi p
            WHERE p.category = :park_category
              AND p.geom && ST_Expand(c.geom, CAST(:park_deg AS double precision))
              AND ST_DWithin(p.geom::geography, c.geom::geography,
                             CAST(:park_radius AS double precision))
            ORDER BY distance_m LIMIT 1
        ) pk ON true
        LEFT JOIN LATERAL (
            SELECT p.name, ST_Distance(p.geom::geography, c.geom::geography) AS distance_m,
                   lower(COALESCE(p.attrs->>'has_emergency_room','')) IN {_TRUTHY_SQL}
                       AS has_er
            FROM poi p
            WHERE p.category = :hospital_category
              AND p.geom && ST_Expand(c.geom, CAST(:hospital_deg AS double precision))
              AND ST_DWithin(p.geom::geography, c.geom::geography,
                             CAST(:hospital_radius AS double precision))
            ORDER BY distance_m LIMIT 1
        ) h ON true
        LEFT JOIN LATERAL (
            SELECT p.name, ST_Distance(p.geom::geography, c.geom::geography) AS distance_m
            FROM poi p
            WHERE p.category = :hospital_category
              AND lower(COALESCE(p.attrs->>'has_emergency_room','')) IN {_TRUTHY_SQL}
              AND p.geom && ST_Expand(c.geom, CAST(:hospital_deg AS double precision))
              AND ST_DWithin(p.geom::geography, c.geom::geography,
                             CAST(:hospital_radius AS double precision))
            ORDER BY distance_m LIMIT 1
        ) er ON true
    """)

    _HAZARDS_SQL = text("""
        SELECT p.category,
               COALESCE(p.attrs->>'hazard_kind', '') AS hazard_kind,
               p.attrs->>'detail' AS detail,
               p.name,
               ST_Distance(p.geom::geography, c.geom::geography) AS distance_m
        FROM complex c
        JOIN poi p
          ON p.category = ANY(CAST(:categories AS text[]))
         AND p.geom && ST_Expand(c.geom, CAST(:deg AS double precision))
        WHERE c.id = :complex_id
          AND ST_DWithin(p.geom::geography, c.geom::geography,
                         CAST(:radius AS double precision))
        ORDER BY distance_m
    """)

    #: 신설 노선 계획. `transit_plan.status` 는 계획|착공|개통 —
    #: 신뢰도 환산은 도메인(`plan_confidence`)이 한다. 여기서는 단계만 넘긴다.
    _PLANS_SQL = text("""
        SELECT tp.name, tp.status, tp.open_expected, tp.source_url
        FROM complex c
        JOIN transit_plan tp
          ON tp.geom && ST_Expand(c.geom, CAST(:deg AS double precision))
         AND ST_DWithin(tp.geom::geography, c.geom::geography,
                        CAST(:radius AS double precision))
        WHERE c.id = :complex_id
        ORDER BY tp.open_expected NULLS LAST
    """)

    def location_facts(self, complex_id: int) -> LocationFacts | None:
        with self._engine.connect() as conn:
            exists = conn.execute(
                text("SELECT geom IS NOT NULL AS has_geom FROM complex WHERE id = :cid"),
                {"cid": complex_id},
            ).one_or_none()
            if exists is None:
                return None
            if not exists.has_geom:
                # 좌표가 없으면 공간 판정을 할 수 없다. 빈 사실을 넘겨
                # 도메인이 '정보 없음'으로 처리하게 한다(추정하지 않는다).
                logger.warning("단지 %s 에 좌표가 없어 입지 분석을 건너뜁니다", complex_id)
                return LocationFacts()

            school = self._fetch_school(conn, complex_id)
            stations = self._fetch_stations(conn, complex_id)
            plans = self._fetch_plans(conn, complex_id)
            pois = self._fetch_pois(conn, complex_id)
            hazards = self._fetch_hazards(conn, complex_id)

        return LocationFacts(school=school, stations=stations, plans=plans,
                             pois=pois, hazards=hazards)

    # --- 입지 조각들 ------------------------------------------------------

    def _fetch_school(self, conn, complex_id: int) -> SchoolFact | None:
        row = conn.execute(self._SCHOOL_SQL, {
            "complex_id": complex_id,
            "main_road_classes": _MAIN_ROAD_CLASSES,
            "road_deg": _deg(_BUILDING_ROAD_RADIUS_M),
        }).one_or_none()
        available = conn.execute(self._DISTRICT_AVAILABLE_SQL, {
            "complex_id": complex_id, "deg": _deg(_DISTRICT_DATA_RADIUS_M),
        }).one().available

        if row is None:
            # 학구도에 포함되지 않았다. **최근접 학교 거리로 대체하지 않는다** —
            # 배정과 거리는 다른 개념이다(models.py 절대 규칙 1).
            # 주변에 학구도 데이터 자체가 없으면 '미확보'로 구분해 넘긴다.
            return SchoolFact(district_data_available=bool(available))

        attrs = row.attrs or {}
        # 주변에 도로 선형 데이터가 아예 없으면 "안 건넌다"가 아니라 **모른다**.
        # False 로 두면 없는 안전을 지어내는 셈이고, 도메인은 False 를 감점하지 않는다.
        # 교차가 잡혔으면 탐색 반경과 무관하게 True 다(학교가 반경보다 멀 수 있다).
        if row.road_crossings:
            crosses: bool | None = True
        elif row.road_rows_nearby:
            crosses = False
        else:
            crosses = None
        return SchoolFact(
            name=row.name,
            in_district=True,
            distance_m=_as_float(row.distance_m),
            crosses_main_road=crosses,
            # 003 의 sd.as_of 가 정본. 없으면 attrs 폴백(003 적용 전 적재분 호환).
            district_as_of=(row.district_as_of.isoformat() if row.district_as_of
                            else attrs.get("district_as_of")),
            district_data_available=True,
            achievement_pct=_opt_float(attrs.get("achievement_pct")),
            achievement_source=attrs.get("achievement_source"),
            achievement_as_of=attrs.get("achievement_as_of"),
        )

    def _fetch_stations(self, conn, complex_id: int) -> tuple[StationFact, ...]:
        rows = conn.execute(self._STATIONS_SQL, {
            "complex_id": complex_id, "category": _CAT_SUBWAY,
            "deg": _deg(_STATION_RADIUS_M), "radius": _STATION_RADIUS_M,
            "limit": _STATION_LIMIT,
        }).all()
        out: list[StationFact] = []
        for row in rows:
            lines = (row.attrs or {}).get("lines") or []
            out.append(StationFact(
                name=row.name or "이름 미상",
                distance_m=_as_float(row.distance_m),
                lines=tuple(str(x) for x in lines),
            ))
        return tuple(out)

    def _fetch_plans(self, conn, complex_id: int) -> tuple[TransitPlan, ...]:
        rows = conn.execute(self._PLANS_SQL, {
            "complex_id": complex_id, "deg": _deg(_STATION_RADIUS_M),
            "radius": _STATION_RADIUS_M,
        }).all()
        return tuple(
            TransitPlan(
                name=row.name,
                status=row.status or "계획",   # 단계 미상은 가장 보수적으로
                open_expected=row.open_expected.isoformat() if row.open_expected else None,
                source=row.source_url,
                as_of=None,
            )
            for row in rows
        )

    def _fetch_pois(self, conn, complex_id: int) -> tuple[PoiFact, ...]:
        row = conn.execute(self._POIS_SQL, {
            "complex_id": complex_id,
            "mart_category": _CAT_MART,
            "mart_deg": _deg(_MART_RADIUS_M), "mart_radius": _MART_RADIUS_M,
            "park_category": _CAT_PARK,
            "park_deg": _deg(_PARK_RADIUS_M), "park_radius": _PARK_RADIUS_M,
            "hospital_category": _CAT_HOSPITAL,
            "hospital_deg": _deg(_HOSPITAL_RADIUS_M),
            "hospital_radius": _HOSPITAL_RADIUS_M,
        }).one_or_none()
        if row is None:
            return ()

        out: list[PoiFact] = []
        if row.mart_distance_m is not None:
            out.append(PoiFact(kind="mart", distance_m=_as_float(row.mart_distance_m),
                               name=row.mart_name))
        if row.park_distance_m is not None:
            out.append(PoiFact(kind="park", distance_m=_as_float(row.park_distance_m),
                               name=row.park_name))
        if row.hosp_distance_m is not None:
            out.append(PoiFact(kind="hospital", distance_m=_as_float(row.hosp_distance_m),
                               name=row.hosp_name,
                               has_emergency_room=bool(row.hosp_has_er)))
        # 최근접 병원에 응급실이 없으면 응급실 있는 병원을 **따로** 넘긴다.
        if row.er_distance_m is not None and not row.hosp_has_er:
            out.append(PoiFact(kind="hospital", distance_m=_as_float(row.er_distance_m),
                               name=row.er_name, has_emergency_room=True))
        return tuple(out)

    def _fetch_hazards(self, conn, complex_id: int) -> tuple[HazardFact, ...]:
        rows = conn.execute(self._HAZARDS_SQL, {
            "complex_id": complex_id, "categories": _HAZARD_CATEGORIES,
            "deg": _deg(_HAZARD_SCAN_RADIUS_M), "radius": _HAZARD_SCAN_RADIUS_M,
        }).all()

        out: list[HazardFact] = []
        for row in rows:
            kind = row.hazard_kind or _CATEGORY_TO_HAZARD.get(row.category, "")
            if kind not in HAZARD_RADIUS_M:
                # 종류를 모르는 행은 버린다. 넘기면 도메인이 '존재'로 보고 감점하는데,
                # 무엇 때문에 감점됐는지 설명할 수 없는 근거는 G2 위반이다.
                logger.debug("유해요소 종류를 알 수 없어 제외: category=%s name=%s",
                             row.category, row.name)
                continue
            distance = _as_float(row.distance_m)
            # 도메인이 '존재'로 보는 반경 안의 것만 넘긴다(models.py HazardFact).
            if distance is None or distance > HAZARD_RADIUS_M[kind]:
                continue
            out.append(HazardFact(kind=kind, distance_m=distance,
                                  detail=row.detail or row.name))
        return tuple(out)

    # --- 동(棟)별 사실 ----------------------------------------------------

    _BUILDINGS_SQL = text("""
        WITH bldg AS (
            SELECT b.id, b.name, b.geom, b.direction_deg
            FROM building b WHERE b.complex_id = :complex_id
        ),
        -- 단지 중심 = 동 좌표들의 무게중심. 집계라 행이 없어도 1행(NULL)을 낸다.
        center AS (
            SELECT ST_Centroid(ST_Collect(geom)) AS geom FROM bldg WHERE geom IS NOT NULL
        ),
        -- 학구도 데이터가 이 근처에 있기는 한가 (포함 아님 ≠ 데이터 없음)
        district AS (
            SELECT EXISTS (
                SELECT 1 FROM complex c
                JOIN school_district sd
                  ON sd.geom && ST_Expand(c.geom, CAST(:district_deg AS double precision))
                WHERE c.id = :complex_id
            ) AS available
        )
        SELECT b.id, b.name, b.direction_deg,
               ST_Distance(b.geom::geography, center.geom::geography) AS center_distance_m,
               st.distance_m AS station_distance_m,
               sc.distance_m AS school_distance_m,
               CASE WHEN sc.distance_m IS NOT NULL THEN true
                    WHEN district.available THEN false
                    ELSE NULL END AS school_in_district,
               pk.distance_m AS park_distance_m,
               -- 도로 선형(003)이 있으면 그게 정확하다. 점(poi) 근사치와 함께
               -- **가까운 쪽**을 쓴다 — 도로가 가까울수록 감점이므로 보수적이다.
               -- LEAST 는 NULL 을 무시하므로 한쪽만 있어도 그대로 동작한다.
               LEAST(rd.distance_m, rs.distance_m) AS main_road_distance_m
        FROM bldg b
        CROSS JOIN center
        CROSS JOIN district
        LEFT JOIN LATERAL (
            SELECT ST_Distance(p.geom::geography, b.geom::geography) AS distance_m
            FROM poi p
            WHERE p.category = :subway_category
              AND p.geom && ST_Expand(b.geom, CAST(:station_deg AS double precision))
              AND ST_DWithin(p.geom::geography, b.geom::geography,
                             CAST(:station_radius AS double precision))
            ORDER BY distance_m LIMIT 1
        ) st ON true
        LEFT JOIN LATERAL (
            SELECT ST_Distance(p.geom::geography, b.geom::geography) AS distance_m
            FROM school_district sd
            JOIN poi p ON p.id = sd.school_poi_id
            WHERE sd.geom && b.geom AND ST_Contains(sd.geom, b.geom)
            ORDER BY distance_m LIMIT 1
        ) sc ON true
        LEFT JOIN LATERAL (
            SELECT ST_Distance(p.geom::geography, b.geom::geography) AS distance_m
            FROM poi p
            WHERE p.category = :park_category
              AND p.geom && ST_Expand(b.geom, CAST(:park_deg AS double precision))
              AND ST_DWithin(p.geom::geography, b.geom::geography,
                             CAST(:park_radius AS double precision))
            ORDER BY distance_m LIMIT 1
        ) pk ON true
        LEFT JOIN LATERAL (
            SELECT ST_Distance(p.geom::geography, b.geom::geography) AS distance_m
            FROM poi p
            WHERE p.category = ANY(CAST(:hazard_categories AS text[]))
              AND COALESCE(p.attrs->>'hazard_kind',
                           CASE WHEN p.category = 'road' THEN 'main_road_noise' END)
                  = 'main_road_noise'
              AND p.geom && ST_Expand(b.geom, CAST(:road_deg AS double precision))
              AND ST_DWithin(p.geom::geography, b.geom::geography,
                             CAST(:road_radius AS double precision))
            ORDER BY distance_m LIMIT 1
        ) rd ON true
        LEFT JOIN LATERAL (
            SELECT ST_Distance(r.geom::geography, b.geom::geography) AS distance_m
            FROM road_segment r
            WHERE r.road_class = ANY(CAST(:main_road_classes AS text[]))
              AND r.geom && ST_Expand(b.geom, CAST(:road_deg AS double precision))
              AND ST_DWithin(r.geom::geography, b.geom::geography,
                             CAST(:road_radius AS double precision))
            ORDER BY distance_m LIMIT 1
        ) rs ON true
        ORDER BY b.id
    """)

    def building_location_facts(self, complex_id: int) -> list[BuildingLocationFact]:
        with self._engine.connect() as conn:
            rows = conn.execute(self._BUILDINGS_SQL, {
                "complex_id": complex_id,
                "subway_category": _CAT_SUBWAY,
                "station_deg": _deg(_STATION_RADIUS_M),
                "station_radius": _STATION_RADIUS_M,
                "park_category": _CAT_PARK,
                "park_deg": _deg(_PARK_RADIUS_M), "park_radius": _PARK_RADIUS_M,
                "hazard_categories": _HAZARD_CATEGORIES,
                "main_road_classes": _MAIN_ROAD_CLASSES,
                "road_deg": _deg(_BUILDING_ROAD_RADIUS_M),
                "road_radius": _BUILDING_ROAD_RADIUS_M,
                "district_deg": _deg(_DISTRICT_DATA_RADIUS_M),
            }).all()

        # 중앙/외곽은 단지 무게중심까지의 거리를 **중앙값으로 반 가른** 상대 분류다.
        # 절대 기준(예: 100m 이내=중앙)은 단지 크기에 따라 무의미해진다.
        # 어디까지나 추정이며, 도메인이 동별 신뢰도를 ≤0.6 으로 묶는 근거이기도 하다.
        centers = sorted(r.center_distance_m for r in rows if r.center_distance_m is not None)
        median = centers[len(centers) // 2] if centers else None

        out: list[BuildingLocationFact] = []
        for row in rows:
            position = None
            if median is not None and row.center_distance_m is not None:
                position = "중앙" if row.center_distance_m <= median else "외곽"
            out.append(BuildingLocationFact(
                building_id=row.id,
                label=row.name,
                station_distance_m=_as_float(row.station_distance_m),
                school_distance_m=_as_float(row.school_distance_m),
                school_in_district=row.school_in_district,
                main_road_distance_m=_as_float(row.main_road_distance_m),
                park_distance_m=_as_float(row.park_distance_m),
                position_in_complex=position,
                orientation_deg=_as_float(row.direction_deg),
            ))
        return out
