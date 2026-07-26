"""추천 실행 러너 — 큐/redis 없이 API BackgroundTask 로 오케스트레이터를 구동한다.

설계 근거: docs/02-design/agents/README.md §2, ORDER 2026-07-25-24-domain

왜 큐 워커가 아니라 BackgroundTask 인가
---------------------------------------
배포 최소구성이 **redis 없는 api+db** 다(개인용, 동시성 낮음). 별도 worker/redis 를
띄우면 VPS 자원을 초과한다. FastAPI `BackgroundTasks` 로 응답 직후 인프로세스에서 돌리면
충분하다. 추천 1건당 후보 수십 건이고 사용자가 사실상 1명이라 직렬 실행으로 족하다.

흐름
----
    POST /recommendations → job 'queued' 저장 → (여기) BackgroundTask:
      (1) 프로필 복호화 → 예산(affordability) 산출
      (2) repo 로 후보 매물·실거래·입지 조회 → Candidate 조립
      (3) run_mvp_pipeline 실행
      (4) recommendation_item/finding + **제외 사유(excluded)·notes** 저장 · status 'done'
    → GET /recommendations/{id} 로 결과

데이터가 없으면(수집 전) **빈 결과가 정상**이다 — 지어내지 않는다.
어떤 예외도 밖으로 던지지 않는다. 실패하면 job 을 'failed' 로 남긴다 —
'queued' 로 영영 멈춰 있는 게 가장 위험하다(worker.py 주석 참조).

왜 제외 사유까지 저장하는가
---------------------------
파이프라인은 예전부터 `excluded`(떨어뜨린 후보와 사유)를 만들었지만, 이 러너가
`items` 만 꺼내 저장해서 **응답에 도달하지 못했다.** 그러면 사용자는 자기가 아는 단지가
빠졌을 때 "예산 초과라서"인지 "표본이 없어서"인지 모른 채 결과 전체를 의심하게 된다.
추천 목록은 답의 절반이고, 나머지 절반은 **왜 저건 없는가**다(api-spec.md §5.2).
"""
from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Any

from app.agents.base import TRIPWIRE_MIN_AMOUNT, extract_amounts
from app.agents.llm import LLMClient
from app.agents.orchestrator import (
    EXCLUDED_AVOIDED,
    EXCLUDED_NO_PRICE,
    EXCLUDED_OVER_BUDGET,
    AnalysisContext,
    Candidate,
    excluded_record,
    run_mvp_pipeline,
)
from app.agents.scoring import BASIS_USER_WEIGHTED
from app.core.security import decrypt_amount, load_key
from app.domain.affordability.engine import compute_affordability
from app.domain.affordability.models import Borrower, PropertyFacts
from app.domain.listings.dedup import AREA_TOLERANCE_M2, group_duplicates
from app.domain.rules.loader import load_rules
from app.domain.valuation.models import MIN_SAMPLE, PERIOD_LADDER, TradeRow
from app.domain.valuation.stats import eligible_trades

logger = logging.getLogger("app.agents.recommend")

#: 실패한 job 의 상태값. **DB 제약(001_init.sql: queued|running|done|failed)과 반드시 같아야 한다.**
#: 예전에는 'error' 를 썼는데 제약에 없는 값이라 UPDATE 가 통째로 깨졌고, 그 결과 job 이
#: **'queued' 로 영원히 멈춰** 화면에는 "분석 중…" 이 무한히 떴다. 실패가 실패로 보이지 않는,
#: 이 프로젝트가 가장 경계하는 형태의 사고다(러너 docstring 이 지목한 바로 그 상태).
#: 프론트의 jobPhase 매핑(lib/recommendation.ts)도 이 값을 알아야 한다 — 한쪽만 고치면 증상이 같다.
JOB_FAILED = "failed"

#: 후보로 볼 단지 상한 — LLM/통계 비용을 태우는 대상이라 넉넉하되 유한하게.
CANDIDATE_COMPLEX_LIMIT = 50
#: 조립된 Candidate 총량 상한(단지 × 면적그룹이 폭증하지 않게).
MAX_CANDIDATES = 200
#: 추천 개수. 상한은 API 스키마(`RecommendationIn.top_n`)와 같은 값이어야 한다 —
#: 여기서만 큰 값을 허용하면 스키마를 우회하는 호출부가 응답을 무한정 키울 수 있다.
DEFAULT_TOP_N = 10
MAX_TOP_N = 50
#: 호가가 없는 단지에서 실거래로 세울 면적대 수(거래 많은 순).
#: 한 단지가 후보 목록을 독식하지 않게 막는다.
TRADE_AREA_GROUPS_PER_COMPLEX = 3

