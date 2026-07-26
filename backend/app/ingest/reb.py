"""한국부동산원 **공동주택 단지 식별정보** 파싱·매칭 (순수 함수).

왜 필요한가 — GEO-1 이 남긴 구멍
---------------------------------
GEO-1 수정으로 틀린 좌표를 걷어내자 확보율이 93.6% → 80.0% 로 떨어졌다(1,307개 단지가
지도·입지분석에서 '정보 없음'). 실패 사유는 둘 다 **"단지명으로 찾기"의 한계**였다:

  · 검증불합격 749건 — 카카오가 다른 동/다른 단지를 돌려줌
  · 검색 0건   518건 — 카카오에 그 이름의 POI 가 아예 없음

MOLIT 단지명은 오염돼 있다(`현대2차(10,11,20,23,24,25동)`, `대치우성아파트1동,2동,3동`).
`가락동 우성` 처럼 **어느 차수인지 알 수 없는 이름**도 많다. 이름으로 더 짜내는 건
정확도를 깎는 방향밖에 없다.

그래서 **이름이 아니라 주소로 찾는다.** 한국부동산원 공동주택 단지 식별정보에는
단지고유번호 · 필지고유번호(PNU) · 지번주소 · 단지명 3종 · 단지종류 · 동수 · 세대수 ·
사용승인일이 들어 있다. PNU 앞 10자리가 **법정동코드**라 우리 `complex.region_code` 와
코드로 대조된다 — 문자열 동명 비교보다 훨씬 단단하다.

출처
----
공공데이터포털 파일데이터 (한국부동산원)
  · 기본정보 https://www.data.go.kr/data/15106861/fileData.do
  · 동정보   https://www.data.go.kr/data/15106866/fileData.do
내려받기는 `scripts/fetch_reb_complex_master.py` (사람이 브라우저로 받는 절차를 자동화).

⚠️ 매칭 원칙 — **애매하면 매칭하지 않는다**
--------------------------------------------
잘못된 매칭은 곧바로 잘못된 좌표·잘못된 동수가 된다. GEO-1 이 "틀린 걸 넣느니 비운다"로
정리된 직후에 그 원칙을 뒤집을 수는 없다. 그래서:

1. **법정동코드가 정확히 같은** 후보만 본다(문자열 동명이 아니라 10자리 코드).
2. 이름 대조는 강한 단계부터 본다(완전일치 → 포함 → 유사도). 한 단계에서 **후보가 둘 이상
   나오면 즉시 '애매'로 끝낸다** — 더 느슨한 단계로 내려가 하나를 고르지 않는다.
   (느슨한 단계로 내려가면 '가락동 우성' 이 '가락우성1차' 나 '가락우성2차' 중 하나에
   임의로 붙는다. 그게 정확히 하면 안 되는 일이다.)
3. 차수·단지번호가 다르면 다른 단지다(`신현대11차` ≠ `신현대12차`) — geocode 와 같은 규칙.
"""
from __future__ import annotations

import csv
import datetime as dt
import io
import re
from collections.abc import Iterable, Sequence
from dataclasses import dataclass

from app.ingest.geocode import NAME_SIMILARITY, comparable_names, name_phases, similarity

__all__ = [
    "MATCH_METHODS", "MatchResult", "RebBuilding", "RebComplex", "REB_KIND_APT",
    "REB_NAME_SIMILARITY", "address_is_mountain", "decode_csv", "dong_label",
    "match_complex", "parse_basic_csv", "parse_dong_csv", "parse_pnu",
]

#: 단지종류 코드. 우리 서비스 범위는 아파트다(CLAUDE.md — 오피스텔·빌라·상가는 범위 밖).
REB_KIND_APT = "1"
REB_KIND_ROWHOUSE = "2"          # 연립
REB_KIND_MULTIPLEX = "3"         # 다세대

#: 매칭 유사도 기준선. 좌표 채택용(geocode.NAME_SIMILARITY=0.80)보다 **한 단계 높다** —
#: 여기서 틀리면 좌표뿐 아니라 동수·세대수·사용승인일까지 통째로 남의 단지 것이 붙는다.
REB_NAME_SIMILARITY = 0.88
assert REB_NAME_SIMILARITY >= NAME_SIMILARITY, "매칭 기준이 좌표 채택 기준보다 느슨할 수 없다"

