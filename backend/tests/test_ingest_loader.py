"""수집 적재 파이프라인 검증 — 픽스처(실응답 형태 XML)로 parse→normalize→load 전 구간.

DB 없이 InMemoryTradeLoader 로 **적재 로직**(get-or-create·중복 dedup·재수집 멱등)을
못박는다. PostgisTradeLoader 는 같은 normalize 키를 쓰므로 이 로직이 곧 운영 로직이다.
"""
from __future__ import annotations

import datetime as dt
from pathlib import Path

import pytest

from app.ingest import normalize
from app.ingest.geocode import (
    KakaoGeocoder,
    NullGeocoder,
    build_query,
    enrich_geom,
)
from app.ingest.loader import InMemoryTradeLoader
from app.ingest.molit import parse_response
from app.ingest.ratelimit import RateLimiter
from app.ingest.runner import run_molit_trade_ingest

FIXTURES = Path(__file__).parent / "fixtures"
NOW = dt.datetime(2026, 7, 25, 3, 0, tzinfo=dt.timezone.utc)


@pytest.fixture(scope="module")
def sample_xml() -> str:
    return (FIXTURES / "molit_apt_trade_sample.xml").read_text(encoding="utf-8")


@pytest.fixture()
def trades(sample_xml):
    return parse_response(sample_xml, now=NOW)


def _silent_clock_limiter() -> RateLimiter:
    t = [0.0]
    return RateLimiter(0.0, clock=lambda: t[0], sleeper=lambda s: None)


# ---------------------------------------------------------------------------
# 파싱 — 픽스처가 기대대로 읽히는가
# ---------------------------------------------------------------------------

def test_픽스처는_6건으로_파싱된다(trades):
    assert len(trades) == 6
    assert trades[0].complex_name == "○○아파트"
    assert trades[0].price_krw == 1_420_000_000       # 142,000만 → 원
    assert trades[4].is_cancelled is True             # 해제거래
    assert trades[5].region_code == "41135"           # 영문필드 sggCd


# ---------------------------------------------------------------------------
# 정규화 키 — 3계층 분리·중복 판정의 뼈대
# ---------------------------------------------------------------------------

def test_같은단지_다른층은_같은_단지타입_다른_거래(trades):
    a, b = trades[0], trades[1]  # ○○ 84.97 14층 / ○○ 84.97 3층
    assert normalize.complex_key(a) == normalize.complex_key(b)
    assert normalize.unit_type_key(a) == normalize.unit_type_key(b)
    assert normalize.trade_dedup_key(a) != normalize.trade_dedup_key(b)


def test_같은단지_다른면적은_다른_타입(trades):
    a, c = trades[0], trades[2]  # 84.97 vs 59.98
    assert normalize.complex_key(a) == normalize.complex_key(c)
    assert normalize.unit_type_key(a) != normalize.unit_type_key(c)


def test_정확한_중복은_같은_dedup키(trades):
    assert normalize.trade_dedup_key(trades[0]) == normalize.trade_dedup_key(trades[3])


# ---------------------------------------------------------------------------
# 적재 — get-or-create + dedup
# ---------------------------------------------------------------------------

def test_적재_카운트(trades):
    loader = InMemoryTradeLoader()
    res = loader.load(trades)
    assert res.complexes_created == 3       # ○○, △△, □□
    assert res.unit_types_created == 4      # ○○84.97, ○○59.98, △△74.90, □□74.52
    assert res.trades_inserted == 5         # 6건 중 1건은 정확한 중복
    assert res.trades_skipped_dup == 1


def test_재수집은_멱등하다(trades):
    """증분 수집이 최근 2개월을 다시 받아도 중복이 쌓이면 안 된다."""
    loader = InMemoryTradeLoader()
    loader.load(trades)
    second = loader.load(trades)            # 같은 배치 재적재
    assert second.trades_inserted == 0
    assert second.trades_skipped_dup == 6
    assert second.complexes_created == 0
    assert second.unit_types_created == 0
    # 누적 총계
    assert loader.totals.trades_inserted == 5
    assert len(loader.trades) == 5          # 저장된 고유 거래 수


def test_해제거래도_적재되지만_플래그가_산다(trades):
    loader = InMemoryTradeLoader()
    loader.load(trades)
    cancelled = [row for row in loader.trades.values() if row["is_cancelled"]]
    assert len(cancelled) == 1              # △△ 해제거래도 버리지 않는다


def test_region_resolver로_법정동코드를_채운다(trades):
    resolver = lambda sgg5, dong: "1168010600" if (sgg5, dong) == ("11680", "대치동") else None
    loader = InMemoryTradeLoader(region_resolver=resolver)
    loader.load(trades)
    daechi = loader.complexes[normalize.complex_key(trades[0])]
    yeoksam = loader.complexes[normalize.complex_key(trades[4])]
    assert daechi.region_code == "1168010600"
    assert yeoksam.region_code is None      # 미매핑은 NULL(추정하지 않음)


