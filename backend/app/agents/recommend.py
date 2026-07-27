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
from app.repositories.base import BBox, BBoxError
from app.domain.affordability.engine import compute_affordability
from app.domain.affordability.models import Borrower, PropertyFacts
from app.domain.conditions import (
    FilterConditions,
    resolve_budget_override,
    resolve_filter_conditions,
    unapplied_notes,
)
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

    prefs = repo.get_preferences(user_id) if hasattr(repo, "get_preferences") else {}
    avoid = (prefs or {}).get("avoid") or {}
    prefer = (prefs or {}).get("prefer") or {}

    # 예산: 명시 override(= 희망 매매가) 우선, 없으면 **저장된 내 조건**, 그래도 없으면
    # 최대 실구매 가능액. ⚠️ 의미는 **상한**이다 — 자세한 근거는 `_budget_notes` 참조.
    # ⚠️ 요청만 읽던 시절에는 클라이언트가 한 줄 빠뜨리면 사용자가 정한 상한이 조용히
    #    사라지고 자기 한도가 쓰였다(예산이 늘어난 것처럼 보이는 실패 — 결과가 비는
    #    것보다 알아채기 어렵다). 면적과 **같은 규칙**으로 저장본을 폴백한다.
    override = resolve_budget_override(criteria, prefer)
    budget = override or afford.max_purchase_krw
    # ⚠️ 평수(전용면적)는 **요청 스키마에 아예 없어서** 추천에 도달하지 못했다 —
    #    지도는 거르고 추천은 안 거르는 상태였다(사용자 제보 2026-07-27).
    #    이제 요청 본문 ∪ 저장된 "내 조건"으로 조건을 모아 후보 선별에 실제로 건다.
    #    (요청 우선 · 저장본 폴백 — 프론트가 한 줄 빠뜨려도 조건이 증발하지 않게.)
    conditions = resolve_filter_conditions(criteria, prefer)
    # ⚠️ 가중치는 **저장만 되고 순위에 쓰이지 않던 값**이었다(슬라이더를 움직여도 결과가
    #    그대로였다). 여기서 파이프라인으로 넘겨 실제 총점에 곱한다 — 근거가 없는 축은
    #    빼고 재정규화하되 그 사실을 응답에 남긴다(app/agents/scoring.py).
    weights = (prefs or {}).get("weights") or {}

    assembly = _assemble_candidates(repo, criteria, budget, conditions)
    candidates = assembly.candidates
    ctx = AnalysisContext(
        affordability=afford, candidates=candidates,
        avoid=avoid, weights=weights, forbidden_amounts=forbidden,
        # 정비사업 판정이 목적에 따라 **정반대**가 된다(관리처분 = 투자엔 '확실',
        # 실거주엔 '이주 임박 — 부적합'). 예산 계산에만 쓰던 값을 여기로도 넘긴다.
        purpose=prop.purpose,
        # 희망가를 **명시했을 때만** 넘긴다. None 이면 파이프라인이 최대 실구매
        # 가능 금액을 쓴다(기존 동작). afford 를 조작해 우회하지 않는다 —
        # 그러면 finance finding 이 희망가를 '실구매 가능 금액'이라고 말하게 된다.
        budget_krw=override,
    )
    # 요청한 top_n 을 실제로 지킨다. 예전엔 파이프라인 기본값(10)으로 고정돼 있어
    # `top_n` 이 API 계약에만 있고 동작하지 않았다 — 이제 제외 사유가 "상위 N건 밖"을
    # 말하므로, 그 N 이 사용자가 요청한 값과 달라선 안 된다.
    top_n = max(1, min(MAX_TOP_N, int(criteria.get("top_n") or DEFAULT_TOP_N)))
    result = run_mvp_pipeline(ctx, llm=llm, top_n=top_n)
    items = result["items"]
    # 각 후보가 **희망가 대비 얼마인지** 실어 준다(프론트가 "희망가보다 1.2억 저렴"을 표시).
    _annotate_budget_gap(items, budget)
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
    notes = (list(result.get("notes") or []) + assembly.notes
             + _budget_notes(override, afford.max_purchase_krw)
             # 형식이 어긋나 **적용하지 못한** 조건, 그리고 설정돼 있지만 아직
             # 반영되지 않는 조건(역세권·1층 기피 등)을 숨기지 않고 말한다.
             + list(conditions.problems)
             + unapplied_notes(prefer, avoid))
    return "done", {"items": items, "excluded": excluded, "notes": notes}


