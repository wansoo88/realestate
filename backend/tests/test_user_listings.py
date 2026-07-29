"""사용자 수동 입력 호가 (migrations/016 · `/me/listings`).

이 파일이 지키는 것은 셋이다. 순서대로 중요하다.

  ① **소유자 스코프(IDOR)** — 남의 호가가 목록·조회·수정·삭제·추천 어디에도
     새지 않는다. 배선을 잊으면 **아무것도 안 보이는 쪽**으로 실패한다(fail-closed).
  ② **출처 구분** — 응답과 근거에서 "사용자 입력"이라는 사실이 지워지지 않는다.
  ③ **낡은 호가 배제** — as_of 가 90일을 넘으면 추천 계산에서 빠진다. 조용히가 아니라
     `staleness`·`eligible_for_recommendation`·`problems` 로 말하면서 뺀다.

세 가지 모두 **깨뜨려 보고** 잡히는지 확인한다(변이 테스트 · 파일 하단).
"""
from __future__ import annotations

import datetime as dt
import inspect
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app.repositories.base import (
    LISTING_FRESH_DAYS,
    LISTING_MAX_AGE_DAYS,
    LISTING_SOURCE_USER,
    LISTING_STALE_DAYS,
    MAX_USER_LISTINGS,
    ComplexSummary,
    listing_staleness,
    listing_usable,
)
from app.repositories.memory import InMemoryRepository

FIXTURES = Path(__file__).parent / "fixtures"
PASSWORD = "correct horse battery staple"
JWT_SECRET = "x" * 40
TODAY = dt.date.today()


def _days_ago(n: int) -> str:
    return (TODAY - dt.timedelta(days=n)).isoformat()


@pytest.fixture()
def client(monkeypatch):
    monkeypatch.setenv("JWT_SECRET", JWT_SECRET)
    monkeypatch.setenv("FIELD_ENCRYPTION_KEY", "k" * 32)
    monkeypatch.setenv("POSTGRES_PASSWORD", "pw")
    monkeypatch.setenv("TAX_RULES_PATH", str(FIXTURES / "tax_rules_test.yaml"))

    from app.core.config import get_settings
    get_settings.cache_clear()
    from app.main import create_app

    repo = InMemoryRepository()
    repo.add_complex(ComplexSummary(id=1, name="테스트1단지", lon=127.05, lat=37.5,
                                    region_code="1168010100", total_households=800))
    repo.add_complex(ComplexSummary(id=2, name="테스트2단지", lon=127.06, lat=37.51,
                                    region_code="1168010100", total_households=500))
    app = create_app(repo=repo)
    with TestClient(app) as c:
        c.repo = repo
        yield c
    get_settings.cache_clear()


def _login(client, email: str) -> dict[str, str]:
    r = client.post("/api/v1/auth/register", json={"email": email, "password": PASSWORD})
    assert r.status_code == 201, r.text
    user = client.repo.get_user_by_email(email)
    client.repo.set_user_status(user.id, "approved", actor="cli")
    r = client.post("/api/v1/auth/login", json={"email": email, "password": PASSWORD})
    assert r.status_code == 200, r.text
    return {"Authorization": f"Bearer {r.json()['access_token']}"}


def _body(**over):
    payload = {"complex_id": 1, "ask_price_krw": 1_480_000_000, "area_m2": 84.97,
               "floor": 9, "apt_dong": "101동", "as_of": TODAY.isoformat()}
    payload.update(over)
    return payload


# ---------------------------------------------------------------------------
# 기본 CRUD
# ---------------------------------------------------------------------------

def test_등록하면_사용자_입력_출처가_응답에_박힌다(client):
    """출처가 응답에서 지워지면 이 숫자는 공공 데이터처럼 보인다(설계 원칙 ②)."""
    h = _login(client, "a@b.co")
    r = client.post("/api/v1/me/listings", json=_body(), headers=h)
    assert r.status_code == 201, r.text
    item = r.json()["item"]
    assert item["source"] == LISTING_SOURCE_USER
    assert item["source_label"] == "사용자 입력"
    assert item["complex_name"] == "테스트1단지"
    assert item["eligible_for_recommendation"] is True
    assert item["staleness"] == "fresh"
    # ₩/㎡ 를 함께 준다 — 단위 실수를 사용자가 스스로 알아채는 가장 빠른 숫자다.
    assert item["price_per_m2_krw"] == round(1_480_000_000 / 84.97)


