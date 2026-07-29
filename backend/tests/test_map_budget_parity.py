"""★ CR37-1 / CR38-1 — **지도가 항목마다 그 면적의 상한으로 판정하는가** (면적이 섞인 지도).

무엇을 지키는 테스트인가
------------------------
`api-spec §4` 와 `routes.py` 주석의 명제는 이것이다:

    같은 `complex_id`·같은 `area_m2` 로 `/affordability` 를 부르면
    지도가 그 항목에 쓴 상한과 **같은 `max_purchase_krw`** 가 나온다.

최대 구매가능 금액은 **면적의 함수**다 — 취득세의 농어촌특별세가 전용 85㎡ 를 경계로
붙는다(운영 세율 실측 1,026,560,000 vs 1,024,580,000). 그래서 지도 전체를 한 숫자로
판정하면 85㎡ 를 가로지르는 화면에서 반드시 갈린다.

⚠️ 이 파일의 1차 판본은 **그 전제를 스스로 빼고 돌았다** (CR38-1, 2026-07-29)
-----------------------------------------------------------------------
1차 판본은 지도에 **모든 단지를 같은 면적(114.5㎡)으로** 깔고 "어긋남 0" 을 보고했다.
단일 면적 지도에서는 한 숫자와 항목별 숫자가 우연히 같아진다 — 고치기 전 코드로도
통과했을 배치다. 정작 면적을 섞는 테스트는 화면 판정과의 대조를 **부르지 않았다**
(부르면 죽었다). *"지도는 34㎡ 와 120㎡ 를 한 화면에 담는다"* 가 이 수정의 존재
이유인데, 검사는 그 전제를 밟지 않았다.

그래서 이 판본은 **모든 판정 테스트가 면적이 섞인 bbox 를 밟는다.** 화면이 지도를 여는
세 가지 상태(단지 미선택 · 85㎡ 이하 선택 · 85㎡ 초과 선택)를 전부 지나간다.

왜 운영 세율(`config/tax_rules.yaml`)을 쓰는가
---------------------------------------------
⛔ **테스트 픽스처(`tests/fixtures/tax_rules_test.yaml`)로는 이 결함을 재현할 수 없다.**
   그 파일의 `t_first_small`(85㎡ 이하)과 `t_first_other`(그 외)는 **합계 세율이 둘 다
   1.1%** 라 면적이 한도를 바꾸지 않는다. 픽스처로 짠 테스트는 고치기 전에도 통과한다 —
   *지키는 척만 하는 검사*가 되는 정확한 형태다. 그래서 여기서만 운영 세율을 쓴다.
   (그 사실 자체를 `test_이_테스트가_밟는_경계가_실재한다` 가 먼저 단언한다 —
    세율이 바뀌어 경계가 사라지면 이 파일은 **빈 검사가 되기 전에 깨진다**.)
"""
from __future__ import annotations

import datetime as dt
import json
import re
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app.repositories.base import ComplexSummary
from app.repositories.memory import InMemoryRepository

REPO_ROOT = Path(__file__).resolve().parents[2]
PROD_RULES = REPO_ROOT / "config" / "tax_rules.yaml"
API_SPEC = REPO_ROOT / "docs" / "02-design" / "api-spec.md"

PASSWORD = "correct horse battery staple"
REGION = "1168010100"
TODAY = dt.date.today()
BBOX = "126.9,37.4,127.1,37.6"

#: 리뷰어 재현에 쓰인 조건 그대로 — 이 자산에서 85㎡ 경계가 금액으로 드러난다.
CASH_KRW = 500_000_000
INCOME_KRW = 100_000_000

#: 전용 85㎡ 를 사이에 둔 두 면적. `SMALL` 은 농특세 비과세, `LARGE` 는 0.2% 가산.
SMALL_AREA = 84.00
LARGE_AREA = 114.50

#: 취득세 면적 구간의 경계(㎡). **85.0 은 '이하' 쪽**이고 85.01 부터 가산이 붙는다.
#: 두 값을 같은 가격으로 지도에 함께 깔면 **0.01㎡ 차이로 판정이 뒤집히는** 자리가 된다.
BOUNDARY_M2 = 85.00
JUST_OVER_M2 = 85.01