#: 자산 금액 필드 ↔ 암호문 컬럼
_AMOUNT_FIELDS = (
    ("cash_krw", "cash_krw_enc"),
    ("income_krw", "income_krw_enc"),
    ("existing_loan_krw", "existing_loan_krw_enc"),
)


def _empty_result() -> dict[str, Any]:
    """결과가 없을 때의 표준 모양. 키를 빠뜨리면 하류가 KeyError 로 죽는다."""
    return {"items": [], "excluded": [], "notes": []}


def run_recommendation_job(
    *, repo: Any, settings: Any, job_id: str, user_id: int,
    criteria: dict[str, Any], llm: LLMClient | None = None,
) -> None:
    """BackgroundTask 진입점. **절대 예외를 던지지 않는다.**"""
    status, result = "error", _empty_result()
    try:
        status, result = _analyze(repo, settings, user_id, criteria, llm)
    except Exception:  # noqa: BLE001 - 백그라운드라 삼켜서 job 상태로만 남긴다
        logger.exception("추천 작업 실패 job=%s", job_id)
        status, result = JOB_FAILED, _empty_result()
    _persist(repo, job_id, user_id, status, result)


def _analyze(repo: Any, settings: Any, user_id: int, criteria: dict[str, Any],
             llm: LLMClient | None) -> tuple[str, dict[str, Any]]:
    # 세율·키는 여기서 로드한다(BackgroundTask 는 Depends 를 못 받는다).
    rules = load_rules(settings.tax_rules_path)          # 실패 시 상위 except → error
    key = load_key(settings.field_encryption_key)

    profile = repo.get_profile(user_id)
    if profile is None:
        # 자산 미입력 → 예산을 알 수 없다. 지어내지 않고 빈 결과.
        # ⚠️ 이것도 "왜 비었는지"다. 빈 목록만 주면 사용자는 데이터가 없는 줄 안다.
        logger.info("추천: 프로필 없음 → 빈 결과 (user=%s)", user_id)
        return "done", {
            "items": [], "excluded": [],
            "notes": ["자산 정보가 없어 예산을 계산할 수 없습니다. "
                      "내 정보에서 보유 현금·연소득을 입력하면 후보를 좁혀 드립니다."],
        }

    borrower, forbidden = _borrower_from_profile(profile, user_id, key)
    prop = PropertyFacts(purpose=str(criteria.get("purpose") or "live"))
    afford = compute_affordability(borrower, rules, prop=prop)

    # 예산: 명시 override 우선, 없으면 실구매 가능액.
    budget = criteria.get("budget_override_krw") or afford.max_purchase_krw

    prefs = repo.get_preferences(user_id) if hasattr(repo, "get_preferences") else {}
    avoid = (prefs or {}).get("avoid") or {}
    # ⚠️ 가중치는 **저장만 되고 순위에 쓰이지 않던 값**이었다(슬라이더를 움직여도 결과가
    #    그대로였다). 여기서 파이프라인으로 넘겨 실제 총점에 곱한다 — 근거가 없는 축은
    #    빼고 재정규화하되 그 사실을 응답에 남긴다(app/agents/scoring.py).
    weights = (prefs or {}).get("weights") or {}

    assembly = _assemble_candidates(repo, criteria, budget)
    candidates = assembly.candidates
    ctx = AnalysisContext(
        affordability=afford, candidates=candidates,
        avoid=avoid, weights=weights, forbidden_amounts=forbidden,
    )
    # 요청한 top_n 을 실제로 지킨다. 예전엔 파이프라인 기본값(10)으로 고정돼 있어
    # `top_n` 이 API 계약에만 있고 동작하지 않았다 — 이제 제외 사유가 "상위 N건 밖"을
    # 말하므로, 그 N 이 사용자가 요청한 값과 달라선 안 된다.
    top_n = max(1, min(MAX_TOP_N, int(criteria.get("top_n") or DEFAULT_TOP_N)))
    result = run_mvp_pipeline(ctx, llm=llm, top_n=top_n)
    items = result["items"]
    # 조립 단계에서 떨어진 단지가 앞에 온다 — 후보조차 되지 못한 쪽이 사용자 질문에
    # 더 가깝다("우리 단지가 아예 안 보인다").
    # 제외 사유는 사용자에게 그대로 보인다 — 나가기 직전에 자산 원본을 한 번 더 거른다.
    excluded = _strip_asset_amounts(
        assembly.excluded + (result.get("excluded") or []), forbidden)
    trade_basis = sum(1 for it in items if it.get("price_basis") == "trade")
    # 가중치가 실제로 반영된 건수를 남긴다 — "반영했다"는 주장을 로그로 반증할 수 있게.
    # ⚠️ 가중치 **값**은 찍지 않는다(사용자 취향도 개인정보다). 건수만 센다.
    weighted = sum(1 for it in items if it.get("score_basis") == BASIS_USER_WEIGHTED)
    logger.info(
        "추천 완료 user=%s 후보=%d 추천=%d (실거래기준 %d · 호가기준 %d · "
        "가중치반영 %d) 제외=%d %s",
        user_id, len(candidates), len(items), trade_basis, len(items) - trade_basis,
        weighted, len(excluded), _reason_counts(excluded))
    return "done", {"items": items, "excluded": excluded,
                    "notes": list(result.get("notes") or []) + assembly.notes}


