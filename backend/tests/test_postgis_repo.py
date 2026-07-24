"""PostGIS 리포지토리 + `migrations/*.sql` **실검증** 테스트.

이 파일은 실제 PostgreSQL+PostGIS 가 있어야만 의미가 있다.
`TEST_DATABASE_URL` 이 없으면 통째로 skip 한다 — 조용히 통과시키지 않고
"검증 안 됨"이 실행 결과에 보이게 두는 게 요점이다.

실행
----
    # DB 준비 (예: docker)
    docker run -d --name pg-test -e POSTGRES_PASSWORD=pw -e POSTGRES_DB=realestate_test \
        -p 55432:5432 postgis/postgis:16-3.4

    set TEST_DATABASE_URL=postgresql+psycopg://postgres:pw@localhost:55432/realestate_test
    python -m pytest -m needs_db -v

⚠️ 이 테스트는 대상 DB 의 `public` 스키마를 **삭제하고 다시 만든다.**
   실수로 운영 DB 를 지우지 않도록 DB 이름에 `test` 가 없으면 거부한다.
"""
from __future__ import annotations

import os
from pathlib import Path

import pytest
from sqlalchemy import text
from sqlalchemy.exc import DBAPIError, IntegrityError

from app.repositories.base import ProfileRecord
from app.repositories.postgis import PostgisRepository

pytestmark = pytest.mark.needs_db

BACKEND_DIR = Path(__file__).resolve().parents[1]
#: 파일명 순서 = 적용 순서 (001 → 002 → ...)
MIGRATIONS = sorted((BACKEND_DIR / "migrations").glob("[0-9]*.sql"))
FIXTURES = Path(__file__).parent / "fixtures"

DB_URL = os.getenv("TEST_DATABASE_URL", "")

#: 도메인 데이터 테이블 — 테스트마다 비운다. app_user 는 CASCADE 로 함께 지워진다.
_TRUNCATE = """
TRUNCATE complex, trade, listing, unit_type, building, region,
         app_user, recommendation_job, recommendation_item, agent_finding,
         user_profile, user_preference,
         poi, school_district, transit_plan
RESTART IDENTITY CASCADE
"""


@pytest.fixture(scope="session")
def engine():
    if not DB_URL:
        pytest.skip("TEST_DATABASE_URL 미설정 — 실 DB 검증을 건너뜁니다(미검증 상태)")

    from sqlalchemy import create_engine

    if "test" not in DB_URL.rsplit("/", 1)[-1].lower():
        pytest.fail("안전장치: TEST_DATABASE_URL 의 DB 이름에 'test' 가 들어가야 합니다 "
                    "(이 테스트는 public 스키마를 삭제합니다)")

    eng = create_engine(DB_URL, pool_pre_ping=True)
    # --- 여기가 마이그레이션 실검증이다 ---
    # 빈 스키마에 migrations/*.sql 을 파일명 순서대로 적용한다(운영에서
    # docker-entrypoint-initdb.d 가 하는 것과 같은 순서). 실패하면 이 fixture 가
    # 터지고 아래 테스트가 전부 error 로 보고된다 — 조용히 통과하지 않는다.
    with eng.connect().execution_options(isolation_level="AUTOCOMMIT") as conn:
        conn.exec_driver_sql("DROP SCHEMA IF EXISTS public CASCADE")
        conn.exec_driver_sql("CREATE SCHEMA public")
        for path in MIGRATIONS:
            # 파일 안에 BEGIN/COMMIT 이 있으므로 드라이버에 그대로 넘긴다.
            conn.exec_driver_sql(path.read_text(encoding="utf-8"))
    yield eng
    eng.dispose()


@pytest.fixture()
def repo(engine):
    with engine.begin() as conn:
        conn.execute(text(_TRUNCATE))
    return PostgisRepository(engine)


def _seed_complex(engine, *, name: str, lon: float, lat: float,
                  region: str = "1168010100", built_year: int = 2005) -> int:
    with engine.begin() as conn:
        conn.execute(text("""
            INSERT INTO region (code, sido, sigungu) VALUES (:code, '서울', '강남구')
            ON CONFLICT (code) DO NOTHING
        """), {"code": region})
        row = conn.execute(text("""
            INSERT INTO complex (region_code, name, geom, built_year, total_households)
            VALUES (:region, :name,
                    ST_SetSRID(ST_MakePoint(:lon, :lat), 4326), :built_year, 500)
            RETURNING id
        """), {"region": region, "name": name, "lon": lon, "lat": lat,
               "built_year": built_year}).one()
    return row.id


