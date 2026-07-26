"""사용자 가중치(가격·입지·가치·리스크) → 총점.

설계 근거: docs/02-design/api-spec.md §5.3, docs/02-design/agents/README.md §2

왜 이 모듈이 생겼나
-------------------
`user_preference.weights` 는 화면에서 슬라이더로 받아 DB 에 **저장만 되고 있었다.**
추천 점수는 `sum(score × confidence) / sum(confidence)` — 에이전트 **신뢰도** 가중
평균이라 사용자가 슬라이더를 아무리 움직여도 결과가 한 글자도 바뀌지 않았다.
슬라이더가 있으니 사용자는 반영된다고 믿는다. 이 제품이 가장 경계하는 "작동하는 척"이다.

그런데 그냥 곱하면 더 나쁜 거짓이 된다
--------------------------------------
4개 축 중 **실제 신호가 있는 축은 일부뿐**이다(2026-07-26 운영 DB 실측:
listing 0행 · poi 0행 · school_district 0행 · road_segment 0행 · trade 611,518행).
근거가 없는 축에 0점을 주고 곱하면 "입지가 나쁘다"는 없는 판정이 생기고,
조용히 빼면 사용자는 자기 가중치가 반영된 줄 안다. **둘 다 사용자를 속인다.**

그래서 이 모듈의 규칙은 셋이다:
  1. 신호가 있는 축만 총점에 넣고 **나머지 가중치는 재정규화**한다.
  2. 빠진 축·비율·사유를 `score_axes`·`score_notes` 로 **응답에 남긴다**.
  3. 가중치를 적용할 축이 하나도 없으면 **점수를 만들지 않는다**(`None`).
     0 은 "나쁘다", None 은 "모른다" — 섞으면 그것도 환각이다(G2).

축 ↔ 에이전트 매핑은 아래 `AXIS_SPECS` **한 곳**에만 있다. 여기저기 흩뿌리면
"가격 축이 대체 뭘 보는 건데"에 아무도 답할 수 없게 된다.
"""
from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Any

from app.agents.base import Finding
from app.domain.valuation.models import Liquidity

# ---------------------------------------------------------------------------
# 축 (user_preference.weights 의 키) — 프론트 lib/preferences.ts 와 **같은 문자열**
# ---------------------------------------------------------------------------
AXIS_PRICE = "price"
AXIS_LOCATION = "location"
AXIS_VALUE = "value"
AXIS_RISK = "risk"

#: 축의 커버리지. full = 설계한 신호를 다 본다, partial = 일부만 본다(무엇이 빠졌는지 명시).
COVERAGE_FULL = "full"
COVERAGE_PARTIAL = "partial"


@dataclass(frozen=True)
class AxisSpec:
    """축 하나의 정의. **이 표가 매핑의 정본이다.**"""

    axis: str
    label: str                       # 화면 문구(프론트 WEIGHT_LABELS 와 같은 말)
    agent_ids: tuple[str, ...]       # 이 축의 점수를 만드는 에이전트
    signal: str                      # 어떤 신호를 점수로 쓰는가(사람이 읽는 설명)
    coverage: str                    # full | partial
    coverage_gap: str | None = None  # partial 이면 **무엇이 빠졌는지** — 반드시 적는다


