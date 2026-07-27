"""정비사업(재건축·재개발) 추진현황 파싱 — **순수 함수**.

출처 (2026-07-27 실호출 확인)
------------------------------
① 서울특별시 도시정비사업 통계 · 472행 · 열린데이터광장 `OA-22856`
     CSV   : https://datafile.seoul.go.kr/bigfile/iot/sheet/csv/download.do (무키·무로그인·https)
     ⚠️ 인증키가 필요한 OpenAPI 경로는 **의도적으로 쓰지 않는다**(SR24-1). 그 엔드포인트는
        평문 HTTP 이고 키를 URL **경로**에 담아 예외 메시지·프록시 로그로 그대로 샌다.
        같은 데이터셋이므로 무키 CSV 로 충분하다 — 자세한 사유는
        `scripts/load_redevelopment.py` 의 `SEOUL_CSV_URL` 주석.
     항목  : 자치구 · 구역명 · **지번주소** · 사업유형 · **사업추진단계** +
             구역지정/추진위/조합설립/건축심의/사업시행/관리처분/이주/착공 **일자** +
             기존가구수 · 건립세대수
     라이선스: 공공누리 4유형(출처표시 + 상업적 이용금지 + 변경금지) →
             **개인 비상업 용도 전제**(CLAUDE.md 제약)에서만 쓴다.

② 인천광역시 도시 및 주거환경 정비사업 추진현황 · 144행 · 공공데이터포털 `15055212`
     CSV   : https://www.data.go.kr/cmm/cmm/fileDownload.do?atchFileId=…(무키·무로그인)
     항목  : 구명 · 구역명 · **위치**(지번) · 면적 · 사업유형 · **진행단계**
     ⚠️ 단계별 일자·세대수가 **없다.** 없는 것을 서울 형식에 맞춰 채우지 않는다.

③ 경기도 — **미수집.** 도 단위 공개 API 가 없고 시군별로 흩어져 있으며(하남·이천·안양·
     고양·부천·남양주 등 일부만), 경기데이터드림 별도 인증키가 필요하다.
     국토교통부 「전국 도시정비사업 통합 데이터」(1,566행)에는 단계가 있으나
     **법정동·지번이 없어** 우리 매칭 규칙(대표지번 정확일치)을 만족시킬 수 없다.
     → 경기도 단지는 "정비사업 정보 미확보"로 나간다(없다고 말하지 않는다).

⚠️⚠️ 매칭 규칙 — **애매하면 매칭하지 않는다**
---------------------------------------------
잘못된 매칭 1건은 없는 것보다 훨씬 나쁘다(사용자가 그 근거로 수억을 쓴다).
그래서 이름 유사도를 **일절 쓰지 않고**, 대표지번의 (법정동코드·본번·부번)이
부동산원 필지와 **완전히 같을 때만** 잇는다.

  * 지번을 못 읽으면            → `no_jibun` (도로명만 있으면 `road_address_only`)
  * 지번이 둘 이상이면          → `multi_jibun` (예: "경동 40번지 및 율목동 10번지 일원")
  * 법정동을 못 찾으면          → `unknown_dong`
  * 한 필지에 단지가 너무 많으면 → 매칭 보류(적재 스크립트가 상한을 건다)

행정동 표기('목2동523-45')는 법정동('목동')으로 되돌려 맞추되, **되돌린 이름이 실제로
그 시군구의 법정동일 때만** 인정하고 `match_method` 에 그 사실을 남긴다(추측 금지).
"""
from __future__ import annotations

import csv
import datetime as dt
import io
import re
from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from typing import Any

from app.domain.redevelopment.models import (  # noqa: F401 - 재수출(호출부 호환)
    SOURCE_INCHEON,
    SOURCE_SEOUL,
)
from app.domain.redevelopment.stages import normalize_biz_type, normalize_stage

__all__ = [
    "DONG_EXACT", "DONG_ADMIN_STRIPPED", "DONG_SCOPE_SIDO_UNIQUE", "DONG_SCOPE_SIGUNGU",
    "DongIndex", "DongScope", "JibunRef", "ParsedAddress", "RedevRecord",
    "SIDO_INCHEON", "SIDO_SEOUL",
    "SOURCE_INCHEON", "SOURCE_SEOUL", "STATUS_AMBIGUOUS_DONG", "STATUS_MULTI_JIBUN",
    "STATUS_NO_JIBUN", "STATUS_OK", "STATUS_ROAD_ONLY", "STATUS_UNKNOWN_DONG",
    "build_dong_index", "decode_csv", "parse_address", "parse_incheon_csv",
    "parse_seoul_csv", "parse_seoul_rows",
]