# ---------------------------------------------------------------------------
# 마이그레이션 (001_init.sql)
# ---------------------------------------------------------------------------

def test_마이그레이션이_빈_DB에_적용된다(engine):
    """fixture 가 이미 적용했다. 여기서는 핵심 객체가 실제로 생겼는지 본다."""
    with engine.connect() as conn:
        exts = {r.extname for r in conn.execute(text("SELECT extname FROM pg_extension"))}
        assert {"postgis", "citext"} <= exts

        tables = {r.tablename for r in conn.execute(text(
            "SELECT tablename FROM pg_tables WHERE schemaname = 'public'"))}
        for expected in ("complex", "building", "unit_type", "trade", "listing",
                         "app_user", "user_profile", "user_preference",
                         "recommendation_job", "recommendation_item", "agent_finding"):
            assert expected in tables, f"{expected} 테이블이 없습니다"


def test_공간_인덱스가_GiST로_생성된다(engine):
    with engine.connect() as conn:
        rows = conn.execute(text("""
            SELECT i.relname AS index_name, am.amname AS method
            FROM pg_index x
            JOIN pg_class i ON i.oid = x.indexrelid
            JOIN pg_am am   ON am.oid = i.relam
            JOIN pg_class t ON t.oid = x.indrelid
            WHERE t.relname IN ('complex','building','poi','region',
                                'school_district','transit_plan')
              AND am.amname = 'gist'
        """)).all()
    names = {r.index_name for r in rows}
    assert "idx_complex_geom" in names
    assert "idx_building_geom" in names
    assert "idx_poi_geom" in names


def test_trade_파티션이_붙어있고_연도별로_라우팅된다(engine):
    complex_id = _seed_complex(engine, name="파티션테스트", lon=127.0, lat=37.5)
    with engine.begin() as conn:
        parts = {r.relname for r in conn.execute(text("""
            SELECT c.relname FROM pg_inherits i
            JOIN pg_class c ON c.oid = i.inhrelid
            JOIN pg_class p ON p.oid = i.inhparent
            WHERE p.relname = 'trade'
        """))}
        assert "trade_2026" in parts and "trade_default" in parts

        for date, expected in (("2026-03-01", "trade_2026"),
                               ("2019-07-07", "trade_2019"),
                               # 파티션 범위 밖 — 조용히 사라지면 안 된다
                               ("2099-01-01", "trade_default")):
            conn.execute(text("""
                INSERT INTO trade (complex_id, contract_date, price_krw, source)
                VALUES (:cid, CAST(:d AS date), 1000000000, 'test')
            """), {"cid": complex_id, "d": date})
            landed = conn.execute(text("""
                SELECT tableoid::regclass::text AS part FROM trade
                WHERE complex_id = :cid AND contract_date = CAST(:d AS date)
            """), {"cid": complex_id, "d": date}).one().part
            assert landed == expected, f"{date} 가 {landed} 로 들어갔습니다"


def test_CHECK_제약이_실제로_막는다(engine):
    complex_id = _seed_complex(engine, name="제약테스트", lon=127.01, lat=37.51)

    with pytest.raises(IntegrityError):  # price_krw > 0
        with engine.begin() as conn:
            conn.execute(text("""
                INSERT INTO trade (complex_id, contract_date, price_krw, source)
                VALUES (:cid, DATE '2026-01-05', 0, 'test')
            """), {"cid": complex_id})

    with pytest.raises(IntegrityError):  # status IN (...)
        with engine.begin() as conn:
            conn.execute(text("""
                INSERT INTO listing (complex_id, ask_price_krw, status, source)
                VALUES (:cid, 1000000000, '팔림', 'test')
            """), {"cid": complex_id})

    with pytest.raises(IntegrityError):  # direction_deg BETWEEN 0 AND 359
        with engine.begin() as conn:
            conn.execute(text("""
                INSERT INTO building (complex_id, name, direction_deg)
                VALUES (:cid, '101동', 400)
            """), {"cid": complex_id})


