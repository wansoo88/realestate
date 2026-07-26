"""입지(F3) 원천 파싱 — POI · 도로선형 · 신설노선 계획.

설계 근거: docs/02-design/erd.md(poi/school_district/road_segment/transit_plan) ·
          app/repositories/postgis.py(location_facts) ·
          app/domain/location/analysis.py(PROXIMITY_BANDS·HAZARD_RADIUS_M)

⚠️ 이 모듈은 **리포지토리와의 데이터 계약**을 지키는 것이 유일한 존재 이유다
--------------------------------------------------------------------------
`postgis.py` 는 poi 를 category 와 **attrs 의 특정 키**로만 읽는다. 키 이름이 하나라도
어긋나면 SQL 은 예외 없이 성공하고 결과만 빈다 — 즉 **조용히 입지 분석이 죽는다**.
그래서 계약을 상수로 못박고(`CAT_*`, `ATTR_*`) 테스트가 리포지토리 쪽 상수와 대조한다.

  category  | 리포지토리가 읽는 attrs 키          | 쓰는 곳
  ----------|--------------------------------------|--------------------------------
  subway    | lines (JSON 배열)                    | StationFact.lines → 환승 가치
  hospital  | has_emergency_room (truthy 문자열)   | PoiFact.has_emergency_room
  mart/park | (없음 — 거리만)                      | PoiFact
  school    | achievement_* · district_as_of       | SchoolFact (학구도 있을 때만)
  hazard    | hazard_kind · detail                 | HazardFact.kind — **없으면 행이 버려진다**
  road      | hazard_kind (없으면 main_road_noise) | 동별 간선도로 근접

순수 함수만 둔다(네트워크·DB 없음). 원천 응답 → 레코드. 적재는 `poi_loader.py`.

원천
----
* OSM(Overpass) — ODbL 1.0. 출처표시 "© OpenStreetMap contributors" 필수.
  공공 오픈API 가 키 발급(사람 단계) 없이는 닫혀 있어 선택했다. 크롤링이 아니라
  **공개 API**이며 재배포 조건은 `config/sources.yaml` 에 적어 둔다.
* NEIS 교육정보 개방 포털(교육부) — 학교 기본정보. 좌표가 없어 주소 지오코딩이 필요하다.
"""
from __future__ import annotations

import datetime as dt
import logging
import re
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass, field
from typing import Any

logger = logging.getLogger("ingest.poi")

# ---------------------------------------------------------------------------
# 계약 상수 — postgis.py 의 _CAT_* / attrs 키와 **같은 값**이어야 한다.
# (tests/test_ingest_poi.py 가 리포지토리 상수와 대조해 못박는다)
# ---------------------------------------------------------------------------

CAT_SUBWAY = "subway"
CAT_SCHOOL = "school"
CAT_MART = "mart"
CAT_HOSPITAL = "hospital"
CAT_PARK = "park"
CAT_HAZARD = "hazard"
CAT_ROAD = "road"

ATTR_LINES = "lines"
#: 고속·간선 여객 서비스(KTX·SRT·무궁화 등). **노선 수에 세지 않는다** —
#: 리포지토리는 이 키를 읽지 않으며, 표시·설명용으로만 남긴다.
ATTR_INTERCITY = "intercity"
ATTR_HAS_ER = "has_emergency_room"
ATTR_HAZARD_KIND = "hazard_kind"
ATTR_DETAIL = "detail"
ATTR_SCHOOL_LEVEL = "school_level"

#: 도메인 HAZARD_RADIUS_M 의 kind 값. 여기 없는 종류를 쓰면 리포지토리가 그 행을 버린다.
HAZARD_MAIN_ROAD = "main_road_noise"
HAZARD_RAILWAY = "railway"
HAZARD_HARMFUL = "harmful_facility"
HAZARD_POWER_LINE = "power_line"

SOURCE_OSM = "osm_overpass"
SOURCE_NEIS = "neis_schoolinfo"

