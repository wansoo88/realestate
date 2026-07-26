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
         poi, school_district, transit_plan, road_segment
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
        # ⚠️ 파라미터 없이 **raw 커서**로 실행한다. exec_driver_sql 로 넘기면 psycopg3 가
        #    SQL 안의 '%' 를 파라미터 자리표시자로 읽어, COMMENT 에 '77~93%' 같은 퍼센트가
        #    들어간 정상 마이그레이션이 `incomplete placeholder` 로 깨진다(006, 실DB 검증에서 발견).
        #    운영은 psql(docker-entrypoint-initdb.d)로 적용돼 '%' 가 리터럴이므로,
        #    **테스트도 psql 과 같은 의미로 실행해야** 검증이 운영을 대표한다.
        raw = conn.connection.dbapi_connection
        for path in MIGRATIONS:
            # 파일 안에 BEGIN/COMMIT 이 있으므로 드라이버에 그대로 넘긴다.
            with raw.cursor() as cur:
                cur.execute(path.read_text(encoding="utf-8"))
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
    #
    # exec_driver_sql 을 쓰는 이유: SQLAlchemy `text()` 는 JSON 리터럴 '{"a":1}' 의
    # `:1` 을 바인드 파라미터로 오해석한다(CR-008 에서 이 테스트가 실패한 원인).
    # 드라이버로 직접 보내면 콜론을 해석하지 않는다. 파라미터는 psycopg 의 %s 를 쓴다.
    with pytest.raises(DBAPIError):
        with engine.begin() as conn:
            conn.exec_driver_sql(
                """
                INSERT INTO agent_finding (item_id, agent_id, evidence)
                VALUES (%s, 'valuation-trader', '{"a":1}'::jsonb)
                """,
                (item_id,),
            )


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
# 추천 러너 핸드오프 (docs/domain/recommendation-execution.md §repo인터페이스)
#   러너가 duck-typing 으로 부르므로, 시그니처가 어긋나도 크래시 대신
#   **조용히 추천이 비어** 버린다. 그래서 실제 동작을 여기서 못 박는다.
# ---------------------------------------------------------------------------

def test_후보조회는_시군구_5자리로_접두매칭한다(repo, engine):
    """region_codes 는 5자리 시군구, complex.region_code 는 10자리 법정동코드다.

    완전일치로 짜면 후보가 **항상 0건**이 되고 러너는 그걸 정상으로 취급한다.
    """
    gangnam = _seed_complex(engine, name="강남단지", lon=127.05, lat=37.50,
                            region="1168010100")
    bundang = _seed_complex(engine, name="분당단지", lon=127.11, lat=37.36,
                            region="4113510100")

    assert [c.id for c in repo.recommendation_candidates(region_codes=["11680"])] == [gangnam]
    assert [c.id for c in repo.recommendation_candidates(region_codes=["41135"])] == [bundang]
    got = repo.recommendation_candidates(region_codes=["11680", "41135"])
    assert {c.id for c in got} == {gangnam, bundang}
    # 빈 목록이면 전체 (러너가 지역 미지정으로 부를 수 있다)
    assert len(repo.recommendation_candidates(region_codes=[])) == 2
    # 10자리를 그대로 줘도 동작한다
    assert [c.id for c in repo.recommendation_candidates(
        region_codes=["1168010100"])] == [gangnam]


def test_후보조회는_예산으로_거르지_않는다(repo, engine):
    """예산 초과 단지도 넘기고 파이프라인이 사유와 함께 제외한다(ux/README.md §4)."""
    _seed_complex(engine, name="비싼단지", lon=127.05, lat=37.50)
    got = repo.recommendation_candidates(region_codes=["11680"], max_price_krw=1)
    assert len(got) == 1