def test_근거없는_agent_finding은_저장되지_않는다(engine):
    """G2: evidence 가 빈 배열이면 CHECK 가 막는다."""
    complex_id = _seed_complex(engine, name="근거테스트", lon=127.02, lat=37.52)
    with engine.begin() as conn:
        conn.execute(text("""
            INSERT INTO app_user (email, password_hash) VALUES ('g2@example.com', 'x')
        """))
        uid = conn.execute(text("SELECT id FROM app_user WHERE email='g2@example.com'")).one().id
        conn.execute(text("""
            INSERT INTO recommendation_job (id, user_id, criteria_snapshot)
            VALUES ('job_g2', :uid, '{}'::jsonb)
        """), {"uid": uid})
        item_id = conn.execute(text("""
            INSERT INTO recommendation_item (job_id, complex_id, rank)
            VALUES ('job_g2', :cid, 1) RETURNING id
        """), {"cid": complex_id}).one().id

    with pytest.raises(IntegrityError):
        with engine.begin() as conn:
            conn.execute(text("""
                INSERT INTO agent_finding (item_id, agent_id, evidence)
                VALUES (:iid, 'valuation-trader', '[]'::jsonb)
            """), {"iid": item_id})

    # ⚠️ 배열이 아닌 값을 넣으면 CHECK 위반이 아니라 함수 오류(22023)로 터진다.
    #    막히긴 하지만 오류 종류가 달라 API 에서 잡는 예외도 달라진다 — 알고 있어야 한다.
    with pytest.raises(DBAPIError):
        with engine.begin() as conn:
            conn.execute(text("""
                INSERT INTO agent_finding (item_id, agent_id, evidence)
                VALUES (:iid, 'valuation-trader', '{"a":1}'::jsonb)
            """), {"iid": item_id})


# ---------------------------------------------------------------------------
# 리포지토리 — 사용자 · 프로필
# ---------------------------------------------------------------------------

def test_사용자_생성과_조회(repo):
    user = repo.create_user("Kim@Example.com ", "argon2-hash")
    assert user.id > 0
    assert user.email == "kim@example.com"

    assert repo.get_user(user.id).email == "kim@example.com"
    # citext — 대소문자가 달라도 같은 계정으로 찾는다
    assert repo.get_user_by_email("KIM@example.com").id == user.id
    assert repo.get_user_by_email("nobody@example.com") is None
    assert repo.get_user(999999) is None


def test_이메일_중복은_ValueError로_바뀐다(repo):
    """인메모리 구현과 같은 예외여야 라우터가 409 를 낸다."""
    repo.create_user("dup@example.com", "h")
    with pytest.raises(ValueError):
        repo.create_user("DUP@example.com", "h")


def test_프로필은_암호문_그대로_왕복한다(repo):
    user = repo.create_user("profile@example.com", "h")
    blob = bytes(range(64))
    repo.upsert_profile(ProfileRecord(
        user_id=user.id, cash_krw_enc=blob, income_krw_enc=b"\x00\x01",
        existing_loan_krw_enc=None, owned_houses=1, household_size=3))

    got = repo.get_profile(user.id)
    assert got.cash_krw_enc == blob          # bytea 왕복에서 1바이트도 변하면 안 된다
    assert got.income_krw_enc == b"\x00\x01"
    assert got.existing_loan_krw_enc is None
    assert got.owned_houses == 1 and got.household_size == 3

    # 같은 사용자를 다시 저장하면 행이 늘지 않고 덮어써진다
    repo.upsert_profile(ProfileRecord(user_id=user.id, cash_krw_enc=b"new",
                                      owned_houses=2, household_size=1))
    again = repo.get_profile(user.id)
    assert again.cash_krw_enc == b"new" and again.owned_houses == 2


def test_프로필_평문_컬럼이_존재하지_않는다(engine):
    """G3: 금액 평문이 들어갈 자리를 스키마가 아예 제공하지 않는지 확인."""
    with engine.connect() as conn:
        cols = {r.column_name: r.data_type for r in conn.execute(text("""
            SELECT column_name, data_type FROM information_schema.columns
            WHERE table_name = 'user_profile'
        """))}
    for enc in ("cash_krw_enc", "income_krw_enc", "existing_loan_krw_enc"):
        assert cols[enc] == "bytea"
    for plain in ("cash_krw", "income_krw", "existing_loan_krw"):
        assert plain not in cols, f"평문 컬럼 {plain} 이 존재합니다 (G3 위반)"


