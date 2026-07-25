"""국토부 실거래 레코드 정규화 — MolitTrade → complex / unit_type / trade 키.

설계 근거: docs/02-design/erd.md(P1 단지→동→타입 3계층, §0 동 정보 부재) ·
          team/roles/re-data.md(중복 제거 기준 문서화, 결측·이상치는 버리지 말고 표시)

왜 순수 함수인가
----------------
정규화·중복판정 규칙은 **하나여야** 한다. DB 로더와 인메모리 검증이 서로 다른 규칙을 쓰면
"테스트는 통과하는데 운영에서 중복이 쌓이는" 최악이 된다. 그래서 키 산출을 여기 한 곳에
모아 두고, 로더들은 이 키만 쓴다.

⚠️ MolitTrade 가 주지 않는 것
-----------------------------
- **동(棟)**: 없음(erd.md §0). trade 는 층까지만.
- **좌표**: 없음. complex.geom 은 지오코딩(geocode.py)으로 후처리 enrich.
- **법정동코드 10자리**: region_code 는 시군구 5자리만 온다. 10자리 FK 는 resolver 필요.
"""
from __future__ import annotations

import datetime as dt
from dataclasses import dataclass

from app.ingest.molit import MolitTrade

#: 전용면적 비교 정밀도. 스키마 numeric(8,4) 와 맞춘다. 부동소수 흔들림으로 같은
#: 타입이 다른 타입으로 갈라지지 않게 반올림해 키를 만든다.
AREA_DECIMALS = 4


def _norm_name(name: str | None) -> str:
    """단지명 정규화 — 앞뒤 공백만 제거. 과한 정규화는 다른 단지를 합쳐 버린다.

    "○○아파트" 와 "○○아파트 " 는 같지만, "○○1차"·"○○2차"는 **다른 단지**다.
    그래서 공백만 정리하고 숫자·차수는 절대 건드리지 않는다.
    """
    return (name or "").strip()


def _norm_area(area_m2: float) -> float:
    return round(float(area_m2), AREA_DECIMALS)


@dataclass(frozen=True)
class ComplexKey:
    """단지 식별 자연키. region_code 는 MOLIT 의 시군구 5자리다(10자리 아님)."""

    region_sgg5: str
    legal_dong: str | None
    name: str


@dataclass(frozen=True)
class UnitTypeKey:
    """면적 타입 키. MOLIT 에 type_name(84A 등)이 없어 면적으로만 가른다."""

    complex: ComplexKey
    area_m2: float


@dataclass(frozen=True)
class TradeDedupKey:
    """실거래 재수집 멱등성 키.

    MOLIT 은 거래 고유 ID 를 주지 않는다. 증분 수집이 최근 2개월을 다시 받으므로
    같은 거래가 반복 유입된다 → 이 자연키로 이미 있는 건 건너뛴다.
    (아주 드물게 같은 단지·같은 날·같은 층·같은 면적·같은 가격의 서로 다른 거래가
     하나로 합쳐질 수 있으나, 거래 ID 가 없는 한 이게 최선이다. 근본 해결은 원천 ID.)
    """

    complex: ComplexKey
    contract_date: dt.date
    price_krw: int
    area_m2: float
    floor: int | None
    is_cancelled: bool


def complex_key(t: MolitTrade) -> ComplexKey:
    return ComplexKey(
        region_sgg5=(t.region_code or "").strip(),
        legal_dong=(t.legal_dong.strip() if t.legal_dong else None),
        name=_norm_name(t.complex_name),
    )


def unit_type_key(t: MolitTrade) -> UnitTypeKey:
    return UnitTypeKey(complex=complex_key(t), area_m2=_norm_area(t.area_m2))


def trade_dedup_key(t: MolitTrade) -> TradeDedupKey:
    return TradeDedupKey(
        complex=complex_key(t),
        contract_date=t.contract_date,
        price_krw=t.price_krw,
        area_m2=_norm_area(t.area_m2),
        floor=t.floor,
        is_cancelled=t.is_cancelled,
    )
