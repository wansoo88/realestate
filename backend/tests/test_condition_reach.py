"""내 조건이 추천까지 **도달하는지**를 지키는 회귀 테스트 (ORDER 2026-07-27).

왜 이 파일이 따로 있나 — 같은 계열의 결함이 세 번 났다
--------------------------------------------------------
① `budget_override_krw` 가 후보 *조회*에만 닿고 *제외 판정*에는 닿지 않았다.
② `weights` 가 저장만 되고 순위에 쓰이지 않았다.
③ **평수가 요청 스키마에 아예 없어** 지도는 거르는데 추천은 안 걸렀다(사용자 제보).

셋 다 계산이 틀린 게 아니라 **배선이 없었다.** 그래서 개별 수정으로 끝내지 않고
"조건이 도달하지 못하면 테스트가 실패하는 구조"를 만든다:

* **구조 검사** — 화면(`frontend/src/api/client.ts` 의 `Preferences`)이 수집하는 조건은
  전부 서버 레지스트리(`app/domain/conditions.py`)에 있어야 한다. 새 조건을 UI 에
  추가하고 서버 배선을 잊으면 **여기서 먼저 넘어진다.**
* **행동 증명** — 레지스트리가 "반영된다"고 주장하는 조건은 각각 **켠 경우와 끈 경우의
  결과가 실제로 달라지는지**를 API 전 구간(POST → BackgroundTask → GET)에서 보인다.
  필드가 존재한다는 assert 는 아무것도 증명하지 못한다(그건 ③번 버그도 통과시킨다).
* **계약 검사** — 결과 목록의 **모든 항목이 조건을 만족**하는지 본다. "대체로 맞다"는
  이 제품에서 실패다.

변이(mutation)로 검증된 것들 — 아래 중 하나라도 되돌리면 이 파일이 빨개진다:
  · 후보 조립의 **실거래** 분기 면적 판정을 지우면 → test_증명[area_filters_candidates]
  · 후보 조립의 **호가** 분기 면적 판정을 지우면   → test_증명[area_filters_candidates]
  · `FilterConditions.area_ok` 의 미상 처리를 통과로 뒤집으면 → 같은 증명
  · 리포지토리 SQL 의 면적 절만 지우면    → (인메모리에서는 안 잡히므로) 조립 판정이 잡는다
  · `_avoid_tokens` 의 꺼진 값 무시를 지우면 → test_증명[avoid_excludes_and_off_restores]
  · 후보 조립에서 repo 의 정비사업 판정을 안 싣거나(`_build(redevelopment=None)`),
    `build_axis_signals` 의 재건축 축 신호를 죽이거나, `normalize_weights` 가 **명시한 0**
    을 무시하고 기본 15% 를 덮어쓰거나, 목적(purpose)이 `assess_redevelopment` 에
    닿지 않으면 → test_증명[weights_change_order_redevelopment] (4종 실측 확인)

⚠️ 호가 경로를 일부러 태운다 (CR-029 차단 2, 2026-07-27)
--------------------------------------------------------
예전 이 파일은 모든 시드가 `listings=()` 라 **실거래 분기만** 탔다. 그래서 위 두 줄의
주장이 거짓이었다 — 호가 분기의 면적 판정을 통째로 지워도 전부 초록이었고,
`area_ok` 의 미상 처리를 뒤집어도 초록이었다(인메모리 리포지토리가 단지 단위에서
먼저 걸러 도메인 가드가 판정에 관여하지 않았다).
지금은 **한 단지 안에 조건에 맞는 호가와 맞지 않는 호가를 함께** 심는다. 그래야
단지가 리포지토리 필터를 통과하고, 그 다음 문인 조립 단계의 가드가 실제로 판정한다.
운영에 포털 호가가 붙으면 이 분기가 **주 경로**가 된다.
"""
from __future__ import annotations

import datetime as dt
import inspect
import re
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app.api.schemas import RecommendationIn
from app.domain.conditions import (
    APPLIED_EFFECTS,
    EFFECT_CANDIDATE_FILTER,
    EFFECT_NOT_APPLIED,
    GROUP_AVOID,
    GROUP_PREFER,
    GROUP_WEIGHT,
    REGISTRY,
    FilterConditions,
    filter_specs,
    resolve_filter_conditions,
    spec_keys,
)
from app.domain.location.models import HazardFact, LocationFacts, StationFact
from app.domain.redevelopment.models import RedevProject
from app.domain.redevelopment.stages import (
    KIND_REBUILD,
    STAGE_COMPLETED,
    STAGE_IMPLEMENTATION,
)
from app.domain.valuation.models import ListingRow, TradeRow
from app.repositories.base import ComplexSummary
from app.repositories.memory import InMemoryRepository

FIXTURES = Path(__file__).parent / "fixtures"
REPO_ROOT = Path(__file__).resolve().parents[2]
PASSWORD = "correct horse battery staple"
REGION = "1168000000"
OTHER_REGION = "4117300000"
OKU = 100_000_000
TODAY = dt.date.today()


# ---------------------------------------------------------------------------
# 공통 — API 전 구간을 태운다(인메모리 repo · BackgroundTask 동기 실행)
# ---------------------------------------------------------------------------

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
    r = client.post("/api/v1/auth/register", json={"email": email, "password": PASSWORD})
    assert r.status_code == 201, r.text
    user = client.repo.get_user_by_email(email)
    client.repo.set_user_status(user.id, "approved", actor="cli")
    return client.post("/api/v1/auth/login",
                       json={"email": email, "password": PASSWORD}).json()["access_token"]


def _ready(client, *, cash=1_200_000_000, income=310_000_000) -> str:
    """로그인 + 자산 입력까지. 예산이 후보를 자르지 않도록 넉넉히 둔다 —
    조건 하나만 움직여 결과를 비교하려면 나머지는 고정돼 있어야 한다."""
    token = _login(client)
    r = client.put("/api/v1/me/profile",
                   json={"cash_krw": cash, "income_krw": income}, headers=_auth(token))
    assert r.status_code == 200, r.text
    return token


def _prefs(client, token, *, prefer=None, avoid=None, weights=None) -> None:
    r = client.put("/api/v1/me/preferences",
                   json={"prefer": prefer or {}, "avoid": avoid or {},
                         "weights": weights or {}},
                   headers=_auth(token))
    assert r.status_code == 200, r.text


def _run(client, token, body) -> dict:
    r = client.post("/api/v1/recommendations", json=body, headers=_auth(token))
    assert r.status_code == 202, r.text
    got = client.get(f"/api/v1/recommendations/{r.json()['job_id']}", headers=_auth(token))
    assert got.status_code == 200, got.text
    return got.json()


def _names(body) -> set[str]:
    return {it["complex"]["name"] for it in body["items"]}


def _areas(body) -> list[float]:
    return [it["unit_type"]["area_m2"] for it in body["items"]]