def test_선호조건_저장과_기본값(repo, engine):
    user = repo.create_user("prefs@example.com", "h")
    assert repo.get_preferences(user.id) == {"prefer": {}, "avoid": {}, "weights": {}}

    prefs = {"prefer": {"school": True}, "avoid": {"고압선": True}, "weights": {"가격": 0.5}}
    repo.set_preferences(user.id, prefs)
    assert repo.get_preferences(user.id) == prefs

    # 두 번째 저장은 행을 새로 만들지 않고 갱신한다 (002 UNIQUE + ON CONFLICT)
    repo.set_preferences(user.id, {"prefer": {}, "avoid": {}, "weights": {"교통": 1}})
    assert repo.get_preferences(user.id)["weights"] == {"교통": 1}
    with engine.connect() as conn:
        count = conn.execute(text(
            "SELECT count(*) FROM user_preference WHERE user_id = :uid"),
            {"uid": user.id}).scalar_one()
    assert count == 1, "선호 조건 행이 사용자당 1개를 넘었습니다"


def test_002_user_preference_UNIQUE가_중복을_막는다(repo, engine):
    """002 마이그레이션이 실제로 걸렸는지 — 제약 없이는 이 INSERT 가 통과한다."""
    user = repo.create_user("uniq@example.com", "h")
    repo.set_preferences(user.id, {"prefer": {}, "avoid": {}, "weights": {}})
    with pytest.raises(IntegrityError):
        with engine.begin() as conn:
            conn.execute(text("""
                INSERT INTO user_preference (user_id, prefer, avoid, weights)
                VALUES (:uid, '{}'::jsonb, '{}'::jsonb, '{}'::jsonb)
            """), {"uid": user.id})


# ---------------------------------------------------------------------------
# 리포지토리 — 지도 (F1)
# ---------------------------------------------------------------------------

def test_bbox_조회가_범위_안의_단지만_돌려준다(repo, engine):
    inside = _seed_complex(engine, name="범위안", lon=127.05, lat=37.50)
    _seed_complex(engine, name="범위밖", lon=129.00, lat=35.10)

    rows = repo.complexes_in_bbox(min_lon=127.0, min_lat=37.4,
                                  max_lon=127.1, max_lat=37.6)
    assert [r.id for r in rows] == [inside]
    assert rows[0].name == "범위안"
    assert rows[0].lon == pytest.approx(127.05)
    assert rows[0].region_code == "1168010100"   # char(10) 공백 패딩 제거 확인


def test_bbox_조회가_GiST_인덱스를_탄다(repo, engine):
    """erd.md §3.1 — `&&` 가 idx_complex_geom 을 타야 한다.

    데이터가 적으면 플래너가 순차 스캔을 고르므로 seqscan 을 꺼서
    "인덱스를 쓸 수 있는 쿼리인가"만 본다.
    """
    _seed_complex(engine, name="플랜확인", lon=127.05, lat=37.50)
    params = {"min_lon": 127.0, "min_lat": 37.4, "max_lon": 127.1, "max_lat": 37.6,
              "built_after": None, "area_min": None, "area_max": None, "limit": 500}
    with engine.connect() as conn:
        conn.execute(text("SET enable_seqscan = off"))
        plan = "\n".join(
            r[0] for r in conn.execute(
                text("EXPLAIN " + PostgisRepository._BBOX_SQL.text), params))
    assert "idx_complex_geom" in plan, f"GiST 인덱스를 타지 않습니다:\n{plan}"


def test_최근_실거래와_활성매물이_함께_온다(repo, engine):
    cid = _seed_complex(engine, name="시세단지", lon=127.05, lat=37.50)
    with engine.begin() as conn:
        conn.execute(text("""
            INSERT INTO trade (complex_id, contract_date, price_krw, source) VALUES
              (:cid, DATE '2026-05-01', 1500000000, 'molit'),
              (:cid, DATE '2026-06-01', 1600000000, 'molit'),
              -- 해제된 거래는 최신이어도 시세로 쓰지 않는다
              (:cid, DATE '2026-07-01', 9900000000, 'molit')
        """), {"cid": cid})
        conn.execute(text("""
            UPDATE trade SET is_cancelled = true WHERE contract_date = DATE '2026-07-01'
        """))
        conn.execute(text("""
            INSERT INTO listing (complex_id, ask_price_krw, status, source) VALUES
              (:cid, 1700000000, 'active', 'portal'),
              (:cid, 1650000000, 'withdrawn', 'portal')
        """), {"cid": cid})
        dup_of = conn.execute(text("""
            SELECT id FROM listing WHERE complex_id = :cid AND status = 'active'
        """), {"cid": cid}).one().id
        # 중복 매물은 대표건 하나로만 센다
        conn.execute(text("""
            INSERT INTO listing (complex_id, ask_price_krw, status, source, duplicate_of)
            VALUES (:cid, 1700000000, 'active', 'portal2', :dup)
        """), {"cid": cid, "dup": dup_of})

    row = repo.complexes_in_bbox(min_lon=127.0, min_lat=37.4,
                                 max_lon=127.1, max_lat=37.6)[0]
    assert row.recent_price_krw == 1600000000
    assert row.price_as_of == "2026-06-01"    # 언제 거래된 값인지 항상 함께
    assert row.active_listings == 1