#: 축 ↔ 에이전트 ↔ 신호 매핑 (한 곳에 상수로 · api-spec.md §5.3 과 같은 내용)
#:
#: ⚠️ `finance-tax-advisor` 는 어느 축에도 없다 — 예산은 **가중치로 조절하는 취향이 아니라
#:    하드 제외 조건**이다(못 사는 집은 아무리 점수가 높아도 추천이 아니다).
#:    실제로 그 finding 의 score 는 항상 None 이라 예전 신뢰도 평균에도 들어가지 않았다.
AXIS_SPECS: dict[str, AxisSpec] = {
    AXIS_PRICE: AxisSpec(
        axis=AXIS_PRICE,
        label="가격",
        agent_ids=("valuation-trader",),
        signal="호가 − 적정가 밴드 중위 갭(ask_gap_pct)을 0~100 으로 환산",
        coverage=COVERAGE_FULL,
    ),
    AXIS_LOCATION: AxisSpec(
        axis=AXIS_LOCATION,
        label="입지",
        agent_ids=("location-analyst",),
        signal="학군(학구도)·역세권·생활 인프라 근접 종합 점수",
        coverage=COVERAGE_FULL,
    ),
    AXIS_VALUE: AxisSpec(
        axis=AXIS_VALUE,
        label="가치(시세)",
        agent_ids=("valuation-trader",),
        signal="12개월 거래회전율 기반 환금성(liquidity.turnover_12m_pct)",
        coverage=COVERAGE_PARTIAL,
        coverage_gap=("동별 가격 편차(dong_valuation)는 '어느 동이 비싼가'를 재는 값이라 "
                      "후보 점수로 환산하지 않고 참고 정보로만 제공합니다."),
    ),
    AXIS_RISK: AxisSpec(
        axis=AXIS_RISK,
        label="리스크",
        agent_ids=("listing-researcher",),
        signal="매물 신뢰도(허위·미끼·중복 등록 탐지) 점수",
        coverage=COVERAGE_PARTIAL,
        coverage_gap=("권리관계·근저당·재건축 추가분담금·깡통전세 분석(risk-auditor)은 "
                      "2차 기능이라 이 점수에 들어가지 않습니다."),
    ),
}

#: 축 순서 고정(응답·문서·테스트가 같은 순서를 본다).
WEIGHT_AXES: tuple[str, ...] = tuple(AXIS_SPECS)

# --- 축별 상태 --------------------------------------------------------------
STATUS_APPLIED = "applied"          # 가중치 > 0 이고 신호도 있다 → 총점에 들어갔다
STATUS_NO_SIGNAL = "no_signal"      # 가중치 > 0 인데 근거가 없다 → 제외 + 고지
STATUS_ZERO_WEIGHT = "zero_weight"  # 사용자가 0 을 줬다 → 애초에 안 본다
STATUS_NO_WEIGHTS = "no_weights"    # 저장된 가중치 자체가 없다 → 기존 동작으로 폴백

#: 가중치가 아예 없을 때 남기는 사실(요구 3). 조용히 기존 동작으로 돌아가지 않는다.
NOTE_NO_WEIGHTS = ("저장된 조건 가중치가 없어(또는 전부 0) 가격·입지·가치·리스크 "
                   "가중치를 적용하지 않고 에이전트 신뢰도 가중 평균으로 순위를 매겼습니다.")
#: 가중치는 있는데 그 축들에 근거가 하나도 없을 때.
NOTE_NO_APPLICABLE_AXIS = ("요청하신 가중치 축에 반영할 근거가 하나도 없어 "
                           "점수를 매기지 않았습니다(0점이 아니라 '모름'입니다).")

# --- score_basis ------------------------------------------------------------
#: 사용자 가중치로 계산했다.
BASIS_USER_WEIGHTED = "user_weighted"
#: 가중치가 없어 **기존 동작**(에이전트 신뢰도 가중 평균)으로 계산했다.
#: ⚠️ 문자열을 바꾸지 말 것 — 기존 응답 계약(api-spec §5)이 이 값을 쓴다.
BASIS_AGENT_SCORES = "agent_scores"

# ---------------------------------------------------------------------------
# 환금성 → 가치 축 점수
# ---------------------------------------------------------------------------
#: 12개월 거래회전율이 이 값(%) 이상이면 만점. `stats.liquidity()` 의 '좋음' 경계와
#: **같은 값**이어야 한다(등급과 점수가 어긋나면 rationale 과 순위가 서로 다른 말을 한다).
#: 동기화는 `test_scoring.py::test_환금성_만점_기준이_좋음_등급_경계와_같다` 가 고정한다.
TURNOVER_FULL_SCORE_PCT = 5.0

