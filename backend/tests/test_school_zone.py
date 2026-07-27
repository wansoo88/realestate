"""학구도 파싱·적재 테스트 (app/ingest/school_zone.py · scripts/load_school_zone.py).

여기서 고정하는 것은 "돌아간다"가 아니라 **틀리면 조용히 틀리는 것들**이다.
학구 배정은 리포트에 단정형으로 나가는 주장이라, 어긋나도 예외가 안 나는 결함이 제일 위험하다.

고정 대상 (전부 변이 테스트로 확인했다 — 방어를 빼면 실제로 빨개진다)
  1. shx 오프셋·길이의 **16비트 워드 → 바이트** 환산 (×2 빠뜨리면 2번째부터 어긋남)
  2. 링 방향에 따른 **구멍(hole) 분리** (안 하면 도넛 학구의 구멍이 외곽으로 승격)
  3. **학교급 필터** (급이 섞이면 최근접 중학교가 '배정 초등학교'가 된다)
  4. 자연키가 (학구ID, **학교ID**) — 공동학구가 있어 학구ID 단독은 키가 못 된다
  5. 적재 SQL 의 자기교차 보정·좌표변환·멱등 구문
  6. **초등 통학구역과 중·고 학교군은 모델이 다르다**(§6) — 같게 만들면 거짓말이 된다
"""
from __future__ import annotations

import importlib.util
import io
import struct
import sys
import zipfile
from pathlib import Path

import pytest

from app.ingest.school_zone import (
    CAPITAL_AREA_SD,
    ELEMENTARY,
    HIGH,
    MIDDLE,
    SchoolLink,
    SchoolLocation,
    build_records,
    build_zone_records,
    district_source_ref,
    parse_link_csv,
    parse_school_location_csv,
    parse_zone_shapefile,
    school_source_ref,
    shp_polygon_to_wkb,
    zone_source_ref,
)

BACKEND_DIR = Path(__file__).resolve().parents[1]
SCRIPTS_DIR = BACKEND_DIR / "scripts"


# ---------------------------------------------------------------------------
# 합성 shapefile — 원천 없이 파서를 검증한다
# ---------------------------------------------------------------------------

def _polygon_record(rings: list[list[tuple[float, float]]]) -> bytes:
    """shapefile 폴리곤 레코드 **본문**(shape type 부터)."""
    xs = [x for ring in rings for x, _ in ring]
    ys = [y for ring in rings for _, y in ring]
    parts = []
    offset = 0
    for ring in rings:
        parts.append(offset)
        offset += len(ring)
    body = struct.pack("<i", 5)
    body += struct.pack("<4d", min(xs), min(ys), max(xs), max(ys))
    body += struct.pack("<ii", len(rings), sum(len(r) for r in rings))
    body += struct.pack(f"<{len(parts)}i", *parts)
    for ring in rings:
        for x, y in ring:
            body += struct.pack("<dd", x, y)
    return body


def _dbf(rows: list[dict[str, str]], columns: list[tuple[str, int]]) -> bytes:
    header_len = 32 + 32 * len(columns) + 1
    record_len = 1 + sum(length for _, length in columns)
    out = bytearray()
    out += struct.pack("<B3B", 3, 26, 1, 1)
    out += struct.pack("<I", len(rows))
    out += struct.pack("<HH", header_len, record_len)
    out += b"\0" * 20
    for name, length in columns:
        out += name.encode("cp949").ljust(11, b"\0")[:11]
        out += b"C"
        out += b"\0" * 4
        out += bytes([length, 0])
        out += b"\0" * 14
    out += b"\x0D"
    for row in rows:
        out += b" "
        for name, length in columns:
            out += row.get(name, "").encode("cp949").ljust(length, b" ")[:length]
    return bytes(out)


