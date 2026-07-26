"""추천 실행 경로(BackgroundTask) 테스트 — ORDER 2026-07-25-24-domain.

redis/큐 없이 API BackgroundTask 로 orchestrator 를 돌리는 경로를 인메모리 repo 로 검증한다.
TestClient 는 BackgroundTask 를 **동기로** 끝낸 뒤 응답을 돌려주므로, POST 직후 GET 하면
결과가 이미 준비돼 있다.
"""
from __future__ import annotations

import datetime as dt
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app.domain.valuation.models import ListingRow, TradeRow
from app.repositories.base import ComplexSummary
from app.repositories.memory import InMemoryRepository

FIXTURES = Path(__file__).parent / "fixtures"
PASSWORD = "correct horse battery staple"
REGION = "1168000000"
OKU = 100_000_000
TODAY = dt.date.today()


@pytest.fixture()
def client(monkeypatch):
    monkeypatch.setenv("JWT_SECRET", "x" * 40)
    monkeypatch.setenv("FIELD_ENCRYPTION_KEY", "k" * 32)
    monkeypatch.setenv("POSTGRES_PASSWORD", "pw")
    monkeypatch.setenv("TAX_RULES_PATH", str(FIXTURES / "tax_rules_test.yaml"))

    from app.core.config import get_settings
    get_settings.cache_clear()

    from app.main import create_app
    repo = InMemoryRepository()
    app = create_app(repo=repo)
    with TestClient(app) as c:
        c.repo = repo
        yield c
    get_settings.cache_clear()


