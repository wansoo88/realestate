"""LLM-1 — "AI 추천"에 실제 LLM 이 붙는 경로.

배경
----
`AnthropicLLM` 은 진작 있었지만 라우터가 `llm=` 을 넘기지 않아 파이프라인은 **항상**
`None` 을 받았다. 그래서 사용자가 "AI 추천"을 눌러도 언제나 규칙 기반 요약이었고,
그 사실을 알 방법도 없었다.

이 파일이 못박는 것
-------------------
1. **SR4-2** — 이 배선으로 프롬프트가 처음으로 진짜 외부(api.anthropic.com)로 나간다.
   그래서 `httpx.stream` 을 가로채 **실제로 전송될 본문**을 열어 자산 원본이 없는지 본다.
   FakeLLM 으로 파이프라인만 보는 것과 다르다 — 여기서는 라우터→build_llm→
   AnthropicLLM→HTTP 까지 전 구간이 실제 코드다.
2. **폴백** — 타임아웃·429·5xx·스키마 위반이 추천 전체를 죽이지 않는다.
3. **비용** — 후보가 많아도 호출 수가 유한하고, 버려질 후보에는 돈을 쓰지 않는다.
4. **키** — 로그·응답·예외 어디에도 키가 나오지 않는다.
"""
from __future__ import annotations

import datetime as dt
import json
import logging
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app.agents.llm import (
    DEFAULT_MAX_TOKENS,
    MAX_OUTPUT_TOKENS,
    MAX_PROMPT_CHARS,
    AnthropicLLM,
    FakeLLM,
    LLMError,
    build_llm,
)
from app.agents.orchestrator import LLM_MAX_FAILURES, LLM_SUMMARY_LIMIT
from app.domain.valuation.models import ListingRow, TradeRow
from app.repositories.base import ComplexSummary
from app.repositories.memory import InMemoryRepository

FIXTURES = Path(__file__).parent / "fixtures"
PASSWORD = "correct horse battery staple"
REGION = "1168000000"
OKU = 100_000_000
TODAY = dt.date.today()

#: 테스트용 가짜 키. **실제 키를 여기 적지 않는다.**
FAKE_KEY = "sk-ant-test-0123456789abcdefghijklmnop"

GOOD_RESPONSE = {"headline": "요약", "why": ["근거"], "why_not": ["리스크"],
                 "next_actions": ["현장 확인"]}


# ---------------------------------------------------------------------------
# httpx 가로채기 — "실제로 나갈 본문"을 손에 넣는다
# ---------------------------------------------------------------------------

class _Resp:
    """`httpx.Response` 대역 — **스트리밍 모양**이다(SR25-1).

    `llm.py` 가 `httpx.post(...).json()` 에서 `httpx.stream(...)` + 상한 읽기로 바뀌었다.
    대역이 `.json()` 만 갖고 있으면 테스트는 사라진 경로를 검증하게 된다.
    """

    def __init__(self, status_code=200, payload=None, headers=None):
        self.status_code = status_code
        self._payload = payload if payload is not None else {
            "content": [{"type": "text", "text": json.dumps(GOOD_RESPONSE,
                                                            ensure_ascii=False)}]}
        self.headers = headers or {}

    def raise_for_status(self):
        return None                      # llm.py 는 상태코드를 직접 다룬다

    def _body(self) -> bytes:
        if isinstance(self._payload, (bytes, bytearray)):
            return bytes(self._payload)
        if isinstance(self._payload, str):
            return self._payload.encode("utf-8")
        return json.dumps(self._payload, ensure_ascii=False).encode("utf-8")

    def iter_bytes(self, chunk_size=None):
        yield self._body()

    def json(self):
        return self._payload


class _Ctx:
    """`with httpx.stream(...) as resp:` 를 흉내 내는 최소 컨텍스트."""

    def __init__(self, resp):
        self._resp = resp

    def __enter__(self):
        return self._resp

    def __exit__(self, *exc):
        return False