#: OSM highway 등급 → `road_segment.road_class` (001/003 CHECK 제약값).
#: 보조간선(secondary)·일반은 **넣지 않는다** — 통학로 횡단 판정에서 이면도로까지
#: 세면 모든 단지가 '대로 횡단'이 되어 판정이 무의미해진다(postgis._MAIN_ROAD_CLASSES).
ROAD_CLASS_BY_HIGHWAY: dict[str, str] = {
    "motorway": "고속도로",
    "motorway_link": "고속도로",
    "trunk": "자동차전용",
    "trunk_link": "자동차전용",
    "primary": "간선",
    "primary_link": "간선",
}

#: 신설 노선 단계 매핑. OSM 은 계획/공사중을 태그로 구분한다.
#: `proposed` 는 노선안 단계라 도메인에서 신뢰도 0.4 로 묶인다(PLAN_STATUS_CONFIDENCE).
TRANSIT_STATUS_BY_TAG: dict[str, str] = {
    "construction": "착공",
    "proposed": "계획",
}

#: 여객 철도역으로 인정할 태그. 화물역·폐역을 역세권으로 세면 안 된다.
_PASSENGER_TAGS = ("subway", "train", "light_rail", "monorail")

#: 통근 노선으로 셀 route 종류. `attrs['lines']` 에 들어가고 **환승 가점의 근거**가 된다.
_COMMUTER_ROUTES = ("subway", "light_rail", "monorail")
#: route=train 중 통근으로 볼 서비스 등급(광역전철 — 경의·중앙선, 수인·분당선 등).
_COMMUTER_TRAIN_SERVICES = ("commuter", "regional")

#: 고속·간선 여객 서비스. 노선 수에서 **뺀다**.
#:
#: 왜 빼는가 — 역세권 가치에서 '노선 수'는 **통근 선택지**를 뜻한다. OSM 은 KTX·SRT·
#: 무궁화호·ITX-새마을을 각각 별도 route 관계로 두기 때문에 그대로 세면
#: 수원역이 '노선 10개', 서울역이 '노선 11개'가 된다(실측). 그러면
#:   ① 리포트 근거 문구가 "노선 10개"로 나가 사용자를 오도하고,
#:   ② 통근 노선이 1개뿐인 역이 환승 가점(+8)을 받는다.
#: 정보 자체는 버리지 않고 `attrs['intercity']` 로 따로 남긴다.
_INTERCITY_SERVICES = ("high_speed", "highspeed", "long_distance")


# ---------------------------------------------------------------------------
# 레코드
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class PoiRecord:
    """`poi` 한 행. `source_ref` 는 **자연키**다(재실행 멱등의 근거).

    자연키를 원천 ID(`node/123`·`neis:B10/7031110`)로 두는 이유: 이름·좌표는 원천이
    갱신하면 바뀌지만 ID 는 안 바뀐다. 이름+좌표를 키로 쓰면 원천이 좌표를 1m 고치는
    순간 같은 시설이 두 행이 된다.
    """

    category: str
    lon: float
    lat: float
    source_ref: str
    name: str | None = None
    attrs: dict[str, Any] = field(default_factory=dict)
    source: str = SOURCE_OSM


@dataclass(frozen=True)
class RoadRecord:
    """`road_segment` 한 행. geom 은 WKT LINESTRING 으로 넘긴다(적재에서 ST_GeomFromText)."""

    road_class: str
    wkt: str
    source_ref: str
    name: str | None = None
    lanes: int | None = None
    source: str = SOURCE_OSM
    source_url: str | None = None
    as_of: dt.date | None = None


@dataclass(frozen=True)
class TransitPlanRecord:
    """`transit_plan` 한 행. **확정 호재가 아니다** — status 로 신뢰도가 갈린다."""

    name: str
    status: str
    wkt: str
    source_ref: str
    open_expected: dt.date | None = None
    source_url: str | None = None


@dataclass(frozen=True)
class SchoolRecord:
    """NEIS 학교 1건. **좌표가 없다** — 주소 지오코딩 뒤에야 PoiRecord 가 된다."""

    name: str
    level: str                  # 초등학교 | 중학교 | 고등학교
    address: str                # 도로명주소
    sido: str                   # 서울특별시 | 경기도 | 인천광역시
    source_ref: str             # 'neis:{교육청코드}/{학교코드}'
    founded: str | None = None
    office: str | None = None


