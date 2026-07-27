"""지도 응답의 **특성 태그용 사실** — `nearest_station` · `redevelopment` (MAP-2).

왜 이 파일이 따로 있는가
------------------------
화면(`frontend/src/lib/tags.ts`)은 단지에 🏢대단지·🚇역세권·🔨재건축 배지를 단다.
추천 카드에는 세 값이 다 실리는데 **지도 응답에는 세대수만** 있었다 → 주변 단지
목록에서 역세권·재건축이 **항상 "판정 불가"** 로 떴다. 여기 테스트는 두 가지를 고정한다:

① **이름과 모양이 추천과 같다.** 다르면 프론트가 태그 판정을 두 벌 갖게 되고,
   두 벌은 반드시 어긋난다(임계값 500m·1,000세대는 프론트 한 곳에만 있어야 한다).
② **모름과 없음을 섞지 않는다.** `redevelopment.available:false` 는 '정비사업 없음'이
   아니라 '확인되지 않음'이고(수집 범위: 서울·인천), `nearest_station:null` 은
   '역이 없다'가 아니라 '탐색 반경 안에서 못 찾았다'이다.
   ⚠️ 이 구분이 무너지면 화면이 **거짓 단언**을 한다 — 태그가 안 뜨는 것보다 나쁘다.
"""
from __future__ import annotations

import re
from pathlib import Path

import pytest

from app.api.routes import _map_tag_facts
from app.repositories.base import (
    ComplexSummary,
    NearestStationFact,
    RedevelopmentFact,
)
from app.repositories.postgis import PostgisRepository, _redev_fact, _station_fact

FRONTEND = Path(__file__).resolve().parents[2] / "frontend" / "src"


def _summary(**kw) -> ComplexSummary:
    base = dict(id=1, name="단지", lon=127.05, lat=37.5, region_code="1168000000")
    base.update(kw)
    return ComplexSummary(**base)


# ---------------------------------------------------------------------------
# 모양 — 추천 카드와 같은 이름·같은 형태
# ---------------------------------------------------------------------------

def test_역_사실은_판정이_아니라_값이다():
    """★ boolean 을 보내면 안 된다 — 임계값(500m)은 표시 관례라 바뀐다.

    서버가 '역세권 여부'로 굳혀 보내면 과거에 저장된 결과에 옛 임계값이 박히고
    되돌릴 수 없다. 거리를 주고 판정은 화면이 한다.
    """
    facts = _map_tag_facts(_summary(
        nearest_station=NearestStationFact(distance_m=412.3, name="선릉역",
                                           lines=("2호선", "수인분당선"))))
    station = facts["nearest_station"]
    assert station == {
        "name": "선릉역", "distance_m": 412.3, "line_count": 2,
        "lines": ["2호선", "수인분당선"], "basis": "straight_line",
    }
    assert not any(isinstance(v, bool) for v in station.values())


def test_역을_못_찾으면_0이_아니라_null():
    """0m 는 '역 바로 위'라는 뜻이다 — 모름을 0 으로 적으면 최고의 역세권이 된다."""
    facts = _map_tag_facts(_summary(nearest_station=None))
    assert facts["nearest_station"] is None


def test_정비사업_미매칭은_블록을_빼지_않고_available_false_로_싣는다():
    """★ '미확인 ≠ 없음'. 블록을 통째로 빼면 둘이 같은 모양(필드 부재)이 된다."""
    facts = _map_tag_facts(_summary(redevelopment=RedevelopmentFact(available=False)))
    redev = facts["redevelopment"]
    assert redev is not None, "블록을 빼면 '없다'와 '모른다'가 구분되지 않는다"
    assert redev["available"] is False


def test_available_false_의_뜻이_응답에_적혀_있다():
    """★ 플래그만 주고 뜻을 안 적으면 소비자가 '없음'으로 읽는다.

    ⚠️ 다만 **항목마다** 적지는 않는다 — 500단지 중 470이 미매칭이라 같은 문장이
       470번 실리면 응답이 64KiB 커진다(지도는 팬할 때마다 다시 부른다).
       뜻은 응답에 한 번, 항목에는 플래그만.
    """
    from app.api.routes import REDEV_MAP_UNKNOWN_NOTE

    assert "확인되지 않았다" in REDEV_MAP_UNKNOWN_NOTE
    assert "미수집" in REDEV_MAP_UNKNOWN_NOTE
    assert "missing" not in _map_tag_facts(
        _summary(redevelopment=RedevelopmentFact(available=False)))["redevelopment"]


def test_정비사업_매칭은_단계를_그대로_싣는다():
    facts = _map_tag_facts(_summary(redevelopment=RedevelopmentFact(
        available=True, stage="association", raw_stage="조합설립인가",
        zone_name="개포1구역")))
    redev = facts["redevelopment"]
    assert redev["available"] is True
    assert redev["raw_stage"] == "조합설립인가"