def _seed_trades(engine, complex_id: int, *, n: int, price_krw: int) -> None:
    with engine.begin() as conn:
        for i in range(n):
            conn.execute(text("""
                INSERT INTO trade (complex_id, contract_date, price_krw, area_m2, source)
                VALUES (:cid, current_date - CAST(:days AS int), :price, 84.97, 'molit')
            """), {"cid": complex_id, "days": 15 * i + 1, "price": price_krw})


def test_후보조회는_호가가_0건이어도_단지를_돌려준다(repo, engine):
    """★핵심 회귀 (CHARTER G4): 공공API 에는 호가가 없다.

    호가로 INNER JOIN 하거나 `active_listings > 0` 을 WHERE 에 두면 `listing` 이 빈
    운영 DB 에서 후보가 **구조적으로 항상 0건**이 된다(2026-07-26 실측: listing 0건).
    """
    cid = _seed_complex(engine, name="호가없는단지", lon=127.05, lat=37.50)
    _seed_trades(engine, cid, n=8, price_krw=800_000_000)

    got = repo.recommendation_candidates(region_codes=["11680"])
    assert [c.id for c in got] == [cid]
    assert got[0].active_listings == 0        # 호가는 정말로 0건이다
    assert got[0].recent_price_krw == 800_000_000


def test_후보조회는_실거래_표본이_많은_단지를_먼저_준다(repo, engine):
    """LIMIT 이 id 순으로 잘리면 거래 0건 단지만 뽑혀 후보가 0건이 된다."""
    quiet = _seed_complex(engine, name="거래없는단지", lon=127.05, lat=37.50)
    busy = _seed_complex(engine, name="거래많은단지", lon=127.06, lat=37.51)
    _seed_trades(engine, busy, n=10, price_krw=800_000_000)

    got = repo.recommendation_candidates(region_codes=["11680"])
    assert [c.id for c in got] == [busy, quiet]   # id 순이면 quiet 가 먼저였을 것


def test_후보조회는_예산안에서_체결된_단지를_먼저_준다(repo, engine):
    """예산은 **정렬 신호**다(거르지 않는다).

    이게 없으면 LIMIT 이 '거래 많은 = 비싼 대단지'로 다 차서 예산이 작은 사용자에게는
    후보가 전멸한다(송파 실측: 후보 136 중 117 예산초과).
    """
    pricey = _seed_complex(engine, name="비싼대단지", lon=127.05, lat=37.50)
    modest = _seed_complex(engine, name="저렴한단지", lon=127.06, lat=37.51)
    _seed_trades(engine, pricey, n=20, price_krw=2_500_000_000)   # 표본은 더 많다
    _seed_trades(engine, modest, n=8, price_krw=700_000_000)

    # 예산 없으면 표본 많은 쪽이 먼저
    assert [c.id for c in repo.recommendation_candidates(region_codes=["11680"])] \
        == [pricey, modest]

    # 예산이 있으면 예산 안에서 체결된 단지가 먼저 — 그래도 비싼 단지가 사라지진 않는다
    got = repo.recommendation_candidates(region_codes=["11680"],
                                         max_price_krw=1_000_000_000)
    assert [c.id for c in got] == [modest, pricey]


def test_후보조회는_호가있는_단지를_최우선으로_준다(repo, engine):
    """호가가 살아 있으면 '지금 살 수 있는 물건'이 있는 쪽이 먼저다."""
    listed = _seed_complex(engine, name="호가있는단지", lon=127.05, lat=37.50)
    traded = _seed_complex(engine, name="실거래만단지", lon=127.06, lat=37.51)
    _seed_trades(engine, traded, n=20, price_krw=700_000_000)
    with engine.begin() as conn:
        conn.execute(text("""
            INSERT INTO listing (complex_id, ask_price_krw, area_m2, status, source)
            VALUES (:cid, 900000000, 84.97, 'active', 'portal')
        """), {"cid": listed})

    got = repo.recommendation_candidates(region_codes=["11680"],
                                         max_price_krw=1_000_000_000)
    assert [c.id for c in got] == [listed, traded]


