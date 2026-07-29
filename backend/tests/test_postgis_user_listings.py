"""사용자 수동 입력 호가 — **실 DB 검증** (migrations/016).

`TEST_DATABASE_URL` 이 없으면 통째로 skip 한다. 조용히 통과시키지 않고
"검증 안 됨"이 실행 결과에 보이게 두는 게 요점이다(test_postgis_repo.py 와 같은 규약).

    docker run -d --name pg-test -e POSTGRES_PASSWORD=pw -e POSTGRES_DB=realestate_test \
        -p 55432:5432 postgis/postgis:16-3.4
    set TEST_DATABASE_URL=postgresql+psycopg://postgres:pw@localhost:55432/realestate_test
    python -m pytest tests/test_postgis_user_listings.py -m needs_db -v

여기서 지키는 것
----------------
① DB 가 **출처 짝맞춤**을 강제한다(앱 코드를 우회해도 섞이지 않는다).
② 소유자 스코프가 **SQL 안에** 있다(파이썬 검사에 의존하지 않는다).
③ 낡은 호가는 **쿼리에서** 빠진다(호출부가 잊어도 계산에 안 들어간다).
④ 사용자 입력이 **지도의 매물 수를 바꾸지 않는다**(교차 사용자 누출 차단).

※ 이 파일이 skip 된 상태에서도 위 4가지는 운영 DB 에서 한 번 실측했다
   (2026-07-29, `BEGIN … ROLLBACK` 안에서 016 적용 후 제약 8종 파괴 시험).
   그건 1회성 확인이라 회귀를 못 막는다 — 회귀를 막는 것은 이 파일이다.
"""
from __future__ import annotations

import datetime as dt
import os
from pathlib import Path

import pytest
from sqlalchemy import text
from sqlalchemy.exc import IntegrityError

from app.api import schemas
from app.repositories.base import LISTING_SOURCE_USER, LISTING_STALE_DAYS
from app.repositories.postgis import PostgisRepository

pytestmark = pytest.mark.needs_db

BACKEND_DIR = Path(__file__).resolve().parents[1]
MIGRATIONS = sorted((BACKEND_DIR / "migrations").glob("[0-9]*.sql"))
DB_URL = os.getenv("TEST_DATABASE_URL", "")
TODAY = dt.date.today()

_TRUNCATE = """
TRUNCATE complex, trade, listing, region, app_user
RESTART IDENTITY CASCADE
"""


@pytest.fixture(scope="module")
def engine():
    if not DB_URL:
        pytest.skip("TEST_DATABASE_URL 미설정 — 실 DB 검증을 건너뜁니다(미검증 상태)")
    from sqlalchemy import create_engine

    if "test" not in DB_URL.rsplit("/", 1)[-1].lower():
        pytest.fail("안전장치: TEST_DATABASE_URL 의 DB 이름에 'test' 가 들어가야 합니다")

    eng = create_engine(DB_URL, pool_pre_ping=True)
    with eng.connect().execution_options(isolation_level="AUTOCOMMIT") as conn:
        conn.exec_driver_sql("DROP SCHEMA IF EXISTS public CASCADE")
        conn.exec_driver_sql("CREATE SCHEMA public")
        raw = conn.connection.dbapi_connection
        for path in MIGRATIONS:
            with raw.cursor() as cur:
                cur.execute(path.read_text(encoding="utf-8"))
    yield eng
    eng.dispose()


@pytest.fixture()
def repo(engine):
    with engine.begin() as conn:
        conn.execute(text(_TRUNCATE))
    return PostgisRepository(engine)


@pytest.fixture()
def seed(engine, repo):
    """단지 2곳 + 사용자 2명."""
    with engine.begin() as conn:
        conn.execute(text("""
            INSERT INTO region (code, sido, sigungu) VALUES ('1168010100','서울','강남구')
            ON CONFLICT (code) DO NOTHING
        """))
        ids = [conn.execute(text("""
            INSERT INTO complex (region_code, name, geom, built_year, total_households)
            VALUES ('1168010100', :name, ST_SetSRID(ST_MakePoint(:lon, 37.5), 4326),
                    2005, 500)
            RETURNING id
        """), {"name": n, "lon": lon}).one().id
            for n, lon in (("가단지", 127.01), ("나단지", 127.02))]
        users = [conn.execute(text("""
            INSERT INTO app_user (email, password_hash) VALUES (:e, 'x') RETURNING id
        """), {"e": e}).one().id for e in ("a@t.co", "b@t.co")]
    return {"complexes": ids, "users": users}