class Wire:
    """`httpx.stream` 대역. 나간 요청을 전부 기록한다."""

    def __init__(self, responses=None):
        self.requests: list[dict] = []
        self._responses = list(responses or [])

    def __call__(self, method, url, *, headers=None, json=None, timeout=None, **kw):
        self.requests.append({"url": url, "headers": headers or {},
                              "json": json or {}, "timeout": timeout,
                              "method": method})
        nxt = self._responses.pop(0) if self._responses else _Resp()
        if isinstance(nxt, Exception):
            raise nxt
        return _Ctx(nxt)

    # -- 검사 편의 --
    @property
    def prompts(self) -> list[str]:
        """실제 전송 본문에서 사용자 메시지만."""
        out = []
        for r in self.requests:
            for m in r["json"].get("messages", []):
                out.append(str(m.get("content", "")))
        return out

    def body_text(self) -> str:
        return json.dumps(self.requests, ensure_ascii=False, default=str)


@pytest.fixture()
def wire(monkeypatch):
    w = Wire()
    monkeypatch.setattr("httpx.stream", w)
    # 재시도 백오프로 테스트가 느려지지 않게.
    monkeypatch.setattr("app.agents.llm.time.sleep", lambda *_: None)
    return w


def _make_client(monkeypatch, *, api_key: str = ""):
    monkeypatch.setenv("JWT_SECRET", "x" * 40)
    monkeypatch.setenv("FIELD_ENCRYPTION_KEY", "k" * 32)
    monkeypatch.setenv("POSTGRES_PASSWORD", "pw")
    monkeypatch.setenv("TAX_RULES_PATH", str(FIXTURES / "tax_rules_test.yaml"))
    monkeypatch.setenv("ANTHROPIC_API_KEY", api_key)

    from app.core.config import get_settings
    get_settings.cache_clear()

    from app.main import create_app
    repo = InMemoryRepository()
    app = create_app(repo=repo)
    client = TestClient(app)
    client.repo = repo
    return client


@pytest.fixture()
def keyed_client(monkeypatch):
    """ANTHROPIC_API_KEY 가 **있는** 앱 — 실제 LLM 경로가 켜진다."""
    from app.core.config import get_settings
    with _make_client(monkeypatch, api_key=FAKE_KEY) as c:
        yield c
    get_settings.cache_clear()


@pytest.fixture()
def keyless_client(monkeypatch):
    """키가 **없는** 앱 — 규칙 기반으로 동작해야 한다."""
    from app.core.config import get_settings
    with _make_client(monkeypatch, api_key="") as c:
        yield c
    get_settings.cache_clear()


# ---------------------------------------------------------------------------
# 시드 · 실행 헬퍼
# ---------------------------------------------------------------------------

def _auth(token): return {"Authorization": f"Bearer {token}"}


def _login(client, email="a@b.co") -> str:
    client.post("/api/v1/auth/register", json={"email": email, "password": PASSWORD})
    user = client.repo.get_user_by_email(email)
    client.repo.set_user_status(user.id, "approved", actor="cli")
    return client.post("/api/v1/auth/login",
                       json={"email": email, "password": PASSWORD}).json()["access_token"]


CASH, INCOME = 312_400_000, 187_600_000


def _set_profile(client, token, cash=CASH, income=INCOME):
    r = client.put("/api/v1/me/profile", json={"cash_krw": cash, "income_krw": income},
                   headers=_auth(token))
    assert r.status_code == 200, r.text


def _seed(repo, *, complex_id=1, ask_oku=7.0, area=84.97):
    repo.add_complex(ComplexSummary(
        id=complex_id, name=f"단지{complex_id}", lon=127.05, lat=37.51,
        region_code=REGION, built_year=2015, total_households=500,
        recent_price_krw=int(ask_oku * OKU), price_as_of=TODAY.isoformat(),
        active_listings=2))
    repo.add_listings(complex_id, [
        ListingRow(id=complex_id * 10 + i, ask_price_krw=int(ask_oku * OKU),
                   area_m2=area, floor=10, listed_at=TODAY - dt.timedelta(days=10),
                   collected_at=TODAY, agency=f"중개{i}", status="active")
        for i in range(2)])
    repo.add_trades(complex_id, [
        TradeRow(contract_date=TODAY - dt.timedelta(days=15 * i),
                 price_krw=int(ask_oku * OKU), area_m2=area, floor=10)
        for i in range(8)])


