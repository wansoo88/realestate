"""수집 적재 파이프라인 검증 — 픽스처(실응답 형태 XML)로 parse→normalize→load 전 구간.

DB 없이 InMemoryTradeLoader 로 **적재 로직**(get-or-create·중복 dedup·재수집 멱등)을
못박는다. PostgisTradeLoader 는 같은 normalize 키를 쓰므로 이 로직이 곧 운영 로직이다.
"""
from __future__ import annotations

import datetime as dt
from pathlib import Path

import pytest

from app.core.masking import SecretSafeError
from app.ingest import normalize
from app.ingest.geocode import build_query
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


def _deal_xml(*, cancelled: bool, dong: str | None = None) -> str:
    """같은 거래(◇◇ 도곡동 84.97㎡ 10층 15억 2026-06-10)를 정상/해제 두 버전으로.

    dong 을 주면 <동> 필드를 붙인다(운영 API 의 aptDong). None 이면 필드 없음(결측).
    """
    flag = "O" if cancelled else " "
    extra = "<해제사유발생일>26.06.25</해제사유발생일>" if cancelled else ""
    dong_xml = f"<동>{dong}</동>" if dong is not None else ""
    return f"""<response><header><resultCode>00</resultCode></header><body><items>
      <item><거래금액>150,000</거래금액><년>2026</년><월>6</월><일>10</일>
      <아파트>◇◇아파트</아파트><전용면적>84.97</전용면적><지역코드>11680</지역코드>
      <법정동>도곡동</법정동><층>10</층>{dong_xml}<해제여부>{flag}</해제여부>{extra}</item>
    </items></body></response>"""


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
    assert normalize.trade_natural_key(a) != normalize.trade_natural_key(b)


def test_같은단지_다른면적은_다른_타입(trades):
    a, c = trades[0], trades[2]  # 84.97 vs 59.98
    assert normalize.complex_key(a) == normalize.complex_key(c)
    assert normalize.unit_type_key(a) != normalize.unit_type_key(c)


def test_정확한_중복은_같은_자연키(trades):
    assert normalize.trade_natural_key(trades[0]) == normalize.trade_natural_key(trades[3])


def test_자연키에는_해제여부가_들어가지_않는다():
    """INGEST-2: 같은 거래는 정상이든 해제든 같은 자연키여야 upsert 로 원본을 갱신한다."""
    normal = parse_response(_deal_xml(cancelled=False), now=NOW)[0]
    cancelled = parse_response(_deal_xml(cancelled=True), now=NOW)[0]
    assert normal.is_cancelled is False and cancelled.is_cancelled is True
    assert normalize.trade_natural_key(normal) == normalize.trade_natural_key(cancelled)


# ---------------------------------------------------------------------------
# 적재 — get-or-create + dedup
# ---------------------------------------------------------------------------

def test_적재_카운트(trades):
    loader = InMemoryTradeLoader()
    res = loader.load(trades)
    assert res.complexes_created == 3       # ○○, △△, □□
    assert res.unit_types_created == 4      # ○○84.97, ○○59.98, △△74.90, □□74.52
    assert res.trades_inserted == 5         # 6건 중 1건은 같은 자연키(upsert)
    assert res.trades_updated == 1


def test_재수집은_멱등하다(trades):
    """증분 수집이 최근 2개월을 다시 받아도 중복 행이 쌓이면 안 된다(upsert)."""
    loader = InMemoryTradeLoader()
    loader.load(trades)
    second = loader.load(trades)            # 같은 배치 재적재
    assert second.trades_inserted == 0
    assert second.trades_updated == 6
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