def test_예산초과_단지를_걸러내지_않는다(repo, engine):
    """ux/README.md §4 — 왜 후보에 없는지 보이게 하려면 목록에는 남아야 한다."""
    _seed_complex(engine, name="비싼단지", lon=127.05, lat=37.50)
    rows = repo.complexes_in_bbox(min_lon=127.0, min_lat=37.4,
                                  max_lon=127.1, max_lat=37.6, max_price_krw=1)
    assert len(rows) == 1


def test_준공연도와_면적_필터(repo, engine):
    old = _seed_complex(engine, name="구축", lon=127.05, lat=37.50, built_year=1990)
    new = _seed_complex(engine, name="신축", lon=127.06, lat=37.51, built_year=2020)
    with engine.begin() as conn:
        conn.execute(text("""
            INSERT INTO unit_type (complex_id, area_m2, type_name) VALUES
              (:old, 59.9, 'A'), (:new, 84.9, 'A')
        """), {"old": old, "new": new})

    box = {"min_lon": 127.0, "min_lat": 37.4, "max_lon": 127.1, "max_lat": 37.6}
    assert [r.id for r in repo.complexes_in_bbox(**box, built_after=2000)] == [new]
    assert [r.id for r in repo.complexes_in_bbox(**box, area_min_m2=80)] == [new]
    assert [r.id for r in repo.complexes_in_bbox(**box, area_max_m2=60)] == [old]
    assert len(repo.complexes_in_bbox(**box, limit=1)) == 1


# ---------------------------------------------------------------------------
# 리포지토리 — 추천 작업 (IDOR)
# ---------------------------------------------------------------------------

def test_남의_작업은_조회되지_않는다(repo):
    """security.md §2.2 — 소유권 검증을 쿼리가 강제한다."""
    owner = repo.create_user("owner@example.com", "h")
    other = repo.create_user("other@example.com", "h")

    repo.create_job("rec_abc", owner.id, {"region": "강남구"})

    assert repo.get_job("rec_abc", owner.id) is not None
    assert repo.get_job("rec_abc", other.id) is None      # ← 여기가 무너지면 유출이다
    assert repo.get_job("rec_없음", owner.id) is None


def test_작업_스냅샷과_항목이_순위대로_온다(repo, engine):
    user = repo.create_user("job@example.com", "h")
    cid = _seed_complex(engine, name="추천단지", lon=127.05, lat=37.50)
    criteria = {"budget_krw": 1500000000, "regions": ["강남구", "송파구"]}
    repo.create_job("rec_items", user.id, criteria)

    with engine.begin() as conn:
        conn.execute(text("""
            INSERT INTO recommendation_item
                (job_id, complex_id, rank, total_score, est_price_krw, timing_signal)
            VALUES ('rec_items', :cid, 2, 71.500, 1400000000, 'hold'),
                   ('rec_items', :cid, 1, 88.250, 1450000000, 'buy')
        """), {"cid": cid})

    job = repo.get_job("rec_items", user.id)
    assert job.status == "queued"
    assert job.criteria_snapshot == criteria      # 재현성 근거(G2)가 그대로 남는다
    assert [it["rank"] for it in job.items] == [1, 2]
    assert job.items[0]["total_score"] == pytest.approx(88.25)
    assert job.items[0]["timing_signal"] == "buy"


# ---------------------------------------------------------------------------
# 리포지토리 — 입지 (location-analyst 입력)
# ---------------------------------------------------------------------------

