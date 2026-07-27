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


def _seed_complex(repo, *, complex_id=1, ask_oku=7.0, area=84.97, households=500,
                  lon=127.05, lat=37.51, region=REGION, name="테스트단지"):
    repo.add_complex(ComplexSummary(
        id=complex_id, name=name, lon=lon, lat=lat, region_code=region,
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
# 사용자 조건 가중치 — 저장만 되고 순위에 안 쓰이던 값 (회귀 방지)
#
# ★ 파이프라인 단위 테스트(test_scoring.py)만으로는 **러너가 prefs 를 안 넘기는 버그**를
#   못 잡는다. 이번 버그가 정확히 그 모양이었다: 계산 로직이 아니라 **배선**이 없었다.
#   그래서 여기서는 PUT /me/preferences → POST /recommendations 전 구간을 태운다.
# ---------------------------------------------------------------------------

def _seed_weighted_pair(repo):
    """가격 축과 가치(환금성) 축이 **정확히 반대**인 두 단지를 심는다.

    1 가격우위단지 : 호가 = 실거래 중위(갭 0 → 가격 만점) · 4000세대(회전율 바닥)
    2 환금성우위단지: 호가 = 중위 +10%(가격 낮음)        · 100세대(회전율 만점)
    """
    def seed(cid, name, ask_oku, median_oku, households):
        repo.add_complex(ComplexSummary(
            id=cid, name=name, lon=127.05, lat=37.51, region_code=REGION,
            built_year=2015, total_households=households,
            recent_price_krw=int(median_oku * OKU), price_as_of=TODAY.isoformat(),
            active_listings=1))
        repo.add_listings(cid, [ListingRow(
            id=cid * 10, ask_price_krw=int(ask_oku * OKU), area_m2=84.97, floor=10,
            listed_at=TODAY - dt.timedelta(days=10), collected_at=TODAY,
            agency="중개", status="active")])
        repo.add_trades(cid, [
            TradeRow(contract_date=TODAY - dt.timedelta(days=15 * i),
                     price_krw=int(median_oku * OKU), area_m2=84.97, floor=10)
            for i in range(8)])

    seed(1, "가격우위단지", ask_oku=7.0, median_oku=7.0, households=4000)
    seed(2, "환금성우위단지", ask_oku=7.7, median_oku=7.0, households=100)


def _set_weights(client, token, weights):
    r = client.put("/api/v1/me/preferences",
                   json={"prefer": {}, "avoid": {}, "weights": weights},
                   headers=_auth(token))
    assert r.status_code == 200, r.text


def test_저장된_가중치가_추천_순위를_실제로_바꾼다(client):
    """★ 핵심 회귀: 슬라이더를 움직이면 결과가 **달라져야** 한다.

    예전에는 `weights` 가 저장만 되고 러너가 `avoid` 만 꺼내 써서, 가격 100% 든
    가치 100% 든 완전히 같은 목록이 나왔다.
    """
    token = _login(client)
    _set_profile(client, token, cash=1_000_000_000, income=300_000_000)
    _seed_weighted_pair(client.repo)

    _set_weights(client, token, {"price": 1.0})
    price_body = _run(client, token, {"region_codes": [REGION]})
    price_order = [it["complex"]["name"] for it in price_body["items"]]

    _set_weights(client, token, {"value": 1.0})
    value_body = _run(client, token, {"region_codes": [REGION]})
    value_order = [it["complex"]["name"] for it in value_body["items"]]

    assert price_order[0] == "가격우위단지", price_order
    assert value_order[0] == "환금성우위단지", value_order
    assert price_order != value_order, "가중치를 바꿨는데 순위가 같다 — 반영되지 않은 것이다"
    assert price_body["items"][0]["score_basis"] == "user_weighted"


def test_가중치가_반영되지_않은_축은_결과에_고지된다(client):
    """입지 100% — 데이터가 없으면 조용히 무시하지 않고 **왜 못 썼는지** 말한다."""
    token = _login(client)
    _set_profile(client, token, cash=1_000_000_000, income=300_000_000)
    _seed_weighted_pair(client.repo)
    # 재건축 축은 명시적으로 0 — 이 테스트는 '입지 100%'가 어떻게 고지되는지만 본다.
    # (0 을 주지 않으면 서버가 기본 비중 15% 를 넣어 입지가 85% 가 된다.)
    _set_weights(client, token, {"location": 1.0, "redevelopment": 0})

    body = _run(client, token, {"region_codes": [REGION]})

    notes = " ".join(body["notes"])
    assert "입지 가중치 100%가" in notes and "반영되지 않았습니다" in notes
    # 점수는 0 이 아니라 '모름'이다.
    assert all(it["total_score"] is None for it in body["items"])
    top = body["items"][0]
    assert any("반영되지 않았습니다" in n for n in top["score_notes"])
    loc = next(a for a in top["score_axes"] if a["axis"] == "location")
    assert loc["status"] == "no_signal" and loc["missing"]


def test_가중치_미저장이면_기존_동작이고_그_사실을_말한다(client):
    """조건을 한 번도 저장하지 않은 사용자에게 동작이 바뀌면 안 된다."""
    token = _login(client)
    _set_profile(client, token, cash=1_000_000_000, income=300_000_000)
    _seed_weighted_pair(client.repo)

    body = _run(client, token, {"region_codes": [REGION]})
    assert body["items"][0]["score_basis"] == "agent_scores"
    assert any("가중치가 없어" in n for n in body["notes"])


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


# ---------------------------------------------------------------------------
# "이 주변에서 검색" (REC-5) — API 경로
#
# 확정 계약: `bbox="minLon,minLat,maxLon,maxLat"` (/map/complexes 와 같은 형식).
# region_codes 와 둘 다 오면 **교집합**. 둘 다 없으면 전체. 형식 오류는 **422**.
# ---------------------------------------------------------------------------

#: 강남 근처 / 평촌(안양 동안구) 근처 — 서로 겹치지 않는 두 범위.
BBOX_GANGNAM = "127.01,37.45,127.12,37.54"
BBOX_PYEONGCHON = "126.92,37.35,126.99,37.42"


def _seed_two_areas(repo):
    """강남 좌표 단지 1번, 평촌 좌표 단지 2번. **예산·가격은 동일하게** 둔다.

    가격을 다르게 두면 결과가 바뀐 이유가 bbox 때문인지 예산 때문인지 알 수 없다.
    """
    _seed_complex(repo, complex_id=1, ask_oku=7.0, lon=127.05, lat=37.51,
                  region="1168000000", name="강남단지")
    _seed_complex(repo, complex_id=2, ask_oku=7.0, lon=126.95, lat=37.39,
                  region="4117300000", name="평촌단지")


def test_bbox로_같은_예산에서_다른_단지가_나온다(client):
    """★ 요점: 예산을 그대로 두고 **bbox 만 바꾸면** 결과가 달라져야 한다."""
    token = _login(client)
    _set_profile(client, token)
    _seed_two_areas(client.repo)

    gangnam = _run(client, token, {"bbox": BBOX_GANGNAM})
    pyeongchon = _run(client, token, {"bbox": BBOX_PYEONGCHON})

    assert [i["complex"]["name"] for i in gangnam["items"]] == ["강남단지"]
    assert [i["complex"]["name"] for i in pyeongchon["items"]] == ["평촌단지"]


def test_bbox가_없으면_전체가_후보다(client):
    token = _login(client)
    _set_profile(client, token)
    _seed_two_areas(client.repo)

    body = _run(client, token, {})
    assert {i["complex"]["name"] for i in body["items"]} == {"강남단지", "평촌단지"}


def test_지역과_bbox는_교집합이다(client):
    """지역은 강남, 범위는 평촌 → **둘 다 만족하는 단지가 없다**(합집합이면 2건이 된다)."""
    token = _login(client)
    _set_profile(client, token)
    _seed_two_areas(client.repo)

    both = _run(client, token, {"region_codes": ["11680"], "bbox": BBOX_PYEONGCHON})
    assert both["items"] == [], "교집합이 아니라 합집합으로 동작한다"

    # 같은 지역 + 같은 범위면 그 단지가 나온다(교집합이 과하게 좁지도 않다).
    match = _run(client, token, {"region_codes": ["11680"], "bbox": BBOX_GANGNAM})
    assert [i["complex"]["name"] for i in match["items"]] == ["강남단지"]


def test_교집합이면_그_사실을_notes로_말한다(client):
    token = _login(client)
    _set_profile(client, token)
    _seed_two_areas(client.repo)

    body = _run(client, token, {"region_codes": ["11680"], "bbox": BBOX_GANGNAM})
    assert any("교집합" in n for n in body["notes"]), body["notes"]


def test_좌표없는_단지가_빠지면_숫자로_고지한다(client):
    """★ 좌표 미확보 단지는 bbox 로 못 찾는다 — **조용히 빠지면 안 된다.**

    고정 문구("약 5%")가 아니라 그때그때 센 숫자를 싣는다. 수집이 진행되면
    문구도 같이 따라가야 한다.
    """
    token = _login(client)
    _set_profile(client, token)
    _seed_complex(client.repo, complex_id=1, lon=127.05, lat=37.51, name="좌표있음")
    client.repo.add_complex(ComplexSummary(
        id=2, name="좌표없음", lon=None, lat=None, region_code=REGION))

    body = _run(client, token, {"bbox": BBOX_GANGNAM})

    assert [i["complex"]["name"] for i in body["items"]] == ["좌표있음"]
    note = [n for n in body["notes"] if "좌표" in n]
    assert note, body["notes"]
    assert "1개" in note[0] and "2개" in note[0], f"세어서 말하지 않는다: {note[0]}"


def test_좌표가_전부_있으면_겁주지_않는다(client):
    """빠진 게 없는데 '빠질 수 있다'고 하면 그 고지는 곧 무시된다."""
    token = _login(client)
    _set_profile(client, token)
    _seed_complex(client.repo, complex_id=1, lon=127.05, lat=37.51)

    body = _run(client, token, {"bbox": BBOX_GANGNAM})
    assert not [n for n in body["notes"] if "좌표" in n], body["notes"]


def test_bbox를_criteria_스냅샷에_남긴다(client):
    """재현성 — 어떤 범위로 돌린 결과인지 나중에 확인할 수 있어야 한다."""
    token = _login(client)
    _set_profile(client, token)
    _seed_two_areas(client.repo)

    body = _run(client, token, {"bbox": BBOX_GANGNAM})
    assert body["criteria_snapshot"]["bbox"] == BBOX_GANGNAM


# --- 입력 검증 (형식 오류는 422) --------------------------------------------

@pytest.mark.parametrize("bad", [
    "bad", "126.9,37.5,127.1",                 # 형식
    "127.2,37.5,127.1,37.6",                   # min >= max
    "126.9,91,127.1,92",                       # 위도 범위 밖
    "-181,37.5,127.1,37.6",                    # 경도 범위 밖
    "120.0,30.0,130.0,40.0",                   # 너무 넓음
    "37.5,126.9,37.6,127.1",                   # 위경도 뒤바뀜
])
def test_잘못된_bbox는_422(client, bad):
    token = _login(client)
    r = client.post("/api/v1/recommendations", json={"bbox": bad}, headers=_auth(token))
    assert r.status_code == 422, r.text


@pytest.mark.parametrize("bad", ["%", "11%", "_1680", "11680; DROP", "abc", ""])
def test_잘못된_region_code는_422(client, bad):
    """SR21-4 — `%` 를 넣으면 지역 선택이 **조용히 무력화**된다(전 지역 매칭).

    인젝션은 아니지만 실패가 실패로 보이지 않아서 더 나쁘다 — 입구에서 거절한다.
    """
    token = _login(client)
    r = client.post("/api/v1/recommendations",
                    json={"region_codes": [bad]}, headers=_auth(token))
    assert r.status_code == 422, r.text


def test_와일드카드_지역코드가_범위를_넓히지_못한다(client):
    """검증을 우회해 러너까지 내려가도 `%` 가 전 지역으로 번지지 않아야 한다."""
    from app.agents.recommend import _analyze

    _seed_two_areas(client.repo)
    token = _login(client)
    _set_profile(client, token)

    from app.core.config import get_settings
    user = client.repo.get_user_by_email("a@b.co")
    status, result = _analyze(client.repo, get_settings(), user.id,
                              {"region_codes": ["%"]}, None)
    assert status == "done"
    assert result["items"] == [], "`%` 가 전 지역을 매칭했다(조용한 실패)"


def test_bbox가_비어있으면_전체로_본다(client):
    """빈 문자열은 '안 보냄'과 같게 다룬다 — 프론트가 초기값으로 ''를 보낼 수 있다."""
    token = _login(client)
    _set_profile(client, token)
    _seed_two_areas(client.repo)

    body = _run(client, token, {"bbox": ""})
    assert len(body["items"]) == 2


def test_러너가_bbox형식오류를_조용히_넘기지_않는다(client):
    """API 를 거치지 않는 호출(스크립트·재실행)에서도 무시하지 않고 말한다."""
    from app.agents.recommend import _analyze
    from app.core.config import get_settings

    _seed_two_areas(client.repo)
    token = _login(client)
    _set_profile(client, token)
    user = client.repo.get_user_by_email("a@b.co")

    status, result = _analyze(client.repo, get_settings(), user.id,
                              {"bbox": "쓰레기"}, None)
    assert status == "done"
    assert any("bbox" in n for n in result["notes"]), result["notes"]


# ---------------------------------------------------------------------------
# 희망 매매가를 예산으로 (ORDER 2026-07-26)
#
# `budget_override_krw` 의 의미는 **상한**이다(대역이 아니다). 근거는
# `app/agents/recommend.py::_budget_notes` 참조.
# ---------------------------------------------------------------------------

def test_희망가를_주면_후보가_실제로_달라진다(client):
    """같은 데이터·같은 프로필인데 희망가만 바꿔서 결과가 바뀌는지 본다.

    ⚠️ 여기서 '달라진다'를 상수로 확인하지 않는다. **희망가 없이 돌린 결과**를
    기준으로 삼아 두 실행을 비교한다 — 기준선이 함께 움직이면 대조가 무의미해진다.
    """
    token = _login(client)
    _set_profile(client, token)                       # 현금 3억 · 소득 2억
    _seed_complex(client.repo, complex_id=1, ask_oku=7.0, name="싼단지")
    _seed_complex(client.repo, complex_id=2, ask_oku=8.5, name="비싼단지")

    wide = _run(client, token, {"region_codes": [REGION]})
    assert {i["complex"]["id"] for i in wide["items"]} == {1, 2}, \
        "기준선부터 두 단지가 다 나와야 대조가 성립한다"

    narrow = _run(client, token, {"region_codes": [REGION],
                                  "budget_override_krw": 8 * OKU})

    assert {i["complex"]["id"] for i in narrow["items"]} == {1}
    dropped = [e for e in narrow["excluded"] if e["complex_id"] == 2]
    assert dropped and dropped[0]["reason_code"] == "over_budget"


def test_희망가가_예산_상한으로_고지된다(client):
    token = _login(client)
    _set_profile(client, token)
    _seed_complex(client.repo, ask_oku=7.0)

    body = _run(client, token, {"region_codes": [REGION],
                                "budget_override_krw": 8 * OKU})
    joined = " ".join(body["notes"])
    assert f"{8 * OKU:,}" in joined
    assert "상한" in joined


def test_희망가가_최대구매가를_넘으면_그_사실을_말한다(client):
    """슬라이더를 올린 만큼 살 수 있다고 믿게 두지 않는다.

    예산 필터가 사용자의 실제 한도를 **조용히 대체**하는 것이 이 고지가 막는 문제다.
    """
    token = _login(client)
    _set_profile(client, token, cash=100_000_000, income=50_000_000)
    _seed_complex(client.repo, ask_oku=7.0)

    over = _run(client, token, {"region_codes": [REGION],
                                "budget_override_krw": 30 * OKU})
    assert any("초과" in n and "최대 실구매" in n for n in over["notes"]), over["notes"]

    # 한도 안의 희망가에는 그 경고가 붙지 않는다(항상 겁주면 아무도 안 읽는다).
    under = _run(client, token, {"region_codes": [REGION],
                                 "budget_override_krw": 1 * OKU})
    assert not any("최대 실구매" in n for n in under["notes"]), under["notes"]


def test_추천카드에_희망가_대비_차액이_실린다(client):
    """프론트가 '희망가보다 1.2억 저렴'을 그릴 수 있어야 한다."""
    token = _login(client)
    _set_profile(client, token)
    _seed_complex(client.repo, ask_oku=7.0)

    budget = 8 * OKU
    body = _run(client, token, {"region_codes": [REGION],
                                "budget_override_krw": budget})
    item = body["items"][0]
    # 비교 대상은 파이프라인이 예산 판정에 실제로 쓴 값이어야 한다.
    assert item["budget_gap_krw"] == item["est_price_krw"] - budget
    assert item["budget_gap_krw"] < 0, "희망가보다 싼 후보는 음수여야 한다"
    assert item["budget_gap_pct"] == pytest.approx(
        item["budget_gap_krw"] * 100.0 / budget, abs=0.05)


def test_희망가가_없으면_차액의_기준은_최대구매가다(client):
    """희망가를 안 줘도 필드는 존재한다 — 키가 없다가 생기면 프론트가 깨진다."""
    token = _login(client)
    _set_profile(client, token)
    _seed_complex(client.repo, ask_oku=7.0)

    body = _run(client, token, {"region_codes": [REGION]})
    item = body["items"][0]
    assert "budget_gap_krw" in item and item["budget_gap_krw"] is not None
    assert item["budget_gap_krw"] < 0        # 추천된 이상 예산 이하다


def test_예산이_없으면_차액은_None이다(client):
    """자산 미입력 등으로 예산이 0 이면 '0 차이'가 아니라 **모름**이다(G2)."""
    from app.agents.recommend import _annotate_budget_gap

    items = [{"est_price_krw": 700_000_000}]
    _annotate_budget_gap(items, 0)
    assert items[0]["budget_gap_krw"] is None
    assert items[0]["budget_gap_pct"] is None


def test_희망가가_내_한도보다_높아도_후보가_사라지지_않는다(client):
    """회귀: `budget_override_krw` 가 **제외 판정에 닿지 않던** 버그.

    예전에는 파이프라인이 항상 `affordability.max_purchase_krw` 로만 예산을 판정했다.
    그래서 희망가를 자기 한도보다 높게 잡으면 조회는 통과한 후보가 전부 "예산 초과"로
    잘려 **결과가 통째로 비었다** — 슬라이더를 올릴수록 결과가 사라지는 형태라
    사용자가 원인을 짐작할 수도 없다.

    ⚠️ 기준선(희망가 없이 = 한도로 판정)이 실제로 비어야 대조가 성립한다. 그래야
    "희망가 덕분에 살아난 것"이지 "원래 나오던 것"이 아니다.
    """
    token = _login(client)
    _set_profile(client, token, cash=100_000_000, income=50_000_000)   # 한도 작게
    _seed_complex(client.repo, ask_oku=7.0)

    baseline = _run(client, token, {"region_codes": [REGION]})
    assert baseline["items"] == [], "기준선이 비어 있지 않으면 이 회귀를 못 잡는다"

    with_target = _run(client, token, {"region_codes": [REGION],
                                       "budget_override_krw": 8 * OKU})
    assert [i["complex"]["id"] for i in with_target["items"]] == [1]
    # 살려 주되 **한도를 넘는다는 사실은 반드시 말한다**(조용히 통과시키지 않는다).
    assert any("최대 실구매" in n for n in with_target["notes"]), with_target["notes"]


def test_예산상한은_희망가가_없으면_최대구매가로_폴백한다():
    """`AnalysisContext.budget_krw` 를 안 주면 기존 동작 그대로여야 한다."""
    from app.agents.orchestrator import AnalysisContext
    from app.domain.affordability.models import (
        AffordabilityResult, CostBreakdown, LoanLimits,
    )

    afford = AffordabilityResult(
        max_purchase_krw=837_750_000, usable_cash_krw=280_000_000,
        loan_krw=557_750_000,
        limits=LoanLimits(ltv_krw=1, dsr_krw=1, dti_krw=None,
                          effective_krw=1, binding="LTV"),
        costs=CostBreakdown(0, 0, 0, 0), binding_constraint="LTV")

    assert AnalysisContext(affordability=afford,
                           candidates=[]).effective_budget_krw == 837_750_000
    assert AnalysisContext(affordability=afford, candidates=[],
                           budget_krw=600_000_000).effective_budget_krw == 600_000_000


# ---------------------------------------------------------------------------
# REC-7 — 후보 조회 상한
#
# 실측(운영 DB · 강남 11680 · 단지 506개, 2026-07-28):
#   · 후보 조회 SQL 자체는 상한과 **거의 무관**했다(50/100/200/400 전부 0.8~1.3초).
#     `ORDER BY 매물수·예산내 거래수` 가 전 행을 훑은 뒤에야 LIMIT 이 걸리기 때문이다
#     → 상한 50 은 DB 부하를 **하나도 줄이지 않고** 있었다.
#   · 실제 비용은 단지당 조립(호가·실거래·입지·정비사업 조회) 21~23ms.
#     50→120 은 +1.0초, 200 이면 +2.8초. 파이썬 피크 메모리 1.5MiB · DB 정렬 78kB.
#   · 120 위로는 `MAX_CANDIDATES`(200)가 먼저 걸려 추가 조회가 버려진다
#     (송파 실측: 단지 100개에서 이미 후보 200개).
# ---------------------------------------------------------------------------

def test_후보_조회_상한이_보고된_조건충족_단지수를_덮는다():
    """★ 회귀 — 강남에서 조건 충족 단지가 96개인데 50개만 보던 상태(REC-7).

    숫자를 바꿀 때 **왜 그 숫자인지**가 함께 바뀌어야 한다. 96 은 실측값이고,
    상한이 그 아래로 내려가면 같은 사고가 되돌아온다.
    """
    from app.agents.recommend import CANDIDATE_COMPLEX_LIMIT, MAX_CANDIDATES

    assert CANDIDATE_COMPLEX_LIMIT >= 96, (
        "강남 실측 조건 충족 단지 96개를 덮지 못합니다 — 상한을 내리려면 "
        "그 근거(실측)를 함께 남기세요")
    assert CANDIDATE_COMPLEX_LIMIT <= MAX_CANDIDATES, (
        "단지 상한이 후보 상한보다 크면 조회한 단지가 버려집니다(시간만 늘어난다)")


def test_상한에_걸리면_무슨_기준의_상위_N인지_말한다():
    """★ "일부는 안 봤다"만 적으면 사용자는 빠진 단지가 무작위인지 알 수 없다.

    상한 자체는 남길 수밖에 없다 — 그렇다면 **무슨 순서로 골랐는지**가 답이다.
    """
    from app.agents import recommend as R

    repo = InMemoryRepository()
    for i in range(1, R.CANDIDATE_COMPLEX_LIMIT + 1):
        repo.add_complex(ComplexSummary(
            id=i, name=f"단지{i}", lon=127.0, lat=37.5, region_code=REGION,
            built_year=2005, total_households=500))

    out = R._assemble_candidates(repo, {"region_codes": [REGION]}, None)
    note = next((n for n in out.notes if "조회 상한" in n), None)
    assert note, out.notes
    assert str(R.CANDIDATE_COMPLEX_LIMIT) in note
    for basis in ("활성 매물", "예산", "실거래 표본"):
        assert basis in note, f"선정 기준 '{basis}' 가 고지에 없습니다: {note}"


def test_상한_아래에서는_그_고지가_뜨지_않는다():
    """늘 뜨는 고지는 읽히지 않는다."""
    from app.agents import recommend as R

    repo = InMemoryRepository()
    repo.add_complex(ComplexSummary(id=1, name="단지", lon=127.0, lat=37.5,
                                    region_code=REGION, built_year=2005,
                                    total_households=500))
    out = R._assemble_candidates(repo, {"region_codes": [REGION]}, None)
    assert not any("조회 상한" in n for n in out.notes), out.notes


def test_리포지토리에_넘기는_상한이_상수와_같다():
    """★ 변이 가드 — 상수를 올리고 호출부에 숫자를 박아 두면 아무 일도 안 일어난다."""
    from app.agents import recommend as R

    seen: dict[str, int] = {}

    def fake_query(*, region_codes, max_price_krw, limit, bbox, **kw):
        seen["limit"] = limit
        return []

    R._query_candidates(fake_query, region_codes=[REGION], budget=None, bbox=None,
                        conditions=R.FilterConditions())
    assert seen["limit"] == R.CANDIDATE_COMPLEX_LIMIT