def _shapefile_zip(records: list[bytes], attributes: list[dict[str, str]]) -> bytes:
    """(shp, shx, dbf, cpg) 를 담은 zip. shx 는 **워드 단위**로 적는다(실제 규격)."""
    shp = bytearray(b"\0" * 100)
    shx = bytearray(b"\0" * 100)
    for i, body in enumerate(records, start=1):
        offset_bytes = len(shp)
        shp += struct.pack(">ii", i, len(body) // 2)      # 레코드 헤더(번호, 워드길이)
        shp += body
        shx += struct.pack(">ii", offset_bytes // 2, len(body) // 2)

    # 실제 배포본과 같은 컬럼 집합. EDU_NM(교육지원청)이 필수인 이유는
    # 고등학교 학교군 이름이 '1학교군'처럼 교육지원청 안에서만 유일해서다.
    columns = [("OBJECTID", 10), ("HAKGUDO_ID", 10), ("HAKGUDO_NM", 40),
               ("HAKGUDO_GB", 1), ("SD_CD", 2), ("SGG_CD", 3), ("BASE_DT", 10),
               ("EDU_NM", 30)]
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as zf:
        zf.writestr("zone.shp", bytes(shp))
        zf.writestr("zone.shx", bytes(shx))
        zf.writestr("zone.dbf", _dbf(attributes, columns))
        zf.writestr("zone.cpg", "EUC-KR")
    return buf.getvalue()


SQUARE = [(0.0, 0.0), (0.0, 10.0), (10.0, 10.0), (10.0, 0.0), (0.0, 0.0)]      # 시계방향
HOLE = [(3.0, 3.0), (7.0, 3.0), (7.0, 7.0), (3.0, 7.0), (3.0, 3.0)]           # 반시계
FAR_SQUARE = [(100.0, 100.0), (100.0, 110.0), (110.0, 110.0),
              (110.0, 100.0), (100.0, 100.0)]


def _wkb_parts(wkb: bytes) -> list[list[int]]:
    """WKB MultiPolygon → [[링 정점수, ...], ...]. 구조 검증용 최소 파서."""
    assert wkb[0] == 1, "리틀엔디언이어야 한다"
    kind, = struct.unpack("<I", wkb[1:5])
    assert kind == 6, f"MultiPolygon(6) 이어야 하는데 {kind}"
    count, = struct.unpack("<I", wkb[5:9])
    pos = 9
    out = []
    for _ in range(count):
        assert wkb[pos] == 1
        inner, = struct.unpack("<I", wkb[pos + 1:pos + 5])
        assert inner == 3, f"Polygon(3) 이어야 하는데 {inner}"
        ring_count, = struct.unpack("<I", wkb[pos + 5:pos + 9])
        pos += 9
        rings = []
        for _ in range(ring_count):
            n, = struct.unpack("<I", wkb[pos:pos + 4])
            rings.append(n)
            pos += 4 + 16 * n
        out.append(rings)
    return out


# ---------------------------------------------------------------------------
# 1. WKB 변환 · 구멍 분리
# ---------------------------------------------------------------------------

def test_단일_폴리곤이_MultiPolygon_WKB_로_나온다():
    """school_district.geom 이 geometry(MultiPolygon,4326) 이라 단일도 Multi 여야 한다."""
    wkb = shp_polygon_to_wkb(_polygon_record([SQUARE]))
    assert _wkb_parts(wkb) == [[5]]


def test_구멍은_외곽으로_승격되지_않고_같은_폴리곤의_내부링이_된다():
    """★ 변이 가드 — 링 방향 분리를 빼면 [[5],[5]] 가 되어 구멍이 '또 하나의 학구'가 된다.

    그러면 도넛 학구의 구멍 안에 있는 단지가 학구에 **포함된 것으로** 판정된다.
    """
    wkb = shp_polygon_to_wkb(_polygon_record([SQUARE, HOLE]))
    assert _wkb_parts(wkb) == [[5, 5]], "구멍이 외곽 폴리곤으로 승격됐다"


def test_외곽이_둘이면_폴리곤도_둘이다():
    wkb = shp_polygon_to_wkb(_polygon_record([SQUARE, FAR_SQUARE]))
    assert _wkb_parts(wkb) == [[5], [5]]


def test_폴리곤이_아닌_셰이프는_건너뛴다():
    assert shp_polygon_to_wkb(struct.pack("<i", 1) + b"\0" * 16) is None   # Point


# ---------------------------------------------------------------------------
# 2. shx 워드→바이트 환산 (×2)
# ---------------------------------------------------------------------------

def test_두번째_레코드도_정확히_읽힌다_shx_는_워드단위다():
    """★ 변이 가드 — `_shx_offsets` 의 ×2 를 빼면 이 테스트가 깨진다.

    첫 레코드는 오프셋이 100(워드)≈200(바이트)라 우연히 읽히는 경우가 있어 **예외가
    안 난다.** 두 번째부터 조용히 어긋나므로 레코드를 2개 이상 두고 확인해야 한다.
    """
    zip_bytes = _shapefile_zip(
        [_polygon_record([SQUARE]), _polygon_record([FAR_SQUARE, HOLE])],
        [{"HAKGUDO_ID": "Z1", "HAKGUDO_NM": "가초통학구역",
          "SD_CD": "11", "BASE_DT": "2026-03-20"},
         {"HAKGUDO_ID": "Z2", "HAKGUDO_NM": "나초통학구역",
          "SD_CD": "41", "BASE_DT": "2026-03-20"}],
    )
    zones = parse_zone_shapefile(zip_bytes)
    assert [z.zone_id for z in zones] == ["Z1", "Z2"]
    assert [z.zone_name for z in zones] == ["가초통학구역", "나초통학구역"]
    # 두 번째 레코드의 **구조**까지 맞아야 한다(오프셋이 밀리면 여기서 깨진다).
    assert _wkb_parts(zones[0].wkb) == [[5]]
    assert _wkb_parts(zones[1].wkb) == [[5, 5]]


def test_수도권_시도코드로_거른다():
    zip_bytes = _shapefile_zip(
        [_polygon_record([SQUARE]), _polygon_record([FAR_SQUARE])],
        [{"HAKGUDO_ID": "Z1", "HAKGUDO_NM": "서울", "SD_CD": "11", "BASE_DT": "2026-03-20"},
         {"HAKGUDO_ID": "Z2", "HAKGUDO_NM": "부산", "SD_CD": "26", "BASE_DT": "2026-03-20"}],
    )
    assert [z.zone_id for z in parse_zone_shapefile(zip_bytes)] == ["Z1"]
    assert len(parse_zone_shapefile(zip_bytes, sido_codes=None)) == 2
    assert "26" not in CAPITAL_AREA_SD and CAPITAL_AREA_SD == {"11", "41", "28"}


def test_배포_형식이_바뀌면_추측하지_않고_멈춘다():
    columns = [("OBJECTID", 10), ("HAKGUDO_ID", 10)]        # 필수 컬럼 누락
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as zf:
        zf.writestr("zone.shp", b"\0" * 100)
        zf.writestr("zone.shx", b"\0" * 100)
        zf.writestr("zone.dbf", _dbf([{"HAKGUDO_ID": "Z1"}], columns))
    with pytest.raises(ValueError, match="기대한 컬럼"):
        parse_zone_shapefile(buf.getvalue())


def test_묶음에_shx_가_없으면_멈춘다():
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as zf:
        zf.writestr("zone.shp", b"\0" * 100)
        zf.writestr("zone.dbf", b"\0" * 100)
    with pytest.raises(ValueError, match="shx"):
        parse_zone_shapefile(buf.getvalue())


# ---------------------------------------------------------------------------
# 3. 초등학교 전용 필터 — 중·고 혼입 방어
# ---------------------------------------------------------------------------

_LINK_CSV = (
    "학구ID,학교ID,학교명,학교급구분,시도교육청코드,시도교육청명,"
    "교육지원청코드,교육지원청명,데이터기준일자\r\n"
    "Z1,B1,가초등학교,초등학교,7010000,서울특별시교육청,7041000,남부교육지원청,2026-03-20\r\n"
    "Z1,B2,나초등학교,초등학교,7010000,서울특별시교육청,7041000,남부교육지원청,2026-03-20\r\n"
    "Z9,B9,다중학교,중학교,7010000,서울특별시교육청,7041000,남부교육지원청,2026-03-20\r\n"
    "Z8,B8,라고등학교,고등학교,7010000,서울특별시교육청,7041000,남부교육지원청,2026-03-20\r\n"
).encode("cp949")


def test_연계정보는_기본적으로_초등학교만_남긴다():
    """★ 변이 가드 — level 필터를 없애면 중·고가 섞이고, `_SCHOOL_SQL` 이 학교급을
    구분하지 않으므로 **가장 가까운 중학교가 '배정 초등학교'로 보고된다.**
    """
    links = parse_link_csv(_LINK_CSV)
    assert {link.level for link in links} == {ELEMENTARY}
    assert [link.school_id for link in links] == ["B1", "B2"]


def test_연계정보_CP949_와_컬럼검사():
    links = parse_link_csv(_LINK_CSV)
    assert links[0].school_name == "가초등학교"
    assert links[0].office == "남부교육지원청"
    with pytest.raises(ValueError, match="기대한 컬럼"):
        parse_link_csv("학구ID,학교ID\r\nZ1,B1\r\n가나다\r\n".encode("cp949"))


_LOCATION_CSV = (
    "학교ID,학교명,학교급구분,소재지지번주소,소재지도로명주소,위도,경도,데이터기준일자\r\n"
    "B1,가초등학교,초등학교,서울 강남구 1,테헤란로 1,37.5,127.0,2026-03-20\r\n"
    "B2,나초등학교,초등학교,서울 강남구 2,테헤란로 2,,,2026-03-20\r\n"
    "B9,다중학교,중학교,서울 강남구 9,테헤란로 9,37.6,127.1,2026-03-20\r\n"
).encode("utf-8-sig")


def test_좌표가_없는_학교는_담지_않는다():
    """좌표를 지어내지 않는다. 없으면 그 학교는 배정 근거로 쓸 수 없다."""
    locations = parse_school_location_csv(_LOCATION_CSV)
    assert set(locations) == {"B1"}          # B2 좌표없음 · B9 중학교
    assert locations["B1"].lat == 37.5
    assert locations["B1"].address == "테헤란로 1"


# ---------------------------------------------------------------------------
# 4. 결합 · 자연키
# ---------------------------------------------------------------------------

def _zone(zone_id: str, wkb: bytes | None = None):
    from app.ingest.school_zone import ZonePolygon

    return ZonePolygon(zone_id=zone_id, zone_name=f"{zone_id}통학구역", sd_cd="11",
                       base_dt="2026-03-20",
                       wkb=wkb or shp_polygon_to_wkb(_polygon_record([SQUARE])))


def test_공동학구는_학교수만큼_행이_생기고_지오메트리를_공유한다():
    zones = [_zone("Z1")]
    links = [SchoolLink("Z1", "B1", "가초등학교", ELEMENTARY),
             SchoolLink("Z1", "B2", "나초등학교", ELEMENTARY)]
    locations = {
        "B1": SchoolLocation("B1", "가초등학교", ELEMENTARY, 37.5, 127.0),
        "B2": SchoolLocation("B2", "나초등학교", ELEMENTARY, 37.6, 127.1),
    }
    records, report = build_records(zones, links, locations)
    assert len(records) == 2
    assert {r.wkb for r in records} == {zones[0].wkb}
    assert len({r.source_ref for r in records}) == 2, "자연키가 충돌하면 한 행만 남는다"
    assert report.records == 2


def test_자연키는_학구ID_단독이_아니라_학교ID_까지_포함한다():
    """★ 변이 가드 — 학구ID 단독을 키로 쓰면 공동학구의 두 번째 학교가 첫 번째를
    덮어써서 **배정 학교가 조용히 하나 사라진다.**
    """
    assert district_source_ref("Z1", "B1") != district_source_ref("Z1", "B2")
    assert "B1" in district_source_ref("Z1", "B1")
    assert school_source_ref("B1") == "kesi:B1"
    # NEIS 경로('neis:...')와 접두사로 구분돼 poi 자연키가 충돌하지 않는다.
    assert not school_source_ref("B1").startswith("neis:")


def test_좌표없는_학교와_연계없는_학구는_세어서_보고한다():
    zones = [_zone("Z1"), _zone("Z2")]
    links = [SchoolLink("Z1", "B1", "가초등학교", ELEMENTARY)]
    records, report = build_records(zones, links, {})
    assert records == []
    assert report.zones_without_link == ["Z2"]
    assert report.schools_without_location == ["B1"]


def test_다른_학교급_링크는_결합단계에서도_막힌다():
    """파싱 필터가 뚫려도 결합에서 한 번 더 막는다(방어 이중화)."""
    zones = [_zone("Z9")]
    links = [SchoolLink("Z9", "B9", "다중학교", "중학교")]
    locations = {"B9": SchoolLocation("B9", "다중학교", "중학교", 37.6, 127.1)}
    records, report = build_records(zones, links, locations)
    assert records == []
    assert report.wrong_level == 1


def test_원천의_중복행은_접는다():
    """★ 변이 가드 — 원천에 완전 중복 행이 실제로 있다(2026-03-20 판 Z000106450).

    접지 않으면 같은 (학구,학교) 조합이 두 번 만들어지고, PostgreSQL 이
    `ON CONFLICT DO UPDATE command cannot affect row a second time` 로
    **적재 트랜잭션 전체를 깬다**(실제로 밟았다).
    """
    duplicated = (
        "학구ID,학교ID,학교명,학교급구분,시도교육청코드,시도교육청명,"
        "교육지원청코드,교육지원청명,데이터기준일자\r\n"
        "Z1,B1,가초등학교,초등학교,7010000,서울,7041000,남부,2026-03-20\r\n"
        "Z1,B1,가초등학교,초등학교,7010000,서울,7041000,남부,2026-03-20\r\n"
    ).encode("cp949")
    links = parse_link_csv(duplicated)
    assert len(links) == 1
    assert len({(link.zone_id, link.school_id) for link in links}) == 1


def test_멀티파트_학구는_하나의_MultiPolygon_으로_합쳐진다():
    """학구ID·이름이 같은 폴리곤 둘 = 섬처럼 떨어진 한 학구. 합치는 게 원본의 뜻이다."""
    from app.ingest.school_zone import ZonePolygon, merge_zone_parts

    part_a = shp_polygon_to_wkb(_polygon_record([SQUARE]))
    part_b = shp_polygon_to_wkb(_polygon_record([FAR_SQUARE]))
    zones = [ZonePolygon("Z1", "가초통학구역", "11", "2026-03-20", part_a),
             ZonePolygon("Z1", "가초통학구역", "11", "2026-03-20", part_b)]
    merged, ambiguous = merge_zone_parts(zones)
    assert ambiguous == []
    assert len(merged) == 1
    assert _wkb_parts(merged[0].wkb) == [[5], [5]], "두 파트가 한 MultiPolygon 이어야 한다"


def test_학구ID가_다른_구역_둘에_쓰이면_합치지_않고_버린다():
    """★ 변이 가드 — 원천 결함(Z000106450: 고덕함박초 / 현민초).

    합치면 두 학교가 서로의 구역까지 배정한다고 **단정**하게 되고, 하나를 고르면
    나머지가 조용히 틀린다. 버리면 해당 단지는 '학구도 미포함'이 되어 도메인이
    배정을 단정하지 않는다(거리로 대체되지도 않는다).
    """
    from app.ingest.school_zone import ZonePolygon, merge_zone_parts

    zones = [
        ZonePolygon("Z1", "고덕함박초통학구역", "41", "2026-03-20",
                    shp_polygon_to_wkb(_polygon_record([SQUARE]))),
        ZonePolygon("Z1", "현민초통학구역", "41", "2026-03-20",
                    shp_polygon_to_wkb(_polygon_record([FAR_SQUARE]))),
    ]
    merged, ambiguous = merge_zone_parts(zones)
    assert merged == [] and ambiguous == ["Z1"]

    links = [SchoolLink("Z1", "B1", "고덕함박초등학교", ELEMENTARY),
             SchoolLink("Z1", "B2", "현민초등학교", ELEMENTARY)]
    locations = {"B1": SchoolLocation("B1", "고덕함박초등학교", ELEMENTARY, 37.5, 127.0),
                 "B2": SchoolLocation("B2", "현민초등학교", ELEMENTARY, 37.6, 127.1)}
    records, report = build_records(zones, links, locations)
    assert records == [], "모호한 학구로는 배정을 만들지 않는다"
    assert report.ambiguous_zones == ["Z1"]


def test_결합_결과에_자연키_중복이_없다():
    """적재 전 마지막 방어 — 자연키가 겹치면 upsert 가 트랜잭션을 깬다."""
    from app.ingest.school_zone import ZonePolygon

    zones = [ZonePolygon("Z1", "가초통학구역", "11", "2026-03-20",
                         shp_polygon_to_wkb(_polygon_record([SQUARE]))),
             ZonePolygon("Z1", "가초통학구역", "11", "2026-03-20",
                         shp_polygon_to_wkb(_polygon_record([FAR_SQUARE])))]
    links = [SchoolLink("Z1", "B1", "가초등학교", ELEMENTARY),
             SchoolLink("Z1", "B1", "가초등학교", ELEMENTARY)]      # 원천 중복 흉내
    locations = {"B1": SchoolLocation("B1", "가초등학교", ELEMENTARY, 37.5, 127.0)}
    records, _ = build_records(zones, links, locations)
    refs = [r.source_ref for r in records]
    assert len(refs) == len(set(refs)), f"자연키 중복: {refs}"


def test_학업성취도는_넣지_않는다():
    """초등은 국가수준 학업성취도 대상이 아니다 — 출처 없는 수치를 만들지 않는다."""
    zones = [_zone("Z1")]
    links = [SchoolLink("Z1", "B1", "가초등학교", ELEMENTARY)]
    locations = {"B1": SchoolLocation("B1", "가초등학교", ELEMENTARY, 37.5, 127.0)}
    records, _ = build_records(zones, links, locations)
    assert "achievement_pct" not in records[0].attrs
    assert records[0].attrs["district_as_of"] == "2026-03-20"


# ---------------------------------------------------------------------------
# 5. 적재 SQL
# ---------------------------------------------------------------------------

def _load_module():
    if str(SCRIPTS_DIR) not in sys.path:
        sys.path.insert(0, str(SCRIPTS_DIR))
    spec = importlib.util.spec_from_file_location(
        "_test_load_school_zone", SCRIPTS_DIR / "load_school_zone.py")
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


def _sql() -> str:
    module = _load_module()
    zones = [_zone("Z1")]
    links = [SchoolLink("Z1", "B1", "가초등학교", ELEMENTARY)]
    locations = {"B1": SchoolLocation("B1", "가초등학교", ELEMENTARY, 37.5, 127.0)}
    records, _ = build_records(zones, links, locations)
    return "".join(module.iter_sql(records))


def test_적재SQL_이_자기교차를_보정한다():
    """★ 변이 가드 — 원천 폴리곤 0.5%가 자기교차라, 보정을 빼면 `ST_Contains` 가
    GEOS 예외를 던져 **입지 분석 전체가 실패**한다.
    """
    sql = _sql()
    assert "ST_MakeValid" in sql
    # MakeValid 는 GeometryCollection 을 돌려줄 수 있다. 면만 뽑지 않으면
    # geometry(MultiPolygon,4326) 제약에 걸려 적재가 통째로 실패한다.
    assert "ST_CollectionExtract" in sql and ", 3)" in sql
    assert "ST_Multi" in sql


def test_적재SQL_의_좌표변환은_PostGIS_가_한다():
    sql = _sql()
    assert "ST_Transform" in sql
    assert "5186" in sql and "4326" in sql


def test_적재SQL_이_멱등이다():
    """★ 변이 가드 — 학구도는 매년 3·9월 재배포된다. upsert 가 아니면 행이 쌓이고
    `LIMIT 1` 이 어느 판을 고를지 알 수 없게 된다.
    """
    sql = _sql()
    assert sql.count("ON CONFLICT (source, source_ref)") == 2   # poi · school_district
    assert "DO UPDATE" in sql
    assert "INSERT INTO school_district" in sql
    assert "as_of" in sql, "기준일자(G2)를 함께 적재해야 한다"


def test_적재SQL_이_옛행을_지우지_않고_세기만_한다():
    """원천이 반쪽만 배포된 날 배정이 통째로 사라지는 사고를 막는다."""
    sql = _sql()
    assert "DELETE" not in sql.upper()
    assert "stale" in sql


def test_적재SQL_도_원장을_남긴다():
    """★ 변이 가드 — psql 로 흘려 넣는 경로가 ingest_log 를 빠뜨리면 "언제 무엇이
    들어왔는지"가 사라진다. 두 적재 경로의 관측이 갈라지면 안 된다.
    """
    sql = _sql()
    assert "INSERT INTO ingest_log" in sql
    assert "school_district" in sql and "kesi_school_zone:elementary" in sql
    # 임시 함수는 반드시 스키마 한정으로 부른다 — 한정 없이 부르면 PostgreSQL 이
    # 보안상 해석하지 않아 적재가 통째로 실패한다.
    assert "pg_temp.s(" in sql


def test_두_적재경로가_같은_문장을_쓴다():
    """SQL 파일 경로와 직접 적재 경로가 같은 파이프라인을 공유해야 한다."""
    module = _load_module()
    sql = _sql()
    for statement in module._PIPELINE:
        assert statement in sql, "직접 적재 경로에만 있는 문장이 있다(경로 분기)"


def test_적재SQL_이_한_트랜잭션이다():
    sql = _sql()
    assert sql.startswith("--") and "BEGIN;" in sql and sql.rstrip().endswith("COMMIT;")


def test_달러인용_구분자_충돌은_조용히_넘어가지_않는다():
    module = _load_module()
    with pytest.raises(ValueError, match="달러인용"):
        module._literal("학교$sz$이름")


# ---------------------------------------------------------------------------
# 6. 중·고 학교군 (013) — 초등과 **다른 모델**임을 고정한다
#
# 여기서 지키는 것은 "돌아간다"가 아니라 다음 둘이다:
#   ① 학교군을 초등 모델(1행=1(구역,학교))로 넣지 못한다 — 넣는 순간 배정이 된다.
#   ② 구역 1행 + 후보 N — 후보 수가 남아야 "배정 후보 N곳"이라고 말할 수 있다.
# ---------------------------------------------------------------------------

def _group_zone(zone_id: str, *, name: str | None = None, wkb: bytes | None = None):
    from app.ingest.school_zone import ZonePolygon

    return ZonePolygon(zone_id=zone_id, zone_name=name or f"{zone_id}학교군",
                       sd_cd="11", base_dt="2026-03-20",
                       wkb=wkb or shp_polygon_to_wkb(_polygon_record([SQUARE])),
                       edu_office="서울특별시강남서초교육지원청", zone_gb="0")


def test_학교군은_구역_1행에_후보_N_으로_묶인다():
    """★ 초등처럼 학교마다 행을 만들면 지오메트리가 4~14벌 복제되고(실측 32MB·30MB),
    무엇보다 '구역 하나에 학교 여럿'이라는 사실이 표현되지 않는다.
    """
    zones = [_group_zone("Z2001")]
    links = [SchoolLink("Z2001", "B1", "가중학교", MIDDLE),
             SchoolLink("Z2001", "B2", "나중학교", MIDDLE),
             SchoolLink("Z2001", "B3", "다중학교", MIDDLE)]
    locations = {sid: SchoolLocation(sid, f"{sid}중", MIDDLE, 37.5, 127.0)
                 for sid in ("B1", "B2", "B3")}
    records, report = build_zone_records(zones, links, locations, level=MIDDLE)

    assert len(records) == 1, "학교군은 구역마다 1행이다"
    record = records[0]
    assert record.source_ref == zone_source_ref("Z2001") == "kesi:Z2001"
    assert record.zone_kind == "학교군"
    assert record.level == MIDDLE
    assert [m.school_id for m in record.members] == ["B1", "B2", "B3"]
    assert report.members == 3
    assert record.edu_office == "서울특별시강남서초교육지원청"


def test_초등을_학교군_경로로_넣으면_거부한다():
    """★ 변이 가드 — 통학구역을 학교군으로 넣으면 3,246행이 2,656개 '학교군'이 되고
    '배정 초등학교'가 통째로 사라진다. 조용히 통과시키지 않는다.
    """
    with pytest.raises(ValueError, match="build_records"):
        build_zone_records([_group_zone("Z1")], [], {}, level=ELEMENTARY)


def test_학교군도_다른_급_링크는_막는다():
    zones = [_group_zone("Z2001")]
    links = [SchoolLink("Z2001", "B9", "가고등학교", HIGH)]     # 급이 다르다
    locations = {"B9": SchoolLocation("B9", "가고등학교", HIGH, 37.5, 127.0)}
    records, report = build_zone_records(zones, links, locations, level=MIDDLE)
    assert records == []
    assert report.wrong_level == 1


def test_후보_학교_좌표가_하나도_없으면_구역째_버리고_센다():
    """지오메트리만 남으면 "학교군 안인데 학교는 0곳"이라는 판정이 나간다."""
    zones = [_group_zone("Z2001")]
    links = [SchoolLink("Z2001", "B1", "가중학교", MIDDLE)]
    records, report = build_zone_records(zones, links, {}, level=MIDDLE)
    assert records == []
    assert report.zones_without_member == ["Z2001"]
    assert report.schools_without_location == ["B1"]


def test_학교군_자연키는_초등과_모양이_다르다():
    """섞이면 upsert 가 서로를 덮는다. 초등은 'kesi:Z/B', 학교군은 'kesi:Z'."""
    assert zone_source_ref("Z2001") == "kesi:Z2001"
    assert "/" in district_source_ref("Z1", "B1")
    assert "/" not in zone_source_ref("Z2001")


def test_학교군_적재SQL_은_배정학교를_적지_않고_후보를_단다():
    """★ 변이 가드 — school_poi_id 에 후보 하나를 적으면 조회가 그걸 '배정'으로 읽는다.

    013 의 CHECK 가 DB 에서도 막지만, 적재기가 그런 SQL 을 만들지 않는 것이 먼저다.
    """
    module = _load_module()
    zones = [_group_zone("Z2001")]
    links = [SchoolLink("Z2001", "B1", "가중학교", MIDDLE),
             SchoolLink("Z2001", "B2", "나중학교", MIDDLE)]
    locations = {sid: SchoolLocation(sid, f"{sid}중", MIDDLE, 37.5, 127.0)
                 for sid in ("B1", "B2")}
    records, _ = build_zone_records(zones, links, locations, level=MIDDLE)
    sql = "".join(module.iter_zone_sql(records, "middle"))

    assert "INSERT INTO school_district_member" in sql
    assert "SELECT NULL, g.geom" in sql, "학교군 행의 배정 학교는 NULL 이어야 한다"
    assert "school_level" in sql and "중학교" in sql
    assert "'학교군'" in sql or "학교군" in sql
    # 초등과 같은 안전장치들이 학교군 경로에도 있어야 한다.
    assert "ST_MakeValid" in sql and "ST_CollectionExtract" in sql
    assert "ST_Transform" in sql and "5186" in sql
    assert sql.count("ON CONFLICT") >= 3        # poi · school_district · member
    assert "INSERT INTO ingest_log" in sql and "kesi_school_zone:middle" in sql
    assert sql.rstrip().endswith("COMMIT;")


def test_학교군_적재는_구역을_지우지_않고_구성원만_교체한다():
    """구역 삭제는 금지(원천 반쪽 배포 사고). 구성원은 이번 배포분 기준으로 정리한다."""
    module = _load_module()
    zones = [_group_zone("Z2001")]
    links = [SchoolLink("Z2001", "B1", "가중학교", MIDDLE)]
    locations = {"B1": SchoolLocation("B1", "가중학교", MIDDLE, 37.5, 127.0)}
    records, _ = build_zone_records(zones, links, locations, level=MIDDLE)
    sql = "".join(module.iter_zone_sql(records, "middle"))

    assert "DELETE FROM school_district_member" in sql
    # 지우는 대상은 **member 뿐**이다. 구역(school_district) 자체를 지우는 문장이
    # 있으면 안 된다 — 'school_district_member' 를 걸러내고 남는 게 있으면 실패.
    assert "DELETE FROM school_district\n" not in sql
    assert "DELETE FROM school_district " not in sql, "구역을 지우면 안 된다"
    assert "member_removed" in sql and "stale" in sql


def test_학교군_stale_은_급별로_센다():
    """★ 변이 가드 — 급 필터를 빼면 중학교 적재가 초등 3,246행을 '없어진 행'으로 센다."""
    module = _load_module()
    stale = module._zone_stale_count(MIDDLE)
    assert "school_level = '중학교'" in stale
    # 초등 경로도 마찬가지다.
    assert "school_level = '초등학교'" in module._STALE_COUNT


def test_두_적재경로가_학교군에서도_같은_문장을_쓴다():
    module = _load_module()
    zones = [_group_zone("Z2001")]
    links = [SchoolLink("Z2001", "B1", "가중학교", MIDDLE)]
    locations = {"B1": SchoolLocation("B1", "가중학교", MIDDLE, 37.5, 127.0)}
    records, _ = build_zone_records(zones, links, locations, level=MIDDLE)
    sql = "".join(module.iter_zone_sql(records, "middle"))
    for statement in module._zone_pipeline(MIDDLE):
        assert statement in sql, "직접 적재 경로에만 있는 문장이 있다(경로 분기)"


def test_학교급별로_다른_SHP_파일을_읽는다():
    """급마다 원천 파일이 다르다 — 초등 zip 하나로 중·고를 만들어내지 않는다."""
    module = _load_module()
    files = {key: name for key, (_, name) in module.LEVEL_FILES.items()}
    assert files == {"elementary": "elementary_zone.zip",
                     "middle": "middle_zone.zip",
                     "high": "high_zone.zip"}
    assert len(set(files.values())) == 3