def _seed_poi(engine, *, category: str, name: str, lon: float, lat: float,
              attrs: str = "{}") -> int:
    with engine.begin() as conn:
        return conn.execute(text("""
            INSERT INTO poi (category, name, geom, attrs, source)
            VALUES (:cat, :name, ST_SetSRID(ST_MakePoint(:lon,:lat),4326),
                    CAST(:attrs AS jsonb), 'test')
            RETURNING id
        """), {"cat": category, "name": name, "lon": lon, "lat": lat,
               "attrs": attrs}).one().id


def test_학구도_포함이어야_배정학교로_인정한다(repo, engine):
    """models.py 절대 규칙 1 — 배정 근거는 거리가 아니라 학구도 포함 여부다."""
    cid = _seed_complex(engine, name="학군단지", lon=127.05, lat=37.50)
    school = _seed_poi(engine, category="school", name="언주초", lon=127.052, lat=37.502,
                       attrs='{"district_as_of":"2026","achievement_pct":88.5,'
                             '"achievement_source":"학교알리미","achievement_as_of":"2025"}')
    with engine.begin() as conn:
        # 단지를 덮는 학구도 폴리곤
        conn.execute(text("""
            INSERT INTO school_district (school_poi_id, geom, source)
            VALUES (:sid, ST_SetSRID(ST_MakeEnvelope(127.04,37.49,127.06,37.51),4326),
                    '학교알리미')
        """), {"sid": school})

    facts = repo.location_facts(cid)
    assert facts.school is not None
    assert facts.school.in_district is True
    assert facts.school.name == "언주초"
    assert facts.school.district_data_available is True
    assert facts.school.distance_m == pytest.approx(280, abs=80)   # geography 미터
    assert facts.school.achievement_pct == 88.5
    # 도로 선형 데이터가 없어 판정 불가 → False(안전함)로 지어내지 않는다
    assert facts.school.crosses_main_road is None


def test_학구도_미포함과_미확보를_구분한다(repo, engine):
    # 학구도 폴리곤(127.04~127.06) 밖이지만 데이터 확보 반경(5km) 안 — 약 1.3km
    far = _seed_complex(engine, name="학구도밖", lon=127.075, lat=37.50)
    school = _seed_poi(engine, category="school", name="먼초교", lon=127.05, lat=37.50)
    with engine.begin() as conn:
        conn.execute(text("""
            INSERT INTO school_district (school_poi_id, geom, source)
            VALUES (:sid, ST_SetSRID(ST_MakeEnvelope(127.04,37.49,127.06,37.51),4326), 'x')
        """), {"sid": school})

    # 학구도 데이터가 아예 없는 지역
    none_area = _seed_complex(engine, name="데이터없음", lon=128.50, lat=37.50)

    f_far = repo.location_facts(far)
    assert f_far.school.in_district is False
    assert f_far.school.name is None          # 최근접 학교로 대체하지 않는다

    f_none = repo.location_facts(none_area)
    assert f_none.school.district_data_available is False


def test_역_최단거리와_노선을_돌려준다(repo, engine):
    cid = _seed_complex(engine, name="역세권", lon=127.05, lat=37.50)
    _seed_poi(engine, category="subway", name="선릉역", lon=127.0505, lat=37.5005,
              attrs='{"lines":["2호선","수인분당선"]}')
    _seed_poi(engine, category="subway", name="먼역", lon=127.070, lat=37.515)

    facts = repo.location_facts(cid)
    assert [s.name for s in facts.stations] == ["선릉역", "먼역"]   # 가까운 순
    assert facts.stations[0].lines == ("2호선", "수인분당선")
    assert facts.stations[0].distance_m < 100


def test_응급실_병원을_따로_넘긴다(repo, engine):
    """도메인이 nearest('hospital') 과 nearest('hospital', er=True) 를 따로 묻는다."""
    cid = _seed_complex(engine, name="인프라단지", lon=127.05, lat=37.50)
    _seed_poi(engine, category="hospital", name="가까운의원", lon=127.0505, lat=37.5005,
              attrs='{"has_emergency_room": false}')
    _seed_poi(engine, category="hospital", name="응급실병원", lon=127.058, lat=37.505,
              attrs='{"has_emergency_room": true}')
    _seed_poi(engine, category="mart", name="마트", lon=127.052, lat=37.501)
    _seed_poi(engine, category="park", name="공원", lon=127.051, lat=37.5015)

    pois = {(p.kind, p.has_emergency_room): p for p in repo.location_facts(cid).pois}
    assert ("mart", None) in pois and ("park", None) in pois
    assert pois[("hospital", False)].name == "가까운의원"
    assert pois[("hospital", True)].name == "응급실병원"
    # 응급실 병원이 더 멀다는 사실이 그대로 보존돼야 한다
    assert pois[("hospital", True)].distance_m > pois[("hospital", False)].distance_m


