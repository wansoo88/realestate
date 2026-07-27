"""단지 좌표 확보 — 카카오 로컬 키워드 검색 + **결과 검증**(WGS84).

왜 필요한가
-----------
MOLIT 실거래에는 좌표가 없다(normalize.py). 하지만 지도(F1)·입지 분석(F5)·동별 추정(F4)이
전부 complex.geom(POINT,4326) 위에서 돈다. 좌표 없는 단지는 지도에 못 찍고 입지 분석이
'정보 없음'이 된다(postgis.py 주석). 그래서 적재 후 **별도 단계**로 좌표를 채운다.

좌표 소스 조사 (ORDER 지시: 카카오 or 별도소스)
------------------------------------------------
| 후보 | 방식 | 판단 |
|---|---|---|
| **카카오 로컬 키워드검색** | "법정동 단지명" → 장소 좌표 | ✅ 채택. 단지명 기반이라 실거래명과 직결. REST 키 필요 |
| **카카오 주소검색** | 지번주소 → 좌표 | ✅ 채택(2026-07-26). 부동산원 단지 마스터가 지번주소를 주면서 가능해졌다 |
| 건축물대장 | 대장에 좌표가 있으면 사용 | 동별 좌표까지 가능하나 매칭 난이도↑ (2차) |
| 도로명주소 API(주소기반산업지원) | 주소→좌표 | 카카오 실패 시 폴백 |

⚠️ 2026-07-26 REB-1 — 이름으로 못 찾는 것은 **주소로** 찾는다
--------------------------------------------------------------
GEO-1 수정 후 미확보 1,307건의 사유는 검증불합격 749 + 검색0건 518 이었고, 둘 다
"단지명으로 찾기"의 한계였다. 한국부동산원 공동주택 단지 식별정보로 단지↔지번주소를
이어 붙이면(app/ingest/reb.py) 이름을 거치지 않고 좌표를 얻을 수 있다.

**주소 경로도 검증을 우회하지 않는다.** 오히려 키워드 경로보다 대조할 게 더 많다:
  1. `address.b_code`(법정동코드 10자리) == 우리 `complex.region_code` — 문자열이 아닌 코드 대조
  2. 본번·부번이 부동산원 PNU 와 일치 — 카카오가 다른 지번으로 미끄러지는 걸 잡는다
  3. `address_type` 이 REGION(동 중심점)이면 불합격 — 이걸 받으면 한 동의 단지가 전부 한 점이 된다
  4. 산번지 여부 일치 — '산87-85' 와 '87-85' 는 다른 필지다
  5. 수도권 bbox · 좌표 충돌 차단은 키워드 경로와 동일

⚠️ 2026-07-26 CR-020 GEO-1 — "확보율"은 품질이 아니다
-----------------------------------------------------
이전 구현은 카카오 응답의 **첫 결과를 그대로 믿었다**(size=1, 검증 없음).
그 결과 운영 DB 6,538개 단지 중

- 다른 단지와 **좌표가 완전히 같은 단지 514건(7.9%)**
- 그중 **68건은 법정동이 서로 다름** (역삼동/도곡동/서초동 '대우디오빌' 계열 4건이 한 점)

이 나왔다. 확보율 93.6% 는 그 결함을 덮고 있었다. 코드가 스스로 적어둔 정당화
("법정동은 절대 떼지 않으니 동 안에서 겹칠 확률은 낮다")를 실데이터가 반증했다.

그래서 이 모듈은 이제 **"찾았다"가 아니라 "확인됐다"만 채택**한다:

1. **결과 검증** — 카카오가 돌려준 `address_name` 의 법정동이 질의한 법정동과 같아야 한다.
2. **권역 검증** — 시도·시군구가 맞아야 하고, 좌표가 수도권 bbox 안이어야 한다.
3. **이름 대조** — `place_name` 이 질의한 단지명과 맞아야 한다(포함 또는 유사도).
4. **보수적 변형** — 괄호 안이 지번·동목록일 때만 떼어낸다. '(경남)'·'(5-1단지)'·'(주공)'
   처럼 **단지·차수·시공사**를 가리키는 표기는 절대 떼지 않는다 — 그걸 떼면
   '탑마을(경남)1'·'탑마을(기산)1' 이 같은 이름이 되어 한 점에 뭉친다(야탑동 실측).
5. **좌표 충돌 차단** — 이미 다른 단지가 쓰는 점은 재사용하지 않는다(enrich_geom).
   단, MOLIT 이름 오염으로 한 단지가 여러 행으로 갈라진 경우
   ('대치우성아파트1동,2동' ~ '대치우성')는 같은 점을 **공유로 허용**하고 따로 센다.
   ⚠️ 괄호 안 **지번**('(1002-10)')은 갈라진 이름이 아니라 **다른 단지**다 — GEO-6 참조.

원칙은 그대로다 — **틀린 좌표는 좌표 없음보다 나쁘다.** 확보율이 떨어지더라도
검증을 통과하지 못한 좌표는 넣지 않는다. 못 찾은 건 '정보 없음'으로 보인다.

⚠️ 2026-07-26 CR-021 GEO-3/GEO-4 — 법정동이 같아도 다른 단지다
--------------------------------------------------------------
GEO-1 수정으로 법정동 교차충돌이 68 → 0 이 되자 "남은 좌표 충돌 199건은 전부 같은
법정동 안의 동일 단지"라고 결론냈는데, **같은 라운드에 적재한 부동산원 마스터가
그걸 반증했다** — 같은 점을 쓰면서 단지고유번호가 서로 다른 그룹이 15개(30단지).
법정동 대조는 "다른 동에 찍혔나"만 잡고, "같은 동 안에서 남의 단지에 붙었나"는
못 잡는다. 그래서 두 가지를 고쳤다:

- **GEO-3**: `same_complex` 가 `reb_complex_id` 를 **부정 증거로도** 쓴다. 양쪽 다
  번호가 있고 서로 다르면 그 자리에서 '다른 단지' — 이름 유사도로 구제하지 않는다
  (`different_reb_complex`). 이미 들어간 오좌표는 `unsafe_shared_ids` 로 재판정해
  비우고 주소 경로로 다시 확보했다.
- **GEO-4**: 차수 가드(`name_phases`)를 **채택 단계**(`name_matches`)에도 넣었다.
  `same_complex`·`reb._hit` 에만 있어서 '신현대12차'↔'신현대11차'(유사도 0.833)가
  채택 단계를 통과했다(같은 법정동 685쌍). 충돌 게이트는 좌표가 소수점 6자리까지
  같을 때만 막아 주므로, 옆 단지의 다른 출입구 좌표를 받으면 그대로 들어간다.

⚠️ 키·합법성
-----------
- KAKAO_REST_API_KEY 는 사람이 발급한다(.env). 없으면 NullGeocoder 로 동작(좌표 미확보).
- 카카오 로컬 API 는 개인·비상업 쿼터 내 사용. rate limit 준수(RateLimiter).
"""
from __future__ import annotations

import difflib
import re
from collections.abc import Callable, Iterable
from dataclasses import dataclass, field
from typing import Any, Protocol

from app.ingest.ratelimit import RateLimiter

KAKAO_KEYWORD_URL = "https://dapi.kakao.com/v2/local/search/keyword.json"
KAKAO_ADDRESS_URL = "https://dapi.kakao.com/v2/local/search/address.json"

#: 수도권 대략 권역(경도·위도). 서비스 범위는 서울+경기+인천(CLAUDE.md)이다.
#: 카카오가 엉뚱한 지방 동명이인 장소를 돌려줬을 때 마지막 안전망으로 쓴다.
#: 넉넉히 잡는다 — 여기서 정밀하게 자를 게 아니라 명백한 이상치만 걸러내는 용도다.
CAPITAL_BBOX = (125.9, 36.8, 127.9, 38.4)   # (min_lon, min_lat, max_lon, max_lat)

#: 응답 후보를 몇 개까지 받아 검증할지. 1위가 틀렸어도 2~5위에 정답이 있는 경우가 많다.
#: 이전 구현은 size=1 로 "1위=정답"을 가정했고, 그게 좌표 충돌 514건의 뿌리였다.
SEARCH_SIZE = 5