def _seed(repo, *, complex_id, name, areas=(84.97,), price_oku=7.0, built_year=2015,
          households=800, region=REGION, lon=127.05, lat=37.51, n=8,
          listings=(), listed_days_ago=5):
    """단지 하나 + (기본) 실거래만. 운영 DB 의 실제 모습이 호가 0건이다.

    `areas` 를 여러 개 주면 **한 단지 안에 여러 면적대**가 생긴다 — 단지 단위로만
    거르는 구현(쿼리만 고치고 조립을 안 고친 경우)을 잡기 위한 장치다.
    """
    repo.add_complex(ComplexSummary(
        id=complex_id, name=name, lon=lon, lat=lat, region_code=region,
        built_year=built_year, total_households=households,
        recent_price_krw=int(price_oku * OKU), price_as_of=TODAY.isoformat(),
        active_listings=len(listings)))
    trades = []
    for area in areas:
        trades += [TradeRow(contract_date=TODAY - dt.timedelta(days=15 * i),
                            price_krw=int(price_oku * OKU), area_m2=area, floor=10)
                   for i in range(n)]
    repo.add_trades(complex_id, trades)
    if listings:
        repo.add_listings(complex_id, [
            ListingRow(id=complex_id * 10 + i, ask_price_krw=int(ask_oku * OKU),
                       area_m2=area, floor=10,
                       listed_at=TODAY - dt.timedelta(days=listed_days_ago),
                       collected_at=TODAY, agency=f"중개{i}", status="active")
            for i, (ask_oku, area) in enumerate(listings)])


# ===========================================================================
# Part 1 — 구조: 화면 ↔ 레지스트리 ↔ 요청 스키마 ↔ 리포지토리
# ===========================================================================

_CLIENT_TS = REPO_ROOT / "frontend" / "src" / "api" / "client.ts"
_BLOCK_COMMENT = re.compile(r"/\*.*?\*/", re.S)
_LINE_COMMENT = re.compile(r"//[^\n]*")
_KEY = re.compile(r"([A-Za-z_]\w*)\s*\??\s*:")


def _strip_comments(text: str) -> str:
    return _LINE_COMMENT.sub("", _BLOCK_COMMENT.sub("", text))


def _block(text: str, start: int) -> str:
    """`text[start]` 부터 시작하는 `{...}` 블록 본문(중첩 포함)."""
    depth = 0
    for i in range(start, len(text)):
        if text[i] == "{":
            depth += 1
            if depth == 1:
                begin = i + 1
        elif text[i] == "}":
            depth -= 1
            if depth == 0:
                return text[begin:i]
    raise AssertionError("닫히지 않은 블록")


def _ui_condition_keys() -> dict[str, set[str]]:
    """"내 조건" 화면이 수집하는 키 — **프론트 타입이 정본**이다.

    서버 테스트가 프론트 파일을 읽는 것은 의도적이다. 이 목록은 두 곳에 있으면
    반드시 어긋나고, 어긋나는 순간 "화면에는 있는데 서버는 모르는 조건"이 생긴다 —
    이번 사고(평수)가 정확히 그것이다.
    """
    assert _CLIENT_TS.exists(), (
        f"프론트 계약 파일을 찾지 못했습니다: {_CLIENT_TS}. "
        "이 테스트는 '화면이 수집하는 조건'을 그 파일에서 읽습니다 — "
        "경로가 바뀌었다면 이 상수를 고치세요(검사를 지우지 마세요).")
    text = _strip_comments(_CLIENT_TS.read_text(encoding="utf-8"))
    idx = text.index("export interface Preferences")
    body = _block(text, idx)
    out: dict[str, set[str]] = {}
    for group in ("prefer", "avoid", "weights"):
        pos = body.index(f"{group}:")
        out[group] = set(_KEY.findall(_block(body, pos)))
    return out


def test_UI가_수집하는_조건은_모두_서버_레지스트리에_있다():
    """★ 핵심 구조 검사: 새 조건을 화면에 추가하고 서버 배선을 잊으면 여기서 걸린다.

    하드코딩된 필드 나열이 아니라 **프론트 타입에서 끌어온다** — 손으로 적은 목록은
    다음 항목이 추가될 때 또 뚫린다.
    """
    ui = _ui_condition_keys()
    for group, keys in (("prefer", GROUP_PREFER), ("avoid", GROUP_AVOID),
                        ("weights", GROUP_WEIGHT)):
        missing = ui[group] - spec_keys(keys)
        assert not missing, (
            f"화면(Preferences.{group})에는 있는데 서버 조건 레지스트리에 없는 항목: "
            f"{sorted(missing)}. app/domain/conditions.py 의 REGISTRY 에 추가하고, "
            f"추천에 반영하든지(effect + proof) 반영하지 않는다고 명시하세요"
            f"(effect=not_applied + gap_note). **조용히 무시하는 선택지는 없습니다.**")
        stale = spec_keys(keys) - ui[group]
        assert not stale, (
            f"레지스트리에만 있고 화면에는 없는 항목: {sorted(stale)} — "
            "화면에서 지웠다면 레지스트리에서도 지우세요(죽은 조건이 남습니다).")


def test_반영된다고_주장하는_조건에는_증명이_있다():
    """"결과를 바꾼다"는 주장에는 **행동 증명**이 따라야 한다.

    proof 이름만 적고 시나리오를 안 쓰면 여기서 실패한다 — 주장만 남는 것을 막는다.
    """
    for spec in REGISTRY:
        if spec.effect in APPLIED_EFFECTS:
            assert spec.proof, f"{spec.key}: effect={spec.effect} 인데 proof 가 없습니다"
            assert spec.proof in PROOFS, (
                f"{spec.key}: proof={spec.proof!r} 시나리오가 이 파일에 없습니다. "
                "조건이 결과를 실제로 바꾸는지 켠/끈 비교로 증명하세요.")
        else:
            assert spec.effect == EFFECT_NOT_APPLIED
            assert spec.gap_note, (
                f"{spec.key}: 반영하지 않는 조건은 **사용자에게 말해야** 합니다"
                "(gap_note). 화면에 스위치가 있는데 아무 일도 안 일어나는 상태가 "
                "가장 나쁩니다.")


def test_후보선별_조건은_요청_스키마에_존재한다():
    """★ 이번 버그(③)의 직접 회귀: 평수가 `RecommendationIn` 에 아예 없었다."""
    fields = RecommendationIn.model_fields
    for spec in filter_specs():
        assert spec.request_field, f"{spec.key}: 후보 선별 조건인데 요청 필드가 없습니다"
        assert spec.request_field in fields, (
            f"{spec.key}: `RecommendationIn.{spec.request_field}` 가 없습니다 — "
            "요청에 실리지 않는 조건은 추천에 도달할 수 없습니다.")


def test_후보선별_조건은_FilterConditions_에_자리가_있다():
    """레지스트리에 조건을 추가하고 해석기를 안 고치면 값이 갈 곳이 없다."""
    conditions = FilterConditions()
    for spec in filter_specs():
        assert hasattr(conditions, spec.key), (
            f"{spec.key}: FilterConditions 에 필드가 없습니다 — "
            "resolve_filter_conditions 가 값을 읽어도 버려집니다.")