def _run(client, token, body=None):
    r = client.post("/api/v1/recommendations", json=body or {}, headers=_auth(token))
    assert r.status_code == 202, r.text
    got = client.get(f"/api/v1/recommendations/{r.json()['job_id']}", headers=_auth(token))
    assert got.status_code == 200, got.text
    return got.json()


# ---------------------------------------------------------------------------
# 배선 — 키가 있으면 붙고, 없으면 규칙 기반
# ---------------------------------------------------------------------------

def test_키가_없으면_LLM을_만들지_않는다():
    assert build_llm(_Settings(api_key="")) is None
    assert build_llm(_Settings(api_key="   ")) is None


def test_키가_있으면_LLM을_만든다():
    llm = build_llm(_Settings(api_key=FAKE_KEY))
    assert isinstance(llm, AnthropicLLM)


def test_모델명이_비면_붙이지_않는다():
    """모델 없이 호출하면 매번 400 이다 — 붙은 척하느니 규칙 기반이 낫다."""
    assert build_llm(_Settings(api_key=FAKE_KEY, model="")) is None


class _Settings:
    def __init__(self, *, api_key="", model="claude-sonnet-5"):
        self.anthropic_api_key = api_key
        self.claude_model = model


def test_키가_있으면_추천이_실제로_LLM을_부른다(keyed_client, wire):
    """★ LLM-1 회귀: 라우터가 llm= 을 안 넘기면 이 테스트가 깨진다."""
    token = _login(keyed_client)
    _set_profile(keyed_client, token)
    _seed(keyed_client.repo)

    body = _run(keyed_client, token)

    assert body["items"], body
    assert wire.requests, "LLM 이 호출되지 않았다 — 라우터 배선이 끊겼다"
    assert wire.requests[0]["url"] == AnthropicLLM.ENDPOINT
    assert body["items"][0]["summary_basis"] == "llm"
    assert body["items"][0]["headline"] == "요약"


def test_키가_없으면_그_사실을_notes로_말한다(keyless_client, wire):
    """"AI 추천"을 눌렀는데 LLM 이 안 돌았다는 걸 사용자가 알 수 있어야 한다."""
    token = _login(keyless_client)
    _set_profile(keyless_client, token)
    _seed(keyless_client.repo)

    body = _run(keyless_client, token)

    assert body["items"], "키가 없다고 추천이 죽으면 안 된다"
    assert wire.requests == [], "키가 없는데 외부 호출이 나갔다"
    assert body["items"][0]["summary_basis"] == "fallback"
    note = [n for n in body["notes"] if "규칙 기반" in n]
    assert note, body["notes"]
    assert "AI 미연결" in note[0] or "ANTHROPIC_API_KEY" in note[0], note[0]
    # 순위·근거까지 의심하게 만들지는 않는다 — 무엇이 영향을 안 받는지도 말한다.
    assert "순위" in note[0]


def test_LLM이_붙으면_미연결_고지는_사라진다(keyed_client, wire):
    token = _login(keyed_client)
    _set_profile(keyed_client, token)
    _seed(keyed_client.repo)

    body = _run(keyed_client, token)
    assert not [n for n in body["notes"] if "AI 미연결" in n], body["notes"]


# ---------------------------------------------------------------------------
# ★ SR4-2 — 실제로 나가는 본문에 자산 원본이 없다
#
# 지금까지는 FakeLLM 이라 유출돼도 밖으로 안 갔다. 이 배선부터는 진짜 나간다.
# ---------------------------------------------------------------------------