def test_같은_단지_같은_면적에_여러_건을_넣을_수_있다(client):
    """매물은 원래 여럿이다. 서버가 임의로 합치면 선택지가 사라진다."""
    h = _login(client, "a@b.co")
    for floor in (3, 9, 17):
        r = client.post("/api/v1/me/listings", json=_body(floor=floor), headers=h)
        assert r.status_code == 201
    rows = client.get("/api/v1/me/listings?complex_id=1", headers=h).json()
    assert rows["summary"]["total"] == 3
    assert rows["summary"]["eligible_for_recommendation"] == 3


def test_같은_조건_중복은_막지_않되_고지한다(client):
    """저장은 하되 말한다 — 합칠지는 사람이 정한다(가격이 바뀐 재입력은 두 매물이 된다)."""
    h = _login(client, "a@b.co")
    client.post("/api/v1/me/listings", json=_body(), headers=h)
    r = client.post("/api/v1/me/listings",
                    json=_body(ask_price_krw=1_400_000_000), headers=h)
    assert r.status_code == 201
    joined = " ".join(r.json()["problems"])
    assert "이미 1건" in joined and "수정" in joined


def test_수정과_삭제가_된다(client):
    """되돌릴 수 없으면 아무도 안 쓴다."""
    h = _login(client, "a@b.co")
    lid = client.post("/api/v1/me/listings", json=_body(), headers=h).json()["item"]["id"]

    r = client.patch(f"/api/v1/me/listings/{lid}",
                     json={"ask_price_krw": 1_390_000_000, "as_of": TODAY.isoformat()},
                     headers=h)
    assert r.status_code == 200, r.text
    assert r.json()["item"]["ask_price_krw"] == 1_390_000_000

    assert client.delete(f"/api/v1/me/listings/{lid}", headers=h).status_code == 204
    assert client.get("/api/v1/me/listings", headers=h).json()["summary"]["total"] == 0


def test_상태를_traded_로_바꾸면_추천에서_빠진다(client):
    """삭제하지 않고 '팔렸다'를 기록으로 남기는 길."""
    h = _login(client, "a@b.co")
    lid = client.post("/api/v1/me/listings", json=_body(), headers=h).json()["item"]["id"]
    r = client.patch(f"/api/v1/me/listings/{lid}", json={"status": "traded"}, headers=h)
    assert r.json()["item"]["eligible_for_recommendation"] is False
    assert client.repo.listings_for_complex(1, user_id=1) == []


def test_가격만_바꾸면_422(client):
    """호가는 '얼마'와 '언제 본 값'이 분리될 수 없다."""
    h = _login(client, "a@b.co")
    lid = client.post("/api/v1/me/listings", json=_body(), headers=h).json()["item"]["id"]
    r = client.patch(f"/api/v1/me/listings/{lid}",
                     json={"ask_price_krw": 1_390_000_000}, headers=h)
    assert r.status_code == 422
    assert "as_of" in r.json()["detail"]["message"]


def test_비울_수_없는_값에_null을_보내면_422다(client):
    """조용히 무시하면 사용자는 지웠다고 믿는다. 그리고 500 으로 터지지도 않는다 —
    사용자 입력 오류가 서버 오류로 보이는 것도 거짓말이다."""
    h = _login(client, "a@b.co")
    lid = client.post("/api/v1/me/listings", json=_body(), headers=h).json()["item"]["id"]
    for field in ("as_of", "ask_price_krw", "area_m2", "status"):
        r = client.patch(f"/api/v1/me/listings/{lid}", json={field: None}, headers=h)
        assert r.status_code == 422, f"{field}: null 이 {r.status_code} 로 통과했다"
        assert field in r.json()["detail"]["message"]
    # 원본은 그대로다.
    item = client.get("/api/v1/me/listings", headers=h).json()["items"][0]
    assert item["as_of"] == TODAY.isoformat()


def test_비울_수_있는_값은_null로_지운다(client):
    """생략 = 안 건드림 · null = 비우기. 두 뜻이 겹치지 않는다."""
    h = _login(client, "a@b.co")
    lid = client.post("/api/v1/me/listings", json=_body(note="원본"),
                      headers=h).json()["item"]["id"]

    r = client.patch(f"/api/v1/me/listings/{lid}", json={"note": None}, headers=h)
    assert r.json()["item"]["note"] is None
    assert r.json()["item"]["apt_dong"] == "101동"      # 생략한 항목은 그대로

    r = client.patch(f"/api/v1/me/listings/{lid}", json={"apt_dong": "  "}, headers=h)
    assert r.json()["item"]["apt_dong"] is None         # 공백만 있어도 비운다

    r = client.patch(f"/api/v1/me/listings/{lid}", json={"floor": None}, headers=h)
    assert r.json()["item"]["floor"] is None            # 층 '모름'으로 되돌리기


def test_없는_단지에는_저장하지_않는다(client):
    h = _login(client, "a@b.co")
    r = client.post("/api/v1/me/listings", json=_body(complex_id=9999), headers=h)
    assert r.status_code == 404


