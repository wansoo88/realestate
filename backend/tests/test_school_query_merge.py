"""학구 조회를 **한 쿼리로 합친 뒤에도 급이 섞이지 않는가** (PERF-1).

배경
----
`location_facts` 가 급(초·중·고) 3벌을 따로 조회했다. 비싼 부분(`ST_Contains` 로 포함
구역을 찾는 것)은 급과 무관하게 매번 같은 일이라 세 번 계산됐다. 합쳤다.

⚠️ **합치면서 깨지면 안 되는 보장**
   급 분리가 있는 이유는 하나다 — *"가장 가까운 중학교가 배정 초등학교로 보고되는 것"*
   을 막는 것. 학구도는 리포트에 **단정형**으로 나가는 주장이라, 어긋나도 예외가
   안 나는 게 제일 위험하다.

이 파일은 DB 없이 도는 가드다(실DB 가드는 `test_postgis_repo.py` 의 013 계열).
둘 다 필요하다: 실DB 테스트는 `TEST_DATABASE_URL` 이 없으면 통째로 skip 되므로,
평소 실행에서 급 분리를 지키는 것은 여기다.
"""
from __future__ import annotations

import re

import pytest

from app.repositories.postgis import (
    _LEVEL_ELEMENTARY,
    _LEVEL_HIGH,
    _LEVEL_MIDDLE,
    _SCHOOL_LEVELS,
    PostgisRepository,
)


class _Row:
    """조회 1행 대역. 실제 컬럼 이름을 그대로 쓴다."""

    def __init__(self, level, name, distance_m=100.0, candidate_count=1,
                 zone_count=1, zone_name="구역", zone_kind="통학구역"):
        self.school_level = level
        self.name = name
        self.distance_m = distance_m
        self.attrs = {}
        self.district_as_of = None
        self.zone_name = zone_name
        self.zone_kind = zone_kind
        self.candidate_count = candidate_count
        self.zone_count = zone_count
        self.road_rows_nearby = 0
        self.road_crossings = 0


class _AvailRow:
    def __init__(self, level, available):
        self.level = level
        self.available = available


class _Conn:
    """실행된 문장을 세는 연결 대역."""

    def __init__(self, school_rows, avail):
        self._school_rows = school_rows
        self._avail = avail
        self.statements: list[tuple[str, dict]] = []

    def execute(self, statement, params=None):
        sql = str(statement)
        self.statements.append((sql, params or {}))
        if "unnest(CAST(:levels AS text[])) AS lv(level)" in sql:
            rows = [_AvailRow(lv, self._avail.get(lv, False))
                    for lv in params["levels"]]
        else:
            wanted = set(params["levels"])
            rows = [r for r in self._school_rows if r.school_level in wanted]
        return _Result(rows)


class _Result:
    def __init__(self, rows):
        self._rows = rows

    def all(self):
        return list(self._rows)


def _fetch(school_rows, avail=None):
    repo = PostgisRepository.__new__(PostgisRepository)
    conn = _Conn(school_rows, avail or {})
    return repo._fetch_schools(conn, 1), conn


# ---------------------------------------------------------------------------
# 급 분리 (합치면서 깨지면 회귀)
# ---------------------------------------------------------------------------

def test_행에_실린_급으로만_가른다():
    """★ 변이 가드 — 결과를 순서·인덱스로 가르면 여기서 깨진다.

    조회가 1벌이 됐으므로 "몇 번째 호출인가"로 급을 알 방법이 없다. 유일한 근거는
    행이 말하는 `school_level` 이다.
    """
    out, _ = _fetch([
        # 일부러 초등이 아닌 순서로 준다.
        _Row(_LEVEL_MIDDLE, "가까운중학교", distance_m=50.0),
        _Row(_LEVEL_ELEMENTARY, "먼초등학교", distance_m=900.0),
    ])
    assert out[_LEVEL_ELEMENTARY].name == "먼초등학교"
    assert out[_LEVEL_ELEMENTARY].level == _LEVEL_ELEMENTARY
    assert out[_LEVEL_MIDDLE].name == "가까운중학교"