#: region.sido('서울특별시') → 카카오 address_name 표기('서울')
_SIDO_SHORT = {"서울특별시": "서울", "인천광역시": "인천", "경기도": "경기"}


# ---------------------------------------------------------------------------
# 값 객체
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class Place:
    """카카오 장소 1건 — **검증에 필요한 것만** 담는다.

    좌표는 x=경도(lon), y=위도(lat) 로 온다 — 순서를 뒤집으면 지도에서 바다에 찍힌다.
    """

    lon: float
    lat: float
    place_name: str = ""
    address_name: str = ""          # 지번 주소: '서울 강남구 대치동 977'
    road_address_name: str = ""
    category_name: str = ""


@dataclass(frozen=True)
class AddressHit:
    """카카오 **주소검색** 결과 1건 — 검증에 필요한 것만.

    키워드검색(Place)과 달리 장소명이 없다. 대신 `b_code`(법정동코드)·본번·부번이
    구조화돼 오므로 문자열이 아니라 **코드로** 대조할 수 있다.
    """

    lon: float
    lat: float
    address_name: str = ""          # '서울 종로구 청운동 56-45'
    address_type: str = ""          # REGION / ROAD / REGION_ADDR / ROAD_ADDR
    b_code: str = ""                # 법정동코드 10자리 '1111010100'
    main_no: int | None = None      # 본번 56
    sub_no: int = 0                 # 부번 45 (없으면 0)
    is_mountain: bool = False
    building_name: str = ""         # 도로명주소의 건물명 — 참고용(검증에는 쓰지 않는다)


@dataclass(frozen=True)
class GeoTarget:
    """지오코딩 대상. **질의 문자열이 아니라 구조**를 넘긴다 — 검증에 원본이 필요하다.

    질의어만 넘기던 이전 설계에서는 "무엇을 찾으려 했는지"가 응답 시점에 사라져서
    돌려받은 좌표가 맞는지 대조할 방법이 아예 없었다(GEO-1 의 구조적 원인).

    `address` 이하는 **부동산원 단지 마스터와 매칭된 단지**에만 채워진다(REB-1).
    비어 있으면 주소 경로를 아예 시도하지 않는다 — 주소를 추정해 만들지 않는다.
    """

    name: str
    legal_dong: str = ""
    sigungu: str = ""               # '강남구' · '성남시 분당구'
    sido: str = ""                  # '서울특별시'
    # --- 주소 경로(부동산원 매칭분) ---
    address: str = ""               # '서울특별시 종로구 청운동 56-45'
    legal_dong_code: str = ""       # '1111010100' — 카카오 b_code 와 코드 대조
    main_no: int | None = None      # 본번
    sub_no: int = 0                 # 부번
    is_mountain: bool = False
    #: 부동산원 단지고유번호. **같은 값이면 같은 단지**다(엄격 매칭을 통과한 것) —
    #: MOLIT 이름 오염으로 갈라진 행들이 좌표를 공유해도 되는지 판정하는 데 쓴다.
    reb_id: str = ""


@dataclass(frozen=True)
class GeoFix:
    """검증을 통과한 좌표 1건."""

    lon: float
    lat: float
    #: 'exact'   = 원본 단지명 그대로 찾음
    #: 'variant' = 지번·동목록을 떼어낸 이름으로 찾음(한 단계 덜 확실 — 표시용으로 남긴다)
    #: 'address' = 부동산원 매칭 단지의 지번주소로 찾음(법정동코드·본번·부번까지 일치)
    confidence: str = "exact"
    query: str = ""
    matched_name: str = ""
    matched_address: str = ""
    #: 좌표 출처 — DB `complex.geom_source` 에 그대로 들어간다(마이그레이션 007/008).
    source: str = "kakao_keyword"


# ---------------------------------------------------------------------------
# 이름 정리 — 보수적으로 (CR-020 통과조건 4)
# ---------------------------------------------------------------------------

#: 동(棟) 한 토막: '103동'(숫자) 또는 '가동·에이동'(한글 1~2자).
#: 더 길게 잡으면 '청학아파트에이동' 에서 '파트에이동' 까지 먹어 단지명이 잘린다.
_DONG_TOKEN = r"(?:\d{1,4}동|[가-힣]{1,2}동)"
#: 이름 **끝**에 붙은 동 나열: '…아파트1동,2동,3동' / '…에이동,비동,씨동'
_DONG_LIST_TAIL = re.compile(rf"{_DONG_TOKEN}(?:\s*[,·~-]\s*{_DONG_TOKEN})*\s*$")
#: 괄호 묶음 하나 (내용은 그룹 1)
_PAREN_GROUP = re.compile(r"[(\[（【]([^)\]）】]*)[)\]）】]")
#: 괄호 안이 **지번·번호**뿐: '(963)' '(1002-10)' '(1511-3)' '(23)'
_PAREN_NUMERIC = re.compile(r"^[\d\s,~./-]+$")
#: 괄호 안이 **동 목록**뿐: '(103동)' '(101동~103동)' '(10,11,20,23,24,25동)'
#: 마지막 토막에만 '동'이 붙는 표기('10,11,…,25동')가 실제로 가장 흔하다.
_PAREN_DONGS = re.compile(
    rf"^\s*(?:{_DONG_TOKEN}|\d{{1,4}})(?:\s*[,·~-]\s*(?:{_DONG_TOKEN}|\d{{1,4}}))*\s*$")


def _strip_parens(name: str) -> str:
    """괄호 묶음 중 **지번·동목록만** 제거한다.

    ⚠️ 여기가 GEO-1 의 핵심이다. 이전 구현은 괄호를 전부 떼어서
       '탑마을(경남)1'·'탑마을(기산)1'·'탑마을(선경)1'·'탑마을(쌍용)1' 을 모두
       '탑마을1' 로 만들었고, 넷이 한 좌표에 뭉쳤다(야탑동 실측).
       괄호 안의 시공사('(경남)')·단지('(5-1단지)')·차수 표기는 **단지를 가르는 정보**다.
    """
    def _repl(m: re.Match[str]) -> str:
        inner = m.group(1).strip()
        if not inner or _PAREN_NUMERIC.match(inner) or _PAREN_DONGS.match(inner):
            return " "
        return m.group(0)                     # 단지·차·시공사 표기 → 그대로 둔다

    return _PAREN_GROUP.sub(_repl, name)


def strip_name_noise(name: str) -> str:
    """단지명에서 **검색을 방해하는 군더더기만** 떼어낸다(지번·동 나열).

    수집원(MOLIT)의 단지명을 **바꾸지 않는다** — 검색어를 만들 때만 쓴다.
    저장된 이름은 자연키의 일부라 건드리면 중복 판정이 무너진다(normalize.py).
    """
    out = _strip_parens(name or "")
    out = _DONG_LIST_TAIL.sub("", out)
    return re.sub(r"\s+", " ", out).strip(" ,·-")


#: 카카오는 단지 안의 **부속시설도 별도 장소**로 준다:
#:   '반포훼밀리아파트 경비실' · '가락우성아파트 상가' · '…입주자대표회의-2 전기차충전소'
#: 좌표는 단지 부지 안이라 쓸 만한데, 이름만 보고 버리면 멀쩡한 단지가 지도에서 사라진다
#: (2026-07-26 표본 진단에서 확인). 꼬리만 떼고 단지명으로 대조한다.
_FACILITY_TAIL = re.compile(
    r"(?:경비실|관리사무소|입주자대표회의|커뮤니티센터|주민센터|지하주차장|주차장입구|주차장|"
    r"정문|후문|출입구|게이트|전기차충전소|충전소|상가|어린이집|놀이터|택배보관함)"
    r"[\s\dA-Za-z-]*$")


def _strip_facility(name: str) -> str:
    """장소명 끝의 부속시설 표기를 떼어낸다('…아파트 지하주차장' → '…아파트')."""
    out = (name or "").strip()
    for _ in range(3):                            # '…대표회의-2 전기차충전소' 처럼 겹쳐 온다
        stripped = _FACILITY_TAIL.sub("", out).strip(" -·")
        if stripped == out or not stripped:
            break
        out = stripped
    return out