def test_리포지토리_두_구현_모두_조건_인자를_받는다():
    """인메모리만 받으면 테스트는 초록불인데 프로덕션에서만 조건이 사라진다."""
    from app.repositories.postgis import PostgisRepository

    expected = set(FilterConditions(area_min_m2=1.0, area_max_m2=2.0, built_after=2000,
                                    min_households=1).repo_kwargs())
    for impl in (InMemoryRepository, PostgisRepository):
        for method in ("recommendation_candidates", "candidate_scope_stats"):
            params = set(inspect.signature(getattr(impl, method)).parameters)
            assert expected <= params, (
                f"{impl.__name__}.{method} 가 조건 인자를 받지 않습니다: "
                f"{sorted(expected - params)}")


def test_리포지토리_조회_자체가_조건으로_좁혀진다():
    """조회 단계에서도 좁혀야 한다 — **조회 상한(50개 단지) 때문이다.**

    후보 조립이 계약을 지키므로 여기서 안 걸러도 "틀린 결과"는 안 나온다. 대신 훨씬
    나쁜 일이 난다: 상한이 조건과 무관한 단지로 다 차서 **맞는 후보가 0건**이 되고,
    사용자는 "내 조건에 맞는 집이 없다"로 읽는다(실측: 강남 506개 중 조건 충족은 96개).
    그래서 조회 자체를 검사한다 — 이 판정이 사라지면 여기서 잡힌다.
    (PostGIS 쪽 같은 판정은 `tests/test_postgis_repo.py` 의 needs_db 테스트가 잡는다.)
    """
    repo = InMemoryRepository()
    _seed(repo, complex_id=1, name="소형단지", areas=(59.9,), built_year=2015,
          households=1500)
    _seed(repo, complex_id=2, name="대형단지", areas=(84.97,), built_year=1990,
          households=300)

    def ids(**kw):
        return {c.id for c in repo.recommendation_candidates(region_codes=[], **kw)}

    assert ids() == {1, 2}
    assert ids(area_min_m2=55, area_max_m2=62) == {1}
    assert ids(built_after=2000) == {1}
    assert ids(min_households=1000) == {1}

    stats = repo.candidate_scope_stats(region_codes=[], area_min_m2=55, area_max_m2=62)
    assert stats == {"scope_total": 2, "area_dropped": 1, "built_dropped": 0,
                     "built_unknown": 0, "households_dropped": 0,
                     "households_unknown": 0}


# ---------------------------------------------------------------------------
# ★ SR24-4 — 범위 통계 조회는 **서버측 상한** 아래에서 돈다
#
# `candidate_scope_stats` 는 `complex` 를 LIMIT 없이 훑으며 행마다 EXISTS 3개를 돈다.
# 방아쇠는 공격이 아니라 평범한 사용이다(`area_min_m2=1` + 지역 "11" = 서울 전역).
# 배포하면 이 쿼리가 **처음으로** 61만 행짜리 실데이터에 닿는다.
# ---------------------------------------------------------------------------

def test_DB_엔진에_서버측_statement_timeout_이_걸린다(monkeypatch):
    """★ 변이 대상: `create_db_engine` 의 `connect_args`.

    클라이언트 타임아웃은 **서버 쿼리를 멈추지 못한다** — 연결을 끊어도 PostgreSQL 은
    계속 돈다. 그래서 상한은 세션 설정(libpq `options`)으로 들어가야 하고,
    커넥션마다 자동으로 붙어야 한다(애플리케이션이 기억하는 방식이면 언젠가 빠진다).
    """
    import sqlalchemy

    from app.repositories import postgis

    captured: dict = {}

    def fake_create_engine(url, **kw):
        captured.update(kw)
        captured["url"] = url
        return object()

    monkeypatch.setattr(sqlalchemy, "create_engine", fake_create_engine)

    class _S:
        database_url = "postgresql+psycopg://u:p@h:5432/db"

    postgis.create_db_engine(_S())
    options = str(captured.get("connect_args", {}).get("options", ""))
    assert "statement_timeout" in options, captured
    # 값은 밀리초다. 0 이거나 터무니없이 크면 상한이 없는 것과 같다.
    ms = int(re.search(r"statement_timeout=(\d+)", options).group(1))
    assert 0 < ms <= 30_000, ms
    assert captured.get("pool_pre_ping") is True     # 기존 보장이 사라지지 않았다


def test_통계_조회가_실패하면_그_사실을_사용자에게_말한다():
    """★ 변이 대상: `_scope_condition_notes` 의 except 분기.

    타임아웃(또는 어떤 실패든)에 예외를 삼키고 빈 목록을 돌려주면, 화면에서 고지가
    **그냥 사라진다** — 사용자는 "조건으로 빠진 단지가 없다"로 읽는다.
    실패는 결과를 죽이지 않되 **보여야** 한다.
    """
    from app.agents.recommend import _SCOPE_STATS_FAILED_NOTE, _scope_condition_notes

    class _Boom:
        def candidate_scope_stats(self, **kw):
            raise RuntimeError("canceling statement due to statement timeout")

    conditions = resolve_filter_conditions({"area_min_m2": 1}, {})
    notes = _scope_condition_notes(_Boom(), [REGION], None, conditions)
    assert notes == [_SCOPE_STATS_FAILED_NOTE]
    # 조건이 아예 없으면 셀 것도 없으므로 말하지 않는다(잡음 방지).
    assert _scope_condition_notes(_Boom(), [REGION], None,
                                  resolve_filter_conditions({}, {})) == []


def test_저장된_조건과_요청_조건은_요청이_이긴다():
    """"이번만 다르게"가 가능해야 하고, 안 보내면 저장된 내 조건이 살아야 한다."""
    saved = {"area_min_m2": 59, "area_max_m2": 85, "built_after": 2000}
    assert resolve_filter_conditions({}, saved).area_min_m2 == 59
    assert resolve_filter_conditions({"area_min_m2": 30}, saved).area_min_m2 == 30
    # 저장된 값이 없어도 요청만으로 성립한다.
    assert resolve_filter_conditions({"area_max_m2": 60}, {}).area_max_m2 == 60


def test_저장된_조건을_이번만_끌_수_있다(client):
    """조건을 **끄는 방법**이 있어야 한다.

    폴백만 있으면 화면에서 면적 칩을 껐는데 추천은 계속 걸러진다 — 이번 사고의
    거울상(끈 조건이 계속 켜져 있는 상태)이다. `null` 은 "안 보냄"과 같아서
    값으로는 '조건 없음'을 표현할 수 없으므로 스위치를 둔다.
    """
    token = _ready(client)
    _seed(client.repo, complex_id=1, name="소형단지", areas=(59.9,))
    _seed(client.repo, complex_id=2, name="대형단지", areas=(84.97,))
    _prefs(client, token, prefer={"area_min_m2": 55, "area_max_m2": 62})

    assert _names(_run(client, token, {"region_codes": [REGION]})) == {"소형단지"}
    off = _run(client, token, {"region_codes": [REGION],
                               "use_saved_conditions": False})
    assert _names(off) == {"소형단지", "대형단지"}
    # 끄면 조건 고지도 사라져야 한다(적용하지 않은 조건을 적용했다고 말하지 않는다).
    assert not any("내 조건을 적용했습니다" in n for n in off["notes"]), off["notes"]