def test_정상거래가_해제되면_시세에서_사라진다():
    """★INGEST-2 회귀(CHARTER §0 최대 리스크): 허위신고 후 해제로 시세를 띄우는 조작 차단.

    정상 15억이 유입돼 시세에 잡힌 뒤, 같은 거래가 해제되어 재유입되면 **기존 행이
    is_cancelled=True 로 갱신**되어 시세(NOT is_cancelled)에서 사라져야 한다. 중복 행이
    생겨 원본 15억이 남으면 안 된다.
    """
    loader = InMemoryTradeLoader()
    loader.load(parse_response(_deal_xml(cancelled=False), now=NOW))

    # 정상일 때는 시세(active)에 15억이 잡힌다
    assert any(r["price_krw"] == 1_500_000_000 for r in loader.active_trades())

    # 같은 거래가 해제되어 재유입 → 새 행이 아니라 기존 행 갱신
    res = loader.load(parse_response(_deal_xml(cancelled=True), now=NOW))
    assert res.trades_inserted == 0
    assert res.trades_updated == 1
    assert len(loader.trades) == 1          # 중복 행이 생기지 않는다

    # 해제됐으므로 시세에서 사라진다 — 원본 15억이 통계에 남으면 안 된다
    assert loader.active_trades() == []
    assert all(r["is_cancelled"] for r in loader.trades.values())


def test_동은_결측_재유입에도_보존된다():
    """★APTDONG-1 회귀(CR-015): 동(棟)이 있는 거래가 동 결측으로 재유입돼도 기존 동을 지우면 안 된다.

    운영 API 는 aptDong 을 77~93%만 준다. 같은 거래가 어떤 배치엔 동과 함께, 다른 배치엔
    동 없이 올 수 있다(해제 재유입 포함). 재적재가 동을 None 으로 덮으면 F4 실측 표본이
    조용히 사라진다. PostGIS 로더의 COALESCE(:apt_dong, apt_dong) 와 InMemory 가 **같은
    규칙**이어야 한다.
    """
    loader = InMemoryTradeLoader()
    # 1) 동 '103' 과 함께 유입
    loader.load(parse_response(_deal_xml(cancelled=False, dong="103"), now=NOW))
    (row,) = loader.trades.values()
    assert row["apt_dong"] == "103"

    # 2) 같은 자연키가 동 결측으로 재유입(해제 포함) → 동은 보존돼야 한다
    loader.load(parse_response(_deal_xml(cancelled=True, dong=None), now=NOW))
    (row,) = loader.trades.values()
    assert row["apt_dong"] == "103"         # None 으로 덮이지 않는다
    assert row["is_cancelled"] is True      # 해제 플래그는 최신값으로 갱신(INGEST-2 유지)

    # 3) 나중에 다른 동 값이 오면 그때는 최신값으로 갱신(COALESCE: 새 값이 있으면 이긴다)
    loader.load(parse_response(_deal_xml(cancelled=False, dong="105"), now=NOW))
    (row,) = loader.trades.values()
    assert row["apt_dong"] == "105"


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
# 지오코딩 — 좌표 확보. 검증·충돌 차단 전부 tests/test_geocode.py 로 옮겼다
# (CR-020 GEO-1). 여기서는 정규화 키가 질의로 이어지는 접점만 지킨다.
# ---------------------------------------------------------------------------

def test_지오코딩_질의는_법정동_단지명(trades):
    q = build_query(normalize.complex_key(trades[0]))
    assert q == "대치동 ○○아파트"


# ---------------------------------------------------------------------------
# 실행 배선(run_molit) — DB 없이 검증 가능한 부분
# ---------------------------------------------------------------------------

# ⚠️ 대역이 `get()` 이 아니라 `stream()` 인 이유(SR25-1): MOLIT 응답을 상한 없이
#    `.text` 로 읽던 것을 스트리밍 + 상한(`app.core.http.request_capped`)으로 바꿨다.
#    대역이 옛 모양을 유지하면 테스트만 옛 경로를 검증하게 된다.
class _FakeStreamResp:
    def __init__(self, body: bytes = b"<response/>", *, boom: bool = False) -> None:
        self._body = body
        self._boom = boom
        self.headers = {"content-length": str(len(body))}
        self.charset_encoding = "utf-8"

    def raise_for_status(self):
        if self._boom:
            raise RuntimeError("503")

    def iter_bytes(self, chunk_size=None):
        yield self._body


