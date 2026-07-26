"""입지(F3) 원천 파싱·적재 테스트.

이 파일의 **가장 중요한 테스트는 계약 테스트**다(§계약).

왜냐하면 이 경로의 실패는 조용하기 때문이다. `poi.attrs` 의 키를 `lines` 대신
`line_names` 로 적어도 SQL 은 성공하고, `location_facts()` 는 예외 없이 빈 결과를 낸다.
그러면 `location-analyst` 는 "판단 보류"를 내는데 — 그건 데이터가 없을 때와 **똑같은
증상**이라 아무도 원인을 못 찾는다. 그래서 계약을 코드가 아니라 테스트로 못박는다.
"""
from __future__ import annotations

import datetime as dt

import pytest

from app.domain.location.analysis import HAZARD_RADIUS_M, PLAN_STATUS_CONFIDENCE
from app.ingest import poi as poi_mod
from app.ingest.poi import (
    CAT_HAZARD,
    CAT_HOSPITAL,
    CAT_MART,
    CAT_PARK,
    CAT_SCHOOL,
    CAT_SUBWAY,
    PoiRecord,
    dedupe,
    element_point,
    is_passenger_station,
    neis_total_count,
    normalize_line_name,
    parse_amenities,
    parse_hazards,
    parse_neis_schools,
    parse_roads,
    parse_stations,
    parse_transit_plans,
    school_to_poi,
    station_lines,
)
from app.ingest.poi_loader import InMemoryPoiLoader

# ---------------------------------------------------------------------------
# §계약 — 리포지토리가 읽는 값과 수집기가 쓰는 값이 같은가
# ---------------------------------------------------------------------------


def test_categories_match_repository_constants():
    """poi.category 문자열이 postgis.py 의 상수와 **글자 단위로** 같아야 한다.

    다르면 `location_facts()` 의 LATERAL 이 0행을 내고 입지 분석이 조용히 죽는다.
    """
    from app.repositories import postgis as repo

    assert CAT_SUBWAY == repo._CAT_SUBWAY
    assert CAT_MART == repo._CAT_MART
    assert CAT_PARK == repo._CAT_PARK
    assert CAT_HOSPITAL == repo._CAT_HOSPITAL
    # 유해요소는 리포지토리가 category 두 개를 함께 훑는다.
    assert CAT_HAZARD in repo._HAZARD_CATEGORIES
    assert poi_mod.CAT_ROAD in repo._HAZARD_CATEGORIES


def test_hazard_kinds_are_known_to_the_domain():
    """우리가 쓰는 hazard_kind 는 전부 도메인이 반경을 아는 종류여야 한다.

    모르는 종류를 넣으면 리포지토리가 그 행을 **버린다**(postgis `_fetch_hazards`) —
    적재는 성공했는데 판정에는 안 쓰이는, 가장 알아채기 힘든 낭비가 된다.
    """
    used = {poi_mod.HAZARD_MAIN_ROAD, poi_mod.HAZARD_RAILWAY,
            poi_mod.HAZARD_HARMFUL, poi_mod.HAZARD_POWER_LINE}
    assert used <= set(HAZARD_RADIUS_M)


def test_hazard_attr_keys_match_repository_sql():
    """`hazard_kind` · `detail` 키 이름이 리포지토리 SQL 과 같아야 한다."""
    from app.repositories import postgis as repo

    sql = str(repo.PostgisRepository._HAZARDS_SQL)
    assert f"'{poi_mod.ATTR_HAZARD_KIND}'" in sql
    assert f"'{poi_mod.ATTR_DETAIL}'" in sql


def test_emergency_room_attr_key_matches_repository_sql():
    from app.repositories import postgis as repo

    assert f"'{poi_mod.ATTR_HAS_ER}'" in str(repo.PostgisRepository._POIS_SQL)


def test_station_lines_attr_key_matches_repository_reader():
    """`attrs['lines']` — 리포지토리 `_fetch_stations` 가 이 키로 노선을 읽는다."""
    import inspect

    from app.repositories import postgis as repo

    source = inspect.getsource(repo.PostgisRepository._fetch_stations)
    assert f'"{poi_mod.ATTR_LINES}"' in source or f"'{poi_mod.ATTR_LINES}'" in source