# ---------------------------------------------------------------------------
# OSM 공통
# ---------------------------------------------------------------------------

def osm_ref(element: Mapping[str, Any]) -> str:
    """OSM 요소 → 'node/123' 형태의 자연키."""
    return f"{element.get('type')}/{element.get('id')}"


def element_point(element: Mapping[str, Any]) -> tuple[float, float] | None:
    """요소의 대표 좌표(lon, lat). 없으면 None — **추정하지 않는다.**

    node 는 lat/lon 을 직접 갖고, way/relation 은 Overpass `out center` 가 붙여 주는
    `center` 를 쓴다. center 를 안 붙이고 받은 way 는 좌표가 없으므로 버린다(빈 좌표를
    0,0 으로 채우면 서아프리카 앞바다에 병원이 생긴다).
    """
    if element.get("lat") is not None and element.get("lon") is not None:
        try:
            return float(element["lon"]), float(element["lat"])
        except (TypeError, ValueError):
            return None
    center = element.get("center") or {}
    try:
        return float(center["lon"]), float(center["lat"])
    except (KeyError, TypeError, ValueError):
        return None


def _name_of(tags: Mapping[str, Any]) -> str | None:
    """표시 이름. 한국어 이름을 우선한다(사용자가 읽는 근거 문구에 그대로 들어간다)."""
    for key in ("name:ko", "name", "official_name"):
        value = str(tags.get(key) or "").strip()
        if value:
            return value
    return None


def _linestring_wkt(element: Mapping[str, Any]) -> str | None:
    """Overpass `out geom` 의 좌표열 → WKT LINESTRING. 2점 미만이면 None.

    좌표 순서는 **경도 위도**다(WKT/EPSG:4326 축순서). 뒤집으면 위도 127도가 되어
    PostGIS 가 받아 주고도 거리 계산이 통째로 틀린다.
    """
    geometry = element.get("geometry") or []
    points: list[str] = []
    for node in geometry:
        try:
            lon, lat = float(node["lon"]), float(node["lat"])
        except (KeyError, TypeError, ValueError):
            continue
        points.append(f"{lon:.7f} {lat:.7f}")
    if len(points) < 2:
        return None
    return "LINESTRING(" + ",".join(points) + ")"


def _int_or_none(value: Any) -> int | None:
    raw = str(value or "").strip()
    match = re.match(r"^\d+", raw)
    return int(match.group()) if match else None


def _elements(payload: Any) -> list[dict[str, Any]]:
    """Overpass 응답 → elements. 모양이 다르면 조용히 빈 목록(호출부가 0건을 실패로 본다)."""
    if isinstance(payload, Mapping):
        items = payload.get("elements")
        if isinstance(items, list):
            return [e for e in items if isinstance(e, Mapping)]
    return []


# ---------------------------------------------------------------------------
# 지하철·철도역 (category=subway)
# ---------------------------------------------------------------------------

#: 노선명에서 방향·행선 꼬리를 떼어 중복을 없앤다.
#: OSM 은 상·하행을 별도 relation 으로 두는 경우가 많아('2호선: 시청 → 을지로입구')
#: 그대로 세면 환승역이 아닌데 line_count 가 2가 되어 +8점이 붙는다.
_LINE_TAIL = re.compile(r"\s*[:(].*$")


def normalize_line_name(raw: str) -> str:
    """노선 표시명 정규화. 방향 꼬리를 떼고 공백을 줄인다."""
    name = _LINE_TAIL.sub("", str(raw or "")).strip()
    return re.sub(r"\s+", " ", name)


#: 정차 지점(stop_position)이 역 노드에서 떨어져 있을 수 있는 거리.
#: 이름이 같으면 넉넉히, 이름이 없으면 아주 가까울 때만 인정한다.
#: 대형 환승역(고속터미널·왕십리)은 승강장이 역 표시점에서 300m 넘게 벌어지기도 한다.
STOP_MATCH_NAMED_M = 450.0
STOP_MATCH_ANON_M = 150.0