#: 가치 축 신뢰도. 회전율은 실거래 건수 ÷ 세대수라 **실측**이지만, 분자는 해당 면적대
#: 거래만 세고 분모는 단지 전체 세대수라 면적 타입이 많은 단지일수록 낮게 나온다.
#: 그 한계를 confidence 로 드러낸다(밴드 0.85·매물 0.8 보다 낮게).
VALUE_AXIS_CONFIDENCE = 0.7

# --- 신호가 없을 때의 표준 사유 ---------------------------------------------
NO_ASK_REASON = ("활성 호가가 없어 호가–적정가 갭을 계산할 수 없습니다 "
                 "(공공 오픈API 에는 호가가 포함되지 않습니다)")
NO_BAND_REASON = "적정가 밴드를 세울 실거래 표본이 부족합니다"
NO_TURNOVER_REASON = "단지 세대수를 알 수 없어 거래회전율(환금성)을 계산할 수 없습니다"
NO_LISTING_TRUST_REASON = "평가할 활성 호가가 없어 매물 신뢰도를 판정할 수 없습니다"
NO_LOCATION_REASON = "입지 데이터(학군·교통·인프라) 미수집"


@dataclass(frozen=True)
class AxisSignal:
    """후보 1건에서 **실제로 측정된** 축 신호. 없으면 score=None + missing."""

    axis: str
    score: float | None
    confidence: float
    detail: str | None = None          # 근거 한 줄(사람이 읽는)
    missing: tuple[str, ...] = ()      # 신호가 없으면 그 사유


@dataclass(frozen=True)
class ScoreResult:
    """총점 + **어떻게 나온 점수인지**. 점수만 주면 검증할 수 없다."""

    total: float | None
    basis: str | None
    axes: tuple[dict[str, Any], ...] = ()
    notes: tuple[str, ...] = ()
    #: 사용자 가중치 중 실제로 총점에 반영된 비율(%). 후보마다 다를 수 있다
    #: (호가가 있는 후보는 가격·리스크 축이 살아 있고, 없는 후보는 죽는다).
    coverage_pct: float | None = None


# ---------------------------------------------------------------------------
# 가중치 정규화 — **클라이언트를 믿지 않는다**
# ---------------------------------------------------------------------------

def normalize_weights(raw: Any) -> tuple[dict[str, float], list[str]]:
    """저장된 가중치를 합이 1 인 비율로. 쓸 수 없으면 빈 dict.

    프론트(`lib/preferences.ts`)가 이미 정규화해 보내지만 **그건 클라이언트의 주장**이다.
    `PUT /me/preferences` 는 `dict[str, float]` 를 그대로 받으므로 음수·NaN·합 0·모르는
    키가 얼마든지 저장돼 있을 수 있다. 여기서 다시 정규화한다.

    반환
    ----
    ``(weights, ignored_keys)`` — 못 쓴 항목은 **버리되 목록으로 돌려준다.**
    조용히 버리면 사용자는 자기가 준 값이 반영된 줄 안다(한글 키 "가격" 등).
    0·음수는 "이 축은 안 본다"는 **정상 입력**이라 목록에 넣지 않는다.
    """
    if not isinstance(raw, dict):
        return {}, []

    usable: dict[str, float] = {}
    ignored: list[str] = []
    for key, val in raw.items():
        name = str(key)
        if name not in AXIS_SPECS:
            ignored.append(name)
            continue
        try:
            num = float(val)
        except (TypeError, ValueError):
            ignored.append(name)          # 숫자가 아니면 "준 적 없음"이 아니라 "못 쓴 값"
            continue
        if not math.isfinite(num):
            ignored.append(name)          # NaN·inf 도 마찬가지 — 조용히 삼키지 않는다
            continue
        if num <= 0:
            continue                       # 0·음수는 "이 축은 안 본다"는 정상 입력
        usable[name] = num

    total = sum(usable.values())
    if total <= 0:
        return {}, ignored
    # 축 순서를 고정해 돌려준다(응답·로그가 매번 같은 순서여야 비교가 쉽다).
    return ({axis: usable[axis] / total for axis in WEIGHT_AXES if axis in usable},
            ignored)


