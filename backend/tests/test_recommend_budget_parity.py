"""★ CR39-2 — **추천도 후보 면적으로 예산 상한을 세우는가** (하드 제외라 더 위험하다).

무엇을 지키는 테스트인가
------------------------
`api-spec §5` 의 명제는 이것이다:

    후보의 판정 단위는 단지가 아니라 **단지 × 면적대**다. 그래서 예산 상한도
    후보마다 그 후보의 면적으로 세운다 —
        제외 = est_price_krw > max_purchase(area = unit_type.area_m2)
    같은 면적으로 `POST /affordability` 를 부르면 **같은 숫자**가 나온다.

최대 구매가능 금액은 면적의 함수다(취득세 농어촌특별세가 전용 85㎡ 경계). 지도는
CR37-1 에서 이미 항목별 판정으로 고쳤는데 **추천은 `PropertyFacts()` 기본값 84.0 으로
만든 한 숫자로 후보를 하드 제외하고 있었다**(CR39-2).

⚠️ 지도와 다른 점 — **여기서 갈리면 후보가 사라진다**
-----------------------------------------------------
지도의 오판은 배지 하나가 틀리는 것이고 단지는 화면에 남는다. 추천의 오판은
**후보를 목록에서 지운다.** 그래서 이 파일은 판정의 방향만 보지 않고 세 가지를 함께
못박는다:
  ① 새로 제외되는 후보에 **제외 사유가 남는가**(`reason_code=over_budget` + 문장)
  ② `items + excluded` 가 후보 총수와 **같은가**(어디에도 없는 후보 = 조용한 유실)
  ③ 상한을 세울 수 없는 후보(면적 미상)를 제외하지도, 조용히 통과시키지도 않는가

왜 운영 세율(`config/tax_rules.yaml`)을 쓰는가
---------------------------------------------
⛔ **테스트 픽스처(`tests/fixtures/tax_rules_test.yaml`)로는 이 결함을 재현할 수 없다.**
   `t_first_small`(85㎡ 이하)과 `t_first_other` 의 합계 세율이 **둘 다 1.1%** 라 면적이
   한도를 바꾸지 않는다 — 픽스처로 짜면 고치기 전에도 통과하는 *지키는 척만 하는 검사*가
   된다. `test_map_budget_parity.py` 가 운영 세율을 쓰는 이유가 그것이고, 여기도 같다.
   (그 사실 자체를 `test_이_테스트가_밟는_경계가_실재한다` 가 먼저 단언한다.)
"""
from __future__ import annotations

import datetime as dt
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app.domain.valuation.models import ListingRow
from app.repositories.base import ComplexSummary
from app.repositories.memory import InMemoryRepository

REPO_ROOT = Path(__file__).resolve().parents[2]
PROD_RULES = REPO_ROOT / "config" / "tax_rules.yaml"
API_SPEC = REPO_ROOT / "docs" / "02-design" / "api-spec.md"

PASSWORD = "correct horse battery staple"
REGION = "1168010100"
TODAY = dt.date.today()

#: 리뷰어 재현 조건 그대로 — 이 자산에서 85㎡ 경계가 금액으로 드러난다.
CASH_KRW = 500_000_000
INCOME_KRW = 100_000_000

SMALL_AREA = 84.00
BOUNDARY_M2 = 85.00        # '이하' 쪽
JUST_OVER_M2 = 85.01       # 여기서부터 농특세 0.2%
LARGE_AREA = 114.50

#: 한 추천 안에 섞이는 면적. **85㎡ 경계를 가로지른다**(한쪽에만 몰면 1구간이라 공짜 통과).
MIXED_AREAS = (59.9, SMALL_AREA, BOUNDARY_M2, JUST_OVER_M2, LARGE_AREA, 120.0)


