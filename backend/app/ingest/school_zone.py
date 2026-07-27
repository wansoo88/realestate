"""학구도 파싱 — 초등 **통학구역** · 중·고 **학교군** (SHP · 연계정보 · 학교위치, 순수 함수).

왜 필요한가 — school 축(0.35)이 통째로 죽어 있었다
--------------------------------------------------
`school_district` 가 0행이라 `analysis.assess_school()` 이 항상
"학구도 데이터 미확보"만 반환했고, `_weighted_score` 는 있는 항목끼리만 정규화하므로
입지 점수가 사실상 **transit 0.40 + infra 0.25** 로만 계산됐다. 학군 근거 없는
'학군 반영' 점수가 나가고 있었던 셈이다.

이전 라운드는 "학구도 폴리곤을 배포하는 무키 경로가 없다"고 결론냈지만 **틀렸다.**
표준데이터 페이지(15021149/standard.do)에는 파일이 안 붙어 있을 뿐, 파일데이터
페이지에는 붙어 있고 인증키도 로그인도 필요 없다.

데이터 5종 (전부 공공데이터포털 파일데이터 · 무키)
--------------------------------------------------
운영주체가 한국지방교육행정연구재단 → **한국교육시설안전원**으로 이관됐다.
같은 데이터의 구판(2025-09-22)과 신판(2026-03-20)이 동시에 올라와 있으므로
**신판을 쓴다**(구판을 쓰면 반년 낡은 배정으로 판정하게 된다).

  ① 초등학교통학구역 SHP  https://www.data.go.kr/data/15159265/fileData.do
       7,140개 폴리곤 · EPSG:5186 · HAKGUDO_ID(학구ID) 보유
  ② 중학교학교군 SHP      https://www.data.go.kr/data/15159264/fileData.do
       1,684개 폴리곤 · 같은 속성 구조
  ③ 고등학교학교군 SHP    https://www.data.go.kr/data/15159263/fileData.do
       73개 폴리곤 (SGG_CD 가 없다 — 시군구를 넘는 광역 구역이라서)
  ④ 학교학구도연계정보 CSV https://www.data.go.kr/data/15159266/fileData.do
       17,985행 · 학구ID ↔ 학교ID (초 11,667 · 중 5,281 · 고 1,037)
  ⑤ 초중등학교위치 CSV     https://www.data.go.kr/data/15159184/fileData.do
       12,011교 · 학교ID ↔ 위도·경도 (초 6,303 · 중 3,312 · 고 2,396)

목표 체인 (전부 **문자열 정확일치**로 닫힌다 — 퍼지매칭 없음)
    SHP.HAKGUDO_ID → 연계.학구ID → 연계.학교ID → 위치.학교ID → 좌표
실측 매칭률: 수도권 학구 2,655/2,658(99.9%) · 학교 좌표 3,254/3,256(99.9%).

⚠️ 연계정보는 **오픈API 로도 열려 있지만 호출하지 않는다.**
   같은 데이터이고(referenceDate 2026-03-20 동일, 표본 1000/1000 일치) 파일은 1회
   무키 다운로드로 끝나는 반면 API 는 numOfRows 상한이 1,000 이라 18회를 써야 한다.
   API 는 `config/sources.yaml` 에 **갱신 감지용 저비용 크로스체크**로만 등록돼 있다.

⚠️⚠️ **학교급마다 자료의 의미가 다르다. 뭉뚱그리면 거짓말이 된다.**
   원천 데이터셋의 제목부터 다르다 — 초등은 「통학구역」, 중·고는 「학교군」이다.
   같은 표에 담되 `school_level` 로 갈라 조회하고, 문구도 급별로 다르게 쓴다.

     초등 통학구역 : 구역 하나에 학교 1곳이 원칙(수도권 실측 79%). 이때는 배정이라
                     말할 수 있다. 나머지 21%는 **공동학구**로 학교가 2곳 이상 걸린다 —
                     이 경우 "배정 학교"라고 단정할 수 없어 후보 수를 함께 낸다.
     중 학교군     : 수도권 학구당 학교 **4.46곳**(실측). '이 구역이면 이 중학교'가 아니다.
     고 학교군     : 수도권 학구당 학교 **14.39곳**(실측). 사실상 광역 단위다
                     (예: '강남서초학교군' 하나가 강남구+서초구 전체).

   ⚠️ **배정 방식(단일배정/추첨/평준화)은 원천 어디에도 없다.** SHP 속성 14개
      (HAKGUDO_ID·HAKGUDO_NM·HAKGUDO_GB·SD_CD·SGG_CD·EDU_*·BASE_DT·…), 연계정보 CSV
      9개 컬럼, 학교위치 CSV 18개 컬럼을 전부 확인했고 배정 방식 필드가 없다.
      데이터셋 설명문에도 없다. 그러므로 이 모듈은 배정 방식을 **만들어내지 않는다.**
      "중학교는 대체로 추첨" 같은 통념을 데이터인 척 적는 것도 지어내기다.
      우리가 적을 수 있는 건 셀 수 있는 것뿐이다 — **구역에 연계된 학교가 몇 곳인가.**

   ⚠️ HAKGUDO_GB(0/1)는 뜻이 문서화돼 있지 않다. 실측상 '1'이 연계 학교 2곳 이상과
      거의 정확히 겹치지만(초등 7,139개 중 어긋남 11개), **확인된 정의가 없으므로**
      해석하지 않는다. 파싱만 해서 `ZonePolygon.zone_gb` 에 원값으로 들고 있고,
      **DB 에는 넣지 않는다** — 뜻을 모르는 값에 컬럼을 주면 언젠가 누군가 그걸
      '공동학구 플래그'로 읽는다. 후보가 여럿인지는 연계정보로 세면 되고, 그건 확실하다.

   구조: 초등은 1행=1(구역,학교) 그대로 두고(회귀 없음), 중·고는 1행=1구역 +
   `school_district_member` 로 후보 학교를 단다(migration 013). 지오메트리를 4~14벌
   복제하지 않기 위해서이기도 하고, 학교군에는 애초에 '그 구역의 학교'가 하나가 아니라서다.
"""
from __future__ import annotations