#: 실제 수도권 지도 한 화면의 모습 — 34㎡ 원룸형부터 120㎡ 대형까지 섞여 있다.
#: `None` 은 체결 면적을 모르는 단지(운영에서 실제로 생긴다).
MIXED_AREAS = (34.0, 59.9, SMALL_AREA, BOUNDARY_M2, JUST_OVER_M2, LARGE_AREA, 120.0)


@pytest.fixture()
def client(monkeypatch):
    """**운영 세율**로 뜬 앱. (다른 파일은 가상 픽스처를 쓴다 — 위 머리말 참조)"""
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


def _seed(repo, specs):
    """`(id, 가격, 체결면적)` 목록을 지도에 올린다. 면적은 `None` 도 받는다(면적 미상).

    운영 PostGIS 는 가격·기준일·면적을 **한 거래 행**에서 가져오므로, 면적이 없으면
    금액도 없다. 픽스처도 그 규약을 지킨다(면적만 비우는 케이스는 따로 만든다).
    """
    for i, (cid, price, area) in enumerate(specs):
        repo.add_complex(ComplexSummary(
            id=cid, name=f"단지{cid}", lon=127.05 + i * 0.001, lat=37.51,
            region_code=REGION, built_year=2015, total_households=800,
            recent_price_krw=price, price_as_of=TODAY.isoformat(),
            price_area_m2=area, active_listings=0))


def _map(client, token, **params):
    r = client.get("/api/v1/map/complexes",
                   params={"bbox": BBOX, "zoom": 15, "purpose": "live", **params},
                   headers=_auth(token))
    assert r.status_code == 200, r.text
    return r.json()


def _limit(client, token, *, area_m2=None, complex_id=None) -> int:
    """화면이 쓰는 그 숫자 — `/affordability` 의 `max_purchase_krw`.

    `area_m2` 를 빼고 부르면 서버 기본값 84.0 이 쓰인다(`AffordabilityIn.area_m2`) —
    **단지를 고르기 전 기본 진입 경로**가 정확히 그 모양이다.
    """
    body: dict = {"purpose": "live"}
    if area_m2 is not None:
        body["area_m2"] = area_m2
    if complex_id is not None:
        body["complex_id"] = complex_id
    r = client.post("/api/v1/affordability", json=body, headers=_auth(token))
    assert r.status_code == 200, r.text
    return r.json()["max_purchase_krw"]


def _single_number_verdicts(items, budget_krw: int | None) -> dict[str, int]:
    """**예산을 한 숫자로 들고** 지도 전체를 판정했을 때 서버 판정과 얼마나 갈리는가.

    CR38-1 이전의 화면(`lib/budgetStatus.checkVerdicts`)이 하던 계산 그대로다 —
    `/affordability` 가 준 금액 **하나**로 지도 항목 전부를 판정하고 서버 `over_budget`
    과 대조한다. 이 파일은 그 방식이 **면적이 섞이면 원리상 맞을 수 없다**는 것을
    숫자로 못박는 데 쓴다(아래 `test_한_숫자로_판정하면_...`).

    규칙:
      · 가격·예산 중 하나라도 양수가 아니면 `unknown` → 비교하지 않는다
      · 서버가 `null` 이면 `serverUnknown` → **불일치가 아니다**(`?? false` 금지)
      · 둘 다 판정했는데 답이 다르면 `conflicts`
    """
    compared = conflicts = server_unknown = screen_unknown = 0
    diverged: list[int] = []
    for item in items:
        price = item["recent_price_krw"]
        if not budget_krw or not price:
            screen_unknown += 1
            continue
        screen_over = price > budget_krw
        server = item["over_budget"]
        if server is None:
            server_unknown += 1
            continue
        compared += 1
        if server != screen_over:
            conflicts += 1
            diverged.append(item["id"])
    return {"compared": compared, "conflicts": conflicts,
            "serverUnknown": server_unknown, "screenUnknown": screen_unknown,
            "divergedIds": diverged}


# ---------------------------------------------------------------------------
# 0. 이 파일이 빈 검사가 아님을 먼저 증명한다
# ---------------------------------------------------------------------------