# ---------------------------------------------------------------------------
# ① DB 가 출처 짝맞춤을 강제한다 — 앱을 우회해도 섞이지 않는다
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("cols, values, why", [
    ("ask_price_krw, area_m2, as_of, source",
     "1480000000, 84.97, current_date, 'user_entered'",
     "source 만 user_entered 이고 소유자가 없다"),
    ("created_by_user_id, ask_price_krw, area_m2, as_of, source",
     "{u}, 1480000000, 84.97, current_date, 'molit'",
     "소유자가 있는데 source 를 공공 출처로 위장했다"),
    ("created_by_user_id, ask_price_krw, area_m2, source",
     "{u}, 1480000000, 84.97, 'user_entered'",
     "사용자 입력에 as_of 가 없다"),
    ("created_by_user_id, ask_price_krw, area_m2, as_of, source",
     "{u}, 1000000000000, 84.97, current_date, 'user_entered'",
     "1조원"),
    ("created_by_user_id, ask_price_krw, area_m2, as_of, source",
     "{u}, 9000000, 84.97, current_date, 'user_entered'",
     "900만원 — 단위 실수"),
    ("created_by_user_id, ask_price_krw, area_m2, as_of, source",
     "{u}, 1480000000, 0, current_date, 'user_entered'",
     "면적 0"),
    ("created_by_user_id, ask_price_krw, area_m2, floor, as_of, source",
     "{u}, 1480000000, 84.97, 9999, current_date, 'user_entered'",
     "9999층"),
])
def test_DB가_직접_막는다(engine, seed, cols, values, why):
    cid = seed["complexes"][0]
    uid = seed["users"][0]
    with pytest.raises(IntegrityError), engine.begin() as conn:
        conn.execute(text(
            f"INSERT INTO listing (complex_id, {cols}) "
            f"VALUES ({cid}, {values.format(u=uid)})"))


def test_수집_출처의_계약은_그대로다(engine, seed):
    """016 의 CHECK 는 **사용자 입력 행에만** 걸린다. 수집 경로를 조이지 않는다."""
    cid = seed["complexes"][0]
    with engine.begin() as conn:
        conn.execute(text("""
            INSERT INTO listing (complex_id, ask_price_krw, area_m2, source)
            VALUES (:cid, 1480000000, 84.97, 'portal')
        """), {"cid": cid})
        n = conn.execute(text(
            "SELECT count(*) FROM listing WHERE created_by_user_id IS NULL")).scalar()
    assert n == 1


def test_사용자를_지우면_그의_호가도_사라진다(engine, seed, repo):
    cid, uid = seed["complexes"][0], seed["users"][0]
    repo.add_user_listing(uid, complex_id=cid, ask_price_krw=1_480_000_000,
                          area_m2=84.97, as_of=TODAY)
    with engine.begin() as conn:
        conn.execute(text("DELETE FROM app_user WHERE id = :u"), {"u": uid})
        left = conn.execute(text("SELECT count(*) FROM listing")).scalar()
    assert left == 0


# ---------------------------------------------------------------------------
# ② 소유자 스코프가 SQL 안에 있다
# ---------------------------------------------------------------------------

def test_분석_경로가_주인_것만_준다(repo, seed):
    cid, (a, b) = seed["complexes"][0], seed["users"]
    repo.add_user_listing(a, complex_id=cid, ask_price_krw=1_480_000_000,
                          area_m2=84.97, as_of=TODAY, floor=9)
    repo.add_user_listing(b, complex_id=cid, ask_price_krw=1_200_000_000,
                          area_m2=84.97, as_of=TODAY, floor=3)

    assert [r.ask_price_krw for r in repo.listings_for_complex(cid, a)] \
        == [1_480_000_000]
    assert [r.ask_price_krw for r in repo.listings_for_complex(cid, b)] \
        == [1_200_000_000]
    # user_id 없이 부르면 **하나도** 안 나온다(fail-closed).
    assert repo.listings_for_complex(cid) == []


def test_남의_것은_조회도_수정도_삭제도_안_된다(repo, seed):
    cid, (a, b) = seed["complexes"][0], seed["users"]
    rec = repo.add_user_listing(a, complex_id=cid, ask_price_krw=1_480_000_000,
                                area_m2=84.97, as_of=TODAY)
    assert repo.get_user_listing(rec.id, b) is None
    assert repo.update_user_listing(rec.id, b, note="침입") is None
    assert repo.delete_user_listing(rec.id, b) is False
    # 원본이 그대로다.
    assert repo.get_user_listing(rec.id, a).note is None