#: 희망가 예산이 붙은 후보에 실리는 키. 프론트가 "희망가 대비 −1.2억(−13%)"을 그린다.
#: 값의 부호 규약: **음수 = 희망가보다 싸다**(가격 − 예산).
BUDGET_GAP_KEY = "budget_gap_krw"
BUDGET_GAP_PCT_KEY = "budget_gap_pct"


def _annotate_budget_gap(items: list[dict[str, Any]], budget: int | None) -> None:
    """추천 카드에 '적용 예산 대비 차액'을 붙인다.

    ⚠️ 예산이 0/None 이면(자산 미입력 등) 예산 필터 자체가 꺼진 상태다. 그때 0 을 넣으면
    "희망가와 딱 맞다"로 읽힌다 — **모르는 건 None** 으로 둔다(G2).
    비교 대상은 파이프라인이 예산 판정에 실제로 쓴 값(`est_price_krw`)이다.
    다른 값을 쓰면 "예산 안"이라며 통과시킨 후보가 화면에서는 초과로 보인다.
    """
    if not budget:
        for item in items:
            item[BUDGET_GAP_KEY] = None
            item[BUDGET_GAP_PCT_KEY] = None
        return
    for item in items:
        price = item.get("est_price_krw")
        if not price:
            item[BUDGET_GAP_KEY] = None
            item[BUDGET_GAP_PCT_KEY] = None
            continue
        gap = int(price) - int(budget)
        item[BUDGET_GAP_KEY] = gap
        item[BUDGET_GAP_PCT_KEY] = round(gap * 100.0 / int(budget), 1)


def _budget_notes(override: int | None, max_purchase_krw: int) -> list[str]:
    """희망 매매가를 예산으로 쓸 때의 고지.

    **희망가는 '상한'이다** (대역이 아니다)
    -----------------------------------------
    `budget_override_krw` 는 원래 "이 금액 이하만 보여 달라"는 뜻으로 만들어졌고,
    후보 조회(`max_price_krw`)와 하드 제외(`price > budget`)가 이미 그렇게 동작한다.
    희망가를 ±N% **대역**으로 바꾸면 (1) 같은 필드가 호출자에 따라 다른 뜻이 되고,
    (2) 희망가보다 **싼** 좋은 후보가 하한에 걸려 사라진다. 예산은 "여기까지"이지
    "여기쯤"이 아니다 — 싸게 사는 것은 실패가 아니다. 그래서 상한을 유지한다.
    (대역이 필요하면 `min_price_krw` 를 따로 만들 일이지 이 필드를 바꿀 일이 아니다.)

    다만 희망가가 최대 실구매 가능 금액을 넘으면 **말해 준다** — 안 그러면 사용자는
    슬라이더를 올린 만큼 살 수 있다고 믿는다(예산 필터가 조용히 자기 한도를 대체한다).
    여기 실리는 금액은 희망가(사용자 입력)와 최대 구매가(파생값)뿐이다 —
    보유현금·연소득 원본은 넣지 않는다(SR4-2).
    """
    if not override:
        return []
    note = (f"희망 매매가 {override:,}원을 예산 **상한**으로 적용했습니다 "
            f"— 이 금액 이하 후보만 봅니다.")
    if max_purchase_krw and override > max_purchase_krw:
        note += (f" 다만 이 금액은 산정된 최대 실구매 가능 금액 {max_purchase_krw:,}원을 "
                 f"{override - max_purchase_krw:,}원 초과합니다 — 초과분은 추가 현금이 "
                 f"필요하며, 대출 한도 안에서 해결되지 않을 수 있습니다.")
    return [note]


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
    # 예산은 희망 매매가일 수도, 최대 실구매 가능 금액일 수도 있다. 어느 쪽인지는
    # notes 가 말한다 — 여기서 단정하면 희망가를 준 사용자에게 틀린 문장이 나간다.
    EXCLUDED_OVER_BUDGET: "예산 초과 — 적용된 예산 상한을 넘습니다",
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


def _parse_bbox(raw: Any) -> tuple[BBox | None, str | None]:
    """criteria 의 `bbox` → BBox. 어긋나면 `(None, 사유 문장)`.

    ⚠️ 여기서 **조용히 None 으로 넘어가지 않는다.** bbox 가 무시된 채 전체를 뒤지면
    사용자는 "이 주변"을 눌렀는데 엉뚱한 동네가 나온 이유를 알 수 없다.
    정상 경로에서는 API 스키마가 이미 422 로 막으므로 이 문장은 뜨지 않는다.
    """
    if raw in (None, ""):
        return None, None
    try:
        return BBox.parse(str(raw)), None
    except BBoxError as exc:
        logger.warning("추천: bbox 형식 오류 — 지도 범위 조건을 적용하지 않았습니다 (%s)", exc)
        return None, (f"지도 범위(bbox) 형식이 올바르지 않아 '이 주변' 조건을 "
                      f"적용하지 않았습니다: {exc}")