import csv
import io
import struct
import zipfile
from collections.abc import Iterable, Iterator, Sequence
from dataclasses import dataclass, field

__all__ = [
    "CAPITAL_AREA_SD", "ELEMENTARY", "HIGH", "LEVELS", "MIDDLE", "SOURCE_KESI",
    "SchoolDistrictRecord", "SchoolLink", "SchoolLocation", "SchoolZoneRecord",
    "ZONE_KIND", "ZoneMember", "ZonePolygon", "build_records", "build_zone_records",
    "district_source_ref", "merge_wkb_multipolygons", "merge_zone_parts",
    "parse_link_csv", "parse_school_location_csv", "parse_zone_shapefile",
    "school_source_ref", "shp_polygon_to_wkb", "zone_source_ref",
]

#: 수도권 시도코드. 서비스 범위가 수도권이라 여기서 자른다(CLAUDE.md).
#: 전국을 넣으면 DB 가 5배(+100MB)가 되는데 쓰이지 않는다. 더 중요한 건 **비수도권 단지가
#: '학구도 미확보'로 남아야** 한다는 점이다 — `_DISTRICT_AVAILABLE_SQL` 이 반경 5km 안의
#: 폴리곤 유무로 '미확보'와 '미포함'을 가르므로, 수도권만 넣으면 그 구분이 자동으로 산다.
CAPITAL_AREA_SD = frozenset({"11", "41", "28"})     # 서울 · 경기 · 인천

#: 학교급. 값은 연계정보 CSV 의 `학교급구분` 문자열 **그대로**다(번역·축약 금지 —
#: 필터가 문자열 정확일치라 한 글자만 달라도 조용히 0건이 된다).
ELEMENTARY = "초등학교"
MIDDLE = "중학교"
HIGH = "고등학교"
LEVELS = (ELEMENTARY, MIDDLE, HIGH)

#: 급 → 구역 종류. **원천 데이터셋의 제목에서 온 낱말**이지 우리 해석이 아니다.
#:   15159265 「초등학교통학구역」 / 15159264 「중학교학교군」 / 15159263 「고등학교학교군」
#: 배정 방식이 아니다 — 배정 방식은 원천에 없다(모듈 docstring ⚠️).
ZONE_KIND: dict[str, str] = {
    ELEMENTARY: "통학구역",
    MIDDLE: "학교군",
    HIGH: "학교군",
}

SOURCE_KESI = "kesi_school_zone"

#: SHP 원본 좌표계 — Korea 2000 / 중부원점(2010). 변환은 **PostGIS 가** 한다
#: (`ST_Transform(..., 4326)`). 파이썬에서 재구현하면 pyproj 없이 검증 불가능한
#: 좌표가 조용히 들어간다. 서버 PostGIS 3.4.3 의 spatial_ref_sys 에 5186 이 있다.
ZONE_SRID = 5186

#: shapefile 셰이프 타입 5 = Polygon. 다른 타입이 오면 배포 형식이 바뀐 것이다.
_SHP_POLYGON = 5