#: 매칭 방법(강한 순). 이 순서가 곧 신뢰도 순서이고, DB `complex.reb_match_method` 에 남는다.
MATCH_METHODS = ("name_exact", "name_contains", "name_fuzzy")

#: 파일 인코딩 후보. 2026-07-26 배포본은 UTF-8 BOM 이지만 공공데이터포털 파일은
#: CP949 로 바뀌는 일이 흔하다 — 틀린 인코딩으로 읽으면 한글이 깨진 채 적재된다.
_ENCODINGS = ("utf-8-sig", "cp949", "utf-8")

_BASIC_HEADER = {
    "reb_id": "단지고유번호",
    "parcel_id": "필지고유번호",
    "address_jibun": "주소",
    "name_price": "단지명_공시가격",
    "name_ledger": "단지명_건축물대장",
    "name_road": "단지명_도로명주소",
    "kind": "단지종류",
    "building_count": "동수",
    "household_count": "세대수",
    "approved_on": "사용승인일",
}
_DONG_HEADER = {
    "reb_id": "단지고유번호",
    "name_price": "동명_공시가격",
    "name_ledger": "동명_건축물대장",
    "name_road": "동명_도로명주소",
    "floors": "지상층수",
}


# ---------------------------------------------------------------------------
# 값 객체
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class PnuParts:
    """필지고유번호(PNU) 19자리 = 법정동코드(10) + 산여부(1) + 본번(4) + 부번(4).

    앞 10자리가 법정동코드라 `region.code` · `complex.region_code` 와 **코드로** 맞춰진다.
    본번·부번은 카카오 주소검색 응답(`main_address_no`/`sub_address_no`)과 대조해
    "내가 물어본 그 지번이 맞는지"를 확인하는 데 쓴다.
    """

    legal_dong_code: str
    is_mountain: bool
    main_no: int
    sub_no: int

    @property
    def sigungu_code(self) -> str:
        return self.legal_dong_code[:5]


def parse_pnu(pnu: str) -> PnuParts | None:
    """PNU → 부분. 19자리 숫자가 아니면 **추측하지 않고** None."""
    raw = (pnu or "").strip()
    if len(raw) != 19 or not raw.isdigit():
        return None
    return PnuParts(
        legal_dong_code=raw[:10],
        # 산여부 자리는 1(대지)·2(산)이 대부분이지만 실배포본에 3~7 도 섞여 있다
        # (2026-07-26 실측). '산'인지 아닌지만 알면 되므로 2 만 산으로 본다.
        is_mountain=raw[10] == "2",
        main_no=int(raw[11:15]),
        sub_no=int(raw[15:19]),
    )


@dataclass(frozen=True)
class RebComplex:
    """부동산원 단지 1건(기본정보)."""

    reb_id: str
    parcel_id: str
    address_jibun: str = ""
    name_price: str = ""
    name_ledger: str = ""
    name_road: str = ""
    kind: str = ""
    building_count: int | None = None
    household_count: int | None = None
    approved_on: dt.date | None = None

    @property
    def pnu(self) -> PnuParts | None:
        return parse_pnu(self.parcel_id)

    @property
    def legal_dong_code(self) -> str:
        parts = self.pnu
        return parts.legal_dong_code if parts else ""

    @property
    def names(self) -> tuple[str, ...]:
        """대조에 쓸 단지명들. 세 출처가 서로 다를 수 있어 **전부** 본다.

        공시가격 이름은 '우정(102동)' 처럼 동이 섞여 오고, 건축물대장 이름은
        '우정아파트' 처럼 정식 명칭인 경우가 많다. 하나만 보면 멀쩡한 매칭을 놓친다.
        """
        seen: list[str] = []
        for n in (self.name_price, self.name_ledger, self.name_road):
            n = (n or "").strip()
            if n and n not in seen:
                seen.append(n)
        return tuple(seen)


@dataclass(frozen=True)
class RebBuilding:
    """부동산원 동(棟) 1건(동정보). `label` 이 None 이면 **동으로 쓰지 않는다.**"""

    reb_id: str
    name_price: str = ""
    name_ledger: str = ""
    name_road: str = ""
    floors: int | None = None

    @property
    def label(self) -> str | None:
        """'101동' 같은 정규 표기. 판독할 수 없으면 None — **동을 만들어내지 않는다.**"""
        for raw in (self.name_price, self.name_ledger, self.name_road):
            got = dong_label(raw)
            if got:
                return got
        return None