def test_지도에는_목적별_판정을_싣지_않는다():
    """같은 '관리처분'이 투자엔 '확실', 실거주엔 '이주 임박 — 부적합'이다.

    지도는 사용자의 목적을 모른다. 목적 없이 만든 판정을 올리면 추천 카드와
    다른 말을 하게 되고, 사용자는 어느 쪽도 못 믿는다.
    """
    facts = _map_tag_facts(_summary(redevelopment=RedevelopmentFact(
        available=True, stage="disposition", raw_stage="관리처분계획인가")))
    assert "verdict" not in facts["redevelopment"]
    assert "score" not in facts["redevelopment"]


# ---------------------------------------------------------------------------
# 프론트 계약 — 이름이 어긋나면 태그는 조용히 "판정 불가"가 된다
# ---------------------------------------------------------------------------

def _frontend_text(*parts: str) -> str:
    path = FRONTEND.joinpath(*parts)
    assert path.exists(), (
        f"프론트 계약 파일을 찾지 못했습니다: {path}. 이 테스트는 '화면이 무엇을 "
        "읽는지'를 그 파일에서 확인합니다 — 경로가 바뀌었다면 상수를 고치세요"
        "(검사를 지우지 마세요).")
    return path.read_text(encoding="utf-8")


def test_프론트가_읽는_이름과_서버가_보내는_이름이_같다():
    """★ 핵심 계약 검사 — 이 둘이 어긋나도 **아무 에러가 안 난다.**

    화면은 `c.nearest_station?.distance_m` · `c.redevelopment` 를 읽는다. 서버가
    `station`·`redev` 로 보내면 프론트는 `undefined` 를 받고 **조용히 "모름"** 이 된다.
    실패가 실패로 보이지 않는, 이 프로젝트가 가장 경계하는 형태다.
    """
    tags = _frontend_text("lib", "tags.ts")
    # 지도 항목(ComplexItem)을 사실로 옮기는 함수만 본다 — 추천 항목 변환은
    # 같은 파일의 다른 함수이고 필드 이름이 다르다(total_households).
    body = tags[tags.index("export function complexTagFacts"):]
    body = body[:body.index("}")]
    reads = set(re.findall(r"\bc\.(\w+)", body))
    served = set(_map_tag_facts(_summary())) | {"households"}
    for key in ("nearest_station", "redevelopment"):
        assert key in reads, f"프론트가 {key} 를 더 이상 읽지 않습니다(계약 확인 필요)"
        assert key in served, f"서버 지도 응답에 {key} 가 없습니다"
    assert reads <= served, (
        f"화면이 읽는데 지도 응답에 없는 키: {sorted(reads - served)}")


def test_프론트는_available_false_를_모름으로_접는다():
    """서버가 false 를 '아님'으로 쓰기 시작하면 이 전제가 깨진다 — 문서로 못박는다."""
    tags = _frontend_text("lib", "tags.ts")
    assert "block.available ? true : undefined" in tags, (
        "프론트의 `redevelopmentFact` 가 바뀌었습니다. 서버는 available:false 를 "
        "**'확인되지 않음'** 으로 보냅니다 — 화면이 이걸 '아님'으로 읽기 시작하면 "
        "없는 사실을 단정하게 됩니다(서버 쪽 의미를 먼저 맞추세요).")


# ---------------------------------------------------------------------------
# 성능 — N+1 이 되면 500단지 × 공간질의다
# ---------------------------------------------------------------------------

def test_지도_조회는_단지마다_따로_묻지_않는다():
    """★ 변이 가드 — 역·정비사업을 파이썬 루프로 조회하면 여기서 깨진다.

    상한이 500단지라 단지당 1회씩만 더 물어도 공간질의가 500배가 된다
    (SR-025 가 지적한 지점). 같은 SQL 안 LATERAL 로 붙여야 LIMIT 이 먼저 걸린다.
    """
    sql = str(PostgisRepository._BBOX_SQL)
    assert "LEFT JOIN LATERAL" in sql
    assert ":station_category" in sql and "redev_project_complex" in sql, (
        "역·정비사업이 지도 조회 SQL 안에 없습니다 — 밖에서 단지마다 물으면 N+1 입니다")
    # 실행 문장 수를 직접 센다(문자열 검사만으로는 루프가 생겨도 모른다).
    executed: list[str] = []

    class _Conn:
        def execute(self, statement, params=None):
            executed.append(str(statement))
            return _Result()

        def __enter__(self):
            return self

        def __exit__(self, *_a):
            return False

    class _Result:
        def all(self):
            return []

    class _Engine:
        def connect(self):
            return _Conn()

    repo = PostgisRepository.__new__(PostgisRepository)
    repo._engine = _Engine()
    repo.complexes_in_bbox(min_lon=127.0, min_lat=37.4, max_lon=127.1, max_lat=37.6)
    assert len(executed) == 1, f"지도 조회가 {len(executed)}개 문장을 돌렸습니다"