def test_유해요소는_도메인_반경_안의_것만_넘긴다(repo, engine):
    """HAZARD_RADIUS_M(power_line 150m) 밖의 것은 넘기지 않는다."""
    cid = _seed_complex(engine, name="유해단지", lon=127.05, lat=37.50)
    # 약 55m — power_line 반경(150m) 안
    _seed_poi(engine, category="hazard", name="송전탑", lon=127.0506, lat=37.50,
              attrs='{"hazard_kind":"power_line","detail":"154kV"}')
    # 약 890m — 반경 밖
    _seed_poi(engine, category="hazard", name="먼송전탑", lon=127.06, lat=37.50,
              attrs='{"hazard_kind":"power_line"}')
    # category=road → main_road_noise 로 유추 (약 22m, 반경 50m 안)
    _seed_poi(engine, category="road", name="테헤란로", lon=127.05025, lat=37.50)
    # 종류를 알 수 없는 행은 버린다 — 근거 없는 감점 방지(G2)
    _seed_poi(engine, category="hazard", name="정체불명", lon=127.0501, lat=37.50)

    kinds = {h.kind: h for h in repo.location_facts(cid).hazards}
    assert set(kinds) == {"power_line", "main_road_noise"}
    assert kinds["power_line"].detail == "154kV"
    assert kinds["power_line"].distance_m <= 150


def test_신설노선_계획은_단계만_넘긴다(repo, engine):
    """신뢰도 환산은 도메인(plan_confidence)이 한다 — 여기서 점수를 매기지 않는다."""
    cid = _seed_complex(engine, name="호재단지", lon=127.05, lat=37.50)
    with engine.begin() as conn:
        conn.execute(text("""
            INSERT INTO transit_plan (name, geom, open_expected, status, source_url)
            VALUES ('GTX-C', ST_SetSRID(ST_MakePoint(127.051,37.5005),4326),
                    DATE '2030-12-31', '계획', 'https://molit.go.kr/x')
        """))
    plans = repo.location_facts(cid).plans
    assert len(plans) == 1
    assert plans[0].status == "계획"
    assert plans[0].open_expected == "2030-12-31"
    assert plans[0].source == "https://molit.go.kr/x"


def test_좌표없는_단지는_빈_사실을_돌려준다(repo, engine):
    with engine.begin() as conn:
        cid = conn.execute(text("""
            INSERT INTO complex (name, geom) VALUES ('좌표없음', NULL) RETURNING id
        """)).one().id
    facts = repo.location_facts(cid)
    assert facts is not None and facts.school is None and facts.stations == ()
    assert repo.location_facts(999_999) is None      # 없는 단지는 None


def test_동별_입지사실과_중앙외곽_분류(repo, engine):
    cid = _seed_complex(engine, name="동별단지", lon=127.05, lat=37.50)
    _seed_poi(engine, category="subway", name="역", lon=127.0490, lat=37.50)
    with engine.begin() as conn:
        conn.execute(text("""
            INSERT INTO building (complex_id, name, geom, direction_deg) VALUES
              (:cid, '101동', ST_SetSRID(ST_MakePoint(127.0495,37.500),4326), 180),
              (:cid, '105동', ST_SetSRID(ST_MakePoint(127.0505,37.500),4326), 90)
        """), {"cid": cid})

    facts = {b.label: b for b in repo.building_location_facts(cid)}
    assert set(facts) == {"101동", "105동"}
    # 역에 가까운 쪽이 실제로 더 가깝게 나와야 한다(geography 미터)
    assert facts["101동"].station_distance_m < facts["105동"].station_distance_m
    assert facts["101동"].orientation_deg == 180
    # 무게중심 기준 중앙/외곽 상대 분류
    assert {facts["101동"].position_in_complex,
            facts["105동"].position_in_complex} <= {"중앙", "외곽"}
    # 학구도가 없는 지역이므로 '미확보'(None) — False(미포함)로 단정하지 않는다
    assert facts["101동"].school_in_district is None


def test_동이_없으면_빈_목록(repo, engine):
    cid = _seed_complex(engine, name="동없음", lon=127.05, lat=37.50)
    assert repo.building_location_facts(cid) == []