def route_kind(tags: Mapping[str, Any]) -> str | None:
    """route 관계 → 'commuter' | 'intercity' | None(노선 아님).

    통근 노선만 `lines` 로 세고 고속·간선은 `intercity` 로 분리한다(위 상수 주석).
    """
    if str(tags.get("type") or "") != "route":
        return None
    route = str(tags.get("route") or "")
    service = str(tags.get("service") or "").strip().lower()
    if route in _COMMUTER_ROUTES:
        # 드물게 route=subway 에 service=commuter 가 붙는다 — 그래도 통근이다.
        return "commuter"
    if route != "train":
        return None
    if service in _COMMUTER_TRAIN_SERVICES:
        return "commuter"
    if service in _INTERCITY_SERVICES:
        return "intercity"
    # service 가 없는 route=train 은 KTX·무궁화·ITX-새마을 같은 간선 여객이 대부분이다
    # (실측 29건: '경부선 무궁화호', 'KTX 호남선' 등). 통근으로 세지 않는다 —
    # 모르는 것을 통근으로 세면 없는 환승 가치를 만들어 낸다.
    return "intercity"


def station_lines(routes_payload: Any, *, kind: str = "commuter") -> dict[str, list[str]]:
    """route relation 응답 → {멤버 node osm_ref: [노선명...]}.

    ⚠️ 여기서 나오는 키는 **역 노드가 아니라 정차지점(stop_position) 노드**인 경우가
       대부분이다. OSM 대중교통 스키마(PTv2)에서 route 관계의 멤버는
       `public_transport=stop_position` 이고, `railway=station` 노드는 그 관계에
       들어가지 않는다 — 실측(수도권 62개 노선, 강남 일대): route 멤버 1,940개 중
       station 노드와 **ID 가 일치한 건수 0**.
       그래서 이 결과를 그대로 역에 붙이면 노선이 전부 빈 배열이 된다.
       역과 잇는 일은 `assign_lines` 가 좌표·이름으로 한다.
    """
    out: dict[str, list[str]] = {}
    for rel in _elements(routes_payload):
        if rel.get("type") != "relation":
            continue
        tags = rel.get("tags") or {}
        if route_kind(tags) != kind:
            continue
        label = normalize_line_name(
            tags.get("ref") or tags.get("name:ko") or tags.get("name") or "")
        if not label:
            continue
        for member in rel.get("members") or []:
            if not isinstance(member, Mapping) or member.get("type") != "node":
                continue
            # 정거장 역할만 센다. 선로 통과 노드까지 세면 노선 수가 부풀려진다.
            role = str(member.get("role") or "")
            if role and not role.startswith("stop") and not role.startswith("platform"):
                continue
            ref = f"node/{member.get('ref')}"
            bucket = out.setdefault(ref, [])
            if label not in bucket:
                bucket.append(label)
    return out


def _member_nodes(routes_payload: Any) -> dict[str, tuple[float, float, str]]:
    """route 응답에 함께 실려 온 멤버 노드 → {osm_ref: (lon, lat, 이름)}.

    Overpass 질의가 `node(r.rt);` 로 멤버 노드를 같이 내려 주기 때문에 좌표가 있다.
    """
    out: dict[str, tuple[float, float, str]] = {}
    for el in _elements(routes_payload):
        if el.get("type") != "node":
            continue
        point = element_point(el)
        if point is None:
            continue
        tags = el.get("tags") or {}
        out[osm_ref(el)] = (point[0], point[1], _name_of(tags) or "")
    return out