def test_후보조회에_시세와_매물수가_실린다(repo, engine):
    cid = _seed_complex(engine, name="후보단지", lon=127.05, lat=37.50)
    with engine.begin() as conn:
        conn.execute(text("""
            INSERT INTO trade (complex_id, contract_date, price_krw, source)
            VALUES (:cid, DATE '2026-06-01', 1600000000, 'molit')
        """), {"cid": cid})
        conn.execute(text("""
            INSERT INTO listing (complex_id, ask_price_krw, status, source)
            VALUES (:cid, 1700000000, 'active', 'portal')
        """), {"cid": cid})

    c = repo.recommendation_candidates(region_codes=["11680"])[0]
    assert c.recent_price_krw == 1600000000
    assert c.price_as_of == "2026-06-01"
    assert c.active_listings == 1


def test_활성매물만_중복포함해서_넘긴다(repo, engine):
    """중복 제거는 러너의 group_duplicates 가 한다 — 미리 지우면 근거를 못 만든다."""
    cid = _seed_complex(engine, name="매물단지", lon=127.05, lat=37.50)
    with engine.begin() as conn:
        conn.execute(text("""
            INSERT INTO listing (complex_id, ask_price_krw, area_m2, floor,
                                 listed_at, status, agency, source) VALUES
              (:cid, 1700000000, 84.9, 10, DATE '2026-07-01', 'active', 'A공인', 'p1'),
              (:cid, 1700000000, 84.9, 10, DATE '2026-07-02', 'active', 'B공인', 'p2'),
              (:cid, 1650000000, 84.9,  3, DATE '2026-06-01', 'withdrawn', 'C공인', 'p3')
        """), {"cid": cid})

    rows = repo.listings_for_complex(cid)
    assert len(rows) == 2                       # withdrawn 제외, 중복 2건은 그대로
    assert {r.agency for r in rows} == {"A공인", "B공인"}
    assert rows[0].area_m2 == pytest.approx(84.9)
    assert rows[0].floor == 10
    assert all(r.status == "active" for r in rows)
    assert repo.listings_for_complex(999_999) == []


def test_실거래는_해제건도_그대로_넘긴다(repo, engine):
    """해제 제외는 통계 계층이 정한다. 여기서 걸러 버리면 '해제 몇 건'을 근거로 못 쓴다."""
    cid = _seed_complex(engine, name="거래단지", lon=127.05, lat=37.50)
    with engine.begin() as conn:
        conn.execute(text("""
            INSERT INTO trade (complex_id, contract_date, price_krw, area_m2,
                               floor, is_cancelled, source) VALUES
              (:cid, DATE '2026-05-01', 1500000000, 84.9, 5, false, 'molit'),
              (:cid, DATE '2026-06-01', 9900000000, 84.9, 7, true,  'molit')
        """), {"cid": cid})

    rows = repo.trades_for_complex(cid)
    assert len(rows) == 2
    assert rows[0].contract_date.isoformat() == "2026-06-01"   # 최신순
    assert rows[0].is_cancelled is True
    assert rows[1].price_krw == 1500000000