def test_뒤집힌_면적조건은_조용히_무시되지_않는다():
    """min > max 는 뒤집지도, 없던 일로 하지도 않는다 — 사유를 남긴다."""
    got = resolve_filter_conditions({}, {"area_min_m2": 85, "area_max_m2": 59})
    assert got.area_min_m2 is None and got.area_max_m2 is None
    assert got.problems and "최소값이 최대값보다" in got.problems[0]


@pytest.mark.parametrize("path,params", [
    ("/api/v1/map/complexes", {"bbox": "127.0,37.4,127.1,37.6", "zoom": 14,
                               "area_min_m2": 85, "area_max_m2": 59}),
])
def test_지도도_뒤집힌_면적조건을_400으로_거절한다(client, path, params):
    token = _ready(client)
    r = client.get(path, params=params, headers=_auth(token))
    assert r.status_code == 400, r.text


def test_추천도_뒤집힌_면적조건을_400으로_거절한다(client):
    token = _ready(client)
    r = client.post("/api/v1/recommendations",
                    json={"area_min_m2": 85, "area_max_m2": 59}, headers=_auth(token))
    assert r.status_code == 400, r.text


@pytest.mark.parametrize("bad", [{"area_min_m2": 0}, {"area_max_m2": -1},
                                 {"built_after": 1800}, {"min_households": -5}])
def test_말이_안_되는_조건값은_422(client, bad):
    """0㎡·음수는 존재하지 않는 값이다. 조용히 계산하지 않는다(지도와 같은 규칙)."""
    token = _ready(client)
    r = client.post("/api/v1/recommendations", json=bad, headers=_auth(token))
    assert r.status_code == 422, r.text


# --- ★ SR24-6 회귀: 무한대가 조건을 조용히 지우던 자리 ----------------------
#
# `Infinity` 는 `gt=0` 을 **통과한다**(inf > 0). 통과하면 `_positive_number` 가 뒤에서
# `None` 으로 만들어 조건이 사라지는데, 사용자에게는 조건이 걸린 결과처럼 보였다.
# `NaN`·`-Infinity` 는 이미 422 였으므로 **규칙을 하나로 맞춘다.**
# ⚠️ JSON 표준에는 Infinity 가 없지만 파이썬 `json.loads` 는 그 리터럴을 받아들인다 —
#    그래서 이 값은 실제로 서버까지 도달한다(이론적 입력이 아니다).

@pytest.mark.parametrize("field", ["area_min_m2", "area_max_m2"])
@pytest.mark.parametrize("literal", ["Infinity", "-Infinity", "NaN"])
def test_무한대와_NaN_면적조건은_422로_거절한다(client, field, literal):
    token = _ready(client)
    r = client.post("/api/v1/recommendations",
                    content=f'{{"{field}": {literal}}}',
                    headers={**_auth(token), "Content-Type": "application/json"})
    assert r.status_code == 422, r.text


@pytest.mark.parametrize("literal", ["Infinity", "-Infinity", "NaN"])
def test_지도도_무한대_면적조건을_422로_거절한다(client, literal):
    """지도와 추천이 같은 값을 다르게 판정하면 두 화면이 서로 다른 말을 한다."""
    token = _ready(client)
    r = client.get("/api/v1/map/complexes",
                   params={"bbox": "127.0,37.4,127.1,37.6", "zoom": 14,
                           "area_min_m2": literal},
                   headers=_auth(token))
    assert r.status_code == 422, r.text


def test_저장된_조건의_무한대는_조용히_사라지지_않고_고지된다():
    """★ 저장된 내 조건은 `RecommendationIn` 검증을 **거치지 않는다**(dict[str, Any]).

    그래서 API 의 422 만으로는 이 경로가 닫히지 않는다. 도메인이 값을 버릴 때는
    반드시 `problems` 로 말한다 — `conditions.py` 가 존재하는 이유가 그것이다.
    """
    got = resolve_filter_conditions({}, {"area_min_m2": float("inf")})
    assert got.area_min_m2 is None
    assert got.problems, "면적 조건이 사라졌는데 아무 고지도 없다"
    assert "전용면적 최소" in got.problems[0], got.problems

    # NaN·0·문자열도 같은 규칙이다.
    for bad in (float("nan"), 0, -3, "많이"):
        out = resolve_filter_conditions({"area_max_m2": bad}, {})
        assert out.area_max_m2 is None
        assert out.problems, f"{bad!r} 이 조용히 사라졌다"

    # 정상값에는 아무 말도 하지 않는다(늘 뜨는 고지는 읽히지 않는다).
    assert resolve_filter_conditions({"area_max_m2": 84}, {}).problems == ()


def test_고지된_조건_문제는_추천_notes_까지_도달한다(client):
    """`problems` 를 만들어 놓고 응답에 싣지 않으면 아무것도 고친 게 아니다."""
    token = _ready(client)
    _seed(client.repo, complex_id=1, name="단지", areas=(84.97,))
    # 저장된 조건에 Infinity 를 직접 넣는다(화면 → PUT /me/preferences 경로는
    # dict[str, Any] 라 이 값이 통과한다).
    client.repo.set_preferences(
        client.repo.get_user_by_email("a@b.co").id,
        {"prefer": {"area_min_m2": float("inf")}, "avoid": {}, "weights": {}})

    body = _run(client, token, {"region_codes": [REGION]})
    assert any("전용면적 최소" in n for n in body["notes"]), body["notes"]


# ===========================================================================
# Part 2 — 행동 증명: 조건을 켜고 끄면 결과가 **달라지는가**
#
# ⚠️ 각 증명은 "조건 없이 돌린 결과"를 기준선으로 삼는다. 상수와 비교하면
#    기준선이 함께 움직였을 때(예: 다른 이유로 후보가 0건) 통과해 버린다.
# ===========================================================================