# ⚠️ `SOURCE_SEOUL`·`SOURCE_INCHEON` 은 **도메인(models.py)에 한 번만** 정의한다.
#    화면 출처명(`SOURCE_LABELS`)이 같은 파일에 있어야 키와 라벨이 따로 놀지 않는다
#    (SR25-3: 라벨이 기계 키였고, 그 키에는 삭제한 OpenAPI 테이블명이 남아 있었다).
#    여기서는 재수출만 한다 — 적재 스크립트·테스트가 이 이름으로 import 한다.

SOURCE_URL_SEOUL = "https://data.seoul.go.kr/dataList/OA-22856/S/1/datasetView.do"
SOURCE_URL_INCHEON = "https://www.data.go.kr/data/15055212/fileData.do"

#: 시도명 — `region.sido` 와 **같은 문자열**이어야 한다(색인 열쇠다).
SIDO_SEOUL = "서울특별시"
SIDO_INCHEON = "인천광역시"

# --- 주소 파싱 상태 ---------------------------------------------------------
STATUS_OK = "ok"
STATUS_NO_JIBUN = "no_jibun"              # 동은 찾았는데 번지가 없다
STATUS_MULTI_JIBUN = "multi_jibun"        # 지번이 둘 이상 — 애매하므로 매칭 안 함
STATUS_UNKNOWN_DONG = "unknown_dong"      # 그 시도의 법정동을 못 찾았다
STATUS_AMBIGUOUS_DONG = "ambiguous_dong"  # 동명이 시도 안에서 중복인데 시군구로 못 가른다
STATUS_ROAD_ONLY = "road_address_only"    # 도로명만 있다(지번 없음)

# --- 법정동 확정 방법 -------------------------------------------------------
DONG_EXACT = "exact"                      # 원문에 법정동명이 그대로 있었다
DONG_ADMIN_STRIPPED = "admin_stripped"    # 행정동('목2동') → 법정동('목동')

# --- 법정동을 어느 범위에서 확정했나 ----------------------------------------
#: 자료가 말한 시군구 안에서 찾았다(가장 강하다).
DONG_SCOPE_SIGUNGU = "sigungu"
#: 자료의 시군구가 우리 `region` 에 없어서(예: 2026 인천 행정구역 개편 — 중구·동구·서구 →
#: 제물포구·영종구·검단구·서해구) **시도 전체에서 유일한 법정동**임을 근거로 확정했다.
#: 유일하지 않으면 확정하지 않는다 — 그게 이 라벨이 존재하는 이유다.
DONG_SCOPE_SIDO_UNIQUE = "sido_unique"


@dataclass(frozen=True)
class DongScope:
    """한 시도의 법정동 색인 + **자료가 말한** 시군구.

    왜 시군구가 아니라 시도로 색인하는가
    ------------------------------------
    시군구 이름은 **바뀐다.** 2026년 인천 행정구역 개편으로 중구·동구·서구가
    제물포구·영종구·검단구·서해구가 됐는데, 정비사업 자료(2026-05-31 기준)에는
    아직 옛 이름이 실려 있다. 시군구 이름으로만 색인하면 인천 144행 중 40행이
    "법정동 목록 없음"으로 통째로 사라진다 — 데이터가 아니라 **표기 변경 때문에** 잃는다.
    또 '중구'는 서울에도 인천에도 있어서 시군구 이름만으로 색인하면 두 도시가 섞인다
    (그 상태로 매칭하면 서울 중구 지번이 인천 구역에 붙을 수 있다 — 가장 하면 안 되는 일).

    그래서 **시도로 색인하고 시군구는 동명 중복을 가르는 데만** 쓴다.
    시군구로 가를 수 없고 시도 안에서도 유일하지 않으면 **확정하지 않는다.**
    """

    #: 법정동명 → ((법정동코드, 시군구), …)
    by_name: Mapping[str, tuple[tuple[str, str], ...]]
    #: 자료가 말한 시군구(옛 이름일 수 있다).
    sigungu: str = ""

    def resolve(self, name: str) -> tuple[str | None, str]:
        """동명 → (법정동코드, 확정 범위). 확정 못 하면 (None, 사유)."""
        entries = self.by_name.get(name, ())
        if not entries:
            return None, STATUS_UNKNOWN_DONG
        same_gu = [code for code, gu in entries if gu == self.sigungu]
        if len(same_gu) == 1:
            return same_gu[0], DONG_SCOPE_SIGUNGU
        if len(entries) == 1:
            return entries[0][0], DONG_SCOPE_SIDO_UNIQUE
        return None, STATUS_AMBIGUOUS_DONG