# ---------------------------------------------------------------------------
# 검증 — 말도 안 되는 값을 조용히 받지 않는다
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("over, why", [
    ({"ask_price_krw": 0}, "0원"),
    ({"ask_price_krw": 15}, "억 단위로 잘못 입력"),
    ({"ask_price_krw": 150_000}, "만원 단위로 잘못 입력"),
    ({"ask_price_krw": 1_000_000_000_000}, "1조원"),
    ({"area_m2": 0}, "면적 0"),
    ({"area_m2": -84.0}, "음수 면적"),
    ({"area_m2": 5000.0}, "면적 5000㎡"),
    ({"floor": 9999}, "9999층"),
    ({"as_of": (TODAY + dt.timedelta(days=1)).isoformat()}, "미래 날짜"),
    ({"as_of": _days_ago(LISTING_MAX_AGE_DAYS + 1)}, "1년 넘은 호가"),
])
def test_말도_안_되는_값은_422(client, over, why):
    h = _login(client, "a@b.co")
    r = client.post("/api/v1/me/listings", json=_body(**over), headers=h)
    assert r.status_code == 422, f"{why} 를 받아들였다: {r.text}"


def test_422_응답이_입력값을_되돌려주지_않는다(client):
    """SR25-2 — pydantic 은 ValueError 문자열을 그대로 반사한다. 값은 싣지 않는다."""
    h = _login(client, "a@b.co")
    r = client.post("/api/v1/me/listings",
                    json=_body(as_of=(TODAY + dt.timedelta(days=3)).isoformat()), headers=h)
    assert r.status_code == 422
    assert (TODAY + dt.timedelta(days=3)).isoformat() not in r.text


#: 두 리포지토리가 갈라지던 입력. `\x00` 은 **JSON 문법상 정상**이라
#: (`"\u0000"`) pydantic `str`·`max_length`·`.strip()` 을 전부 통과했다.
_CONTROL_PAYLOADS = [
    ("\x00", "NUL — PostgreSQL text 가 타입 수준에서 거절한다(운영 500 의 원인)"),
    ("101동\x00", "값 뒤에 붙은 NUL"),
    ("메모\x01끝", "C0 제어문자"),
    ("메모\x1b[31m빨강", "ANSI 이스케이프(터미널·로그를 조작한다)"),
    ("메모\x7f", "DEL"),
]


@pytest.mark.parametrize("payload, why", _CONTROL_PAYLOADS)
@pytest.mark.parametrize("field", ["note", "apt_dong"])
def test_제어문자는_저장하지_않고_거절한다(client, field, payload, why):
    """★ SR31-1. **인메모리 201 / 운영 500** 이던 갈라짐을 계약으로 닫는다.

    갈라짐이 남으면 이 구간에서 테스트 1,368건이 운영을 대표하지 못한다 —
    인메모리에서 초록인 입력이 PostgreSQL 에서 `psycopg.DataError` 로 죽는다.
    **좁은 쪽(PostgreSQL)에 맞춰 거절**한다. 조용히 지우지 않는 이유는
    이 두 필드가 "원문 그대로 보관·반환"을 약속한 자리이기 때문이다.

    변이: `_clean_optional_text` 의 제어문자 검사를 지우면 201 이 되어 깨진다.
    """
    h = _login(client, "a@b.co")
    r = client.post("/api/v1/me/listings", json=_body(**{field: payload}), headers=h)
    assert r.status_code == 422, f"{why} 를 받아들였다: {r.text}"
    # 값을 되비추지 않는다(SR25-2) — 무엇이 걸렸는지 말하되 무엇을 보냈는지는 안 적는다.
    assert "\\u0000" not in r.text and "\\u001b" not in r.text
    assert client.get("/api/v1/me/listings", headers=h).json()["summary"]["total"] == 0


@pytest.mark.parametrize("payload, why", _CONTROL_PAYLOADS)
def test_수정으로도_제어문자를_넣을_수_없다(client, payload, why):
    """POST 만 막으면 PATCH 가 뒷문이 된다 — 두 스키마가 **같은 함수**를 써야 한다."""
    h = _login(client, "a@b.co")
    lid = client.post("/api/v1/me/listings", json=_body(),
                      headers=h).json()["item"]["id"]
    r = client.patch(f"/api/v1/me/listings/{lid}", json={"note": payload}, headers=h)
    assert r.status_code == 422, f"{why} 를 PATCH 로 받아들였다: {r.text}"
    assert client.get("/api/v1/me/listings",
                      headers=h).json()["items"][0]["note"] is None