def test_resolver_없으면_region_code는_None(trades):
    loader = InMemoryTradeLoader()
    loader.load(trades)
    assert all(c.region_code is None for c in loader.complexes.values())


# ---------------------------------------------------------------------------
# runner 통합 — fetch→parse→load, ingest_log
# ---------------------------------------------------------------------------

def test_러너가_로더로_적재하고_로그를_남긴다(sample_xml):
    loader = InMemoryTradeLoader()
    logged = []
    run = run_molit_trade_ingest(
        service_key="KEY", region_codes5=["11680"], months=["202606"],
        fetch=lambda params: sample_xml, now=NOW,
        rate_limiter=_silent_clock_limiter(),
        row_sink=loader.load, log_sink=logged.append)

    assert run.status == "ok"
    assert run.rows_ok == 6                  # 파싱된 건수
    assert loader.totals.trades_inserted == 5
    assert logged and logged[0].status == "ok"


# ---------------------------------------------------------------------------
# 지오코딩 — 좌표 확보 (카카오 키워드검색)
# ---------------------------------------------------------------------------

def test_지오코딩_질의는_법정동_단지명(trades):
    q = build_query(normalize.complex_key(trades[0]))
    assert q == "대치동 ○○아파트"


def test_enrich_geom_은_찾은것만_반영하고_못찾으면_센다():
    # 첫 단지는 좌표 있음, 둘째는 없음(None)
    coords = {"대치동 ○○아파트": (127.056, 37.494)}

    class FakeGeo:
        def geocode(self, query):
            return coords.get(query)

    updates: list[tuple[int, float, float]] = []
    res = enrich_geom(
        [(1, "대치동 ○○아파트"), (2, "역삼동 △△아파트")],
        FakeGeo(),
        lambda cid, lon, lat: updates.append((cid, lon, lat)))

    assert res.resolved == 1 and res.unresolved == 1
    assert updates == [(1, 127.056, 37.494)]


def test_null_geocoder는_항상_None():
    assert NullGeocoder().geocode("아무거나") is None


def test_kakao_는_x경도_y위도_순서로_돌려준다():
    """x=경도(lon), y=위도(lat). 뒤집으면 지도에서 바다에 찍힌다."""
    def fake_get(url, headers, params):
        assert headers["Authorization"].startswith("KakaoAK ")
        return {"documents": [{"x": "127.0561", "y": "37.4941", "place_name": "○○아파트"}]}

    geo = KakaoGeocoder("KEY", http_get=fake_get, rate_limiter=_silent_clock_limiter())
    assert geo.geocode("대치동 ○○아파트") == (127.0561, 37.4941)


def test_kakao_결과없으면_None():
    geo = KakaoGeocoder("KEY", http_get=lambda u, h, p: {"documents": []},
                        rate_limiter=_silent_clock_limiter())
    assert geo.geocode("없는단지") is None
    assert geo.geocode("   ") is None       # 빈 질의는 호출도 안 함


# ---------------------------------------------------------------------------
# 실행 배선(run_molit) — DB 없이 검증 가능한 부분
# ---------------------------------------------------------------------------

def test_http_fetch_는_params로_GET하고_text를_돌려준다():
    from app.ingest.run_molit import make_http_fetch

    class FakeResp:
        text = "<response/>"
        def raise_for_status(self): pass

    class FakeClient:
        def __init__(self): self.calls = []
        def get(self, url, params, timeout):
            self.calls.append((url, params)); return FakeResp()

    client = FakeClient()
    fetch = make_http_fetch("https://x/api", client=client)
    body = fetch({"LAWD_CD": "11680", "DEAL_YMD": "202606"})
    assert body == "<response/>"
    assert client.calls[0][0] == "https://x/api"
    assert client.calls[0][1]["LAWD_CD"] == "11680"


def test_http_fetch_는_전송오류를_올린다():
    from app.ingest.run_molit import make_http_fetch

    class FakeResp:
        text = ""
        def raise_for_status(self): raise RuntimeError("503")

    class FakeClient:
        def get(self, url, params, timeout): return FakeResp()

    with pytest.raises(RuntimeError):
        make_http_fetch("https://x", client=FakeClient())({"a": "b"})


def test_시군구코드_정규화는_유효한것만_남긴다():
    from app.ingest.run_molit import region_codes_from
    assert region_codes_from(["11680", " 41135 ", "1168", "abcde", ""]) == ["11680", "41135"]


def test_run_daily_는_키없으면_실패로_기록하고_DB를_안친다():
    """키 미발급 상태(현재): 가짜 성공 없이 failed. log_sink 주입으로 DB 없이 검증."""
    import datetime as _dt

    from app.ingest.run_molit import run_daily

    logged = []
    run = run_daily(
        service_key="", region_codes5=["11680"], engine=object(),
        today=_dt.date(2026, 7, 25), log_sink=logged.append)

    assert run.status == "failed"
    assert "MOLIT_API_KEY" in run.message
    assert "적재:" in run.message            # 적재 요약도 덧붙는다(0 신규)
    assert logged and logged[0].status == "failed"
