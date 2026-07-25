"""국토교통부 아파트 매매 실거래가 수집.

설계 근거: docs/02-design/agents/01-listing-researcher.md, security.md §5

이 소스가 1순위인 이유
----------------------
무료·합법·안정적이다. 포털 수집이 막혀도 이것만으로 서비스가 성립해야 한다(G4).

동(棟) 정보 — 설계 가정 정정(2026-07-25 실측)
---------------------------------------------
설계 초안(erd §0)은 "동 정보 없음"으로 봤으나, **운영 API 는 aptDong 을 77~93%
제공한다**(강남87·분당93·인천91·종로77%). 그래서 F4(동별 가치 차이)는 좌표 추정이
아니라 **실거래 기반 실측**으로 갈 수 있다. 다만 결측 10~23% 가 있어 apt_dong 은
자연키에 넣지 않고(키 흔들림 방지) 부가 컬럼으로만 저장하며, 결측분은 좌표추정으로 폴백한다.

금액 단위 함정
--------------
`거래금액` 은 **만원 단위 문자열**이고 콤마와 공백이 섞여 온다: `" 82,500"`.
이걸 그대로 int 로 읽으면 8만원짜리 아파트가 된다. 반드시 정리 후 ×10,000.
"""
from __future__ import annotations

import datetime as dt
import re
import xml.etree.ElementTree as ET
from dataclasses import dataclass
from typing import Any

SOURCE_NAME = "molit_apt_trade"

#: 응답 필드명이 버전에 따라 한글/영문으로 다르게 온다. 둘 다 받는다.
_FIELD_ALIASES: dict[str, tuple[str, ...]] = {
    "amount": ("거래금액", "dealAmount"),
    "year": ("년", "dealYear"),
    "month": ("월", "dealMonth"),
    "day": ("일", "dealDay"),
    "name": ("아파트", "aptNm", "aptName"),
    "area": ("전용면적", "excluUseAr"),
    "region_code": ("지역코드", "sggCd"),
    "dong": ("법정동", "umdNm"),
    "floor": ("층", "floor"),
    "apt_dong": ("aptDong", "동"),   # 운영 API 에 77~93% 존재 — F4(동별 가치)를 실측 가능케 함
    "built_year": ("건축년도", "buildYear"),
    "cancelled": ("해제여부", "cdealType"),
    "cancel_date": ("해제사유발생일", "cdealDay"),
    "registered": ("등기일자", "rgstDate"),
    "trade_type": ("거래유형", "dealingGbn"),
}


class MolitParseError(ValueError):
    """응답을 신뢰할 수 없음. 조용히 넘기지 않고 실패로 기록한다."""


@dataclass(frozen=True)
class MolitTrade:
    """수집된 실거래 한 건. 모든 레코드에 출처·수집시각이 붙는다(G2)."""

    complex_name: str
    region_code: str
    legal_dong: str | None
    contract_date: dt.date
    price_krw: int
    area_m2: float
    floor: int | None
    #: 실거래 동(棟). 운영 API 가 77~93% 제공(강남87·분당93·인천91·종로77%, 2026-07-25 실측).
    #: '410'·'114' 숫자 또는 '청담(103)' 이름 혼재 → 원본 보존, 빈값은 None.
    #: 설계 가정(erd §0 '동 정보 없음')을 뒤집는다 — F4 를 좌표추정 대신 실거래로 할 수 있다.
    apt_dong: str | None
    built_year: int | None
    is_cancelled: bool
    cancelled_on: dt.date | None
    registered_at: dt.date | None
    trade_type: str | None
    source: str
    ingested_at: dt.datetime

    def to_row(self) -> dict[str, Any]:
        return {
            "complex_name": self.complex_name,
            "region_code": self.region_code,
            "contract_date": self.contract_date,
            "price_krw": self.price_krw,
            "area_m2": self.area_m2,
            "floor": self.floor,
            "apt_dong": self.apt_dong,
            "is_cancelled": self.is_cancelled,
            "registered_at": self.registered_at,
            "trade_type": self.trade_type,
            "source": self.source,
            "ingested_at": self.ingested_at,
        }


def normalize_apt_dong(raw: str | None) -> str | None:
    """실거래 동(棟) 표기 정규화. 빈값·공백은 None, 그 외는 원본을 strip 해 보존한다.

    운영 API 는 '410'·'114'(동번호)와 '청담(103)'(이름+번호)을 혼재해 준다.
    여기서는 원본 표기를 살리고(F4 에서 building.name 과 매칭할 때 필요),
    무의미한 공백/하이픈만 None 으로 정리한다 — 없는 걸 있다고 지어내지 않는다.
    """
    if not raw:
        return None
    v = raw.strip()
    if not v or v in ("-", "0"):
        return None
    return v


def _text(item: ET.Element, key: str) -> str | None:
    for tag in _FIELD_ALIASES[key]:
        el = item.find(tag)
        if el is not None and el.text is not None:
            value = el.text.strip()
            if value:
                return value
    return None


