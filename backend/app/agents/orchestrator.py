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
from app.domain.valuation.models import DongValuation, ListingRow, TradeRow
from app.domain.valuation.stats import (
    ask_gap_pct,
    dong_effect,
    fair_price_band,
    liquidity,
)

logger = logging.getLogger("agents")

DISCLAIMER = ("투자 권유가 아니며 개인 판단을 돕는 참고 자료입니다. "
              "실제 계약 전 현장 확인과 전문가 상담을 권합니다.")

#: 실거래 신고 지연 — 모든 시세 판단에 붙는 상수 리스크
DELAY_RISK = Risk("medium", "실거래는 신고까지 최대 30일이 걸려 최근 거래가 반영되지 않았을 수 있습니다.")

# --- 가격 근거 (price_basis) ------------------------------------------------
#
# 이 제품에서 **호가와 실거래는 같은 숫자가 아니다.**
#   listing = "지금 이 값에 살 수 있다"  (매도인이 부른 값 · 지금 존재하는 물건)
#   trade   = "최근 이 정도에 거래됐다"  (이미 끝난 거래 · 지금 살 수 있는 물건은 없음)
#
# 공공 API 에는 호가가 없다. 포털 수집이 막히면 `listing` 테이블이 통째로 비고,
# 호가를 요구하는 설계는 후보를 **구조적으로 0건**으로 만든다(CHARTER G4 위반).
# 그래서 실거래만으로도 후보를 세우되, **어느 쪽 근거인지 응답에 명시**한다(G2).
# 실거래 중위가를 호가처럼 위장하지 않는다 — 위장하는 순간 하류(프론트·리포트)가
# "지금 이 값에 살 수 있다"로 읽는다.
PRICE_BASIS_LISTING = "listing"
PRICE_BASIS_TRADE = "trade"

# --- 제외 사유 (excluded) ---------------------------------------------------
#
# 이 제품의 신뢰는 **"왜 이건 안 나왔지"에 답하는 것**에 달려 있다. 추천 목록만 주면
# 사용자는 자기가 아는 단지가 빠졌을 때 결과 전체를 의심한다. 그래서 떨어뜨린 후보를
# 사유와 함께 남기고, 저장·조회 경로로 끝까지 실어 보낸다(api-spec.md §5.2).
#
# ⚠️ 사유 문장에 **사용자 자산 원본 금액을 적지 않는다**(security.md §6 · SR4-2).
#    한도·초과분 같은 **파생값**까지가 허용선이다 — 원본 현금·소득은 애초에 이 계층에
#    들어오지 않는다(AnalysisContext 가 파생값만 갖는다). 러너가 그 위에 그물을 하나 더 건다.
EXCLUDED_NO_PRICE = "no_price_evidence"      # 호가 없음 + 실거래 표본 부족
EXCLUDED_OVER_BUDGET = "over_budget"         # 예산 초과
EXCLUDED_AVOIDED = "avoided"                 # 사용자가 기피한 조건에 해당(F5)
EXCLUDED_RANK_CUTOFF = "below_rank_cutoff"   # 분석은 통과했지만 상위 N 밖

#: 실거래 기준 후보에 붙는 표준 문구. UI 가 그대로 노출해도 되도록 완결형으로 둔다.
TRADE_BASIS_NOTE = ("현재 등록된 매물이 없습니다 — 최근 실거래 기준 추정가입니다. "
                    "실제 매수 가능 가격은 다를 수 있습니다.")
#: 실거래 기준 후보의 판정 문구(호가 갭 판정을 대체한다).
TRADE_BASIS_VERDICT = "현재 매물 없음 — 최근 실거래 기준"


