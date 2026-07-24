"""시세 분석 테스트.

이 테스트가 지키려는 것
-----------------------
1. 해제 거래가 통계에 섞이면 안 된다 (허위 신고가가 시세를 왜곡한다)
2. 표본이 적으면 **숫자를 만들지 않는다** — 이 제품의 정체성이다
3. 기간을 넓혔으면 그 사실이 결과에 남아야 한다
"""
from __future__ import annotations

import datetime as dt

import pytest

from app.domain.valuation.models import ListingRow, TradeRow, floor_band
from app.domain.valuation.stats import (
    ask_gap_pct,
    eligible_trades,
    fair_price_band,
    floor_effect,
    liquidity,
)

TODAY = dt.date(2026, 7, 24)
OKU = 100_000_000


def t(days_ago: int, price_oku: float, *, area=84.97, floor=10, cancelled=False) -> TradeRow:
    return TradeRow(
        contract_date=TODAY - dt.timedelta(days=days_ago),
        price_krw=int(price_oku * OKU),
        area_m2=area,
        floor=floor,
        is_cancelled=cancelled,
    )


# ---------------------------------------------------------------------------
# 표본 선별
# ---------------------------------------------------------------------------

def test_해제거래는_제외된다():
    trades = [t(10, 14.0), t(20, 30.0, cancelled=True), t(30, 14.2)]
    kept = eligible_trades(trades, as_of=TODAY)
    assert len(kept) == 2
    assert all(not x.is_cancelled for x in kept)


def test_기간_밖_거래는_제외된다():
    trades = [t(10, 14.0), t(400, 12.0)]
    kept = eligible_trades(trades, months=6, as_of=TODAY)
    assert len(kept) == 1


def test_면적이_다르면_제외된다():
    trades = [t(10, 14.0, area=84.97), t(10, 9.0, area=59.98)]
    kept = eligible_trades(trades, area_m2=84.97, as_of=TODAY)
    assert len(kept) == 1


def test_면적_허용오차_안이면_포함된다():
    trades = [t(10, 14.0, area=84.97), t(10, 14.1, area=84.99)]
    kept = eligible_trades(trades, area_m2=84.97, as_of=TODAY)
    assert len(kept) == 2


def test_미래_계약일은_데이터오류로_제외():
    future = TradeRow(contract_date=TODAY + dt.timedelta(days=5),
                      price_krw=14 * OKU, area_m2=84.97, floor=10)
    assert eligible_trades([future], as_of=TODAY) == []


# ---------------------------------------------------------------------------
# 적정가 밴드
# ---------------------------------------------------------------------------

def test_표본이_부족하면_밴드를_만들지_않는다():
    trades = [t(10, 14.0), t(20, 14.2)]        # 2건
    band = fair_price_band(trades, area_m2=84.97, as_of=TODAY)

    assert band.available is False
    assert band.median_krw is None, "표본 부족인데 숫자를 만들면 안 된다"
    assert "미달" in (band.reason or "")


def test_충분한_표본이면_밴드가_나온다():
    trades = [t(d, p) for d, p in
              [(10, 13.8), (30, 14.0), (50, 14.1), (70, 14.2), (90, 14.5)]]
    band = fair_price_band(trades, area_m2=84.97, as_of=TODAY)

    assert band.available is True
    assert band.sample_size == 5
    assert band.median_krw == int(14.1 * OKU)
    assert band.p25_krw <= band.median_krw <= band.p75_krw
    assert band.expanded is False
    assert band.period_months == 6


def test_표본이_부족하면_기간을_넓히고_표시한다():
    """최근 6개월엔 3건, 24개월까지 넓히면 6건."""
    trades = [t(d, 14.0) for d in (10, 60, 120)] + [t(d, 13.5) for d in (400, 500, 600)]
    band = fair_price_band(trades, area_m2=84.97, as_of=TODAY)

    assert band.available is True
    assert band.expanded is True, "기간 확장 사실이 결과에 남아야 한다"
    assert band.period_months and band.period_months > 6
    assert band.sample_size >= 5