def assign_lines(stations: Sequence[PoiRecord], routes_payload: Any) -> None:
    """역 레코드의 `attrs['lines']` 를 **제자리에서** 채운다.

    잇는 규칙 (엄격한 쪽부터)
      ① route 멤버가 역 노드 자체인 경우 — ID 직접 일치(일부 네트워크는 이렇게 돼 있다).
      ② 정차지점 이름이 역 이름과 같고 450m 이내.
      ③ 이름이 없는 정차지점이 150m 이내.

    ②의 이름 대조가 핵심이다. 거리만으로 이으면 환승역이 아닌 인접역(예: 종로3가와
    을지로3가는 약 500m)에 남의 노선이 붙어 **환승역 가점(+8)** 이 잘못 들어간다.
    """
    commuter = station_lines(routes_payload, kind="commuter")
    intercity = station_lines(routes_payload, kind="intercity")
    if not commuter and not intercity:
        return
    members = _member_nodes(routes_payload)

    def _labels_for(station: PoiRecord, by_ref: dict[str, list[str]]) -> list[str]:
        found: list[str] = []

        def _add(labels: Iterable[str]) -> None:
            for label in labels:
                if label not in found:
                    found.append(label)

        # ① 직접 일치
        _add(by_ref.get(station.source_ref, []))

        # ②③ 정차지점 경유
        station_key = _squeeze_name(station.name or "")
        for ref, labels in by_ref.items():
            point = members.get(ref)
            if point is None:
                continue
            lon, lat, name = point
            distance = _haversine_m(station.lon, station.lat, lon, lat)
            stop_key = _squeeze_name(name)
            if stop_key and station_key and stop_key == station_key:
                if distance <= STOP_MATCH_NAMED_M:
                    _add(labels)
            elif not stop_key and distance <= STOP_MATCH_ANON_M:
                _add(labels)
        return found

    for station in stations:
        station.attrs[ATTR_LINES] = _labels_for(station, commuter)
        # 고속·간선은 노선 수에 넣지 않되 버리지도 않는다(표시·설명용).
        express = _labels_for(station, intercity)
        if express:
            station.attrs[ATTR_INTERCITY] = express


#: 역명 비교용 축약 — '역' 접미사와 공백·기호 차이를 흡수한다.
#: '고속터미널' vs '고속터미널역', '서울역' vs '서울' 을 같게 본다.
_NON_NAME_CHARS = re.compile(r"[^0-9A-Za-z가-힣]")


def _squeeze_name(name: str) -> str:
    key = _NON_NAME_CHARS.sub("", str(name or ""))
    if len(key) > 1 and key.endswith("역"):
        key = key[:-1]
    return key


def _haversine_m(lon1: float, lat1: float, lon2: float, lat2: float) -> float:
    """두 좌표 사이 거리(m). 지오코딩 계층과 같은 계산을 쓴다(중복 정의 금지)."""
    from app.ingest.geocode import haversine_m

    return haversine_m(lon1, lat1, lon2, lat2)


def is_passenger_station(tags: Mapping[str, Any]) -> bool:
    """여객 전철역인가. 화물역·폐역·공사중 역은 역세권 근거가 될 수 없다."""
    if str(tags.get("railway") or "") not in ("station", "halt"):
        return False
    for bad in ("disused", "abandoned", "razed", "construction", "proposed"):
        if str(tags.get(bad) or "").strip() or str(tags.get("railway") or "") == bad:
            return False
    if str(tags.get("usage") or "") == "freight":
        return False
    return any(str(tags.get(k) or "").lower() == "yes" for k in _PASSENGER_TAGS)


def parse_stations(payload: Any, routes_payload: Any = None) -> list[PoiRecord]:
    """역 노드 → PoiRecord(category=subway). 노선은 relation 에서 붙인다."""
    out: list[PoiRecord] = []
    for el in _elements(payload):
        tags = el.get("tags") or {}
        if not is_passenger_station(tags):
            continue
        point = element_point(el)
        name = _name_of(tags)
        if point is None or not name:
            # 이름 없는 역은 근거 문구('최근접 역 … 250m')를 만들 수 없다.
            continue
        attrs: dict[str, Any] = {ATTR_LINES: []}
        if tags.get("operator"):
            attrs["operator"] = str(tags["operator"])
        if tags.get("network"):
            attrs["network"] = str(tags["network"])
        out.append(PoiRecord(category=CAT_SUBWAY, lon=point[0], lat=point[1],
                             source_ref=osm_ref(el), name=name, attrs=attrs))
    if routes_payload is not None:
        assign_lines(out, routes_payload)
    return out


# ---------------------------------------------------------------------------
# 생활 인프라 (mart · park · hospital)
# ---------------------------------------------------------------------------

#: 응급실 보유로 볼 태그. OSM 은 `emergency=yes` 로 표기한다.
_ER_TRUTHY = ("yes", "true", "1")