#: DBF 에서 반드시 있어야 하는 컬럼. 하나라도 없으면 배포 형식이 바뀐 것이므로
#: **추측하지 않고 멈춘다** (틀린 학구 배정은 틀린 추천으로 바로 이어진다).
#: EDU_NM(교육지원청)이 필수인 이유: 고등학교 학교군 이름은 '1학교군'·'2학교군' 처럼
#: 교육지원청 안에서만 유일하다. 교육지원청 없이 표시하면 전국의 '1학교군'이 같은
#: 이름으로 보인다. 초·중·고 SHP 세 벌에 모두 들어 있다(실측).
#: ⚠️ SGG_CD 는 넣지 않는다 — **고등학교 SHP 에는 없다**(시군구를 넘는 광역 구역이라서).
_ZONE_COLUMNS = ("HAKGUDO_ID", "HAKGUDO_NM", "SD_CD", "BASE_DT", "EDU_NM")

_LINK_COLUMNS = ("학구ID", "학교ID", "학교명", "학교급구분")
_LOCATION_COLUMNS = ("학교ID", "학교명", "학교급구분", "위도", "경도")

#: CSV 인코딩 후보. 연계정보는 CP949, 학교위치는 UTF-8 BOM 으로 서로 다르다(실측).
_ENCODINGS = ("utf-8-sig", "cp949", "utf-8")


# ---------------------------------------------------------------------------
# 레코드
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class ZonePolygon:
    """학구 폴리곤 1개. `wkb` 는 **EPSG:5186 좌표 그대로**다(변환은 PostGIS)."""

    zone_id: str                 # HAKGUDO_ID — 'Z000102998'
    zone_name: str               # HAKGUDO_NM — '서울언주초통학구역' (학교명이 아니다)
    sd_cd: str                   # 시도코드
    base_dt: str                 # BASE_DT — '2026-03-20' → school_district.as_of
    wkb: bytes
    edu_office: str | None = None    # EDU_NM — '서울특별시강남서초교육지원청'
    #: HAKGUDO_GB 원값('0'/'1'). **뜻이 문서화돼 있지 않아 해석하지도, 적재하지도 않는다.**
    #: 파싱 결과를 확인·검증할 때(원천 대조) 쓰려고 들고만 있는다.
    zone_gb: str | None = None


@dataclass(frozen=True)
class SchoolLink:
    """학구 ↔ 학교 연결 1건. 공동학구는 학구 하나에 여러 학교가 걸린다."""

    zone_id: str
    school_id: str               # 'B000003402'
    school_name: str
    level: str                   # 초등학교 | 중학교 | 고등학교
    office: str | None = None    # 교육지원청명


@dataclass(frozen=True)
class SchoolLocation:
    """학교 좌표 1건. 학교ID 가 연계정보와 **같은 체계**라 정확일치로 붙는다."""

    school_id: str
    name: str
    level: str
    lat: float
    lon: float
    address: str | None = None
    as_of: str | None = None


@dataclass(frozen=True)
class SchoolDistrictRecord:
    """`school_district` 한 행 + 그 행이 가리키는 `poi`(학교) 한 건.

    공동학구(학구 하나에 학교 N개)는 **N행**이 된다. 지오메트리가 중복되지만
    현재 스키마가 1행=1(구역,학교) 이라 이게 정직한 표현이다 — 초등은 중복배수가
    1.22 라 비용이 작다(중학교는 4.47, 고등학교는 14.4 — 또 하나의 '초등만' 근거).
    """

    source_ref: str              # 'kesi:{학구ID}/{학교ID}' — school_district 자연키
    zone_id: str
    zone_name: str
    school_source_ref: str       # 'kesi:{학교ID}' — poi 자연키
    school_id: str
    school_name: str
    lat: float
    lon: float
    as_of: str                   # BASE_DT
    wkb: bytes
    attrs: dict = field(default_factory=dict)

    @property
    def wkb_hex(self) -> str:
        return self.wkb.hex()


@dataclass(frozen=True)
class ZoneMember:
    """학교군에 속한 학교 1곳. `school_district_member` 한 행 + 그 학교의 `poi` 한 건."""

    school_source_ref: str       # 'kesi:{학교ID}' — poi 자연키
    school_id: str
    school_name: str
    lat: float
    lon: float
    attrs: dict = field(default_factory=dict)


@dataclass(frozen=True)
class SchoolZoneRecord:
    """`school_district` 한 행 = **구역 하나**. 후보 학교는 `members` 로 딸린다.

    초등(`SchoolDistrictRecord`)과 형태가 다른 이유는 편의가 아니라 **의미**다.
    학교군은 '학교마다 구역 하나'가 아니라 '구역 하나에 학교 여럿'이고,
    school_poi_id(단수)에는 그 사실을 적을 자리가 없다(migration 013).
    """

    source_ref: str              # 'kesi:{학구ID}' — 학구ID 단독이 키다(구역이 1행이므로)
    zone_id: str
    zone_name: str
    level: str                   # 중학교 | 고등학교
    zone_kind: str               # 학교군
    as_of: str                   # BASE_DT
    wkb: bytes
    members: tuple[ZoneMember, ...] = ()
    #: 표시용 교육지원청(EDU_NM). school_district 에 컬럼이 없어 **적재하지 않는다** —
    #: 같은 값이 각 학교 poi.attrs['office'] 로 들어간다(연계정보 CSV 교육지원청명).
    edu_office: str | None = None

    @property
    def wkb_hex(self) -> str:
        return self.wkb.hex()