def test_이_테스트가_밟는_경계가_실재한다(client):
    """⚠️ **먼저 이것부터.** 두 면적의 한도가 실제로 다르지 않으면 아래 테스트는
    전부 '아무 일도 없어서 통과'가 된다(가상 픽스처로 짜면 정확히 그렇게 된다).

    운영 세율에서 85㎡ 초과분에 농특세 0.2% 가 붙는 한 두 값은 다르다.
    세제가 바뀌어 이 차이가 사라지면 **이 줄이 먼저 깨진다** — 그때 이 파일 전체가
    무의미해졌다는 사실이 조용히 묻히지 않는다.

    경계의 **위치**까지 못박는다(85.0 은 이하 · 85.01 부터 가산). 아래 테스트들이
    그 경계를 사이에 두고 면적을 깔기 때문에, 경계가 옮겨가면 배치가 무의미해진다.
    """
    token = _ready(client)
    small = _limit(client, token, area_m2=SMALL_AREA)
    large = _limit(client, token, area_m2=LARGE_AREA)
    assert small > large, (
        f"85㎡ 이하({SMALL_AREA})와 초과({LARGE_AREA})의 한도가 같습니다({small}) — "
        "이 파일의 모든 테스트가 빈 검사가 됩니다. 세율 설정을 확인하세요.")
    # 차이의 크기도 세율에서 나온 값인지 본다(0.2% 근방). 값이 통째로 달라지면 알린다.
    assert 0 < (small - large) < large * 0.01, (small, large)

    # 경계가 어디인가 — 0.01㎡ 차이로 뒤집히는 자리가 실재한다.
    assert _limit(client, token, area_m2=BOUNDARY_M2) == small, (
        f"{BOUNDARY_M2}㎡ 가 '85㎡ 이하' 구간이 아닙니다 — 아래 배치의 전제가 깨집니다")
    assert _limit(client, token, area_m2=JUST_OVER_M2) == large, (
        f"{JUST_OVER_M2}㎡ 가 '85㎡ 초과' 구간이 아닙니다 — 경계가 옮겨간 것 같습니다")

    # 단지를 고르기 전(기본 진입)의 한도 = 서버 기본 면적 84.0 = '85㎡ 이하' 쪽.
    assert _limit(client, token) == small


# ---------------------------------------------------------------------------
# 1. ★ 차단 CR37-1 · CR38-1 — **면적이 섞인 지도**에서 항목별 판정
# ---------------------------------------------------------------------------

def _mixed_map(client, token):
    """실제 지도 한 화면 — 면적 7종 × 가격 3구간 + 면적 미상 1건.

    가격은 두 상한을 기준으로 잡는다:
        below   : 둘 다 아래   → 면적과 무관하게 예산 안
        between : **두 상한 사이** → 면적이 답을 결정한다 (여기가 이 파일의 전부다)
        above   : 둘 다 위     → 면적과 무관하게 예산 초과

    돌려주는 것: `(items_by_id, {"small": …, "large": …, "between": …} 금액들)`
    """
    small_limit = _limit(client, token, area_m2=SMALL_AREA)
    large_limit = _limit(client, token, area_m2=LARGE_AREA)
    below = large_limit - 5_000_000
    between = (small_limit + large_limit) // 2       # 두 상한 **사이**
    above = small_limit + 5_000_000

    specs = []
    cid = 0
    for area in MIXED_AREAS:
        for price in (below, between, above):
            cid += 1
            specs.append((cid, price, area))
    specs.append((cid + 1, between, None))           # 체결 면적 미상
    _seed(client.repo, specs)

    body = _map(client, token, budget="mine")
    assert body["budget"] == {"applied": True, "basis": "max_purchase", "reason": None}
    items = {i["id"]: i for i in body["items"]}
    assert len(items) == len(specs), (len(items), len(specs))
    return items, {"small": small_limit, "large": large_limit,
                   "below": below, "between": between, "above": above}