def proof_area_filters_candidates(client) -> None:
    """평수. ★ 이번 사고의 본체. **실거래 경로와 호가 경로를 둘 다 태운다.**"""
    token = _ready(client)
    # --- 실거래만 있는 단지(오늘의 운영 모습: listing 테이블이 비어 있다) ---------
    # 1번: 59.9㎡ 만 · 2번: 84.97㎡ 만 · 3번: **한 단지에 두 면적대**
    _seed(client.repo, complex_id=1, name="소형단지", areas=(59.9,))
    _seed(client.repo, complex_id=2, name="대형단지", areas=(84.97,))
    _seed(client.repo, complex_id=3, name="혼합단지", areas=(59.9, 84.97))
    # --- 호가가 있는 단지(포털 수집이 붙은 뒤의 모습 — 이쪽이 주 경로가 된다) -----
    # ★ 호가가 하나라도 있으면 조립은 **호가 분기만** 탄다(실거래 분기는 건너뛴다).
    #   한 단지 안에 맞는 호가와 안 맞는 호가를 섞어야, 단지가 리포지토리 필터를
    #   통과한 뒤 **조립 단계의 가드가 실제로 판정**하는 상황이 만들어진다.
    _seed(client.repo, complex_id=4, name="호가혼합단지", areas=(59.9, 84.97),
          listings=((7.0, 59.9), (7.4, 84.97)))
    # 면적 0 인 호가(수집 결손)를 조건에 맞는 호가와 **같은 단지에** 둔다.
    # 이래야 `area_ok` 의 미상 처리가 판정에 관여한다(단지는 59.9 덕분에 살아남는다).
    _seed(client.repo, complex_id=5, name="호가면적미상단지", areas=(59.9,),
          listings=((7.0, 59.9), (7.1, 0.0)))

    wide = _run(client, token, {"region_codes": [REGION]})
    assert _names(wide) == {"소형단지", "대형단지", "혼합단지",
                            "호가혼합단지", "호가면적미상단지"}, "기준선이 성립해야 한다"
    assert {59.9, 84.97} <= set(_areas(wide))
    # 기준선에서는 면적 0 호가도 후보가 된다(조건이 없으므로) — 그래야 아래 대조가 성립한다.
    assert 0.0 in _areas(wide), "면적 미상 호가가 기준선에 없으면 미상 처리를 증명할 수 없다"

    narrow = _run(client, token, {"region_codes": [REGION],
                                  "area_min_m2": 55, "area_max_m2": 62})

    assert _names(narrow) == {"소형단지", "혼합단지", "호가혼합단지",
                              "호가면적미상단지"}, "평수 조건이 후보를 좁히지 못했다"
    # ★ 단지가 아니라 **후보(면적대)** 단위로 걸러야 한다 — 혼합단지의 84.97 이 남으면
    #   "조건에 안 맞는 매물이 나온다"는 제보가 그대로 재현된다.
    assert all(55 <= a <= 62 for a in _areas(narrow)), _areas(narrow)
    # 단지 4개 × 후보 1개씩. 하나라도 더 있으면 어느 분기가 안 거른 것이다:
    #   5개 → 호가혼합단지의 84.97 이 살아남음(호가 분기 면적 판정 부재)
    #   5개 → 호가면적미상단지의 0㎡ 가 살아남음(`area_ok` 미상 처리가 통과로 뒤집힘)
    assert len(_areas(narrow)) == 4, _areas(narrow)
    assert 0.0 not in _areas(narrow), "면적 미상(0㎡) 호가가 조건을 통과했다 — 모름 ≠ 충족"
    # 걸러낸 사실을 숫자로 말한다(제외 목록에 쌓지 않는 대신).
    joined = " ".join(narrow["notes"])
    assert "전용 55~62㎡" in joined, narrow["notes"]
    assert "확인되지 않은" in joined, narrow["notes"]

    # 반대 방향도 본다 — 조건이 그냥 "적게 나오게" 하는 게 아니라 **맞는 것만** 남긴다.
    big = _run(client, token, {"region_codes": [REGION],
                               "area_min_m2": 80, "area_max_m2": 90})
    assert _names(big) == {"대형단지", "혼합단지", "호가혼합단지"}
    assert all(80 <= a <= 90 for a in _areas(big)), _areas(big)


def proof_built_after_filters_candidates(client) -> None:
    """준공연도. 지도는 이미 거른다 — 추천만 안 거르면 같은 계열의 결함이다."""
    token = _ready(client)
    _seed(client.repo, complex_id=1, name="구축", built_year=1990)
    _seed(client.repo, complex_id=2, name="신축", built_year=2015)
    _seed(client.repo, complex_id=3, name="연식미상", built_year=None)

    wide = _run(client, token, {"region_codes": [REGION]})
    assert _names(wide) == {"구축", "신축", "연식미상"}

    narrow = _run(client, token, {"region_codes": [REGION], "built_after": 2000})
    assert _names(narrow) == {"신축"}, "준공연도 조건이 반영되지 않았다"
    # 미상은 통과시키지 않되 **말한다**(모름 ≠ 조건 충족).
    assert any("준공" in n for n in narrow["notes"]), narrow["notes"]


def proof_min_households_filters_candidates(client) -> None:
    """세대수. 값을 모르는 단지를 조용히 통과시키지도, 조용히 버리지도 않는다."""
    token = _ready(client)
    _seed(client.repo, complex_id=1, name="소단지", households=300)
    _seed(client.repo, complex_id=2, name="대단지", households=1500)
    _seed(client.repo, complex_id=3, name="세대수미상", households=None)

    wide = _run(client, token, {"region_codes": [REGION]})
    assert _names(wide) == {"소단지", "대단지", "세대수미상"}

    narrow = _run(client, token, {"region_codes": [REGION], "min_households": 1000})
    assert _names(narrow) == {"대단지"}
    assert any("세대" in n for n in narrow["notes"]), narrow["notes"]


def proof_budget_excludes_over_price(client) -> None:
    """가격. 후보 **조회**와 **제외 판정** 양쪽에 닿는지 본다(1차 사고의 회귀)."""
    token = _ready(client, cash=300_000_000, income=200_000_000)
    _seed(client.repo, complex_id=1, name="싼단지", price_oku=7.0)
    _seed(client.repo, complex_id=2, name="비싼단지", price_oku=8.5)

    wide = _run(client, token, {"region_codes": [REGION]})
    assert _names(wide) == {"싼단지", "비싼단지"}, "기준선부터 둘 다 나와야 한다"

    budget = 8 * OKU
    narrow = _run(client, token, {"region_codes": [REGION],
                                  "budget_override_krw": budget})
    assert _names(narrow) == {"싼단지"}
    # ★ 목록에 남은 항목은 **전부** 예산 이하여야 한다("대체로"는 실패다).
    assert all(it["est_price_krw"] <= budget for it in narrow["items"])
    dropped = [e for e in narrow["excluded"] if e["complex_name"] == "비싼단지"]
    assert dropped and dropped[0]["reason_code"] == "over_budget", narrow["excluded"]

    # 저장된 희망가(내 조건)만으로도 같은 결과여야 한다 — 요청에 안 실어도 도달한다.
    # (요청만 읽으면 클라이언트 한 줄 누락에 상한이 조용히 사라지고 자기 한도가 쓰인다.)
    _prefs(client, token, prefer={"target_price_krw": budget})
    saved = _run(client, token, {"region_codes": [REGION]})
    assert _names(saved) == {"싼단지"}, "저장된 희망 매매가가 추천에 도달하지 않았다"
    assert all(it["est_price_krw"] <= budget for it in saved["items"])