@pytest.fixture()
def client(monkeypatch):
    """**운영 세율**로 뜬 앱. (다른 추천 테스트는 가상 픽스처를 쓴다 — 위 머리말 참조)"""
    monkeypatch.setenv("JWT_SECRET", "x" * 40)
    monkeypatch.setenv("FIELD_ENCRYPTION_KEY", "k" * 32)
    monkeypatch.setenv("POSTGRES_PASSWORD", "pw")
    monkeypatch.setenv("TAX_RULES_PATH", str(PROD_RULES))

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


def _ready(client, email="a@b.co") -> str:
    """가입 → 승인 → 로그인 → 자산 입력. **희망 매매가는 저장하지 않는다**(재현 조건)."""
    r = client.post("/api/v1/auth/register", json={"email": email, "password": PASSWORD})
    assert r.status_code == 201, r.text
    user = client.repo.get_user_by_email(email)
    client.repo.set_user_status(user.id, "approved", actor="cli")
    token = client.post("/api/v1/auth/login",
                        json={"email": email, "password": PASSWORD}
                        ).json()["access_token"]
    r = client.put("/api/v1/me/profile",
                   json={"cash_krw": CASH_KRW, "income_krw": INCOME_KRW},
                   headers=_auth(token))
    assert r.status_code == 200, r.text
    return token


def _limit(client, token, *, area_m2=None) -> int:
    """화면이 쓰는 그 숫자 — `/affordability` 의 `max_purchase_krw`.

    `area_m2` 를 빼고 부르면 서버 기본값 84.0 이 쓰인다(`AffordabilityIn.area_m2`).
    """
    body: dict = {"purpose": "live"}
    if area_m2 is not None:
        body["area_m2"] = area_m2
    r = client.post("/api/v1/affordability", json=body, headers=_auth(token))
    assert r.status_code == 200, r.text
    return r.json()["max_purchase_krw"]


def _seed(repo, specs):
    """`(id, 면적, 호가)` 목록을 후보로 깐다. 면적 `0.0` 은 **면적 미상**(수집 결손)이다.

    호가를 넣는 이유: `price_basis=listing` 이면 `est_price_krw == ask_price_krw` 라
    적정가 밴드(표본·시점 보정)가 끼어들지 않는다 — 이 파일이 보려는 것은 **상한**이다.
    """
    for i, (cid, area, price) in enumerate(specs):
        repo.add_complex(ComplexSummary(
            id=cid, name=f"단지{cid}", lon=127.05 + i * 0.001, lat=37.51,
            region_code=REGION, built_year=2015, total_households=800,
            recent_price_krw=price, price_as_of=TODAY.isoformat(),
            price_area_m2=(area or None), active_listings=1))
        repo.add_listings(cid, [ListingRow(
            id=cid * 10, ask_price_krw=price, area_m2=area, floor=10,
            listed_at=TODAY - dt.timedelta(days=5), collected_at=TODAY,
            agency="중개", status="active")])


def _run(client, token, body=None) -> dict:
    """POST 로 큐잉 → (BackgroundTask 동기 실행) → GET 으로 결과."""
    payload = {"region_codes": [REGION], "top_n": 50}
    payload.update(body or {})
    r = client.post("/api/v1/recommendations", json=payload, headers=_auth(token))
    assert r.status_code == 202, r.text
    got = client.get(f"/api/v1/recommendations/{r.json()['job_id']}",
                     headers=_auth(token))
    assert got.status_code == 200, got.text
    return got.json()


def _mixed(client, token):
    """면적 6종 × 가격 3구간 + 면적 미상 1건을 깔고 추천을 돈다.

    가격은 두 상한을 기준으로 잡는다:
        below   : 둘 다 아래   → 면적과 무관하게 예산 안
        between : **두 상한 사이** → 면적이 답을 결정한다 (여기가 이 파일의 전부다)
        above   : 둘 다 위     → 면적과 무관하게 예산 초과

    돌려주는 것: `(body, specs, 금액들)`
    """
    small = _limit(client, token, area_m2=SMALL_AREA)
    large = _limit(client, token, area_m2=LARGE_AREA)
    below = large - 5_000_000
    between = (small + large) // 2
    above = small + 5_000_000

    specs: list[tuple[int, float, int, str]] = []
    cid = 0
    for area in MIXED_AREAS:
        for label, price in (("below", below), ("between", between), ("above", above)):
            cid += 1
            specs.append((cid, area, price, label))
    specs.append((cid + 1, 0.0, between, "between"))          # 면적 미상
    _seed(client.repo, [(c, a, p) for c, a, p, _ in specs])

    body = _run(client, token)
    return body, specs, {"small": small, "large": large, "below": below,
                         "between": between, "above": above}