def _reason_counts(excluded: list[dict[str, Any]]) -> dict[str, int]:
    """사유 **코드별** 분포. 문장으로 세면 금액·단지명 때문에 전부 유니크해진다."""
    counts: dict[str, int] = {}
    for e in excluded:
        code = str(e.get("reason_code") or "unknown")
        counts[code] = counts.get(code, 0) + 1
    return counts


#: 자산 원본이 섞인 사유를 대체할 문구. 사유를 통째로 버리지 않는다 —
#: "왜 빠졌는지"는 남기고 **숫자만** 지운다(사용자는 여전히 답을 얻는다).
_SAFE_REASON = {
    EXCLUDED_OVER_BUDGET: "예산 초과 — 산정된 실구매 가능 금액을 넘습니다",
    EXCLUDED_NO_PRICE: "가격 근거 없음 — 활성 호가가 없고 실거래 표본이 부족합니다",
    EXCLUDED_AVOIDED: "기피 조건에 해당합니다",
}
_SAFE_REASON_FALLBACK = "제외됨 — 사유 문구에 민감정보가 섞여 가렸습니다"


def _strip_asset_amounts(excluded: list[dict[str, Any]],
                         forbidden: list[int]) -> list[dict[str, Any]]:
    """제외 사유에 **자산 원본 금액**이 섞였는지 마지막으로 거른다 (SR4-2).

    왜 필요한가
    -----------
    제외 사유는 `recommendation_job.result_meta` 에 **평문 jsonb** 로 저장되고 API 응답에도
    그대로 실린다. 보유현금·연소득·기존대출은 컬럼 암호화 대상인데(security.md §3),
    사유 문장으로 새면 그 암호화가 무의미해진다. 한도·부대비용 같은 **파생값**은 허용이고
    (사용자가 `/affordability` 로 이미 보는 값), **원본**은 금지다.

    1차 방어는 구조다 — 사유를 만드는 `orchestrator` 는 원본을 아예 갖고 있지 않다
    (`AnalysisContext` 에 없다). 이건 그 위에 얹는 그물이고, 미래에 누가 "친절하게"
    "보유현금 8억으로는 부족합니다" 같은 문구를 넣으면 여기서 잡힌다.

    매칭은 substring 이 아니라 **값 비교**다(`extract_amounts`) — 시세 13억이 자산 3억으로
    오차단되지 않는다. 걸리면 사유 문장만 안전한 문구로 바꾸고 코드·단지명은 남긴다.
    """
    guarded = {v for v in forbidden if v and v >= TRIPWIRE_MIN_AMOUNT}
    if not guarded:
        return list(excluded)

    out: list[dict[str, Any]] = []
    for entry in excluded:
        reason = str(entry.get("reason") or "")
        if reason and extract_amounts(reason) & guarded:
            code = str(entry.get("reason_code") or "")
            # ⚠️ 로그에도 값을 찍지 않는다(무엇이 걸렸는지는 코드로 충분하다).
            logger.warning("제외 사유에 자산 원본 금액이 섞여 마스킹했습니다 (code=%s)", code)
            entry = {**entry,
                     "reason": _SAFE_REASON.get(code, _SAFE_REASON_FALLBACK),
                     "reason_redacted": True}
        out.append(entry)
    return out