@dataclass
class Candidate:
    complex_id: int
    complex_name: str
    unit_type_id: int | None
    area_m2: float
    #: 대표 호가 그룹. **None 일 수 있다(1급 시민).**
    #: 공공 API 에는 호가가 없으므로 호가 0건인 단지도 실거래 기준으로 후보가 된다.
    #: ⚠️ 여기에 가짜 대표 호가를 만들어 끼우지 말 것 — 하류가 그걸 진짜 호가로 믿는다.
    group: ListingGroup | None = None
    trades: list[TradeRow] = field(default_factory=list)
    total_households: int | None = None
    listings: list[ListingRow] = field(default_factory=list)
    #: 입지 사실(학군·교통·인프라·유해요소). 리포지토리가 공간쿼리로 채워 넘긴다.
    #: 없으면 location-analyst 는 판단 보류를 낸다(지어내지 않는다).
    location: LocationFacts | None = None

    @property
    def price_basis(self) -> str:
        """이 후보의 가격 근거가 호가인가 실거래인가."""
        return PRICE_BASIS_LISTING if self.group is not None else PRICE_BASIS_TRADE

    @property
    def ask_price_krw(self) -> int | None:
        """대표 호가. 호가가 없으면 **None** — 실거래 중위로 채우지 않는다."""
        return self.group.representative.ask_price_krw if self.group is not None else None

    @property
    def target_floor(self) -> int | None:
        """층 보정 대상 층. 호가가 없으면 대상 층 자체가 없다(보정하지 않는다)."""
        return self.group.representative.floor if self.group is not None else None


def reference_band(candidate: Candidate, as_of: dt.date):
    """이 후보의 적정가 밴드. 호가가 있으면 그 층으로 보정한다.

    호가가 없으면 보정할 대상 층이 없으므로 단지·면적 기준 밴드를 그대로 쓴다.
    """
    return fair_price_band(candidate.trades, area_m2=candidate.area_m2, as_of=as_of,
                           target_floor=candidate.target_floor)


def reference_price_krw(candidate: Candidate, band: Any) -> int | None:
    """예산 판정·표시에 쓸 **기준가**와 그 근거를 정한다.

    호가가 있으면 호가(사실), 없으면 실거래 중위(추정)다. 둘 다 없으면 **None** —
    가격 근거가 없는 후보는 예산을 따질 수도, 추천할 수도 없다(지어내지 않는다).
    """
    if candidate.group is not None:
        return candidate.ask_price_krw
    return band.median_krw if band.available else None


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
    if candidate.group is None:
        # 평가할 매물 자체가 없다. "정상 매물"도 "허위 의심"도 아니다 —
        # 공공 API 에는 호가가 없으므로 이건 **정상적인 데이터 없음**이다(G4).
        return insufficient(
            "listing-researcher",
            ["현재 등록된 호가 매물 없음 — 공공 오픈API 에는 호가가 포함되지 않습니다"])

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