@pytest.mark.parametrize("row_kw, expect_station, expect_available", [
    ({"station_distance_m": 412.34, "station_name": "선릉역",
      "station_attrs": {"lines": ["2호선"]}, "redev_stage": None}, 412.3, False),
    ({"station_distance_m": None, "station_name": None, "station_attrs": None,
      "redev_stage": "association"}, None, True),
])
def test_조회행_변환(row_kw, expect_station, expect_available):
    """행 → 사실 변환. **없는 값을 만들지 않는다.**"""
    class _Row:
        redev_raw_stage = "조합설립인가"
        redev_zone_name = "개포1구역"

        def __init__(self, **kw):
            for k, v in kw.items():
                setattr(self, k, v)

    row = _Row(**row_kw)
    station = _station_fact(row)
    assert (None if station is None else station.distance_m) == expect_station
    assert _redev_fact(row).available is expect_available


# ---------------------------------------------------------------------------
# 라우터 통과 — 필드가 실제로 응답에 실리는가
# ---------------------------------------------------------------------------

@pytest.fixture()
def client(monkeypatch):
    """API 클라이언트 — 인증·설정 배선은 `test_api` 의 것을 그대로 쓴다.

    같은 배선을 두 벌 적으면 한쪽만 낡아서, 여기서만 통과하는 테스트가 된다.
    """
    from test_api import _make_client

    with _make_client(monkeypatch, "http://testserver") as c:
        yield c
    from app.core.config import get_settings
    get_settings.cache_clear()


def test_지도_응답에_두_필드가_실린다(client):
    """★ 회귀 — 이 두 키가 빠지면 주변 단지 태그가 **항상 '판정 불가'** 가 된다."""
    from test_api import _auth, _register_and_login

    token = _register_and_login(client, "map@b.co")
    client.repo.add_complex(_summary(
        id=1, total_households=1200,
        nearest_station=NearestStationFact(distance_m=310.0, name="가나역",
                                           lines=("2호선",)),
        redevelopment=RedevelopmentFact(available=True, stage="association",
                                        raw_stage="조합설립인가", zone_name="가나구역")))
    client.repo.add_complex(_summary(id=2, lon=127.06, lat=37.51))

    body = client.get("/api/v1/map/complexes",
                      params={"bbox": "126.9,37.4,127.1,37.6", "zoom": 15},
                      headers=_auth(token)).json()
    items = {i["id"]: i for i in body["items"]}

    assert items[1]["nearest_station"]["distance_m"] == 310.0
    assert items[1]["redevelopment"]["available"] is True
    # 값을 못 채운 단지도 **키는 온다**(키 부재와 모름을 섞지 않는다).
    assert items[2]["nearest_station"] is None
    assert items[2]["redevelopment"] is None
    # available:false 의 뜻은 응답에 한 번 적힌다.
    assert "확인되지 않았다" in body["redevelopment_note"]


#: 항목에 실어도 되는 문자열 길이 상한(글자). 이보다 긴 값은 **단지마다 다른 사실**이
#: 아니라 설명 문장일 가능성이 높고, 설명은 500번 반복될 이유가 없다.
_MAX_ITEM_STRING_LEN = 40


def test_항목마다_같은_설명문장을_반복하지_않는다():
    """★ 지도는 팬할 때마다 다시 부른다 — 응답 크기가 곧 체감 속도다.

    한 화면이 최대 500단지이고 운영 실측으로 그중 470이 정비사업 미매칭이다.
    `available:false` 의 뜻을 항목마다 적었더니 **같은 문장 470벌 = +64KiB** 였다.
    설명은 응답에 한 번(`redevelopment_note`), 항목에는 플래그와 사실만.
    """
    facts = _map_tag_facts(_summary(
        nearest_station=NearestStationFact(distance_m=412.3, name="선릉역",
                                           lines=("2호선", "수인분당선")),
        redevelopment=RedevelopmentFact(available=False)))

    def strings(value):
        if isinstance(value, str):
            yield value
        elif isinstance(value, dict):
            for v in value.values():
                yield from strings(v)
        elif isinstance(value, list):
            for v in value:
                yield from strings(v)

    long = [s for s in strings(facts) if len(s) > _MAX_ITEM_STRING_LEN]
    assert not long, (
        f"항목에 {_MAX_ITEM_STRING_LEN}자 넘는 문자열이 있습니다: {long}. "
        "단지마다 달라지지 않는 설명이라면 응답 단위 필드로 옮기세요"
        "(500단지 × 같은 문장 = 수십 KiB).")