@dataclass(frozen=True)
class DongIndex:
    """시도별 법정동 색인. `region` 테이블 스냅샷을 파서가 쓰는 모양으로 담는다."""

    #: 시도 → (법정동명 → ((법정동코드, 시군구), …))
    by_sido: Mapping[str, Mapping[str, tuple[tuple[str, str], ...]]]

    def scope(self, sido: str, sigungu: str) -> DongScope:
        return DongScope(by_name=self.by_sido.get(sido, {}), sigungu=sigungu or "")


@dataclass(frozen=True)
class JibunRef:
    """대표지번 하나. 부동산원 필지(`reb_complex`)와 대조할 열쇠."""

    legal_dong_code: str
    dong_name: str
    main_no: int
    sub_no: int
    is_mountain: bool
    dong_match: str          # exact | admin_stripped
    dong_scope: str          # sigungu | sido_unique

    @property
    def key(self) -> tuple[str, int, int, bool]:
        return (self.legal_dong_code, self.main_no, self.sub_no, self.is_mountain)


@dataclass(frozen=True)
class ParsedAddress:
    status: str
    jibun: JibunRef | None = None
    #: 사람이 읽는 사유(적재 리포트가 그대로 쓴다).
    detail: str = ""
    #: 여러 지번이 읽혔을 때 그 목록(진단용). 매칭에는 쓰지 않는다.
    candidates: tuple[tuple[str, int, int], ...] = ()


@dataclass(frozen=True)
class RedevRecord:
    """출처 1행 → 우리 표준 모양. **원문을 지우지 않는다.**"""

    source: str
    source_key: str
    source_url: str
    sido: str
    sigungu: str
    zone_name: str
    raw_stage: str
    stage: str
    raw_biz_type: str | None
    biz_type: str
    address_raw: str
    as_of: dt.date
    # 파싱 결과
    parse_status: str = STATUS_NO_JIBUN
    parse_detail: str = ""
    legal_dong_code: str | None = None
    main_no: int | None = None
    sub_no: int | None = None
    is_mountain: bool = False
    dong_match: str | None = None
    dong_scope: str | None = None
    # 단계별 일자 (서울만)
    zone_designated_on: dt.date | None = None
    committee_on: dt.date | None = None
    association_on: dt.date | None = None
    design_review_on: dt.date | None = None
    implementation_on: dt.date | None = None
    disposition_on: dt.date | None = None
    relocation_start_on: dt.date | None = None
    relocation_end_on: dt.date | None = None
    construction_start_on: dt.date | None = None
    existing_households: int | None = None
    planned_households: int | None = None


# ---------------------------------------------------------------------------
# 인코딩
# ---------------------------------------------------------------------------
_ENCODINGS = ("utf-8-sig", "cp949", "utf-8")


def decode_csv(raw: bytes) -> str:
    """공공데이터 CSV 는 CP949 가 흔하다. 순서대로 시도하고 전부 실패하면 예외.

    ⚠️ `errors='replace'` 로 뭉개지 않는다 — 깨진 한글로 매칭하면 조용히 0건이 된다.
    """
    last: Exception | None = None
    for enc in _ENCODINGS:
        try:
            return raw.decode(enc)
        except UnicodeDecodeError as exc:  # noqa: PERF203 - 인코딩 후보가 셋뿐이다
            last = exc
    raise ValueError(f"CSV 인코딩을 판별하지 못했습니다: {last}")


# ---------------------------------------------------------------------------
# 주소 → 대표지번
# ---------------------------------------------------------------------------