def test_추천결과_저장과_조회_왕복(repo, engine):
    """저장한 리포트 본문이 그대로 돌아와야 한다 (payload — 005).

    re-pm 승인 근거: "headline·why·why_not·next_actions·판단보류사유가 응답에서
    사라지면 추천이 반쪽이다." 그 다섯 가지를 여기서 하나씩 확인한다.
    """
    user = repo.create_user("save@example.com", "h")
    cid = _seed_complex(engine, name="저장단지", lon=127.05, lat=37.50)
    repo.create_job("rec_save", user.id, {"region_codes": ["11680"]})

    items = [{
        "complex": {"id": cid, "name": "저장단지"},
        "unit_type": {"area_m2": 84.9},
        "building": None,
        "ask_price_krw": 1_700_000_000,
        "total_score": 88.25,
        "timing_signal": "unknown",
        "headline": "예산 안에서 가장 균형 잡힌 후보",
        "why": ["역세권 350m", "학구도 포함"],
        "why_not": ["1층 매물"],
        "next_actions": ["현장 확인"],
        "rank": 1,
        "findings": [
            {"agent_id": "valuation-trader", "verdict": "적정", "rationale": "중위 대비 -2%",
             "evidence": [{"claim": "중위 17억", "source": "국토부", "as_of": "2026-07-01"}],
             "risks": [], "score": 88.0, "confidence": 0.8, "basis": None, "missing": []},
            # 근거 없는 '판단 보류' — agent_finding 에는 못 들어간다(CHECK)
            {"agent_id": "location-analyst", "verdict": "판단 보류", "rationale": "입지 데이터 없음",
             "evidence": [], "risks": [], "score": None, "confidence": 0.0,
             "basis": None, "missing": ["학군"]},
        ],
    }]
    repo.save_job_result("rec_save", user.id, status="done", items=items)

    job = repo.get_job("rec_save", user.id)
    assert job.status == "done"
    assert len(job.items) == 1
    got = job.items[0]
    # 리포트 본문 4종 — 정규화 컬럼만으로는 하나도 복원되지 않는다
    assert got["headline"] == "예산 안에서 가장 균형 잡힌 후보"
    assert got["why"] == ["역세권 350m", "학구도 포함"]
    assert got["why_not"] == ["1층 매물"]
    assert got["next_actions"] == ["현장 확인"]
    assert got["rank"] == 1

    # 다섯째 — 판단 보류 사유. agent_finding 에는 못 들어가지만(CHECK) 여기엔 남는다.
    abstained = [f for f in got["findings"] if f["verdict"] == "판단 보류"]
    assert len(abstained) == 1
    assert abstained[0]["agent_id"] == "location-analyst"
    assert abstained[0]["rationale"] == "입지 데이터 없음"
    assert abstained[0]["missing"] == ["학군"]

    with engine.connect() as conn:
        item = conn.execute(text("""
            SELECT complex_id, rank, total_score, est_price_krw, timing_signal, unit_type_id
            FROM recommendation_item WHERE job_id = 'rec_save'
        """)).one()
        assert item.complex_id == cid and item.rank == 1
        assert float(item.total_score) == pytest.approx(88.25)
        assert item.est_price_krw == 1_700_000_000
        assert item.unit_type_id is None            # unit_type 미적재 → NULL 허용

        # 근거 있는 finding 만 저장된다 (G2 · agent_finding CHECK)
        agents = [r.agent_id for r in conn.execute(text(
            "SELECT agent_id FROM agent_finding"))]
        assert agents == ["valuation-trader"]


def test_남의_작업에는_결과를_쓰지_못한다(repo):
    """IDOR — save_job_result 도 소유권을 다시 확인한다."""
    owner = repo.create_user("owner2@example.com", "h")
    other = repo.create_user("other2@example.com", "h")
    repo.create_job("rec_idor", owner.id, {})

    repo.save_job_result("rec_idor", other.id, status="done",
                         items=[{"complex": {"id": 1}, "total_score": 99}])

    job = repo.get_job("rec_idor", owner.id)
    assert job.status == "queued"     # 남이 쓴 결과가 반영되지 않았다
    assert job.items == []


def test_결과_재저장은_이전_결과를_대체한다(repo, engine):
    user = repo.create_user("rerun@example.com", "h")
    cid = _seed_complex(engine, name="재실행단지", lon=127.05, lat=37.50)
    repo.create_job("rec_rerun", user.id, {})

    def _item(score):
        return {"complex": {"id": cid}, "total_score": score, "rank": 1,
                "timing_signal": "unknown", "findings": []}

    repo.save_job_result("rec_rerun", user.id, status="done", items=[_item(50)])
    repo.save_job_result("rec_rerun", user.id, status="done", items=[_item(90)])

    with engine.connect() as conn:
        n = conn.execute(text(
            "SELECT count(*) FROM recommendation_item WHERE job_id='rec_rerun'")).scalar_one()
    assert n == 1
    assert repo.get_job("rec_rerun", user.id).items[0]["total_score"] == 90