def proof_avoid_excludes_and_off_restores(client) -> None:
    """기피. ★ 체크를 **풀면 원래대로 돌아오는지**까지 본다.

    예전에는 저장된 `{"main_road_noise": false}` 의 **키만** 보고 기피를 적용해서,
    체크를 해제해도 계속 제외됐다(껐는데 켜져 있는 조건).
    """
    token = _ready(client)
    _seed(client.repo, complex_id=1, name="대로변단지")
    _seed(client.repo, complex_id=2, name="조용한단지")
    client.repo.set_location_facts(1, LocationFacts(
        stations=(StationFact("역", 400.0, ("2호선",)),),
        hazards=(HazardFact(kind="main_road_noise", distance_m=20.0),)))
    client.repo.set_location_facts(2, LocationFacts(
        stations=(StationFact("역", 400.0, ("2호선",)),)))

    _prefs(client, token, avoid={"main_road_noise": False})
    off = _run(client, token, {"region_codes": [REGION]})
    assert _names(off) == {"대로변단지", "조용한단지"}, "끈 기피 조건이 적용되고 있다"

    _prefs(client, token, avoid={"main_road_noise": True})
    on = _run(client, token, {"region_codes": [REGION]})
    assert _names(on) == {"조용한단지"}, "켠 기피 조건이 적용되지 않았다"
    assert any(e["reason_code"] == "avoided" for e in on["excluded"]), on["excluded"]


def _seed_weight_pair(repo) -> None:
    """가격 축과 가치(환금성) 축이 **정확히 반대**인 두 단지."""
    _seed(repo, complex_id=1, name="가격우위단지", price_oku=7.0, households=4000,
          listings=((7.0, 84.97),))
    _seed(repo, complex_id=2, name="환금성우위단지", price_oku=7.0, households=100,
          listings=((7.7, 84.97),))


def proof_weights_change_order(client) -> None:
    """가격·가치 비중. 슬라이더를 움직이면 순위가 **달라져야** 한다."""
    token = _ready(client)
    _seed_weight_pair(client.repo)

    _prefs(client, token, weights={"price": 1.0})
    price_order = [it["complex"]["name"]
                   for it in _run(client, token, {"region_codes": [REGION]})["items"]]
    _prefs(client, token, weights={"value": 1.0})
    value_order = [it["complex"]["name"]
                   for it in _run(client, token, {"region_codes": [REGION]})["items"]]

    assert price_order[0] == "가격우위단지", price_order
    assert value_order[0] == "환금성우위단지", value_order
    assert price_order != value_order


def proof_weights_change_order_location(client) -> None:
    """입지 비중. 입지 실측이 있으면 순위가 그쪽으로 움직여야 한다."""
    token = _ready(client)
    # 가격은 역전시켜 둔다 — 입지 비중이 실제로 작동해야만 순서가 뒤집힌다.
    _seed(client.repo, complex_id=1, name="역세권단지", price_oku=7.0,
          listings=((7.7, 84.97),))
    _seed(client.repo, complex_id=2, name="가격우위단지", price_oku=7.0,
          listings=((7.0, 84.97),))
    client.repo.set_location_facts(1, LocationFacts(
        stations=(StationFact("강남역", 150.0, ("2호선", "신분당선")),)))
    client.repo.set_location_facts(2, LocationFacts(
        stations=(StationFact("먼역", 2500.0, ("1호선",)),)))

    _prefs(client, token, weights={"price": 1.0})
    price_first = [it["complex"]["name"]
                   for it in _run(client, token, {"region_codes": [REGION]})["items"]]
    _prefs(client, token, weights={"location": 1.0})
    loc_first = [it["complex"]["name"]
                 for it in _run(client, token, {"region_codes": [REGION]})["items"]]

    assert price_first[0] == "가격우위단지", price_first
    assert loc_first[0] == "역세권단지", loc_first


def proof_weights_change_order_risk(client) -> None:
    """리스크 비중(매물 신뢰도). 오래 안 팔린 매물은 신뢰도가 낮다."""
    token = _ready(client)
    # 1번: 호가 = 실거래 중위(가격 만점) · 등록 200일(신뢰도 감점)
    # 2번: 호가 +10%(가격 낮음)        · 등록 5일(신뢰도 만점)
    _seed(client.repo, complex_id=1, name="가격우위단지", price_oku=7.0,
          listings=((7.0, 84.97),), listed_days_ago=200)
    _seed(client.repo, complex_id=2, name="신뢰도우위단지", price_oku=7.0,
          listings=((7.7, 84.97),), listed_days_ago=5)

    _prefs(client, token, weights={"price": 1.0})
    price_first = [it["complex"]["name"]
                   for it in _run(client, token, {"region_codes": [REGION]})["items"]]
    _prefs(client, token, weights={"risk": 1.0})
    risk_first = [it["complex"]["name"]
                  for it in _run(client, token, {"region_codes": [REGION]})["items"]]

    assert price_first[0] == "가격우위단지", price_first
    assert risk_first[0] == "신뢰도우위단지", risk_first


def _redev(stage: str, raw_stage: str) -> RedevProject:
    """정비사업 구역 1건 — **단계만** 있고 일자·세대수는 없다.

    일부러 비운다: 일자가 있으면 정체 감점, 세대수가 있으면 사업성 보정이 붙어
    점수가 단계 하나로 결정되지 않는다. 이 증명이 보려는 것은 "재건축 비중이
    순위를 바꾸는가"이므로 단계 외의 변수는 넣지 않는다.
    """
    return RedevProject(zone_name="테스트구역", sigungu="강남구", raw_stage=raw_stage,
                        stage=stage, raw_biz_type="공동주택재건축",
                        biz_type=KIND_REBUILD, source="test", as_of=TODAY)


