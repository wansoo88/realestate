"""MVP 에이전트 파이프라인.

설계 근거: docs/02-design/agents/README.md §2

    [1] finance-tax-advisor   (규칙 계산 · LLM 없음)  → 예산 상한
    [2] listing-researcher    (DB/규칙)             → 후보 축소
    [3] valuation-trader · location-analyst (규칙 + LLM 설명)
    [4] portfolio-advisor     (LLM 종합)

순서가 중요하다. 예산 상한 없이 분석하면 **살 수 없는 집에 API 비용을 태운다.**
"""
from __future__ import annotations

import datetime as dt
import logging
from collections.abc import Iterable
from dataclasses import dataclass, field
from typing import Any

from app.agents.base import (
    AgentOutputError,
    Evidence,
    Finding,
    PromptSafetyError,
    Risk,
    assert_no_secrets,
    data_block,
    insufficient,
    scan_injection,
    validate_finding,
)
from app.agents.llm import LLMClient, LLMError
from app.domain.affordability.models import AffordabilityResult
from app.domain.listings.dedup import ListingGroup, trust_score
from app.domain.location.analysis import evaluate_location
from app.domain.location.models import LocationAssessment, LocationFacts
from app.domain.valuation.models import ListingRow, TradeRow
from app.domain.valuation.stats import ask_gap_pct, fair_price_band, liquidity

logger = logging.getLogger("agents")

DISCLAIMER = ("투자 권유가 아니며 개인 판단을 돕는 참고 자료입니다. "
              "실제 계약 전 현장 확인과 전문가 상담을 권합니다.")

#: 실거래 신고 지연 — 모든 시세 판단에 붙는 상수 리스크
DELAY_RISK = Risk("medium", "실거래는 신고까지 최대 30일이 걸려 최근 거래가 반영되지 않았을 수 있습니다.")


@dataclass
class Candidate:
    complex_id: int
    complex_name: str
    unit_type_id: int | None
    area_m2: float
    group: ListingGroup
    trades: list[TradeRow] = field(default_factory=list)
    total_households: int | None = None
    listings: list[ListingRow] = field(default_factory=list)
    #: 입지 사실(학군·교통·인프라·유해요소). 리포지토리가 공간쿼리로 채워 넘긴다.
    #: 없으면 location-analyst 는 판단 보류를 낸다(지어내지 않는다).
    location: LocationFacts | None = None


@dataclass
class AnalysisContext:
    """파이프라인 입력.

    ⚠️ **1차 방어는 이 구조다.** 이 컨텍스트는 사용자 자산 **원본 금액을 담지 않고**
    `affordability` **계산 결과(파생값)** 만 가진다. 각 Finding 도 한도·부대비용 같은
    파생값만 프롬프트에 싣는다. 즉 원본 자산은 애초에 LLM 경로로 갈 수 없다.
    `forbidden_amounts` 는 그 위에 얹는 **best-effort tripwire** 일 뿐 주 방어가 아니다.
    """

    affordability: AffordabilityResult
    candidates: list[Candidate]
    avoid: dict[str, Any] = field(default_factory=dict)
    as_of: dt.date = field(default_factory=dt.date.today)
    #: tripwire 검사값(프롬프트 구성에는 쓰지 않는다). 비워두면 파이프라인이
    #: affordability 파생값으로 보강하고, 그래도 비면 fail-loud 로 막는다.
    forbidden_amounts: list[int] = field(default_factory=list)


# ---------------------------------------------------------------------------
# [1] finance-tax-advisor — LLM 없음
# ---------------------------------------------------------------------------