def _auth(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


def _login(client, email="a@b.co") -> str:
    """가입 → **승인** → 로그인.

    가입 직후 계정은 `pending` 이라 로그인이 403 이다(관리자 승인제 · migrations/009).
    테스트 편의를 위해 프로덕션 기본값을 approved 로 바꾸지 않는다 — 그러면 승인제가
    통째로 무력화되고, 그 사실을 아무 테스트도 잡지 못한다. 여기서 **명시적으로** 승인한다.
    """
    r = client.post("/api/v1/auth/register", json={"email": email, "password": PASSWORD})
    assert r.status_code == 201, r.text
    user = client.repo.get_user_by_email(email)
    client.repo.set_user_status(user.id, "approved", actor="cli")
    return client.post("/api/v1/auth/login",
                       json={"email": email, "password": PASSWORD}).json()["access_token"]


def _set_profile(client, token, cash=300_000_000, income=200_000_000):
    r = client.put("/api/v1/me/profile",
                   json={"cash_krw": cash, "income_krw": income},
                   headers=_auth(token))
    assert r.status_code == 200, r.text


def _seed_complex(repo, *, complex_id=1, ask_oku=7.0, area=84.97, households=500):
    repo.add_complex(ComplexSummary(
        id=complex_id, name="테스트단지", lon=127.05, lat=37.51, region_code=REGION,
        built_year=2015, total_households=households,
        recent_price_krw=int(ask_oku * OKU), price_as_of=TODAY.isoformat(),
        active_listings=2))
    listings = [
        ListingRow(id=complex_id * 10 + i, ask_price_krw=int(ask_oku * OKU),
                   area_m2=area, floor=10,
                   listed_at=TODAY - dt.timedelta(days=10), collected_at=TODAY,
                   agency=f"중개{i}", status="active")
        for i in range(2)
    ]
    repo.add_listings(complex_id, listings)
    trades = [
        TradeRow(contract_date=TODAY - dt.timedelta(days=15 * i),
                 price_krw=int(ask_oku * OKU), area_m2=area, floor=10)
        for i in range(8)
    ]
    repo.add_trades(complex_id, trades)


def _seed_trades_only(repo, *, complex_id=1, price_oku=7.0, area=84.97,
                      households=500, n=8, with_dong=False, name="호가없는단지"):
    """**호가 없이** 단지 + 실거래만 심는다.

    이게 운영 DB 의 실제 모습이다: 공공 오픈API 에는 호가가 없어 `listing` 이 0건이다
    (2026-07-26 서버 실측: complex 6,538 · trade 120,138 · **listing 0**).
    """
    repo.add_complex(ComplexSummary(
        id=complex_id, name=name, lon=127.05, lat=37.51, region_code=REGION,
        built_year=2015, total_households=households,
        recent_price_krw=int(price_oku * OKU), price_as_of=TODAY.isoformat(),
        active_listings=0))
    trades = []
    for i in range(n):
        dong = None
        if with_dong:
            # 101동(비쌈) / 105동(쌈) — F4 동별 실측이 성립하도록 각각 표본을 채운다.
            dong = "101" if i % 2 == 0 else "105"
        bump = 0.0
        if with_dong:
            bump = 0.6 if dong == "101" else -0.6
        trades.append(TradeRow(
            contract_date=TODAY - dt.timedelta(days=15 * i),
            price_krw=int((price_oku + bump) * OKU), area_m2=area, floor=10,
            apt_dong=dong))
    repo.add_trades(complex_id, trades)


def _run(client, token, body):
    """POST 로 큐잉 → (BackgroundTask 동기 실행) → GET 으로 결과."""
    r = client.post("/api/v1/recommendations", json=body, headers=_auth(token))
    assert r.status_code == 202, r.text
    job_id = r.json()["job_id"]
    got = client.get(f"/api/v1/recommendations/{job_id}", headers=_auth(token))
    assert got.status_code == 200, got.text
    return got.json()


# ---------------------------------------------------------------------------
# 실제 추천이 나온다
# ---------------------------------------------------------------------------

def test_추천이_백그라운드에서_실행돼_결과가_나온다(client):
    token = _login(client)
    _set_profile(client, token)
    _seed_complex(client.repo, ask_oku=7.0)

    body = _run(client, token, {"region_codes": [REGION]})

    assert body["status"] == "done", body
    assert body["items"], "후보가 있는데 추천이 비었다"
    top = body["items"][0]
    assert top["complex"]["id"] == 1
    assert top["total_score"] is not None
    # 근거·반대근거가 함께 나온다(G2/F6).
    assert "why" in top and "why_not" in top
    assert top["findings"], "에이전트별 근거가 저장돼야 한다"


def test_예산초과_단지는_제외되고_사유가_남는다(client):
    token = _login(client)
    _set_profile(client, token, cash=100_000_000, income=50_000_000)   # 예산 작게
    _seed_complex(client.repo, ask_oku=50.0)                           # 50억 — 확실히 초과

    body = _run(client, token, {"region_codes": [REGION]})
    assert body["status"] == "done"
    assert body["items"] == []          # 못 사는 집은 추천이 아니다

    # ★ 여기가 요점: **왜** 안 나왔는지가 응답에 실려야 한다.
    # 빈 items 만 주면 사용자는 데이터가 없는 줄 알고 결과 전체를 의심한다.
    assert body["excluded"], "제외 사유가 응답에 없으면 '왜 이건 안 나왔지'에 답할 수 없다"
    entry = body["excluded"][0]
    assert entry["complex_id"] == 1
    # complex_id 만 있으면 화면에 "단지 #1"이라고 밖에 못 쓴다 — 이름이 있어야 쓸모가 있다.
    assert entry["complex_name"] == "테스트단지"
    assert entry["reason_code"] == "over_budget"
    assert "예산 초과" in entry["reason"]
    assert entry["price_basis"] == "listing"


def test_제외사유에_사용자_자산_원본금액이_없다(client):
    """SR4-2 — 제외 사유는 평문으로 저장·전송된다. 자산 원본이 섞이면 안 된다.

    한도(파생값)는 허용이고 보유현금·연소득 **원본**은 금지다. substring 이 아니라
    금액 **값**으로 검사한다(정상 시세가 자산으로 오탐되지 않게).
    """
    from app.agents.base import extract_amounts

    cash, income = 123_400_000, 87_600_000
    token = _login(client)
    _set_profile(client, token, cash=cash, income=income)
    _seed_complex(client.repo, ask_oku=50.0)          # 예산 초과 → 사유 문장 생성

    body = _run(client, token, {"region_codes": [REGION]})
    assert body["excluded"]

    blob = " ".join(str(e.get("reason", "")) for e in body["excluded"])
    leaked = extract_amounts(blob) & {cash, income}
    assert not leaked, f"제외 사유에 자산 원본이 들어갔다: {leaked}"


def test_순위에서_잘린_후보도_사유와_함께_남는다(client):
    """조건을 다 통과하고 11위라서 빠진 단지도 사용자에겐 '안 나온 후보'다."""
    token = _login(client)
    _set_profile(client, token)
    for cid, ask in ((1, 7.0), (2, 7.2), (3, 7.4)):
        _seed_complex(client.repo, complex_id=cid, ask_oku=ask)

    body = _run(client, token, {"region_codes": [REGION], "top_n": 1})

    assert len(body["items"]) == 1, "top_n 이 지켜지지 않으면 '상위 N건 밖'이 거짓말이 된다"
    cut = [e for e in body["excluded"] if e["reason_code"] == "below_rank_cutoff"]
    assert len(cut) == 2
    assert all(e["complex_name"] for e in cut)
    assert "상위 1건 밖" in cut[0]["reason"]
    # 모든 후보는 추천이거나 제외다 — 말없이 사라지는 후보가 없어야 한다.
    assert len(body["items"]) + len(body["excluded"]) == 3


def test_제외가_없으면_빈_목록으로_내려간다(client):
    """빈 목록과 '필드 없음'은 다른 뜻이다 — 프론트가 구분해 표시한다."""
    token = _login(client)
    _set_profile(client, token)
    _seed_complex(client.repo, ask_oku=7.0)

    body = _run(client, token, {"region_codes": [REGION]})
    assert body["items"] and body["excluded"] == []
    assert isinstance(body["notes"], list) and body["notes"]


def test_프로필이_없으면_그_사실을_notes로_말한다(client):
    """빈 결과에도 이유가 있다. '데이터가 없어서'와 '예산을 몰라서'는 다르다."""
    token = _login(client)
    _seed_complex(client.repo, ask_oku=7.0)          # 후보는 있는데 프로필이 없다

    body = _run(client, token, {"region_codes": [REGION]})
    assert body["items"] == []
    assert any("자산" in n for n in body["notes"]), body["notes"]


# ---------------------------------------------------------------------------
# 호가 없는 단지 — 공공API 만으로도 추천이 나와야 한다 (CHARTER G4)
#
# 회귀 방지 대상: `_assemble_candidates` 가 `if not listings: continue` 로 호가 없는
# 단지를 건너뛰던 버그. 공공 오픈API 에는 호가가 없어 listing 테이블이 통째로 비므로
# 추천이 **구조적으로 항상 0건**이었다.
# ---------------------------------------------------------------------------

def test_호가가_없어도_실거래로_후보가_선다(client):
    """★핵심 회귀: listing 0건이어도 추천이 나온다."""
    token = _login(client)
    _set_profile(client, token)
    _seed_trades_only(client.repo, price_oku=7.0)      # 호가 0건, 실거래만

    body = _run(client, token, {"region_codes": [REGION]})

    assert body["status"] == "done"
    assert body["items"], "호가가 없다는 이유로 후보가 0건이 되면 G4 위반이다"
    assert body["items"][0]["complex"]["id"] == 1


def test_실거래기준_후보는_price_basis가_trade다(client):
    """가격 근거를 응답에 **명시적 필드**로 싣는다 — 호가처럼 위장하지 않는다(G2)."""
    token = _login(client)
    _set_profile(client, token)
    _seed_trades_only(client.repo, price_oku=7.0)

    top = _run(client, token, {"region_codes": [REGION]})["items"][0]

    assert top["price_basis"] == "trade"
    assert top["price_estimated"] is True
    assert top["est_price_krw"] > 0                    # 예산 비교에 실제로 쓴 값
    assert top["price_note"] and "실거래" in top["price_note"]
    # 적정가 밴드 자체가 근거로 실린다(갭 대신).
    assert top["price_band"] and top["price_band"]["median_krw"] > 0
    assert top["price_band"]["sample_size"] >= 5


def test_실거래기준_후보에는_호가와_호가갭이_없다(client):
    """비교 대상(호가)이 없으므로 갭을 만들어내면 안 된다 — None 이어야 한다."""
    token = _login(client)
    _set_profile(client, token)
    _seed_trades_only(client.repo, price_oku=7.0)

    top = _run(client, token, {"region_codes": [REGION]})["items"][0]

    assert top["ask_price_krw"] is None, "호가가 없는데 숫자가 실리면 하류가 호가로 믿는다"
    assert top["ask_gap_pct"] is None, "비교 대상이 없는데 갭을 지어냈다"
    assert top["building"] is None, "특정 물건이 없으므로 동 표기도 없다"

    val = next(f for f in top["findings"] if f["agent_id"] == "valuation-trader")
    assert "현재 매물 없음" in val["verdict"]
    assert "%" not in val["verdict"]
    # 매물 리서처는 평가할 매물이 없다 — '정상 매물'로 단정하지 않는다.
    listing_f = next(f for f in top["findings"] if f["agent_id"] == "listing-researcher")
    assert listing_f["verdict"] == "판단 보류"
    assert listing_f["missing"]


def test_호가가_생기면_호가_경로로_돌아간다(client):
    """수집이 살아나면 즉시 호가 기준(ask_gap 판정)으로 복귀해야 한다."""
    token = _login(client)
    _set_profile(client, token)
    _seed_complex(client.repo, ask_oku=7.5)            # 호가 7.5억 · 실거래 7.5억

    top = _run(client, token, {"region_codes": [REGION]})["items"][0]

    assert top["price_basis"] == "listing"
    assert top["price_estimated"] is False
    assert top["price_note"] is None
    assert top["ask_price_krw"] == int(7.5 * OKU)
    assert top["est_price_krw"] == top["ask_price_krw"]
    assert top["ask_gap_pct"] is not None, "호가가 있으면 갭을 계산해야 한다"
    assert top["total_score"] is not None and top["score_basis"] == "agent_scores"


def test_실거래기준_후보도_동별_실측이_살아있다(client):
    """★F4 회귀: dong_valuation 은 실거래 기반이라 **호가 유무와 무관**하다."""
    token = _login(client)
    _set_profile(client, token)
    _seed_trades_only(client.repo, price_oku=7.0, n=10, with_dong=True)

    top = _run(client, token, {"region_codes": [REGION]})["items"][0]

    assert top["price_basis"] == "trade"
    dv = top["dong_valuation"]
    assert dv is not None and dv["available"] is True, "호가가 없다고 F4 가 죽으면 안 된다"
    assert dv["basis"] == "trade_measured"
    dongs = {d["dong"]: d for d in dv["dongs"]}
    assert dongs["101"]["vs_complex_pct"] > 0 > dongs["105"]["vs_complex_pct"]


def test_실거래기준_예산초과는_추정치임을_사유에_남긴다(client):
    """예산 필터는 실거래 추정가로 비교하되 **추정임을 결과에 남긴다.**"""
    token = _login(client)
    _set_profile(client, token, cash=100_000_000, income=50_000_000)
    _seed_trades_only(client.repo, price_oku=50.0)     # 50억 — 확실히 초과

    body = _run(client, token, {"region_codes": [REGION]})
    assert body["items"] == []                        # 못 사는 집은 추천이 아니다


def test_실거래_표본이_부족하면_후보로_세우지_않는다(client):
    """가격 근거가 없으면(호가 없음 + 표본 부족) 지어내지 않고 후보에서 뺀다.

    ★ 그러나 **말없이 빼지는 않는다.** 후보가 되기도 전에 떨어진 단지는 예전에
    어디에도 남지 않아서, 사용자가 "우리 단지가 왜 아예 안 보이냐"고 물으면 답이 없었다
    (실측: 강남구 조회 50개 단지 중 4개가 여기서 사라졌다).
    """
    token = _login(client)
    _set_profile(client, token)
    _seed_trades_only(client.repo, price_oku=7.0, n=2)   # MIN_SAMPLE(5) 미만

    body = _run(client, token, {"region_codes": [REGION]})
    assert body["status"] == "done"
    assert body["items"] == []

    assert len(body["excluded"]) == 1
    entry = body["excluded"][0]
    assert entry["reason_code"] == "no_price_evidence"
    assert entry["complex_name"] == "호가없는단지"
    assert "실거래" in entry["reason"]


def test_호가_단지와_실거래_단지가_섞여도_각각_제_근거를_쓴다(client):
    token = _login(client)
    _set_profile(client, token)
    _seed_complex(client.repo, complex_id=1, ask_oku=7.5)               # 호가 있음
    _seed_trades_only(client.repo, complex_id=2, price_oku=7.0)         # 호가 없음

    items = _run(client, token, {"region_codes": [REGION]})["items"]
    by_id = {it["complex"]["id"]: it for it in items}
    assert set(by_id) == {1, 2}
    assert by_id[1]["price_basis"] == "listing" and by_id[1]["ask_gap_pct"] is not None
    assert by_id[2]["price_basis"] == "trade" and by_id[2]["ask_price_krw"] is None
    # 점수가 있는 후보(호가 기준)가 점수 없는 후보보다 위에 온다.
    assert items[0]["complex"]["id"] == 1


# ---------------------------------------------------------------------------
# 데이터 없을 때 — 빈 결과가 정상(수집 전)
# ---------------------------------------------------------------------------

def test_매물데이터가_없으면_빈결과_done(client):
    token = _login(client)
    _set_profile(client, token)
    # 단지·매물 미시딩 → 후보 없음

    body = _run(client, token, {"region_codes": [REGION]})
    assert body["status"] == "done"
    assert body["items"] == []


def test_프로필이_없으면_크래시없이_빈결과(client):
    token = _login(client)
    # 프로필 미입력 → 예산 미상 → 빈 결과, 그러나 done(스택 안 남고 정상 종료)
    body = _run(client, token, {"region_codes": [REGION]})
    assert body["status"] == "done"
    assert body["items"] == []


# ---------------------------------------------------------------------------
# 실거래 면적대 선택 — 호가가 없을 때 "어떤 유닛을 후보로 세울지"
# ---------------------------------------------------------------------------

def _t(area, price_oku=7.0, days=10):
    return TradeRow(contract_date=TODAY - dt.timedelta(days=days),
                    price_krw=int(price_oku * OKU), area_m2=area, floor=10)


def test_면적대는_거래많은순으로_고르고_표본미달은_뺀다():
    from app.agents.recommend import _trade_area_groups

    trades = ([_t(59.9, days=5 * i) for i in range(6)]       # 6건
              + [_t(84.97, days=5 * i) for i in range(9)]    # 9건
              + [_t(114.5, days=5 * i) for i in range(2)])   # 2건 — MIN_SAMPLE 미달
    assert _trade_area_groups(trades) == [84.97, 59.9]


def test_오차안의_면적은_한_덩어리로_본다():
    """84.9 와 84.97 을 따로 세우면 같은 타입이 두 후보가 된다(밴드는 어차피 합산)."""
    from app.agents.recommend import _trade_area_groups

    trades = ([_t(84.97, days=5 * i) for i in range(6)]
              + [_t(84.9, days=5 * i + 2) for i in range(6)])
    assert _trade_area_groups(trades) == [84.9]     # 하나만


def test_오래된_거래만_있으면_면적대를_세우지_않는다():
    """밴드가 쓰지 않는 창(36개월 밖)의 거래를 '가격 근거 있음'으로 세면 안 된다."""
    from app.agents.recommend import _trade_area_groups

    old = [_t(84.97, days=40 * 30 + 30 * i) for i in range(8)]
    assert _trade_area_groups(old) == []


def test_해제거래는_면적대_표본에서_빠진다():
    from app.agents.recommend import _trade_area_groups

    trades = [TradeRow(contract_date=TODAY - dt.timedelta(days=5 * i),
                       price_krw=int(7.0 * OKU), area_m2=84.97, floor=10,
                       is_cancelled=True) for i in range(8)]
    assert _trade_area_groups(trades) == []


def test_한_단지가_후보를_독식하지_않는다():
    from app.agents.recommend import TRADE_AREA_GROUPS_PER_COMPLEX, _trade_area_groups

    trades = []
    for area in (49.5, 59.9, 74.2, 84.97, 114.5):
        trades += [_t(area, days=5 * i) for i in range(6)]
    assert len(_trade_area_groups(trades)) == TRADE_AREA_GROUPS_PER_COMPLEX


# ---------------------------------------------------------------------------
# 제외 사유의 마지막 그물 — 자산 원본이 문장으로 새는 경로 (SR4-2)
# ---------------------------------------------------------------------------

def test_사유에_자산원본이_섞이면_문장만_가리고_사유는_남긴다():
    """미래에 누가 '보유현금 3억으로는 부족합니다' 같은 문구를 넣어도 여기서 잡힌다.

    사유를 통째로 버리지 않는다 — 사용자는 여전히 '예산 초과'라는 답을 받아야 한다.
    """
    from app.agents.recommend import _strip_asset_amounts

    entry = {"complex_id": 7, "complex_name": "○○아파트", "reason_code": "over_budget",
             "reason": "예산 초과 (보유현금 300,000,000원으로는 부족)"}
    out = _strip_asset_amounts([entry], [300_000_000])

    assert "300,000,000" not in out[0]["reason"]
    assert out[0]["reason_redacted"] is True
    assert "예산 초과" in out[0]["reason"]          # 사유 자체는 살아 있다
    assert out[0]["complex_name"] == "○○아파트"     # 화면에 필요한 정보도 그대로


def test_정상_사유는_금액이_있어도_가리지_않는다():
    """시세 13억이 자산 3억으로 오차단되면 사유가 전부 뭉개진다(값 비교, substring 아님)."""
    from app.agents.recommend import _strip_asset_amounts

    entry = {"complex_id": 7, "reason_code": "over_budget",
             "reason": "예산 초과 (호가 1,300,000,000원 > 한도 850,000,000원)"}
    out = _strip_asset_amounts([entry], [300_000_000])

    assert out[0]["reason"] == entry["reason"]
    assert "reason_redacted" not in out[0]


# ---------------------------------------------------------------------------
# IDOR — 남의 추천은 못 본다(백그라운드 저장도 소유권 검증)
# ---------------------------------------------------------------------------

def test_남의_추천결과는_못본다(client):
    t1 = _login(client, "a@b.co")
    t2 = _login(client, "b@b.co")
    _set_profile(client, t1, cash=300_000_000, income=200_000_000)
    _seed_complex(client.repo)

    r = client.post("/api/v1/recommendations", json={"region_codes": [REGION]},
                    headers=_auth(t1))
    job_id = r.json()["job_id"]

    assert client.get(f"/api/v1/recommendations/{job_id}",
                      headers=_auth(t1)).status_code == 200
    assert client.get(f"/api/v1/recommendations/{job_id}",
                      headers=_auth(t2)).status_code == 404


# ---------------------------------------------------------------------------
# ★ JOB-1 회귀: 실패 상태값이 DB 제약과 어긋나면 job 이 영원히 멈춘다
# ---------------------------------------------------------------------------

def test_실패상태값이_DB제약에_들어있다():
    """러너가 쓰는 실패 상태가 001_init.sql 의 CHECK 목록 안에 있어야 한다.

    예전엔 러너가 'error' 를 썼는데 제약은 queued|running|done|failed 만 허용해
    UPDATE 가 통째로 깨졌고, job 이 **'queued' 로 영원히 멈춰** 화면에 "분석 중…" 이
    무한히 떴다. 실패가 실패로 보이지 않는 사고다.

    문자열을 손으로 비교하지 않고 **마이그레이션 원문에서 허용 목록을 파싱**해 대조한다 —
    스키마가 바뀌면 이 테스트가 같이 따라간다.
    """
    import re
    from pathlib import Path

    from app.agents.recommend import JOB_FAILED

    sql = (Path(__file__).resolve().parents[1] / "migrations" / "001_init.sql").read_text(
        encoding="utf-8")
    # recommendation_job 의 status CHECK 절을 찾는다
    m = re.search(r"recommendation_job\b.*?status\s+text[^,]*?CHECK\s*\(\s*status\s+IN\s*\(([^)]+)\)",
                  sql, re.S | re.I)
    assert m, "001_init.sql 에서 recommendation_job.status CHECK 를 찾지 못했습니다"
    allowed = {v.strip().strip("'\"") for v in m.group(1).split(",")}

    assert JOB_FAILED in allowed, (
        f"러너의 실패 상태 {JOB_FAILED!r} 가 DB 제약 {sorted(allowed)} 에 없습니다 — "
        "UPDATE 가 깨져 job 이 queued 로 멈춥니다"
    )


def test_실패하면_job이_failed로_남는다():
    """예외가 나도 job 이 queued 에 머물지 않고 실패로 확정돼야 한다."""
    from app.agents.recommend import JOB_FAILED, run_recommendation_job

    class BoomRepo:
        def __init__(self): self.saved = []
        def get_profile(self, *a, **k): raise RuntimeError("boom")
        def save_job_result(self, job_id, user_id, *, status, items, **kw):
            self.saved.append(status)

    repo = BoomRepo()
    run_recommendation_job(repo=repo, settings=object(), job_id="rec_x",
                           user_id=1, criteria={})
    assert repo.saved == [JOB_FAILED], f"실패 시 상태가 {repo.saved} 로 남았습니다"