def test_수집_행은_사용자_CRUD로_건드릴_수_없다(engine, repo, seed):
    """`source='user_entered'` 조건이 SQL 에 있어 수집 데이터가 사용자 API 로 새지 않는다."""
    cid, uid = seed["complexes"][0], seed["users"][0]
    with engine.begin() as conn:
        lid = conn.execute(text("""
            INSERT INTO listing (complex_id, ask_price_krw, area_m2, source)
            VALUES (:cid, 1480000000, 84.97, 'portal') RETURNING id
        """), {"cid": cid}).one().id
    assert repo.get_user_listing(lid, uid) is None
    assert repo.delete_user_listing(lid, uid) is False
    with engine.connect() as conn:
        assert conn.execute(text("SELECT count(*) FROM listing")).scalar() == 1


def test_목록은_내_것만_최근_확인순으로(repo, seed):
    (c1, c2), (a, b) = seed["complexes"], seed["users"]
    repo.add_user_listing(a, complex_id=c1, ask_price_krw=1_000_000_000,
                          area_m2=59.0, as_of=TODAY - dt.timedelta(days=10))
    repo.add_user_listing(a, complex_id=c2, ask_price_krw=2_000_000_000,
                          area_m2=84.97, as_of=TODAY)
    repo.add_user_listing(b, complex_id=c1, ask_price_krw=3_000_000_000,
                          area_m2=84.97, as_of=TODAY)

    mine = repo.list_user_listings(a)
    assert [r.ask_price_krw for r in mine] == [2_000_000_000, 1_000_000_000]
    assert [r.complex_name for r in mine] == ["나단지", "가단지"]
    assert len(repo.list_user_listings(a, complex_id=c1)) == 1


# ---------------------------------------------------------------------------
# ③ 낡은 호가는 쿼리에서 빠진다
# ---------------------------------------------------------------------------

def test_낡은_호가는_분석_경로에_안_나오고_목록에는_남는다(repo, seed):
    cid, uid = seed["complexes"][0], seed["users"][0]
    fresh = repo.add_user_listing(uid, complex_id=cid, ask_price_krw=1_480_000_000,
                                  area_m2=84.97, as_of=TODAY)
    repo.add_user_listing(uid, complex_id=cid, ask_price_krw=1_100_000_000,
                          area_m2=84.97,
                          as_of=TODAY - dt.timedelta(days=LISTING_STALE_DAYS + 1))

    assert [r.id for r in repo.listings_for_complex(cid, uid)] == [fresh.id]
    assert len(repo.list_user_listings(uid)) == 2       # 고치라고 보여준다


def test_경계_하루_차이로_갈린다(repo, seed):
    cid, uid = seed["complexes"][0], seed["users"][0]
    edge = repo.add_user_listing(uid, complex_id=cid, ask_price_krw=1_480_000_000,
                                 area_m2=84.97,
                                 as_of=TODAY - dt.timedelta(days=LISTING_STALE_DAYS))
    assert [r.id for r in repo.listings_for_complex(cid, uid)] == [edge.id]

    repo.update_user_listing(edge.id, uid,
                             as_of=TODAY - dt.timedelta(days=LISTING_STALE_DAYS + 1))
    assert repo.listings_for_complex(cid, uid) == []


def test_상태를_바꾸면_분석에서_빠진다(repo, seed):
    cid, uid = seed["complexes"][0], seed["users"][0]
    rec = repo.add_user_listing(uid, complex_id=cid, ask_price_krw=1_480_000_000,
                                area_m2=84.97, as_of=TODAY)
    repo.update_user_listing(rec.id, uid, status="traded")
    assert repo.listings_for_complex(cid, uid) == []


def test_사용자_입력의_확인시점은_as_of다(repo, seed):
    """`collected_at`(저장 시각)이 아니라 as_of 가 하류로 간다 — 3개월 전에 본 매물을
    오늘 입력해도 '오늘 확인된 호가'로 둔갑하지 않는다."""
    cid, uid = seed["complexes"][0], seed["users"][0]
    seen = TODAY - dt.timedelta(days=40)
    repo.add_user_listing(uid, complex_id=cid, ask_price_krw=1_480_000_000,
                          area_m2=84.97, as_of=seen)
    row = repo.listings_for_complex(cid, uid)[0]
    assert row.collected_at == seen
    assert row.listed_at is None        # 포털 등록일은 모른다 — 지어내지 않는다
    # 출처가 분석 계층까지 간다 — 여기서 끊기면 `dedup.trust_score` 가 사람이 적은
    # 한 건에 만점을 준다(= 리스크 축 100점). 인메모리 구현과 **같은 규칙**이다
    # (test_user_listing_wiring.py::test_리포지토리가_출처와_확인일을_분석계층까지_싣는다).
    assert row.source == LISTING_SOURCE_USER
    assert row.is_user_entered is True
    assert row.as_of == seen