def test_해제거래가_밴드를_왜곡하지_않는다():
    normal = [t(d, 14.0) for d in (10, 20, 30, 40, 50)]
    with_fake = normal + [t(25, 50.0, cancelled=True)]

    b1 = fair_price_band(normal, area_m2=84.97, as_of=TODAY)
    b2 = fair_price_band(with_fake, area_m2=84.97, as_of=TODAY)
    assert b1.median_krw == b2.median_krw


# ---------------------------------------------------------------------------
# 층 효과
# ---------------------------------------------------------------------------

def test_층대_구분():
    assert floor_band(1) == "1-5"
    assert floor_band(9) == "6-15"
    assert floor_band(25) == "16+"
    assert floor_band(None) is None


def test_층효과는_표본이_적으면_만들지_않는다():
    trades = [t(10, 14.0, floor=3)] + [t(d, 14.5, floor=10) for d in (20, 30, 40)]
    eff = floor_effect(trades)
    assert "1-5" not in eff, "1건짜리 층대에 비율을 만들면 안 된다"
    assert "6-15" in eff


def test_저층이_할인되면_보정이_1보다_작다():
    low = [t(d, 13.0, floor=2) for d in (5, 15, 25)]
    mid = [t(d, 14.0, floor=10) for d in (35, 45, 55)]
    eff = floor_effect(low + mid)
    assert eff["1-5"] < 1.0 < eff["16+"] if "16+" in eff else eff["1-5"] < 1.0


def test_대상층_보정이_밴드에_반영된다():
    low = [t(d, 13.0, floor=2) for d in (5, 15, 25)]
    mid = [t(d, 15.0, floor=10) for d in (35, 45, 55)]

    band_low = fair_price_band(low + mid, area_m2=84.97, as_of=TODAY, target_floor=2)
    band_mid = fair_price_band(low + mid, area_m2=84.97, as_of=TODAY, target_floor=10)
    assert band_low.median_krw < band_mid.median_krw


# ---------------------------------------------------------------------------
# 호가 갭
# ---------------------------------------------------------------------------

def test_호가갭_계산():
    trades = [t(d, 14.0) for d in (10, 20, 30, 40, 50)]
    band = fair_price_band(trades, area_m2=84.97, as_of=TODAY)
    assert ask_gap_pct(int(14.7 * OKU), band) == pytest.approx(5.0, abs=0.01)


def test_밴드가_없으면_갭도_없다():
    band = fair_price_band([t(10, 14.0)], area_m2=84.97, as_of=TODAY)
    assert ask_gap_pct(int(14.7 * OKU), band) is None, "근거 없이 갭을 계산하면 안 된다"


# ---------------------------------------------------------------------------
# 환금성
# ---------------------------------------------------------------------------

def _listing(i: int, days_listed: int) -> ListingRow:
    return ListingRow(
        id=i, ask_price_krw=int(14.5 * OKU), area_m2=84.97, floor=9,
        listed_at=TODAY - dt.timedelta(days=days_listed),
        collected_at=TODAY, status="active",
    )


def test_환금성_지표():
    trades = [t(d, 14.0) for d in range(10, 360, 20)]     # 12개월 내 다수
    listings = [_listing(1, 10), _listing(2, 50)]
    liq = liquidity(trades, listings, total_households=500, as_of=TODAY)

    assert liq.turnover_12m_pct is not None
    assert liq.median_days_on_market == 30
    assert liq.grade in {"좋음", "보통", "나쁨"}


def test_세대수를_모르면_회전율을_만들지_않는다():
    liq = liquidity([t(10, 14.0)], [], total_households=None, as_of=TODAY)
    assert liq.turnover_12m_pct is None
    assert liq.grade == "판단보류"


def test_밴드_evidence에_표본수가_들어간다():
    trades = [t(d, 14.0) for d in (10, 20, 30, 40, 50)]
    band = fair_price_band(trades, area_m2=84.97, as_of=TODAY)
    ev = band.to_evidence(as_of=TODAY)

    assert len(ev) == 1
    assert ev[0]["data_rows"] == 5
    assert ev[0]["source"]
    assert ev[0]["as_of"] == "2026-07-24"


def test_밴드가_없으면_evidence도_비어있다():
    band = fair_price_band([t(10, 14.0)], area_m2=84.97, as_of=TODAY)
    assert band.to_evidence(as_of=TODAY) == []