def district_source_ref(zone_id: str, school_id: str) -> str:
    """school_district 자연키.

    학구ID **단독은 키가 될 수 없다** — 공동학구는 같은 학구ID 로 여러 행이 생긴다.
    (학구ID, 학교ID) 쌍이라야 재실행이 행을 쌓지 않는다.
    """
    return f"kesi:{zone_id}/{school_id}"


def school_source_ref(school_id: str) -> str:
    """poi(category=school) 자연키. NEIS 경로('neis:...')와 접두사로 구분된다."""
    return f"kesi:{school_id}"


def zone_source_ref(zone_id: str) -> str:
    """학교군(구역 1행) 자연키.

    초등의 `district_source_ref` 와 **모양이 다르다**('kesi:Z…' vs 'kesi:Z…/B…').
    섞일 수 없는 이유가 둘 있다: ① 학구ID 번호대가 급별로 다르고(초 Z0001…,
    중 Z0002…, 고 Z0003…) ② 초등은 슬래시 뒤에 학교ID 가 붙는다.
    그래도 (source, source_ref) 유니크(012)가 최종 방어선이다.
    """
    return f"kesi:{zone_id}"


# ---------------------------------------------------------------------------
# shapefile — 순수 파이썬 파서
# ---------------------------------------------------------------------------
#
# geopandas/fiona/GDAL 을 쓰지 않는 이유는 취향이 아니라 **운영 제약**이다.
# 대상 VPS 는 가용 메모리가 200MB 안팎이고 디스크 여유가 2.6GB 다. geopandas 설치는
# 디스크 300MB+·import 만으로 메모리 100MB+ 를 먹어 다른 실서비스를 위협한다.
# 폴리곤 shapefile 파싱은 아래 60줄이면 끝나고, 좌표변환은 PostGIS 가 이미 할 수 있다.


def _decode(raw: bytes) -> str:
    """한글이 보여야 성공으로 친다(reb.decode_csv 와 같은 원칙).

    `errors='replace'` 로 넘기면 깨진 학교명이 그대로 적재되고, 그 뒤 조인은 전부
    실패하면서 원인은 안 보인다.
    """
    for enc in _ENCODINGS:
        try:
            text = raw.decode(enc)
        except UnicodeDecodeError:
            continue
        if any("가" <= ch <= "힣" for ch in text[:5000]):
            return text
    raise ValueError("인코딩을 판별하지 못했습니다 (utf-8-sig/cp949 모두 실패)")


def _dbf_rows(data: bytes, encoding: str) -> list[dict[str, str]]:
    """dBASE III 레코드를 dict 로. 필드 정의는 헤더 0x0D 까지 32바이트씩 이어진다."""
    count, = struct.unpack("<I", data[4:8])
    header_len, = struct.unpack("<H", data[8:10])
    record_len, = struct.unpack("<H", data[10:12])

    fields: list[tuple[str, int]] = []
    offset = 32
    while data[offset] != 0x0D:
        raw = data[offset:offset + 32]
        fields.append((raw[:11].split(b"\0")[0].decode(encoding, "replace"), raw[16]))
        offset += 32

    rows: list[dict[str, str]] = []
    for i in range(count):
        pos = header_len + i * record_len + 1      # +1 = 삭제 표시 바이트
        row: dict[str, str] = {}
        for name, length in fields:
            row[name] = data[pos:pos + length].decode(encoding, "replace").strip()
            pos += length
        rows.append(row)
    return rows


def _signed_area(ring: Sequence[tuple[float, float]]) -> float:
    total = 0.0
    n = len(ring)
    for i in range(n):
        x1, y1 = ring[i]
        x2, y2 = ring[(i + 1) % n]
        total += x1 * y2 - x2 * y1
    return total / 2.0