def finance_finding(result: AffordabilityResult) -> Finding:
    evidence = [
        Evidence(claim=e.get("claim", ""), source=e.get("source", ""),
                 as_of=e.get("as_of"), source_url=e.get("source_url"))
        for e in result.evidence
    ]
    if not evidence:
        return insufficient("finance-tax-advisor", ["세율 근거 없음"])

    return validate_finding(Finding(
        agent_id="finance-tax-advisor",
        verdict=f"실구매 가능 {result.max_purchase_krw:,}원",
        rationale=(
            f"취득 부대비용 {result.costs.total_krw:,}원을 포함해 "
            f"{result.max_purchase_krw:,}원까지 가능합니다. "
            f"한도를 묶는 것은 {result.binding_constraint} 입니다."
        ),
        evidence=evidence,
        risks=[Risk("medium", "실제 한도는 금융기관 심사·신용등급에 따라 달라집니다.")],
        score=None,
        confidence=0.95,
    ))


# ---------------------------------------------------------------------------
# [2] listing-researcher — 규칙
# ---------------------------------------------------------------------------

def listing_finding(candidate: Candidate, median_krw: int | None,
                    as_of: dt.date) -> Finding:
    score, signals = trust_score(candidate.group,
                                 median_price_krw=median_krw, as_of=as_of)
    rep = candidate.group.representative

    risks: list[Risk] = []
    if score < 0.7:
        risks.append(Risk("medium", "매물 신뢰도가 낮습니다: " + "; ".join(signals)))
    if candidate.group.duplicate_count >= 4:
        risks.append(Risk("low",
                          f"{candidate.group.duplicate_count}개 중개사에 중복 등록되어 있습니다."))

    return validate_finding(Finding(
        agent_id="listing-researcher",
        verdict="확인 필요" if score < 0.7 else "정상 매물",
        rationale=(f"호가 {rep.ask_price_krw:,}원, {rep.floor}층. "
                   + ("특이사항: " + "; ".join(signals) if signals else "특이 신호 없음.")),
        evidence=[Evidence(claim=f"활성 매물 {candidate.group.duplicate_count}건",
                           source="포털 매물 수집", as_of=as_of.isoformat())],
        risks=risks,
        score=round(score * 100, 1),
        confidence=0.8,
    ))


# ---------------------------------------------------------------------------
# [3] valuation-trader — 규칙 계산 + (선택) LLM 설명
# ---------------------------------------------------------------------------

def valuation_finding(candidate: Candidate, as_of: dt.date) -> Finding:
    band = fair_price_band(candidate.trades, area_m2=candidate.area_m2,
                           as_of=as_of,
                           target_floor=candidate.group.representative.floor)
    if not band.available:
        return insufficient("valuation-trader", [band.reason or "실거래 표본 부족"])

    ask = candidate.group.representative.ask_price_krw
    gap = ask_gap_pct(ask, band)
    liq = liquidity(candidate.trades, candidate.listings,
                    candidate.total_households, as_of=as_of)

    if gap is None:
        verdict = "판단 보류"
    elif gap <= -10:
        verdict = "적정가 하단 — 급매 가능"
    elif gap >= 10:
        verdict = "적정가 상단"
    else:
        verdict = "적정가 범위"

    risks = [DELAY_RISK]
    if band.expanded:
        risks.append(Risk("low",
                          f"표본이 부족해 최근 {band.period_months}개월까지 확장해 계산했습니다."))
    if liq.grade == "나쁨":
        risks.append(Risk("medium", "거래 회전율이 낮아 매도에 시간이 걸릴 수 있습니다."))

    # 점수: 갭이 작을수록 좋다(0% 기준). ±20% 를 0점 경계로 본다.
    score = max(0.0, min(100.0, 100.0 - abs(gap) * 5)) if gap is not None else None

    return validate_finding(Finding(
        agent_id="valuation-trader",
        verdict=verdict,
        rationale=(
            f"동일 타입 {band.sample_size}건 중위 {band.median_krw:,}원 대비 "
            f"호가 {ask:,}원은 {gap:+.1f}% 입니다. 환금성은 {liq.grade}."
        ),
        evidence=band.to_evidence(as_of=as_of) and [
            Evidence(claim=f"중위 실거래가 {band.median_krw:,}원",
                     source="국토교통부 실거래가",
                     as_of=as_of.isoformat(), data_rows=band.sample_size)
        ],
        risks=risks,
        score=score,
        confidence=0.85,
    ))