@pytest.mark.parametrize("payload", [
    "네이버 부동산\n○○공인",      # 붙여넣기에 흔한 줄바꿈
    "가격\t14.8억",               # 표에서 복사하면 탭이 온다
    "급매 🏠 확인함",              # 이모지는 제어문자가 아니다
    "１０１동",                    # 전각
])
def test_정상적인_붙여넣기는_그대로_보존한다(client, payload):
    """제어문자를 막는다고 사람이 실제로 쓰는 값까지 막으면 안 된다.

    탭·줄바꿈은 PostgreSQL 도 받는다 — 여기서 거절하면 **양쪽 다 받을 수 있는 값**을
    우리가 임의로 좁히는 것이고, 그건 갈라짐을 고치는 방법이 아니다.
    """
    h = _login(client, "a@b.co")
    r = client.post("/api/v1/me/listings", json=_body(note=payload), headers=h)
    assert r.status_code == 201, r.text
    assert r.json()["item"]["note"] == payload.strip()


def test_사용자당_행_상한이_있고_닿으면_말한다(client):
    """★ SR31-3. **행을 무제한 만드는 첫 엔드포인트**다(프로필·선호는 1행 upsert).

    운영 `/` 는 92% 사용·여유 2.2GB 이고 db 는 `mem_limit 192m` · 스왑 없음이다.
    악의가 아니라 클라이언트 재시도 루프 하나로도 닿는다. 상한이 없으면 그때
    디스크가 먼저 죽고, 같은 호스트의 다른 서비스까지 함께 죽는다.

    거절은 **조용하지 않다** — 409 + 무엇을 하면 되는지(삭제·PATCH)를 말한다.

    변이: 라우터의 `len(mine) >= MAX_USER_LISTINGS` 검사를 지우면 201 이 되어 깨진다.
    """
    h = _login(client, "a@b.co")
    uid = client.repo.get_user_by_email("a@b.co").id
    for _ in range(MAX_USER_LISTINGS):
        client.repo.add_user_listing(uid, complex_id=1, ask_price_krw=1_000_000_000,
                                     area_m2=84.97, as_of=TODAY)

    r = client.post("/api/v1/me/listings", json=_body(), headers=h)
    assert r.status_code == 409, r.text
    detail = r.json()["detail"]
    assert detail["code"] == "LIMIT_REACHED"
    assert "수정" in detail["message"] and str(MAX_USER_LISTINGS) in detail["message"]

    # 지우면 다시 넣을 수 있다 — 영구히 잠기지 않는다.
    lid = client.get("/api/v1/me/listings", headers=h).json()["items"][0]["id"]
    assert client.delete(f"/api/v1/me/listings/{lid}", headers=h).status_code == 204
    assert client.post("/api/v1/me/listings", json=_body(),
                       headers=h).status_code == 201


def test_상한은_목록_상한과_같은_값이라_요약이_틀리지_않는다(client):
    """★ CR35-8 을 상한 하나로 함께 닫는다.

    `list_user_listings` 가 200건에서 자르는데 그보다 많이 만들 수 있으면
    `summary.total` 과 중복 경고가 **조용히** 틀린다(201건째부터 "이미 N건
    등록돼 있습니다"가 거짓이 된다). 두 숫자를 하나로 묶으면 그 상태가 생기지 않는다.

    변이: `MAX_USER_LISTINGS` 와 `list_user_listings(limit=...)` 기본값을 갈라 놓으면
    (예: 상한 300 / 목록 200) 여기서 깨진다.

    ★ CR36-4: **프로토콜 선언(`base.py`)도 함께 본다.** 두 구현은 상수를 쓰는데
    선언만 리터럴 `200` 이었다. 값이 같은 동안에는 아래 `signature` 검사가 통과하므로
    (200 == MAX_USER_LISTINGS), 리터럴 자체를 소스에서 금지한다 — 상수를 올리는 날
    선언만 남아 "계약은 200, 구현은 300"이 되는 것을 막는 것이 목적이다.
    """
    import re

    from app.repositories.base import UserListingRepository
    from app.repositories.memory import InMemoryRepository
    from app.repositories.postgis import PostgisRepository

    for repo_cls in (UserListingRepository, InMemoryRepository, PostgisRepository):
        sig = inspect.signature(repo_cls.list_user_listings)
        assert sig.parameters["limit"].default == MAX_USER_LISTINGS, (
            f"{repo_cls.__name__}.list_user_listings 의 목록 상한이 "
            f"MAX_USER_LISTINGS 와 다르다 — 요약·중복 경고가 조용히 틀린다")

    for module in (inspect.getmodule(UserListingRepository),
                   inspect.getmodule(InMemoryRepository),
                   inspect.getmodule(PostgisRepository)):
        source = inspect.getsource(module)
        literal = re.search(r"def list_user_listings\([^)]*limit:\s*int\s*=\s*\d+",
                            source, re.DOTALL)
        assert literal is None, (
            f"{module.__name__} 의 list_user_listings 에 목록 상한이 리터럴로 "
            "박혀 있다 — MAX_USER_LISTINGS 를 쓸 것")

    h = _login(client, "a@b.co")
    uid = client.repo.get_user_by_email("a@b.co").id
    for _ in range(MAX_USER_LISTINGS):
        client.repo.add_user_listing(uid, complex_id=1, ask_price_krw=1_000_000_000,
                                     area_m2=84.97, as_of=TODAY)
    listed = client.get("/api/v1/me/listings", headers=h).json()
    assert listed["summary"]["total"] == MAX_USER_LISTINGS == len(listed["items"])