def proof_weights_change_order_redevelopment(client) -> None:
    """재건축 비중. 슬라이더를 0 ↔ 100% 로 움직이면 순위가 **달라져야** 한다.

    ★ 이 축에만 있는 함정 두 개를 함께 고정한다.
      ① **'안 보냄'과 '0'이 다른 뜻이다.** 뒤에 추가된 축이라 키가 없으면 서버가
         기본 15%를 넣는다(`scoring.DEFAULT_AXIS_WEIGHTS`). 그러니 "재건축을 끈"
         상태는 키를 빼는 게 아니라 **0 을 명시해 보내는 것**이고, 서버가 그 0 을
         존중하는지까지 봐야 이 축을 껐다고 말할 수 있다.
      ② **비단조 · 목적 의존.** 같은 단계가 실거주와 투자에 정반대 신호다
         (`redevelopment/analysis.STAGE_PROFILE`). 그래서 목적만 바꿔도 순서가
         다시 뒤집히는지 본다 — 다른 축이 우연히 같은 순서를 만든 경우와 구분된다.
    """
    token = _ready(client)
    # 가격은 역전시켜 둔다 — 재건축 비중이 실제로 작동해야만 순서가 뒤집힌다.
    # 준공 = 실거주에 좋고 투자엔 나쁨 / 사업시행인가 = 그 반대.
    _seed(client.repo, complex_id=1, name="준공단지", price_oku=7.0,
          listings=((7.7, 84.97),))
    _seed(client.repo, complex_id=2, name="사업시행단지", price_oku=7.0,
          listings=((7.0, 84.97),))
    client.repo.set_redevelopment(1, _redev(STAGE_COMPLETED, "준공"))
    client.repo.set_redevelopment(2, _redev(STAGE_IMPLEMENTATION, "사업시행인가"))

    def run(weights, **body):
        _prefs(client, token, weights=weights)
        return _run(client, token, {"region_codes": [REGION], **body})

    def order(body):
        return [it["complex"]["name"] for it in body["items"]]

    def redev_axis(body, name):
        item = next(it for it in body["items"] if it["complex"]["name"] == name)
        return next(a for a in item["score_axes"] if a["axis"] == "redevelopment")

    # --- 끈 상태: 0 을 **명시**해서 보낸다(프론트가 실제로 보내는 모양) ----------
    off = run({"price": 1.0, "location": 0.0, "value": 0.0, "risk": 0.0,
               "redevelopment": 0.0})
    assert order(off)[0] == "사업시행단지", order(off)
    # 명시한 0 이 존중돼야 '끈 상태'가 성립한다 — 여기서 applied 가 나오면 서버가
    # 기본 15% 를 덮어씌운 것이고, 그러면 아래 대조는 0 과 100% 의 비교가 아니다.
    assert redev_axis(off, "사업시행단지")["status"] == "zero_weight"

    # --- 켠 상태: 재건축 100% (기본 목적 = 실거주) ------------------------------
    on = run({"price": 0.0, "location": 0.0, "value": 0.0, "risk": 0.0,
              "redevelopment": 1.0})
    assert order(on)[0] == "준공단지", order(on)
    assert order(on) != order(off), "재건축 비중을 0 → 100% 로 바꿨는데 순위가 같다"
    top_axis = redev_axis(on, "준공단지")
    assert top_axis["status"] == "applied"
    # 점수 자체가 순위를 만든 것이어야 한다(순서만 우연히 맞은 게 아니라).
    assert top_axis["score"] > redev_axis(on, "사업시행단지")["score"]

    # --- 같은 가중치 · 같은 데이터인데 **목적**만 바꾸면 다시 뒤집힌다 ----------
    invest = run({"price": 0.0, "location": 0.0, "value": 0.0, "risk": 0.0,
                  "redevelopment": 1.0}, purpose="invest")
    assert order(invest)[0] == "사업시행단지", order(invest)

    # --- 키가 아예 없으면 기본 15% + **그 사실을 말한다** -----------------------
    # 예전 저장값(재건축 축이 생기기 전의 내 조건)이 여기에 해당한다. 조용히 넣으면
    # 사용자가 준 적 없는 비중이 순위를 바꾸는데 아무도 모른다.
    legacy = run({"price": 1.0, "location": 0.0, "value": 0.0, "risk": 0.0})
    assert redev_axis(legacy, "사업시행단지")["status"] == "applied"
    assert any("기본 비중" in n and "15%" in n for n in legacy["notes"]), legacy["notes"]


def proof_region_scope(client) -> None:
    token = _ready(client)
    _seed(client.repo, complex_id=1, name="강남단지", region=REGION)
    _seed(client.repo, complex_id=2, name="안양단지", region=OTHER_REGION,
          lon=126.95, lat=37.39)

    assert _names(_run(client, token, {})) == {"강남단지", "안양단지"}
    assert _names(_run(client, token, {"region_codes": ["11680"]})) == {"강남단지"}
    assert _names(_run(client, token, {"region_codes": ["41173"]})) == {"안양단지"}


def proof_bbox_scope(client) -> None:
    token = _ready(client)
    _seed(client.repo, complex_id=1, name="강남단지", lon=127.05, lat=37.51)
    _seed(client.repo, complex_id=2, name="안양단지", region=OTHER_REGION,
          lon=126.95, lat=37.39)

    gangnam = _run(client, token, {"bbox": "127.01,37.45,127.12,37.54"})
    anyang = _run(client, token, {"bbox": "126.92,37.35,126.99,37.42"})
    assert _names(gangnam) == {"강남단지"}
    assert _names(anyang) == {"안양단지"}


def proof_top_n_limits_items(client) -> None:
    token = _ready(client)
    for cid, price in ((1, 7.0), (2, 7.2), (3, 7.4)):
        _seed(client.repo, complex_id=cid, name=f"단지{cid}", price_oku=price)

    assert len(_run(client, token, {"region_codes": [REGION]})["items"]) == 3
    one = _run(client, token, {"region_codes": [REGION], "top_n": 1})
    assert len(one["items"]) == 1
    assert sum(1 for e in one["excluded"]
               if e["reason_code"] == "below_rank_cutoff") == 2


def proof_purpose_reaches_affordability(client, monkeypatch=None) -> None:
    """목적(실거주/투자)이 **자금 계산까지 실제로 전달되는지**.

    ⚠️ 여기만 출력 비교가 아니라 **이음매(seam) 검사**다. 목적은 대출 캡·스트레스
    금리 규칙을 통해서만 결과를 바꾸는데, 테스트 세율표에는 그 분기가 없어서
    "결과가 같다"가 정상이다. 그래서 값이 도메인까지 도달하는지를 직접 본다 —
    러너가 `purpose` 를 떨어뜨리면 실패한다(있는 척은 못 한다).

    ⚠️ 이음매의 **위치가 옮겨졌다**(CR39-2, 2026-07-30): 러너는 이제 자금 계산을
    직접 부르지 않고 면적별 상한 조회기(`app/domain/affordability/budget.py`)를 통해
    부른다. 그래서 spy 도 그 모듈에 건다. 호출 **횟수**는 세율 구간 수에 따라 달라지므로
    (구간별 1회 캐시) 개수를 못박지 않고 **모든 호출이 그 목적을 들고 갔는지**를 본다 —
    이게 원래 명제("purpose 가 도달한다")에 더 가깝고 구간 수에 흔들리지 않는다.
    """
    from app.domain.affordability import budget as budget_mod

    seen: list[str] = []
    original = budget_mod.compute_affordability

    def spy(borrower, rules, *, prop=None, **kw):
        seen.append(getattr(prop, "purpose", None))
        return original(borrower, rules, prop=prop, **kw)

    token = _ready(client)
    _seed(client.repo, complex_id=1, name="단지")
    budget_mod.compute_affordability = spy
    try:
        _run(client, token, {"region_codes": [REGION], "purpose": "invest"})
        invest = list(seen)
        seen.clear()
        _run(client, token, {"region_codes": [REGION], "purpose": "live"})
        live = list(seen)
    finally:
        budget_mod.compute_affordability = original

    assert invest and set(invest) == {"invest"}, f"목적이 도달하지 않았다: {invest}"
    assert live and set(live) == {"live"}, f"목적이 도달하지 않았다: {live}"