# ---------------------------------------------------------------------------
# finding·환금성 → 축 신호
# ---------------------------------------------------------------------------

def liquidity_score(liq: Liquidity | None) -> float | None:
    """환금성 → 0~100. 회전율을 모르면 **점수를 만들지 않는다.**"""
    if liq is None or liq.turnover_12m_pct is None:
        return None
    ratio = min(1.0, max(0.0, liq.turnover_12m_pct / TURNOVER_FULL_SCORE_PCT))
    return round(ratio * 100, 1)


def _liquidity_detail(liq: Liquidity | None) -> str | None:
    if liq is None or liq.turnover_12m_pct is None:
        return None
    return f"환금성 {liq.grade} — 12개월 거래회전율 {liq.turnover_12m_pct}%"


def build_axis_signals(*, valuation: Finding, listing: Finding, location: Finding,
                       liq: Liquidity | None, has_ask: bool) -> dict[str, AxisSignal]:
    """후보 1건의 축 신호를 만든다. **없는 신호를 지어내지 않는다.**

    각 축이 무엇을 보는지는 `AXIS_SPECS` 가 정본이고, 여기는 그 표대로 값을 꺼내 온다.
    """
    price_missing: tuple[str, ...] = ()
    if valuation.score is None:
        price_missing = (tuple(valuation.missing)
                         or ((NO_ASK_REASON,) if not has_ask else (NO_BAND_REASON,)))

    risk_missing: tuple[str, ...] = ()
    if listing.score is None:
        risk_missing = tuple(listing.missing) or (NO_LISTING_TRUST_REASON,)

    loc_missing: tuple[str, ...] = ()
    if location.score is None:
        loc_missing = tuple(location.missing) or (NO_LOCATION_REASON,)

    value_score = liquidity_score(liq)

    return {
        AXIS_PRICE: AxisSignal(
            axis=AXIS_PRICE, score=valuation.score, confidence=valuation.confidence,
            detail=valuation.verdict if valuation.score is not None else None,
            missing=price_missing),
        AXIS_LOCATION: AxisSignal(
            axis=AXIS_LOCATION, score=location.score, confidence=location.confidence,
            detail=location.verdict if location.score is not None else None,
            missing=loc_missing),
        AXIS_VALUE: AxisSignal(
            axis=AXIS_VALUE, score=value_score,
            confidence=VALUE_AXIS_CONFIDENCE if value_score is not None else 0.0,
            detail=_liquidity_detail(liq),
            missing=() if value_score is not None else (NO_TURNOVER_REASON,)),
        AXIS_RISK: AxisSignal(
            axis=AXIS_RISK, score=listing.score, confidence=listing.confidence,
            detail=listing.verdict if listing.score is not None else None,
            missing=risk_missing),
    }


# ---------------------------------------------------------------------------
# 총점
# ---------------------------------------------------------------------------

def confidence_weighted_total(findings: list[Finding]) -> float | None:
    """**기존 동작** — 에이전트 신뢰도 가중 평균. 가중치가 없을 때의 폴백.

    점수를 매길 근거가 하나도 없으면 0 이 아니라 None 이다.
    """
    scored = [f for f in findings if f.score is not None]
    if not scored:
        return None
    return round(sum(f.score * f.confidence for f in scored)
                 / sum(f.confidence for f in scored), 1)


def _pct(weight: float) -> str:
    value = weight * 100
    return f"{value:.0f}%" if abs(value - round(value)) < 0.05 else f"{value:.1f}%"