# ---------------------------------------------------------------------------
# 파싱
# ---------------------------------------------------------------------------

def decode_csv(raw: bytes) -> str:
    """인코딩을 추정해 디코딩한다. 한글이 안 보이면 **성공으로 치지 않는다.**

    `errors='replace'` 로 조용히 넘어가면 깨진 이름이 그대로 적재되고,
    그 뒤 매칭은 전부 실패한다 — 원인을 찾기 아주 어려운 종류의 사고다.
    """
    for enc in _ENCODINGS:
        try:
            text = raw.decode(enc)
        except UnicodeDecodeError:
            continue
        if any("가" <= ch <= "힣" for ch in text[:5000]):
            return text
    raise ValueError("인코딩을 판별하지 못했습니다 (utf-8-sig/cp949 모두 실패)")


def _rows(text: str, header: dict[str, str], *, what: str) -> Iterable[dict[str, str]]:
    reader = csv.DictReader(io.StringIO(text))
    missing = [col for col in header.values() if col not in (reader.fieldnames or [])]
    if missing:
        raise ValueError(
            f"{what} 파일에 예상한 컬럼이 없습니다: {missing} "
            f"(실제: {reader.fieldnames}) — 배포 형식이 바뀌었을 수 있습니다")
    yield from reader


def _int(value: str) -> int | None:
    raw = (value or "").strip().replace(",", "")
    return int(raw) if raw.isdigit() else None


def _date(value: str) -> dt.date | None:
    """'YYYY-MM-DD' → date. '--' 같은 결측 표기는 None(추측하지 않는다)."""
    raw = (value or "").strip()
    try:
        return dt.date.fromisoformat(raw)
    except ValueError:
        return None


def parse_basic_csv(text: str) -> list[RebComplex]:
    out: list[RebComplex] = []
    for row in _rows(text, _BASIC_HEADER, what="기본정보"):
        reb_id = (row[_BASIC_HEADER["reb_id"]] or "").strip()
        parcel = (row[_BASIC_HEADER["parcel_id"]] or "").strip()
        if not reb_id or parse_pnu(parcel) is None:
            continue                     # 식별할 수 없는 행은 버린다 — 추정 금지
        out.append(RebComplex(
            reb_id=reb_id,
            parcel_id=parcel,
            address_jibun=(row[_BASIC_HEADER["address_jibun"]] or "").strip(),
            name_price=(row[_BASIC_HEADER["name_price"]] or "").strip(),
            name_ledger=(row[_BASIC_HEADER["name_ledger"]] or "").strip(),
            name_road=(row[_BASIC_HEADER["name_road"]] or "").strip(),
            kind=(row[_BASIC_HEADER["kind"]] or "").strip(),
            building_count=_int(row[_BASIC_HEADER["building_count"]]),
            household_count=_int(row[_BASIC_HEADER["household_count"]]),
            approved_on=_date(row[_BASIC_HEADER["approved_on"]]),
        ))
    return out


def parse_dong_csv(text: str) -> list[RebBuilding]:
    out: list[RebBuilding] = []
    for row in _rows(text, _DONG_HEADER, what="동정보"):
        reb_id = (row[_DONG_HEADER["reb_id"]] or "").strip()
        if not reb_id:
            continue
        out.append(RebBuilding(
            reb_id=reb_id,
            name_price=(row[_DONG_HEADER["name_price"]] or "").strip(),
            name_ledger=(row[_DONG_HEADER["name_ledger"]] or "").strip(),
            name_road=(row[_DONG_HEADER["name_road"]] or "").strip(),
            floors=_int(row[_DONG_HEADER["floors"]]),
        ))
    return out


# ---------------------------------------------------------------------------
# 동(棟) 표기 정규화
# ---------------------------------------------------------------------------