def test_이상한_단가는_거절이_아니라_고지다(client):
    """가능하지만 이상한 값은 저장하되 말한다 — 강남 초고가·경기 저가를 막으면 안 된다."""
    h = _login(client, "a@b.co")
    # 84.97㎡ 를 1.48억으로(10배 실수) → ㎡당 174만원
    r = client.post("/api/v1/me/listings",
                    json=_body(ask_price_krw=148_000_000), headers=h)
    assert r.status_code == 201
    assert any("㎡당" in p for p in r.json()["problems"])
    # 저장은 됐다 — 값이 맞을 수도 있으므로 사용자가 판단한다.
    assert client.get("/api/v1/me/listings", headers=h).json()["summary"]["total"] == 1


# ---------------------------------------------------------------------------
# ★ CR35-11 — ₩/㎡ 를 통과하는 자릿수 실수는 **그 단지 실거래**로만 잡힌다
#
# 9.2억을 3.0억으로 오타해도 84.97㎡ 기준 353만원/㎡ 라 절대 구간(200만~6,000만)
# 한가운데다. 그래서 아무 경고 없이 저장되고 카드에는 "적정가 하단 — 급매 가능"이
# 떴다. **틀린 값이 좋은 소식으로 보이는** 형태다.
# ---------------------------------------------------------------------------

def _seed_trades(repo, complex_id=1, *, price_oku=9.2, area=84.97, n=10):
    """그 단지의 실거래를 심는다. 밴드 중위 ≈ price_oku 억."""
    from app.domain.valuation.models import TradeRow

    repo.add_trades(complex_id, [
        TradeRow(contract_date=TODAY - dt.timedelta(days=20 * i),
                 price_krw=int(price_oku * 100_000_000), area_m2=area, floor=10)
        for i in range(n)
    ])


def _band_note(problems: list[str]) -> str | None:
    return next((p for p in problems if "최근 실거래 기준가" in p), None)


def test_단지_실거래와_동떨어진_호가는_고지한다(client):
    """★ CR35-11. 9.2억 단지에 3.0억 — ₩/㎡ 검사는 통과하지만 여기서 걸린다.

    변이: `_listing_problems` 의 `_band_problem` 호출이나 라우터의
    `_listing_reference(repo, rec)` 인자를 지우면 경고가 사라져 여기서 깨진다.
    """
    h = _login(client, "a@b.co")
    _seed_trades(client.repo)

    r = client.post("/api/v1/me/listings",
                    json=_body(ask_price_krw=300_000_000), headers=h)

    assert r.status_code == 201, "거절하지 않는다 — 진짜 급매일 수 있다"
    problems = r.json()["problems"]
    # ₩/㎡ 검사는 이 값을 통과시킨다(353만원/㎡). 이 사실이 이 테스트의 존재 이유다.
    assert 2_000_000 <= 300_000_000 / 84.97 <= 60_000_000
    assert not any("㎡당" in p for p in problems), "절대 구간은 이 값을 못 잡는다"

    note = _band_note(problems)
    assert note, problems
    assert "낮습니다" in note and "자릿수" in note
    assert "그대로 두셔도" in note, "막지 않는다는 사실을 말해야 한다"
    # 저장은 됐다.
    assert client.get("/api/v1/me/listings", headers=h).json()["summary"]["total"] == 1


def test_정상_범위_호가에는_밴드_경고가_붙지_않는다(client):
    """늘 뜨는 경고는 아무도 읽지 않는다. 9.2억 단지에 9.9억(+7.6%)은 조용하다."""
    h = _login(client, "a@b.co")
    _seed_trades(client.repo)

    r = client.post("/api/v1/me/listings",
                    json=_body(ask_price_krw=990_000_000), headers=h)
    assert r.status_code == 201
    assert _band_note(r.json()["problems"]) is None, r.json()["problems"]