#: 도로명 주소 패턴(…로 / …길 + 숫자). 지번이 안 읽혔을 때 사유를 가르는 데만 쓴다.
_ROAD_RE = re.compile(r"[가-힣A-Za-z0-9]+(?:로|길)\s*\d+")

#: 행정동 표기('목2동' · '숭의2동'). 법정동으로 되돌릴 후보를 찾는다.
_ADMIN_DONG_RE = re.compile(r"([가-힣]{1,8}?)(\d{1,2})동")

#: 동명 뒤의 번지. '산87-85' 처럼 산번지가 붙을 수 있다.
_NUMBER_RE = re.compile(r"\s*(?:제)?\s*(산)?\s*(\d{1,5})(?:\s*-\s*(\d{1,5}))?")

#: 지번 뒤에 콤마로 다른 번지가 이어지는 나열('송림동 2, 4번지 일원').
#: 어느 번지인지 특정할 수 없으므로 **매칭하지 않는다**.
#: ⚠️ `^` 를 쓰지 않는다 — `pattern.match(text, pos)` 의 `^` 는 pos 가 아니라
#:    **문자열 맨 앞**에서만 맞아서, 넣으면 이 가드가 통째로 무력화된다(조용히 통과).
_JIBUN_LIST_RE = re.compile(r"\s*,\s*\d")


#: 법정동명 **바로 앞**에 올 수 있는 한글. 행정구역 접미사뿐이다('양천구목동903').
#: 그 외 한글이 붙어 있으면 그건 더 긴 낱말의 꼬리이지 법정동명이 아니다.
_ALLOWED_PREV = ("구", "시", "군", "면", "읍")


def _is_hangul(ch: str) -> bool:
    return "가" <= ch <= "힣"


def _boundary_ok(text: str, idx: int) -> bool:
    """법정동명 앞이 낱말 경계인가.

    ⚠️ **이 검사가 없으면 실제로 틀린 매칭이 난다.** 실측(2026-07-27):
       '망우본동461-12'(중랑구)·'중계본동30-3'(노원구)의 꼬리 '본동' 이 **동작구 본동**
       으로 잡혔다. 중랑구 재개발 구역이 동작구 필지에 붙는, 이 프로젝트에서 가장
       하면 안 되는 형태의 오매칭이다. 지금은 앞 글자가 한글이면(행정구역 접미사 제외)
       매칭하지 않고 '법정동 못 찾음'으로 남긴다 — 놓치는 편이 틀리는 편보다 낫다.

    ⚠️ 접미사 예외에는 **꼬리 조건**이 붙는다 (CR-029 차단 3, 2026-07-27).
       `_ALLOWED_PREV` 는 '구/시/군/면/읍' 인데, 이걸 앞 글자만 보고 허용하면
       '**면**목동' 의 '목동'(양천구)도 통과한다 — 중랑구 정비구역이 양천구 필지에
       붙는다. 행정구역 이름은 언제나 **어간 + 접미사**다('양천구'·'조안면'·'고양시').
       접미사 한 글자만 덩그러니 앞에 있는 것은 행정구역이 아니라 더 긴 낱말의
       일부다. 그래서 접미사 앞에 한글 어간이 최소 한 글자 더 있어야 허용한다.
    """
    if idx == 0:
        return True
    prev = text[idx - 1]
    if not _is_hangul(prev):
        return True
    if prev not in _ALLOWED_PREV:
        return False
    # '…구목동' 은 되고 '면목동'(앞에 어간이 없다)은 안 된다.
    return idx >= 2 and _is_hangul(text[idx - 2])