def place_core(place_name: str) -> str:
    """카카오 장소명 → 대조용 단지명. 부속시설 꼬리와 동 나열을 뗀다."""
    return strip_name_noise(_strip_facility(place_name))


_NON_NAME = re.compile(r"[^0-9A-Za-z가-힣]")


def _squeeze(s: str) -> str:
    """비교용 축약 — 공백·기호를 지우고 소문자로. 'e편한세상'과 'E-편한세상'을 같게 본다."""
    return _NON_NAME.sub("", s or "").lower()


def _drop_apt(s: str) -> str:
    """'아파트' 표기 차이 흡수. 다 지워 빈 문자열이 되면 원본을 유지한다."""
    return s.replace("아파트", "") or s


def name_key(name: str) -> str:
    """비교용 축약 키 — 지번·동목록을 떼고 공백·기호를 지운 소문자."""
    return _squeeze(strip_name_noise(name))


def comparable_names(name: str) -> tuple[str, ...]:
    """대조용 축약형들 — (축약, '아파트' 제거본). 같으면 하나만.

    부동산원 매칭(app/ingest/reb.py)이 좌표 채택과 **같은 이름 규칙**을 쓰도록
    여기서 한 번만 정의한다. 두 곳에서 따로 정리하면 규칙이 조용히 갈라진다.
    """
    key = name_key(name)
    dropped = _drop_apt(key)
    return (key,) if dropped == key else (key, dropped)


def similarity(a: str, b: str) -> float:
    """축약된 두 이름의 유사도(0~1). 임계값은 쓰는 쪽이 정한다."""
    return difflib.SequenceMatcher(None, a, b).ratio()


# ---------------------------------------------------------------------------
# 검증 — 카카오가 돌려준 것이 **내가 찾던 것**인가
# ---------------------------------------------------------------------------

#: 표기 차이만 흡수하는 선('훼미리'/'훼밀리'=0.80). 더 낮추면 다른 단지가 붙기 시작한다:
#:   '무지개마을4단지' vs '무지개마을청구' = 0.67 · '우성2' vs '우성5' = 0.67
#: 유사도는 **좌표 채택**에만 쓰고, 좌표를 공유시켜 주는 판정(same_complex)에는 쓰지 않는다.
NAME_SIMILARITY = 0.80


def _compare(a_raw: str, b_raw: str, *, fuzzy: bool) -> bool:
    """정리된 두 이름이 같은 단지를 가리키는가. `fuzzy` 면 유사도까지 인정한다.

    2자 이하 축약형은 '서초'가 '서초그랑자이'에 걸리는 식의 오매칭이 나므로
    포함을 인정하지 않고 **완전 일치만** 본다.
    """
    a0, b0 = _squeeze(a_raw), _squeeze(b_raw)
    if len(a0) < 2 or len(b0) < 2:
        return False
    for a, b in ((a0, b0), (_drop_apt(a0), _drop_apt(b0))):
        if not a or not b:
            continue
        if a == b:
            return True
        short, long_ = (a, b) if len(a) <= len(b) else (b, a)
        if len(short) >= 3 and short in long_:
            return True
        if fuzzy and difflib.SequenceMatcher(None, a, b).ratio() >= NAME_SIMILARITY:
            return True
    return False


def name_contains(a_name: str, b_name: str) -> bool:
    """두 단지명이 **같거나 한쪽이 다른 쪽을 통째로 품는가**(퍼지 매칭 없음)."""
    return _compare(strip_name_noise(a_name), strip_name_noise(b_name), fuzzy=False)


def name_matches(target_name: str, place_name: str) -> bool:
    """질의한 단지명과 카카오 `place_name` 이 같은 단지를 가리키는가.

    양쪽을 **같은 방식으로** 정리한 뒤 비교한다. 이전에는 내 이름만 정리하고
    카카오 이름은 날것으로 비교해서 '반포훼미리' vs '반포훼밀리아파트 102동' 같은
    **맞는 좌표를 버렸다**(2026-07-26 표본 진단).

    ⚠️ 2026-07-26 CR-021 GEO-4 — 차수 가드는 **채택 단계에도** 있어야 한다
       `same_complex`(공유)와 `reb._hit`(매칭)에는 차수 대조가 있었는데 여기에만
       없었다. 그래서 유사도 0.80 이 '신현대12차'↔'신현대11차'(0.833),
       '두산위브2단지'↔'두산위브1단지'(0.857) 를 **수락**했다(같은 법정동 685쌍).
       충돌 게이트가 막아준 건 좌표가 소수점 6자리까지 같을 때뿐이라, 카카오가
       옆 단지의 다른 출입구 좌표를 주면 몇 m 어긋난 채 그대로 채택된다.
       세 곳이 같은 규칙을 쓰게 만든다 — 차수가 다르면 어디서도 같은 단지가 아니다.
    """
    core = place_core(place_name)
    if name_phases(target_name) != name_phases(core):
        return False                       # '신현대11차' vs '신현대12차'
    return _compare(strip_name_noise(target_name), core, fuzzy=True)


def dong_matches(place: Place, legal_dong: str) -> bool:
    """카카오 주소의 법정동이 질의한 법정동과 같은가.

    **cross-dong 오매칭(68건)을 정면으로 겨냥한 검증이다.** '도곡동 대우디오빌'을
    질의했는데 카카오 지번주소가 '서울 강남구 역삼동 736-24' 면 여기서 걸린다.
    지번주소가 아예 없으면 확인할 수 없으므로 **불합격**으로 본다(모르면 넣지 않는다).
    '당산동4가' 처럼 가(街)까지 있는 표기는 그대로 비교한다(당산동4가 ≠ 당산동5가).

    ⚠️ GEO-8 — 읍·면 지역은 법정동명이 **두 토막**이다
    ------------------------------------------------
    MOLIT 은 읍·면 지역에서 `umdNm` 을 '오남읍 오남리' 처럼 두 토막으로 준다.
    예전 구현은 `dong in addr.split()` 이라 두 토막짜리 이름이 **어떤 주소와도 절대
    같아질 수 없었고**, 그 결과 경기 외곽 읍·면 단지는 검색 결과가 맞아도 전부
    불합격 → 좌표 없음 → 지도에서 사라졌다(실측 1,009단지). 코드가 통과 불가능한
    조건을 걸어 놓은 것이라 "엄격"이 아니라 결함이다.
    이제 **모든 토막이 주소에 있어야** 통과한다 — 한 토막짜리 이름에 대해서는
    예전과 완전히 같고, 두 토막짜리는 '오남읍'과 '오남리' 를 **둘 다** 요구하므로
    느슨해지지 않는다.
    """
    dong = (legal_dong or "").strip()
    addr = (place.address_name or "").strip()
    if not dong or not addr:
        return False
    parts = addr.split()
    return all(tok in parts for tok in dong.split())


def region_matches(place: Place, target: GeoTarget) -> bool:
    """시도·시군구가 맞는가(권역 검증). 시군구는 **앞 토막**으로 본다.

    '화성시 동탄구'(2025 신설)처럼 카카오 표기가 아직 안 따라온 경우가 있어
    '성남시 분당구' → '성남시', '화성시 동탄구' → '화성시' 로 느슨하게 확인한다.
    법정동 검증(dong_matches)이 이미 촘촘하므로 여기서 더 조일 필요는 없다.
    """
    addr = f"{place.address_name} {place.road_address_name}"
    sido_short = _SIDO_SHORT.get(target.sido, target.sido).strip()
    if sido_short and sido_short not in addr:
        return False
    head = (target.sigungu or "").split()
    if head and head[0] not in addr:
        return False
    return True


def in_capital_bbox(lon: float, lat: float) -> bool:
    min_lon, min_lat, max_lon, max_lat = CAPITAL_BBOX
    return min_lon <= lon <= max_lon and min_lat <= lat <= max_lat


def verify(place: Place, target: GeoTarget) -> bool:
    """이 장소를 이 단지의 좌표로 채택해도 되는가. **하나라도 어긋나면 안 된다.**"""
    return (in_capital_bbox(place.lon, place.lat)
            and dong_matches(place, target.legal_dong)
            and region_matches(place, target)
            and name_matches(target.name, place.place_name))


