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

#: 후보 정렬용 실거래 창(일). 적정가 밴드의 마지막 사다리(36개월)와 맞춘다 —
#: 그보다 오래된 거래는 밴드가 쓰지 않으므로 "가격 근거 있음"으로 세면 안 된다.
_CANDIDATE_TRADE_WINDOW_DAYS = 36 * 30

#: 단지 하나당 가져올 실거래 최대 건수. 시세 통계는 최근 36개월까지만 보므로
#: (valuation/models.py PERIOD_LADDER) 전 이력을 끌어올 이유가 없다.
#: 대단지 10년치가 수천 행이라 상한이 없으면 후보 50개 × 수천 행이 메모리로 올라온다.
_TRADE_HISTORY_LIMIT = 2000

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


def _item_to_dict(row: Any) -> dict[str, Any]:
    """recommendation_item 행 → API 가 돌려줄 항목.

    `payload`(원본 JSON)가 있으면 그대로 쓴다. 정규화 컬럼은 조회·감사용이지
    리포트 본문을 담지 못한다(headline·why·why_not·next_actions·risks 가 없다).
    payload 가 비어 있는 옛 행에서는 컬럼으로 최소한만 복원한다.
    """
    payload = getattr(row, "payload", None)
    if payload:
        # DB 가 부여한 식별자와 순위는 payload 보다 DB 쪽이 정본이다.
        return {**payload, "id": row.id, "rank": row.rank}
    return {
        "id": row.id,
        "complex_id": row.complex_id,
        "building_id": row.building_id,
        "unit_type_id": row.unit_type_id,
        "rank": row.rank,
        "total_score": _as_float(row.total_score),
        "est_price_krw": row.est_price_krw,
        "timing_signal": row.timing_signal,
    }


def _norm_email(email: str) -> str:
    # 컬럼은 citext 라 DB 가 대소문자를 무시하지만, 반환값 표기를 인메모리 구현과
    # 똑같이 맞춰 둔다(둘 사이에서 테스트가 갈리지 않게).
    return email.strip().lower()


#: 사용자 조회 컬럼. **한 곳에만 적는다** — 조회마다 따로 적으면 언젠가 한 쿼리에서만
#: `status` 가 빠지고, 그 경로로 들어온 사용자는 기본값(pending)이 아니라 코드 기본값을
#: 갖게 된다. 승인 여부가 조회 경로에 따라 달라지는 건 인가 결함이다.
_USER_COLUMNS = """
    id, email::text AS email, password_hash, status, is_admin,
    created_at, status_changed_at, status_changed_by, status_reason
"""