def test_road_classes_are_accepted_by_schema_and_domain():
    """도로 등급이 (1) 스키마 CHECK 값이고 (2) 리포지토리가 간선으로 세는 값이어야 한다."""
    from app.repositories import postgis as repo

    produced = set(poi_mod.ROAD_CLASS_BY_HIGHWAY.values())
    assert produced <= set(repo._MAIN_ROAD_CLASSES), (
        "간선 판정에 안 쓰이는 등급을 적재하면 통학로 횡단 판정에 잡히지 않는다")


def test_transit_status_values_are_known_to_the_domain():
    """transit_plan.status 는 도메인이 신뢰도를 아는 단계여야 한다(착공 전 ≤ 0.4)."""
    assert set(poi_mod.TRANSIT_STATUS_BY_TAG.values()) <= set(PLAN_STATUS_CONFIDENCE)


# ---------------------------------------------------------------------------
# 좌표
# ---------------------------------------------------------------------------


def test_element_point_reads_node_and_way_center():
    assert element_point({"lat": 37.5, "lon": 127.0}) == (127.0, 37.5)
    assert element_point({"center": {"lat": 37.5, "lon": 127.0}}) == (127.0, 37.5)


def test_element_point_returns_none_without_coordinates():
    """좌표가 없으면 **0,0 으로 채우지 않는다** — 기니만에 병원이 생긴다."""
    assert element_point({"type": "way", "id": 1}) is None
    assert element_point({"center": {"lat": "x", "lon": None}}) is None


# ---------------------------------------------------------------------------
# 역 · 노선
# ---------------------------------------------------------------------------

_STATION = {"type": "node", "id": 1, "lat": 37.5, "lon": 127.0,
            "tags": {"railway": "station", "subway": "yes", "name": "역삼"}}


def test_parse_stations_attaches_lines_from_relations():
    routes = {"elements": [
        {"type": "relation", "id": 9, "tags": {"type": "route", "route": "subway",
                                               "ref": "2"},
         "members": [{"type": "node", "ref": 1, "role": "stop"}]},
    ]}
    [rec] = parse_stations({"elements": [_STATION]}, routes)
    assert rec.category == CAT_SUBWAY
    assert rec.name == "역삼"
    assert (rec.lon, rec.lat) == (127.0, 37.5)
    assert rec.attrs["lines"] == ["2"]


def test_station_lines_dedupes_direction_variants():
    """상·하행이 별도 relation 이라 그대로 세면 환승역이 아닌데 line_count 가 2가 된다."""
    routes = {"elements": [
        {"type": "relation", "id": 9,
         "tags": {"type": "route", "route": "subway", "name": "2호선: 시청 → 을지로입구"},
         "members": [{"type": "node", "ref": 1, "role": "stop"}]},
        {"type": "relation", "id": 10,
         "tags": {"type": "route", "route": "subway", "name": "2호선: 을지로입구 → 시청"},
         "members": [{"type": "node", "ref": 1, "role": "stop"}]},
    ]}
    assert station_lines(routes) == {"node/1": ["2호선"]}


def test_station_lines_counts_transfer_station_once_per_line():
    routes = {"elements": [
        {"type": "relation", "id": 9, "tags": {"type": "route", "route": "subway",
                                               "ref": "2"},
         "members": [{"type": "node", "ref": 1, "role": "stop"}]},
        {"type": "relation", "id": 11, "tags": {"type": "route", "route": "subway",
                                                "ref": "9"},
         "members": [{"type": "node", "ref": 1, "role": "stop"}]},
    ]}
    assert station_lines(routes)["node/1"] == ["2", "9"]


def test_normalize_line_name_strips_direction_tail():
    assert normalize_line_name("수도권 전철 1호선: A → B") == "수도권 전철 1호선"
    assert normalize_line_name("신분당선 (연장)") == "신분당선"


@pytest.mark.parametrize("tags", [
    {"railway": "station", "usage": "freight", "name": "화물역", "train": "yes"},
    {"railway": "station", "name": "폐역", "disused": "yes", "train": "yes"},
    {"railway": "construction", "name": "공사중역", "subway": "yes"},
    {"railway": "station", "name": "버스만"},          # 여객철도 태그 없음
])
def test_is_passenger_station_rejects_non_service_stations(tags):
    """화물역·폐역·공사중 역을 역세권 근거로 쓰면 안 된다."""
    assert not is_passenger_station(tags)