def _borrower_from_profile(profile: Any, user_id: int, key: bytes) -> tuple[Borrower, list[int]]:
    """암호문 프로필 → Borrower + tripwire 검사값(원본 자산).

    기존 대출의 **연 상환액/이자**는 프로필에 없으므로 0 으로 둔다(추정하지 않는다,
    routes.py::/affordability 와 동일). 원본 금액은 forbidden 으로만 넘기고
    프롬프트에는 절대 싣지 않는다(security.md §6).
    """
    amounts: dict[str, int] = {}
    for plain, enc_attr in _AMOUNT_FIELDS:
        amounts[plain] = decrypt_amount(
            getattr(profile, enc_attr), user_id=user_id, field=plain, key=key) or 0

    borrower = Borrower(
        cash_krw=amounts["cash_krw"],
        annual_income_krw=amounts["income_krw"],
        existing_annual_repayment_krw=0,
        existing_annual_interest_krw=0,
        owned_houses=profile.owned_houses,
        household_size=profile.household_size,
    )
    forbidden = [v for v in amounts.values() if v]
    return borrower, forbidden


def _trade_area_groups(trades: list[TradeRow], *,
                       limit: int = TRADE_AREA_GROUPS_PER_COMPLEX) -> list[float]:
    """실거래를 전용면적으로 묶어 **후보로 세울 면적대**를 고른다(거래 많은 순).

    왜 필요한가
    -----------
    호가가 있으면 "어떤 유닛을 살 것인가"를 매물이 정해 준다. 호가가 없으면 그걸
    정해 주는 게 없다. 그래서 그 단지에서 **실제로 거래된 면적대**를 후보로 삼는다.
    (없는 평형을 추천하지 않기 위해서다 — 거래가 없는 면적대는 가격도 말할 수 없다.)

    표본이 `MIN_SAMPLE` 미만인 면적대는 애초에 세우지 않는다. 세워 봐야 적정가 밴드가
    안 나와서 "가격 근거 없음"으로 제외될 뿐이고, 그만큼 상한(MAX_CANDIDATES)을 낭비한다.
    기간은 밴드가 마지막으로 시도하는 창(PERIOD_LADDER 최대)과 맞춘다.

    면적은 `AREA_TOLERANCE_M2` 안에서 한 덩어리로 본다. 84.9 와 84.97 을 따로 세우면
    같은 타입이 두 후보가 되고, 밴드는 어차피 오차 안의 거래를 함께 쓰므로 중복이다.
    돌려주는 값은 **실거래에 실제로 있던 면적**이다(반올림한 대표값이 아니다) —
    표시 면적을 우리가 만들어내지 않기 위해서다.
    """
    recent = eligible_trades(trades, months=PERIOD_LADDER[-1])
    counts: dict[float, int] = {}
    for t in recent:
        if t.area_m2 <= 0:
            continue
        counts[t.area_m2] = counts.get(t.area_m2, 0) + 1

    # 거래 많은 순 → 같은 건수면 면적 오름차순(결정론적).
    ranked = sorted(counts, key=lambda a: (-counts[a], a))

    chosen: list[float] = []
    for area in ranked:
        # 오차 안의 거래를 합쳐도 표본이 안 되면 밴드가 안 나온다.
        nearby = sum(n for a, n in counts.items() if abs(a - area) <= AREA_TOLERANCE_M2)
        if nearby < MIN_SAMPLE:
            continue
        if any(abs(area - picked) <= AREA_TOLERANCE_M2 for picked in chosen):
            continue                          # 이미 고른 면적대와 같은 덩어리
        chosen.append(area)
        if len(chosen) >= limit:
            break
    return chosen