def _to_user(row: Any) -> UserRecord:
    return UserRecord(
        id=row.id, email=row.email, password_hash=row.password_hash,
        status=row.status, is_admin=row.is_admin, created_at=row.created_at,
        status_changed_at=row.status_changed_at,
        status_changed_by=row.status_changed_by,
        status_reason=row.status_reason,
    )


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
        """가입. **상태는 DB 기본값(pending)** 이다 — 여기서 status 를 넘기지 않는다.

        승인 상태를 INSERT 파라미터로 받게 만들면 언젠가 호출부 하나가 'approved' 를
        넘기고, 승인제는 그 경로로 조용히 무력화된다(migrations/009).
        """
        sql = text(f"""
            INSERT INTO app_user (email, password_hash)
            VALUES (:email, :password_hash)
            RETURNING {_USER_COLUMNS}
        """)
        try:
            with self._engine.begin() as conn:
                row = conn.execute(
                    sql, {"email": _norm_email(email), "password_hash": password_hash}
                ).one()
                # 가입도 이력에 남긴다 — "언제 신청했고 언제 승인됐나"가 한 표에 보인다.
                conn.execute(text("""
                    INSERT INTO user_status_event (user_id, event, actor)
                    VALUES (:uid, 'registered', 'self')
                """), {"uid": row.id})
        except IntegrityError as exc:
            if _is_unique_violation(exc):
                # 라우터가 409 로 바꾼다. 인메모리 구현과 같은 예외를 던져야
                # 리포지토리를 갈아끼워도 API 동작이 바뀌지 않는다.
                raise ValueError("이미 등록된 이메일입니다") from exc
            raise
        return _to_user(row)

    def get_user_by_email(self, email: str) -> UserRecord | None:
        sql = text(f"SELECT {_USER_COLUMNS} FROM app_user WHERE email = :email")
        with self._engine.connect() as conn:
            row = conn.execute(sql, {"email": _norm_email(email)}).one_or_none()
        return None if row is None else _to_user(row)

    def get_user(self, user_id: int) -> UserRecord | None:
        sql = text(f"SELECT {_USER_COLUMNS} FROM app_user WHERE id = :user_id")
        with self._engine.connect() as conn:
            row = conn.execute(sql, {"user_id": user_id}).one_or_none()
        return None if row is None else _to_user(row)

    # -- 사용자 승인 (관리자 · migrations/009) -----------------------------

    def list_users(self, *, status: str | None = None,
                   limit: int = 100) -> list[UserRecord]:
        """대기/승인/거부 목록. **비밀번호 해시도 그대로 담겨 오지만** 라우터가
        스키마로 걸러 낸다(schemas.AdminUserOut) — 여기서 컬럼을 줄이면 두 벌이 된다."""
        sql = text(f"""
            SELECT {_USER_COLUMNS}
            FROM app_user
            WHERE (CAST(:status AS text) IS NULL OR status = CAST(:status AS text))
            ORDER BY created_at, id
            LIMIT CAST(:limit AS int)
        """)
        with self._engine.connect() as conn:
            rows = conn.execute(sql, {"status": status, "limit": limit}).all()
        return [_to_user(r) for r in rows]

    def count_active_admins(self) -> int:
        sql = text("SELECT count(*) FROM app_user WHERE is_admin AND status = :approved")
        with self._engine.connect() as conn:
            return int(conn.execute(sql, {"approved": STATUS_APPROVED}).scalar_one())

    def _lock_and_load(self, conn, user_id: int):
        """대상 행을 잠그고 읽는다. 승인된 관리자 집합도 **id 순으로 함께 잠근다.**

        왜 집합까지 잠그나: 관리자 A·B 를 동시에 강등하면 두 트랜잭션이 각자
        "나 말고 1명 남아 있다"를 보고 둘 다 통과해 **관리자 0명**이 된다.
        같은 순서로 같은 집합을 잠그면 두 트랜잭션이 직렬화되어 나중 것이 거절된다.
        """
        conn.execute(text("""
            SELECT id FROM app_user
            WHERE is_admin AND status = :approved
            ORDER BY id
            FOR UPDATE
        """), {"approved": STATUS_APPROVED})
        return conn.execute(
            text(f"SELECT {_USER_COLUMNS} FROM app_user WHERE id = :uid FOR UPDATE"),
            {"uid": user_id},
        ).one_or_none()

    @staticmethod
    def _guard_last_admin(conn, row: Any, *, still_admin: bool) -> None:
        was_admin = bool(row.is_admin) and row.status == STATUS_APPROVED
        if not was_admin or still_admin:
            return
        remaining = int(conn.execute(text("""
            SELECT count(*) FROM app_user
            WHERE is_admin AND status = :approved AND id <> :uid
        """), {"approved": STATUS_APPROVED, "uid": row.id}).scalar_one())
        if remaining == 0:
            raise LastAdminError(
                "마지막 관리자입니다. 다른 관리자를 먼저 지정한 뒤에 바꾸세요")

    def set_user_status(self, user_id: int, status: str, *, actor: str,
                        actor_user_id: int | None = None,
                        reason: str | None = None) -> UserRecord | None:
        """상태 변경 + 감사 기록을 **한 트랜잭션**으로 한다.

        둘을 나누면 "승인은 됐는데 누가 했는지 없는" 행이 생긴다 —
        승인제에서 그건 기록이 없는 것과 같다.
        """
        with self._engine.begin() as conn:
            row = self._lock_and_load(conn, user_id)
            if row is None:
                return None
            # 거부·대기로 내리면 관리자 자격도 함께 잃는다(승인된 관리자만 관리자다).
            self._guard_last_admin(conn, row, still_admin=(status == STATUS_APPROVED))
            updated = conn.execute(text(f"""
                UPDATE app_user
                   SET status = :status,
                       status_changed_at = now(),
                       status_changed_by = :actor_uid,
                       status_reason = :reason
                 WHERE id = :uid
                RETURNING {_USER_COLUMNS}
            """), {"status": status, "actor_uid": actor_user_id,
                   "reason": reason, "uid": user_id}).one()
            conn.execute(text("""
                INSERT INTO user_status_event
                    (user_id, event, reason, actor, actor_user_id)
                VALUES (:uid, :event, :reason, :actor, :actor_uid)
            """), {"uid": user_id, "event": status, "reason": reason,
                   "actor": actor, "actor_uid": actor_user_id})
        return _to_user(updated)

    def set_user_admin(self, user_id: int, is_admin: bool, *, actor: str,
                       actor_user_id: int | None = None) -> UserRecord | None:
        with self._engine.begin() as conn:
            row = self._lock_and_load(conn, user_id)
            if row is None:
                return None
            self._guard_last_admin(conn, row, still_admin=is_admin)
            updated = conn.execute(text(f"""
                UPDATE app_user SET is_admin = :is_admin
                 WHERE id = :uid
                RETURNING {_USER_COLUMNS}
            """), {"is_admin": is_admin, "uid": user_id}).one()
            conn.execute(text("""
                INSERT INTO user_status_event (user_id, event, actor, actor_user_id)
                VALUES (:uid, :event, :actor, :actor_uid)
            """), {"uid": user_id,
                   "event": "admin_granted" if is_admin else "admin_revoked",
                   "actor": actor, "actor_uid": actor_user_id})
        return _to_user(updated)

    def status_events(self, user_id: int) -> list[dict[str, Any]]:
        """감사 이력. 운영 확인용(CLI `--history`)."""
        sql = text("""
            SELECT event, reason, actor, actor_user_id, created_at
            FROM user_status_event WHERE user_id = :uid
            ORDER BY created_at, id
        """)
        with self._engine.connect() as conn:
            rows = conn.execute(sql, {"uid": user_id}).all()
        return [{"event": r.event, "reason": r.reason, "actor": r.actor,
                 "actor_user_id": r.actor_user_id, "created_at": r.created_at}
                for r in rows]

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
            SELECT id, user_id, criteria_snapshot, status, result_meta
            FROM recommendation_job
            WHERE id = :job_id AND user_id = :user_id
        """)
        # rank 는 SQL 함수명과 겹치므로 전부 테이블 별칭을 붙여 둔다.
        items_sql = text("""
            SELECT ri.id, ri.complex_id, ri.building_id, ri.unit_type_id, ri.rank,
                   ri.total_score, ri.est_price_krw, ri.timing_signal, ri.payload
            FROM recommendation_item ri
            WHERE ri.job_id = :job_id
            ORDER BY ri.rank NULLS LAST, ri.id
        """)
        with self._engine.connect() as conn:
            job = conn.execute(job_sql, {"job_id": job_id, "user_id": user_id}).one_or_none()
            if job is None:
                return None
            items = conn.execute(items_sql, {"job_id": job_id}).all()

        meta = job.result_meta or {}
        return JobRecord(
            id=job.id,
            user_id=job.user_id,
            criteria_snapshot=job.criteria_snapshot or {},
            status=job.status,
            # payload 가 있으면 **그대로** 돌려준다 — 인메모리 구현과 완전히 같은
            # 응답이 되도록. 정규화 컬럼만으로 되살리면 headline·why·why_not·
            # next_actions·risks 가 전부 사라져 리포트가 빈 껍데기가 된다.
            items=[_item_to_dict(it) for it in items],
            # 제외 사유·notes 는 **항목이 아니라 실행의 결과**라 job 행에 붙어 있다(010).
            # 010 이전 행은 NULL → 빈 목록. 그 실행에는 실제로 없었던 것이므로 지어내지 않는다.
            excluded=list(meta.get("excluded") or []),
            notes=list(meta.get("notes") or []),
        )

    # -- 지역코드 해석 (re-data 수집 로더용) -------------------------------
    #
    # 수집기가 받는 건 주소 문자열이고, `complex.region_code` 에 넣어야 하는 건
    # 10자리 법정동코드다. 그 사이를 잇는다.
    #
    # ⚠️ 못 찾으면 **None 을 돌려준다.** 비슷한 이름으로 넘겨짚지 않는다 —
    #    지역코드가 틀리면 그 단지가 엉뚱한 지역 통계에 섞이고, 사용자는
    #    "강남 단지"라며 다른 구 물건을 보게 된다.

    def _region_index(self) -> dict[tuple[str, str], str]:
        """(시군구, 동) → 법정동코드. 첫 호출 때 한 번 만들고 재사용한다.

        같은 동 이름이 여러 구에 있으므로(예: 신사동) **시군구 없이는 찾지 않는다.**
        """
        cached = getattr(self, "_region_idx_cache", None)
        if cached is not None:
            return cached

        sql = text("""
            SELECT code, sido, sigungu, dong
            FROM region
            WHERE dong IS NOT NULL AND sigungu IS NOT NULL
            ORDER BY code
        """)
        index: dict[tuple[str, str], str] = {}
        with self._engine.connect() as conn:
            for row in conn.execute(sql):
                code = (row.code or "").rstrip()
                sigungu = (row.sigungu or "").strip()
                dong = (row.dong or "").strip()
                if not code or not sigungu or not dong:
                    continue
                # '수원시 장안구' 처럼 두 토막인 경우 마지막 토막으로도 찾을 수 있게 한다.
                for key in {(sigungu, dong), (sigungu.split()[-1], dong)}:
                    index.setdefault(key, code)

        self._region_idx_cache = index
        logger.info("region 인덱스 %d건 로드", len(index))
        return index

    def resolve_region_code(self, address: str) -> str | None:
        """지번 주소 → 10자리 법정동코드. 못 찾으면 None.

        `"서울특별시 강남구 대치동 316"` · `"경기도 성남시 분당구 정자동 178"` 처럼
        시군구와 동이 함께 있는 주소를 가정한다(공공 API 의 지번주소 형식).
        """
        if not address:
            return None
        index = self._region_index()
        # 토큰을 앞에서부터 훑으며 (시군구, 동) 조합을 찾는다. 도로명주소나
        # 동이 없는 주소는 매칭되지 않고 None 이 된다 — 그게 맞다.
        tokens = [t for t in address.replace(",", " ").split() if t]
        for i, sigungu in enumerate(tokens):
            for dong in tokens[i + 1:i + 4]:      # 시군구 뒤 3토막 안에 동이 있다
                code = index.get((sigungu, dong))
                if code:
                    return code
                # '성남시 분당구' 처럼 시군구가 두 토막인 경우
                if i + 1 < len(tokens):
                    code = index.get((f"{sigungu} {tokens[i + 1]}", dong))
                    if code:
                        return code
        return None

    def resolve_region_codes(self, addresses: list[str]) -> dict[str, str | None]:
        """배치 해석. 인덱스를 한 번만 만들어 쓴다(주소 수만큼 쿼리하지 않는다)."""
        self._region_index()
        return {addr: self.resolve_region_code(addr) for addr in addresses}

    # -- 추천 러너용 조회 (docs/domain/recommendation-execution.md §repo인터페이스) --
    #
    # re-domain 러너는 이 메서드들을 **duck-typing 으로** 부른다. 없으면 경고 후
    # 빈 결과로 degrade 하므로, 시그니처가 어긋나도 크래시 대신 **조용히 추천이 비어** 버린다.
    # 그래서 인메모리 구현과 인자 이름까지 똑같이 맞춘다(테스트가 둘을 교차 검증한다).

    #: region_codes 는 **5자리 시군구 코드**로 온다(config/regions_capital.yaml).
    #: 반면 complex.region_code 는 10자리 법정동코드다 → **접두 매칭**이 필요하다.
    #: 이걸 완전일치로 짜면 후보가 항상 0건이 되고, 러너는 빈 결과를 정상으로 취급한다.
    #:
    #: ⚠️ 호가(listing)로 **조인해 거르지 않는다.** 공공 오픈API 에는 호가가 없어
    #:    수집이 막히면 이 테이블이 통째로 비고, INNER JOIN 이면 후보가 구조적으로 0건이 된다
    #:    (CHARTER G4: 공공API 만으로도 서비스가 성립해야 한다). 매물 수는 **정렬 신호일 뿐**이다.
    #:
    #: ⚠️ 지역 접두 매칭에 `LIKE rc || '%'` 를 쓰지 않는다 (SR21-4).
    #:    `%` 나 `_` 가 섞인 코드가 들어오면 `LIKE` 는 **에러 없이 전 지역을 매칭**해서
    #:    지역 선택이 조용히 무력화된다("강남만" 이 "전국"이 된다). 인젝션은 아니지만
    #:    실패가 실패로 보이지 않는, 이 프로젝트가 가장 경계하는 종류의 사고다.
    #:    `left(region_code, length(rc)) = rc` 는 와일드카드 개념 자체가 없어 구조적으로 막힌다
    #:    (접두 매칭 의미는 동일하고, 이 조건은 원래 인덱스를 타지 않아 비용도 같다).
    #:    API 계층의 형식 검증(422)은 그 앞의 1차 방어다 — 여기가 마지막 문이다.
    _CANDIDATES_SQL_TEMPLATE = """
        SELECT c.id,
               c.name,
               ST_X(c.geom) AS lon,
               ST_Y(c.geom) AS lat,
               c.region_code,
               c.built_year,
               c.total_households,
               t.price_krw     AS recent_price_krw,
               t.contract_date AS price_as_of,
               COALESCE(l.active_listings, 0) AS active_listings
        FROM complex c
        LEFT JOIN LATERAL (
            SELECT tr.price_krw, tr.contract_date
            FROM trade tr
            WHERE tr.complex_id = c.id AND NOT tr.is_cancelled
            ORDER BY tr.contract_date DESC
            LIMIT 1
        ) t ON true
        LEFT JOIN LATERAL (
            SELECT count(*) AS active_listings
            FROM listing li
            WHERE li.complex_id = c.id
              AND li.status = 'active'
              AND li.duplicate_of IS NULL
        ) l ON true
        LEFT JOIN LATERAL (
            -- 가격 근거가 될 최근 실거래. idx_trade_complex_date 를 탄다.
            -- affordable_trades 는 **예산으로 실제 체결된 적이 있는** 거래 수다.
            -- 단지 중위가로 예산을 재면 안 된다 — 대단지는 중위가 25억이어도 소형은
            -- 10억이라 "살 수 있는 물건이 있는 단지"를 통째로 놓친다.
            SELECT count(*) AS recent_trades,
                   count(*) FILTER (
                       WHERE CAST(:max_price_krw AS bigint) IS NULL
                          OR tr2.price_krw <= CAST(:max_price_krw AS bigint)
                   ) AS affordable_trades
            FROM trade tr2
            WHERE tr2.complex_id = c.id
              AND NOT tr2.is_cancelled
              AND tr2.contract_date >= current_date - CAST(:trade_window_days AS int)
        ) tc ON true
        WHERE {bbox_clause}(
                cardinality(CAST(:region_codes AS text[])) = 0
                OR EXISTS (
                    SELECT 1 FROM unnest(CAST(:region_codes AS text[])) AS rc
                    WHERE left(c.region_code, length(rc)) = rc
                )
              )
        -- ① 활성 매물이 있는 단지를 먼저 본다(지금 살 수 있는 물건이 있는 쪽).
        -- ② **예산으로 체결된 거래가 있는 단지**를 먼저 본다.
        --    ⚠️ 거르는 게 아니라 **정렬**이다. 예산 초과 단지도 LIMIT 안에 남고
        --       파이프라인이 사유와 함께 떨어뜨린다(ux/README.md §4).
        --       이 줄이 없으면 LIMIT 50 이 거래 많은 = 비싼 대단지로 다 차서,
        --       예산이 작은 사용자에게는 후보가 전멸한다(실측: 송파 136 후보 중 117 예산초과).
        -- ③ 그다음 실거래 표본이 많은 단지 — 적정가 밴드를 만들 수 있어야 후보로 선다.
        --    이게 없으면 LIMIT 이 id 순으로 잘려 거래 0건 단지 50개를 뽑고 후보가 0건이 된다.
        ORDER BY COALESCE(l.active_listings, 0) DESC,
                 COALESCE(tc.affordable_trades, 0) DESC,
                 COALESCE(tc.recent_trades, 0) DESC,
                 c.id
        LIMIT CAST(:limit AS int)
    """

    #: "이 주변에서 검색" — 지도 범위 안의 단지로 후보를 좁힌다 (REC-5).
    #:
    #: ⚠️ **WHERE 의 맨 앞**에 온다. `&&` 가 GiST(idx_complex_geom)를 타야 하고,
    #:    `ST_Intersects`·`ST_Within` 을 앞에 두면 전건 스캔이 된다(erd.md §3.1).
    #: ⚠️ geom 이 NULL 인 단지는 `&&` 가 NULL 을 내며 **조용히 빠진다.** 그게 맞는 동작이지만
    #:    (좌표를 모르면 "이 주변"인지 판정할 수 없다) 사용자에게는 반드시 고지해야 한다
    #:    — 러너가 `geocode_coverage` 로 숫자를 세어 notes 에 싣는다.
    _BBOX_CLAUSE = """c.geom && ST_MakeEnvelope(
                  CAST(:min_lon AS double precision),
                  CAST(:min_lat AS double precision),
                  CAST(:max_lon AS double precision),
                  CAST(:max_lat AS double precision), 4326)
          AND """

    # SQL 문자열은 **코드 안의 리터럴 두 개로만** 조립한다 — 사용자 입력은 전부
    # 바인딩 파라미터(:min_lon …)로 들어간다. 조건마다 문자열을 이어 붙이지 않고
    # 변형을 미리 컴파일해 두는 이유는, `(:has_bbox IS FALSE OR geom && …)` 같은
    # 형태로 쓰면 플래너가 bbox 를 상수로 못 보고 **GiST 인덱스를 포기**하기 때문이다.
    _CANDIDATES_SQL = text(_CANDIDATES_SQL_TEMPLATE.format(bbox_clause=""))
    _CANDIDATES_BBOX_SQL = text(
        _CANDIDATES_SQL_TEMPLATE.format(bbox_clause=_BBOX_CLAUSE))

    def recommendation_candidates(
        self, *, region_codes: list[str], max_price_krw: int | None = None,
        limit: int = 50, bbox: BBox | None = None,
    ) -> list[ComplexSummary]:
        """조건에 맞는 후보 단지.

        `max_price_krw` 로 **걸러내지 않는다.** 예산 초과 단지도 그대로 넘기고
        파이프라인이 "왜 제외됐는지" 사유와 함께 떨어뜨린다(ux/README.md §4).
        여기서 조용히 지우면 사용자는 그 단지를 아예 못 본다.
        다만 **정렬에는 쓴다** — LIMIT 안에서 자리를 다툴 때 예산으로 살 수 있었던
        단지에 우선권을 준다. 안 그러면 거래 많은 = 비싼 대단지가 LIMIT 을 다 채우고
        예산이 작은 사용자에게는 후보가 전멸한다(거르는 것과 순서를 주는 것은 다르다).

        호가 유무로도 걸러내지 않는다 — 호가가 없으면 실거래 기준으로 후보가 된다(G4).

        `bbox` 가 오면 그 범위로 좁힌다. `region_codes` 와 **둘 다 오면 교집합**이다 —
        지역을 고르고 "이 주변"까지 눌렀다면 둘 다 만족하는 단지를 원한 것이다.
        """
        params: dict[str, Any] = {
            "region_codes": list(region_codes or []),
            "trade_window_days": _CANDIDATE_TRADE_WINDOW_DAYS,
            "max_price_krw": max_price_krw,
            "limit": limit,
        }
        sql = self._CANDIDATES_SQL
        if bbox is not None:
            sql = self._CANDIDATES_BBOX_SQL
            params |= {"min_lon": bbox.min_lon, "min_lat": bbox.min_lat,
                       "max_lon": bbox.max_lon, "max_lat": bbox.max_lat}

        with self._engine.connect() as conn:
            rows = conn.execute(sql, params).all()

        return [
            ComplexSummary(
                id=row.id, name=row.name, lon=row.lon, lat=row.lat,
                region_code=(row.region_code or "").rstrip(),
                built_year=row.built_year,
                total_households=row.total_households,
                recent_price_krw=row.recent_price_krw,
                price_as_of=row.price_as_of.isoformat() if row.price_as_of else None,
                active_listings=row.active_listings,
            )
            for row in rows
        ]

    #: 좌표 확보 현황. bbox 검색에서 **몇 개가 구조적으로 빠지는지**를 세는 데 쓴다.
    #: 고정 문구("약 5%")로 적으면 수집이 진행돼도 영영 낡은 값이 남는다 — 그래서 센다.
    _GEOCODE_COVERAGE_SQL = text("""
        SELECT count(c.geom) AS with_geom, count(*) AS total
        FROM complex c
        WHERE cardinality(CAST(:region_codes AS text[])) = 0
           OR EXISTS (
                SELECT 1 FROM unnest(CAST(:region_codes AS text[])) AS rc
                WHERE left(c.region_code, length(rc)) = rc
              )
    """)

    def geocode_coverage(
        self, *, region_codes: list[str] | None = None) -> tuple[int, int]:
        """(좌표 있는 단지 수, 전체 단지 수). 지역을 주면 그 범위만 센다."""
        with self._engine.connect() as conn:
            row = conn.execute(self._GEOCODE_COVERAGE_SQL, {
                "region_codes": list(region_codes or []),
            }).one()
        return int(row.with_geom or 0), int(row.total or 0)

    _LISTINGS_SQL = text("""
        SELECT li.id, li.ask_price_krw, li.area_m2, li.floor,
               li.listed_at, li.collected_at, li.building_id, li.agency, li.status
        FROM listing li
        WHERE li.complex_id = :complex_id AND li.status = 'active'
        ORDER BY li.ask_price_krw, li.id
    """)

    def listings_for_complex(self, complex_id: int) -> list[ListingRow]:
        """활성 호가. **중복을 여기서 지우지 않는다** — 러너가 group_duplicates 로
        묶어 대표건을 고른다. 미리 지우면 어떤 근거로 묶였는지 설명할 수 없다."""
        with self._engine.connect() as conn:
            rows = conn.execute(self._LISTINGS_SQL, {"complex_id": complex_id}).all()
        return [
            ListingRow(
                id=row.id,
                ask_price_krw=row.ask_price_krw,
                area_m2=float(row.area_m2) if row.area_m2 is not None else 0.0,
                floor=row.floor,
                listed_at=row.listed_at,
                # collected_at 은 timestamptz — 모델은 date 를 기대한다
                collected_at=row.collected_at.date() if row.collected_at else None,
                building_id=row.building_id,
                agency=row.agency,
                status=row.status,
            )
            for row in rows
        ]

    _TRADES_SQL = text("""
        SELECT tr.contract_date, tr.price_krw, tr.area_m2, tr.floor,
               tr.apt_dong, tr.is_cancelled
        FROM trade tr
        WHERE tr.complex_id = :complex_id
        ORDER BY tr.contract_date DESC
        LIMIT CAST(:limit AS int)
    """)

    def trades_for_complex(self, complex_id: int) -> list[TradeRow]:
        """실거래. **해제건도 그대로 넘긴다** — 통계 계층이 제외 여부를 정한다.
        여기서 걸러 버리면 '해제가 몇 건이었나'를 근거로 쓸 수 없다."""
        with self._engine.connect() as conn:
            rows = conn.execute(self._TRADES_SQL, {
                "complex_id": complex_id, "limit": _TRADE_HISTORY_LIMIT,
            }).all()
        return [
            TradeRow(
                contract_date=row.contract_date,
                price_krw=row.price_krw,
                area_m2=float(row.area_m2) if row.area_m2 is not None else 0.0,
                floor=row.floor,
                apt_dong=row.apt_dong,      # F4 동별 실측(운영 API aptDong)
                is_cancelled=row.is_cancelled,
            )
            for row in rows
        ]

    # -- 추천 결과 저장 ----------------------------------------------------

    def save_job_result(self, job_id: str, user_id: int, *, status: str,
                        items: list[dict[str, Any]],
                        excluded: list[dict[str, Any]] | None = None,
                        notes: list[str] | None = None) -> None:
        """분석 결과를 되쓴다.

        ⚠️ 소유권을 **여기서 다시 확인한다**(IDOR). 작업을 만든 사람과 결과를 쓰는
        사람이 같은지 UPDATE 의 WHERE 로 강제하고, 안 맞으면 조용히 아무것도 하지 않는다.

        저장 구조 (recommendation-execution.md §저장매핑)
          items[i]              → recommendation_item 1행
          items[i]["findings"]  → agent_finding N행
          items[i] 원본 JSON     → recommendation_item.payload (아래 주석 참조)
          excluded · notes      → recommendation_job.result_meta (010)

        제외 사유는 **항목이 아니다.** `recommendation_item` 에 rank NULL 로 끼워 넣으면
        조회 쿼리에 딸려 나와 제외된 단지가 추천으로 둔갑할 수 있어, job 행에 붙인다.
        """
        meta = {"excluded": list(excluded or []), "notes": list(notes or [])}
        with self._engine.begin() as conn:
            owned = conn.execute(text("""
                UPDATE recommendation_job
                   SET status = :status,
                       completed_at = CASE WHEN :status IN ('done','failed')
                                           THEN now() ELSE completed_at END,
                       result_meta = CAST(:meta AS jsonb)
                 WHERE id = :job_id AND user_id = :user_id
                RETURNING id
            """), {"job_id": job_id, "user_id": user_id, "status": status,
                   # 재실행이면 이전 실행의 제외 사유를 남기지 않는다 —
                   # items 를 통째로 갈아끼우는 것과 같은 트랜잭션·같은 규칙이다.
                   "meta": json.dumps(meta, ensure_ascii=False, default=str),
                   }).one_or_none()

            if owned is None:
                # 남의 작업이거나 없는 작업. 결과를 쓰지 않는다.
                logger.warning("save_job_result: 소유권 불일치 또는 없는 작업 (job=%s)", job_id)
                return

            # 재실행 시 결과가 겹치지 않게 먼저 비운다.
            # agent_finding 은 ON DELETE CASCADE 로 함께 지워진다.
            conn.execute(text("DELETE FROM recommendation_item WHERE job_id = :job_id"),
                         {"job_id": job_id})

            for item in items:
                self._insert_item(conn, job_id, item)

    def _insert_item(self, conn, job_id: str, item: dict[str, Any]) -> None:
        complex_id = (item.get("complex") or {}).get("id")
        if complex_id is None:
            logger.warning("추천 항목에 complex.id 가 없어 건너뜁니다 (job=%s)", job_id)
            return

        building = item.get("building") or {}
        area_m2 = (item.get("unit_type") or {}).get("area_m2")

        row = conn.execute(text("""
            INSERT INTO recommendation_item
                (job_id, complex_id, building_id, unit_type_id, rank,
                 total_score, est_price_krw, timing_signal, payload)
            VALUES (:job_id, :complex_id, :building_id,
                    -- 면적으로 unit_type 을 찾되, 없으면 NULL (스키마가 허용한다).
                    -- 없는 타입을 만들어 넣지 않는다 — 수집이 채울 자리다.
                    -- ⚠️ 두 자리 모두 CAST 가 필요하다. `:area_m2 IS NOT NULL` 은 타입 문맥이
                    --    없어서 area_m2 가 NULL 로 오면 PostgreSQL 이 파라미터 타입을 못 정하고
                    --    AmbiguousParameter 로 **저장 자체가 실패**한다(실DB 검증에서 발견).
                    --    인메모리 리포지토리로는 재현되지 않는 경로다.
                    (SELECT ut.id FROM unit_type ut
                      WHERE ut.complex_id = :complex_id
                        AND CAST(:area_m2 AS numeric) IS NOT NULL
                        AND ut.area_m2 = CAST(:area_m2 AS numeric)
                      ORDER BY ut.id LIMIT 1),
                    :rank, :total_score, :est_price_krw, :timing_signal,
                    CAST(:payload AS jsonb))
            RETURNING id
        """), {
            "job_id": job_id,
            "complex_id": complex_id,
            "building_id": building.get("id"),
            "area_m2": area_m2,
            "rank": item.get("rank"),
            "total_score": item.get("total_score"),
            # 판단에 실제로 쓴 기준가. 호가 기준이면 호가와 같고, 실거래 기준이면
            # 실거래 중위(추정)다. **어느 쪽인지는 payload 의 price_basis 가 정본** —
            # 이 컬럼만 보고 호가로 읽으면 안 된다(그래서 payload 를 함께 저장한다).
            "est_price_krw": item.get("est_price_krw", item.get("ask_price_krw")),
            "timing_signal": item.get("timing_signal"),
            "payload": json.dumps(item, ensure_ascii=False, default=str),
        }).one()

        for finding in item.get("findings") or []:
            self._insert_finding(conn, row.id, finding)

    def _insert_finding(self, conn, item_id: int, finding: dict[str, Any]) -> None:
        evidence = finding.get("evidence") or []
        if not evidence:
            # 스키마가 `CHECK (jsonb_array_length(evidence) > 0)` 로 막는다.
            # 근거 없는 판단은 저장하지 않는다는 설계다(G2) — '판단 보류' finding 이
            # 여기 해당한다. 넣으려 하면 트랜잭션 전체가 깨지므로 건너뛴다.
            # ⚠️ 그 대신 사유가 DB 에서 사라지므로 payload JSON 에는 남겨 둔다.
            logger.debug("근거 없는 finding 은 저장하지 않습니다 (agent=%s)",
                         finding.get("agent_id"))
            return

        conn.execute(text("""
            INSERT INTO agent_finding
                (item_id, agent_id, score, verdict, rationale, evidence, confidence)
            VALUES (:item_id, :agent_id, :score, :verdict, :rationale,
                    CAST(:evidence AS jsonb), :confidence)
        """), {
            "item_id": item_id,
            "agent_id": finding.get("agent_id") or "unknown",
            "score": finding.get("score"),
            "verdict": finding.get("verdict"),
            "rationale": finding.get("rationale"),
            "evidence": json.dumps(evidence, ensure_ascii=False, default=str),
            "confidence": finding.get("confidence"),
        })

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