def _gap_note(axis: str) -> str | None:
    """이 축이 **어디까지만 보는지**. partial 커버 축에만 있다.

    "점수가 낮다"와 "그 위험은 아예 안 봤다"는 완전히 다른 말이다.
    """
    spec = AXIS_SPECS[axis]
    if not spec.coverage_gap:
        return None
    return f"{spec.label} 축은 {spec.signal}까지만 봅니다 — {spec.coverage_gap}"


def _axis_row(axis: str, weight: float, sig: AxisSignal, status: str,
              applied_weight: float | None) -> dict[str, Any]:
    spec = AXIS_SPECS[axis]
    return {
        "axis": axis,
        "label": spec.label,
        "agent_ids": list(spec.agent_ids),
        "signal": spec.signal,
        "coverage": spec.coverage,
        "coverage_gap": spec.coverage_gap,
        "weight": round(weight, 4),
        # 재정규화 후 실효 비중. 빠진 축이 있으면 남은 축들이 이만큼 커진다.
        "applied_weight": (None if applied_weight is None else round(applied_weight, 4)),
        "score": sig.score,
        "confidence": sig.confidence,
        "detail": sig.detail,
        "status": status,
        "missing": list(sig.missing),
    }


def score_item(*, findings: list[Finding], signals: dict[str, AxisSignal],
               weights: dict[str, float]) -> ScoreResult:
    """후보 1건의 총점.

    규칙
    ----
    * 가중치가 없다(전부 0·미저장·전부 모르는 키) → **기존 동작**(신뢰도 가중 평균) +
      그 사실을 note 로 남긴다.
    * 가중치가 있다 → 신호가 있는 축만 골라 `Σ(w·score)/Σ(w)` (**재정규화**).
      빠진 축은 비율·사유와 함께 `score_axes`·`score_notes` 에 남긴다.
    * 가중치는 있는데 **신호 있는 축이 하나도 없다** → 점수를 만들지 않는다(None).
      사용자가 0 을 준 축의 점수로 총점을 만들면 그건 사용자의 질문에 대한 답이 아니다.
    """
    if not weights:
        total = confidence_weighted_total(findings)
        axes = tuple(
            _axis_row(axis, 0.0, signals[axis], STATUS_NO_WEIGHTS, None)
            for axis in WEIGHT_AXES
        )
        return ScoreResult(
            total=total,
            basis=BASIS_AGENT_SCORES if total is not None else None,
            axes=axes,
            notes=(NOTE_NO_WEIGHTS,),
            coverage_pct=None,
        )

    applied = {axis: w for axis, w in weights.items()
               if w > 0 and signals[axis].score is not None}
    dropped = {axis: w for axis, w in weights.items()
               if w > 0 and signals[axis].score is None}
    applied_sum = sum(applied.values())

    rows: list[dict[str, Any]] = []
    for axis in WEIGHT_AXES:
        weight = weights.get(axis, 0.0)
        sig = signals[axis]
        if weight <= 0:
            status, eff = STATUS_ZERO_WEIGHT, None
        elif axis in applied:
            status = STATUS_APPLIED
            eff = weight / applied_sum if applied_sum else None
        else:
            status, eff = STATUS_NO_SIGNAL, 0.0
        rows.append(_axis_row(axis, weight, sig, status, eff))

    notes: list[str] = []
    for axis, weight in dropped.items():
        reason = "; ".join(signals[axis].missing) or "근거 없음"
        notes.append(f"{AXIS_SPECS[axis].label} 가중치 {_pct(weight)}가 "
                     f"반영되지 않았습니다 — {reason}")
    # ⚠️ 커버리지 고지는 **적용 여부와 무관하게** 낸다. 리스크 축이 "호가가 없어
    #    반영되지 않았습니다"로만 끝나면 사용자는 "호가만 들어오면 리스크가 다 반영된다"고
    #    읽는다 — risk-auditor(권리관계·깡통전세)는 애초에 없다는 사실이 가려진다.
    for axis, weight in weights.items():
        if weight > 0 and (note := _gap_note(axis)):
            notes.append(note)

    if not applied:
        # 가중치를 준 축이 전부 근거 없음 → **점수 없음**(0 도, 다른 축의 점수도 아니다).
        notes.append(NOTE_NO_APPLICABLE_AXIS)
        return ScoreResult(total=None, basis=None, axes=tuple(rows),
                           notes=tuple(notes), coverage_pct=0.0)

    total = round(sum(weights[a] * signals[a].score for a in applied) / applied_sum, 1)
    if dropped:
        notes.append(f"반영된 가중치는 {_pct(applied_sum)} 입니다 — "
                     f"나머지 {_pct(sum(dropped.values()))}는 근거가 없어 제외하고 "
                     "남은 축으로 재정규화했습니다.")
    return ScoreResult(total=total, basis=BASIS_USER_WEIGHTED, axes=tuple(rows),
                       notes=tuple(notes), coverage_pct=round(applied_sum * 100, 1))