#: 부동산원 동명 실표기(2026-07-26 실측 157,021행):
#:   '101' · '제101' · '청운현대(아)101동' · '가' · '나' · '' (빈칸 13,343행)
#: 아래 패턴 중 하나로 **읽히는 것만** 동으로 인정한다. 읽히지 않으면 버린다 —
#: 동수(개수)를 아는 것과 동 목록을 아는 것은 다르고, 모르는 동을 지어내면 F4 가 거짓이 된다.
_DONG_PATTERNS = (
    re.compile(r"^제?\s*(\d{1,4})\s*동?$"),        # '101' · '제101' · '101동'
    re.compile(r"(\d{1,4})\s*동$"),                 # '청운현대(아)101동'
    re.compile(r"^([가-힣]{1,2})\s*동$"),           # '가동' · '에이동'
    re.compile(r"^([가-힣]{1,2})$"),                # '가' · '나'
    re.compile(r"^([A-Za-z]{1,2})\s*동?$"),         # 'A' · 'A동'
)


def dong_label(raw: str) -> str | None:
    """부동산원 동명 → '101동' 정규 표기. 읽을 수 없으면 None."""
    text = (raw or "").strip()
    if not text:
        return None
    for pattern in _DONG_PATTERNS:
        m = pattern.search(text)
        if not m:
            continue
        token = m.group(1)
        if token.isdigit():
            return f"{int(token)}동"                # '0101' → '101동'
        return f"{token.upper()}동" if token.isascii() else f"{token}동"
    return None


#: 지번주소의 '산' 표기. '산본동' 같은 동명에 걸리지 않도록 **숫자 앞의 산**만 본다.
_MOUNTAIN_RE = re.compile(r"(?:^|\s)산\s*\d")


def address_is_mountain(address: str) -> bool:
    """'…정릉동 산87-85' 처럼 산번지인가. 산87-85 와 87-85 는 **다른 필지**다."""
    return bool(_MOUNTAIN_RE.search(address or ""))


# ---------------------------------------------------------------------------
# 매칭 — 우리 complex ↔ 부동산원 단지
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class MatchResult:
    """매칭 결과. `status` 는 'matched' | 'ambiguous' | 'unmatched'."""

    status: str
    reb_id: str = ""
    method: str = ""
    #: 애매할 때 실제로 걸린 후보들(사람이 읽고 판단할 근거). 상한 5개.
    rivals: tuple[str, ...] = ()

    @property
    def matched(self) -> bool:
        return self.status == "matched"


def _hit(method: str, mine: str, theirs: str) -> bool:
    """단계별 이름 대조. 차수·단지번호가 다르면 어떤 단계에서도 같은 단지가 아니다."""
    if name_phases(mine) != name_phases(theirs):
        return False                       # '신현대11차' vs '신현대12차'
    for a in comparable_names(mine):
        for b in comparable_names(theirs):
            if len(a) < 2 or len(b) < 2:
                continue
            if method == "name_exact":
                if a == b:
                    return True
                continue
            short, long_ = (a, b) if len(a) <= len(b) else (b, a)
            if method == "name_contains":
                if len(short) >= 3 and short in long_:
                    return True
                continue
            if method == "name_fuzzy" and similarity(a, b) >= REB_NAME_SIMILARITY:
                return True
    return False


def match_complex(name: str, candidates: Sequence[RebComplex]) -> MatchResult:
    """단지명 하나를 **같은 법정동코드의** 부동산원 후보들과 대조한다.

    ⚠️ 호출자는 후보를 **법정동코드로 이미 걸러서** 넘겨야 한다. 이 함수는 이름만 본다 —
       지역 대조는 코드로 하는 게 정확하고, 그 책임을 여기 섞으면 두 곳에서 달라진다.

    한 단계에서 서로 다른 단지가 둘 이상 걸리면 **거기서 끝낸다**('ambiguous').
    더 느슨한 단계로 내려가 임의로 하나를 고르지 않는다.
    """
    clean = (name or "").strip()
    if not clean or not candidates:
        return MatchResult("unmatched")

    for method in MATCH_METHODS:
        hits = [c for c in candidates if any(_hit(method, clean, n) for n in c.names)]
        ids = sorted({c.reb_id for c in hits})
        if len(ids) == 1:
            return MatchResult("matched", reb_id=ids[0], method=method)
        if len(ids) > 1:
            return MatchResult("ambiguous", method=method, rivals=tuple(ids[:5]))
    return MatchResult("unmatched")