def test_면적이_섞인_지도에서_항목마다_그_면적의_한도로_판정한다(client):
    """★ CR38-1 의 통과 조건 본체. **한 화면에 34㎡ 와 120㎡ 가 함께 있다.**

    각 항목의 `over_budget` 이 *그 항목 면적으로 부른* `/affordability` 와 같은 답인지
    **항목마다 API 를 다시 불러** 대조한다(계약 문장 그대로).

    변이: `_item_over_budget` 을 `budget_at(84.0)` 고정이나 `budget_at(None)` 으로
    되돌리면 85㎡ 초과 · `between` 가격 항목에서 깨진다.
    """
    token = _ready(client)
    items, money = _mixed_map(client, token)

    checked_between = 0
    for item in items.values():
        area = item["price_area_m2"]
        price = item["recent_price_krw"]
        if area is None:
            assert item["over_budget"] is None, "면적을 모르면 판정하지 않는다"
            continue
        limit = _limit(client, token, area_m2=area)
        assert item["over_budget"] == (price > limit), (
            f"단지 {item['id']}: 전용 {area}㎡ · {price:,}원 — 지도는 "
            f"{item['over_budget']} 인데 그 면적의 한도는 {limit:,}원이다")
        if price == money["between"]:
            checked_between += 1

    # 빈 통과 금지 ① — 답이 갈리는 구간을 실제로 밟았다(면적 7종 전부).
    assert checked_between == len(MIXED_AREAS), checked_between
    # 빈 통과 금지 ② — 같은 화면 안에서 True 와 False 가 **둘 다** 나왔다.
    verdicts = {i["over_budget"] for i in items.values()}
    assert verdicts == {True, False, None}, verdicts


def test_같은_가격이라도_0점01제곱미터_차이로_판정이_뒤집힌다(client):
    """경계가 실제로 **면적에서** 오는 것인지 못박는다.

    85.00㎡ 와 85.01㎡ 는 가격도 같고 단지 조건도 같다. 다른 것은 면적뿐이고,
    그래서 답이 달라야 한다. 서버가 한 숫자로 판정하면 둘은 **같은 답**이 된다.
    """
    token = _ready(client)
    items, money = _mixed_map(client, token)

    at_boundary = [i for i in items.values()
                   if i["price_area_m2"] == BOUNDARY_M2
                   and i["recent_price_krw"] == money["between"]][0]
    just_over = [i for i in items.values()
                 if i["price_area_m2"] == JUST_OVER_M2
                 and i["recent_price_krw"] == money["between"]][0]

    assert at_boundary["recent_price_krw"] == just_over["recent_price_krw"]
    assert at_boundary["over_budget"] is False, "85.00㎡ 는 농특세가 안 붙어 살 수 있다"
    assert just_over["over_budget"] is True, "85.01㎡ 는 농특세 0.2% 때문에 넘는다"


#: 화면이 지도를 여는 세 가지 상태. `area` 는 그 상태에서 `/affordability` 에 실리는 값.
#: (`None` = 단지를 고르기 전 — 파라미터를 아예 안 싣는다 → 서버 기본 84.0)
SCREEN_STATES = [
    pytest.param(None, id="단지_미선택_기본진입"),
    pytest.param(SMALL_AREA, id="85제곱미터_이하_단지_선택"),
    pytest.param(LARGE_AREA, id="85제곱미터_초과_단지_선택"),
]


@pytest.mark.parametrize("selected_area", SCREEN_STATES)
def test_어느_단지를_고르든_지도_판정은_그대로다(client, selected_area):
    """★ 세 상태 전부(CR38-1 통과 조건 1·2·3).

    **지도 판정은 사용자가 무엇을 골랐는지와 무관하다** — 항목마다 그 항목의 면적으로
    서는 값이기 때문이다. 반대로 화면이 예산을 한 숫자로 들고 있으면 그 숫자는
    선택에 따라 움직인다(그게 아래 테스트에서 갈리는 이유다).

    여기서는 고른 단지의 자금계획(`complex_id` + `area_m2` — 화면이 실제로 쓰는 호출
    모양)과 **그 단지의 지도 배지**가 같은 말을 하는지도 함께 본다.
    """
    token = _ready(client)
    items, money = _mixed_map(client, token)

    # ① 선택 상태와 무관하게 지도 판정은 항목 면적으로 선다.
    for item in items.values():
        area = item["price_area_m2"]
        if area is None:
            continue
        expected_limit = money["small"] if area <= BOUNDARY_M2 else money["large"]
        assert item["over_budget"] == (item["recent_price_krw"] > expected_limit), item

    if selected_area is None:
        # 단지를 고르기 전이면 자금계획은 면적 없이 열린다 — 대조할 단지가 없다.
        assert _limit(client, token) == money["small"]
        return

    # ② 그 면적의 단지를 눌러 자금계획을 열면, 서버는 **배지와 같은 말**을 해야 한다.
    picked = [i for i in items.values()
              if i["price_area_m2"] == selected_area
              and i["recent_price_krw"] == money["between"]][0]
    plan_limit = _limit(client, token,
                        complex_id=picked["id"], area_m2=selected_area)
    assert plan_limit == _limit(client, token, area_m2=selected_area)
    assert picked["over_budget"] == (picked["recent_price_krw"] > plan_limit), (
        "단지를 눌러 연 자금계획과 그 단지의 지도 배지가 서로 다른 말을 한다", picked)