# ---------------------------------------------------------------------------
# 004 — trade 자연키 · 지역코드 해석
# ---------------------------------------------------------------------------

def test_004_중복_실거래는_한_번만_적재된다(repo, engine):
    """원본에 거래 ID 가 없어 매일 배치가 같은 거래를 다시 받아온다.

    중복이 쌓이면 표본 수가 부풀어 MIN_SAMPLE 을 가짜로 넘기고 중위가가 왜곡된다.
    """
    cid = _seed_complex(engine, name="중복단지", lon=127.05, lat=37.50)
    row = {"cid": cid}
    ins = text("""
        INSERT INTO trade (complex_id, contract_date, price_krw, area_m2, floor, source)
        VALUES (:cid, DATE '2026-06-01', 1500000000, 84.9, 5, 'molit')
        ON CONFLICT ON CONSTRAINT trade_natural_key
        DO UPDATE SET is_cancelled = EXCLUDED.is_cancelled
    """)
    with engine.begin() as conn:
        conn.execute(ins, row)
        conn.execute(ins, row)          # 같은 배치를 다시 돌린다
        conn.execute(ins, row)

    with engine.connect() as conn:
        n = conn.execute(text(
            "SELECT count(*) FROM trade WHERE complex_id = :cid"), {"cid": cid}).scalar_one()
    assert n == 1, "같은 거래가 여러 번 적재됐습니다 (자연키 미적용)"


def test_004_층_면적이_비어도_중복을_막는다(repo, engine):
    """NULLS NOT DISTINCT — 기본 동작이면 NULL 끼리 달라서 유니크가 안 걸린다.

    원본에서 floor·area_m2 가 비는 행이 바로 중복이 가장 많이 생기는 자리다.
    """
    cid = _seed_complex(engine, name="널단지", lon=127.05, lat=37.50)
    ins = text("""
        INSERT INTO trade (complex_id, contract_date, price_krw, area_m2, floor, source)
        VALUES (:cid, DATE '2026-06-01', 1500000000, NULL, NULL, 'molit')
        ON CONFLICT ON CONSTRAINT trade_natural_key DO NOTHING
    """)
    with engine.begin() as conn:
        conn.execute(ins, {"cid": cid})
        conn.execute(ins, {"cid": cid})

    with engine.connect() as conn:
        n = conn.execute(text(
            "SELECT count(*) FROM trade WHERE complex_id = :cid"), {"cid": cid}).scalar_one()
    assert n == 1


def test_004_해제여부는_갱신된다(repo, engine):
    """해제는 나중에 바뀌어 다시 내려온다 — 자연키는 같고 상태만 바뀐다."""
    cid = _seed_complex(engine, name="해제단지", lon=127.05, lat=37.50)
    with engine.begin() as conn:
        conn.execute(text("""
            INSERT INTO trade (complex_id, contract_date, price_krw, area_m2, floor,
                               is_cancelled, source)
            VALUES (:cid, DATE '2026-06-01', 1500000000, 84.9, 5, false, 'molit')
        """), {"cid": cid})
        conn.execute(text("""
            INSERT INTO trade (complex_id, contract_date, price_krw, area_m2, floor,
                               is_cancelled, source)
            VALUES (:cid, DATE '2026-06-01', 1500000000, 84.9, 5, true, 'molit')
            ON CONFLICT ON CONSTRAINT trade_natural_key
            DO UPDATE SET is_cancelled = EXCLUDED.is_cancelled
        """), {"cid": cid})

    rows = repo.trades_for_complex(cid)
    assert len(rows) == 1 and rows[0].is_cancelled is True


