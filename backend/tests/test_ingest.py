"""수집기 테스트 — G4(수집 합법성)와 파싱 정확성.

가장 중요한 것: **금액 단위 변환**. 만원 단위를 원으로 안 바꾸면 시세가 1/10000 이 되고
모든 분석이 조용히 무너진다.
"""
from __future__ import annotations

import datetime as dt
import random

import pytest

from app.ingest.molit import (
    MolitParseError,
    build_params,
    months_between,
    parse_amount_krw,
    parse_response,
)
from app.ingest.ratelimit import RateLimiter, backoff_delays

SAMPLE = """<?xml version="1.0" encoding="UTF-8"?>
<response>
  <header><resultCode>00</resultCode><resultMsg>NORMAL SERVICE.</resultMsg></header>
  <body>
    <items>
      <item>
        <거래금액> 142,000</거래금액>
        <건축년도>2008</건축년도>
        <년>2026</년><월>6</월><일>12</일>
        <아파트>○○아파트</아파트>
        <전용면적>84.97</전용면적>
        <지역코드>11680</지역코드>
        <법정동>대치동</법정동>
        <층>14</층>
        <해제여부> </해제여부>
        <등기일자>26.07.02</등기일자>
        <거래유형>중개거래</거래유형>
      </item>
      <item>
        <거래금액>98,500</거래금액>
        <년>2026</년><월>5</월><일>3</일>
        <아파트>△△아파트</아파트>
        <전용면적>59.98</전용면적>
        <지역코드>11680</지역코드>
        <층>3</층>
        <해제여부>O</해제여부>
        <해제사유발생일>26.05.20</해제사유발생일>
      </item>
    </items>
  </body>
</response>
"""

ENGLISH_SAMPLE = """<?xml version="1.0" encoding="UTF-8"?>
<response>
  <header><resultCode>000</resultCode></header>
  <body><items>
    <item>
      <dealAmount>110,000</dealAmount>
      <dealYear>2026</dealYear><dealMonth>4</dealMonth><dealDay>9</dealDay>
      <aptNm>□□아파트</aptNm>
      <excluUseAr>74.52</excluUseAr>
      <sggCd>41135</sggCd>
      <floor>7</floor>
    </item>
  </items></body>
</response>
"""


# ---------------------------------------------------------------------------
# 금액 변환 — 가장 중요한 부분
# ---------------------------------------------------------------------------

def test_만원단위를_원으로_바꾼다():
    assert parse_amount_krw(" 142,000") == 1_420_000_000


def test_공백과_콤마를_제거한다():
    assert parse_amount_krw("  98,500  ") == 985_000_000
    assert parse_amount_krw("98500") == 985_000_000


def test_빈_금액은_오류():
    with pytest.raises(MolitParseError):
        parse_amount_krw("")
    with pytest.raises(MolitParseError):
        parse_amount_krw("   ")


def test_0이하_금액은_오류():
    with pytest.raises(MolitParseError):
        parse_amount_krw("0")


# ---------------------------------------------------------------------------
# 파싱
# ---------------------------------------------------------------------------

def test_한글_필드_파싱():
    now = dt.datetime(2026, 7, 24, tzinfo=dt.timezone.utc)
    rows = parse_response(SAMPLE, now=now)

    assert len(rows) == 2
    first = rows[0]
    assert first.complex_name == "○○아파트"
    assert first.price_krw == 1_420_000_000
    assert first.contract_date == dt.date(2026, 6, 12)
    assert first.area_m2 == pytest.approx(84.97)
    assert first.floor == 14
    assert first.built_year == 2008
    assert first.is_cancelled is False
    assert first.registered_at == dt.date(2026, 7, 2)
    assert first.trade_type == "중개거래"


def test_영문_필드도_파싱된다():
    rows = parse_response(ENGLISH_SAMPLE)
    assert len(rows) == 1
    assert rows[0].complex_name == "□□아파트"
    assert rows[0].price_krw == 1_100_000_000
    assert rows[0].region_code == "41135"


def test_해제거래가_표시된다():
    """해제 거래를 못 알아보면 허위 신고가가 시세를 왜곡한다."""
    rows = parse_response(SAMPLE)
    assert rows[1].is_cancelled is True
    assert rows[1].cancelled_on == dt.date(2026, 5, 20)