#: 채택 가능한 주소 종류. **REGION 은 받지 않는다** — 지번을 못 찾았을 때 카카오가 주는
#: '동 단위' 결과라, 이걸 믿으면 한 법정동의 단지가 전부 동 중심점 하나로 뭉친다
#: (GEO-1 의 514건 뭉침과 정확히 같은 실패). ROAD 도 도로 자체라 받지 않는다.
ADDRESS_TYPES_OK = ("REGION_ADDR", "ROAD_ADDR")


def verify_address(hit: AddressHit, target: GeoTarget) -> bool:
    """이 주소 결과를 이 단지의 좌표로 채택해도 되는가.

    이름 대조가 없는 대신 **코드·번지로** 대조한다. 이름 대조는 이미 앞 단계(부동산원
    매칭)에서 엄격하게 끝났고, 여기서 확인할 것은 "카카오가 내가 물어본 그 필지를
    돌려줬는가"다. 대조할 근거(법정동코드·본번)가 없으면 **불합격**이다 — 모르면 넣지 않는다.
    """
    if not target.legal_dong_code or target.main_no is None:
        return False
    return (in_capital_bbox(hit.lon, hit.lat)
            and hit.address_type in ADDRESS_TYPES_OK
            and hit.b_code == target.legal_dong_code
            and hit.main_no == target.main_no
            and hit.sub_no == target.sub_no
            and hit.is_mountain == target.is_mountain)


# ---------------------------------------------------------------------------
# 질의 생성
# ---------------------------------------------------------------------------

def build_query(key: Any) -> str:
    """단지 키(ComplexKey/GeoTarget) → 카카오 질의. '법정동 단지명'이 매칭률이 가장 높다."""
    parts = [p for p in (getattr(key, "legal_dong", ""), getattr(key, "name", "")) if p]
    return " ".join(parts).strip()


def query_variants(target: GeoTarget) -> list[tuple[str, str]]:
    """(질의어, confidence) 목록. **원본이 항상 먼저다.**

    군더더기를 떼는 건 원본이 실패했을 때뿐이다 — 짧게 자를수록 다른 단지에 걸릴
    위험이 커진다. 법정동은 질의에서도 검증에서도 절대 떼지 않는다.
    """
    dong = (target.legal_dong or "").strip()
    original = " ".join(p for p in (dong, (target.name or "").strip()) if p).strip()
    out: list[tuple[str, str]] = []
    if original:
        out.append((original, "exact"))
    core = strip_name_noise(target.name)
    # 단지명이 통째로 사라졌으면(법정동만 남음) 후보로 쓰지 않는다 — 동 전체를 찍게 된다.
    if len(_squeeze(core)) >= 2:
        variant = " ".join(p for p in (dong, core) if p).strip()
        if variant and variant != original:
            out.append((variant, "variant"))
    return out


# ---------------------------------------------------------------------------
# 검색 백엔드
# ---------------------------------------------------------------------------

class PlaceSearch(Protocol):
    def search(self, query: str) -> list[Place]:
        """질의어 → 장소 후보(상위 N). 결과가 없으면 빈 리스트."""
        ...


class NullPlaceSearch:
    """검색을 하지 않는다(키 미발급 등). 항상 빈 결과."""

    def search(self, query: str) -> list[Place]:
        return []


#: (url, headers, params) → 파싱된 JSON dict. 테스트에서 네트워크 없이 주입한다.
HttpGet = Callable[[str, dict[str, str], dict[str, str]], dict[str, Any]]


def _httpx_get(url: str, headers: dict[str, str], params: dict[str, str]) -> dict[str, Any]:
    """카카오 로컬 GET. 예외는 **비밀을 지운 형태로** 감싸 올린다(SR17-1).

    카카오는 키를 `Authorization` 헤더로 받으므로 URL 자체에는 키가 없지만,
    이 함수도 키를 아는 계층이다. 헤더·URL 이 예외·traceback 에 실려 나가는 경로를
    구조적으로 막아 둔다 — 호출부가 기억해서 지우게 두지 않는다.
    """
    import json as _json

    import httpx

    from app.core.http import request_capped
    from app.core.masking import masked_error

    secrets = tuple(v.split(" ", 1)[-1] for k, v in headers.items()
                    if k.lower() in ("authorization", "x-api-key"))
    try:
        # ⚠️ SR25-1 — 예전에는 `httpx.get(...).json()` 이었다. `.json()` 은 본문을
        #    **전부 읽은 뒤** 파싱하므로 상한이 없었다. 스트리밍으로 받으면서 센다.
        _resp, body = request_capped(httpx, "GET", url, headers=headers,
                                     params=params, timeout=20.0,
                                     what="카카오 로컬")
        return _json.loads(body)
    except Exception as exc:                     # noqa: BLE001 - 마스킹해 다시 올린다
        raise masked_error(exc, prefix="카카오 로컬 요청 실패: ",
                           extra_secrets=secrets) from None


class KakaoPlaceSearch:
    """카카오 로컬 키워드 검색. **후보를 여러 개 받아** 검증 계층에 넘긴다."""

    def __init__(self, rest_api_key: str, *,
                 http_get: HttpGet = _httpx_get,
                 rate_limiter: RateLimiter | None = None,
                 size: int = SEARCH_SIZE) -> None:
        if not rest_api_key:
            raise ValueError("KAKAO_REST_API_KEY 가 필요합니다")
        self._key = rest_api_key
        self._get = http_get
        self._size = size
        self._limiter = rate_limiter or RateLimiter(min_interval_sec=0.3, jitter_sec=0.2)

    @property
    def rate_limiter(self) -> RateLimiter:
        """속도 제한기. 키워드·주소 백엔드가 **같은 인스턴스를 공유해야** 실효 간격이
        설정값대로 지켜진다(SR18-7). 호출부가 그걸 지켰는지 밖에서 확인할 수 있게 연다."""
        return self._limiter

    def search(self, query: str) -> list[Place]:
        if not query.strip():
            return []
        self._limiter.wait()                       # rate limit — 카카오 쿼터·차단 회피
        headers = {"Authorization": f"KakaoAK {self._key}"}
        data = self._get(KAKAO_KEYWORD_URL, headers,
                         {"query": query, "size": str(self._size)})
        out: list[Place] = []
        for doc in (data.get("documents") or []):
            try:
                out.append(Place(
                    lon=float(doc["x"]), lat=float(doc["y"]),
                    place_name=str(doc.get("place_name") or ""),
                    address_name=str(doc.get("address_name") or ""),
                    road_address_name=str(doc.get("road_address_name") or ""),
                    category_name=str(doc.get("category_name") or ""),
                ))
            except (KeyError, TypeError, ValueError):
                continue                            # 좌표가 깨진 문서는 버린다
        return out


class AddressSearch(Protocol):
    def search(self, address: str) -> list[AddressHit]:
        """지번주소 → 주소 후보. 결과가 없으면 빈 리스트."""
        ...


class NullAddressSearch:
    """주소 검색을 하지 않는다(부동산원 매칭 전 · 키 미발급 등). 항상 빈 결과."""

    def search(self, address: str) -> list[AddressHit]:
        return []


def _int_or_none(value: Any) -> int | None:
    raw = str(value or "").strip()
    return int(raw) if raw.isdigit() else None