def test_실제_전송본문에_자산_원본금액이_없다(keyed_client, wire):
    """★ 최대 보안 관심사. 전송 직전 HTTP 본문을 그대로 열어 검사한다."""
    from app.agents.base import extract_amounts

    token = _login(keyed_client)
    _set_profile(keyed_client, token, cash=CASH, income=INCOME)
    _seed(keyed_client.repo)

    _run(keyed_client, token)
    assert wire.requests, "호출이 없으면 이 테스트는 아무것도 증명하지 못한다"

    blob = wire.body_text()
    leaked = extract_amounts(blob) & {CASH, INCOME}
    assert not leaked, f"자산 원본이 외부로 나갔다: {leaked}"
    # 숫자 표기가 바뀌어도(콤마·억 단위) 잡히도록 원문 문자열도 함께 본다.
    for raw in (str(CASH), str(INCOME), f"{CASH:,}", f"{INCOME:,}"):
        assert raw not in blob, f"자산 원본 표기 {raw} 가 프롬프트에 있다"


def test_전송본문에_파생값은_있어도_된다(keyed_client, wire):
    """방어가 과해서 **아무 근거도 못 보내는** 상태가 아닌지 확인한다.

    한도·부대비용 같은 계산 결과는 사용자가 이미 /affordability 로 보는 값이라 허용이다.
    이게 없으면 요약이 근거 없는 문장이 되고, 그건 이 제품이 금지하는 것이다(G2).
    """
    token = _login(keyed_client)
    _set_profile(keyed_client, token)
    _seed(keyed_client.repo)
    _run(keyed_client, token)

    joined = "\n".join(wire.prompts)
    assert "실구매 가능" in joined or "한도" in joined, joined[:500]


def test_tripwire가_살아있다_원본이_섞이면_전송하지_않는다():
    """★ 2차 방어가 무장 해제되지 않았는지.

    누군가 "친절하게" finding 에 보유현금을 한 줄 넣으면 **호출 자체가 막혀야** 한다.
    폴백으로 흘려보내면 그 순간 유출이 정상 동작이 된다.
    """
    from app.agents.base import Evidence, Finding, PromptSafetyError
    from app.agents.orchestrator import portfolio_summary

    llm = FakeLLM(repeat=GOOD_RESPONSE)
    leaky = Finding(agent_id="finance-tax-advisor", verdict="v",
                    rationale=f"보유 현금 {CASH:,}원으로는 부족합니다",
                    evidence=[Evidence(claim="c", source="s")])

    with pytest.raises(PromptSafetyError):
        portfolio_summary([leaky], llm, [CASH, INCOME])
    assert llm.calls == [], "tripwire 가 걸렸는데 호출이 나갔다"


def test_tripwire는_비용상한보다_먼저_돈다():
    """예산이 없다는 이유로 검사를 건너뛰면, 상한에 걸린 날에만 방어가 사라진다."""
    from app.agents.base import Evidence, Finding, PromptSafetyError
    from app.agents.orchestrator import LLMBudget, portfolio_summary

    llm = FakeLLM(repeat=GOOD_RESPONSE)
    spent = LLMBudget(max_calls=0)              # 호출 슬롯이 하나도 없다
    leaky = Finding(agent_id="x", verdict="v",
                    rationale=f"보유 현금 {CASH:,}원",
                    evidence=[Evidence(claim="c", source="s")])

    with pytest.raises(PromptSafetyError):
        portfolio_summary([leaky], llm, [CASH], budget=spent)


def test_검사값이_비면_외부전송을_막는다():
    """fail-loud — 검사할 게 없어서 통과하는 조용한 no-op 을 만들지 않는다."""
    from app.agents.base import Evidence, Finding, PromptSafetyError
    from app.agents.orchestrator import portfolio_summary

    llm = FakeLLM(repeat=GOOD_RESPONSE)
    finding = Finding(agent_id="x", verdict="v", rationale="r",
                      evidence=[Evidence(claim="c", source="s")])
    with pytest.raises(PromptSafetyError):
        portfolio_summary([finding], llm, [])
    assert llm.calls == []