# ---------------------------------------------------------------------------
# API 전 구간 (register → login → profile → map) — 실 DB 위에서
# ---------------------------------------------------------------------------

def test_API_전구간이_PostGIS_위에서_동작한다(repo, engine, monkeypatch):
    monkeypatch.setenv("JWT_SECRET", "x" * 40)
    monkeypatch.setenv("FIELD_ENCRYPTION_KEY", "k" * 32)
    monkeypatch.setenv("POSTGRES_PASSWORD", "pw")
    monkeypatch.setenv("TAX_RULES_PATH", str(FIXTURES / "tax_rules_test.yaml"))

    from fastapi.testclient import TestClient

    from app.core.config import get_settings
    get_settings.cache_clear()
    from app.main import create_app

    _seed_complex(engine, name="E2E단지", lon=127.05, lat=37.50)
    password = "correct horse battery staple"

    try:
        with TestClient(create_app(repo=repo)) as client:
            r = client.post("/api/v1/auth/register",
                            json={"email": "e2e@example.com", "password": password})
            assert r.status_code == 201, r.text

            r = client.post("/api/v1/auth/login",
                            json={"email": "e2e@example.com", "password": password})
            assert r.status_code == 200, r.text
            auth = {"Authorization": f"Bearer {r.json()['access_token']}"}

            r = client.put("/api/v1/me/profile", headers=auth, json={
                "cash_krw": 500_000_000, "income_krw": 90_000_000,
                "existing_loan_krw": 0, "owned_houses": 0, "household_size": 3})
            assert r.status_code == 200, r.text

            r = client.get("/api/v1/me/profile", headers=auth)
            assert r.status_code == 200
            # 평문 금액이 DB 를 왕복하고도 그대로 복원된다(암호화 → bytea → 복호화)
            assert r.json()["cash_krw"] == 500_000_000
            assert r.json()["household_size"] == 3

            r = client.get("/api/v1/map/complexes", headers=auth,
                           params={"bbox": "127.0,37.4,127.1,37.6", "zoom": 15})
            assert r.status_code == 200, r.text
            body = r.json()
            assert body["level"] == "complex"
            assert [i["name"] for i in body["items"]] == ["E2E단지"]

            r = client.post("/api/v1/recommendations", headers=auth,
                            json={"region_codes": ["1168010100"], "purpose": "live"})
            assert r.status_code == 202, r.text
            job_id = r.json()["job_id"]
            assert client.get(f"/api/v1/recommendations/{job_id}",
                              headers=auth).status_code == 200
    finally:
        get_settings.cache_clear()


def test_DB에_평문_금액이_남지_않는다(repo, engine, monkeypatch):
    """G3: 저장된 bytea 어디에도 금액이 평문 문자열로 보이지 않아야 한다."""
    monkeypatch.setenv("JWT_SECRET", "x" * 40)
    monkeypatch.setenv("FIELD_ENCRYPTION_KEY", "k" * 32)
    monkeypatch.setenv("POSTGRES_PASSWORD", "pw")
    monkeypatch.setenv("TAX_RULES_PATH", str(FIXTURES / "tax_rules_test.yaml"))

    from fastapi.testclient import TestClient

    from app.core.config import get_settings
    get_settings.cache_clear()
    from app.main import create_app

    password = "correct horse battery staple"
    try:
        with TestClient(create_app(repo=repo)) as client:
            client.post("/api/v1/auth/register",
                        json={"email": "leak@example.com", "password": password})
            r = client.post("/api/v1/auth/login",
                            json={"email": "leak@example.com", "password": password})
            auth = {"Authorization": f"Bearer {r.json()['access_token']}"}
            client.put("/api/v1/me/profile", headers=auth, json={
                "cash_krw": 123_456_789, "income_krw": 98_765_432,
                "existing_loan_krw": 0, "owned_houses": 0, "household_size": 1})
    finally:
        get_settings.cache_clear()

    with engine.connect() as conn:
        row = conn.execute(text("""
            SELECT cash_krw_enc, income_krw_enc FROM user_profile
        """)).one()
    for blob in (bytes(row.cash_krw_enc), bytes(row.income_krw_enc)):
        assert b"123456789" not in blob
        assert b"98765432" not in blob
        assert blob[:1] == b"\x01"    # 암호문 포맷 버전 헤더