def parse_amenities(payload: Any, *, category: str) -> list[PoiRecord]:
    """마트·공원·병원 요소 → PoiRecord.

    병원만 `has_emergency_room` 을 붙인다 — 리포지토리가 '가장 가까운 병원'과
    '가장 가까운 응급실 병원'을 **따로** 묻기 때문이다(_POIS_SQL 의 h / er).
    ⚠️ 응급실 여부가 태그로 없으면 **false 로 단정하지 않고 키를 비운다.**
       비어 있으면 SQL 의 truthy 검사가 자연히 거짓이 되어 '응급실 아님'으로 처리되는데,
       그건 '응급실 없음'이 아니라 '모름'이다 — 그래서 attrs 에 근거(er_source)를 남긴다.
    """
    out: list[PoiRecord] = []
    for el in _elements(payload):
        tags = el.get("tags") or {}
        point = element_point(el)
        if point is None:
            continue
        name = _name_of(tags)
        attrs: dict[str, Any] = {}
        if category == CAT_HOSPITAL:
            raw = str(tags.get("emergency") or "").strip().lower()
            if raw in _ER_TRUTHY:
                attrs[ATTR_HAS_ER] = True
                attrs["er_source"] = "osm:emergency"
            elif raw in ("no", "false", "0"):
                attrs[ATTR_HAS_ER] = False
                attrs["er_source"] = "osm:emergency"
            # 태그가 없으면 키 자체를 안 만든다(모름 ≠ 없음).
        if category == CAT_MART and tags.get("shop"):
            attrs["shop"] = str(tags["shop"])
        out.append(PoiRecord(category=category, lon=point[0], lat=point[1],
                             source_ref=osm_ref(el), name=name, attrs=attrs))
    return out


# ---------------------------------------------------------------------------
# 유해요소 (category=hazard)
# ---------------------------------------------------------------------------

def _hazard_kind_for(tags: Mapping[str, Any]) -> str | None:
    """OSM 태그 → 도메인 hazard kind. 확실한 것만 매핑하고 나머지는 None.

    ⚠️ 종류를 모르는 행은 리포지토리가 버리므로(postgis `_fetch_hazards`) 여기서
       억지로 이름을 붙이지 않는다. 근거 없는 감점은 '왜 깎였는지' 설명이 안 된다(G2).
    """
    if str(tags.get("power") or "") in ("substation", "tower", "portal"):
        return HAZARD_POWER_LINE
    if str(tags.get("man_made") or "") == "works":
        return HAZARD_HARMFUL
    if str(tags.get("amenity") or "") in ("waste_transfer_station",):
        return HAZARD_HARMFUL
    if str(tags.get("landuse") or "") == "landfill":
        return HAZARD_HARMFUL
    return None


def parse_hazards(payload: Any) -> list[PoiRecord]:
    """유해요소 점 → PoiRecord(category=hazard, attrs.hazard_kind)."""
    out: list[PoiRecord] = []
    for el in _elements(payload):
        tags = el.get("tags") or {}
        kind = _hazard_kind_for(tags)
        point = element_point(el)
        if kind is None or point is None:
            continue
        name = _name_of(tags)
        attrs = {ATTR_HAZARD_KIND: kind,
                 ATTR_DETAIL: name or kind}
        out.append(PoiRecord(category=CAT_HAZARD, lon=point[0], lat=point[1],
                             source_ref=osm_ref(el), name=name, attrs=attrs))
    return out


# ---------------------------------------------------------------------------
# 도로 선형 (road_segment)
# ---------------------------------------------------------------------------

def parse_roads(payload: Any, *, as_of: dt.date | None = None) -> list[RoadRecord]:
    """간선급 도로 way → RoadRecord. 등급 매핑에 없으면 버린다."""
    out: list[RoadRecord] = []
    for el in _elements(payload):
        tags = el.get("tags") or {}
        road_class = ROAD_CLASS_BY_HIGHWAY.get(str(tags.get("highway") or ""))
        if road_class is None:
            continue
        wkt = _linestring_wkt(el)
        if wkt is None:
            continue
        out.append(RoadRecord(
            road_class=road_class,
            wkt=wkt,
            source_ref=osm_ref(el),
            name=_name_of(tags),
            lanes=_int_or_none(tags.get("lanes")),
            source_url="https://www.openstreetmap.org/" + osm_ref(el),
            as_of=as_of,
        ))
    return out