def test_INGEST2_해제거래_시세조작이_막힌다(repo, engine):
    """자연키에 `is_cancelled` 가 들어가면 방어가 깨진다 — 그걸 여기서 못 박는다.

    공격: 높은 가격에 계약 → 신고 → 해제.
    해제 신고가 **별도 행**으로 들어오면 원래의 허위 고가 행이 그대로 살아남아
    시세가 위로 조작된다. 자연키에서 is_cancelled 를 빼야 upsert 가
    **기존 행을 해제로 갱신**하고, 통계 계층이 그 한 행을 제외할 수 있다.
    """
    cid = _seed_complex(engine, name="조작단지", lon=127.05, lat=37.50)
    normal = text("""
        INSERT INTO trade (complex_id, contract_date, price_krw, area_m2, floor,
                           is_cancelled, source)
        VALUES (:cid, DATE '2026-06-01', :price, 84.9, 5, false, 'molit')
        ON CONFLICT ON CONSTRAINT trade_natural_key
        DO UPDATE SET is_cancelled = EXCLUDED.is_cancelled
    """)
    cancelled = text("""
        INSERT INTO trade (complex_id, contract_date, price_krw, area_m2, floor,
                           is_cancelled, source)
        VALUES (:cid, DATE '2026-06-01', :price, 84.9, 5, true, 'molit')
        ON CONFLICT ON CONSTRAINT trade_natural_key
        DO UPDATE SET is_cancelled = EXCLUDED.is_cancelled
    """)
    with engine.begin() as conn:
        # 정상 시세 한 건
        conn.execute(normal, {"cid": cid, "price": 1_500_000_000})
        # 허위 고가 신고
        conn.execute(normal, {"cid": cid, "price": 3_000_000_000})
        # 며칠 뒤 해제 신고가 내려온다
        conn.execute(cancelled, {"cid": cid, "price": 3_000_000_000})

    rows = repo.trades_for_complex(cid)
    # 허위 고가가 '정상' 행으로 남아 있으면 안 된다 (있으면 시세가 2배로 뛴다)
    assert len(rows) == 2, "해제행이 별도로 생겼습니다 — 자연키에 is_cancelled 가 들어갔습니다"
    high = [r for r in rows if r.price_krw == 3_000_000_000]
    assert len(high) == 1 and high[0].is_cancelled is True

    live = [r for r in rows if not r.is_cancelled]
    assert [r.price_krw for r in live] == [1_500_000_000]

    # 자연키 정의 자체를 확인 — is_cancelled 가 들어가면 즉시 깨진다
    with engine.connect() as conn:
        cols = conn.execute(text("""
            SELECT a.attname
            FROM pg_constraint c
            JOIN unnest(c.conkey) WITH ORDINALITY AS k(attnum, ord) ON true
            JOIN pg_attribute a ON a.attrelid = c.conrelid AND a.attnum = k.attnum
            WHERE c.conname = 'trade_natural_key'
            ORDER BY k.ord
        """)).scalars().all()
    assert "is_cancelled" not in cols, f"자연키에 is_cancelled 가 있습니다: {cols}"
    assert set(cols) == {"complex_id", "contract_date", "price_krw", "area_m2", "floor"}


def _seed_regions(engine) -> None:
    with engine.begin() as conn:
        conn.execute(text("""
            INSERT INTO region (code, sido, sigungu, dong) VALUES
              ('1168010100','서울특별시','강남구','역삼동'),
              ('1168010600','서울특별시','강남구','대치동'),
              ('1135010100','서울특별시','강북구','미아동'),
              ('4113510100','경기도','성남시 분당구','정자동')
            ON CONFLICT (code) DO NOTHING
        """))


def test_주소에서_법정동코드를_찾는다(repo, engine):
    _seed_regions(engine)
    assert repo.resolve_region_code("서울특별시 강남구 대치동 316") == "1168010600"
    # 시군구가 두 토막인 경우
    assert repo.resolve_region_code("경기도 성남시 분당구 정자동 178") == "4113510100"