def test_중학교만_있으면_초등은_미포함이지_중학교가_아니다():
    """★ 이 프로젝트가 가장 경계하는 조용한 오보 — 거리로 배정을 대체하지 않는다."""
    out, _ = _fetch([_Row(_LEVEL_MIDDLE, "가까운중학교", distance_m=10.0)],
                    avail={_LEVEL_ELEMENTARY: True})
    elem = out[_LEVEL_ELEMENTARY]
    assert elem.in_district is False
    assert elem.name is None, "포함되지 않은 급에 학교 이름을 채우면 안 된다"
    assert elem.level == _LEVEL_ELEMENTARY
    assert elem.district_data_available is True   # 데이터는 있는데 포함이 아니다


def test_미확보_판정도_급별로_따로_묻는다():
    """초등 학구도만 있는 곳에서 '중학교 학교군도 확보됨'이 되면 안 된다."""
    out, conn = _fetch([_Row(_LEVEL_ELEMENTARY, "초등만초")],
                       avail={_LEVEL_MIDDLE: True, _LEVEL_HIGH: False})
    assert out[_LEVEL_ELEMENTARY].district_data_available is True
    assert out[_LEVEL_MIDDLE].district_data_available is True
    assert out[_LEVEL_HIGH].district_data_available is False
    # 포함 구역이 있던 급은 **묻지 않는다**(불필요한 공간질의를 만들지 않는다).
    avail_params = [p for sql, p in conn.statements if "lv(level)" in sql][0]
    assert _LEVEL_ELEMENTARY not in avail_params["levels"]


def test_모든_급에_구역이_있으면_미확보_조회를_아예_안_한다():
    _, conn = _fetch([_Row(lv, f"학교{lv}") for lv in _SCHOOL_LEVELS])
    assert len(conn.statements) == 1, "물어볼 필요가 없는 조회를 돌렸다"


def test_조회는_두_문장을_넘지_않는다():
    """★ PERF-1 의 요점 — 급마다 조회를 되살리면 여기서 깨진다."""
    _, conn = _fetch([])          # 세 급 모두 포함 구역 없음(최악)
    assert len(conn.statements) == 2, [s for s, _ in conn.statements]


def test_요청하지_않은_급은_결과에_없다():
    """`:levels` 밖의 급(예: 유치원)이 섞여 들어오면 안 된다."""
    out, _ = _fetch([_Row("유치원", "어린이집병설"), _Row(_LEVEL_ELEMENTARY, "정상초")])
    assert set(out) == set(_SCHOOL_LEVELS)
    assert out[_LEVEL_ELEMENTARY].name == "정상초"


# ---------------------------------------------------------------------------
# SQL 구조 — 급 분리를 지키는 세 지점
# ---------------------------------------------------------------------------

_SQL = str(PostgisRepository._SCHOOL_SQL)


@pytest.mark.parametrize("fragment, why", [
    ("WHERE sd.school_level = ANY(CAST(:levels AS text[]))",
     "포함 구역을 급으로 좁히지 않으면 급 미상(NULL) 행까지 들어온다"),
    ("SELECT DISTINCT ON (school_level)",
     "급마다 최근접 1행이 아니면 가장 가까운 중학교 하나가 전체 결과가 된다"),
    ("WHERE c2.school_level = n.school_level",
     "후보 수를 급으로 안 가르면 초등 카드에 중·고 후보까지 합산된다"),
    ("WHERE g.school_level = n.school_level",
     "구역 수를 급으로 안 가르면 zone_count 가 급 합계가 된다"),
])
def test_SQL이_급_분리를_지키는_네_지점(fragment, why):
    """★ 변이 가드 — 넷 중 하나라도 지우면 급이 섞인다.

    운영 DB 실측으로도 확인했다(단지 200개 표본): 후보/구역 수의 급 필터를 지우면
    596/600, `DISTINCT ON` 의 급 분리를 지우면 396/600 이 3벌 조회 결과와 달라진다.
    """
    assert fragment in _SQL, why


def test_급을_문자열로_박아_넣지_않는다():
    """급 목록은 `:levels` 로 바인딩된다 — SQL 안에 리터럴로 박으면 조용히 어긋난다."""
    for level in _SCHOOL_LEVELS:
        assert f"'{level}'" not in _SQL


def test_최근접_동률이면_결정적으로_고른다():
    """같은 입력에 같은 학교가 나와야 근거가 된다(재현 가능성)."""
    order = re.search(r"ORDER BY school_level,([^\n]*)", _SQL).group(1)
    assert "distance_m" in order and "poi_id" in order, order