@pytest.mark.parametrize("selected_area", SCREEN_STATES)
def test_한_숫자로_판정하면_세_상태_전부에서_어긋난다(client, selected_area):
    """⚠️ **이 테스트는 '고장'이 아니라 산술을 단언한다** — 면적이 섞인 지도를
    금액 **하나**로 판정하면 어느 상태에서도 맞을 수 없다.

    CR38-1 이전의 화면이 그 방식이었고(`/affordability` 한 번 → 전 항목 판정),
    리뷰어가 세 상태 전부에서 `conflicts=2` 를 재현했다. 여기서는 같은 계산을
    **서버 안에서** 돌려 그 사실을 고정한다:

    * 지도·목록 배지는 서버 `over_budget` 을 그대로 써야 한다(CR38-1 권고 (B)).
      화면이 자기 숫자로 다시 판정하는 순간 아래 `divergedIds` 가 곧 오답 목록이다.
    * 1차 판본은 이 대조를 **면적을 섞은 배치에서 부르지 않았다**(부르면 죽었다).
      이제 부르고, 죽는 대신 **얼마나·어디서 갈리는지**를 적는다.

    변이: `_item_over_budget` 을 고정 84 로 되돌리면 갈리는 자리가 달라져
    (미선택·85㎡ 이하 선택 상태에서는 conflicts 가 0 이 된다) 여기서 깨진다.
    """
    token = _ready(client)
    items, money = _mixed_map(client, token)

    screen_budget = _limit(client, token, area_m2=selected_area)
    check = _single_number_verdicts(list(items.values()), screen_budget)

    # 화면이 든 한 숫자는 **한 구간의 한도**일 수밖에 없다.
    assert screen_budget in (money["small"], money["large"]), screen_budget
    # 그래서 반대 구간의 `between` 가격 항목들이 통째로 갈린다.
    if screen_budget == money["small"]:
        expected = [i["id"] for i in items.values()
                    if i["price_area_m2"] is not None
                    and i["price_area_m2"] > BOUNDARY_M2
                    and i["recent_price_krw"] == money["between"]]
    else:
        expected = [i["id"] for i in items.values()
                    if i["price_area_m2"] is not None
                    and i["price_area_m2"] <= BOUNDARY_M2
                    and i["recent_price_krw"] == money["between"]]

    assert expected, "갈릴 자리가 없다면 배치가 잘못된 것이다(면적이 안 섞였다)"
    assert sorted(check["divergedIds"]) == sorted(expected), (
        "한 숫자 판정이 갈리는 자리가 예상과 다르다", check, expected,
        [(i["id"], i["price_area_m2"], i["recent_price_krw"], i["over_budget"])
         for i in items.values()])
    assert check["conflicts"] == len(expected) > 0, check
    assert check["serverUnknown"] == 1, check   # 면적 미상 1건은 불일치가 아니다


def test_저장한_희망가_기준이면_면적이_섞여도_한_숫자로_맞는다(client):
    """①(저장된 희망 매매가)은 사용자가 정한 **금액 하나**라 면적과 무관하다.

    그래서 이 기준에서는 면적이 섞여도 한 숫자 판정이 서버와 어긋나지 않는다.
    **위 테스트가 '항상 갈린다고 우기는 검사'가 아님을 여기서 보인다** — 갈리는 것은
    ②(자산으로 계산한 한도)뿐이고, 그 차이가 이 파일이 지키는 사실이다.
    """
    token = _ready(client)
    target = 1_025_570_000
    client.put("/api/v1/me/preferences",
               json={"prefer": {"target_price_krw": target}}, headers=_auth(token))

    specs = [(i + 1, price, area)
             for i, (area, price) in enumerate(
                 [(a, p) for a in MIXED_AREAS
                  for p in (target - 5_000_000, target + 5_000_000)])]
    _seed(client.repo, specs)

    body = _map(client, token, budget="mine")
    assert body["budget"]["basis"] == "target_price"
    check = _single_number_verdicts(body["items"], target)
    assert check["conflicts"] == 0, check
    assert check["compared"] == len(specs), check
    assert {i["over_budget"] for i in body["items"]} == {True, False}