# ---------------------------------------------------------------------------
# [3] location-analyst — 공간쿼리 결과를 근거로. 데이터 없으면 판단 보류
# ---------------------------------------------------------------------------

def _assessment_to_finding(assessment: LocationAssessment) -> Finding:
    """입지 종합 판정을 Finding 으로. 근거가 하나도 없으면 판단 보류."""
    if not assessment.excluded and not assessment.has_evidence:
        return insufficient("location-analyst",
                            list(assessment.missing)
                            or ["입지 판단에 쓸 실측 데이터 부족"])

    evidence = [Evidence(claim=e["claim"], source=e["source"], as_of=e.get("as_of"))
                for e in assessment.evidence]
    risks = [Risk(r["severity"], r["detail"]) for r in assessment.risks]

    if assessment.excluded:
        # 기피 조건 해당 — 근거가 아니라 제외 사유를 남긴다.
        return validate_finding(Finding(
            agent_id="location-analyst",
            verdict=assessment.verdict,
            rationale=assessment.rationale,
            evidence=evidence or [Evidence(
                claim=assessment.rationale, source="유해요소 반경 판정", as_of=None)],
            risks=[Risk("high", r) for r in assessment.exclusion_reasons] or risks,
            score=None,
            confidence=assessment.confidence,
        ))

    return validate_finding(Finding(
        agent_id="location-analyst",
        verdict=assessment.verdict,
        rationale=assessment.rationale,
        evidence=evidence,
        risks=risks,
        score=assessment.score,
        confidence=assessment.confidence,
    ))


def location_finding(candidate: Candidate, as_of: dt.date, *,
                     avoid: Iterable[str] | None = None) -> Finding:
    """입지 판정. 입지 사실이 없으면 지어내지 않고 판단 보류."""
    if candidate.location is None:
        return insufficient("location-analyst",
                            ["입지 데이터(학군·교통·인프라) 미수집"])
    assessment = evaluate_location(candidate.location, avoid=avoid, as_of=as_of)
    return _assessment_to_finding(assessment)


# ---------------------------------------------------------------------------
# [4] portfolio-advisor — LLM 종합
# ---------------------------------------------------------------------------

PORTFOLIO_SYSTEM = """당신은 부동산 분석 결과를 요약하는 역할입니다.

절대 규칙:
1. 제공된 분석 결과에 **없는 사실을 추가하지 마세요.**
2. 각 문장은 제공된 evidence 중 하나에 대응해야 합니다.
3. 미래 가격 상승을 단정하지 마세요. "오릅니다" 같은 표현 금지.
4. 투자를 권유하는 표현을 쓰지 마세요.
5. 확신할 수 없으면 "확인 필요"라고 쓰세요.
6. 단점(why_not)을 반드시 포함하세요. 장점만 나열하면 안 됩니다.

JSON 으로만 답하세요:
{"headline": "한 줄 요약", "why": ["근거1","근거2"], "why_not": ["리스크1"],
 "next_actions": ["현장에서 확인할 것"]}"""


def _fallback_summary(findings: list[Finding]) -> dict[str, Any]:
    """LLM 이 실패해도 제품이 죽지 않게 규칙 기반으로 요약한다.

    문장은 투박하지만 **근거는 정확하다.** 그럴듯한 문장보다 정확한 근거가 낫다.
    """
    why = [f.rationale for f in findings if not f.missing and f.rationale]
    why_not = [r.detail for f in findings for r in f.risks]
    return {
        "headline": "분석 요약(자동 생성)",
        "why": why[:5],
        "why_not": why_not[:5] or ["확인된 하방 리스크 없음 — 데이터 부족일 수 있습니다."],
        "next_actions": ["현장 방문으로 소음·일조·주차 확인",
                         "등기부등본으로 권리관계 확인(본 시스템은 확인하지 않음)"],
        "generated_by": "fallback",
    }