#: bbox 검색이 좌표 없는 단지를 구조적으로 놓친다는 사실. **반드시 말해야 한다** —
#: 조용히 빠지면 사용자는 "그 단지는 조건에 안 맞았다"고 잘못 이해한다.
_BBOX_GEOM_NOTE = (
    "'이 주변' 검색은 좌표가 확인된 단지만 대상입니다. "
    "{scope} 단지 {total:,}개 중 {missing:,}개({missing_pct}%)는 주소 좌표가 아직 없어 "
    "이 결과에서 빠졌습니다 — 지역으로 검색하면 포함됩니다."
)
_BBOX_GEOM_NOTE_PLAIN = (
    "'이 주변' 검색은 좌표가 확인된 단지만 대상입니다. 주소 좌표가 아직 없는 단지는 "
    "이 결과에서 빠집니다 — 지역으로 검색하면 포함됩니다."
)
_BBOX_INTERSECT_NOTE = (
    "지역 선택과 '이 주변'을 함께 적용했습니다(교집합) — 두 조건을 모두 만족하는 단지만 봅니다."
)


def _bbox_scope_notes(repo: Any, region_codes: list[str], intersected: bool) -> list[str]:
    """bbox 를 쓸 때 붙는 고지 — 교집합 여부 + 좌표 미확보로 빠진 몫.

    좌표 확보율은 **그때그때 센다.** "약 5%" 같은 고정 문구를 적으면 수집이 진행돼도
    영영 낡은 값이 남고, 사용자는 틀린 숫자를 근거로 판단하게 된다.
    """
    notes: list[str] = [_BBOX_INTERSECT_NOTE] if intersected else []

    coverage = getattr(repo, "geocode_coverage", None)
    if coverage is None:
        notes.append(_BBOX_GEOM_NOTE_PLAIN)
        return notes
    try:
        with_geom, total = coverage(region_codes=region_codes)
    except Exception:  # noqa: BLE001 - 고지 하나 때문에 추천을 죽이지 않는다
        logger.exception("좌표 확보율 조회 실패 — 숫자 없이 고지합니다")
        notes.append(_BBOX_GEOM_NOTE_PLAIN)
        return notes

    missing = max(0, int(total) - int(with_geom))
    if missing <= 0:
        return notes                    # 빠진 게 없으면 겁줄 필요도 없다
    notes.append(_BBOX_GEOM_NOTE.format(
        scope="선택한 지역의" if region_codes else "전체",
        total=int(total), missing=missing,
        missing_pct=round(missing * 100.0 / int(total), 1) if total else 0.0))
    return notes


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
    #: 내 조건(평수·연식·세대수)으로 **여기서** 걸러낸 수. 제외 목록에 쌓지 않는 대신
    #: 반드시 센다 — 거르는 것과 말하지 않는 것은 다르다.
    dropped: dict[str, int] = field(default_factory=dict)

    def drop(self, key: str, n: int = 1) -> None:
        if n:
            self.dropped[key] = self.dropped.get(key, 0) + n


def _query_candidates(query: Any, *, region_codes: list[str], budget: int | None,
                      bbox: BBox | None, conditions: FilterConditions) -> list[Any]:
    """후보 조회. 조건을 **리포지토리에도** 넘겨 조회 상한이 조건 밖 단지로 차지 않게 한다.

    ⚠️ 조건 인자를 모르는 리포지토리 구현(옛 버전·테스트 더블)이면 조건 없이 다시 부른다.
       크래시로 추천을 통째로 죽이지 않되, **조용히 넘어가지도 않는다**(로그에 남긴다).
       결과가 조건을 지키는지는 이 함수가 아니라 후보 조립이 보장한다.
    """
    kwargs = conditions.repo_kwargs()
    try:
        return list(query(region_codes=region_codes, max_price_krw=budget,
                          limit=CANDIDATE_COMPLEX_LIMIT, bbox=bbox, **kwargs) or [])
    except TypeError:
        if not kwargs:
            raise
        logger.warning(
            "리포지토리가 조건 인자(%s)를 받지 않아 조건 없이 조회합니다 — "
            "조건은 후보 조립 단계에서 적용됩니다.", ", ".join(sorted(kwargs)))
        return list(query(region_codes=region_codes, max_price_krw=budget,
                          limit=CANDIDATE_COMPLEX_LIMIT, bbox=bbox) or [])