def test_parse_stations_drops_unnamed_station():
    """이름이 없으면 '최근접 역 … 250m' 근거 문구를 만들 수 없다."""
    el = {**_STATION, "tags": {"railway": "station", "subway": "yes"}}
    assert parse_stations({"elements": [el]}) == []


def test_parse_stations_without_routes_yields_empty_lines():
    """노선 관계를 안 받았으면 lines 는 빈 배열 — 없는 노선을 지어내지 않는다."""
    [rec] = parse_stations({"elements": [_STATION]})
    assert rec.attrs["lines"] == []


# --- PTv2: route 멤버는 역 노드가 아니라 정차지점이다 -----------------------
#
# 실측(강남 일대 62개 노선): route 멤버 노드 1,940개 중 railway=station 노드와
# ID 가 일치한 건수 **0**. 이 사실을 모르고 ID 로만 이으면 노선이 전부 빈 배열이 되고,
# 리포트에 "노선 0개"가 찍힌다. 아래 테스트들이 그 회귀를 막는다.

def _routes_with_stop_position(*, stop_lon: float, stop_lat: float,
                               stop_name: str, ref: str = "9") -> dict:
    """역 노드(id=1)와 **다른** id 를 가진 정차지점을 멤버로 갖는 노선 관계."""
    return {"elements": [
        {"type": "relation", "id": 100,
         "tags": {"type": "route", "route": "subway", "ref": ref},
         "members": [{"type": "node", "ref": 777, "role": "stop"}]},
        {"type": "node", "id": 777, "lat": stop_lat, "lon": stop_lon,
         "tags": {"public_transport": "stop_position", "name": stop_name}},
    ]}


def test_lines_attach_through_stop_position_not_station_id():
    """정차지점 노드를 거쳐 노선이 역에 붙어야 한다(ID 는 서로 다르다)."""
    routes = _routes_with_stop_position(stop_lon=127.0004, stop_lat=37.5002,
                                        stop_name="역삼")
    [rec] = parse_stations({"elements": [_STATION]}, routes)
    assert rec.attrs["lines"] == ["9"]


def test_lines_ignore_same_named_stop_that_is_too_far():
    """이름이 같아도 450m 를 넘으면 잇지 않는다 — 동명 다른 역이 실제로 있다."""
    routes = _routes_with_stop_position(stop_lon=127.02, stop_lat=37.52,
                                        stop_name="역삼")
    [rec] = parse_stations({"elements": [_STATION]}, routes)
    assert rec.attrs["lines"] == []


def test_lines_ignore_nearby_stop_of_a_different_station():
    """가까워도 **이름이 다르면** 붙이지 않는다.

    거리만으로 이으면 종로3가/을지로3가처럼 인접한 역에 남의 노선이 붙어
    환승역 가점(+8)이 근거 없이 들어간다.
    """
    routes = _routes_with_stop_position(stop_lon=127.0020, stop_lat=37.5010,
                                        stop_name="선릉")
    [rec] = parse_stations({"elements": [_STATION]}, routes)
    assert rec.attrs["lines"] == []


def test_lines_match_station_name_with_or_without_suffix():
    """'역삼' 과 '역삼역' 은 같은 역이다."""
    routes = _routes_with_stop_position(stop_lon=127.0004, stop_lat=37.5002,
                                        stop_name="역삼역")
    [rec] = parse_stations({"elements": [_STATION]}, routes)
    assert rec.attrs["lines"] == ["9"]


def test_unnamed_stop_position_attaches_only_when_very_close():
    """이름 없는 정차지점은 아주 가까울 때만(150m) 인정한다."""
    near = _routes_with_stop_position(stop_lon=127.0005, stop_lat=37.5000,
                                      stop_name="")
    far = _routes_with_stop_position(stop_lon=127.0030, stop_lat=37.5000,
                                     stop_name="")
    assert parse_stations({"elements": [_STATION]}, near)[0].attrs["lines"] == ["9"]
    assert parse_stations({"elements": [_STATION]}, far)[0].attrs["lines"] == []


# --- 통근 노선 vs 고속·간선 여객 ---------------------------------------------
#
# OSM 은 KTX·SRT·무궁화호·ITX-새마을을 각각 별도 route 관계로 둔다. 그대로 세면
# 실측에서 수원역이 '노선 10개', 서울역이 '노선 11개'가 됐다. 그러면
#   ① 리포트 근거가 "노선 10개"로 나가 사용자를 오도하고,
#   ② 통근 노선이 1개뿐인 역(광명: 1호선 + KTX 3종)이 환승 가점 +8 을 받는다.