def portfolio_summary(findings: list[Finding], llm: LLMClient | None,
                      forbidden_amounts: list[int]) -> dict[str, Any]:
    if llm is None:
        # 외부 전송이 없다 → tripwire 불필요(구조적 방어만으로 충분).
        return _fallback_summary(findings)

    # fail-loud: 실제 외부(LLM) 전송 경로인데 tripwire 검사값이 하나도 없으면
    # "검사할 게 없어서 통과"라는 조용한 no-op 을 만들지 않고 **막는다**.
    # (best-effort 그물이라도 실경로에서 무장 해제된 채 나가지 않게 강제)
    if not [v for v in forbidden_amounts if v and v >= 1_000_000]:
        raise PromptSafetyError(
            "forbidden_amounts 가 비어 자산유출 tripwire 가 무장 해제됩니다. "
            "affordability 원본에서 파생한 검사값을 넘기세요. (security.md §6)"
        )

    payload = [f.to_dict() for f in findings]
    user = data_block("analysis_results", payload) + \
        "\n\n위 분석 결과만으로 요약하세요. 없는 사실을 만들지 마세요."

    # 자산 원본 금액이 섞였는지 호출 직전에 걸러낸다 (best-effort tripwire, security.md §6).
    # ⚠️ 주 방어는 이게 아니라 finding 이 파생값만 싣는 구조다.
    assert_no_secrets(user, forbidden_amounts)

    for hit in scan_injection(user):
        logger.warning("수집 데이터에서 인젝션 의심 패턴 발견: %s", hit)

    try:
        raw = llm.complete_json(system=PORTFOLIO_SYSTEM, user=user)
    except LLMError as exc:
        logger.warning("LLM 요약 실패, 규칙 기반으로 대체합니다: %s", exc)
        return _fallback_summary(findings)

    # 스키마 검증 — 벗어나면 폐기하고 폴백
    if not isinstance(raw.get("headline"), str) or not isinstance(raw.get("why"), list):
        logger.warning("LLM 응답이 스키마를 벗어나 폐기합니다")
        return _fallback_summary(findings)

    why_not = raw.get("why_not")
    if not isinstance(why_not, list) or not why_not:
        # 단점을 안 쓰면 우리가 채운다. 장점만 있는 리포트는 내보내지 않는다.
        why_not = [r.detail for f in findings for r in f.risks] or \
            ["확인된 하방 리스크 없음 — 데이터 부족일 수 있습니다."]

    return {
        "headline": raw["headline"],
        "why": [str(x) for x in raw["why"]][:6],
        "why_not": [str(x) for x in why_not][:6],
        "next_actions": [str(x) for x in (raw.get("next_actions") or [])][:5],
        "generated_by": "llm",
    }


# ---------------------------------------------------------------------------
# 파이프라인
# ---------------------------------------------------------------------------

def _avoid_tokens(avoid: dict[str, Any] | None) -> list[str]:
    """느슨하게 들어오는 기피 조건에서 문자열 토큰만 긁어낸다.

    입지와 무관한 토큰(1층·재건축 등)은 하위 로직(``_canonical_avoids``)이 걸러낸다.
    """
    tokens: list[str] = []
    for key, val in (avoid or {}).items():
        tokens.append(str(key))
        if isinstance(val, str):
            tokens.append(val)
        elif isinstance(val, (list, tuple, set)):
            tokens += [str(x) for x in val]
    return tokens


def _derive_forbidden(ctx: AnalysisContext) -> list[int]:
    """tripwire 검사값을 방어적으로 보강한다.

    호출자가 `forbidden_amounts` 를 채워 넘기지 않아도(A5) affordability 파생값 중
    **원본에 가까운 값**을 자동으로 포함시켜, 실경로에서 tripwire 가 완전 no-op 이 되지 않게 한다.
    (income·기존대출 원본은 AffordabilityResult 에 남지 않으므로, 그건 호출자가 넘겨야 하고
     안 넘기면 `portfolio_summary` 의 fail-loud 가 막는다.)
    """
    vals: set[int] = {v for v in ctx.forbidden_amounts if v}
    usable_cash = getattr(ctx.affordability, "usable_cash_krw", 0)
    if usable_cash:
        vals.add(usable_cash)
    return sorted(vals)