class KakaoAddressSearch:
    """카카오 로컬 **주소검색**. 지번주소 → 필지 좌표.

    키워드검색과 같은 rate limiter 규약을 따른다(쿼터·차단 회피). 응답의
    `address` 블록에 법정동코드(`b_code`)와 본번·부번이 들어 있어 검증이 단단해진다.
    """

    def __init__(self, rest_api_key: str, *,
                 http_get: HttpGet = _httpx_get,
                 rate_limiter: RateLimiter | None = None,
                 size: int = SEARCH_SIZE) -> None:
        if not rest_api_key:
            raise ValueError("KAKAO_REST_API_KEY 가 필요합니다")
        self._key = rest_api_key
        self._get = http_get
        self._size = size
        self._limiter = rate_limiter or RateLimiter(min_interval_sec=0.3, jitter_sec=0.2)

    @property
    def rate_limiter(self) -> RateLimiter:
        """SR18-7 — 키워드 백엔드와 **같은 인스턴스**여야 한다. `KakaoPlaceSearch` 참조."""
        return self._limiter

    def search(self, address: str) -> list[AddressHit]:
        if not address.strip():
            return []
        self._limiter.wait()
        headers = {"Authorization": f"KakaoAK {self._key}"}
        data = self._get(KAKAO_ADDRESS_URL, headers,
                         {"query": address, "size": str(self._size)})
        out: list[AddressHit] = []
        for doc in (data.get("documents") or []):
            addr = doc.get("address") or {}
            road = doc.get("road_address") or {}
            try:
                out.append(AddressHit(
                    lon=float(doc["x"]), lat=float(doc["y"]),
                    address_name=str(doc.get("address_name") or ""),
                    address_type=str(doc.get("address_type") or ""),
                    b_code=str(addr.get("b_code") or ""),
                    main_no=_int_or_none(addr.get("main_address_no")),
                    sub_no=_int_or_none(addr.get("sub_address_no")) or 0,
                    is_mountain=str(addr.get("mountain_yn") or "N").upper() == "Y",
                    building_name=str(road.get("building_name") or ""),
                ))
            except (KeyError, TypeError, ValueError):
                continue                            # 좌표가 깨진 문서는 버린다
        return out


# ---------------------------------------------------------------------------
# 지오코더
# ---------------------------------------------------------------------------

class Geocoder(Protocol):
    def locate(self, target: GeoTarget) -> GeoFix | None:
        """단지 → 검증을 통과한 좌표. 확신이 없으면 None."""
        ...


class NullGeocoder:
    """좌표를 확보하지 않는다(키 미발급 등). 항상 None — 도메인이 '정보 없음' 처리."""

    #: 진단 코드 자리를 맞춰 둔다(enrich_geom 이 읽는다).
    last_reason: str = "no_result"

    def locate(self, target: GeoTarget) -> GeoFix | None:
        return None


class VerifiedGeocoder:
    """검색 결과를 **대조해서 통과한 것만** 좌표로 채택한다.

    후보 1위를 믿지 않는다. 질의 변형마다 상위 N 후보를 훑어 법정동·시군구·이름이
    모두 맞는 첫 후보를 쓰고, 없으면 좌표를 비운다 — 확보율보다 정확도가 먼저다.

    부동산원 주소가 있으면 **주소를 먼저** 본다(REB-1). 이름 오염이 개입하지 않고
    법정동코드·본번까지 대조되므로 이름 경로보다 확실하다. 주소가 없거나 주소로
    확인되지 않으면 기존 키워드 경로로 내려간다 — 두 경로 모두 검증을 통과해야 한다.
    """

    def __init__(self, search: PlaceSearch,
                 address_search: AddressSearch | None = None) -> None:
        self._search = search
        self._address = address_search or NullAddressSearch()
        #: 진단용 — 왜 못 찾았는지. 'no_result'(검색 0건) / 'mismatch'(검증 불합격)
        self.last_reason: str = ""
        #: 진단용 — 어느 경로로 확보/실패했는지. 'address' / 'keyword'
        self.last_path: str = ""

    @property
    def backends(self) -> tuple[PlaceSearch, AddressSearch]:
        """(키워드, 주소) 백엔드. 배선이 맞는지 밖에서 확인할 수 있게 연다.

        특히 **둘이 같은 속도 제한기를 쓰는지**(SR18-7)를 테스트가 확인한다 —
        따로 만들면 카카오 실효 호출 간격이 설정값의 절반이 된다.
        """
        return self._search, self._address

    def _by_address(self, target: GeoTarget) -> tuple[GeoFix | None, bool]:
        """(좌표, 후보를 하나라도 봤는가)."""
        hits = self._address.search(target.address)
        for hit in hits:
            if verify_address(hit, target):
                return GeoFix(lon=hit.lon, lat=hit.lat, confidence="address",
                              query=target.address, matched_name=hit.building_name,
                              matched_address=hit.address_name,
                              source="kakao_address"), True
        return None, bool(hits)

    def locate(self, target: GeoTarget) -> GeoFix | None:
        self.last_reason = ""
        self.last_path = ""
        saw_any = False

        if target.address:
            fix, saw = self._by_address(target)
            saw_any = saw_any or saw
            if fix is not None:
                self.last_path = "address"
                return fix
            self.last_path = "address"

        for query, confidence in query_variants(target):
            places = self._search.search(query)
            saw_any = saw_any or bool(places)
            for place in places:
                if verify(place, target):
                    self.last_path = "keyword"
                    return GeoFix(lon=place.lon, lat=place.lat, confidence=confidence,
                                  query=query, matched_name=place.place_name,
                                  matched_address=place.address_name)
        self.last_reason = "mismatch" if saw_any else "no_result"
        return None


# ---------------------------------------------------------------------------
# 좌표 충돌 — 두 단지가 같은 점을 쓰면 최소 하나는 틀렸다
# ---------------------------------------------------------------------------

#: 좌표 동일 판정 자릿수. 1e-6도 ≒ 0.11m — 같은 POI 를 잡으면 값이 완전히 같다.
POINT_DECIMALS = 6


def point_key(lon: float, lat: float) -> tuple[float, float]:
    return (round(lon, POINT_DECIMALS), round(lat, POINT_DECIMALS))


#: 차수·단지 번호 — '2차'·'3단지'. 이게 다르면 **다른 단지**다(신현대11차 ≠ 신현대12차).
_PHASE_TOKEN = re.compile(r"\d+(?:차|단지)")


def name_phases(name: str) -> frozenset[str]:
    """이름에 든 차수·단지 번호들. 다르면 **다른 단지**다 — 매칭·좌표공유 양쪽에서 쓴다."""
    return frozenset(_PHASE_TOKEN.findall(name_key(name)))


#: 내부 별칭(기존 호출부 유지).
_phases = name_phases


#: 괄호 안이 **지번 표기**인 토막: '(963)' '(1002-10)' '(1057-0)'.
#: '동'이 들어간 것은 제외한다 — '(101동)' '(10,11,25동)' 은 **한 단지의 동 목록**이다.
_PAREN_JIBUN = re.compile(r"^[\d]+(?:-[\d]+)?$")


def paren_jibun(name: str) -> frozenset[str]:
    """이름의 괄호 안 **지번 표기**들. 다르면 다른 단지다 (CR-022 GEO-6).

    ⚠️ 2026-07-26 실측으로 뒤집힌 판단
    ------------------------------------
    이 모듈은 원래 '삼환나띠르빌(1002-10)' ~ '(1002-22)' 를 "지번만 다른 **한 단지**"로
    보고 좌표 공유를 허용했다. 부동산원 마스터가 그걸 반증한다 — 그 표기들은
    **각각 별개의 단지고유번호**를 가진 서로 다른 단지다:

        11650100249289 삼환나띠르빌(1002-7)   15세대
        11650100003082 삼환나띠르빌(1002-8)   30세대
        11650100050186 삼환나띠르빌(1002-9)   19세대
        11650100050187 삼환나띠르빌(1002-10)  16세대   ← '한 단지'가 아니다
        ...

    괄호 안 지번은 MOLIT 이 지어낸 표기가 아니라 **공시가격 단지명 표기 그대로**다
    (부동산원 `name_price` 가 문자 하나까지 같다). 즉 이건 잡음이 아니라 **식별자**다.
    좌표를 공유하던 16개 그룹/37단지를 전수 대조한 결과 **전부** 부동산원에서 서로 다른
    단지로 확인됐다(뉴월드 402-42/402-120, 근상프리즘 4건, 광남캐스빌, 우성 23/1058 …).

    본번만 비교하면 안 되는 이유도 같은 데이터가 보여준다 — '뉴월드(402-42)' 와
    '뉴월드(402-120)' 는 **본번이 같은데도 다른 단지**다. 그래서 부번까지 포함한
    **표기 전체**로 비교한다. 부번 0 은 '(666)'/'(666-0)' 두 표기가 섞이므로 정규화한다.
    """
    out: set[str] = set()
    for m in _PAREN_GROUP.finditer(name or ""):
        inner = m.group(1).strip().replace(" ", "")
        if not _PAREN_JIBUN.match(inner):
            continue                       # 동 목록·시공사·차수 표기는 여기서 보지 않는다
        main, _, sub = inner.partition("-")
        out.add(main if sub in ("", "0") else inner)
    return frozenset(out)