# ---------------------------------------------------------------------------
# 결과 전체에 붙는 고지 — 개별 아이템을 안 열어봐도 보이게
# ---------------------------------------------------------------------------

def summary_notes(*, weights: dict[str, float], unknown_keys: list[str],
                  results: list[ScoreResult], total_items: int) -> list[str]:
    """items 전체를 훑어 "무엇이 얼마나 반영됐는지"를 한 줄로 요약한다.

    개별 후보의 `score_notes` 만 남기면 사용자는 카드를 하나하나 열어야 알 수 있다.
    가중치는 결과 **전체**의 성격을 바꾸므로 목록 상단에도 한 번 말한다.
    """
    notes: list[str] = []
    if unknown_keys:
        notes.append(
            f"가중치 항목 {', '.join(sorted(set(unknown_keys)))} 은(는) 무시했습니다 "
            f"— 이름이 다르거나 숫자가 아닙니다. "
            f"사용 가능한 항목: {', '.join(WEIGHT_AXES)}.")

    if not weights:
        notes.append(NOTE_NO_WEIGHTS)
        return notes

    used = " · ".join(f"{AXIS_SPECS[a].label} {_pct(w)}" for a, w in weights.items())
    notes.append(f"조건 가중치를 순위에 반영했습니다 ({used}).")
    if not results:
        return notes

    # 축별로 "몇 건에서 반영되지 못했는지"를 센다. 후보마다 다를 수 있다.
    dropped_counts: dict[str, int] = {}
    reasons: dict[str, set[str]] = {}
    for res in results:
        for row in res.axes:
            if row["status"] != STATUS_NO_SIGNAL:
                continue
            axis = row["axis"]
            dropped_counts[axis] = dropped_counts.get(axis, 0) + 1
            reasons.setdefault(axis, set()).update(row["missing"])

    for axis in WEIGHT_AXES:
        count = dropped_counts.get(axis)
        if not count:
            continue
        scope = "후보 전부" if count >= total_items else f"후보 {total_items}건 중 {count}건"
        notes.append(
            f"{AXIS_SPECS[axis].label} 가중치 {_pct(weights.get(axis, 0.0))}가 "
            f"{scope}에서 반영되지 않았습니다 — {'; '.join(sorted(reasons[axis]))}. "
            "그만큼 나머지 축으로 재정규화했습니다.")

    if all(res.total is None for res in results):
        notes.append(NOTE_NO_APPLICABLE_AXIS)

    # 커버리지 고지는 반영 여부와 무관하다 — "그 위험은 애초에 안 본다"는 사실은
    # 그 축이 이번에 반영됐든 안 됐든 그대로다(_gap_note 주석 참조).
    for axis in weights:
        note = _gap_note(axis)
        if note:
            notes.append(note)
    return notes