def test_모든_레코드에_출처와_수집시각이_붙는다():
    """G2 근거 감사의 물리적 기반."""
    now = dt.datetime(2026, 7, 24, 3, 0, tzinfo=dt.timezone.utc)
    for row in parse_response(SAMPLE, now=now):
        assert row.source == "molit_apt_trade"
        assert row.ingested_at == now


def test_API_오류코드는_예외로_올린다():
    """공공데이터포털은 오류도 HTTP 200 으로 준다. 결과코드를 봐야 한다."""
    bad = """<response><header><resultCode>30</resultCode>
             <resultMsg>SERVICE KEY IS NOT REGISTERED ERROR.</resultMsg>
             </header><body><items/></body></response>"""
    with pytest.raises(MolitParseError, match="API 오류"):
        parse_response(bad)


def test_깨진_XML은_예외():
    with pytest.raises(MolitParseError, match="XML 파싱 실패"):
        parse_response("<response><unclosed>")


def test_면적이_없으면_예외():
    bad = """<response><header><resultCode>00</resultCode></header><body><items>
      <item><거래금액>100,000</거래금액><년>2026</년><월>1</월><일>1</일>
      <아파트>x</아파트><지역코드>11680</지역코드></item>
    </items></body></response>"""
    with pytest.raises(MolitParseError, match="전용면적"):
        parse_response(bad)


def test_결과가_없으면_빈_목록():
    empty = """<response><header><resultCode>00</resultCode></header>
               <body><items/></body></response>"""
    assert parse_response(empty) == []


def test_동_정보는_애초에_없다():
    """API 가 동을 주지 않는다는 사실을 테스트로 못박아 둔다 (erd.md §0)."""
    rows = parse_response(SAMPLE)
    assert not hasattr(rows[0], "building_name")
    assert not hasattr(rows[0], "dong_no")


# ---------------------------------------------------------------------------
# 요청 파라미터
# ---------------------------------------------------------------------------

def test_파라미터_구성():
    p = build_params(service_key="KEY", region_code5="11680", ym="202606")
    assert p["LAWD_CD"] == "11680"
    assert p["DEAL_YMD"] == "202606"
    assert p["numOfRows"] == "1000"


def test_잘못된_지역코드는_거부():
    with pytest.raises(ValueError):
        build_params(service_key="K", region_code5="1168", ym="202606")


def test_잘못된_연월은_거부():
    with pytest.raises(ValueError):
        build_params(service_key="K", region_code5="11680", ym="2026-06")


def test_증분수집_월목록():
    got = months_between(dt.date(2025, 11, 1), dt.date(2026, 2, 15))
    assert got == ["202511", "202512", "202601", "202602"]


def test_역순이면_빈_목록():
    assert months_between(dt.date(2026, 5, 1), dt.date(2026, 1, 1)) == []


# ---------------------------------------------------------------------------
# 속도 제한 (G4)
# ---------------------------------------------------------------------------

class FakeClock:
    def __init__(self):
        self.t = 0.0

    def __call__(self) -> float:
        return self.t

    def sleep(self, sec: float) -> None:
        self.t += sec


def test_첫_요청은_기다리지_않는다():
    clock = FakeClock()
    rl = RateLimiter(1.0, clock=clock, sleeper=clock.sleep)
    assert rl.wait() == 0.0


def test_연속_요청은_최소간격을_지킨다():
    clock = FakeClock()
    rl = RateLimiter(1.0, clock=clock, sleeper=clock.sleep)
    rl.wait()
    slept = rl.wait()
    assert slept == pytest.approx(1.0)


def test_충분히_시간이_지났으면_안_기다린다():
    clock = FakeClock()
    rl = RateLimiter(1.0, clock=clock, sleeper=clock.sleep)
    rl.wait()
    clock.t += 5.0
    assert rl.wait() == 0.0


def test_지터가_간격을_늘린다():
    clock = FakeClock()
    rl = RateLimiter(1.0, jitter_sec=0.5, clock=clock, sleeper=clock.sleep,
                     rng=random.Random(0))
    rl.wait()
    assert rl.wait() >= 1.0


def test_음수_간격은_거부():
    with pytest.raises(ValueError):
        RateLimiter(-1.0)


def test_백오프는_지수적으로_늘고_상한이_있다():
    assert backoff_delays(4, base=1.0) == [1.0, 2.0, 4.0, 8.0]
    assert backoff_delays(8, base=1.0, cap=10.0)[-1] == 10.0