def valuation_finding(candidate: Candidate, as_of: dt.date, *,
                      band: Any | None = None) -> Finding:
    """시세 판정. **호가 유무에 따라 판정 축이 다르다.**

    호가 있음 → 호가 갭(ask_gap)으로 "적정가 상단/하단"을 판정한다.
    호가 없음 → 비교할 호가가 없다. 갭을 계산하지 않고(None) **적정가 밴드 자체**를
                근거로 제시한다. 없는 숫자를 만들어 내면 그 순간 G2 위반이다.
    """
    band = reference_band(candidate, as_of) if band is None else band
    if not band.available:
        return insufficient("valuation-trader", [band.reason or "실거래 표본 부족"])

    ask = candidate.ask_price_krw
    # ⚠️ 호가가 없으면 갭은 **None** 이다. 실거래 중위를 호가 자리에 넣어 0% 를 만들면
    #    "적정가 범위"라는 근거 없는 판정이 생긴다(비교 대상이 자기 자신이므로).
    gap = ask_gap_pct(ask, band) if ask is not None else None
    liq = liquidity(candidate.trades, candidate.listings,
                    candidate.total_households, as_of=as_of)

    if ask is None:
        verdict = TRADE_BASIS_VERDICT
    elif gap is None:
        verdict = "판단 보류"
    elif gap <= -10:
        verdict = "적정가 하단 — 급매 가능"
    elif gap >= 10:
        verdict = "적정가 상단"
    else:
        verdict = "적정가 범위"

    # F4: 동(棟)별 편차를 실거래 aptDong 으로 실측한다.
    # ⚠️ 실거래 기반이라 **호가 유무와 무관하게** 동작한다. 호가 없는 후보에서도 살아 있어야 한다.
    # ⚠️ 밴드 기간(band.period_months)을 넘기지 않는다 — aptDong 은 등기 후에만 채워져서
    #    최근 6개월 창에서는 동 정보가 33~58% 로 떨어지고, 거래가 많은 단지일수록 밴드가
    #    6개월에 멈춰 실측이 실패한다(실데이터 검증: 6개월 4/8 → 24개월 8/8).
    #    dong_effect 는 자체 기본 창(DONG_PERIOD_MONTHS)을 쓴다.
    dong = dong_effect(candidate.trades, area_m2=candidate.area_m2, as_of=as_of)

    risks = [DELAY_RISK]
    if band.expanded:
        risks.append(Risk("low",
                          f"표본이 부족해 최근 {band.period_months}개월까지 확장해 계산했습니다."))
    if liq.grade == "나쁨":
        risks.append(Risk("medium", "거래 회전율이 낮아 매도에 시간이 걸릴 수 있습니다."))

    if ask is None:
        # 살 수 있는 물건이 확인되지 않았다는 사실 자체가 리스크다. 숨기지 않는다.
        risks.append(Risk("medium",
                          "현재 매수 가능한 매물이 확인되지 않았습니다. "
                          "아래 가격은 호가가 아니라 최근 실거래 기준 추정입니다."))

    # 점수: 갭이 작을수록 좋다(0% 기준). ±20% 를 0점 경계로 본다.
    # ⚠️ 호가가 없으면 **점수를 매기지 않는다(None)**. 매길 축(호가 vs 적정가)이 없다.
    #    0 점을 주면 "나쁘다"로 읽히고, 임의 점수를 주면 근거 없는 서열이 생긴다.
    score = max(0.0, min(100.0, 100.0 - abs(gap) * 5)) if gap is not None else None

    if ask is not None:
        rationale = (
            f"동일 타입 {band.sample_size}건 중위 {band.median_krw:,}원 대비 "
            f"호가 {ask:,}원은 {gap:+.1f}% 입니다. 환금성은 {liq.grade}."
        )
    else:
        rationale = (
            f"{TRADE_BASIS_NOTE} 동일 타입 최근 {band.period_months}개월 실거래 "
            f"{band.sample_size}건 기준 적정가 밴드는 "
            f"{band.p25_krw:,}~{band.p75_krw:,}원(중위 {band.median_krw:,}원)입니다. "
            f"비교할 호가가 없어 호가 갭은 계산하지 않았습니다. 환금성은 {liq.grade}."
        )
    evidence = band.to_evidence(as_of=as_of) and [
        Evidence(claim=f"중위 실거래가 {band.median_krw:,}원",
                 source="국토교통부 실거래가",
                 as_of=as_of.isoformat(), data_rows=band.sample_size)
    ]
    # 동별 실측이 있으면 근거와 문구에 싣는다. 실측이 아니면(폴백) 지어내지 않는다.
    if dong.available:
        top = dong.dongs[0]
        rationale += (f" 동별로는 {top.dong}동이 단지 평균 대비 {top.vs_complex_pct:+.1f}%"
                      f"(실거래 {top.sample_size}건, 동 정보 {dong.coverage_pct}%)입니다.")
        evidence = (evidence or []) + [
            Evidence(claim=e["claim"], source=e["source"], as_of=e["as_of"],
                     data_rows=e["data_rows"])
            for e in dong.to_evidence(as_of=as_of)
        ]

    return validate_finding(Finding(
        agent_id="valuation-trader",
        verdict=verdict,
        rationale=rationale,
        evidence=evidence,
        risks=risks,
        score=score,
        confidence=0.85,
    ))


def _price_band_dict(band: Any) -> dict[str, Any] | None:
    """적정가 밴드를 추천 아이템 형태로 직렬화.

    호가가 없는 후보에게는 **이 밴드가 유일한 가격 근거**다. 갭 숫자를 지어내는 대신
    밴드 자체(p25~p75·표본·기간·확장 여부)를 그대로 보여 준다 — 근거의 강도를
    사용자가 직접 볼 수 있게("확신의 농도").
    """
    if band is None or not band.available:
        return None
    return {
        "p25_krw": band.p25_krw,
        "median_krw": band.median_krw,
        "p75_krw": band.p75_krw,
        "sample_size": band.sample_size,
        "period_months": band.period_months,
        "expanded": band.expanded,
        "source": "국토교통부 실거래가",
    }


