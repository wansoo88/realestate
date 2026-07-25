"""국토부 실거래 레코드 정규화 — MolitTrade → complex / unit_type / trade 키.

설계 근거: docs/02-design/erd.md(P1 단지→동→타입 3계층, §0 동 정보 부재) ·
          team/roles/re-data.md(중복 제거 기준 문서화, 결측·이상치는 버리지 말고 표시)

왜 순수 함수인가
----------------
정규화·중복판정 규칙은 **하나여야** 한다. DB 로더와 인메모리 검증이 서로 다른 규칙을 쓰면
"테스트는 통과하는데 운영에서 중복이 쌓이는" 최악이 된다. 그래서 키 산출을 여기 한 곳에
모아 두고, 로더들은 이 키만 쓴다.

⚠️ MolitTrade 가 주지 않는(또는 불완전한) 것
--------------------------------------------
- **동(棟)**: 운영 API 가 77~93% 제공(설계 초안 erd §0 정정, 2026-07-25 실측).
  결측 10~23% 가 있어 apt_dong 은 **자연키에 넣지 않고**(키 흔들림 방지) trade 부가
  컬럼으로만 저장한다 — 시세 통계 매칭은 층까지, 동은 F4 실측에 부가로 쓴다.
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
class TradeNaturalKey:
    """실거래 자연키 — 한 거래의 정체성. 재수집 시 이 키로 **같은 거래를 찾아 upsert** 한다.

    ⚠️ **is_cancelled 는 키에 넣지 않는다** (INGEST-2, CHARTER §0 최대 리스크).
    허위신고→해제는 국내 가격조작 수법이고, is_cancelled 추적의 목적은 그걸 걷어내는 것이다.
    is_cancelled 를 키에 넣으면 '정상 15억' 유입 후 같은 거래가 해제되어 재유입될 때
    키가 달라져 **원본 정상행이 그대로 남고** 시세 통계(NOT is_cancelled)에 계속 잡힌다.
    키에서 빼야 해제가 원본 행을 UPDATE 해서 시세에서 사라진다.

    MOLIT 은 거래 고유 ID 를 주지 않는다. 아주 드물게 같은 단지·같은 날·같은 층·같은 면적·
    같은 가격의 서로 다른 거래가 하나로 합쳐질 수 있으나, 원천 ID 가 없는 한 이게 최선이다.
    """

    complex: ComplexKey
    contract_date: dt.date
    price_krw: int
    area_m2: float
    floor: int | None


def complex_key(t: MolitTrade) -> ComplexKey:
    return ComplexKey(
        region_sgg5=(t.region_code or "").strip(),
        legal_dong=(t.legal_dong.strip() if t.legal_dong else None),
        name=_norm_name(t.complex_name),
    )


def unit_type_key(t: MolitTrade) -> UnitTypeKey:
    return UnitTypeKey(complex=complex_key(t), area_m2=_norm_area(t.area_m2))


def trade_natural_key(t: MolitTrade) -> TradeNaturalKey:
    return TradeNaturalKey(
        complex=complex_key(t),
        contract_date=t.contract_date,
        price_krw=t.price_krw,
        area_m2=_norm_area(t.area_m2),
        floor=t.floor,
    )