# ---------------------------------------------------------------------------
# 신설 노선 계획 (transit_plan)
# ---------------------------------------------------------------------------

def _plan_status(tags: Mapping[str, Any]) -> str | None:
    railway = str(tags.get("railway") or "")
    return TRANSIT_STATUS_BY_TAG.get(railway)


def _plan_name(tags: Mapping[str, Any]) -> str | None:
    for key in ("name:ko", "name", "construction:name", "proposed:name", "ref"):
        value = str(tags.get(key) or "").strip()
        if value:
            return value
    return None


def parse_transit_plans(payload: Any) -> list[TransitPlanRecord]:
    """공사중·계획 철도 way → TransitPlanRecord.

    이름이 없으면 버린다 — 도메인이 "…은(는) '계획' 단계로 지연될 수 있습니다"라는
    문장을 만들기 때문에 이름 없는 호재는 근거가 되지 못한다.
    개통예정일은 OSM 에 신뢰할 만한 형태로 없어 **비워 둔다**(추정 금지).
    """
    out: list[TransitPlanRecord] = []
    for el in _elements(payload):
        tags = el.get("tags") or {}
        status = _plan_status(tags)
        name = _plan_name(tags)
        wkt = _linestring_wkt(el)
        if status is None or not name or wkt is None:
            continue
        out.append(TransitPlanRecord(
            name=name, status=status, wkt=wkt, source_ref=osm_ref(el),
            open_expected=None,
            source_url="https://www.openstreetmap.org/" + osm_ref(el),
        ))
    return out


# ---------------------------------------------------------------------------
# 학교 (NEIS 교육정보 개방 포털)
# ---------------------------------------------------------------------------

#: NEIS 가 주는 학교급 중 우리가 쓰는 것. 유치원·특수학교는 학군 근거가 아니다.
SCHOOL_LEVELS = ("초등학교", "중학교", "고등학교")


def parse_neis_schools(payload: Any) -> list[SchoolRecord]:
    """NEIS `schoolInfo` 응답 → SchoolRecord.

    NEIS 는 결과를 `{"schoolInfo": [{"head": [...]}, {"row": [...]}]}` 로 준다.
    오류일 때는 `{"RESULT": {...}}` 만 오므로 그때는 빈 목록이다(호출부가 실패로 본다).
    """
    rows: list[Mapping[str, Any]] = []
    if isinstance(payload, Mapping):
        for block in payload.get("schoolInfo") or []:
            if isinstance(block, Mapping) and isinstance(block.get("row"), list):
                rows.extend(r for r in block["row"] if isinstance(r, Mapping))

    out: list[SchoolRecord] = []
    for row in rows:
        level = str(row.get("SCHUL_KND_SC_NM") or "").strip()
        name = str(row.get("SCHUL_NM") or "").strip()
        address = str(row.get("ORG_RDNMA") or "").strip()
        office_code = str(row.get("ATPT_OFCDC_SC_CODE") or "").strip()
        school_code = str(row.get("SD_SCHUL_CODE") or "").strip()
        if level not in SCHOOL_LEVELS or not name or not address or not school_code:
            continue
        out.append(SchoolRecord(
            name=name,
            level=level,
            address=address,
            sido=str(row.get("LCTN_SC_NM") or "").strip(),
            source_ref=f"neis:{office_code}/{school_code}",
            founded=str(row.get("FOND_SC_NM") or "").strip() or None,
            office=str(row.get("ATPT_OFCDC_SC_NM") or "").strip() or None,
        ))
    return out


def neis_total_count(payload: Any) -> int | None:
    """응답 head 의 총건수. 페이지네이션 검증용 — 못 읽으면 None."""
    if not isinstance(payload, Mapping):
        return None
    for block in payload.get("schoolInfo") or []:
        if not isinstance(block, Mapping):
            continue
        for head in block.get("head") or []:
            if isinstance(head, Mapping) and "list_total_count" in head:
                try:
                    return int(head["list_total_count"])
                except (TypeError, ValueError):
                    return None
    return None