#: 조건 때문에 조회 범위에서 빠진 단지 수를 말하는 문장들. **숫자로 말한다** —
#: "일부 단지가 빠졌습니다"는 사용자가 검증할 수 없는 문장이다.
_SCOPE_AREA_NOTE = (
    "{label} 조건으로 범위 내 단지 {total:,}개 중 {dropped:,}개를 제외했습니다 — "
    "해당 면적대의 실거래·매물·타입 근거가 없거나 면적 정보가 확인되지 않은 단지입니다"
    "(확인되지 않은 것은 통과시키지 않습니다 — 모름 ≠ 조건 충족).")
_SCOPE_BUILT_NOTE = (
    "{year}년 이후 준공 조건으로 {dropped:,}개 단지를 제외했습니다"
    "{unknown}.")
_SCOPE_HOUSEHOLDS_NOTE = (
    "{n:,}세대 이상 조건으로 {dropped:,}개 단지를 제외했습니다{unknown}.")
_UNKNOWN_SUFFIX = " — 이 중 {n:,}개는 값이 확인되지 않아 제외한 것입니다(모름 ≠ 아님)"
#: 이 조회가 실패했을 때 **사용자에게** 하는 말. 조용히 빠지면 안 된다 —
#: 그러면 "조건으로 몇 개가 빠졌는지"가 그냥 사라지고, 사용자는 조건이 아무것도
#: 걸러내지 않은 것으로 읽는다(SR24-4: `statement_timeout` 이 실제로 걸리는 자리다).
_SCOPE_STATS_FAILED_NOTE = (
    "조건으로 몇 개 단지가 제외됐는지 세는 조회가 시간 내에 끝나지 않아 그 숫자는 "
    "생략했습니다 — 추천 결과 자체는 조건대로 계산됐습니다(범위를 좁히면 숫자도 나옵니다).")


def _scope_condition_notes(repo: Any, region_codes: list[str], bbox: BBox | None,
                           conditions: FilterConditions) -> list[str]:
    """조건이 범위를 얼마나 좁혔는지. 리포지토리가 세어 주지 않으면 말하지 않는다.

    **지어내지 않는다** — 숫자를 못 세는 구현에서 "일부가 빠졌습니다"라고만 하면
    사용자는 그 일부가 1개인지 400개인지 알 수 없고, 그런 고지는 없느니만 못하다.

    ⚠️ 실패는 **말한다**(SR24-4). 이 조회는 `complex` 전역을 훑으므로
    `statement_timeout`(10초)에 걸릴 수 있는 유일한 자리다. 예전에는 예외를 삼키고
    빈 목록을 돌려줘서, 타임아웃이 나면 사용자 화면에서 고지가 **그냥 사라졌다**.
    사라진 고지는 "제외된 단지가 없다"로 읽힌다 — 조용한 실패다.
    """
    stats_of = getattr(repo, "candidate_scope_stats", None)
    if stats_of is None:
        return []
    if not conditions.active:
        # 조건이 없으면 셀 것도, 할 말도 없다(아래 세 고지 모두 조건이 있어야 나온다).
        # 부수 효과가 하나 더 있다 — **조건 없는 요청에서는 전역 스캔을 아예 안 돈다**
        # (SR24-4 의 부하가 걸리는 그 쿼리다).
        return []
    try:
        stats = stats_of(region_codes=region_codes, bbox=bbox,
                         **conditions.repo_kwargs())
    except Exception:  # noqa: BLE001 - 고지 하나 때문에 추천을 죽이지 않는다
        logger.exception("조건별 제외 단지 수 조회 실패 — 숫자 없이 진행합니다")
        return [_SCOPE_STATS_FAILED_NOTE]

    notes: list[str] = []
    total = int(stats.get("scope_total") or 0)
    if conditions.area_active and stats.get("area_dropped"):
        notes.append(_SCOPE_AREA_NOTE.format(
            label=conditions.describe().split(" · ")[0],
            total=total, dropped=int(stats["area_dropped"])))
    if conditions.built_after is not None and stats.get("built_dropped"):
        unknown = int(stats.get("built_unknown") or 0)
        notes.append(_SCOPE_BUILT_NOTE.format(
            year=conditions.built_after, dropped=int(stats["built_dropped"]),
            unknown=_UNKNOWN_SUFFIX.format(n=unknown) if unknown else ""))
    if conditions.min_households is not None and stats.get("households_dropped"):
        unknown = int(stats.get("households_unknown") or 0)
        notes.append(_SCOPE_HOUSEHOLDS_NOTE.format(
            n=conditions.min_households, dropped=int(stats["households_dropped"]),
            unknown=_UNKNOWN_SUFFIX.format(n=unknown) if unknown else ""))
    return notes