def different_parcel(a: GeoTarget, b: GeoTarget) -> bool:
    """양쪽 다 괄호 지번 표기가 있고 **서로 다른가** — 다른 단지라는 증거.

    한쪽이 비어 있으면 "모른다"이지 "다르다"가 아니다(different_reb_complex 와 같은 규약).
    '롯데캐슬' 과 '롯데캐슬(1057-1)' 은 여기서 갈리지 않는다 — 앞의 것이 어느 지번인지
    모르기 때문이다.
    """
    pa, pb = paren_jibun(a.name), paren_jibun(b.name)
    return bool(pa) and bool(pb) and pa != pb


def same_complex(a: GeoTarget, b: GeoTarget) -> bool:
    """두 행이 **같은 단지가 이름만 갈라진 것**인가(MOLIT 이름 오염).

    '대치우성아파트1동,2동' 과 '대치우성' 은 동 나열만 다른 한 단지다 — 같은 좌표가 맞다.
    반면 '탑마을(경남)1' 과 '탑마을(기산)1' 은 시공사가 다른 **다른 단지**다.
    _strip_parens 가 시공사·단지·차수 표기를 남기므로 여기서 갈린다.

    ⚠️ 2026-07-26 CR-022 GEO-6 — 괄호 안 **지번**은 잡음이 아니라 식별자다
       예전 주석은 '삼환나띠르빌(1002-10)' ~ '(1002-22)' 를 "지번만 다른 한 단지"라고
       적어 두고 좌표 공유를 허용했는데, 부동산원 마스터가 그걸 반증했다 —
       그 표기들은 각각 별개의 단지고유번호를 가진 **서로 다른 단지**다(paren_jibun).

    ⚠️ 여기서는 유사도(퍼지) 매칭을 쓰지 않는다. 좌표를 **공유시켜 주는** 판정이라
       느슨하면 곧바로 오좌표가 된다 — 이름이 같거나 한쪽을 통째로 품을 때만 인정한다.
       포함만으로는 '신세계' ⊂ '신세계3차' 가 통과하므로 차수까지 대조한다
       (2026-07-26 재검증 후 남은 217건 중 9건이 이 유형이었다).

    ⚠️ 2026-07-26 CR-021 GEO-3 — 부동산원 번호는 **부정 증거로도** 쓴다
       이전 구현은 `same_reb_complex` 를 긍정 신호로만 썼다. 양쪽 다 번호가 있고
       **서로 다를 때**(= 부동산원이 "다른 단지"라고 말할 때) 그 사실을 버리고
       이름 포함 판정으로 내려갔고, '대우디오빌' ⊂ '대우디오빌플러스' 가 통과해
       역삼동 720-25(457세대)와 824-25(168세대)가 한 점을 공유했다(운영 DB 15그룹/30단지).
       이름은 오염될 수 있지만 번호는 "후보 2개 이상이면 아무것도 안 쓴다"는 엄격
       매칭을 통과한 값이다 — **번호가 이름을 이긴다.**
    """
    if same_reb_complex(a, b):
        return True                               # 부동산원 단지고유번호가 같다 — 확정
    if different_reb_complex(a, b):
        return False                              # 부동산원이 다른 단지라고 말한다 — 확정
    if different_parcel(a, b):
        return False                              # 괄호 안 지번이 다르다(GEO-6) — 확정
    if (a.legal_dong or "").strip() != (b.legal_dong or "").strip():
        return False                              # 법정동이 다르면 같은 단지일 수 없다
    if _phases(a.name) != _phases(b.name):
        return False                              # 2차 ≠ 3차 — 붙이면 두 단지가 한 점이 된다
    return name_contains(a.name, b.name)


def same_reb_complex(a: GeoTarget, b: GeoTarget) -> bool:
    """부동산원 단지고유번호가 같은가 — **이름을 거치지 않는 동일 단지 판정**.

    MOLIT 이름 오염('대치우성아파트1동,2동' vs '대치우성')으로 한 단지가 여러 행으로
    갈라져도, 둘 다 같은 부동산원 단지에 (애매하지 않게) 매칭됐다면 같은 단지다.
    이름 대조로는 못 붙는 쌍까지 안전하게 좌표를 공유시킨다.
    """
    return bool((a.reb_id or "").strip()) and a.reb_id == b.reb_id


def different_reb_complex(a: GeoTarget, b: GeoTarget) -> bool:
    """부동산원 단지고유번호가 **양쪽 다 있고 서로 다른가** — 다른 단지라는 결정적 증거.

    한쪽이라도 비어 있으면 "모른다"이지 "다르다"가 아니다 — 그때는 판정하지 않는다
    (미매칭 단지끼리 이름으로 붙던 정상 경로를 막지 않기 위해서다).
    """
    ra, rb = (a.reb_id or "").strip(), (b.reb_id or "").strip()
    return bool(ra) and bool(rb) and ra != rb


def unsafe_shared_ids(
    entries: Iterable[tuple[int, GeoTarget, float, float]],
) -> list[int]:
    """이미 들어간 좌표를 **현재 규칙으로 재판정**해, 공유하면 안 되는 단지 id 를 낸다.

    왜 그룹을 통째로 내놓나
    -----------------------
    한 점에 모인 단지들은 **모든 쌍이** `same_complex` 여야 정당한 공유다. 하나라도
    어긋나면 그 점의 좌표 중 최소 하나는 틀렸는데, **어느 쪽이 틀렸는지는 알 수 없다**
    (역삼동 720-25 457세대와 824-25 168세대 중 카카오가 준 POI 의 주인이 누구인지
    좌표만 봐서는 모른다). 임의로 한쪽을 남기면 절반의 확률로 틀린 좌표를 승인하는
    셈이라, 모듈 원칙대로 **그룹 전체를 비우고 다시 확보**한다.

    `enrich_geom` 은 '먼저 온 단지 vs 새 단지'만 비교하므로 3개 이상 모인 점에서는
    2번·3번 단지끼리의 모순을 못 본다. 여기서는 전수 쌍을 본다 — 그래서 채택 시점에
    통과했던 조합도 재판정에서 걸릴 수 있다(그게 맞다).
    """
    groups: dict[tuple[float, float], list[tuple[int, GeoTarget]]] = {}
    for complex_id, target, lon, lat in entries:
        groups.setdefault(point_key(lon, lat), []).append((complex_id, target))

    unsafe: list[int] = []
    for members in groups.values():
        if len(members) < 2:
            continue
        ok = all(same_complex(a[1], b[1])
                 for a, b in _pairs(sorted(members, key=lambda m: m[0])))
        if not ok:
            unsafe.extend(m[0] for m in members)
    return sorted(unsafe)


def _pairs(items: list[tuple[int, GeoTarget]]):
    for i in range(len(items)):
        for j in range(i + 1, len(items)):
            yield items[i], items[j]


# ---------------------------------------------------------------------------
# 이름 경로 좌표 재검사 (CR-022 GEO-7)
# ---------------------------------------------------------------------------
#
# 무엇이 남아 있었나
# ------------------
# GEO-1~GEO-4 로 "다른 단지와 **완전히 같은 점**"은 걷어냈다. 하지만 충돌 게이트는
# 좌표가 소수점 6자리까지 같을 때만 도는 방어라, 카카오가 **옆 단지의 다른 출입구**나
# 같은 이름의 다른 건물을 주면 몇백 m 어긋난 채 조용히 들어간다.
# 표본 진단(319·320건)에서 이름 경로 좌표의 **약 2%가 주소 경로와 400m 넘게** 어긋났고,
# 모집단 4,530건에 외삽하면 약 90건이다.
#
# 왜 주소 쪽을 믿나
# -----------------
# 주소 경로는 이름을 아예 거치지 않고 **법정동코드·본번·부번·산번지**를 코드로 대조한다
# (verify_address). 단, 그 주소가 이 단지의 주소가 맞다는 근거는 부동산원 매칭이 대준다 —
# 그래서 **`name_exact`(단지명 완전일치)로 매칭된 건만** 이 판정을 적용한다.
# `name_contains`/`name_fuzzy` 는 매칭 자체가 덜 확실해서 **주소 쪽이 틀렸을 수 있다**
# (실측 예: '개포자이프레지던스' 1,317m — 여기서 주소를 믿고 덮으면 오류를 심는 것이다).
# 그런 건은 재판정만 하고 **손대지 않는다**(APPLIABLE_METHODS).