@pytest.mark.parametrize("tags,expected", [
    ({"type": "route", "route": "subway"}, "commuter"),
    ({"type": "route", "route": "light_rail"}, "commuter"),
    ({"type": "route", "route": "monorail"}, "commuter"),
    ({"type": "route", "route": "train", "service": "commuter"}, "commuter"),
    ({"type": "route", "route": "train", "service": "regional"}, "commuter"),
    ({"type": "route", "route": "train", "service": "high_speed"}, "intercity"),
    ({"type": "route", "route": "train", "service": "highspeed"}, "intercity"),
    # service 가 없는 route=train 은 간선 여객이 대부분이다 → 통근으로 세지 않는다.
    ({"type": "route", "route": "train"}, "intercity"),
    ({"type": "route", "route": "bus"}, None),
    ({"type": "multipolygon"}, None),
])
def test_route_kind_separates_commuter_from_intercity(tags, expected):
    assert poi_mod.route_kind(tags) == expected


def test_intercity_services_do_not_count_as_lines():
    """KTX 만 서는 역은 통근 노선 1개짜리다 — 환승 가점을 받으면 안 된다(광명역 사례)."""
    routes = {"elements": [
        {"type": "relation", "id": 1,
         "tags": {"type": "route", "route": "subway", "ref": "1"},
         "members": [{"type": "node", "ref": 777, "role": "stop"}]},
        {"type": "relation", "id": 2,
         "tags": {"type": "route", "route": "train", "service": "high_speed",
                  "name": "KTX 경부선"},
         "members": [{"type": "node", "ref": 777, "role": "stop"}]},
        {"type": "relation", "id": 3,
         "tags": {"type": "route", "route": "train", "name": "경부선 무궁화호"},
         "members": [{"type": "node", "ref": 777, "role": "stop"}]},
        {"type": "node", "id": 777, "lat": 37.5001, "lon": 127.0001,
         "tags": {"name": "역삼"}},
    ]}
    [rec] = parse_stations({"elements": [_STATION]}, routes)
    assert rec.attrs["lines"] == ["1"], "간선 여객이 노선 수에 섞이면 안 된다"
    # 정보는 버리지 않는다 — 표시용으로 남긴다.
    assert rec.attrs["intercity"] == ["KTX 경부선", "경부선 무궁화호"]


def test_intercity_key_absent_when_no_express_service():
    """간선 서비스가 없으면 키를 만들지 않는다(빈 배열을 남기지 않는다)."""
    routes = _routes_with_stop_position(stop_lon=127.0004, stop_lat=37.5002,
                                        stop_name="역삼")
    [rec] = parse_stations({"elements": [_STATION]}, routes)
    assert "intercity" not in rec.attrs


def test_repository_does_not_read_intercity_key():
    """`intercity` 는 리포지토리가 읽지 않는 표시용 키다 — 노선 수에 영향이 없어야 한다."""
    import inspect

    from app.repositories import postgis as repo

    source = inspect.getsource(repo.PostgisRepository._fetch_stations)
    assert poi_mod.ATTR_INTERCITY not in source


def test_transfer_station_collects_every_line_once():
    """환승역은 노선을 모두 모으되 중복은 없어야 한다(line_count 가 가점 근거다)."""
    routes = {"elements": [
        {"type": "relation", "id": 1, "tags": {"type": "route", "route": "subway",
                                               "ref": "3"},
         "members": [{"type": "node", "ref": 777, "role": "stop"}]},
        {"type": "relation", "id": 2, "tags": {"type": "route", "route": "subway",
                                               "ref": "9"},
         "members": [{"type": "node", "ref": 778, "role": "stop"}]},
        # 같은 노선의 반대 방향 — 한 번만 세야 한다.
        {"type": "relation", "id": 3, "tags": {"type": "route", "route": "subway",
                                               "ref": "9"},
         "members": [{"type": "node", "ref": 779, "role": "stop"}]},
        {"type": "node", "id": 777, "lat": 37.5001, "lon": 127.0001,
         "tags": {"name": "역삼"}},
        {"type": "node", "id": 778, "lat": 37.5002, "lon": 127.0002,
         "tags": {"name": "역삼"}},
        {"type": "node", "id": 779, "lat": 37.5003, "lon": 127.0003,
         "tags": {"name": "역삼"}},
    ]}
    [rec] = parse_stations({"elements": [_STATION]}, routes)
    assert rec.attrs["lines"] == ["3", "9"]