def _applied_condition_notes(conditions: FilterConditions,
                             dropped: dict[str, int]) -> list[str]:
    """어떤 조건으로 돌았는지 + 그 조건이 후보를 몇 건 걷어냈는지.

    제외 목록(`excluded[]`)에 수천 건을 쌓지 않는 대신 **숫자를 말한다.**
    조건이 없으면 아무 말도 하지 않는다(늘 뜨는 고지는 읽히지 않는다).
    """
    if not conditions.active:
        return []
    notes = [f"내 조건을 적용했습니다: {conditions.describe()}. "
             "조건에 맞지 않는 후보는 추천에서 제외됩니다."]
    area_out = dropped.get("area", 0)
    if area_out:
        notes.append(f"조회된 단지에서 면적 조건 밖 후보 {area_out:,}건을 제외했습니다.")
    area_unknown = dropped.get("area_unknown", 0)
    if area_unknown:
        notes.append(
            f"전용면적이 확인되지 않은 후보 {area_unknown:,}건도 제외했습니다 — "
            "조건에 맞는지 판정할 수 없어 통과시키지 않습니다(모름 ≠ 조건 충족).")
    for key, label in (("built", "준공연도"), ("households", "세대수")):
        n = dropped.get(key, 0)
        unknown = dropped.get(f"{key}_unknown", 0)
        if n or unknown:
            tail = (f" (값이 확인되지 않아 제외한 단지 {unknown:,}개 포함)"
                    if unknown else "")
            notes.append(
                f"조회된 단지 중 {n + unknown:,}개는 {label} 조건에 맞지 않아 "
                f"제외했습니다{tail}.")
    return notes