#: 조건 → 증명 시나리오. 레지스트리가 "반영된다"고 말한 항목은 여기 이름이 있어야 한다.
PROOFS = {
    "area_filters_candidates": proof_area_filters_candidates,
    "built_after_filters_candidates": proof_built_after_filters_candidates,
    "min_households_filters_candidates": proof_min_households_filters_candidates,
    "budget_excludes_over_price": proof_budget_excludes_over_price,
    "avoid_excludes_and_off_restores": proof_avoid_excludes_and_off_restores,
    "weights_change_order": proof_weights_change_order,
    "weights_change_order_location": proof_weights_change_order_location,
    "weights_change_order_risk": proof_weights_change_order_risk,
    "weights_change_order_redevelopment": proof_weights_change_order_redevelopment,
    "region_scope": proof_region_scope,
    "bbox_scope": proof_bbox_scope,
    "top_n_limits_items": proof_top_n_limits_items,
    "purpose_reaches_affordability": proof_purpose_reaches_affordability,
}


@pytest.mark.parametrize("name", sorted(PROOFS))
def test_증명(client, name):
    PROOFS[name](client)


# ===========================================================================
# Part 3 — 계약: 저장된 조건도 도달하는가 · 미상 처리 · 고지
# ===========================================================================

def test_저장된_내조건만으로도_추천이_좁혀진다(client):
    """★ 프론트가 조건을 안 실어 보내도 **서버에 저장된 내 조건**이 살아 있어야 한다.

    이번 사고의 실제 모양이 그것이다 — 화면은 평수를 저장했는데 추천 요청에는
    싣지 않았다. 요청 본문에만 의존하면 프론트 한 줄로 조건이 다시 증발한다.
    """
    token = _ready(client)
    _seed(client.repo, complex_id=1, name="소형단지", areas=(59.9,))
    _seed(client.repo, complex_id=2, name="대형단지", areas=(84.97,))

    _prefs(client, token, prefer={"area_min_m2": 55, "area_max_m2": 62})
    body = _run(client, token, {"region_codes": [REGION]})   # 조건을 **안 보낸다**

    assert _names(body) == {"소형단지"}
    assert all(55 <= a <= 62 for a in _areas(body))


def test_면적_미상_후보는_통과시키지_않고_건수를_말한다(client):
    """조건이 걸렸는데 면적 미상을 통과시키면 제보가 그대로 재현된다.

    반대로 조용히 버리면 유실이다 — 그래서 **버린 건수를 notes 로 말한다**.
    """
    token = _ready(client)
    _seed(client.repo, complex_id=1, name="정상단지", areas=(59.9,))
    # 면적이 없는 호가만 있는 단지(수집 결손). 실거래도 면적 0 으로 둔다.
    client.repo.add_complex(ComplexSummary(
        id=2, name="면적미상단지", lon=127.05, lat=37.51, region_code=REGION,
        built_year=2015, total_households=500, recent_price_krw=7 * OKU,
        price_as_of=TODAY.isoformat(), active_listings=1))
    client.repo.add_listings(2, [ListingRow(
        id=21, ask_price_krw=7 * OKU, area_m2=0.0, floor=10,
        listed_at=TODAY - dt.timedelta(days=5), collected_at=TODAY,
        agency="중개", status="active")])

    wide = _run(client, token, {"region_codes": [REGION]})
    assert "면적미상단지" in _names(wide), "기준선에서는 나오던 단지여야 대조가 성립한다"

    narrow = _run(client, token, {"region_codes": [REGION],
                                  "area_min_m2": 55, "area_max_m2": 62})
    assert _names(narrow) == {"정상단지"}
    assert any("확인되지 않은" in n for n in narrow["notes"]), narrow["notes"]


def test_조건이_없으면_조건_고지도_없다(client):
    """늘 뜨는 고지는 읽히지 않는다 — 조건을 안 걸었으면 아무 말도 하지 않는다."""
    token = _ready(client)
    _seed(client.repo, complex_id=1, name="단지")

    body = _run(client, token, {"region_codes": [REGION]})
    assert not any("내 조건을 적용했습니다" in n for n in body["notes"]), body["notes"]


def test_반영되지_않는_조건은_설정한_경우에만_고지한다(client):
    """역세권·1층 기피는 아직 반영되지 않는다. **그 사실을 말한다** — 다만 설정했을 때만."""
    token = _ready(client)
    _seed(client.repo, complex_id=1, name="단지")

    silent = _run(client, token, {"region_codes": [REGION]})
    assert not any("역세권" in n for n in silent["notes"]), silent["notes"]

    _prefs(client, token, prefer={"subway_within_m": 500}, avoid={"first_floor": True})
    told = _run(client, token, {"region_codes": [REGION]})
    joined = " ".join(told["notes"])
    assert "역세권" in joined and "1층" in joined, told["notes"]


def test_조건으로_후보가_0건이어도_이유를_말한다(client):
    """빈 결과 자체가 답이 되려면 **왜 비었는지**가 있어야 한다."""
    token = _ready(client)
    _seed(client.repo, complex_id=1, name="대형단지", areas=(84.97,))

    body = _run(client, token, {"region_codes": [REGION],
                                "area_min_m2": 20, "area_max_m2": 30})
    assert body["items"] == []
    assert any("내 조건을 적용했습니다" in n for n in body["notes"]), body["notes"]


# ---------------------------------------------------------------------------
# 화면 배지용 값 — 판정이 아니라 **값**을 계약으로 둔다
# ---------------------------------------------------------------------------

def test_추천항목에_세대수와_최근접역_거리가_실린다(client):
    """🏢대단지·🚇역세권 배지는 **값**으로 판단한다(임계값은 표시 계층의 몫).

    임계값(1,000세대·500m)을 서버가 굳혀 boolean 으로 보내면, 저장된 payload 에
    옛 기준이 그대로 박히고 나중에 되돌릴 수 없다.
    """
    token = _ready(client)
    _seed(client.repo, complex_id=1, name="단지", households=1200)
    client.repo.set_location_facts(1, LocationFacts(
        stations=(StationFact("강남역", 320.0, ("2호선", "신분당선")),)))

    item = _run(client, token, {"region_codes": [REGION]})["items"][0]
    assert item["total_households"] == 1200
    assert item["nearest_station"]["distance_m"] == 320.0
    assert item["nearest_station"]["name"] == "강남역"
    assert item["nearest_station"]["line_count"] == 2
    # 직선거리임을 명시한다 — 도보 시간으로 읽히면 안 된다.
    assert item["nearest_station"]["basis"] == "straight_line"


def test_세대수를_모르면_0이_아니라_null이다(client):
    """16,462개 중 2,666개가 미확보다. "모름"과 "아님"은 다르다."""
    token = _ready(client)
    _seed(client.repo, complex_id=1, name="단지", households=None)

    item = _run(client, token, {"region_codes": [REGION]})["items"][0]
    assert item["total_households"] is None
    # 입지 데이터가 없으면 역 거리도 **null** — 0m 로 만들지 않는다.
    assert item["nearest_station"] is None