def _state(body: dict) -> dict[int, tuple[str, str, str]]:
    """`{complex_id: (items|excluded, reason_code, reason)}`."""
    out: dict[int, tuple[str, str, str]] = {}
    for it in body["items"]:
        out[it["complex"]["id"]] = ("item", "-", "-")
    for e in body["excluded"]:
        out.setdefault(e["complex_id"],
                       ("excluded", e["reason_code"], e["reason"] or ""))
    return out


# ---------------------------------------------------------------------------
# 0. 이 파일이 빈 검사가 아님을 먼저 증명한다
# ---------------------------------------------------------------------------

def test_이_테스트가_밟는_경계가_실재한다(client):
    """⚠️ **먼저 이것부터.** 두 면적의 한도가 실제로 다르지 않으면 아래 테스트는 전부
    '아무 일도 없어서 통과'가 된다(픽스처 세율로 짜면 정확히 그렇게 된다).

    세제가 바뀌어 이 차이가 사라지면 **이 줄이 먼저 깨진다** — 그때 이 파일이
    무의미해졌다는 사실이 조용히 묻히지 않는다.
    """
    token = _ready(client)
    small = _limit(client, token, area_m2=SMALL_AREA)
    large = _limit(client, token, area_m2=LARGE_AREA)
    assert small > large, (
        f"85㎡ 이하({SMALL_AREA})와 초과({LARGE_AREA})의 한도가 같습니다({small}) — "
        "이 파일의 모든 테스트가 빈 검사가 됩니다. 세율 설정을 확인하세요.")
    assert 0 < (small - large) < large * 0.01, (small, large)

    # 경계의 **위치**까지 못박는다 — 0.01㎡ 로 뒤집히는 자리가 실재한다.
    assert _limit(client, token, area_m2=BOUNDARY_M2) == small
    assert _limit(client, token, area_m2=JUST_OVER_M2) == large
    # 기준 면적(요약 문구용)은 '85㎡ 이하' 쪽이다 = 옛 한 숫자 판정이 관대했던 이유.
    assert _limit(client, token) == small


# ---------------------------------------------------------------------------
# 1. ★ CR39-2 본체 — 후보마다 그 후보의 면적으로 판정한다
# ---------------------------------------------------------------------------

def test_후보마다_그_면적의_한도로_예산을_판정한다(client):
    """★ 한 추천 안에 59.9㎡ 와 120㎡ 가 함께 있다. `between` 가격이 갈림길이다.

    변이: `orchestrator` 의 `ctx.budget_cap_krw(cand.area_m2)` 를
    `ctx.effective_budget_krw`(84㎡ 한 숫자)로 되돌리면 85㎡ 초과 `between` 후보가
    전부 통과해 여기서 깨진다.
    """
    token = _ready(client)
    body, specs, money = _mixed(client, token)
    state = _state(body)

    checked_between = 0
    for cid, area, _price, label in specs:
        if not area:
            continue                       # 면적 미상은 아래 전용 테스트에서 본다
        where, code, _reason = state[cid]
        expect_over = money[label] > (money["small"] if area <= BOUNDARY_M2
                                      else money["large"])
        if label == "between":
            checked_between += 1
            # `between` 은 85㎡ 이하면 통과, 초과면 제외 — **면적이 답을 정한다**
            assert expect_over == (area > BOUNDARY_M2), (area, label)
        if expect_over:
            assert where == "excluded" and code == "over_budget", (cid, area, label, where, code)
        else:
            assert where == "item", (cid, area, label, where, code)

    # 빈 검사 방지: `between` 가격을 **모든 면적에서** 밟았는가.
    assert checked_between == len(MIXED_AREAS), checked_between