def test_단지_id로_물어도_같은_숫자다(client):
    """화면은 `complex_id` + `area_m2` 로 부른다(`planRequest` 의 complex 분기).
    그 경로로도 지도와 같은 상한이어야 한다 — 화면이 실제로 쓰는 호출 모양이다.

    (항목이 하나뿐이고 그 면적으로 물었으므로, 한 숫자 판정이 맞는 **유일한** 경우다.)
    """
    token = _ready(client)
    limit = _limit(client, token, area_m2=LARGE_AREA)
    _seed(client.repo, [(7, limit + 1_000_000, LARGE_AREA)])

    item = _map(client, token, budget="mine")["items"][0]
    by_complex = _limit(client, token, complex_id=7, area_m2=LARGE_AREA)

    assert by_complex == limit
    assert item["over_budget"] is True
    assert _single_number_verdicts([item], by_complex)["conflicts"] == 0


# ---------------------------------------------------------------------------
# 2. 모르는 것은 모른다고 말한다 (G2)
# ---------------------------------------------------------------------------

def test_체결_면적을_모르면_한도를_못_세우므로_판정하지_않는다(client):
    """`price_area_m2` 가 없으면 **84㎡ 를 가정해 채우지 않는다.**

    가정해 채우면 사용자는 *다른 면적의 한도로 내린 판정*을 자기 단지의 판정으로
    읽는다 — 그게 CR37-1 의 본체였다. `null` 은 화면에서 '모름'으로 처리되고
    **불일치로 세지 않는다**(`serverUnknown`).
    """
    token = _ready(client)
    client.repo.add_complex(ComplexSummary(
        id=1, name="면적미상", lon=127.05, lat=37.51, region_code=REGION,
        built_year=2015, total_households=800,
        recent_price_krw=900_000_000, price_as_of=TODAY.isoformat(),
        price_area_m2=None, active_listings=0))

    body = _map(client, token, budget="mine")
    assert body["items"][0]["over_budget"] is None
    check = _single_number_verdicts(body["items"], _limit(client, token, area_m2=SMALL_AREA))
    assert check == {"compared": 0, "conflicts": 0, "serverUnknown": 1,
                     "screenUnknown": 0, "divergedIds": []}


def test_저장한_희망가는_면적과_무관해서_면적을_몰라도_판정한다(client):
    """①(저장된 희망 매매가)은 사용자가 정한 **금액 하나**다 — 면적이 뭐든 상한이 같다.

    그래서 이 기준에서는 면적 미상 단지도 판정한다. 면적 때문에 판정을 접는 것은
    ②(자산으로 계산한 한도)에만 해당한다는 사실을 여기서 못박는다.
    """
    token = _ready(client)
    client.put("/api/v1/me/preferences",
               json={"prefer": {"target_price_krw": 950_000_000}},
               headers=_auth(token))
    client.repo.add_complex(ComplexSummary(
        id=1, name="면적미상", lon=127.05, lat=37.51, region_code=REGION,
        built_year=2015, total_households=800,
        recent_price_krw=1_000_000_000, price_as_of=TODAY.isoformat(),
        price_area_m2=None, active_listings=0))

    body = _map(client, token, budget="mine")
    assert body["budget"]["basis"] == "target_price"
    assert body["items"][0]["over_budget"] is True


# ---------------------------------------------------------------------------
# 3. 면적별 계산을 **묶어서** 한다 (비용)
# ---------------------------------------------------------------------------