def _assemble_candidates(repo: Any, criteria: dict[str, Any],
                         budget: int | None,
                         conditions: FilterConditions | None = None) -> Assembly:
    """repo 조회 결과를 orchestrator 의 Candidate 로 조립.

    ⚠️ **내 조건(평수·연식·세대수)의 마지막 문이 여기다** (2026-07-27)
    ------------------------------------------------------------------
    리포지토리도 같은 조건으로 조회를 좁히지만, 그건 성능(조회 상한)을 위한 것이고
    **계약을 지키는 것은 이 함수다.** 이유는 두 가지다.
      ① 후보 단위는 단지가 아니라 **단지 × 면적대**다. 84㎡ 와 59㎡ 를 함께 가진 단지는
         쿼리를 통과하지만, 84㎡ 후보는 59㎡ 조건에 맞지 않는다.
      ② 리포지토리는 duck-typing 으로 불린다 — 조건 인자를 모르는 구현이 오면
         쿼리는 조용히 조건 없이 돌아간다. 그때도 결과가 조건을 만족해야 한다.
    걸러낸 수는 `Assembly.dropped` 에 세어 `notes` 로 말한다(조용히 버리지 않는다).

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
    # ⚠️ duck-typing 인 이유: 인메모리 리포지토리(테스트용)에는 이 메서드가 없다.
    #    없으면 정비사업 판정이 전부 '미확보'가 되는데, 그건 **거짓이 아니라 사실**이다
    #    (그 리포지토리에는 실제로 정보가 없다). 다만 조용히 지나가지 않도록 한 번 알린다.
    redev_of = getattr(repo, "redevelopment_for_complex", None)
    if redev_of is None:
        logger.info("repo 에 redevelopment_for_complex 가 없어 정비사업 판정은 "
                    "'미확보'로 나갑니다(추정하지 않습니다).")

    region_codes = list(criteria.get("region_codes") or [])
    # "이 주변에서 검색"(REC-5). API 스키마가 이미 검증했지만 여기서 다시 판다 —
    # 러너는 API 를 거치지 않는 호출(스크립트·재실행)도 받는다. 형식이 어긋나면
    # **범위를 무시하고 전체를 뒤지는 대신** 그 사실을 말하고 지역 조건만 쓴다.
    bbox, bbox_note = _parse_bbox(criteria.get("bbox"))

    conditions = conditions or FilterConditions()
    out = Assembly()
    if bbox_note:
        out.notes.append(bbox_note)
    complexes = _query_candidates(query, region_codes=region_codes, budget=budget,
                                  bbox=bbox, conditions=conditions)
    if bbox is not None:
        out.notes.extend(_bbox_scope_notes(repo, region_codes, bool(region_codes)))
    if conditions.active:
        out.notes.extend(_scope_condition_notes(repo, region_codes, bbox, conditions))

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
        # 단지 단위 조건 — 리포지토리가 이미 걸렀더라도 여기서 한 번 더 본다.
        # (조건 인자를 모르는 리포지토리 구현이 와도 결과는 조건을 지켜야 한다.)
        if not conditions.built_ok(c.built_year):
            out.drop("built_unknown" if c.built_year is None else "built")
            continue
        if not conditions.households_ok(c.total_households):
            out.drop("households_unknown" if c.total_households is None
                     else "households")
            continue

        listings = listings_of(c.id) or []
        trades = (trades_of(c.id) if trades_of else []) or []
        location = location_of(c.id) if location_of else None
        # 매칭된 정비사업 구역(적재 시점에 대표지번 정확일치로 이미 이어져 있다).
        # 없으면 None → 도메인이 '확인되지 않음'으로 판정한다(없다고 말하지 않는다).
        redev = redev_of(c.id) if redev_of else None

        if listings:
            funnel["with_listings"] += 1
            # 같은 물건(중복)을 접고, 서로 다른 유닛(면적·층·동)은 각각 후보로 둔다.
            for grp in group_duplicates(listings):
                area = grp.representative.area_m2
                # 평수는 **후보 선별**이다: 59㎡를 원하는 사람에게 84㎡ 는 제외 사유가
                # 아니라 애초에 후보가 아니다. 면적 미상(0·None)도 통과시키지 않는다 —
                # 조건 대상 여부를 판정할 수 없는 것을 "맞다"고 우기지 않는다.
                if not conditions.area_ok(area):
                    out.drop("area" if conditions.area_known(area) else "area_unknown")
                    continue
                candidates.append(_build(c, area, trades, listings, location,
                                         redev, group=grp))
                funnel["listing_candidates"] += 1
                if len(candidates) >= MAX_CANDIDATES:
                    return _capped(out, funnel, conditions)
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
        # ⚠️ **여기서 걸러진 것을 '가격 근거 없음'으로 부르지 않는다.** 위 분기와 순서를
        #    바꾸면 "59㎡가 없는 단지"가 "실거래 표본이 부족한 단지"로 보고되고,
        #    사용자는 조건을 좁힌 대가를 데이터 부족으로 오해한다.
        kept = [a for a in areas if conditions.area_ok(a)]
        out.drop("area", sum(1 for a in areas
                             if a not in kept and conditions.area_known(a)))
        out.drop("area_unknown", sum(1 for a in areas if not conditions.area_known(a)))
        if not kept:
            continue
        funnel["trade_only"] += 1
        for area in kept:
            candidates.append(_build(c, area, trades, [], location,
                                     redev, group=None))
            funnel["trade_candidates"] += 1
            if len(candidates) >= MAX_CANDIDATES:
                return _capped(out, funnel, conditions)

    _log_funnel(funnel, len(candidates))
    out.notes.extend(_applied_condition_notes(conditions, out.dropped))
    return out


def _capped(out: Assembly, funnel: dict[str, int],
            conditions: FilterConditions | None = None) -> Assembly:
    """후보 상한에 걸려 중단. **그 사실을 사용자에게도 말한다**(로그만 남기지 않는다)."""
    logger.info("후보 상한 %d 도달 — 이후 단지는 생략", MAX_CANDIDATES)
    _log_funnel(funnel, len(out.candidates))
    out.notes.append(
        f"후보 상한({MAX_CANDIDATES}건)에 도달해 이후 단지는 분석하지 않았습니다.")
    # 상한에 걸려 일찍 끝나도 **적용된 조건은 말한다** — 조건 고지가 경로에 따라
    # 사라지면 사용자는 어떤 조건으로 나온 결과인지 알 수 없다.
    if conditions is not None:
        out.notes.extend(_applied_condition_notes(conditions, out.dropped))
    return out


def _build(c: Any, area: float, trades: list[Any], listings: list[Any],
           location: Any, redevelopment: Any = None, *, group: Any) -> Candidate:
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
        redevelopment=redevelopment,
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