def _find_dong_spans(text: str, names: Iterable[str]) -> list[tuple[int, int, str]]:
    """법정동명이 나타나는 구간을 찾는다. **왼쪽부터 · 가장 긴 이름 우선**(최대 일치).

    ⚠️ 정렬 순서에 기대지 않는다 (CR-029 차단 3, 2026-07-27)
    ------------------------------------------------------
    예전 구현은 `sorted(names, key=len, reverse=True)` 로 이름 목록을 돌면서 먼저
    잡힌 구간을 소비했다. 그러면 **결과가 이름 목록의 정렬 순서에 의존**한다 —
    정렬을 짧은 이름 우선으로 바꾸면 '면목동 69-14'(중랑구)가 '목동'(양천구)으로
    읽혔고, 백엔드 테스트 1,064건이 전부 통과했다(리뷰어 실증). 정렬 한 줄이
    오매칭을 막는 유일한 방어였고, 그 줄은 리팩터링으로 언제든 사라진다.

    지금은 **위치 기준 최대 일치**다: 텍스트를 왼쪽부터 훑으면서 그 자리에서
    시작하는 가장 긴 이름을 고르고, 고른 만큼 건너뛴다. 이름을 어떤 순서로 주든
    결과가 같다(`sorted(names)` · `reversed` · 무작위 전부 동일).
    앞쪽 낱말 경계는 `_boundary_ok` 가 본다.
    """
    # 첫 글자별로 후보를 모아 둔다 — 한 자리에서 볼 후보를 이름 전체가 아니라
    # 그 글자로 시작하는 것만으로 줄인다(길이 내림차순으로 고정).
    by_head: dict[str, list[str]] = {}
    for name in names:
        if name:
            by_head.setdefault(name[0], []).append(name)
    for bucket in by_head.values():
        bucket.sort(key=len, reverse=True)

    spans: list[tuple[int, int, str]] = []
    i = 0
    while i < len(text):
        hit: str | None = None
        for name in by_head.get(text[i], ()):
            if text.startswith(name, i):
                hit = name           # 길이 내림차순이라 첫 히트가 최장 일치다
                break
        if hit is not None and _boundary_ok(text, i):
            spans.append((i, i + len(hit), hit))
            i += len(hit)
            continue
        i += 1
    return spans


def _strip_admin_dong(text: str, names: Mapping[str, Any]) -> tuple[str, bool]:
    """'목2동' → '목동'. **되돌린 이름이 실제 법정동일 때만** 바꾼다."""
    changed = False

    def repl(m: re.Match[str]) -> str:
        nonlocal changed
        whole, stem = m.group(0), m.group(1) + "동"
        if whole in names:          # '문래동3가' 같은 진짜 법정동은 건드리지 않는다
            return whole
        if stem in names:
            changed = True
            return stem
        return whole

    return _ADMIN_DONG_RE.sub(repl, text), changed


@dataclass
class _Collected:
    refs: list[JibunRef]
    listed: list[tuple[str, int, int]]
    ambiguous: list[str]


def _collect(text: str, scope: DongScope, dong_match: str) -> _Collected:
    refs: list[JibunRef] = []
    seen: set[tuple[str, int, int, bool]] = set()
    listed: list[tuple[str, int, int]] = []
    ambiguous: list[str] = []
    for _, end, name in _find_dong_spans(text, scope.by_name):
        m = _NUMBER_RE.match(text, end)
        if m is None:
            continue
        main = int(m.group(2))
        sub = int(m.group(3)) if m.group(3) else 0
        listed.append((name, main, sub))
        if _JIBUN_LIST_RE.match(text, m.end()):
            # '송림동 2, 4번지' — 어느 쪽이 대표인지 특정할 수 없다.
            listed.append((name, -1, -1))
            continue
        code, how = scope.resolve(name)
        if code is None:
            # 동명이 시도 안에서 중복인데 시군구로 못 가른다 → **매칭하지 않는다.**
            if how == STATUS_AMBIGUOUS_DONG:
                ambiguous.append(name)
            continue
        ref = JibunRef(legal_dong_code=code, dong_name=name, main_no=main, sub_no=sub,
                       is_mountain=bool(m.group(1)), dong_match=dong_match,
                       dong_scope=how)
        if ref.key not in seen:
            seen.add(ref.key)
            refs.append(ref)
    return _Collected(refs, listed, ambiguous)