#: 지구 평균 반지름(m) — IUGG 평균반지름. 수도권 규모에서 haversine 오차는 무시할 수준이다.
EARTH_RADIUS_M = 6_371_008.8

#: 이름 경로와 주소 경로가 이만큼 넘게 어긋나면 **다른 곳을 가리키는 것**으로 본다.
#: 근거: 수도권 대단지도 대각선이 400m 를 넘는 경우가 드물고, 단지 정문 POI 와 필지
#: 대표점의 차이는 실측에서 대개 100m 안쪽이었다. 더 조이면 정상 편차를 오탐하고,
#: 더 풀면 '옆 단지'가 통과한다.
NAME_PATH_TOLERANCE_M = 400.0

#: 재판정 결과로 **좌표를 고쳐도 되는** 매칭 방법. 여기를 넓히지 말 것 — 위 주석 참조.
APPLIABLE_METHODS: tuple[str, ...] = ("name_exact",)


def haversine_m(lon1: float, lat1: float, lon2: float, lat2: float) -> float:
    """두 좌표 사이 대권거리(m). 투영 없이 계산해 PostGIS 없이도 검증할 수 있게 한다."""
    import math

    p1, p2 = math.radians(lat1), math.radians(lat2)
    dp = p2 - p1
    dl = math.radians(lon2 - lon1)
    a = math.sin(dp / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dl / 2) ** 2
    return 2 * EARTH_RADIUS_M * math.asin(min(1.0, math.sqrt(a)))


#: 재판정 결과 코드.
#:   'agree'      주소 경로 좌표와 허용범위 안 — 그대로 둔다
#:   'mismatch'   허용범위 밖 — 이름 경로 좌표가 틀렸다고 본다(무효화 대상)
#:   'unverified' 주소 후보는 왔지만 코드·번지 대조에 떨어짐 — **판정 불가**, 손대지 않는다
#:   'no_result'  주소 검색 0건 — 판정 불가, 손대지 않는다
SWEEP_STATUSES = ("agree", "mismatch", "unverified", "no_result")


@dataclass(frozen=True)
class SweepVerdict:
    """이름 경로로 넣은 좌표 1건에 대한 재판정 결과."""

    complex_id: int
    status: str
    #: 이름 경로 좌표 ↔ 주소 경로 좌표 거리(m). 주소를 확인하지 못했으면 None.
    distance_m: float | None = None
    #: 검증을 통과한 주소 경로 좌표. 'agree'/'mismatch' 일 때만 채워진다.
    fix: GeoFix | None = None

    @property
    def is_mismatch(self) -> bool:
        return self.status == "mismatch"


def sweep_verdict(target: GeoTarget, lon: float, lat: float,
                  hits: Iterable[AddressHit], *,
                  complex_id: int = 0,
                  tolerance_m: float = NAME_PATH_TOLERANCE_M) -> SweepVerdict:
    """이미 들어간 좌표(lon/lat)를 **주소 경로 결과와 대조**해 판정한다.

    판정만 한다 — DB 도 네트워크도 모른다. 그래서 이 규칙을 테스트로 못박을 수 있다.
    """
    saw_any = False
    for hit in hits:
        saw_any = True
        if not verify_address(hit, target):
            continue
        distance = haversine_m(lon, lat, hit.lon, hit.lat)
        fix = GeoFix(lon=hit.lon, lat=hit.lat, confidence="address",
                     query=target.address, matched_name=hit.building_name,
                     matched_address=hit.address_name, source="kakao_address")
        status = "mismatch" if distance > tolerance_m else "agree"
        return SweepVerdict(complex_id=complex_id, status=status,
                            distance_m=distance, fix=fix)
    return SweepVerdict(complex_id=complex_id,
                        status="unverified" if saw_any else "no_result")


def sweep_name_path(
    entries: Iterable[tuple[int, GeoTarget, float, float]],
    address_search: AddressSearch,
    *,
    tolerance_m: float = NAME_PATH_TOLERANCE_M,
    on_verdict: Callable[[SweepVerdict, GeoTarget], None] | None = None,
) -> list[SweepVerdict]:
    """(id, 단지, 경도, 위도) 목록을 **주소 검색 1회씩** 태워 재판정한다.

    호출은 단지당 정확히 한 번이다 — 이후 무효화·재확보 단계는 여기서 받은 결과를
    재사용한다(`ReplayGeocoder`). 같은 답을 두 번 물으면 카카오 쿼터만 두 배로 쓴다.
    """
    out: list[SweepVerdict] = []
    for complex_id, target, lon, lat in entries:
        hits = address_search.search(target.address) if target.address else []
        verdict = sweep_verdict(target, lon, lat, hits,
                                complex_id=complex_id, tolerance_m=tolerance_m)
        out.append(verdict)
        if on_verdict is not None:
            on_verdict(verdict, target)
    return out


class ReplayGeocoder:
    """이미 검증된 좌표를 **다시 묻지 않고** 돌려준다(재확보 단계용).

    `enrich_geom` 의 충돌 게이트·공유 판정을 그대로 태우기 위해 Geocoder 인터페이스를
    쓴다. 키는 `GeoTarget`(frozen dataclass — 값 동등성으로 해시된다) 자체다:
    같은 값의 target 이 둘이면 그 둘은 실제로 같은 단지이므로 같은 좌표가 맞다.
    """

    def __init__(self, fixes: dict[GeoTarget, GeoFix]) -> None:
        self._fixes = dict(fixes)
        self.last_reason: str = ""

    def locate(self, target: GeoTarget) -> GeoFix | None:
        fix = self._fixes.get(target)
        # 없으면 '검색 0건'과 같은 취급 — 재판정에서 좌표를 얻지 못한 것이다.
        self.last_reason = "" if fix is not None else "no_result"
        return fix


@dataclass
class GeocodeResult:
    resolved: int = 0
    unresolved: int = 0
    #: 검색은 됐지만 법정동·이름 검증에 떨어져 버린 수 (GEO-1 이 잡아낸 오좌표의 자리)
    rejected_mismatch: int = 0
    #: 다른 단지가 이미 쓰는 좌표라 채택하지 않은 수
    rejected_collision: int = 0
    #: 같은 단지가 이름만 갈라진 것으로 판정해 좌표를 공유한 수(정상)
    shared_point: int = 0
    #: 확보분 중 **주소 경로**로 얻은 수(REB-1). 이름 경로와 성과를 갈라 봐야
    #: "부동산원 마스터가 실제로 얼마나 기여했나"를 숫자로 말할 수 있다.
    resolved_by_address: int = 0
    #: 이번 배치에서 다룬 마지막 complex_id. 배치를 이어 돌 때 커서로 쓴다.
    #: 이게 없으면 "못 찾은 단지"가 geom IS NULL 로 계속 남아 매 배치의 앞자리를
    #: 다시 차지하고, 뒤쪽 단지는 영원히 시도되지 않는다(무한 재시도 함정).
    last_id: int = 0
    #: 채택하지 않은 이유 샘플(사람이 읽고 판단할 근거). 상한을 둔다.
    samples: list[str] = field(default_factory=list)

    def note(self, text: str, *, limit: int = 20) -> None:
        if len(self.samples) < limit:
            self.samples.append(text)


#: (complex_id, 검증을 통과한 좌표) → DB 반영.
#: ⚠️ 좌표 값만 넘기지 않는다. 출처·신뢰도·질의어까지 함께 있어야 "이 좌표를 왜 믿는가"를
#:    저장할 수 있고(007/008), 필드가 늘 때마다 인자를 하나씩 덧붙이는 부패를 막는다.
UpdateFn = Callable[[int, "GeoFix"], None]