def test_한_숫자로_판정하면_이_목록에서_반드시_갈린다(client):
    """이 파일이 잡는 결함이 **이 배치에서 실재하는지**를 숫자로 못박는다.

    옛 코드(`PropertyFacts()` 기본 84.0 으로 만든 한 숫자)가 이 목록을 판정하면
    85㎡ 초과 `between` 후보 3건을 **통과시킨다**. 서버는 그것들을 제외한다.
    이 대조가 0 이 되면(세율 변경 등) 위 테스트는 아무것도 지키지 않는다.
    """
    token = _ready(client)
    body, specs, money = _mixed(client, token)
    state = _state(body)

    conflicts = []
    for cid, area, price, _label in specs:
        if not area:
            continue
        one_number_over = price > money["small"]      # 옛 판정(84㎡ 한 숫자)
        server_over = state[cid][1] == "over_budget"
        if one_number_over != server_over:
            conflicts.append((cid, area, price))

    assert [c[1] for c in conflicts] == [JUST_OVER_M2, LARGE_AREA, 120.0], conflicts
    # 방향까지 못박는다 — 옛 판정은 **관대**했다(못 사는 후보를 통과시켰다).
    for cid, _area, price in conflicts:
        assert price <= money["small"] and price > money["large"]
        assert state[cid][1] == "over_budget"


def test_제외_사유는_판정에_실제로_쓴_한도를_말한다(client):
    """사유 문장에 적히는 한도가 **그 후보의 면적으로 세운 값**이어야 한다.

    다른 숫자를 적으면 사용자가 되짚을 수 없다("1,026,560,000원 초과라는데 내
    `/affordability` 는 1,024,580,000원이라고 한다"). 금액은 `/affordability` 를
    같은 면적으로 불러 대조한다 — 화면이 쓰는 바로 그 숫자다.
    """
    token = _ready(client)
    body, specs, money = _mixed(client, token)
    state = _state(body)

    seen = {"small": 0, "large": 0}
    for cid, area, _price, _label in specs:
        if not area or state[cid][0] != "excluded":
            continue
        cap = _limit(client, token, area_m2=area)
        assert f"{cap:,}원" in state[cid][2], (area, cap, state[cid][2])
        seen["small" if cap == money["small"] else "large"] += 1

    # 두 구간의 사유 문장을 **둘 다** 봤는가(한쪽만 보면 한 숫자여도 통과한다).
    assert seen["small"] > 0 and seen["large"] > 0, seen


def test_후보는_items_아니면_excluded_에_정확히_한_번_남는다(client):
    """제외가 늘어나는 수정이므로 **조용한 유실**을 여기서 막는다.

    사용자 질문은 "왜 우리 단지가 없나"다. 어디에도 없는 후보는 그 질문에 답이 없다.
    """
    token = _ready(client)
    body, specs, _money = _mixed(client, token)

    item_ids = [it["complex"]["id"] for it in body["items"]]
    excluded_ids = [e["complex_id"] for e in body["excluded"]]
    assert len(item_ids) == len(set(item_ids))
    assert not (set(item_ids) & set(excluded_ids)), "같은 후보가 양쪽에 있다"
    assert set(item_ids) | set(excluded_ids) == {c for c, *_ in specs}
    # 사유 없는 제외가 없다 — 코드와 문장 **둘 다** 남는다.
    for e in body["excluded"]:
        assert e["reason_code"] and (e["reason"] or "").strip(), e