@dataclass
class Assembly:
    """후보 조립 결과.

    후보만 돌려주면 **조립 단계에서 떨어진 단지가 어디에도 안 남는다.** 실측(강남구)에서
    조회한 50개 단지 중 4개가 "실거래 표본 부족"으로 여기서 사라졌고, 사용자는 그
    단지들에 대해 아무 답도 받지 못했다. 그래서 사유와 단서를 함께 돌려준다.
    """

    candidates: list[Candidate] = field(default_factory=list)
    #: 후보가 되기 전에 떨어진 단지들(파이프라인 excluded 와 **같은 모양**).
    excluded: list[dict[str, Any]] = field(default_factory=list)
    #: 결과 전체에 붙는 단서(조회 상한에 걸렸다 등).
    notes: list[str] = field(default_factory=list)


def _assemble_candidates(repo: Any, criteria: dict[str, Any],
                         budget: int | None) -> Assembly:
    """repo 조회 결과를 orchestrator 의 Candidate 로 조립.

    후보/매물/실거래 조회 메서드가 없으면(PostGIS 구현 대기) **빈 결과** —
    지어내지 않고, 크래시하지도 않는다. 다만 그 사실을 notes 로 말한다
    (빈 화면과 "아직 못 만든 기능"은 사용자에게 완전히 다른 사실이다).

    ⚠️ 호가 없는 단지도 후보다 (CHARTER G4)
    ----------------------------------------
    예전에는 `if not listings: continue` 로 호가 없는 단지를 건너뛰었다. 그런데
    공공 오픈API 에는 호가가 없어서 포털 수집이 없으면 `listing` 테이블이 **통째로 빈다**
    → 후보가 구조적으로 항상 0건. "포털 수집이 막혀도 공공API 만으로 서비스가 성립해야
    한다"(G4)와 정면 충돌이었다.

    지금은 두 경로가 **둘 다 1급 시민**이다:
      · 호가 있음 → 매물 그룹 단위 후보 (price_basis=listing)
      · 호가 없음 → 실거래 면적대 단위 후보 (price_basis=trade, group=None)
    가짜 대표 호가를 만들어 끼우지 않는다 — 그러면 하류가 그걸 호가로 믿는다.
    """
    query = getattr(repo, "recommendation_candidates", None)
    listings_of = getattr(repo, "listings_for_complex", None)
    if query is None or listings_of is None:
        logger.warning(
            "repo 에 후보 조회 메서드가 없어 후보를 조립할 수 없습니다(빈 결과). "
            "PostGIS 구현 대기: recommendation_candidates·listings_for_complex·"
            "trades_for_complex (re-arch).")
        return Assembly(notes=["후보 조회 기능이 아직 연결되지 않아 결과가 비어 있습니다."])

    trades_of = getattr(repo, "trades_for_complex", None)
    location_of = getattr(repo, "location_facts", None)

    region_codes = list(criteria.get("region_codes") or [])
    complexes = query(region_codes=region_codes, max_price_krw=budget,
                      limit=CANDIDATE_COMPLEX_LIMIT)

    out = Assembly()
    candidates = out.candidates
    if len(complexes) >= CANDIDATE_COMPLEX_LIMIT:
        # 조회 상한에 걸렸다 = **지역에 단지가 더 있는데 보지 않았다.** 말하지 않으면
        # 사용자는 이 목록이 지역 전체를 본 결과라고 믿는다(실측 강남구: 단지 506개).
        out.notes.append(
            f"조회 상한({CANDIDATE_COMPLEX_LIMIT}개 단지)에 걸려 지역 내 일부 단지는 "
            "분석하지 않았습니다. 지역을 좁히면 더 정확합니다.")

    # 깔때기: 어디서 후보가 사라지는지 로그로 남긴다("그냥 0건" 보고를 막는다).
    funnel = {"complexes": len(complexes), "with_listings": 0, "trade_only": 0,
              "no_price_evidence": 0, "listing_candidates": 0, "trade_candidates": 0}

    for c in complexes:
        listings = listings_of(c.id) or []
        trades = (trades_of(c.id) if trades_of else []) or []
        location = location_of(c.id) if location_of else None

        if listings:
            funnel["with_listings"] += 1
            # 같은 물건(중복)을 접고, 서로 다른 유닛(면적·층·동)은 각각 후보로 둔다.
            for grp in group_duplicates(listings):
                area = grp.representative.area_m2
                candidates.append(_build(c, area, trades, listings, location, group=grp))
                funnel["listing_candidates"] += 1
                if len(candidates) >= MAX_CANDIDATES:
                    return _capped(out, funnel)
            continue

        # 호가 0건 — 실거래로 후보를 세운다(G4).
        areas = _trade_area_groups(trades)
        if not areas:
            funnel["no_price_evidence"] += 1
            # ⚠️ 여기서 그냥 continue 하면 이 단지는 **어디에도 안 남는다.** 사용자가
            #    "왜 우리 단지가 없지"라고 물으면 답할 근거가 사라진다(실측: 50개 중 4개).
            out.excluded.append(excluded_record(
                complex_id=c.id, complex_name=c.name, area_m2=None,
                price_basis=None, code=EXCLUDED_NO_PRICE,
                reason=(f"가격 근거 없음 — 활성 호가가 없고 최근 {PERIOD_LADDER[-1]}개월 "
                        f"실거래가 같은 면적대에서 {MIN_SAMPLE}건 미만입니다")))
            continue
        funnel["trade_only"] += 1
        for area in areas:
            candidates.append(_build(c, area, trades, [], location, group=None))
            funnel["trade_candidates"] += 1
            if len(candidates) >= MAX_CANDIDATES:
                return _capped(out, funnel)

    _log_funnel(funnel, len(candidates))
    return out