def enrich_geom(
    targets: Iterable[tuple[int, GeoTarget]],
    geocoder: Geocoder,
    update: UpdateFn,
    *,
    occupied: dict[tuple[float, float], tuple[int, GeoTarget]] | None = None,
) -> GeocodeResult:
    """단지 후보들을 지오코딩·검증해 update(id, fix) 로 반영한다.

    `occupied` 는 **이미 다른 단지가 차지한 좌표**다(DB 기존분 + 이번 실행 누적).
    같은 점이 다시 나오면 최소 하나는 틀린 것이므로, 같은 단지의 이름 변형이
    아닌 한 채택하지 않는다 — 좌표는 비워 두고 충돌로 센다.

    DB 와 무관하게(주입식) 동작해 테스트가 네트워크·DB 없이 로직을 검증한다.
    못 찾은 건 조용히 넘기지 않고 사유별로 센다(재시도·조사 대상).
    """
    result = GeocodeResult()
    taken = occupied if occupied is not None else {}
    for complex_id, target in targets:
        result.last_id = max(result.last_id, complex_id)
        fix = geocoder.locate(target)
        if fix is None:
            result.unresolved += 1
            if getattr(geocoder, "last_reason", "") == "mismatch":
                result.rejected_mismatch += 1
            continue

        pk = point_key(fix.lon, fix.lat)
        holder = taken.get(pk)
        if holder is not None and holder[0] != complex_id:
            if not same_complex(holder[1], target):
                result.unresolved += 1
                result.rejected_collision += 1
                result.note(
                    f"충돌 #{complex_id} '{target.legal_dong} {target.name}' → "
                    f"#{holder[0]} '{holder[1].legal_dong} {holder[1].name}' 와 같은 점")
                continue
            result.shared_point += 1              # 같은 단지의 이름 변형 — 공유 허용

        update(complex_id, fix)
        taken.setdefault(pk, (complex_id, target))
        result.resolved += 1
        if fix.source == "kakao_address":
            result.resolved_by_address += 1
    return result


# ---------------------------------------------------------------------------
# 실 DB 배선
# ---------------------------------------------------------------------------

#: 단지 1행에 필요한 것 전부. 부동산원(reb_complex)은 **매칭된 단지만** LEFT JOIN 으로
#: 붙는다 — 매칭이 없으면 주소 컬럼이 NULL 이고, 그러면 주소 경로를 아예 타지 않는다.
_TARGET_COLUMNS = """
    c.id, c.name, c.address_jibun, r.sido, r.sigungu, c.reb_complex_id,
    b.address_jibun AS reb_address, b.legal_dong_code AS reb_dong_code,
    b.main_no AS reb_main_no, b.sub_no AS reb_sub_no, b.is_mountain AS reb_is_mountain
"""
_TARGET_FROM = """
    FROM complex c
    LEFT JOIN region r ON r.code = c.region_code
    LEFT JOIN reb_complex b ON b.reb_complex_id = c.reb_complex_id
"""

_SELECT_TARGETS = f"""
    SELECT {_TARGET_COLUMNS}
    {_TARGET_FROM}
    WHERE c.geom IS NULL AND c.id > :after
    ORDER BY c.id LIMIT :limit
"""

#: 주소 경로 전용 — 부동산원과 매칭돼 주소를 아는 단지만. 이름으로 못 찾은 단지를
#: 회수하는 배치라 매칭 없는 단지에 카카오 쿼터를 태우지 않는다.
_SELECT_ADDRESS_TARGETS = f"""
    SELECT {_TARGET_COLUMNS}
    {_TARGET_FROM}
    WHERE c.geom IS NULL AND c.id > :after AND b.address_jibun IS NOT NULL
    ORDER BY c.id LIMIT :limit
"""

_SELECT_OCCUPIED = f"""
    SELECT {_TARGET_COLUMNS},
           ST_X(c.geom) AS lon, ST_Y(c.geom) AS lat
    {_TARGET_FROM}
    WHERE c.geom IS NOT NULL
    ORDER BY c.id
"""


def row_target(row: Any) -> GeoTarget:
    """DB 행(complex + region + reb_complex 조인) → GeoTarget. 스크립트도 같은 매핑을 쓴다."""
    return GeoTarget(
        name=row.name or "", legal_dong=row.address_jibun or "",
        sigungu=getattr(row, "sigungu", "") or "",
        sido=getattr(row, "sido", "") or "",
        address=getattr(row, "reb_address", "") or "",
        legal_dong_code=getattr(row, "reb_dong_code", "") or "",
        main_no=getattr(row, "reb_main_no", None),
        sub_no=getattr(row, "reb_sub_no", None) or 0,
        is_mountain=bool(getattr(row, "reb_is_mountain", False)),
        reb_id=getattr(row, "reb_complex_id", "") or "",
    )


def load_occupied(engine: Any) -> dict[tuple[float, float], tuple[int, GeoTarget]]:
    """이미 좌표가 있는 단지를 (점 → 단지) 로 싣는다 — 충돌 판정의 기준선."""
    from sqlalchemy import text

    taken: dict[tuple[float, float], tuple[int, GeoTarget]] = {}
    with engine.connect() as conn:
        for row in conn.execute(text(_SELECT_OCCUPIED)):
            taken.setdefault(point_key(row.lon, row.lat), (row.id, row_target(row)))
    return taken


def load_placed(engine: Any) -> list[tuple[int, GeoTarget, float, float]]:
    """좌표가 있는 단지를 **한 행도 빠뜨리지 않고** 싣는다(재판정용).

    `load_occupied` 는 점 하나당 첫 단지만 남기므로(충돌 게이트의 기준선이라 그게 맞다)
    "같은 점을 몇이 쓰고 있나"를 볼 수 없다. 재판정은 전수를 봐야 한다.
    """
    from sqlalchemy import text

    with engine.connect() as conn:
        return [(row.id, row_target(row), float(row.lon), float(row.lat))
                for row in conn.execute(text(_SELECT_OCCUPIED))]


_UPDATE_GEOM = """
    UPDATE complex
    SET geom = ST_SetSRID(ST_MakePoint(:lon, :lat), 4326),
        geom_source = :source,
        geom_confidence = :conf,
        updated_at = now()
    WHERE id = :id
"""


def enrich_postgis_geom(engine: Any, geocoder: Geocoder, *, limit: int = 500,
                        after_id: int = 0,
                        occupied: dict[tuple[float, float], tuple[int, GeoTarget]]
                        | None = None,
                        address_only: bool = False) -> GeocodeResult:
    """geom 이 NULL 인 단지를 찾아 지오코딩해 POINT(4326)로 채운다(실 DB용).

    ⚠️ 키·DB 준비 후 사용. 좌표는 ST_SetSRID(ST_MakePoint(lon, lat), 4326).
       출처(`geom_source`)·신뢰도(`geom_confidence`)를 함께 기록한다(마이그레이션 007/008) —
       나중에 "이 좌표를 왜 믿는가"를 되짚을 수 있어야 한다.

    `address_only` 면 **부동산원과 매칭돼 주소를 아는 단지만** 대상으로 삼는다.
    이름으로 이미 실패한 단지를 주소로 회수하는 배치라, 매칭 없는 단지에 카카오
    쿼터를 다시 태우지 않기 위한 것이다.

    `after_id` 는 이어 돌기용 커서다(`GeocodeResult.last_id` 를 그대로 넘긴다).
    못 찾은 단지는 geom 이 NULL 로 남으므로, 커서 없이 반복 호출하면 같은 실패 건만
    계속 다시 시도하고 뒤쪽 단지는 한 번도 시도되지 않는다.

    `occupied` 를 넘기지 않으면 매 호출마다 DB 에서 새로 싣는다(배치 반복 시 낭비).
    """
    from sqlalchemy import text

    taken = load_occupied(engine) if occupied is None else occupied
    sql = _SELECT_ADDRESS_TARGETS if address_only else _SELECT_TARGETS

    with engine.connect() as conn:
        rows = conn.execute(text(sql), {"limit": limit, "after": after_id}).all()

    def _update(complex_id: int, fix: GeoFix) -> None:
        with engine.begin() as conn:
            conn.execute(text(_UPDATE_GEOM),
                         {"id": complex_id, "lon": fix.lon, "lat": fix.lat,
                          "source": fix.source, "conf": fix.confidence})

    targets = [(r.id, row_target(r)) for r in rows]
    return enrich_geom(targets, geocoder, _update, occupied=taken)
