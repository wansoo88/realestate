"""'이 주변에서 검색'(REC-5) — 범위 값 객체 · 리포지토리 계약 · SQL 규약.

여기서 지키려는 것
------------------
1. **형식이 갈라지지 않는다** — `/map/complexes` 와 `POST /recommendations` 가
   같은 `minLon,minLat,maxLon,maxLat` 를 쓴다. 갈라지면 프론트가 같은 값을 두 번
   다르게 만들고, 지도에 보이는 범위와 추천 대상이 언젠가 조용히 어긋난다.
2. **조용한 실패가 없다** — 뒤집힌 좌표·와일드카드 지역코드처럼 "에러 없이 엉뚱한
   결과"를 내는 입력은 전부 거절한다.
3. **GiST 를 탄다** — bbox 조건이 WHERE 맨 앞에 온다(erd.md §3.1).
"""
from __future__ import annotations

import pytest

from app.repositories.base import MAX_BBOX_DEGREES, BBox, BBoxError
from app.repositories.memory import InMemoryRepository
from app.repositories.postgis import PostgisRepository
from app.repositories.base import ComplexSummary

GANGNAM = "126.9,37.5,127.1,37.6"


# ---------------------------------------------------------------------------
# 값 객체 — 조용히 틀린 범위를 만들지 않는다
# ---------------------------------------------------------------------------

def test_정상_bbox를_경도먼저_읽는다():
    box = BBox.parse(GANGNAM)
    assert (box.min_lon, box.min_lat) == (126.9, 37.5)
    assert (box.max_lon, box.max_lat) == (127.1, 37.6)
    # /map/complexes 의 표기와 왕복이 된다(형식 일관성).
    assert BBox.parse(box.as_text()) == box


@pytest.mark.parametrize("raw", [
    "bad",                      # 숫자가 아님
    "126.9,37.5,127.1",         # 3개
    "126.9,37.5,127.1,37.6,1",  # 5개
    "126.9,37.5,127.1,abc",     # 일부만 숫자
    "",                         # 빈 문자열
])
def test_형식이_어긋나면_거절한다(raw):
    with pytest.raises(BBoxError):
        BBox.parse(raw)


@pytest.mark.parametrize("raw", [
    "127.1,37.5,126.9,37.6",    # min_lon > max_lon
    "126.9,37.6,127.1,37.5",    # min_lat > max_lat
    "126.9,37.5,126.9,37.6",    # 폭 0
])
def test_min이_max보다_크거나_같으면_거절한다(raw):
    """뒤집힌 범위는 SQL 에서 **에러 없이 0건**이 된다 — '거기 단지가 없다'와 구분이 안 된다."""
    with pytest.raises(BBoxError):
        BBox.parse(raw)


@pytest.mark.parametrize("raw", [
    "-181,37.5,127.1,37.6",     # 경도 하한 밖
    "126.9,37.5,181,37.6",      # 경도 상한 밖
    "126.9,-91,127.1,37.6",     # 위도 하한 밖
    "126.9,37.5,127.1,91",      # 위도 상한 밖
])
def test_좌표_범위를_벗어나면_거절한다(raw):
    with pytest.raises(BBoxError):
        BBox.parse(raw)


def test_위경도가_뒤바뀐_입력은_위도범위에서_걸린다():
    """`37.5,126.9,37.6,127.1` — 흔한 실수. 위도 126.9 는 존재하지 않는다."""
    with pytest.raises(BBoxError):
        BBox.parse("37.5,126.9,37.6,127.1")


def test_너무_넓은_범위는_거절한다():
    wide = f"126.0,37.0,{126.0 + MAX_BBOX_DEGREES + 0.1},37.5"
    with pytest.raises(BBoxError, match="너무 넓"):
        BBox.parse(wide)
    # 상한 '이하'는 통과한다(경계에서 갑자기 못 쓰게 되지 않게).
    assert BBox.parse(f"126.0,37.0,{126.0 + MAX_BBOX_DEGREES},37.5")


@pytest.mark.parametrize("raw", ["nan,37.5,127.1,37.6", "126.9,37.5,inf,37.6"])
def test_NaN_Inf는_거절한다(raw):
    """float() 는 통과시키지만 비교가 전부 False 라 검증을 조용히 빠져나간다."""
    with pytest.raises(BBoxError):
        BBox.parse(raw)


# ---------------------------------------------------------------------------
# 인메모리 리포지토리 — PostGIS 와 같은 결과를 내야 테스트가 프로덕션을 대표한다
# ---------------------------------------------------------------------------

def _complex(repo, cid, *, lon, lat, region="1168000000"):
    repo.add_complex(ComplexSummary(id=cid, name=f"단지{cid}", lon=lon, lat=lat,
                                    region_code=region, built_year=2015,
                                    total_households=500))


def test_bbox가_범위밖_단지를_뺀다():
    repo = InMemoryRepository()
    _complex(repo, 1, lon=127.05, lat=37.51)     # 안
    _complex(repo, 2, lon=129.00, lat=35.10)     # 밖(부산)

    box = BBox.parse("127.0,37.4,127.1,37.6")
    got = repo.recommendation_candidates(region_codes=[], bbox=box)
    assert [c.id for c in got] == [1]


def test_bbox가_없으면_기존대로_전체다():
    repo = InMemoryRepository()
    _complex(repo, 1, lon=127.05, lat=37.51)
    _complex(repo, 2, lon=129.00, lat=35.10)
    assert len(repo.recommendation_candidates(region_codes=[])) == 2