# ---------------------------------------------------------------------------
# ④ 사용자 입력이 공용 집계를 바꾸지 않는다
# ---------------------------------------------------------------------------

def test_지도의_매물수는_사용자_입력을_세지_않는다(repo, seed):
    """`active_listings` 는 소유자 인자가 없는 집계다 — 세면 A 의 입력이 B 에게 보인다."""
    cid, uid = seed["complexes"][0], seed["users"][0]
    repo.add_user_listing(uid, complex_id=cid, ask_price_krw=1_480_000_000,
                          area_m2=84.97, as_of=TODAY)

    rows = repo.complexes_in_bbox(min_lon=127.0, min_lat=37.4,
                                  max_lon=127.1, max_lat=37.6)
    assert {r.id for r in rows} >= {cid}
    assert all(r.active_listings == 0 for r in rows)


def test_후보_조회의_면적근거로도_세지_않는다(repo, seed):
    """면적 조건 통과 여부가 남의 입력으로 바뀌면 그것도 관측 가능한 누출이다."""
    cid, uid = seed["complexes"][0], seed["users"][0]
    repo.add_user_listing(uid, complex_id=cid, ask_price_krw=1_480_000_000,
                          area_m2=59.9, as_of=TODAY)
    got = repo.recommendation_candidates(region_codes=["11680"],
                                         area_min_m2=55.0, area_max_m2=65.0)
    assert cid not in {c.id for c in got}


# ---------------------------------------------------------------------------
# 수정 계약
# ---------------------------------------------------------------------------

def test_모르는_필드는_거절한다(repo, seed):
    cid, uid = seed["complexes"][0], seed["users"][0]
    rec = repo.add_user_listing(uid, complex_id=cid, ask_price_krw=1_480_000_000,
                                area_m2=84.97, as_of=TODAY)
    with pytest.raises(ValueError):
        repo.update_user_listing(rec.id, uid, price_krw=1)


def test_부분수정은_준_필드만_바꾼다(repo, seed):
    cid, uid = seed["complexes"][0], seed["users"][0]
    rec = repo.add_user_listing(uid, complex_id=cid, ask_price_krw=1_480_000_000,
                                area_m2=84.97, as_of=TODAY, floor=9,
                                apt_dong="101동", note="원본")
    out = repo.update_user_listing(rec.id, uid, ask_price_krw=1_390_000_000,
                                   as_of=TODAY)
    assert out.ask_price_krw == 1_390_000_000
    assert (out.floor, out.apt_dong, out.note) == (9, "101동", "원본")
    assert out.updated_at is not None


# ---------------------------------------------------------------------------
# ⑤ 두 리포지토리가 **같은 입력을 받아들이는가** (SR31-1)
# ---------------------------------------------------------------------------

def test_API가_통과시키는_문자열은_PostgreSQL도_받는다(repo, seed):
    """★ SR31-1 회귀. 이 갈라짐이 바로 "테스트가 운영을 대표하기를 멈추는" 지점이다.

    이전에는 `\u0000` 이 인메모리에서 **201**, PostgreSQL 에서 **500**
    (`psycopg.DataError: PostgreSQL text fields cannot contain NUL`)이었다.
    지금은 `schemas._clean_optional_text` 가 제어문자를 422 로 거절해 계약이
    좁은 쪽(PostgreSQL)에 맞춰졌다.

    여기서 확인하는 것은 그 반대 방향이다 — **API 가 통과시키는 값은 PostgreSQL 이
    전부 저장·반환하는가.** 좁히기만 하고 정작 정상 입력이 저장되지 않으면
    갈라짐을 반대로 만든 것이다.
    """
    cid, uid = seed["complexes"][0], seed["users"][0]
    for payload in ("네이버 부동산\n○○공인", "가격\t14.8억", "급매 🏠 확인함",
                    "１０１동", "'; DROP TABLE listing;--", "<script>alert(1)</script>"):
        accepted = schemas.UserListingIn(
            complex_id=cid, ask_price_krw=1_480_000_000, area_m2=84.97,
            as_of=TODAY, note=payload).note
        rec = repo.add_user_listing(uid, complex_id=cid, ask_price_krw=1_480_000_000,
                                    area_m2=84.97, as_of=TODAY, note=accepted)
        got = repo.get_user_listing(rec.id, uid)
        assert got.note == accepted, (payload, got.note)