def parse_address(raw: str | None, scope: DongScope) -> ParsedAddress:
    """정비구역 대표지번 주소 → `JibunRef`. **애매하면 실패로 돌려준다.**

    실패가 정상 결과다 — 여기서 억지로 하나를 고르면 그 순간 틀린 근거가 만들어진다.
    """
    text = (raw or "").strip()
    if not text:
        return ParsedAddress(STATUS_NO_JIBUN, detail="지번주소가 비어 있습니다")
    if not scope.by_name:
        return ParsedAddress(STATUS_UNKNOWN_DONG,
                             detail="해당 시도의 법정동 목록을 찾지 못했습니다")

    found = _collect(text, scope, DONG_EXACT)
    dong_match = DONG_EXACT
    if not found.refs and not found.ambiguous:
        # 행정동 표기일 수 있다. 되돌린 이름이 실제 법정동일 때만 재시도한다.
        stripped, changed = _strip_admin_dong(text, scope.by_name)
        if changed:
            found = _collect(stripped, scope, DONG_ADMIN_STRIPPED)
            dong_match = DONG_ADMIN_STRIPPED

    cands = tuple(found.listed)
    if any(main < 0 for _, main, _ in cands):
        return ParsedAddress(
            STATUS_MULTI_JIBUN, detail="한 구역에 지번이 나열돼 대표지번을 특정할 수 없습니다",
            candidates=cands)
    if len(found.refs) > 1:
        return ParsedAddress(
            STATUS_MULTI_JIBUN,
            detail=f"지번이 {len(found.refs)}개 읽혀 대표지번을 특정할 수 없습니다",
            candidates=cands)
    if found.refs:
        ref = found.refs[0]
        notes = []
        if dong_match != DONG_EXACT:
            notes.append("행정동 표기 보정")
        if ref.dong_scope == DONG_SCOPE_SIDO_UNIQUE:
            notes.append(f"자료의 시군구 '{scope.sigungu}' 는 우리 법정동 목록에 없어 "
                         "시도 내 유일 법정동으로 확정")
        detail = f"{ref.dong_name} {ref.main_no}" + (f"-{ref.sub_no}" if ref.sub_no else "")
        if notes:
            detail += " (" + "; ".join(notes) + ")"
        return ParsedAddress(STATUS_OK, jibun=ref, detail=detail, candidates=cands)

    if found.ambiguous:
        return ParsedAddress(
            STATUS_AMBIGUOUS_DONG,
            detail=(f"법정동 '{found.ambiguous[0]}' 이(가) 시도 안에서 중복인데 "
                    f"자료의 시군구 '{scope.sigungu}' 로 가릴 수 없습니다"),
            candidates=cands)
    if _find_dong_spans(text, scope.by_name):
        return ParsedAddress(STATUS_NO_JIBUN,
                             detail="법정동은 찾았지만 번지가 없습니다")
    if _ROAD_RE.search(text):
        return ParsedAddress(STATUS_ROAD_ONLY,
                             detail="도로명 주소만 있어 지번을 알 수 없습니다")
    return ParsedAddress(STATUS_UNKNOWN_DONG,
                         detail="주소에서 법정동을 찾지 못했습니다")


# ---------------------------------------------------------------------------
# 값 변환
# ---------------------------------------------------------------------------
_DATE_RE = re.compile(r"(\d{4})[-./]?(\d{2})[-./]?(\d{2})")


def _date(raw: str | None) -> dt.date | None:
    """'2026-01-22' → date. 빈 값·'-'·형식 불일치는 **None**(0 이나 오늘로 채우지 않는다)."""
    if not raw:
        return None
    m = _DATE_RE.search(str(raw).strip())
    if not m:
        return None
    try:
        return dt.date(int(m.group(1)), int(m.group(2)), int(m.group(3)))
    except ValueError:
        return None


def _int(raw: str | None) -> int | None:
    if raw is None:
        return None
    text = str(raw).replace(",", "").strip()
    if not text or not text.lstrip("-").isdigit():
        return None
    value = int(text)
    return value if value > 0 else None


def _text(raw: str | None) -> str:
    value = (raw or "").strip()
    return "" if value == "-" else value