def test_같은_세율_구간의_면적은_한_번만_계산한다(client, monkeypatch):
    """지도 한 화면은 최대 500단지다. 면적마다 이분탐색을 새로 돌리면 실측 0.75ms ×
    500 = 375ms 로 지도 SQL(125~157ms)보다 오래 걸린다.

    `acquisition_area_class` 로 묶으면 운영 세율에서는 **2회**(85㎡ 이하 / 초과)면 된다.
    변이: `_profile_budget` 의 캐시를 지우면 호출이 40회로 늘어 여기서 깨진다.
    """
    from app.api import routes

    calls: list[float] = []
    real = routes.compute_affordability

    def counted(borrower, rules, **kw):
        prop = kw.get("prop")
        calls.append(prop.area_m2 if prop else -1.0)
        return real(borrower, rules, **kw)

    token = _ready(client)
    # 40 ~ 118㎡ — **85㎡ 경계를 가로지른다**(한쪽에만 몰아 두면 1구간이라 공짜 통과).
    _seed(client.repo, [(i, 900_000_000, 40.0 + i * 2) for i in range(40)])
    monkeypatch.setattr(routes, "compute_affordability", counted)

    body = _map(client, token, budget="mine")
    assert len(body["items"]) == 40
    assert len(calls) == 2, (
        f"면적 40종에 대해 한도를 {len(calls)}번 계산했습니다 — 세율 구간이 같은 면적은 "
        f"한 번이면 됩니다(운영 세율 기준 2구간). areas={calls}")
    # 묶었어도 **각 구간을 실제로 대표하는 면적**으로 계산했는지 본다.
    assert min(calls) <= 85 < max(calls), calls


# ---------------------------------------------------------------------------
# 4. 계약 문서 ↔ 실제 응답 (CR37-6 · 문서가 정본이라면 문서가 맞아야 한다)
# ---------------------------------------------------------------------------
#
# 프론트의 `apiContract.test.ts` 는 **문서를 정본으로** 목을 대조한다. 그러면 문서가
# 서버와 어긋나는 순간 프론트는 **틀린 계약을 충실히 지키게** 된다 — 그리고 그 어긋남을
# 아무도 못 본다(프론트 검사는 문서만 읽고, 백엔드 검사는 문서를 안 읽었다).
# CR37-6 이 정확히 그 형태였다: 문서 군집 예시에 서버에 없는 `name` 이 있었고,
# 서버에 있는 `price_basis` 는 문서에 없었는데 17개 검사가 전부 통과했다.
# 여기서 **양방향으로** 못박는다.

_MARKER_CLUSTER = "// res 200 — zoom < 13 : 군집(클러스터)"
_MARKER_COMPLEX = "// res 200 — zoom >= 13 : 단지 단위"


def _example_after(marker: str, spec: str | None = None) -> dict:
    """문서에서 마커 **바로 뒤**의 JSON 예시 하나를 꺼낸다.

    프론트 `src/test/specParser.ts` 와 같은 규칙이다 — 마커는 문서에 한 번만 있어야
    하고, 객체는 마커 다음 줄에서 시작해야 하며, 중괄호 균형으로 끊는다.
    (예시를 지우면 **옆 예시를 대신 읽는 게 아니라 죽는다.**)

    ⚠️ `spec` 을 인자로 받는 이유: 아래 "빈 검사 금지" 테스트가 **훼손된 사본**으로
       이 함수를 때릴 수 있어야 한다. 실제 파일을 잠깐이라도 훼손하면 같은 순간에
       그 파일을 읽는 다른 작업(프론트 계약 테스트)이 엉뚱하게 깨진다.
    """
    if spec is None:
        spec = API_SPEC.read_text(encoding="utf-8")
    assert marker in spec, f"문서에서 마커를 찾지 못했다: {marker}"
    at = spec.index(marker)
    assert spec.find(marker, at + len(marker)) < 0, f"마커가 두 번 이상: {marker}"

    lines = spec[at + len(marker):].split("\n")
    i = 0
    while i < len(lines) and lines[i].strip() == "":
        i += 1
    assert lines[i].lstrip().startswith("{"), (
        f"'{marker}' 바로 뒤에서 JSON 객체가 시작하지 않는다: {lines[i][:60]!r}")

    body = "\n".join("" if ln.strip().startswith("//") else ln for ln in lines[i:])
    depth, in_str, esc = 0, False, False
    for j, ch in enumerate(body):
        if in_str:
            if esc:
                esc = False
            elif ch == "\\":
                esc = True
            elif ch == '"':
                in_str = False
            continue
        if ch == '"':
            in_str = True
        elif ch == "{":
            depth += 1
        elif ch == "}":
            depth -= 1
            if depth == 0:
                return json.loads(body[:j + 1])
    raise AssertionError(f"'{marker}' 뒤 JSON 객체가 닫히지 않았다")