def test_수정으로_바꾼_가격에도_같은_검사가_돈다(client):
    """POST 로는 막히는데 PATCH 로는 들어가는 자리를 만들지 않는다(SR31-1 과 같은 규칙)."""
    h = _login(client, "a@b.co")
    _seed_trades(client.repo)
    lid = client.post("/api/v1/me/listings",
                      json=_body(ask_price_krw=990_000_000),
                      headers=h).json()["item"]["id"]

    r = client.patch(f"/api/v1/me/listings/{lid}",
                     json={"ask_price_krw": 300_000_000, "as_of": TODAY.isoformat()},
                     headers=h)
    assert r.status_code == 200, r.text
    assert _band_note(r.json()["problems"]), r.json()["problems"]


def test_실거래가_없으면_대조하지_못했다고_말한다(client):
    """**모름을 통과로 읽히게 두지 않는다.** 아무 말이 없으면 사용자는 검증됐다고 읽는다."""
    h = _login(client, "a@b.co")            # 이 픽스처의 단지에는 실거래가 없다

    r = client.post("/api/v1/me/listings", json=_body(), headers=h)
    assert r.status_code == 201
    assert any("대조하지 못했습니다" in p for p in r.json()["problems"])


def test_밴드_대조가_다른_면적을_기준으로_하지_않는다(client):
    """59㎡ 호가를 84㎡ 실거래와 견주면 정상 호가가 전부 '너무 싸다'가 된다.

    ⚠️ 단언이 `problems == []` 인 이유: "경고가 없다"만 보면 **약한 테스트**가 된다.
       면적을 84 로 고정하는 변이는 그 단지의 84㎡ 밴드(9.2억)와 견주거나(→ 45% 경고),
       84.0 근처 거래가 없어(→ "대조하지 못했습니다") **둘 중 하나를 반드시 남긴다.**
       빈 목록을 요구해야 두 갈래가 다 잡힌다(실측: 이 단언 없이는 변이가 살아남았다).
    """
    h = _login(client, "a@b.co")
    _seed_trades(client.repo, price_oku=9.2, area=84.97)
    _seed_trades(client.repo, price_oku=4.0, area=59.94)

    # 59.94㎡ 밴드(4.0억) 기준 +2.5% — 정상. 84㎡ 밴드(9.2억) 기준이면 45% 라 경고가 뜬다.
    r = client.post("/api/v1/me/listings",
                    json=_body(ask_price_krw=410_000_000, area_m2=59.94), headers=h)
    assert r.status_code == 201
    assert r.json()["problems"] == [], r.json()["problems"]


# ---------------------------------------------------------------------------
# 낡은 호가
# ---------------------------------------------------------------------------

def test_낡은_호가는_추천_계산에서_빠지고_목록에는_남는다(client):
    """목록은 **고치라고** 보여주는 화면이다. 숨기면 갱신할 대상을 볼 수 없다."""
    h = _login(client, "a@b.co")
    r = client.post("/api/v1/me/listings",
                    json=_body(as_of=_days_ago(LISTING_STALE_DAYS + 5)), headers=h)
    assert r.status_code == 201
    item = r.json()["item"]
    assert item["staleness"] == "stale"
    assert item["eligible_for_recommendation"] is False
    assert any("제외" in p for p in r.json()["problems"])

    listed = client.get("/api/v1/me/listings", headers=h).json()
    assert listed["summary"] == {**listed["summary"], "total": 1, "stale": 1,
                                 "eligible_for_recommendation": 0}
    assert any("반영되지 않습니다" in n for n in listed["notes"])
    # 그리고 실제로 분석 계층에 도달하지 않는다.
    assert client.repo.listings_for_complex(1, user_id=1) == []


def test_31일에서_90일은_쓰되_며칠_된_값인지_말한다(client):
    h = _login(client, "a@b.co")
    r = client.post("/api/v1/me/listings",
                    json=_body(as_of=_days_ago(LISTING_FRESH_DAYS + 10)), headers=h)
    body = r.json()
    assert body["item"]["staleness"] == "aging"
    assert body["item"]["eligible_for_recommendation"] is True
    assert any("일 전에 확인한" in p for p in body["problems"])


def test_경계값_판정(client):
    """경계에서 등급이 갈리는지 — 상수를 바꾸면 여기가 먼저 깨진다."""
    assert listing_staleness(TODAY - dt.timedelta(LISTING_FRESH_DAYS))[0] == "fresh"
    assert listing_staleness(TODAY - dt.timedelta(LISTING_FRESH_DAYS + 1))[0] == "aging"
    assert listing_staleness(TODAY - dt.timedelta(LISTING_STALE_DAYS))[0] == "aging"
    assert listing_staleness(TODAY - dt.timedelta(LISTING_STALE_DAYS + 1))[0] == "stale"
    # as_of 를 모르면 stale — 모름은 통과가 아니다.
    assert listing_staleness(None)[0] == "stale"
    assert listing_usable(None, "active") is False