def shp_polygon_to_wkb(body: bytes) -> bytes | None:
    """shapefile 폴리곤 레코드 본문 → WKB MultiPolygon(리틀엔디언).

    shapefile 은 외곽/구멍을 **링 방향**으로만 구분한다(외곽 시계방향 = 부호면적 음수,
    구멍 반시계). WKB 는 폴리곤마다 [외곽, 구멍...] 순서를 요구하므로 부호면적으로
    갈라 다시 묶는다. 이걸 안 하면 도넛 모양 학구의 구멍이 **외곽으로 승격**돼
    "구멍 안 단지"가 학구에 포함된 것으로 판정된다.

    MultiPolygon 으로 내보내는 이유: `school_district.geom` 이
    `geometry(MultiPolygon, 4326)` 라 단일 폴리곤도 ST_Multi 를 거쳐야 한다.
    """
    shape_type, = struct.unpack("<i", body[:4])
    if shape_type != _SHP_POLYGON:
        return None

    part_count, point_count = struct.unpack("<ii", body[36:44])
    part_index = struct.unpack(f"<{part_count}i", body[44:44 + 4 * part_count])
    base = 44 + 4 * part_count
    coords = struct.unpack(f"<{2 * point_count}d", body[base:base + 16 * point_count])

    rings: list[list[tuple[float, float]]] = []
    for i in range(part_count):
        start = part_index[i]
        end = part_index[i + 1] if i + 1 < part_count else point_count
        rings.append([(coords[2 * j], coords[2 * j + 1]) for j in range(start, end)])

    polygons: list[list[list[tuple[float, float]]]] = []
    for ring in rings:
        if len(ring) < 4:                     # 닫힌 링은 최소 4점(시작=끝)
            continue
        if _signed_area(ring) < 0 or not polygons:
            polygons.append([ring])           # 외곽 (첫 링은 방향과 무관하게 외곽)
        else:
            polygons[-1].append(ring)         # 직전 외곽의 구멍
    if not polygons:
        return None

    out = bytearray()
    out += b"\x01"
    out += struct.pack("<I", 6)               # wkbMultiPolygon
    out += struct.pack("<I", len(polygons))
    for polygon in polygons:
        out += b"\x01"
        out += struct.pack("<I", 3)           # wkbPolygon
        out += struct.pack("<I", len(polygon))
        for ring in polygon:
            out += struct.pack("<I", len(ring))
            for x, y in ring:
                out += struct.pack("<dd", x, y)
    return bytes(out)


def _shx_offsets(shx: bytes) -> Iterator[tuple[int, int]]:
    """(바이트 오프셋, 바이트 길이).

    ⚠️ shx 의 두 값은 **16비트 워드** 단위다. ×2 를 빠뜨려도 첫 레코드는 우연히
       읽히기 때문에 예외가 안 나고, 그 뒤부터 폴리곤이 조용히 어긋난다.
       (프로토타입에서 실제로 밟았다 — 그래서 이 변환을 함수로 격리했다.)
    """
    for i in range(100, len(shx), 8):         # 헤더 100바이트 뒤부터 8바이트씩
        offset_words, length_words = struct.unpack(">ii", shx[i:i + 8])
        yield offset_words * 2, length_words * 2


def parse_zone_shapefile(
    zip_bytes: bytes, *, sido_codes: Iterable[str] | None = CAPITAL_AREA_SD,
) -> list[ZonePolygon]:
    """통학구역 SHP(zip) → 학구 폴리곤 목록.

    `sido_codes=None` 이면 전국. 기본은 수도권만 — 필터를 **파싱 단계**에 두어야
    쓰지 않을 5만개 정점을 메모리에 올리지 않는다.
    """
    with zipfile.ZipFile(io.BytesIO(zip_bytes)) as zf:
        members: dict[str, str] = {}
        for info in zf.infolist():
            suffix = info.filename.rsplit(".", 1)[-1].lower() if "." in info.filename else ""
            members.setdefault(suffix, info.filename)
        missing = [s for s in ("shp", "shx", "dbf") if s not in members]
        if missing:
            raise ValueError(f"SHP 묶음에 {missing} 가 없습니다 — 배포 형식이 바뀌었습니다")

        # .cpg 가 DBF 인코딩을 적어 준다(현재 배포본은 EUC-KR). 없으면 CP949 로 본다.
        encoding = "cp949"
        if "cpg" in members:
            declared = zf.read(members["cpg"]).decode("ascii", "replace").strip().upper()
            if "UTF" in declared:
                encoding = "utf-8"

        attributes = _dbf_rows(zf.read(members["dbf"]), encoding)
        shx = zf.read(members["shx"])
        shp = zf.read(members["shp"])

    if not attributes:
        raise ValueError("DBF 에 레코드가 없습니다")
    absent = [c for c in _ZONE_COLUMNS if c not in attributes[0]]
    if absent:
        raise ValueError(f"DBF 에 기대한 컬럼이 없습니다: {absent} "
                         f"(실제: {sorted(attributes[0])})")

    wanted = None if sido_codes is None else frozenset(sido_codes)
    zones: list[ZonePolygon] = []
    for row, (offset, length) in zip(attributes, _shx_offsets(shx), strict=False):
        if wanted is not None and row["SD_CD"] not in wanted:
            continue
        # 레코드 헤더 8바이트(번호+길이) 뒤가 본문이다.
        wkb = shp_polygon_to_wkb(shp[offset + 8:offset + 8 + length])
        if wkb is None:
            continue
        zones.append(ZonePolygon(
            zone_id=row["HAKGUDO_ID"].strip(),
            zone_name=row["HAKGUDO_NM"].strip(),
            sd_cd=row["SD_CD"].strip(),
            base_dt=row["BASE_DT"].strip(),
            wkb=wkb,
            edu_office=row["EDU_NM"].strip() or None,
            zone_gb=(row.get("HAKGUDO_GB") or "").strip() or None,
        ))
    return zones