# ---------------------------------------------------------------------------
# 실패해도 추천은 산다
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("status_code", [429, 500, 502, 503])
def test_일시장애면_재시도하고_결국_규칙기반으로_떨어진다(keyed_client, monkeypatch,
                                                    status_code):
    w = Wire([_Resp(status_code), _Resp(status_code), _Resp(status_code)])
    monkeypatch.setattr("httpx.stream", w)
    monkeypatch.setattr("app.agents.llm.time.sleep", lambda *_: None)

    token = _login(keyed_client)
    _set_profile(keyed_client, token)
    _seed(keyed_client.repo)

    body = _run(keyed_client, token)

    assert body["status"] == "done"
    assert body["items"], "LLM 장애가 추천 전체를 죽였다"
    assert body["items"][0]["summary_basis"] == "fallback"
    assert body["items"][0]["why"], "폴백 요약에도 근거가 있어야 한다"
    assert len(w.requests) == 3, "재시도가 돌지 않았다"
    assert any("AI 요약 호출이 실패" in n for n in body["notes"]), body["notes"]


def test_인증오류는_재시도하지_않는다(keyed_client, monkeypatch):
    """키가 틀렸는데 3번 보내봐야 같은 답이다 — 사용자만 기다린다."""
    w = Wire([_Resp(401)])
    monkeypatch.setattr("httpx.stream", w)
    monkeypatch.setattr("app.agents.llm.time.sleep", lambda *_: None)

    token = _login(keyed_client)
    _set_profile(keyed_client, token)
    _seed(keyed_client.repo)

    body = _run(keyed_client, token)
    assert body["items"] and body["items"][0]["summary_basis"] == "fallback"
    assert len(w.requests) == 1, f"4xx 를 재시도했다: {len(w.requests)}회"


def test_네트워크_예외도_추천을_죽이지_않는다(keyed_client, monkeypatch):
    import httpx

    w = Wire([httpx.ConnectTimeout("timed out"), httpx.ConnectTimeout("timed out"),
              httpx.ConnectTimeout("timed out")])
    monkeypatch.setattr("httpx.stream", w)
    monkeypatch.setattr("app.agents.llm.time.sleep", lambda *_: None)

    token = _login(keyed_client)
    _set_profile(keyed_client, token)
    _seed(keyed_client.repo)

    body = _run(keyed_client, token)
    assert body["items"] and body["items"][0]["summary_basis"] == "fallback"


def test_스키마를_벗어난_응답은_폐기한다(keyed_client, monkeypatch):
    """`parse_json_object` 규약 유지 — 모양이 다르면 쓰지 않는다."""
    bad = _Resp(payload={"content": [{"type": "text", "text": '{"nonsense": true}'}]})
    w = Wire([bad, bad, bad])
    monkeypatch.setattr("httpx.stream", w)

    token = _login(keyed_client)
    _set_profile(keyed_client, token)
    _seed(keyed_client.repo)

    body = _run(keyed_client, token)
    assert body["items"][0]["summary_basis"] == "fallback"
    assert body["items"][0]["headline"] == "분석 요약(자동 생성)"


def test_JSON이_아닌_응답도_폐기한다(keyed_client, monkeypatch):
    w = Wire([_Resp(payload={"content": [{"type": "text", "text": "안녕하세요"}]})] * 3)
    monkeypatch.setattr("httpx.stream", w)

    token = _login(keyed_client)
    _set_profile(keyed_client, token)
    _seed(keyed_client.repo)
    assert _run(keyed_client, token)["items"][0]["summary_basis"] == "fallback"


def test_연속_실패하면_회로를_끊는다(keyed_client, monkeypatch):
    """장애는 보통 전면적이다 — 후보 수만큼 타임아웃을 곱하지 않는다."""
    w = Wire([_Resp(500)] * 50)
    monkeypatch.setattr("httpx.stream", w)
    monkeypatch.setattr("app.agents.llm.time.sleep", lambda *_: None)

    token = _login(keyed_client)
    _set_profile(keyed_client, token)
    for cid in range(1, 9):
        _seed(keyed_client.repo, complex_id=cid)

    body = _run(keyed_client, token)
    assert len(body["items"]) == 8
    # 후보 8건 × 재시도 3회 = 24회가 아니라, 실패 2건에서 멈춘다.
    assert len(w.requests) == LLM_MAX_FAILURES * 3, len(w.requests)
    assert all(i["summary_basis"] == "fallback" for i in body["items"])