# ---------------------------------------------------------------------------
# 생활 인프라
# ---------------------------------------------------------------------------


def test_parse_amenities_marks_emergency_room():
    payload = {"elements": [{"type": "node", "id": 2, "lat": 37.5, "lon": 127.0,
                             "tags": {"amenity": "hospital", "name": "A병원",
                                      "emergency": "yes"}}]}
    [rec] = parse_amenities(payload, category=CAT_HOSPITAL)
    assert rec.attrs["has_emergency_room"] is True


def test_parse_amenities_omits_er_key_when_unknown():
    """응급실 태그가 없으면 **키를 만들지 않는다** — '모름'과 '없음'은 다르다."""
    payload = {"elements": [{"type": "node", "id": 3, "lat": 37.5, "lon": 127.0,
                             "tags": {"amenity": "hospital", "name": "B병원"}}]}
    [rec] = parse_amenities(payload, category=CAT_HOSPITAL)
    assert "has_emergency_room" not in rec.attrs


def test_parse_amenities_records_explicit_no_emergency():
    payload = {"elements": [{"type": "node", "id": 4, "lat": 37.5, "lon": 127.0,
                             "tags": {"amenity": "hospital", "name": "C의원",
                                      "emergency": "no"}}]}
    [rec] = parse_amenities(payload, category=CAT_HOSPITAL)
    assert rec.attrs["has_emergency_room"] is False


def test_parse_amenities_uses_way_center_for_parks():
    payload = {"elements": [{"type": "way", "id": 5,
                             "center": {"lat": 37.51, "lon": 127.01},
                             "tags": {"leisure": "park", "name": "근린공원"}}]}
    [rec] = parse_amenities(payload, category=CAT_PARK)
    assert rec.category == CAT_PARK
    assert rec.source_ref == "way/5"
    assert (rec.lon, rec.lat) == (127.01, 37.51)


def test_parse_amenities_skips_way_without_center():
    payload = {"elements": [{"type": "way", "id": 6, "tags": {"shop": "supermarket"}}]}
    assert parse_amenities(payload, category=CAT_MART) == []


# ---------------------------------------------------------------------------
# 유해요소
# ---------------------------------------------------------------------------


def test_parse_hazards_maps_known_kinds():
    payload = {"elements": [
        {"type": "node", "id": 7, "lat": 37.5, "lon": 127.0,
         "tags": {"power": "substation", "name": "변전소"}},
        {"type": "way", "id": 8, "center": {"lat": 37.5, "lon": 127.0},
         "tags": {"man_made": "works", "name": "공장"}},
    ]}
    kinds = [r.attrs["hazard_kind"] for r in parse_hazards(payload)]
    assert kinds == [poi_mod.HAZARD_POWER_LINE, poi_mod.HAZARD_HARMFUL]


def test_parse_hazards_drops_unmapped_features():
    """종류를 모르면 넣지 않는다 — 리포지토리가 어차피 버리고, 근거 없는 감점은 G2 위반."""
    payload = {"elements": [{"type": "node", "id": 9, "lat": 37.5, "lon": 127.0,
                             "tags": {"amenity": "cafe", "name": "카페"}}]}
    assert parse_hazards(payload) == []


# ---------------------------------------------------------------------------
# 도로
# ---------------------------------------------------------------------------


def test_parse_roads_maps_class_and_builds_wkt_in_lon_lat_order():
    payload = {"elements": [{"type": "way", "id": 10,
                             "tags": {"highway": "trunk", "name": "올림픽대로",
                                      "lanes": "8"},
                             "geometry": [{"lat": 37.5, "lon": 127.0},
                                          {"lat": 37.6, "lon": 127.1}]}]}
    [rec] = parse_roads(payload, as_of=dt.date(2026, 7, 26))
    assert rec.road_class == "자동차전용"
    assert rec.lanes == 8
    # WKT 는 '경도 위도' 순서다. 뒤집으면 PostGIS 가 받아 주고도 거리가 통째로 틀린다.
    assert rec.wkt == "LINESTRING(127.0000000 37.5000000,127.1000000 37.6000000)"