def _capped(out: Assembly, funnel: dict[str, int]) -> Assembly:
    """후보 상한에 걸려 중단. **그 사실을 사용자에게도 말한다**(로그만 남기지 않는다)."""
    logger.info("후보 상한 %d 도달 — 이후 단지는 생략", MAX_CANDIDATES)
    _log_funnel(funnel, len(out.candidates))
    out.notes.append(
        f"후보 상한({MAX_CANDIDATES}건)에 도달해 이후 단지는 분석하지 않았습니다.")
    return out


def _build(c: Any, area: float, trades: list[Any], listings: list[Any],
           location: Any, *, group: Any) -> Candidate:
    """면적대 하나를 Candidate 로. 실거래·호가는 그 면적 오차 안의 것만 붙인다."""
    return Candidate(
        complex_id=c.id,
        complex_name=c.name,
        unit_type_id=None,                # 실거래엔 unit_type 매핑이 없다 — 면적으로 묶는다
        area_m2=area,
        group=group,
        trades=[t for t in trades if abs(t.area_m2 - area) <= AREA_TOLERANCE_M2],
        total_households=c.total_households,
        listings=[li for li in listings if abs(li.area_m2 - area) <= AREA_TOLERANCE_M2],
        location=location,
    )


def _log_funnel(funnel: dict[str, int], total: int) -> None:
    """후보 깔때기를 한 줄로 남긴다. 0건일 때 **왜 0건인지** 말할 수 있어야 한다."""
    logger.info(
        "후보 조립: 단지 %d (호가보유 %d · 실거래만 %d · 가격근거없음 %d) "
        "→ 후보 %d (호가기준 %d · 실거래기준 %d)",
        funnel["complexes"], funnel["with_listings"], funnel["trade_only"],
        funnel["no_price_evidence"], total,
        funnel["listing_candidates"], funnel["trade_candidates"])


def _persist(repo: Any, job_id: str, user_id: int, status: str,
             result: dict[str, Any]) -> None:
    """items + **제외 사유 + notes** 를 한 번에 되쓴다.

    셋을 따로 저장하지 않는다 — 하나만 성공하면 "추천은 있는데 제외 사유는 없는"
    반쪽 결과가 남고, 사용자는 그게 사유가 없어서인지 저장이 깨져서인지 구분하지 못한다.
    """
    save = getattr(repo, "save_job_result", None)
    if save is None:
        logger.error(
            "repo 에 save_job_result 가 없어 결과를 저장할 수 없습니다(job=%s). "
            "PostGIS 구현 대기(re-arch).", job_id)
        return
    try:
        save(job_id, user_id, status=status, items=result.get("items") or [],
             excluded=result.get("excluded") or [], notes=result.get("notes") or [])
    except Exception:  # noqa: BLE001
        logger.exception("추천 결과 저장 실패 job=%s", job_id)