def test_같은_동이름은_시군구로_구분한다(repo, engine):
    """동 이름만으로 찾으면 다른 구의 같은 동에 붙는다 — 엉뚱한 지역 통계가 된다."""
    _seed_regions(engine)
    with engine.begin() as conn:
        conn.execute(text("""
            INSERT INTO region (code, sido, sigungu, dong) VALUES
              ('1168010700','서울특별시','강남구','신사동'),
              ('1129013000','서울특별시','성동구','신사동')
            ON CONFLICT (code) DO NOTHING
        """))
    assert repo.resolve_region_code("서울특별시 강남구 신사동 123") == "1168010700"
    assert repo.resolve_region_code("서울특별시 성동구 신사동 123") == "1129013000"


def test_못_찾으면_None을_돌려준다(repo, engine):
    """비슷한 이름으로 넘겨짚지 않는다 — 틀린 지역코드는 조용히 통계를 오염시킨다."""
    _seed_regions(engine)
    assert repo.resolve_region_code("서울특별시 강남구 없는동 1") is None
    assert repo.resolve_region_code("부산광역시 해운대구 우동 1") is None
    assert repo.resolve_region_code("") is None
    # 도로명주소는 동 정보가 없다 → None (추정하지 않는다)
    assert repo.resolve_region_code("서울특별시 강남구 테헤란로 152") is None


def test_배치_해석(repo, engine):
    _seed_regions(engine)
    got = repo.resolve_region_codes([
        "서울특별시 강남구 대치동 316",
        "서울특별시 강북구 미아동 1",
        "없는 주소",
    ])
    assert got["서울특별시 강남구 대치동 316"] == "1168010600"
    assert got["서울특별시 강북구 미아동 1"] == "1135010100"
    assert got["없는 주소"] is None


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


def test_003_학구도_기준연도가_컬럼에서_온다(repo, engine):
    """003 이전엔 기준일자를 적을 자리가 없었다(CHARTER §5)."""
    cid = _seed_complex(engine, name="기준연도단지", lon=127.05, lat=37.50)
    school = _seed_poi(engine, category="school", name="기준초", lon=127.052, lat=37.502)
    with engine.begin() as conn:
        conn.execute(text("""
            INSERT INTO school_district (school_poi_id, geom, source, as_of)
            VALUES (:sid, ST_SetSRID(ST_MakeEnvelope(127.04,37.49,127.06,37.51),4326),
                    '학교알리미', DATE '2026-03-01')
        """), {"sid": school})

    assert repo.location_facts(cid).school.district_as_of == "2026-03-01"


def test_003_통학로_대로횡단을_판정한다(repo, engine):
    """도로 선형이 있어야만 판정한다. 없으면 False 가 아니라 None(모름)."""
    cid = _seed_complex(engine, name="횡단단지", lon=127.05, lat=37.50)
    school = _seed_poi(engine, category="school", name="건너초", lon=127.054, lat=37.50)
    with engine.begin() as conn:
        conn.execute(text("""
            INSERT INTO school_district (school_poi_id, geom, source)
            VALUES (:sid, ST_SetSRID(ST_MakeEnvelope(127.04,37.49,127.06,37.51),4326), 'x')
        """), {"sid": school})

    # 도로 데이터가 없는 동안은 '모름'
    assert repo.location_facts(cid).school.crosses_main_road is None

    with engine.begin() as conn:
        # 단지(127.050)와 학교(127.054) 사이를 남북으로 가로지르는 간선도로
        conn.execute(text("""
            INSERT INTO road_segment (name, road_class, geom, source)
            VALUES ('테헤란로', '간선',
                    ST_SetSRID(ST_MakeLine(ST_MakePoint(127.052,37.49),
                                           ST_MakePoint(127.052,37.51)), 4326), 'test')
        """))
    assert repo.location_facts(cid).school.crosses_main_road is True

    # 통학 직선 밖(단지 반대편)의 도로는 횡단이 아니다
    with engine.begin() as conn:
        conn.execute(text("TRUNCATE road_segment RESTART IDENTITY"))
        conn.execute(text("""
            INSERT INTO road_segment (name, road_class, geom, source)
            VALUES ('반대편로', '간선',
                    ST_SetSRID(ST_MakeLine(ST_MakePoint(127.040,37.49),
                                           ST_MakePoint(127.040,37.51)), 4326), 'test')
        """))
    assert repo.location_facts(cid).school.crosses_main_road is False