def test_parse_roads_skips_minor_roads():
    """이면도로까지 넣으면 모든 단지가 '대로 횡단'이 되어 판정이 무의미해진다."""
    payload = {"elements": [{"type": "way", "id": 11,
                             "tags": {"highway": "residential"},
                             "geometry": [{"lat": 37.5, "lon": 127.0},
                                          {"lat": 37.6, "lon": 127.1}]}]}
    assert parse_roads(payload) == []


def test_parse_roads_skips_degenerate_geometry():
    payload = {"elements": [{"type": "way", "id": 12, "tags": {"highway": "primary"},
                             "geometry": [{"lat": 37.5, "lon": 127.0}]}]}
    assert parse_roads(payload) == []


# ---------------------------------------------------------------------------
# 신설 노선
# ---------------------------------------------------------------------------


def test_parse_transit_plans_maps_status():
    payload = {"elements": [
        {"type": "way", "id": 13, "tags": {"railway": "construction", "name": "GTX-A"},
         "geometry": [{"lat": 37.5, "lon": 127.0}, {"lat": 37.6, "lon": 127.1}]},
        {"type": "way", "id": 14, "tags": {"railway": "proposed", "name": "위례신사선"},
         "geometry": [{"lat": 37.5, "lon": 127.0}, {"lat": 37.6, "lon": 127.1}]},
    ]}
    plans = parse_transit_plans(payload)
    assert [(p.name, p.status) for p in plans] == [("GTX-A", "착공"), ("위례신사선", "계획")]
    # 개통 예정일은 신뢰할 원천이 없어 비워 둔다 — 추정하지 않는다.
    assert all(p.open_expected is None for p in plans)


def test_merge_transit_plans_folds_ways_of_one_line():
    """OSM 은 노선 하나를 여러 way 로 쪼갠다(실측: 신안산선 13개 way).

    접지 않으면 반경 안의 모든 행이 돌아와 같은 호재가 13번 찍히고
    지연 리스크 문구도 13줄이 된다.
    """
    payload = {"elements": [
        {"type": "way", "id": 20, "tags": {"railway": "construction", "name": "신안산선"},
         "geometry": [{"lat": 37.5, "lon": 126.9}, {"lat": 37.51, "lon": 126.91}]},
        {"type": "way", "id": 21, "tags": {"railway": "construction", "name": "신안산선"},
         "geometry": [{"lat": 37.51, "lon": 126.91}, {"lat": 37.52, "lon": 126.92}]},
    ]}
    merged = poi_mod.merge_transit_plans(parse_transit_plans(payload))
    assert len(merged) == 1
    assert merged[0].name == "신안산선"
    assert merged[0].wkt.startswith("MULTILINESTRING((")
    assert merged[0].wkt.count("(") == 3          # MULTILINESTRING + 두 조각
    # 자연키는 way id 가 아니라 노선 단위여야 재분할에도 안정적이다.
    assert merged[0].source_ref == "line:신안산선|착공"


def test_merge_transit_plans_keeps_stages_separate():
    """같은 이름이라도 단계가 다르면 다른 호재다(착공 구간과 계획 구간)."""
    payload = {"elements": [
        {"type": "way", "id": 22, "tags": {"railway": "construction", "name": "A선"},
         "geometry": [{"lat": 37.5, "lon": 126.9}, {"lat": 37.51, "lon": 126.91}]},
        {"type": "way", "id": 23, "tags": {"railway": "proposed", "name": "A선"},
         "geometry": [{"lat": 37.6, "lon": 126.9}, {"lat": 37.61, "lon": 126.91}]},
    ]}
    merged = poi_mod.merge_transit_plans(parse_transit_plans(payload))
    assert sorted(m.status for m in merged) == ["계획", "착공"]


def test_parse_transit_plans_drops_unnamed():
    payload = {"elements": [{"type": "way", "id": 15, "tags": {"railway": "proposed"},
                             "geometry": [{"lat": 37.5, "lon": 127.0},
                                          {"lat": 37.6, "lon": 127.1}]}]}
    assert parse_transit_plans(payload) == []


# ---------------------------------------------------------------------------
# 학교 (NEIS)
# ---------------------------------------------------------------------------