def test_면적_미상_후보는_제외도_통과도_아니라_고지된다(client):
    """상한을 세울 수 없는 후보를 **조용히 처리하지 않는다.**

    · 제외하면 "판정 못 함"이 "못 산다"로 바뀐다(값싼 물건이 근거 없이 사라진다).
    · 84 를 가정하면 *다른 면적의 한도*로 판정하는 것이다(CR37-1 의 본체).
    그래서 판정하지 않고 남기되 **건수를 말한다**.

    변이: 그 고지를 지우면(또는 면적 미상을 84 로 가정하면) 여기서 깨진다.
    """
    token = _ready(client)
    body, specs, _money = _mixed(client, token)
    unknown_id = [c for c, area, *_ in specs if not area][0]
    state = _state(body)

    assert state[unknown_id][0] == "item", "판정 못 한 후보를 제외해 버렸다"
    joined = " ".join(body["notes"])
    assert "전용면적이 확인되지 않아 예산 상한을 세우지 못했" in joined, body["notes"]
    assert "'예산 안'이라는 뜻이 아닙니다" in joined, body["notes"]
    # 카드의 차액도 **모름**이어야 한다 — 0 이나 84㎡ 기준 값을 채우지 않는다.
    card = [it for it in body["items"] if it["complex"]["id"] == unknown_id][0]
    assert card["budget_gap_krw"] is None and card["budget_gap_pct"] is None, card


def test_차액도_후보_면적의_한도를_기준으로_한다(client):
    """카드의 `budget_gap_krw` 가 판정에 쓴 상한과 **같은 숫자**에서 나와야 한다.

    한 숫자로 그리면 차액이 음수(=예산 안)인데 실제로는 초과였던 후보가 생긴다.
    """
    token = _ready(client)
    body, specs, _money = _mixed(client, token)
    by_id = {it["complex"]["id"]: it for it in body["items"]}

    checked_large = 0
    for cid, area, _price, _label in specs:
        item = by_id.get(cid)
        if item is None or not area:
            continue
        cap = _limit(client, token, area_m2=area)
        assert item["budget_gap_krw"] == item["est_price_krw"] - cap, (cid, area)
        assert item["budget_gap_krw"] < 0, "추천된 이상 예산 이하다"
        if area > BOUNDARY_M2:
            checked_large += 1
    # 85㎡ 초과 후보를 실제로 밟았는가(밟지 않으면 한 숫자여도 통과한다).
    assert checked_large > 0, checked_large


# ---------------------------------------------------------------------------
# 2. 희망 매매가는 면적과 무관하다
# ---------------------------------------------------------------------------

def test_희망가는_면적과_무관해서_면적을_몰라도_판정한다(client):
    """①(희망 매매가)은 사용자가 정한 **금액 하나**다 — 면적이 뭐든 상한이 같다.

    그래서 이 기준에서는 면적 미상 후보도 판정한다(제외될 수도 있다). 면적 때문에
    판정을 접는 것은 ②(자산 기준 한도)에만 해당한다는 사실을 여기서 못박는다.
    """
    token = _ready(client)
    target = 900_000_000
    _seed(client.repo, [(1, SMALL_AREA, target - 10_000_000),
                        (2, LARGE_AREA, target + 10_000_000),
                        (3, 0.0, target + 10_000_000)])

    body = _run(client, token, {"budget_override_krw": target})
    state = _state(body)
    assert state[1][0] == "item"
    assert state[2][1] == "over_budget" and f"{target:,}원" in state[2][2]
    # 면적 미상도 **판정한다** — 희망가는 면적의 함수가 아니다.
    assert state[3][1] == "over_budget", state[3]
    # 그러므로 "면적을 몰라 상한을 못 세웠다"는 고지는 나오지 않는다.
    assert not any("예산 상한을 세우지 못했" in n for n in body["notes"]), body["notes"]