# ---------------------------------------------------------------------------
# 서버가 **모르는 것을 안다고 말하지 않는다** (CR35-7 · SR31-2)
# ---------------------------------------------------------------------------

def test_추천_반영_여부를_단언하지_않고_자격만_말한다(client):
    """★ CR35-7 · SR31-2.

    옛 이름은 `used_in_recommendation`("추천에 **사용됨**")이었다. 서버가 재는 것은
    `listing_usable()` = 활성 + 안 낡음뿐이고, 실제로 반영되려면 그 단지가 추천
    요청의 지역·예산·평수 조건과 후보 조회 상한까지 통과해야 한다. 그 조회는 소유자
    인자를 받지 않으므로(교차 사용자 누출 방지) 사용자 호가는 근거로 세어지지 않는다.
    실측(SR-031): 인천 단지에 넣은 호가가 `true` 인데 서울만 요청한 추천은 그 호가를
    **0회** 본다.

    그래서 ① 이름을 자격(`eligible_…`)으로 바꾸고 ② 남은 조건을 상시 고지한다.

    변이: 필드명을 되돌리거나 `LISTING_ELIGIBILITY_NOTE` 를 응답에서 빼면 깨진다.
    """
    h = _login(client, "a@b.co")
    created = client.post("/api/v1/me/listings", json=_body(), headers=h).json()

    # ① 서버가 "사용됐다"고 주장하는 이름이 응답 어디에도 없다.
    assert "used_in_recommendation" not in created["item"]
    assert created["item"]["eligible_for_recommendation"] is True

    # ② 사용자가 그 값을 **처음 보는 자리**(POST 201)에서 조건을 함께 말한다.
    assert any("후보 조회 상한" in n for n in created["notes"]), created["notes"]

    listed = client.get("/api/v1/me/listings", headers=h).json()
    assert "used_in_recommendation" not in listed["summary"]
    assert listed["summary"]["eligible_for_recommendation"] == 1
    assert any("후보 조회 상한" in n for n in listed["notes"]), listed["notes"]


def test_반영_조건_고지는_낡은_호가가_없어도_나온다(client):
    """조건부로 붙이면 '전부 신선한' 흔한 상태에서 사라진다 — 그때가 바로 사용자가
    "다 넣었는데 왜 안 바뀌지"라고 묻는 상태다."""
    h = _login(client, "a@b.co")
    client.post("/api/v1/me/listings", json=_body(), headers=h)
    listed = client.get("/api/v1/me/listings", headers=h).json()

    assert listed["summary"]["stale"] == 0
    assert any("후보 조회 상한" in n for n in listed["notes"]), listed["notes"]

    # 호가가 하나도 없어도 고지는 남는다(빈 목록에서도 계약이 같다).
    h2 = _login(client, "b@b.co")
    empty = client.get("/api/v1/me/listings", headers=h2).json()
    assert empty["items"] == []
    assert any("후보 조회 상한" in n for n in empty["notes"]), empty["notes"]


# ---------------------------------------------------------------------------
# IDOR — 실측
# ---------------------------------------------------------------------------

def test_남의_호가는_목록에_안_보인다(client):
    a = _login(client, "a@b.co")
    b = _login(client, "b@b.co")
    client.post("/api/v1/me/listings", json=_body(), headers=a)

    assert client.get("/api/v1/me/listings", headers=b).json()["items"] == []
    assert len(client.get("/api/v1/me/listings", headers=a).json()["items"]) == 1


def test_남의_호가는_수정도_삭제도_안_되고_404다(client):
    """403 이 아니라 404 — '그 id 는 존재한다'는 사실조차 알려주지 않는다."""
    a = _login(client, "a@b.co")
    b = _login(client, "b@b.co")
    lid = client.post("/api/v1/me/listings", json=_body(), headers=a).json()["item"]["id"]

    mine_missing = client.patch("/api/v1/me/listings/999999",
                                json={"note": "x"}, headers=b)
    others = client.patch(f"/api/v1/me/listings/{lid}", json={"note": "x"}, headers=b)
    assert mine_missing.status_code == others.status_code == 404
    assert mine_missing.json() == others.json()      # 없는 것과 남의 것이 구분 불가

    assert client.delete(f"/api/v1/me/listings/{lid}", headers=b).status_code == 404
    # 남의 삭제 시도로 원본이 사라지지 않았다.
    assert len(client.get("/api/v1/me/listings", headers=a).json()["items"]) == 1