# ---------------------------------------------------------------------------
# 서울
# ---------------------------------------------------------------------------
#: CSV 헤더(한글) ↔ OpenAPI 키(영문). 두 경로가 **같은 파서**로 들어오게 한다.
SEOUL_FIELDS: dict[str, tuple[str, str]] = {
    "code": ("CODE", "CODE"),
    "sigungu": ("DISTRICT", "자치구"),
    "zone_name": ("ZONE_NM", "구역명"),
    "address": ("JIBUN_ADDR", "지번주소"),
    "biz_type": ("BIZ_TYPE", "사업유형"),
    "stage": ("BIZ_STAGE", "사업추진단계"),
    "existing": ("EXISTING_HOUSEHOLDS", "기존가구수(멸실량)"),
    "planned": ("TOT_BUILT_HOUSEHOLDS", "건립세대수_총합계"),
    "zone_on": ("ZONE_DESIGNATION_INIT_YMD", "구역지정_최초"),
    "zone_last_on": ("ZONE_DESIGNATION_LAST_YMD", "구역지정_변경최종"),
    "committee_on": ("PROMOTION_COMMITTEE_YMD", "추진위원회"),
    "assoc_on": ("ASSOCIATION_ESTABLISHMENT_YMD", "조합설립인가(사업시행자 지정일)"),
    "review_on": ("ARCHITECTURAL_REVIEW_YMD", "건축심의"),
    "impl_on": ("BIZ_IMPLEMENTATION_INIT_YMD", "사업시행인가_최초"),
    "impl_last_on": ("BIZ_IMPLEMENTATION_LAST_YMD", "사업시행인가_변경(최종)"),
    "disp_on": ("MGMT_DISPOSITION_INIT_YMD", "관리처분계획인가_최초"),
    "disp_last_on": ("MGMT_DISPOSITION_LAST_YMD", "관리처분계획인가_변경최종"),
    "reloc_start_on": ("MIGRATION_START_YMD", "이주시작일"),
    "reloc_end_on": ("MIGRATION_END_YMD", "이주종료일"),
    "constr_on": ("CONSTRUCTION_START_YMD", "착공일"),
}


def _pick(row: Mapping[str, Any], field: str) -> str:
    api_key, csv_key = SEOUL_FIELDS[field]
    if api_key in row:
        return _text(row.get(api_key))
    return _text(row.get(csv_key))


def _later(*values: dt.date | None) -> dt.date | None:
    """변경(최종) 일자가 있으면 그쪽이 최신이다. 둘 다 없으면 None."""
    known = [v for v in values if v is not None]
    return max(known) if known else None


def parse_seoul_rows(rows: Iterable[Mapping[str, Any]], *, as_of: dt.date,
                     dong_index: DongIndex) -> list[RedevRecord]:
    """서울 행(API JSON 또는 CSV DictReader) → 레코드.

    ⚠️ 한 행도 조용히 버리지 않는다. 지번을 못 읽은 행도 `parse_status` 를 달고
       그대로 반환한다 — 적재 스크립트가 세어서 보고할 수 있어야 한다.
    """
    out: list[RedevRecord] = []
    for row in rows:
        sigungu = _pick(row, "sigungu")
        address = _pick(row, "address")
        parsed = parse_address(address, dong_index.scope(SIDO_SEOUL, sigungu))
        jibun = parsed.jibun
        raw_stage = _pick(row, "stage")
        raw_type = _pick(row, "biz_type")
        code = _pick(row, "code") or f"{sigungu}|{_pick(row, 'zone_name')}"
        out.append(RedevRecord(
            source=SOURCE_SEOUL,
            source_key=code,
            source_url=SOURCE_URL_SEOUL,
            sido=SIDO_SEOUL,
            sigungu=sigungu,
            zone_name=_pick(row, "zone_name"),
            raw_stage=raw_stage,
            stage=normalize_stage(raw_stage),
            raw_biz_type=raw_type or None,
            biz_type=normalize_biz_type(raw_type),
            address_raw=address,
            as_of=as_of,
            parse_status=parsed.status,
            parse_detail=parsed.detail,
            legal_dong_code=jibun.legal_dong_code if jibun else None,
            main_no=jibun.main_no if jibun else None,
            sub_no=jibun.sub_no if jibun else None,
            is_mountain=bool(jibun.is_mountain) if jibun else False,
            dong_match=jibun.dong_match if jibun else None,
            dong_scope=jibun.dong_scope if jibun else None,
            zone_designated_on=_later(_date(_pick(row, "zone_on")),
                                      _date(_pick(row, "zone_last_on"))),
            committee_on=_date(_pick(row, "committee_on")),
            association_on=_date(_pick(row, "assoc_on")),
            design_review_on=_date(_pick(row, "review_on")),
            implementation_on=_later(_date(_pick(row, "impl_on")),
                                     _date(_pick(row, "impl_last_on"))),
            disposition_on=_later(_date(_pick(row, "disp_on")),
                                  _date(_pick(row, "disp_last_on"))),
            relocation_start_on=_date(_pick(row, "reloc_start_on")),
            relocation_end_on=_date(_pick(row, "reloc_end_on")),
            construction_start_on=_date(_pick(row, "constr_on")),
            existing_households=_int(_pick(row, "existing")),
            planned_households=_int(_pick(row, "planned")),
        ))
    return out