def merge_wkb_multipolygons(parts: Sequence[bytes]) -> bytes:
    """MultiPolygon WKB 여러 개 → 하나로. 좌표는 건드리지 않고 폴리곤 목록만 잇는다."""
    if len(parts) == 1:
        return parts[0]
    total = 0
    payloads: list[bytes] = []
    for wkb in parts:
        kind, = struct.unpack("<I", wkb[1:5])
        if wkb[0] != 1 or kind != 6:
            raise ValueError("리틀엔디언 MultiPolygon 만 병합할 수 있습니다")
        count, = struct.unpack("<I", wkb[5:9])
        total += count
        payloads.append(wkb[9:])
    return b"\x01" + struct.pack("<I", 6) + struct.pack("<I", total) + b"".join(payloads)


def merge_zone_parts(
    zones: Sequence[ZonePolygon],
) -> tuple[list[ZonePolygon], list[str]]:
    """같은 학구ID 를 쓰는 폴리곤들을 정리한다. 반환: (정리된 학구, 모호해서 버린 학구ID).

    학구ID 가 겹치는 경우가 두 가지인데 **의미가 정반대**라 나눠 다룬다.

    ① 이름이 같다 → **멀티파트 학구**다. 섬처럼 떨어진 구역을 피처 2개로 나눠 담은 것뿐이니
       하나의 MultiPolygon 으로 합치는 게 원본의 뜻이다.

    ② 이름이 다르다 → **원천 결함**이다(2026-03-20 판 실측: Z000106450 이
       '고덕함박초통학구역'과 '현민초통학구역' 둘에 쓰였다). 어느 폴리곤이 어느 학교의
       학구인지 알 방법이 없다. 합치면 두 학교가 서로의 구역까지 배정하는 것으로 주장하게 되고,
       하나를 고르면 나머지가 조용히 틀린다.
       그래서 **버린다** — 이 저장소의 일관된 규칙이다(reb.py "애매하면 매칭하지 않는다").
       버린 학구의 단지는 '학구도 미포함'이 되어 도메인이 배정을 단정하지 않는다.
       거리로 대체되지 않으므로 안전하다.
    """
    grouped: dict[str, list[ZonePolygon]] = {}
    for zone in zones:
        grouped.setdefault(zone.zone_id, []).append(zone)

    merged: list[ZonePolygon] = []
    ambiguous: list[str] = []
    for zone_id, parts in grouped.items():
        if len(parts) == 1:
            merged.append(parts[0])
            continue
        if len({p.zone_name for p in parts}) > 1:
            ambiguous.append(zone_id)
            continue
        first = parts[0]
        merged.append(ZonePolygon(
            zone_id=zone_id, zone_name=first.zone_name, sd_cd=first.sd_cd,
            base_dt=first.base_dt,
            wkb=merge_wkb_multipolygons([p.wkb for p in parts]),
            edu_office=first.edu_office, zone_gb=first.zone_gb,
        ))
    return merged, ambiguous


# ---------------------------------------------------------------------------
# CSV 두 종
# ---------------------------------------------------------------------------

def _dict_rows(raw: bytes, required: Sequence[str], *, what: str) -> list[dict[str, str]]:
    reader = csv.DictReader(io.StringIO(_decode(raw)))
    absent = [c for c in required if c not in (reader.fieldnames or [])]
    if absent:
        raise ValueError(f"{what} CSV 에 기대한 컬럼이 없습니다: {absent} "
                         f"(실제: {reader.fieldnames})")
    return list(reader)


def parse_link_csv(raw: bytes, *, level: str | None = ELEMENTARY) -> list[SchoolLink]:
    """학교학구도연계정보 CSV → 학구↔학교 연결.

    `level` 기본값이 초등학교인 것이 **중·고 혼입 방어선**이다(모듈 docstring ⚠️).

    ⚠️ 원천에 **완전 중복 행**이 있다(2026-03-20 판 실측: Z000106450 관련 4행이
       2행씩 중복). 접지 않으면 같은 (학구,학교) 조합이 두 번 만들어져
       `ON CONFLICT DO UPDATE command cannot affect row a second time` 로
       **적재 트랜잭션 전체가 깨진다**. 배치 안에서 먼저 접는다(poi_loader 와 같은 이유).
    """
    links: list[SchoolLink] = []
    seen: set[tuple[str, str]] = set()
    for row in _dict_rows(raw, _LINK_COLUMNS, what="학교학구도연계정보"):
        school_level = (row.get("학교급구분") or "").strip()
        if level is not None and school_level != level:
            continue
        zone_id = (row.get("학구ID") or "").strip()
        school_id = (row.get("학교ID") or "").strip()
        if not zone_id or not school_id:
            continue                          # 키 없는 행은 조인 불가 — 세어서 버린다
        if (zone_id, school_id) in seen:
            continue
        seen.add((zone_id, school_id))
        links.append(SchoolLink(
            zone_id=zone_id,
            school_id=school_id,
            school_name=(row.get("학교명") or "").strip(),
            level=school_level,
            office=(row.get("교육지원청명") or "").strip() or None,
        ))
    return links