# ---------------------------------------------------------------------------
# 비용 방어
# ---------------------------------------------------------------------------

def test_버려질_후보에는_LLM을_쓰지_않는다(keyed_client, wire):
    """★ 상위 N건을 보여주려고 후보 25건의 요약을 만들고 나머지를 버리지 않는다.

    ⚠️ `top_n` 을 **호출 상한(LLM_SUMMARY_LIMIT)보다 작게** 잡는다. 상한과 같으면
    "루프 안에서 다 만들다가 상한에 걸린 것"과 "필요한 만큼만 만든 것"이 같은
    호출 수로 보여서, 이 테스트가 아무것도 증명하지 못한다.
    """
    top_n = 3
    assert top_n < LLM_SUMMARY_LIMIT, "상한에 가려 회귀를 못 잡는다"

    token = _login(keyed_client)
    _set_profile(keyed_client, token)
    for cid in range(1, 26):
        _seed(keyed_client.repo, complex_id=cid, ask_oku=7.0 + cid * 0.01)

    body = _run(keyed_client, token, {"top_n": top_n})

    assert len(body["items"]) == top_n
    assert len(wire.requests) == top_n, (
        f"응답에 나가지도 않을 후보에 {len(wire.requests) - top_n}회를 더 태웠다")
    # 상한에도 안 걸렸다 = 순수하게 "필요한 만큼만" 부른 것이다.
    assert not [n for n in body["notes"] if "비용 상한" in n], body["notes"]


def test_top_n이_커도_호출_상한을_넘지_않는다(keyed_client, wire):
    token = _login(keyed_client)
    _set_profile(keyed_client, token)
    for cid in range(1, 26):
        _seed(keyed_client.repo, complex_id=cid, ask_oku=7.0 + cid * 0.01)

    body = _run(keyed_client, token, {"top_n": 25})

    assert len(body["items"]) == 25
    assert len(wire.requests) == LLM_SUMMARY_LIMIT
    assert any("비용 상한" in n for n in body["notes"]), body["notes"]
    # 상한 밖 후보도 요약은 받는다(규칙 기반) — 빈 카드를 내보내지 않는다.
    assert all(i["headline"] for i in body["items"])
    assert sum(1 for i in body["items"] if i["summary_basis"] == "llm") == LLM_SUMMARY_LIMIT


def test_내부용_임시키가_응답에_새지_않는다(keyed_client, wire):
    """요약을 2패스로 미루면서 Finding 객체를 아이템에 실어 나른다.

    이 키가 남으면 `recommendation_item.payload` 에 dataclass 가 문자열로 굳어
    저장되고(json.dumps default=str), 응답이 통째로 부풀며 프론트는 정체불명의
    필드를 보게 된다. 반드시 지워져야 한다.
    """
    from app.agents.orchestrator import _SUMMARY_INPUT_KEY

    token = _login(keyed_client)
    _set_profile(keyed_client, token)
    for cid in range(1, 6):
        _seed(keyed_client.repo, complex_id=cid, ask_oku=7.0 + cid * 0.01)

    body = _run(keyed_client, token, {"top_n": 2})
    assert _SUMMARY_INPUT_KEY not in json.dumps(body, ensure_ascii=False, default=str)
    assert all(_SUMMARY_INPUT_KEY not in i for i in body["items"])


def test_출력토큰_상한을_넘겨_보내지_않는다(keyed_client, wire):
    token = _login(keyed_client)
    _set_profile(keyed_client, token)
    _seed(keyed_client.repo)
    _run(keyed_client, token)

    sent = wire.requests[0]["json"]["max_tokens"]
    assert sent == DEFAULT_MAX_TOKENS
    assert sent <= MAX_OUTPUT_TOKENS


def test_호출부가_상한을_올리려_해도_막는다(wire):
    AnthropicLLM(FAKE_KEY, "m").complete_json(system="s", user="u",
                                              max_tokens=999_999)
    assert wire.requests[0]["json"]["max_tokens"] == MAX_OUTPUT_TOKENS