def test_요약_고지는_어느_면적_기준인지_밝힌다(client):
    """결과 전체에 붙는 한 문장은 후보마다 다른 한도를 담을 수 없다. 그래서 기준
    면적으로 만들고 **그 사실을 적는다** — 문장이 판정보다 강한 주장을 하지 않게.

    변이: 문구에서 '전용 84㎡ 기준'을 지우면 여기서 깨진다.
    """
    token = _ready(client)
    _seed(client.repo, [(1, SMALL_AREA, 500_000_000)])

    body = _run(client, token, {"budget_override_krw": 30 * 100_000_000})
    joined = " ".join(body["notes"])
    assert "최대 실구매 가능 금액(전용 84㎡ 기준)" in joined, body["notes"]
    # 그 숫자가 **정말 그 면적의 한도**인가 — `/affordability` 기본 호출과 대조한다.
    assert f"{_limit(client, token):,}원" in joined, body["notes"]

    # 그리고 그 기준 면적은 `/affordability` 기본값과 **같은 값이어야 한다**
    # (api-spec §5). 갈라지면 "내 정보" 화면의 한도와 이 고지의 한도가 다른 숫자가 된다.
    from app.api.schemas import AffordabilityIn
    from app.domain.affordability.budget import SUMMARY_AREA_M2

    assert SUMMARY_AREA_M2 == AffordabilityIn.model_fields["area_m2"].default


# ---------------------------------------------------------------------------
# 3. 면적별 계산을 **묶어서** 한다 (비용)
# ---------------------------------------------------------------------------

def test_세율_구간이_같은_면적은_한_번만_계산한다(client, monkeypatch):
    """후보는 최대 200건이다. 면적마다 이분탐색을 새로 돌리면(실측 0.75ms) 조회 SQL
    보다 오래 걸린다 — 지도와 **같은 캐시**를 쓴다(`acquisition_area_class`).

    운영 세율이면 2회(85㎡ 이하 / 초과)면 된다. 요약 문구용 기준 면적(84.0)도 같은
    조회기를 쓰므로 계산이 한 번 더 돌지 않는다.
    변이: `profile_affordability` 의 캐시를 지우면 호출이 후보 수만큼 늘어 깨진다.
    """
    from app.domain.affordability import budget as budget_mod

    calls: list[float] = []
    real = budget_mod.compute_affordability

    def counted(borrower, rules, **kw):
        prop = kw.get("prop")
        calls.append(prop.area_m2 if prop else -1.0)
        return real(borrower, rules, **kw)

    token = _ready(client)
    # 40 ~ 118㎡ — 85㎡ 경계를 가로지른다(한쪽에만 몰면 1구간이라 공짜 통과).
    _seed(client.repo, [(i + 1, 40.0 + i * 2, 500_000_000) for i in range(40)])
    monkeypatch.setattr(budget_mod, "compute_affordability", counted)

    body = _run(client, token)
    assert len(body["items"]) == 40, len(body["items"])
    assert len(calls) == 2, (
        f"면적 40종에 대해 한도를 {len(calls)}번 계산했습니다 — 세율 구간이 같은 면적은 "
        f"한 번이면 됩니다(운영 세율 기준 2구간). areas={calls}")
    assert min(calls) <= 85 < max(calls), calls


# ---------------------------------------------------------------------------
# 4. 계약 문서 ↔ 실제 동작
# ---------------------------------------------------------------------------

def test_api_spec_이_추천의_면적별_판정을_사실로_적는다():
    """문서가 정본이라면 문서가 맞아야 한다(CR37-6 과 같은 이유).

    CR39-2 가 지적한 것 중 하나는 **문서가 과거형으로 적혀 추천도 고쳐진 것처럼
    읽혔다**는 점이다. 여기서 그 문장을 못박는다 — 지우면 깨진다.
    """
    spec = API_SPEC.read_text(encoding="utf-8")
    assert "est_price_krw > max_purchase(area = unit_type.area_m2)" in spec, (
        "api-spec 에 추천의 면적별 예산 판정 계약이 없습니다")
    assert "backend/tests/test_recommend_budget_parity.py" in spec, (
        "그 계약을 지키는 테스트가 문서에 적혀 있지 않습니다")