def parse_amount_krw(raw: str) -> int:
    """`" 82,500"` (만원) → `825_000_000` (원).

    공백·콤마를 제거하고 만원 단위를 원으로 환산한다. 이 변환을 빠뜨리면
    시세가 1/10000 로 나와 모든 분석이 무너진다.
    """
    cleaned = re.sub(r"[^\d.-]", "", raw or "")
    if not cleaned:
        raise MolitParseError(f"거래금액을 읽을 수 없습니다: {raw!r}")
    try:
        man = float(cleaned)
    except ValueError as exc:
        raise MolitParseError(f"거래금액 형식 오류: {raw!r}") from exc
    if man <= 0:
        raise MolitParseError(f"거래금액이 0 이하입니다: {raw!r}")
    return int(round(man * 10_000))


def _parse_date(y: str | None, m: str | None, d: str | None) -> dt.date:
    try:
        return dt.date(int(y), int(m), int(d))          # type: ignore[arg-type]
    except (TypeError, ValueError) as exc:
        raise MolitParseError(f"계약일 형식 오류: {y}-{m}-{d}") from exc


def _parse_compact_date(raw: str | None) -> dt.date | None:
    """`'26.07.12'` 또는 `'20260712'` 형태를 관대하게 읽는다. 못 읽으면 None."""
    if not raw:
        return None
    digits = re.sub(r"\D", "", raw)
    try:
        if len(digits) == 8:
            return dt.datetime.strptime(digits, "%Y%m%d").date()
        if len(digits) == 6:
            return dt.datetime.strptime(digits, "%y%m%d").date()
    except ValueError:
        return None
    return None


def parse_response(xml_text: str, *, now: dt.datetime | None = None) -> list[MolitTrade]:
    """XML 응답을 파싱한다.

    개별 항목이 깨져도 전체를 버리지 않되, **조용히 건너뛰지 않는다** —
    호출부가 실패 건수를 `ingest_log` 에 기록할 수 있도록 예외를 모아 올린다.
    """
    now = now or dt.datetime.now(dt.timezone.utc)
    try:
        root = ET.fromstring(xml_text)
    except ET.ParseError as exc:
        raise MolitParseError(f"XML 파싱 실패: {exc}") from exc

    # 공공데이터포털은 오류도 200 으로 준다. 결과코드를 반드시 확인한다.
    code_el = root.find(".//resultCode")
    if code_el is not None and (code_el.text or "").strip() not in ("00", "000"):
        msg_el = root.find(".//resultMsg")
        raise MolitParseError(
            f"API 오류 resultCode={code_el.text} msg={getattr(msg_el, 'text', None)}"
        )

    out: list[MolitTrade] = []
    for item in root.iter("item"):
        amount_raw = _text(item, "amount")
        if amount_raw is None:
            raise MolitParseError("거래금액 필드가 없습니다")

        area_raw = _text(item, "area")
        try:
            area = float(area_raw) if area_raw else 0.0
        except ValueError as exc:
            raise MolitParseError(f"전용면적 형식 오류: {area_raw!r}") from exc
        if area <= 0:
            raise MolitParseError(f"전용면적이 0 이하입니다: {area_raw!r}")

        floor_raw = _text(item, "floor")
        try:
            floor = int(floor_raw) if floor_raw else None
        except ValueError:
            floor = None

        built_raw = _text(item, "built_year")
        try:
            built = int(built_raw) if built_raw else None
        except ValueError:
            built = None

        cancelled_flag = (_text(item, "cancelled") or "").strip()
        out.append(MolitTrade(
            complex_name=(_text(item, "name") or "").strip(),
            region_code=(_text(item, "region_code") or "").strip(),
            legal_dong=_text(item, "dong"),
            contract_date=_parse_date(_text(item, "year"), _text(item, "month"),
                                      _text(item, "day")),
            price_krw=parse_amount_krw(amount_raw),
            area_m2=area,
            floor=floor,
            apt_dong=normalize_apt_dong(_text(item, "apt_dong")),
            built_year=built,
            is_cancelled=cancelled_flag == "O",
            cancelled_on=_parse_compact_date(_text(item, "cancel_date")),
            registered_at=_parse_compact_date(_text(item, "registered")),
            trade_type=_text(item, "trade_type"),
            source=SOURCE_NAME,
            ingested_at=now,
        ))
    return out


def build_params(*, service_key: str, region_code5: str, ym: str,
                 rows: int = 1000, page: int = 1) -> dict[str, str]:
    """요청 파라미터. `region_code5` 는 시군구 5자리, `ym` 은 YYYYMM."""
    if not re.fullmatch(r"\d{5}", region_code5):
        raise ValueError("region_code5 는 숫자 5자리여야 합니다")
    if not re.fullmatch(r"\d{6}", ym):
        raise ValueError("ym 은 YYYYMM 형식이어야 합니다")
    return {
        "serviceKey": service_key,
        "LAWD_CD": region_code5,
        "DEAL_YMD": ym,
        "numOfRows": str(rows),
        "pageNo": str(page),
    }


def months_between(start: dt.date, end: dt.date) -> list[str]:
    """증분 수집용 YYYYMM 목록. 전체 재수집 대신 필요한 달만 돈다."""
    if start > end:
        return []
    out: list[str] = []
    y, m = start.year, start.month
    while (y, m) <= (end.year, end.month):
        out.append(f"{y:04d}{m:02d}")
        m += 1
        if m > 12:
            y, m = y + 1, 1
    return out