def parse_seoul_csv(raw: bytes | str, *, as_of: dt.date,
                    dong_index: DongIndex) -> list[RedevRecord]:
    text = decode_csv(raw) if isinstance(raw, bytes) else raw
    return parse_seoul_rows(csv.DictReader(io.StringIO(text)), as_of=as_of,
                            dong_index=dong_index)


# ---------------------------------------------------------------------------
# 인천
# ---------------------------------------------------------------------------
#: 인천 CSV 헤더는 공백이 섞여 있다('구 역 명', '면적(제곱미터)     ').
#: 헤더를 그대로 믿지 않고 **공백을 지운 뒤** 대조한다.
INCHEON_FIELDS: dict[str, tuple[str, ...]] = {
    "sigungu": ("구명",),
    "zone_name": ("구역명",),
    "address": ("위치",),
    "biz_type": ("사업유형",),
    "stage": ("진행단계",),
}


def _incheon_get(row: Mapping[str, Any], field: str) -> str:
    squeezed = {re.sub(r"\s+", "", str(k)): v for k, v in row.items()}
    for key in INCHEON_FIELDS[field]:
        if key in squeezed:
            return _text(squeezed[key])
    return ""


def parse_incheon_csv(raw: bytes | str, *, as_of: dt.date,
                      dong_index: DongIndex) -> list[RedevRecord]:
    """인천 CSV → 레코드. **단계별 일자·세대수는 이 출처에 없다 → 전부 None.**"""
    text = decode_csv(raw) if isinstance(raw, bytes) else raw
    out: list[RedevRecord] = []
    for row in csv.DictReader(io.StringIO(text)):
        sigungu = _incheon_get(row, "sigungu")
        zone = _incheon_get(row, "zone_name")
        address = _incheon_get(row, "address")
        if not sigungu and not zone:
            continue                       # 빈 줄
        parsed = parse_address(address, dong_index.scope(SIDO_INCHEON, sigungu))
        jibun = parsed.jibun
        raw_stage = _incheon_get(row, "stage")
        raw_type = _incheon_get(row, "biz_type")
        out.append(RedevRecord(
            source=SOURCE_INCHEON,
            source_key=f"{sigungu}|{zone}|{address}",
            source_url=SOURCE_URL_INCHEON,
            sido=SIDO_INCHEON,
            sigungu=sigungu,
            zone_name=zone,
            raw_stage=raw_stage,
            stage=normalize_stage(raw_stage),
            raw_biz_type=raw_type or None,
            biz_type=normalize_biz_type(raw_type),
            address_raw=address,
            as_of=as_of,
            parse_status=parsed.status,
            parse_detail=parsed.detail,
            legal_dong_code=jibun.legal_dong_code if jibun else None,
            main_no=jibun.main_no if jibun else None,
            sub_no=jibun.sub_no if jibun else None,
            is_mountain=bool(jibun.is_mountain) if jibun else False,
            dong_match=jibun.dong_match if jibun else None,
            dong_scope=jibun.dong_scope if jibun else None,
        ))
    return out


def build_dong_index(rows: Iterable[tuple[str, str, str, str]]) -> DongIndex:
    """`(법정동코드, 시도, 시군구, 동)` 행 → 시도별 색인.

    시군구가 아니라 **시도**로 나누는 이유는 `DongScope` 독스트링 참조
    (시군구 이름은 개편으로 바뀌고, '중구'는 서울에도 인천에도 있다).
    """
    index: dict[str, dict[str, list[tuple[str, str]]]] = {}
    for code, sido, sigungu, dong in rows:
        if not sido or not dong:
            continue
        index.setdefault(sido, {}).setdefault(dong, []).append((code, sigungu or ""))
    return DongIndex({sido: {name: tuple(v) for name, v in names.items()}
                      for sido, names in index.items()})