def test_문서의_지도_예시_키가_실제_응답과_같다(client):
    """★ CR37-6. **문서가 정본이면 문서가 서버와 같아야 한다.**

    변이: 문서 예시에서 `price_area_m2`(또는 `price_basis_note`)를 지우거나,
    서버 응답에 필드를 하나 더하고 문서를 안 고치면 여기서 깨진다.
    """
    token = _ready(client)
    _seed(client.repo, [(1, 900_000_000, SMALL_AREA)])

    body = _map(client, token)          # zoom 15 → 단지 단위
    doc = _example_after(_MARKER_COMPLEX)
    assert sorted(doc) == sorted(body), (
        "문서(§4)와 실제 단지 응답의 **최상위 키**가 다릅니다", sorted(doc), sorted(body))
    assert sorted(doc["items"][0]) == sorted(body["items"][0]), (
        "문서와 실제 **항목 키**가 다릅니다",
        sorted(doc["items"][0]), sorted(body["items"][0]))
    assert sorted(doc["budget"]) == sorted(body["budget"]), (
        sorted(doc["budget"]), sorted(body["budget"]))
    # 계약이 3값이라는 사실 자체(프론트가 `?? false` 로 접지 않게)
    assert doc["items"][0]["over_budget"] is None


def test_문서의_군집_예시_키가_실제_응답과_같다(client):
    """군집도 같은 규칙. 줌아웃 응답은 화면이 덜 보는 자리라 드리프트가 오래 산다."""
    token = _ready(client)
    _seed(client.repo, [(1, 900_000_000, SMALL_AREA)])

    r = client.get("/api/v1/map/complexes",
                   params={"bbox": BBOX, "zoom": 10, "budget": "mine"},
                   headers=_auth(token))
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["level"] == "cluster"

    doc = _example_after(_MARKER_CLUSTER)
    assert sorted(doc) == sorted(body), (sorted(doc), sorted(body))
    assert sorted(doc["items"][0]) == sorted(body["items"][0]), (
        sorted(doc["items"][0]), sorted(body["items"][0]))
    assert sorted(doc["budget"]) == sorted(body["budget"])


def test_문서에서_예시를_지우면_이_검사가_죽는다():
    """**빈 검사 금지.** 예시가 사라졌을 때 조용히 통과하면 위 두 테스트는 무의미하다.

    ⚠️ 파일을 훼손하지 않는다 — **메모리 사본**으로 파서를 때린다. 실제 파일을 잠깐
       비틀면, 같은 순간 그 파일을 읽는 프론트 계약 테스트가 엉뚱하게 깨진다.
    """
    spec = API_SPEC.read_text(encoding="utf-8")
    assert _MARKER_COMPLEX in spec and _MARKER_CLUSTER in spec

    # ① 마커 바로 뒤 객체가 사라진 사본 — **옆 예시를 대신 읽으면 안 된다.**
    broken = re.sub(re.escape(_MARKER_CLUSTER) + r"\n\{.*?\n\n",
                    _MARKER_CLUSTER + "\n\n", spec, count=1, flags=re.DOTALL)
    assert broken != spec, "사본 훼손에 실패했다 — 이 테스트가 아무것도 확인하지 않는다"
    assert _MARKER_COMPLEX in broken, "옆 예시는 남아 있어야 시험이 성립한다"
    with pytest.raises(AssertionError):
        _example_after(_MARKER_CLUSTER, broken)

    # ② 마커가 통째로 사라진 사본
    with pytest.raises(AssertionError):
        _example_after(_MARKER_CLUSTER, spec.replace(_MARKER_CLUSTER, "// (지움)"))

    # ③ 원본은 여전히 읽힌다(위 두 단언이 '항상 죽는 파서' 때문이 아님을 보인다)
    assert _example_after(_MARKER_CLUSTER, spec)["level"] == "cluster"

    # 파일을 건드리지 않았다.
    assert API_SPEC.read_text(encoding="utf-8") == spec
