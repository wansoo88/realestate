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
      (4) recommendation_item/finding 저장 · status 'done'
    → GET /recommendations/{id} 로 결과

데이터가 없으면(수집 전) **빈 결과가 정상**이다 — 지어내지 않는다.
어떤 예외도 밖으로 던지지 않는다. 실패하면 job 을 'error' 로 남긴다 —
'queued' 로 영영 멈춰 있는 게 가장 위험하다(worker.py 주석 참조).
"""
from __future__ import annotations

import logging
from typing import Any

from app.agents.llm import LLMClient
from app.agents.orchestrator import AnalysisContext, Candidate, run_mvp_pipeline
from app.core.security import decrypt_amount, load_key
from app.domain.affordability.engine import compute_affordability
from app.domain.affordability.models import Borrower, PropertyFacts
from app.domain.listings.dedup import AREA_TOLERANCE_M2, group_duplicates
from app.domain.rules.loader import load_rules
from app.domain.valuation.models import MIN_SAMPLE, PERIOD_LADDER, TradeRow
from app.domain.valuation.stats import eligible_trades

logger = logging.getLogger("app.agents.recommend")

#: 후보로 볼 단지 상한 — LLM/통계 비용을 태우는 대상이라 넉넉하되 유한하게.
CANDIDATE_COMPLEX_LIMIT = 50
#: 조립된 Candidate 총량 상한(단지 × 면적그룹이 폭증하지 않게).
MAX_CANDIDATES = 200
#: 호가가 없는 단지에서 실거래로 세울 면적대 수(거래 많은 순).
#: 한 단지가 후보 목록을 독식하지 않게 막는다.
TRADE_AREA_GROUPS_PER_COMPLEX = 3

#: 자산 금액 필드 ↔ 암호문 컬럼
_AMOUNT_FIELDS = (
    ("cash_krw", "cash_krw_enc"),
    ("income_krw", "income_krw_enc"),
    ("existing_loan_krw", "existing_loan_krw_enc"),
)


def run_recommendation_job(
    *, repo: Any, settings: Any, job_id: str, user_id: int,
    criteria: dict[str, Any], llm: LLMClient | None = None,
) -> None:
    """BackgroundTask 진입점. **절대 예외를 던지지 않는다.**"""
    status, items = "error", []
    try:
        status, items = _analyze(repo, settings, user_id, criteria, llm)
    except Exception:  # noqa: BLE001 - 백그라운드라 삼켜서 job 상태로만 남긴다
        logger.exception("추천 작업 실패 job=%s", job_id)
        status, items = "error", []
    _persist(repo, job_id, user_id, status, items)


def _analyze(repo: Any, settings: Any, user_id: int, criteria: dict[str, Any],
             llm: LLMClient | None) -> tuple[str, list[dict[str, Any]]]:
    # 세율·키는 여기서 로드한다(BackgroundTask 는 Depends 를 못 받는다).
    rules = load_rules(settings.tax_rules_path)          # 실패 시 상위 except → error
    key = load_key(settings.field_encryption_key)

    profile = repo.get_profile(user_id)
    if profile is None:
        # 자산 미입력 → 예산을 알 수 없다. 지어내지 않고 빈 결과.
        logger.info("추천: 프로필 없음 → 빈 결과 (user=%s)", user_id)
        return "done", []

    borrower, forbidden = _borrower_from_profile(profile, user_id, key)
    prop = PropertyFacts(purpose=str(criteria.get("purpose") or "live"))
    afford = compute_affordability(borrower, rules, prop=prop)

    # 예산: 명시 override 우선, 없으면 실구매 가능액.
    budget = criteria.get("budget_override_krw") or afford.max_purchase_krw

    prefs = repo.get_preferences(user_id) if hasattr(repo, "get_preferences") else {}
    avoid = (prefs or {}).get("avoid") or {}

    candidates = _assemble_candidates(repo, criteria, budget)
    ctx = AnalysisContext(
        affordability=afford, candidates=candidates,
        avoid=avoid, forbidden_amounts=forbidden,
    )
    result = run_mvp_pipeline(ctx, llm=llm)
    items = result["items"]
    trade_basis = sum(1 for it in items if it.get("price_basis") == "trade")
    logger.info(
        "추천 완료 user=%s 후보=%d 추천=%d (실거래기준 %d · 호가기준 %d) 제외=%d",
        user_id, len(candidates), len(items), trade_basis, len(items) - trade_basis,
        len(result.get("excluded") or []))
    return "done", items


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


def _assemble_candidates(repo: Any, criteria: dict[str, Any],
                         budget: int | None) -> list[Candidate]:
    """repo 조회 결과를 orchestrator 의 Candidate 로 조립.

    후보/매물/실거래 조회 메서드가 없으면(PostGIS 구현 대기) **빈 리스트** —
    지어내지 않고, 크래시하지도 않는다.

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
        return []

    trades_of = getattr(repo, "trades_for_complex", None)
    location_of = getattr(repo, "location_facts", None)

    region_codes = list(criteria.get("region_codes") or [])
    complexes = query(region_codes=region_codes, max_price_krw=budget,
                      limit=CANDIDATE_COMPLEX_LIMIT)

    candidates: list[Candidate] = []
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
                    logger.info("후보 상한 %d 도달 — 이후 단지는 생략", MAX_CANDIDATES)
                    _log_funnel(funnel, len(candidates))
                    return candidates
            continue

        # 호가 0건 — 실거래로 후보를 세운다(G4).
        areas = _trade_area_groups(trades)
        if not areas:
            funnel["no_price_evidence"] += 1
            continue
        funnel["trade_only"] += 1
        for area in areas:
            candidates.append(_build(c, area, trades, [], location, group=None))
            funnel["trade_candidates"] += 1
            if len(candidates) >= MAX_CANDIDATES:
                logger.info("후보 상한 %d 도달 — 이후 단지는 생략", MAX_CANDIDATES)
                _log_funnel(funnel, len(candidates))
                return candidates

    _log_funnel(funnel, len(candidates))
    return candidates


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
             items: list[dict[str, Any]]) -> None:
    save = getattr(repo, "save_job_result", None)
    if save is None:
        logger.error(
            "repo 에 save_job_result 가 없어 결과를 저장할 수 없습니다(job=%s). "
            "PostGIS 구현 대기(re-arch).", job_id)
        return
    try:
        save(job_id, user_id, status=status, items=items)
    except Exception:  # noqa: BLE001
        logger.exception("추천 결과 저장 실패 job=%s", job_id)