def test_프롬프트가_너무_길면_보내지_않고_폴백한다():
    """자르지 않는다 — 근거 일부만 보고 쓴 요약은 근거와 어긋난다(G2)."""
    from app.agents.base import Evidence, Finding
    from app.agents.orchestrator import LLMBudget, portfolio_summary

    llm = FakeLLM(repeat=GOOD_RESPONSE)
    huge = Finding(agent_id="x", verdict="v", rationale="가" * (MAX_PROMPT_CHARS + 100),
                   evidence=[Evidence(claim="c", source="s")])
    budget = LLMBudget()

    out = portfolio_summary([huge], llm, [CASH], budget=budget)
    assert out["generated_by"] == "fallback"
    assert llm.calls == [], "상한을 넘었는데 호출이 나갔다"
    assert budget.oversized == 1


def test_클라이언트도_긴_프롬프트를_거절한다(wire):
    """호출부가 예산을 안 넘겨도 마지막 문에서 막힌다."""
    with pytest.raises(LLMError):
        AnthropicLLM(FAKE_KEY, "m").complete_json(system="s",
                                                  user="가" * (MAX_PROMPT_CHARS + 1))
    assert wire.requests == []


# ---------------------------------------------------------------------------
# 키가 새지 않는다
# ---------------------------------------------------------------------------

def test_키는_헤더에만_있고_본문에는_없다(keyed_client, wire):
    token = _login(keyed_client)
    _set_profile(keyed_client, token)
    _seed(keyed_client.repo)
    _run(keyed_client, token)

    req = wire.requests[0]
    assert req["headers"]["x-api-key"] == FAKE_KEY      # 여기 말고는 없어야 한다
    assert FAKE_KEY not in json.dumps(req["json"], ensure_ascii=False)


def test_응답에_키가_없다(keyed_client, wire):
    token = _login(keyed_client)
    _set_profile(keyed_client, token)
    _seed(keyed_client.repo)
    body = _run(keyed_client, token)
    assert FAKE_KEY not in json.dumps(body, ensure_ascii=False)


def test_예외메시지에_키와_응답본문이_없다(monkeypatch):
    """4xx 본문에는 프롬프트가 되비쳐 나올 수 있다 — 상태코드만 남긴다."""
    secret_body = {"error": {"message": f"key {FAKE_KEY} rejected; prompt: 보유현금"}}
    monkeypatch.setattr("httpx.stream", Wire([_Resp(403, payload=secret_body)]))

    with pytest.raises(LLMError) as exc:
        AnthropicLLM(FAKE_KEY, "m").complete_json(system="s", user="u")
    text = str(exc.value)
    assert FAKE_KEY not in text and "보유현금" not in text
    assert "403" in text


def test_repr에_키가_없다():
    llm = AnthropicLLM(FAKE_KEY, "claude-sonnet-5")
    assert FAKE_KEY not in repr(llm) and FAKE_KEY not in str(llm)


def test_로그에_키가_남지_않는다(monkeypatch, caplog):
    """`build_llm` 은 '있다/없다와 모델명'만 남긴다."""
    from app.core.masking import install_log_masking

    install_log_masking()
    monkeypatch.setenv("ANTHROPIC_API_KEY", FAKE_KEY)
    with caplog.at_level(logging.DEBUG):
        build_llm(_Settings(api_key=FAKE_KEY))
    assert FAKE_KEY not in caplog.text
    assert "claude-sonnet-5" in caplog.text


def test_마스킹_대상에_키가_등록돼_있다():
    """혹시 어딘가로 새더라도 로그·예외 경로에서 지워지도록."""
    from app.core.masking import SECRET_ENV_VARS, mask_secrets

    assert "ANTHROPIC_API_KEY" in SECRET_ENV_VARS
    assert FAKE_KEY not in mask_secrets(f"보낸 값: {FAKE_KEY}",
                                        extra_secrets=[FAKE_KEY])