def school_to_poi(school: SchoolRecord, lon: float, lat: float, *,
                  geom_source: str) -> PoiRecord:
    """좌표가 확보된 학교 → PoiRecord(category=school).

    학업성취도는 **넣지 않는다** — 출처·기준연도 없이 넣으면 도메인이 쓰지 않고
    (analysis.assess_school), 있는 척만 하게 된다.
    """
    return PoiRecord(
        category=CAT_SCHOOL, lon=lon, lat=lat,
        source_ref=school.source_ref, name=school.name,
        attrs={
            ATTR_SCHOOL_LEVEL: school.level,
            "address": school.address,
            "founded": school.founded,
            "geom_source": geom_source,
        },
        source=SOURCE_NEIS,
    )


# ---------------------------------------------------------------------------
# 중복 제거
# ---------------------------------------------------------------------------

def dedupe(records: Sequence[PoiRecord]) -> list[PoiRecord]:
    """같은 자연키가 두 번 오면 **처음 것만** 남긴다.

    Overpass 응답은 타일을 나눠 받으면 경계에서 같은 요소가 두 번 온다. DB 의 유니크
    제약(011)이 최종 방어지만, 배치 안에서 미리 접어야 `ON CONFLICT` 가 같은 명령에서
    같은 행을 두 번 건드려 터지는 것(`affect row a second time`)을 막을 수 있다.
    """
    seen: set[tuple[str, str]] = set()
    out: list[PoiRecord] = []
    for rec in records:
        key = (rec.source, rec.source_ref)
        if key in seen:
            continue
        seen.add(key)
        out.append(rec)
    return out


def merge_transit_plans(
    records: Sequence[TransitPlanRecord],
) -> list[TransitPlanRecord]:
    """같은 (이름, 단계)의 way 들을 **MULTILINESTRING 한 행**으로 접는다.

    왜 접는가
    ---------
    OSM 은 노선 하나를 여러 way 로 쪼개 둔다(실측: 123개 way → 고유 노선 34개,
    신안산선 하나가 13개 way). 그대로 적재하면 `_PLANS_SQL` 이 반경 안의 **모든 행**을
    돌려주므로 리포트에 "신안산선(착공)"이 13번 찍히고, 도메인이 착공 전 호재마다 다는
    지연 리스크 문구도 13줄이 된다. 근거가 13배로 부풀어 보이는 건 G2 위반에 가깝다.

    자연키는 way id 가 아니라 `line:{이름}|{단계}` 가 된다 — 노선이 재분할돼도
    같은 행으로 수렴하므로 오히려 way id 보다 안정적이다.
    """
    groups: dict[tuple[str, str], list[TransitPlanRecord]] = {}
    for rec in records:
        groups.setdefault((rec.name, rec.status), []).append(rec)

    out: list[TransitPlanRecord] = []
    for (name, status), items in groups.items():
        parts: list[str] = []
        for item in items:
            inner = item.wkt.strip()
            if inner.upper().startswith("LINESTRING(") and inner.endswith(")"):
                parts.append("(" + inner[len("LINESTRING("):-1] + ")")
        if not parts:
            continue
        wkt = "MULTILINESTRING(" + ",".join(parts) + ")"
        first = items[0]
        out.append(TransitPlanRecord(
            name=name, status=status, wkt=wkt,
            source_ref=f"line:{name}|{status}",
            open_expected=first.open_expected,
            # 대표 way 의 링크를 남긴다 — 노선 전체를 가리키는 URL 은 OSM 에 없다.
            source_url=first.source_url,
        ))
    return out


def dedupe_keyed(records: Sequence[Any]) -> list[Any]:
    """`source`/`source_ref` 를 가진 임의 레코드의 중복 제거(도로·노선계획용)."""
    seen: set[tuple[str, str]] = set()
    out: list[Any] = []
    for rec in records:
        key = (getattr(rec, "source", SOURCE_OSM), rec.source_ref)
        if key in seen:
            continue
        seen.add(key)
        out.append(rec)
    return out


def count_by_category(records: Iterable[PoiRecord]) -> dict[str, int]:
    counts: dict[str, int] = {}
    for rec in records:
        counts[rec.category] = counts.get(rec.category, 0) + 1
    return counts