def run_mvp_pipeline(ctx: AnalysisContext, *, llm: LLMClient | None = None,
                     top_n: int = 10) -> dict[str, Any]:
    """MVP 5종 파이프라인 실행. 반환값은 `/recommendations` 응답의 items."""
    finance = finance_finding(ctx.affordability)
    budget = ctx.affordability.max_purchase_krw
    avoid_tokens = _avoid_tokens(ctx.avoid)
    forbidden = _derive_forbidden(ctx)

    items: list[dict[str, Any]] = []
    excluded: list[dict[str, Any]] = []

    for cand in ctx.candidates:
        rep = cand.group.representative

        # 하드 제외 ① — 아무리 점수가 높아도 못 사는 집은 추천이 아니다.
        if budget and rep.ask_price_krw > budget:
            excluded.append({
                "complex_id": cand.complex_id,
                "reason": f"예산 초과 (호가 {rep.ask_price_krw:,}원 > 한도 {budget:,}원)",
            })
            continue

        # 하드 제외 ② — 기피 조건은 가점 상쇄가 아니라 제외다(F5).
        loc_assess = (evaluate_location(cand.location, avoid=avoid_tokens, as_of=ctx.as_of)
                      if cand.location is not None else None)
        if loc_assess is not None and loc_assess.excluded:
            excluded.append({
                "complex_id": cand.complex_id,
                "reason": "; ".join(loc_assess.exclusion_reasons),
            })
            continue

        valuation = valuation_finding(cand, ctx.as_of)
        median = None
        if valuation.evidence and valuation.evidence[0].data_rows:
            band = fair_price_band(cand.trades, area_m2=cand.area_m2, as_of=ctx.as_of)
            median = band.median_krw

        location = (_assessment_to_finding(loc_assess) if loc_assess is not None
                    else insufficient("location-analyst",
                                      ["입지 데이터(학군·교통·인프라) 미수집"]))
        findings = [
            finance,
            listing_finding(cand, median, ctx.as_of),
            valuation,
            location,
        ]
        scored = [f for f in findings if f.score is not None]
        total = (sum(f.score * f.confidence for f in scored) /
                 sum(f.confidence for f in scored)) if scored else 0.0

        summary = portfolio_summary(findings, llm, forbidden)
        items.append({
            "complex": {"id": cand.complex_id, "name": cand.complex_name},
            "unit_type": {"area_m2": cand.area_m2},
            # 동 추천은 호가에 표기된 경우만. 추정이면 confidence 를 낮게 실어 보낸다.
            "building": ({"id": rep.building_id, "confidence": 0.6,
                          "basis": "listing_reported"} if rep.building_id else None),
            "ask_price_krw": rep.ask_price_krw,
            "total_score": round(total, 1),
            # MVP 에는 타이밍 분석가가 없다. 없는 기능을 있는 척하지 않는다.
            "timing_signal": "unknown",
            "headline": summary["headline"],
            "why": summary["why"],
            "why_not": summary["why_not"],
            "next_actions": summary["next_actions"],
            "findings": [f.to_dict() for f in findings],
        })

    items.sort(key=lambda x: x["total_score"], reverse=True)
    for rank, item in enumerate(items[:top_n], start=1):
        item["rank"] = rank

    return {
        "items": items[:top_n],
        "excluded": excluded,
        "notes": ["타이밍 분석(market-timing-analyst)은 2차 기능입니다.",
                  "입지 분석은 데이터 수집 후 제공됩니다."],
        "disclaimer": DISCLAIMER,
    }