def test_분석_경로도_소유자별로_갈린다(client):
    """`listings_for_complex` 는 **주인 것만** 준다. 이게 추천의 입력이다."""
    a = _login(client, "a@b.co")
    b = _login(client, "b@b.co")
    client.post("/api/v1/me/listings", json=_body(), headers=a)
    client.post("/api/v1/me/listings",
                json=_body(ask_price_krw=1_200_000_000, floor=3), headers=b)

    repo = client.repo
    a_id = repo.get_user_by_email("a@b.co").id
    b_id = repo.get_user_by_email("b@b.co").id
    a_rows = repo.listings_for_complex(1, user_id=a_id)
    b_rows = repo.listings_for_complex(1, user_id=b_id)

    assert [r.ask_price_krw for r in a_rows] == [1_480_000_000]
    assert [r.ask_price_krw for r in b_rows] == [1_200_000_000]


def test_user_id_없이_부르면_사용자_입력이_하나도_안_나온다(client):
    """fail-closed. 배선을 잊었을 때 **남의 것이 새는 쪽**이 아니라 안 보이는 쪽으로 실패한다.

    조용한 결측은 사용자가 "내 매물이 왜 안 보이지"로 알아채지만,
    조용한 누출은 아무도 알아채지 못한다.
    """
    a = _login(client, "a@b.co")
    client.post("/api/v1/me/listings", json=_body(), headers=a)
    assert client.repo.listings_for_complex(1) == []


def test_지도의_매물수는_사용자_입력을_세지_않는다(client):
    """`active_listings` 는 소유자 필터가 없는 집계다 — 세면 A 의 입력이 B 에게 보인다.

    인메모리 구현은 수집 호가(`_listings`)만 세므로 구조적으로 0이다. PostGIS 는
    같은 규칙을 SQL(`li.created_by_user_id IS NULL`)로 강제한다(test_postgis_repo).
    """
    a = _login(client, "a@b.co")
    client.post("/api/v1/me/listings", json=_body(), headers=a)
    b = _login(client, "b@b.co")
    rows = client.get("/api/v1/map/complexes?bbox=127.0,37.4,127.1,37.6&zoom=15",
                      headers=b).json()["items"]
    assert all(row["active_listings"] == 0 for row in rows)


def test_인증없이는_아무것도_못_한다(client):
    for method, path in (("GET", "/api/v1/me/listings"),
                         ("POST", "/api/v1/me/listings"),
                         ("PATCH", "/api/v1/me/listings/1"),
                         ("DELETE", "/api/v1/me/listings/1")):
        r = client.request(method, path, json=_body())
        assert r.status_code == 401, f"{method} {path} 가 열려 있다"


# ---------------------------------------------------------------------------
# 리포지토리 계약 — 두 구현이 같은 규칙을 지켜야 테스트가 프로덕션을 대표한다
# ---------------------------------------------------------------------------

def test_모르는_필드로_수정하면_거절한다():
    """오타(`price_krw`)가 조용히 무시되면 사용자는 고쳤다고 믿는다."""
    repo = InMemoryRepository()
    repo.add_complex(ComplexSummary(id=1, name="A", lon=127.0, lat=37.5,
                                    region_code="1168010100"))
    rec = repo.add_user_listing(7, complex_id=1, ask_price_krw=1_000_000_000,
                                area_m2=84.0, as_of=TODAY)
    with pytest.raises(ValueError):
        repo.update_user_listing(rec.id, 7, price_krw=1)


def test_두_리포지토리가_같은_수정가능_필드를_갖는다():
    """한쪽만 넓으면 인메모리 테스트가 프로덕션을 대표하지 못한다."""
    from app.repositories.postgis import PostgisRepository
    assert set(InMemoryRepository._UPDATABLE) == set(
        PostgisRepository._UPDATABLE_COLUMNS)


def test_사용자_입력에는_listed_at_을_넣지_않는다():
    """`listed_at` 은 포털 등록일이다. 거기에 '내가 본 날'을 넣으면
    `dedup.trust_score` 가 "등록 N일 경과"로 감점하는데, 그건 매물이 안 팔린 기간이
    아니라 **사용자가 입력을 미룬 기간**이다."""
    repo = InMemoryRepository()
    repo.add_complex(ComplexSummary(id=1, name="A", lon=127.0, lat=37.5,
                                    region_code="1168010100"))
    repo.add_user_listing(7, complex_id=1, ask_price_krw=1_000_000_000,
                          area_m2=84.0, as_of=TODAY - dt.timedelta(days=40))
    row = repo.listings_for_complex(1, user_id=7)[0]
    assert row.listed_at is None
    assert row.collected_at == TODAY - dt.timedelta(days=40)