def _dong_valuation_dict(d: DongValuation | None) -> dict[str, Any] | None:
    """F4 동별 실측을 추천 아이템 형태로 직렬화.

    실측(available)이면 basis=trade_measured·높은 신뢰로, 폴백이면 사유를 명시한다.
    실거래 자체가 부족해 valuation 이 나오지 않은 경우(d is None)는 필드를 비운다.
    """
    if d is None:
        return None
    if not d.available:
        return {
            "available": False,
            "method": d.method,          # 표본부족 | 동표본부족 | 동정보없음
            "confidence": 0.0,
            "coverage_pct": d.coverage_pct,
            "reason": d.reason,
            "note": "동별 판단은 좌표추정 폴백 대상입니다.",
        }
    return {
        "available": True,
        "method": d.method,              # 실측(aptDong)
        "basis": "trade_measured",
        "confidence": 0.85,              # 실거래 실측 → 높은 신뢰
        "coverage_pct": d.coverage_pct,
        "period_months": d.period_months,
        "dongs": [
            {"dong": s.dong, "vs_complex_pct": s.vs_complex_pct,
             "sample": s.sample_size, "median_ppm_krw": s.median_ppm_krw}
            for s in d.dongs
        ],
    }


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


def excluded_record(*, complex_id: int | None, complex_name: str | None,
                    area_m2: float | None, price_basis: str | None,
                    code: str, reason: str) -> dict[str, Any]:
    """제외된 후보 1건의 **표준 모양**. 만드는 자리가 여럿이라 한 곳에 모아 둔다.

    `complex_id` 만 남기면 화면은 "단지 #2048 제외"라고 밖에 못 쓰고, 그건 사용자에게
    아무 답도 아니다("내가 아는 그 단지가 이건가?"). 단지명·면적·가격 근거를 같이 준다.

    `reason_code` 는 기계가 읽는 축이다. 사유 문장에는 단지 사정(금액·표본 수)이 섞여
    들어가 그대로 세면 전부 유니크해진다 — 사유별 분포를 내려면 코드가 필요하다.
    문장(`reason`)은 사람용, 코드는 집계용이고 **둘 다 남긴다**.
    """
    return {
        "complex_id": complex_id,
        "complex_name": complex_name,
        "area_m2": area_m2,
        "price_basis": price_basis,
        "price_estimated": (None if price_basis is None
                            else price_basis != PRICE_BASIS_LISTING),
        "reason_code": code,
        "reason": reason,
    }


def excluded_entry(cand: Candidate, *, code: str, reason: str) -> dict[str, Any]:
    """후보(Candidate)에서 제외 항목을 만든다."""
    return excluded_record(
        complex_id=cand.complex_id, complex_name=cand.complex_name,
        area_m2=cand.area_m2, price_basis=cand.price_basis,
        code=code, reason=reason)


