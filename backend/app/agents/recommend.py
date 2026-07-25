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

logger = logging.getLogger("app.agents.recommend")

#: 후보로 볼 단지 상한 — LLM/통계 비용을 태우는 대상이라 넉넉하되 유한하게.
CANDIDATE_COMPLEX_LIMIT = 50
#: 조립된 Candidate 총량 상한(단지 × 면적그룹이 폭증하지 않게).
MAX_CANDIDATES = 200

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
    logger.info("추천 완료 user=%s 후보=%d 추천=%d",
                user_id, len(candidates), len(result["items"]))
    return "done", result["items"]


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


def _assemble_candidates(repo: Any, criteria: dict[str, Any],
                         budget: int | None) -> list[Candidate]:
    """repo 조회 결과를 orchestrator 의 Candidate 로 조립.

    후보/매물/실거래 조회 메서드가 없으면(PostGIS 구현 대기) **빈 리스트** —
    지어내지 않고, 크래시하지도 않는다.
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
    for c in complexes:
        listings = listings_of(c.id) or []
        if not listings:
            continue                          # 호가가 없으면 매수 후보로 세울 수 없다
        trades = (trades_of(c.id) if trades_of else []) or []
        location = location_of(c.id) if location_of else None

        # 같은 물건(중복)을 접고, 서로 다른 유닛(면적·층·동)은 각각 후보로 둔다.
        for grp in group_duplicates(listings):
            area = grp.representative.area_m2
            candidates.append(Candidate(
                complex_id=c.id,
                complex_name=c.name,
                unit_type_id=None,            # 실거래엔 unit_type 매핑이 없다 — 면적으로 묶는다
                area_m2=area,
                group=grp,
                trades=[t for t in trades if abs(t.area_m2 - area) <= AREA_TOLERANCE_M2],
                total_households=c.total_households,
                listings=[l for l in listings if abs(l.area_m2 - area) <= AREA_TOLERANCE_M2],
                location=location,
            ))
            if len(candidates) >= MAX_CANDIDATES:
                logger.info("후보 상한 %d 도달 — 이후 단지는 생략", MAX_CANDIDATES)
                return candidates
    return candidates


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