def test_003_이면도로는_대로횡단으로_치지_않는다(repo, engine):
    """모든 단지가 '대로 횡단'이 되면 판정이 무의미해진다."""
    cid = _seed_complex(engine, name="이면단지", lon=127.05, lat=37.50)
    school = _seed_poi(engine, category="school", name="이면초", lon=127.054, lat=37.50)
    with engine.begin() as conn:
        conn.execute(text("""
            INSERT INTO school_district (school_poi_id, geom, source)
            VALUES (:sid, ST_SetSRID(ST_MakeEnvelope(127.04,37.49,127.06,37.51),4326), 'x')
        """), {"sid": school})
        conn.execute(text("""
            INSERT INTO road_segment (name, road_class, geom, source)
            VALUES ('골목길', '일반',
                    ST_SetSRID(ST_MakeLine(ST_MakePoint(127.052,37.49),
                                           ST_MakePoint(127.052,37.51)), 4326), 'test')
        """))
    # 간선급 도로가 주변에 하나도 없으므로 '모름'
    assert repo.location_facts(cid).school.crosses_main_road is None


def test_003_road_segment_제약(engine):
    """선형이 아닌 도형은 거부한다(점을 도로로 넣으면 거리 계산이 조용히 틀어진다)."""
    with pytest.raises(IntegrityError):
        with engine.begin() as conn:
            conn.execute(text("""
                INSERT INTO road_segment (name, road_class, geom, source)
                VALUES ('점', '간선', ST_SetSRID(ST_MakePoint(127.05,37.5),4326), 't')
            """))
    with pytest.raises(IntegrityError):        # road_class 화이트리스트
        with engine.begin() as conn:
            conn.execute(text("""
                INSERT INTO road_segment (name, road_class, geom, source)
                VALUES ('x', '오솔길',
                        ST_SetSRID(ST_MakeLine(ST_MakePoint(127.05,37.5),
                                               ST_MakePoint(127.06,37.5)),4326), 't')
            """))


def test_003_동별_간선도로_거리는_선형을_쓴다(repo, engine):
    cid = _seed_complex(engine, name="도로단지", lon=127.05, lat=37.50)
    with engine.begin() as conn:
        conn.execute(text("""
            INSERT INTO building (complex_id, name, geom) VALUES
              (:cid, '101동', ST_SetSRID(ST_MakePoint(127.0495,37.500),4326)),
              (:cid, '105동', ST_SetSRID(ST_MakePoint(127.0520,37.500),4326))
        """), {"cid": cid})
        # 127.053 경도를 따라 남북으로 뻗은 간선도로
        conn.execute(text("""
            INSERT INTO road_segment (name, road_class, geom, source)
            VALUES ('간선대로', '간선',
                    ST_SetSRID(ST_MakeLine(ST_MakePoint(127.053,37.49),
                                           ST_MakePoint(127.053,37.51)), 4326), 'test')
        """))

    facts = {b.label: b for b in repo.building_location_facts(cid)}
    # 도로에 붙은 105동이 101동보다 가깝다 — 선형과의 최단거리가 잡혔다는 뜻
    assert facts["105동"].main_road_distance_m < facts["101동"].main_road_distance_m
    assert facts["105동"].main_road_distance_m == pytest.approx(88, abs=40)


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