def _rank_cutoff_entry(item: dict[str, Any], top_n: int) -> dict[str, Any]:
    """순위에서 잘린 후보 1건. 제외 사유 목록과 **같은 모양**으로 만든다.

    점수가 없으면(`total_score is None`) "0점이라 밀렸다"가 아니라 **점수를 매길 근거가
    없어서** 뒤로 간 것이다 — 그 차이를 문장에 그대로 적는다(0 과 null 을 섞지 않는다).
    """
    score = item.get("total_score")
    tail = (f"점수 {score}" if score is not None
            else "점수를 매길 근거(호가 갭·입지 실측)가 없어 뒤로 밀림")
    entry = excluded_record(
        complex_id=(item.get("complex") or {}).get("id"),
        complex_name=(item.get("complex") or {}).get("name"),
        area_m2=(item.get("unit_type") or {}).get("area_m2"),
        price_basis=item.get("price_basis"),
        code=EXCLUDED_RANK_CUTOFF,
        reason=f"상위 {top_n}건 밖 — {tail}")
    entry["total_score"] = score
    return entry


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
    """MVP 5종 파이프라인 실행.

    반환
    ----
    ``items``     상위 top_n 추천(순위 부여)
    ``excluded``  **나머지 전부** — 하드 제외(가격근거·예산·기피) + 순위 컷.
                  ``len(items) + len(excluded) == len(ctx.candidates)`` 가 성립한다.
                  이 등식이 깨지면 어딘가에서 후보가 **말없이 사라진 것**이다.
    ``notes``     결과 전체에 붙는 단서
    """
    finance = finance_finding(ctx.affordability)
    budget = ctx.affordability.max_purchase_krw
    avoid_tokens = _avoid_tokens(ctx.avoid)
    forbidden = _derive_forbidden(ctx)

    items: list[dict[str, Any]] = []
    excluded: list[dict[str, Any]] = []

    for cand in ctx.candidates:
        rep = cand.group.representative if cand.group is not None else None
        basis = cand.price_basis

        # 가격 근거를 먼저 확정한다. 호가가 있으면 호가(사실), 없으면 실거래 중위(추정).
        # 밴드는 여기서 한 번만 계산해 valuation 에 넘긴다(같은 숫자를 두 번 만들지 않는다).
        band = reference_band(cand, ctx.as_of)
        price = reference_price_krw(cand, band)

        # 하드 제외 ⓪ — 가격 근거가 아예 없다(호가 없음 + 실거래 표본 부족).
        # 예산을 따질 수도, 적정가를 말할 수도 없다. 지어내지 않고 사유를 남긴다.
        if price is None:
            excluded.append(excluded_entry(
                cand, code=EXCLUDED_NO_PRICE,
                reason=("가격 근거 없음 — 활성 호가가 없고 "
                        + (band.reason or "실거래 표본 부족"))))
            continue

        # 하드 제외 ① — 아무리 점수가 높아도 못 사는 집은 추천이 아니다.
        # ⚠️ 실거래 기준이면 비교값이 **추정치**다. 사유 문구에 그 사실을 남긴다.
        if budget and price > budget:
            label = (f"호가 {price:,}원" if basis == PRICE_BASIS_LISTING
                     else f"최근 실거래 중위 {price:,}원(추정)")
            # ⚠️ 여기 적히는 금액은 **후보 가격**과 **예산 한도(파생값)** 뿐이다.
            #    보유현금·연소득 원본을 문장에 넣지 않는다(SR4-2).
            excluded.append(excluded_entry(
                cand, code=EXCLUDED_OVER_BUDGET,
                reason=f"예산 초과 ({label} > 한도 {budget:,}원)"))
            continue

        # 하드 제외 ② — 기피 조건은 가점 상쇄가 아니라 제외다(F5).
        loc_assess = (evaluate_location(cand.location, avoid=avoid_tokens, as_of=ctx.as_of)
                      if cand.location is not None else None)
        if loc_assess is not None and loc_assess.excluded:
            excluded.append(excluded_entry(
                cand, code=EXCLUDED_AVOIDED,
                reason="; ".join(loc_assess.exclusion_reasons)))
            continue

        valuation = valuation_finding(cand, ctx.as_of, band=band)
        median = band.median_krw if band.available else None
        dong_val = None
        if band.available:
            # 밴드 기간이 아니라 dong_effect 자체 창을 쓴다(위 valuation_finding 주석 참조).
            # 실거래 기반이라 **호가 유무와 무관하게** 계산된다(F4 회귀 금지).
            dong_val = dong_effect(cand.trades, area_m2=cand.area_m2, as_of=ctx.as_of)

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
        # 점수를 매길 근거가 하나도 없으면 **0 이 아니라 None** 이다.
        # 0.0 은 "나쁘다"로 읽힌다 — "모른다"와 구분되지 않으면 그것도 환각이다(G2).
        total = (round(sum(f.score * f.confidence for f in scored) /
                       sum(f.confidence for f in scored), 1) if scored else None)

        summary = portfolio_summary(findings, llm, forbidden)
        items.append({
            "complex": {"id": cand.complex_id, "name": cand.complex_name},
            "unit_type": {"area_m2": cand.area_m2},
            # 특정 매물의 동은 호가 표기 기준(추정) — confidence 를 낮게 실어 보낸다.
            # 호가가 없으면 특정 물건이 없으므로 building 도 없다(추정하지 않는다).
            "building": ({"id": rep.building_id, "confidence": 0.6,
                          "basis": "listing_reported"}
                         if rep is not None and rep.building_id else None),
            # F4 동별 가치 차이: aptDong 실거래 실측(basis=trade_measured, 높은 신뢰)
            # 이거나, 표본/동정보 부족 시 폴백을 명시한다. 없는 걸 지어내지 않는다.
            "dong_valuation": _dong_valuation_dict(dong_val),
            # --- 가격 계약 (프론트가 반드시 구분해 표시해야 하는 부분) --------
            # price_basis="listing" → est_price_krw == ask_price_krw (지금 살 수 있는 값)
            # price_basis="trade"   → ask_price_krw is None, est_price_krw 는 **추정치**
            "price_basis": basis,
            "ask_price_krw": cand.ask_price_krw,     # 호가 없으면 None (위장 금지)
            "est_price_krw": price,                  # 판단·예산 비교에 실제로 쓴 값
            "price_estimated": basis != PRICE_BASIS_LISTING,
            "price_note": (None if basis == PRICE_BASIS_LISTING else TRADE_BASIS_NOTE),
            "ask_gap_pct": (ask_gap_pct(cand.ask_price_krw, band)
                            if cand.ask_price_krw is not None and band.available else None),
            "price_band": _price_band_dict(band),
            "total_score": total,
            "score_basis": ("agent_scores" if scored else None),
            # MVP 에는 타이밍 분석가가 없다. 없는 기능을 있는 척하지 않는다.
            "timing_signal": "unknown",
            "headline": summary["headline"],
            "why": summary["why"],
            "why_not": summary["why_not"],
            "next_actions": summary["next_actions"],
            "findings": [f.to_dict() for f in findings],
        })

    # 점수가 있는 후보가 먼저. 점수 없는 후보끼리는 **근거 표본이 많은 순**으로 둔다
    # (임의 순서로 잘라내면 top_n 이 사실상 DB 정렬 순서가 된다 — 그건 근거가 아니다).
    items.sort(key=lambda x: (
        x["total_score"] is not None,
        x["total_score"] if x["total_score"] is not None else 0.0,
        (x["price_band"] or {}).get("sample_size", 0),
    ), reverse=True)
    for rank, item in enumerate(items[:top_n], start=1):
        item["rank"] = rank

    # 순위에서 잘린 후보도 **사용자 입장에서는 "안 나온 후보"** 다. 조건을 다 통과하고도
    # 11위라서 빠진 단지를 아무 데도 안 남기면, 사용자는 그게 예산 때문인지 데이터가
    # 없어서인지 알 수 없다. 그래서 잘린 것도 사유와 함께 남긴다 —
    # 이로써 **모든 후보는 items 아니면 excluded 에 한 번씩 들어간다**(둘 다는 아니다).
    for item in items[top_n:]:
        excluded.append(_rank_cutoff_entry(item, top_n))

    notes = ["타이밍 분석(market-timing-analyst)은 2차 기능입니다.",
             "입지 분석은 데이터 수집 후 제공됩니다."]
    if any(it["price_basis"] == PRICE_BASIS_TRADE for it in items[:top_n]):
        notes.append(
            "일부 후보는 현재 등록된 매물이 없어 최근 실거래 기준으로 세운 추정입니다"
            "(price_basis=trade). 호가와 달라 즉시 매수 가능한 가격이 아닙니다.")
    if any(it["total_score"] is None for it in items[:top_n]):
        notes.append(
            "점수를 매길 근거(호가 갭·입지 실측)가 없어 total_score 가 비어 있는 후보가 "
            "있습니다. 이 후보들은 실거래 표본이 많은 순으로 나열됩니다.")

    return {
        "items": items[:top_n],
        "excluded": excluded,
        "notes": notes,
        "disclaimer": DISCLAIMER,
    }