def test_지역과_bbox가_둘다_오면_교집합이다():
    """확정 계약: 지역도 고르고 '이 주변'도 눌렀다면 **둘 다** 만족해야 한다."""
    repo = InMemoryRepository()
    _complex(repo, 1, lon=127.05, lat=37.51, region="1168000000")   # 지역O 범위O
    _complex(repo, 2, lon=127.05, lat=37.51, region="4113500000")   # 지역X 범위O
    _complex(repo, 3, lon=129.00, lat=35.10, region="1168000000")   # 지역O 범위X

    box = BBox.parse("127.0,37.4,127.1,37.6")
    got = repo.recommendation_candidates(region_codes=["11680"], bbox=box)
    assert [c.id for c in got] == [1], "교집합이 아니라 합집합으로 동작한다"


def test_좌표없는_단지는_bbox로_찾을_수_없다():
    """PostGIS 의 `geom && ...` 는 geom 이 NULL 이면 NULL 을 낸다 — 여기서도 같아야 한다.

    인메모리만 통과시키면 실 DB 에서 조용히 빠지고, 테스트는 끝까지 초록불이다.
    """
    repo = InMemoryRepository()
    _complex(repo, 1, lon=127.05, lat=37.51)
    repo.add_complex(ComplexSummary(id=2, name="좌표없음", lon=None, lat=None,
                                    region_code="1168000000"))

    box = BBox.parse("127.0,37.4,127.1,37.6")
    assert [c.id for c in repo.recommendation_candidates(region_codes=[], bbox=box)] == [1]
    # 지역 검색에서는 **빠지지 않는다** — 좌표가 없다고 단지가 없는 것은 아니다.
    assert len(repo.recommendation_candidates(region_codes=["11680"])) == 2


def test_좌표_확보율을_숫자로_센다():
    repo = InMemoryRepository()
    _complex(repo, 1, lon=127.05, lat=37.51)
    repo.add_complex(ComplexSummary(id=2, name="좌표없음", lon=None, lat=None,
                                    region_code="1168000000"))
    _complex(repo, 3, lon=127.4, lat=37.3, region="4113500000")

    assert repo.geocode_coverage() == (2, 3)
    assert repo.geocode_coverage(region_codes=["11680"]) == (1, 2)


def test_지역코드는_접두로_매칭한다():
    """요청은 5자리 시군구, 저장은 10자리 법정동코드다 — 완전일치면 항상 0건이 된다."""
    repo = InMemoryRepository()
    _complex(repo, 1, lon=127.05, lat=37.51, region="1168010100")
    got = repo.recommendation_candidates(region_codes=["11680"])
    assert [c.id for c in got] == [1]


# ---------------------------------------------------------------------------
# PostGIS SQL 규약 — DB 없이도 확인할 수 있는 것들
# ---------------------------------------------------------------------------

def test_bbox절이_WHERE_맨앞에_온다():
    """`&&` 를 먼저 태워야 GiST(idx_complex_geom)를 탄다 (erd.md §3.1).

    지역 조건 뒤로 밀리면 플래너가 인덱스를 포기하고 전건 스캔이 된다 —
    느려질 뿐 결과는 같아서, 성능 회귀는 테스트가 없으면 아무도 모른다.
    """
    sql = PostgisRepository._CANDIDATES_BBOX_SQL.text
    where = sql[sql.index("WHERE"):]
    assert where.index("ST_MakeEnvelope") < where.index("region_codes"), (
        "bbox 조건이 WHERE 맨 앞이 아니다 — GiST 를 못 탄다")
    assert "c.geom &&" in where, "ST_Intersects 가 아니라 && 를 써야 인덱스를 탄다"


def test_bbox_없는_변형에는_공간조건이_없다():
    """'전체 검색'에 좌표 조건이 새면 좌표 없는 단지 5%가 조용히 사라진다."""
    assert "ST_MakeEnvelope" not in PostgisRepository._CANDIDATES_SQL.text


def test_두_변형이_bbox절_말고는_같다():
    """본문이 갈라지면 '이 주변'일 때만 다른 정렬·필터가 먹는 사고가 난다."""
    plain = PostgisRepository._CANDIDATES_SQL.text
    boxed = PostgisRepository._CANDIDATES_BBOX_SQL.text
    assert boxed.replace(PostgisRepository._BBOX_CLAUSE, "") == plain


def test_지역_접두매칭에_LIKE_와일드카드를_쓰지_않는다():
    """SR21-4 — `LIKE rc || '%'` 는 rc 에 `%` 가 섞이면 **전 지역**을 매칭한다.

    에러가 아니라 '조용히 넓어지는' 실패라서 사용자는 강남만 본다고 믿는다.
    `left(region_code, length(rc)) = rc` 는 와일드카드 개념 자체가 없다.
    """
    for sql in (PostgisRepository._CANDIDATES_SQL.text,
                PostgisRepository._CANDIDATES_BBOX_SQL.text,
                PostgisRepository._GEOCODE_COVERAGE_SQL.text):
        assert "LIKE" not in sql.upper(), "지역 접두 매칭에 LIKE 가 남아 있다"
        assert "left(c.region_code, length(rc)) = rc" in sql


def test_SQL에_사용자값을_문자열로_끼워넣지_않는다():
    """조립은 코드 안의 리터럴 2개로만 한다 — 값은 전부 바인딩 파라미터다."""
    boxed = PostgisRepository._CANDIDATES_BBOX_SQL.text
    for name in (":min_lon", ":min_lat", ":max_lon", ":max_lat", ":region_codes"):
        assert name in boxed
    assert "{" not in boxed and "}" not in boxed, "포맷 자리표시자가 남아 있다"