def parse_school_location_csv(
    raw: bytes, *, level: str | None = ELEMENTARY,
) -> dict[str, SchoolLocation]:
    """초중등학교위치 CSV → {학교ID: 좌표}. 좌표가 없는 행은 담지 않는다."""
    out: dict[str, SchoolLocation] = {}
    for row in _dict_rows(raw, _LOCATION_COLUMNS, what="초중등학교위치"):
        school_level = (row.get("학교급구분") or "").strip()
        if level is not None and school_level != level:
            continue
        school_id = (row.get("학교ID") or "").strip()
        try:
            lat = float((row.get("위도") or "").strip())
            lon = float((row.get("경도") or "").strip())
        except ValueError:
            continue                          # 좌표 미상 — 추정하지 않는다
        if not school_id or not (-90 <= lat <= 90) or not (-180 <= lon <= 180):
            continue
        out[school_id] = SchoolLocation(
            school_id=school_id,
            name=(row.get("학교명") or "").strip(),
            level=school_level,
            lat=lat, lon=lon,
            address=(row.get("소재지도로명주소") or row.get("소재지지번주소") or "").strip()
                    or None,
            as_of=(row.get("데이터기준일자") or "").strip() or None,
        )
    return out


# ---------------------------------------------------------------------------
# 체인 결합
# ---------------------------------------------------------------------------

@dataclass
class BuildReport:
    """결합 결과 통계. **조용히 버리지 않는다** — 버린 건 세어서 보고한다."""

    zones: int = 0
    records: int = 0
    zones_without_link: list[str] = field(default_factory=list)
    schools_without_location: list[str] = field(default_factory=list)
    wrong_level: int = 0
    #: 학구ID 하나가 서로 다른 구역 둘에 쓰인 경우(원천 결함). 버린 학구ID들.
    ambiguous_zones: list[str] = field(default_factory=list)
    #: 연계는 있는데 **후보 학교의 좌표가 하나도 없어** 버린 구역(학교군 경로).
    zones_without_member: list[str] = field(default_factory=list)
    #: 적재될 (구역,학교) 연결 수 = school_district_member 행 수(학교군 경로).
    members: int = 0


def build_records(
    zones: Sequence[ZonePolygon],
    links: Sequence[SchoolLink],
    locations: dict[str, SchoolLocation],
    *,
    level: str = ELEMENTARY,
) -> tuple[list[SchoolDistrictRecord], BuildReport]:
    """학구 폴리곤 × 연계 × 좌표 → 적재 레코드.

    좌표가 없는 학교는 **넣지 않는다.** poi 는 `geometry(Point,4326)` 이고 좌표 없는
    학교를 넣으면 거리 계산이 NULL 이 되는데, 그러면 `_school_score` 가 '거리 미상'
    중립점(60)을 주게 된다 — 없는 근거로 점수를 만드는 셈이다.
    """
    # 멀티파트는 합치고, 학구ID 가 중복된 모호한 건은 버린다(merge_zone_parts docstring).
    zones, ambiguous = merge_zone_parts(zones)

    by_zone: dict[str, list[SchoolLink]] = {}
    report = BuildReport(zones=len(zones), ambiguous_zones=ambiguous)
    for link in links:
        if link.level != level:
            report.wrong_level += 1
            continue
        by_zone.setdefault(link.zone_id, []).append(link)

    records: list[SchoolDistrictRecord] = []
    # 자연키 중복은 여기서 **마지막으로** 막는다. 파싱에서 이미 접지만, 겹친 채로
    # SQL 까지 내려가면 upsert 가 트랜잭션을 통째로 깬다(방어 이중화).
    emitted: set[str] = set()
    for zone in zones:
        matched = by_zone.get(zone.zone_id)
        if not matched:
            report.zones_without_link.append(zone.zone_id)
            continue
        for link in matched:
            source_ref = district_source_ref(zone.zone_id, link.school_id)
            if source_ref in emitted:
                continue
            location = locations.get(link.school_id)
            if location is None:
                report.schools_without_location.append(link.school_id)
                continue
            emitted.add(source_ref)
            records.append(SchoolDistrictRecord(
                source_ref=source_ref,
                zone_id=zone.zone_id,
                zone_name=zone.zone_name,
                school_source_ref=school_source_ref(link.school_id),
                school_id=link.school_id,
                school_name=link.school_name or location.name,
                lat=location.lat, lon=location.lon,
                as_of=zone.base_dt,
                wkb=zone.wkb,
                attrs={
                    "school_id": link.school_id,
                    "level": link.level,
                    "zone_id": zone.zone_id,
                    "zone_name": zone.zone_name,
                    "office": link.office,
                    # 학구도 기준연도. `school_district.as_of` 가 정본이지만 003 이전
                    # 적재분 호환을 위해 리포지토리가 attrs 도 본다(_fetch_school).
                    "district_as_of": zone.base_dt,
                    # 원천 데이터셋 제목에서 온 구역 종류. 초등은 '통학구역'.
                    "zone_kind": ZONE_KIND[level],
                    # ⚠️ achievement_pct 는 **넣지 않는다.** 초등학교는 국가수준
                    #    학업성취도 평가 대상이 아니라 출처 있는 수치가 존재하지 않는다.
                    #    출처·기준연도 없는 수치는 쓰지 않는다(analysis.py 원칙 5).
                },
            ))
    report.records = len(records)
    return records, report