_NEIS = {"schoolInfo": [
    {"head": [{"list_total_count": 2}, {"RESULT": {"CODE": "INFO-000"}}]},
    {"row": [
        {"ATPT_OFCDC_SC_CODE": "B10", "SD_SCHUL_CODE": "7031110",
         "SCHUL_NM": "경기초등학교", "SCHUL_KND_SC_NM": "초등학교",
         "LCTN_SC_NM": "서울특별시", "ORG_RDNMA": "서울특별시 서대문구 경기대로9길 10",
         "FOND_SC_NM": "사립", "ATPT_OFCDC_SC_NM": "서울특별시교육청"},
        {"ATPT_OFCDC_SC_CODE": "B10", "SD_SCHUL_CODE": "7010084",
         "SCHUL_NM": "서울유치원", "SCHUL_KND_SC_NM": "유치원",
         "LCTN_SC_NM": "서울특별시", "ORG_RDNMA": "서울특별시 종로구 어딘가 1"},
    ]},
]}


def test_parse_neis_schools_keeps_only_elementary_middle_high():
    """유치원·특수학교는 학군 근거가 아니다."""
    schools = parse_neis_schools(_NEIS)
    assert [s.name for s in schools] == ["경기초등학교"]
    assert schools[0].level == "초등학교"
    assert schools[0].source_ref == "neis:B10/7031110"


def test_neis_total_count_is_read_for_pagination_check():
    """총건수를 못 읽으면 잘린 수집을 성공으로 기록하게 된다."""
    assert neis_total_count(_NEIS) == 2
    assert neis_total_count({"RESULT": {"CODE": "INFO-200"}}) is None


def test_parse_neis_schools_on_error_response_is_empty():
    assert parse_neis_schools({"RESULT": {"CODE": "ERROR-300"}}) == []


def test_school_to_poi_records_level_and_omits_achievement():
    """학업성취도는 출처·기준연도 없이 넣지 않는다(도메인이 안 쓰고, 있는 척만 된다)."""
    [school] = parse_neis_schools(_NEIS)
    rec = school_to_poi(school, 127.0, 37.5, geom_source="kakao_address")
    assert rec.category == CAT_SCHOOL
    assert rec.attrs["school_level"] == "초등학교"
    assert "achievement_pct" not in rec.attrs
    assert rec.source == poi_mod.SOURCE_NEIS


# ---------------------------------------------------------------------------
# 멱등 · 중복
# ---------------------------------------------------------------------------


def _poi(ref: str, name: str = "X") -> PoiRecord:
    return PoiRecord(category=CAT_SUBWAY, lon=127.0, lat=37.5,
                     source_ref=ref, name=name, attrs={"lines": []})


def test_dedupe_folds_tile_boundary_duplicates():
    """타일을 나눠 받으면 경계 요소가 두 번 온다. DB 에 가기 전에 접어야
    `ON CONFLICT ... affect row a second time` 으로 트랜잭션이 깨지지 않는다."""
    out = dedupe([_poi("node/1"), _poi("node/1"), _poi("node/2")])
    assert [r.source_ref for r in out] == ["node/1", "node/2"]


def test_loader_is_idempotent_across_runs():
    """같은 배치를 두 번 적재해도 행이 늘지 않는다(주 1회 갱신 전제)."""
    loader = InMemoryPoiLoader()
    batch = [_poi("node/1"), _poi("node/2")]

    first = loader.load_pois(batch)
    second = loader.load_pois(batch)

    assert (first.inserted, first.updated) == (2, 0)
    assert (second.inserted, second.updated) == (0, 2)
    assert len(loader.pois) == 2


def test_loader_updates_changed_attributes_in_place():
    loader = InMemoryPoiLoader()
    loader.load_pois([_poi("node/1", name="옛이름")])
    loader.load_pois([_poi("node/1", name="새이름")])
    assert len(loader.pois) == 1
    assert next(iter(loader.pois.values())).name == "새이름"


def test_loader_skips_records_without_natural_key():
    """자연키가 없으면 멱등을 보장할 수 없다 — 적재하지 않고 건너뛴 수를 남긴다."""
    loader = InMemoryPoiLoader()
    result = loader.load_pois([_poi("")])
    assert (result.inserted, result.skipped) == (0, 1)
    assert loader.pois == {}