class _FakeStreamClient:
    def __init__(self, resp: _FakeStreamResp | None = None) -> None:
        self.calls: list[tuple] = []
        self._resp = resp or _FakeStreamResp()

    def stream(self, method, url, params=None, timeout=None):
        self.calls.append((url, params, method))

        class _Ctx:
            def __init__(self, resp): self._resp = resp
            def __enter__(self): return self._resp
            def __exit__(self, *exc): return False

        return _Ctx(self._resp)


def test_http_fetch_는_params로_GET하고_text를_돌려준다():
    from app.ingest.run_molit import make_http_fetch

    client = _FakeStreamClient()
    fetch = make_http_fetch("https://x/api", client=client)
    body = fetch({"LAWD_CD": "11680", "DEAL_YMD": "202606"})
    assert body == "<response/>"
    assert client.calls[0][0] == "https://x/api"
    assert client.calls[0][1]["LAWD_CD"] == "11680"
    assert client.calls[0][2] == "GET"


def test_http_fetch_는_전송오류를_올린다():
    from app.ingest.run_molit import make_http_fetch

    client = _FakeStreamClient(_FakeStreamResp(b"", boom=True))
    with pytest.raises(RuntimeError):
        make_http_fetch("https://x", client=client)({"a": "b"})


def test_http_fetch_는_응답이_상한을_넘으면_읽다가_멈춘다(monkeypatch):
    """★ SR25-1 회귀 — 상한이 **읽는 도중** 걸리는지 본다(존재 검사가 아니다).

    `.text` 로 되돌리면 여기서 깨진다: 그 경로는 본문을 이미 전부 읽은 뒤라
    `ResponseTooLarge` 자체가 나오지 않는다. 청크를 100개로 쪼개 주고
    **소비가 중간에 멈추는지**까지 확인한다.
    """
    from app.core import http as core_http
    from app.ingest.run_molit import make_http_fetch

    consumed: list[int] = []

    class _Big(_FakeStreamResp):
        def __init__(self):
            super().__init__(b"")
            self.headers = {}                      # content-length 선언 없음

        def iter_bytes(self, chunk_size=None):
            for i in range(100):
                consumed.append(i)
                yield b"x" * 1024

    monkeypatch.setattr(core_http, "MAX_RESPONSE_BYTES", 4096)
    fetch = make_http_fetch("https://x", client=_FakeStreamClient(_Big()))
    # 이 계층은 **모든** 예외를 마스킹해서 올린다(SR17-1) — 상한 위반도 예외가 아니다.
    with pytest.raises(SecretSafeError) as caught:
        fetch({"a": "b"})
    assert "상한" in str(caught.value)
    assert len(consumed) < 100, "상한을 넘겼는데도 끝까지 읽었다"


def test_http_fetch_는_Content_Length_선언만으로도_거절한다(monkeypatch):
    """한 바이트도 읽지 않고 막는 경로(선언값 검사)."""
    from app.core import http as core_http
    from app.ingest.run_molit import make_http_fetch

    consumed: list[int] = []

    class _Declared(_FakeStreamResp):
        def __init__(self):
            super().__init__(b"")
            self.headers = {"content-length": "99999999"}

        def iter_bytes(self, chunk_size=None):
            consumed.append(1)
            yield b"x"

    monkeypatch.setattr(core_http, "MAX_RESPONSE_BYTES", 4096)
    fetch = make_http_fetch("https://x", client=_FakeStreamClient(_Declared()))
    with pytest.raises(SecretSafeError) as caught:
        fetch({"a": "b"})
    assert "상한" in str(caught.value)
    assert consumed == [], "선언값이 상한을 넘는데도 본문을 읽었다"


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