def build_zone_records(
    zones: Sequence[ZonePolygon],
    links: Sequence[SchoolLink],
    locations: dict[str, SchoolLocation],
    *,
    level: str,
) -> tuple[list[SchoolZoneRecord], BuildReport]:
    """학교군 폴리곤 × 연계 × 좌표 → **구역 1행 + 후보 학교 N** 레코드 (중·고 전용).

    `build_records`(초등)와 갈라진 지점은 딱 하나다: 초등은 학교마다 행을 만들고
    여기서는 **구역마다** 행을 만든다. 그 차이가 곧 두 자료의 의미 차이다.

    좌표 없는 학교는 후보에서 뺀다(거리 계산이 NULL 이 되면 '거리 미상' 중립점이
    붙어 없는 근거로 점수가 만들어진다 — build_records 와 같은 이유).
    후보가 하나도 안 남은 구역은 **구역째 버린다**: 지오메트리만 남으면
    "학교군 안에 있는데 학교는 하나도 없다"는 판정이 나가게 된다.
    """
    if level == ELEMENTARY:
        # 초등을 이 경로로 넣으면 3,246행짜리 통학구역이 2,656개 '학교군'으로 바뀐다.
        # 조용히 통과시키지 않는다.
        raise ValueError("초등학교는 build_records() 로 적재한다 "
                         "(통학구역은 1행=1(구역,학교) 모델이다)")

    zones, ambiguous = merge_zone_parts(zones)

    by_zone: dict[str, list[SchoolLink]] = {}
    report = BuildReport(zones=len(zones), ambiguous_zones=ambiguous)
    for link in links:
        if link.level != level:
            report.wrong_level += 1
            continue
        by_zone.setdefault(link.zone_id, []).append(link)

    records: list[SchoolZoneRecord] = []
    emitted: set[str] = set()
    for zone in zones:
        matched = by_zone.get(zone.zone_id)
        if not matched:
            report.zones_without_link.append(zone.zone_id)
            continue

        members: list[ZoneMember] = []
        seen: set[str] = set()
        for link in matched:
            if link.school_id in seen:
                continue
            location = locations.get(link.school_id)
            if location is None:
                report.schools_without_location.append(link.school_id)
                continue
            seen.add(link.school_id)
            members.append(ZoneMember(
                school_source_ref=school_source_ref(link.school_id),
                school_id=link.school_id,
                school_name=link.school_name or location.name,
                lat=location.lat, lon=location.lon,
                attrs={
                    "school_id": link.school_id,
                    "level": link.level,
                    "office": link.office,
                    "district_as_of": zone.base_dt,
                    # ⚠️ zone_id·zone_name 은 **학교 attrs 에 넣지 않는다.** 학교 하나가
                    #    여러 학교군에 속할 수 있어(중·고에서 흔하다) 그중 하나만 적으면
                    #    나머지가 조용히 틀린다. 구역 정보는 school_district 행에 있다.
                },
            ))

        if not members:
            report.zones_without_member.append(zone.zone_id)
            continue

        source_ref = zone_source_ref(zone.zone_id)
        if source_ref in emitted:
            continue
        emitted.add(source_ref)
        records.append(SchoolZoneRecord(
            source_ref=source_ref,
            zone_id=zone.zone_id,
            zone_name=zone.zone_name,
            level=level,
            zone_kind=ZONE_KIND[level],
            as_of=zone.base_dt,
            wkb=zone.wkb,
            members=tuple(members),
            edu_office=zone.edu_office,
        ))

    report.records = len(records)
    report.members = sum(len(r.members) for r in records)
    return records, report
