"""정비사업 단계 → **리스크-수익 프로파일**.

이 모듈이 지키는 두 가지
------------------------
① **단조 점수 금지.** "단계가 뒤일수록 좋다"는 도메인적으로 틀렸다.
     초기(후보지·구역지정) : 기대수익은 크지만 **무산 위험 + 10년 이상 장기화**
     중간(조합설립~사업시행) : 진행 확실성이 오르고 아직 가격에 덜 반영
     후기(관리처분~착공)     : 확실하지만 **이미 가격에 반영** + 이주·멸실 비용
     준공                    : 재건축 프리미엄 소멸
   그래서 투자 프로파일은 사업시행인가 부근에서 **꺾이는 비단조 곡선**이고,
   실거주 프로파일은 반대로 **뒤로 갈수록 나빠진다**(이주·철거가 임박하므로).
   같은 단계가 목적에 따라 정반대 신호가 된다 — 그것이 이 도메인의 사실이다.

② **추가분담금 금액을 만들어내지 않는다.** 조합 내부 자료라 공개 데이터에 없다.
   세대수 증가율(건립예정 ÷ 기존)로 **사업성의 방향**은 말할 수 있어도 **금액은 못 말한다.**
   `assert_no_cost_estimate()` 가 이 모듈이 만든 모든 문장을 검사해 구조적으로 막는다.
   (사람이 "친절하게" 한 줄 넣는 순간 예외가 난다 — 그게 이 함수의 존재 이유다.)

   ⚠️ **LLM 은 다르게 다룬다**(CR30-1). 모델에게는 이 주제의 재료를 아예 주지 않고
      (`redact_cost_topic` 으로 프롬프트에서 제거), 출력에 주제어가 나타나면
      금액 여부를 따지지 않고 그 요약을 폐기한다(`assert_no_cost_topic`).
      "정규식을 더 정교하게"는 답이 아니었다 — 금액 표기는 무한히 변형된다.
"""
from __future__ import annotations

import datetime as dt
import re
from dataclasses import dataclass, field
from typing import Any

from app.domain.redevelopment.models import RedevProject, source_label
from app.domain.redevelopment.stages import (
    KIND_LABELS,
    STAGE_ASSOCIATION,
    STAGE_CANDIDATE,
    STAGE_COMMITTEE,
    STAGE_COMPLETED,
    STAGE_CONSTRUCTION,
    STAGE_DESIGN_REVIEW,
    STAGE_DISPOSITION,
    STAGE_IMPLEMENTATION,
    STAGE_LABELS,
    STAGE_RELOCATION,
    STAGE_UNKNOWN,
    STAGE_ZONE_DESIGNATED,
)

PURPOSE_LIVE = "live"
PURPOSE_INVEST = "invest"

# ---------------------------------------------------------------------------
# 절대 규칙 ① — 추가분담금 금액 금지
# ---------------------------------------------------------------------------

#: 사용자에게 **항상** 나가는 고지. 이 문장이 빠지면 "분담금은 고려됐다"는 착각이 생긴다.
COST_DISCLOSURE = (
    "추가분담금은 조합 내부 자료라 공개 데이터로 확인할 수 없어 이 분석에 포함되지 "
    "않았습니다 — 분담금 규모는 조합 사무실·정비사업 정보몽땅에서 직접 확인하세요."
)

#: 분담금 **주제어**(어간 단위). 금액 표기가 아니라 '무엇에 대해 말하는가'를 본다.
#:
#: ⚠️ 왜 어간이고 왜 이렇게 넓은가 — CR-029/CR-030 에서 근접 정규식
#: (`분담금` + 금액이 한 문장 30자 이내)이 **네 가지 흔한 완성문**에 뚫렸다:
#: 문장 분리 · 30자 초과 · '부담'(금 없음) · '분담액'. 표기 변형을 쫓는 대신
#: **주제 자체**를 잡는다. 금액 표기는 무한히 변형되지만 주제어는 몇 개 안 된다.
_COST_TOPIC_RE = re.compile(r"분담|부담|환급|추가\s*비용")
#: 금액으로 읽히는 토큰(숫자 + 단위). 연도(2026)·세대수(1,588)는 단위가 없어 안 걸린다.
_MONEY_RE = re.compile(r"\d[\d,.]*\s*(?:억\s*원?|천만\s*원?|백만\s*원?|만\s*원|원)")
#: 문장 경계. 마침표류 뒤의 공백 또는 줄바꿈에서 자른다(프롬프트 재료 삭제용).
_SENTENCE_SPLIT_RE = re.compile(r"(?<=[.!?])\s+|\n+")


class CostGuardError(RuntimeError):
    """분담금 관련 방어가 걸렸다. 아래 두 하위 예외의 공통 조상."""


class CostEstimateError(CostGuardError):
    """**우리 코드가 만든** 문장에 분담금 금액이 섞였다. 만들면 안 되는 숫자다."""


class CostTopicError(CostGuardError):
    """**LLM 이 만든** 문장이 분담금 주제를 건드렸다. 재료를 준 적이 없으므로 이상 신호다."""


def contains_cost_topic(text: str | None) -> bool:
    """이 문자열이 분담금·부담·환급 주제를 건드리는가."""
    return bool(text) and bool(_COST_TOPIC_RE.search(str(text)))


def redact_cost_topic(text: str | None) -> str:
    """분담금 주제를 건드리는 **문장을 통째로 뺀다**(프롬프트 재료 전처리용).

    왜 자르지 않고 문장 단위로 빼는가 — 낱말만 지우면 "…은 조합 내부 자료라 확인할
    수 없어"라는 **문맥이 남아** 모델이 그 자리를 금액으로 메운다. 주제를 없애려면
    문장을 없애야 한다. 남는 문장에는 주제어가 하나도 없음이 구조적으로 보장된다.
    """
    if not text:
        return ""
    kept = [s for s in _SENTENCE_SPLIT_RE.split(str(text))
            if s.strip() and not _COST_TOPIC_RE.search(s)]
    return " ".join(kept).strip()


def assert_no_cost_estimate(*texts: str | None) -> None:
    """**우리 코드가 만든** 문장에 분담금 금액이 들어갔는지 검사한다. 있으면 즉시 예외.

    적용 대상
    ---------
    도메인이 생성한 결정적 문장(rationale·verdict·risks·upsides·must_verify)이다.
    이 문장들은 분담금 **주제**를 말해야 한다(고지가 그 일이다) — 금지되는 것은
    **금액**뿐이다. 그래서 여기서는 주제어 + 금액 토큰의 **동시 출현**을 본다.

    ⚠️ 근접(30자) 조건은 CR-030 에서 버렸다 — 문장을 나누거나 사이에 수식어를
       넣는 것만으로 뚫렸다. 검사 단위는 **문자열 하나 전체**다. 우리 문장은 짧은
       고지·판정문이라 창을 넓혀도 오탐 비용이 없다.

    ⚠️ LLM 출력에는 이 함수를 쓰지 않는다 — `assert_no_cost_topic` 을 쓴다.
       LLM 에게는 분담금 재료를 주지 않으므로, 주제를 꺼내는 것 자체가 이상 신호다.

    왜 경고가 아니라 예외인가
    -------------------------
    사용자는 이 리포트를 근거로 수억 원을 쓴다. "분담금 약 1.2억 예상" 한 줄이면
    없는 확신을 만든다. 경고 로그는 아무도 안 보지만 예외는 테스트가 잡는다.
    """
    for text in texts:
        if not text:
            continue
        body = str(text)
        topic = _COST_TOPIC_RE.search(body)
        money = _MONEY_RE.search(body)
        if topic and money:
            raise CostEstimateError(
                "추가분담금 금액은 공개 데이터에 없습니다 — 지어낸 숫자를 출력할 수 "
                f"없습니다(주제어 {topic.group(0)!r} + 금액 {money.group(0)!r}). "
                "사업성의 '방향'(세대수 증가율 등)만 서술하세요."
            )


def assert_no_cost_topic(*texts: str | None) -> None:
    """**LLM 이 만든** 문장이 분담금 주제를 건드렸는지 검사한다. 건드렸으면 예외.

    금액을 찾지 않는다 — **낱말 하나만 본다.**

    왜 이게 더 강한가
    -----------------
    프롬프트에서 분담금 재료(`COST_DISCLOSURE` 등)를 **빼기 때문**이다. 모델은 이
    주제를 말할 근거를 받지 못하므로, 출력에 주제어가 나타나면 그것은 모델이
    **스스로 지어낸 것**이다. 그래서 금액 표기 변형(문장 분리·거리·어간·필드 분리)을
    쫓을 필요가 없다.

    오탐이 싼 이유
    --------------
    "추가분담금은 확인되지 않았습니다" 같은 **옳은 문장이 걸려도 잃는 정보가 없다.**
    같은 내용을 코드가 고정 문장으로 이미 말한다(`_must_verify` 1번 · 결과 notes).
    걸린 요약은 규칙 기반으로 강등되고, 강등 사실은 사용자에게 고지된다.

    ⚠️ 완전하지 않다. 주제어를 하나도 쓰지 않고 금액만 적는 문장
       ("조합원은 세대당 1억 2천만 원을 더 내야 합니다")은 이 검사로 잡히지 않는다.
       그 경우의 방어는 **재료를 주지 않는 것**과 시스템 프롬프트 규칙이다.
       그래서 사용자 고지에 "어떤 경로로도 막는다"고 쓰지 않는다(CR30-1).
    """
    for text in texts:
        if not text:
            continue
        hit = _COST_TOPIC_RE.search(str(text))
        if hit:
            raise CostTopicError(
                "요약이 분담금·부담 주제를 건드렸습니다 — 이 주제의 재료는 모델에 "
                f"전달되지 않으므로 지어낸 서술입니다(주제어 {hit.group(0)!r}). "
                "요약을 폐기하고 규칙 기반 문장으로 대체합니다."
            )


# ---------------------------------------------------------------------------
# 단계 프로파일 (비단조 · 목적별)
#
# 숫자의 뜻: 0~100 의 **상대 선호도**이지 수익률이 아니다.
# 근거는 도정법 절차상의 성격이며, 아래 주석이 각 값의 이유다.
# ---------------------------------------------------------------------------
STAGE_PROFILE: dict[str, dict[str, float]] = {
    PURPOSE_INVEST: {
        # 무산 가능성이 가장 크고 기간을 전혀 가늠할 수 없다. 기대수익은 크지만
        # '기대'일 뿐이라 확률로 깎는다.
        STAGE_CANDIDATE: 35.0,
        # 법적 지위는 생겼지만 여기서 10년 이상 머무는 구역이 흔하다.
        STAGE_ZONE_DESIGNATED: 55.0,
        # 추진위는 조합 전 단계라 동의율에서 멈추는 경우가 많다.
        STAGE_COMMITTEE: 55.0,
        # 조합설립부터 진행 확실성이 눈에 띄게 오른다. 아직 가격에 다 반영되지 않는다.
        STAGE_ASSOCIATION: 75.0,
        # 계획이 구체화돼 불확실성이 더 준다.
        STAGE_DESIGN_REVIEW: 80.0,
        # 사업시행인가 = 사업 내용 확정. 투자 관점의 **정점**.
        STAGE_IMPLEMENTATION: 85.0,
        # 관리처분부터는 확실하지만 **이미 가격에 반영**되고 이주비·멸실이 시작된다.
        STAGE_DISPOSITION: 65.0,
        STAGE_RELOCATION: 55.0,
        # 착공 이후는 사실상 입주권 거래다. 재건축 '기대'로 살 여지가 거의 없다.
        STAGE_CONSTRUCTION: 50.0,
        # 준공 = 정비사업 종료. 재건축 프리미엄은 소멸한 상태다.
        STAGE_COMPLETED: 30.0,
    },
    PURPOSE_LIVE: {
        # 실거주는 "언제 나가야 하나"가 핵심이다. 단계가 뒤로 갈수록 나빠진다.
        STAGE_CANDIDATE: 50.0,
        STAGE_ZONE_DESIGNATED: 55.0,
        STAGE_COMMITTEE: 50.0,
        # 조합설립 이후는 통상 10년 안팎 묶인다. 실거주에는 제약이다.
        STAGE_ASSOCIATION: 45.0,
        STAGE_DESIGN_REVIEW: 40.0,
        # 사업시행인가 후에는 이주가 가시권이다.
        STAGE_IMPLEMENTATION: 35.0,
        # 관리처분 = 이주·철거 임박. 실거주 목적으로는 사실상 부적합.
        STAGE_DISPOSITION: 25.0,
        STAGE_RELOCATION: 15.0,
        # 착공 시점에는 이미 멸실됐다 — 그 집에서 살 수 없다.
        STAGE_CONSTRUCTION: 15.0,
        # 준공된 새 아파트는 실거주에 좋다.
        STAGE_COMPLETED: 60.0,
    },
}

#: 사업성 보정 — 세대수 증가율(건립예정 ÷ 기존). **금액이 아니라 방향**이다.
#: 증가분이 일반분양 재원이므로 높을수록 사업성이 낫다는 것은 도정법 구조상의 사실이다.
SUPPLY_RATIO_ADJ: tuple[tuple[float, float, str], ...] = (
    (2.0, +8.0, "세대수가 2배 이상 늘어 일반분양 여지가 큽니다"),
    (1.5, +4.0, "세대수가 1.5배 이상 늘어 일반분양 여지가 있습니다"),
    (1.2, 0.0, "세대수 증가폭이 보통입니다"),
    (0.0, -8.0, "세대수 증가폭이 작아 일반분양 여지가 제한적입니다"),
)

#: 정체 판정 기준(년). 마지막 확인 단계일로부터 이만큼 지나면 감점 + 리스크.
STALL_YEARS_SEVERE = 10.0
STALL_YEARS_WARN = 5.0
STALL_ADJ_SEVERE = -15.0
STALL_ADJ_WARN = -8.0

#: 정체 판정을 적용하지 않는 단계 — 착공·준공은 '멈춰 있는 것'이 아니다.
_STALL_EXEMPT = (STAGE_CONSTRUCTION, STAGE_COMPLETED)

#: 신뢰도. 단계는 **실측**(관보/자치단체 고시 기반)이라 추정이 아니지만,
#: 그 단계를 투자 선호도로 옮기는 것은 판단이다. 그래서 1.0 을 주지 않는다.
CONFIDENCE_WITH_DATES = 0.75   # 서울 — 단계 + 단계별 일자 + 세대수
CONFIDENCE_STAGE_ONLY = 0.55   # 인천 — 단계만

#: 근거 basis 라벨. 'estimated' 접두가 아니므로 신뢰도 캡(0.6)에 걸리지 않는다 —
#: 좌표로 추정한 값이 아니라 고시된 사실이기 때문이다(agents/base.py 참조).
BASIS_STAGE_MEASURED = "stage_measured"

#: 초기 단계로 볼 구간. `avoid.redevelopment_early_stage`(api-spec §2) 의 정의이자
#: "10년 이상 묶일 수 있다"는 경고의 대상이다.
EARLY_STAGES: tuple[str, ...] = (STAGE_CANDIDATE, STAGE_ZONE_DESIGNATED, STAGE_COMMITTEE)

#: 실거주 부적합 구간 — 이주·철거가 임박했거나 이미 멸실됐다.
NOT_LIVABLE_STAGES: tuple[str, ...] = (STAGE_DISPOSITION, STAGE_RELOCATION,
                                       STAGE_CONSTRUCTION)


@dataclass(frozen=True)
class RedevAssessment:
    """정비사업 판정. **점수만이 아니라 양쪽(호재·악재)을 함께 낸다.**"""

    available: bool
    stage: str
    raw_stage: str
    #: 0~100. 매칭된 구역이 없거나 단계를 분류하지 못하면 **None**(0 이 아니다).
    score: float | None
    confidence: float
    verdict: str
    rationale: str
    evidence: tuple[dict[str, Any], ...] = ()
    #: (severity, detail) — 이 단계가 갖는 **하방** 리스크.
    risks: tuple[tuple[str, str], ...] = ()
    #: 이 단계가 갖는 **상방** 근거. 리스크만 내면 그것도 한쪽 눈이다.
    upsides: tuple[str, ...] = ()
    #: 시스템이 확인해 주지 못하는 것 — 사용자가 직접 확인해야 하는 항목.
    must_verify: tuple[str, ...] = ()
    missing: tuple[str, ...] = ()
    years_since_milestone: float | None = None
    supply_ratio: float | None = None
    basis: str | None = None
    #: 초기 단계인가(기피 조건 판정에 쓰인다).
    early_stage: bool = False
    detail: dict[str, Any] = field(default_factory=dict)


# --- 데이터가 없을 때의 표준 반환 -------------------------------------------
#: 매칭된 구역이 없다는 것은 **"정비사업이 없다"가 아니라 "확인되지 않았다"** 이다.
#: 경기도는 아예 수집 범위 밖이고, 서울·인천도 지번 파싱 실패분이 있다.
NO_PROJECT_REASON = (
    "이 단지에 매칭된 정비사업 구역이 없습니다 — '정비사업이 없다'는 뜻이 아니라 "
    "'확인되지 않았다'는 뜻입니다(수집 범위: 서울·인천. 경기도는 미수집)."
)
UNKNOWN_STAGE_REASON = (
    "정비사업 구역은 확인됐지만 진행 단계를 공통 기준으로 분류하지 못했습니다 "
    "(원문 단계명: {raw})."
)


def _no_project(missing: str = NO_PROJECT_REASON) -> RedevAssessment:
    return RedevAssessment(
        available=False, stage=STAGE_UNKNOWN, raw_stage="", score=None, confidence=0.0,
        verdict="정비사업 정보 미확보",
        rationale=missing,
        missing=(missing,),
        must_verify=("정비사업 여부는 관할 구청 주거정비과 또는 정비사업 정보몽땅에서 "
                     "직접 확인하세요.",),
    )


def _years_between(start: dt.date, end: dt.date) -> float:
    return round((end - start).days / 365.25, 1)


def _supply_adjustment(ratio: float | None) -> tuple[float, str | None]:
    if ratio is None:
        return 0.0, None
    for threshold, adj, note in SUPPLY_RATIO_ADJ:
        if ratio >= threshold:
            return adj, note
    return 0.0, None


def _stall_adjustment(years: float | None, stage: str) -> tuple[float, str | None]:
    """정체 감점. **일자를 모르면 감점하지 않는다**(모르는 것으로 벌주지 않는다)."""
    if years is None or stage in _STALL_EXEMPT:
        return 0.0, None
    if years >= STALL_YEARS_SEVERE:
        return STALL_ADJ_SEVERE, (
            f"마지막으로 확인된 단계 진전이 {years:g}년 전입니다 — 장기 정체 구역입니다.")
    if years >= STALL_YEARS_WARN:
        return STALL_ADJ_WARN, (
            f"마지막으로 확인된 단계 진전이 {years:g}년 전입니다 — 진행이 더딥니다.")
    return 0.0, None


def _stage_risks(stage: str, purpose: str) -> list[tuple[str, str]]:
    """단계 자체가 갖는 하방 리스크. 목적에 따라 무게가 다르다."""
    risks: list[tuple[str, str]] = []
    if stage in EARLY_STAGES:
        risks.append(("high" if stage == STAGE_CANDIDATE else "medium",
                      "초기 단계 정비사업입니다 — 사업이 무산되거나 10년 이상 "
                      "길어질 수 있고, 그동안 자금이 묶입니다."))
    if stage in (STAGE_ASSOCIATION, STAGE_DESIGN_REVIEW, STAGE_IMPLEMENTATION):
        risks.append(("medium",
                      "조합 단계 진입 이후에도 시공사 선정·공사비 인상·조합 내분으로 "
                      "일정이 밀리는 사례가 많습니다."))
    if stage in (STAGE_DISPOSITION, STAGE_RELOCATION):
        risks.append(("medium",
                      "관리처분 이후에는 기대가 이미 가격에 반영돼 있고, 이주비 대출·"
                      "이주 기간의 주거비가 별도로 듭니다."))
    if purpose == PURPOSE_LIVE and stage in NOT_LIVABLE_STAGES:
        risks.append(("high",
                      "이주·철거가 임박했거나 이미 진행 중이라 실거주 목적에는 "
                      "적합하지 않습니다."))
    if stage == STAGE_COMPLETED:
        risks.append(("low", "정비사업이 끝난 구역이라 재건축 기대는 더 이상 없습니다."))
    return risks


def _stage_upsides(stage: str, purpose: str) -> list[str]:
    """단계가 갖는 상방 근거. 리스크만 나열하면 판단이 아니라 겁주기다."""
    ups: list[str] = []
    if stage in EARLY_STAGES:
        ups.append("초기 단계라 사업이 진행될 경우의 기대 폭은 상대적으로 큽니다.")
    if stage in (STAGE_ASSOCIATION, STAGE_DESIGN_REVIEW, STAGE_IMPLEMENTATION):
        ups.append("조합·인가 단계에 들어서 사업이 실제로 진행될 확실성이 올라갔습니다.")
    if stage == STAGE_IMPLEMENTATION:
        ups.append("사업시행인가로 건축 규모·용도가 확정돼 불확실성이 크게 줄었습니다.")
    if stage in (STAGE_DISPOSITION, STAGE_RELOCATION, STAGE_CONSTRUCTION):
        ups.append("관리처분 이후 단계라 사업 무산 위험은 매우 낮습니다.")
    if purpose == PURPOSE_LIVE and stage == STAGE_COMPLETED:
        ups.append("정비사업이 끝나 새 아파트로 바로 거주할 수 있습니다.")
    return ups


def _verdict(stage: str, purpose: str) -> str:
    """한 줄 판정. **목적에 따라 말이 달라진다.**

    ⚠️ 같은 '사업시행인가'를 실거주 사용자에게 "진행 확실성 상승 구간"이라고 하면
       점수(35점)와 문구가 반대 방향을 가리킨다 — 실거주에게 그 단계는 이주가
       가까워졌다는 뜻이다. 문구와 점수가 어긋나면 사용자는 어느 쪽도 못 믿는다.
    """
    label = STAGE_LABELS.get(stage, STAGE_LABELS[STAGE_UNKNOWN])
    mid = (STAGE_ASSOCIATION, STAGE_DESIGN_REVIEW, STAGE_IMPLEMENTATION)
    if purpose == PURPOSE_LIVE:
        if stage in NOT_LIVABLE_STAGES:
            return f"{label} — 실거주 부적합(이주·철거 임박)"
        if stage in mid:
            return f"{label} — 거주 기간이 제한될 수 있음"
        if stage in EARLY_STAGES:
            return f"{label} — 장기간 묶일 수 있음"
        if stage == STAGE_COMPLETED:
            return f"{label} — 새 아파트, 재건축 기대는 없음"
        return f"{label} — 확인 필요"
    if stage in EARLY_STAGES:
        return f"{label} — 기대는 크지만 불확실"
    if stage == STAGE_COMPLETED:
        return f"{label} — 재건축 기대 소멸"
    if stage in mid:
        return f"{label} — 진행 확실성 상승 구간"
    return f"{label} — 확실하지만 가격 반영 구간"


def assess_redevelopment(project: RedevProject | None, *, purpose: str = PURPOSE_LIVE,
                         as_of: dt.date | None = None) -> RedevAssessment:
    """매칭된 정비사업 구역 → 판정.

    ⚠️ `project` 가 None 이면 점수를 **0 이 아니라 None** 으로 낸다.
       0 은 "재건축 가치가 없다"이고 None 은 "모른다"다. 우리 수집 범위는 서울·인천뿐이라
       경기도 단지는 전부 '모른다'가 정답이다.
    """
    if project is None:
        return _no_project()

    as_of = as_of or dt.date.today()
    purpose = purpose if purpose in STAGE_PROFILE else PURPOSE_LIVE
    stage = project.stage

    if stage == STAGE_UNKNOWN:
        # 구역은 찾았는데 단계를 못 읽었다. **구역이 있다는 사실은 남기고** 점수는 안 준다.
        reason = UNKNOWN_STAGE_REASON.format(raw=project.raw_stage or "(빈 값)")
        return RedevAssessment(
            available=True, stage=STAGE_UNKNOWN, raw_stage=project.raw_stage,
            score=None, confidence=0.0,
            verdict=f"{project.zone_name} 정비사업 구역 — 단계 미분류",
            rationale=f"{reason} {COST_DISCLOSURE}",
            evidence=(_zone_evidence(project),),
            missing=(reason,),
            must_verify=_must_verify(project),
            basis=BASIS_STAGE_MEASURED,
            detail=_detail(project, purpose, None, None),
        )

    base = STAGE_PROFILE[purpose][stage]
    ratio = project.supply_ratio
    supply_adj, supply_note = _supply_adjustment(ratio)

    last = project.last_milestone_on
    years = _years_between(last, as_of) if last is not None else None
    stall_adj, stall_note = _stall_adjustment(years, stage)

    score = max(0.0, min(100.0, base + supply_adj + stall_adj))
    has_dates = last is not None
    confidence = CONFIDENCE_WITH_DATES if has_dates else CONFIDENCE_STAGE_ONLY

    risks = _stage_risks(stage, purpose)
    if stall_note:
        risks.append(("high" if (years or 0) >= STALL_YEARS_SEVERE else "medium",
                      stall_note))
    if supply_note and supply_adj < 0:
        # ⚠️ 예전 문구는 "— 조합원 부담이 커지는 방향입니다." 였다. 뜻은 맞지만
        #    이 문장이 **프롬프트 재료**로 나가면서 모델에게 "얼마나?"를 물어보게
        #    만들었다(CR30-1). 같은 방향을 비용 프레임 없이 말한다.
        risks.append(("medium", supply_note + " — 사업성이 낮은 방향입니다."))

    upsides = _stage_upsides(stage, purpose)
    if supply_note and supply_adj > 0:
        upsides.append(supply_note + ".")

    kind = KIND_LABELS.get(project.biz_type, KIND_LABELS["unknown"])
    label = STAGE_LABELS.get(stage, stage)
    parts = [
        f"{project.sigungu} {project.zone_name} {kind} 구역에 포함됩니다. "
        f"현재 단계는 {label}(원문 '{project.raw_stage}')입니다."
    ]
    if last is not None:
        parts.append(f"가장 최근에 확인된 단계 진전은 {last.isoformat()}"
                     f"({years:g}년 전)입니다.")
    else:
        parts.append("단계별 일자는 이 출처에 없어 진행 속도는 판단하지 않았습니다.")
    if ratio is not None:
        parts.append(f"기존 {project.existing_households:,}가구 → 건립 예정 "
                     f"{project.planned_households:,}세대({ratio:g}배)입니다.")
    parts.append(COST_DISCLOSURE)
    rationale = " ".join(parts)

    verdict = _verdict(stage, purpose)
    must_verify = _must_verify(project)

    # ⚠️ 구조적 방어: 이 모듈이 만든 문장에 분담금 **금액**이 섞이면 여기서 멈춘다.
    #    `must_verify` 도 함께 본다 — 이 목록은 추천 카드의 `next_actions` 에 그대로
    #    합쳐져 나가므로(orchestrator `_merge_actions`) 검사 밖에 두면 구멍이 된다.
    assert_no_cost_estimate(rationale, verdict, *(d for _, d in risks), *upsides,
                            *must_verify)

    return RedevAssessment(
        available=True,
        stage=stage,
        raw_stage=project.raw_stage,
        score=round(score, 1),
        confidence=confidence,
        verdict=verdict,
        rationale=rationale,
        evidence=_evidence(project, ratio),
        risks=tuple(risks),
        upsides=tuple(upsides),
        must_verify=must_verify,
        years_since_milestone=years,
        supply_ratio=ratio,
        basis=BASIS_STAGE_MEASURED,
        early_stage=stage in EARLY_STAGES,
        detail=_detail(project, purpose, base, score),
    )


def _zone_evidence(project: RedevProject) -> dict[str, Any]:
    return {
        "claim": f"{project.zone_name} 정비사업 구역 (원문 단계 '{project.raw_stage}')",
        "source": source_label(project.source),
        "as_of": project.as_of.isoformat() if project.as_of else None,
        "source_url": project.source_url,
    }


def _evidence(project: RedevProject, ratio: float | None) -> tuple[dict[str, Any], ...]:
    out = [_zone_evidence(project)]
    last = project.last_milestone_on
    if last is not None:
        out.append({
            "claim": f"최근 단계 일자 {last.isoformat()}",
            "source": source_label(project.source),
            "as_of": project.as_of.isoformat() if project.as_of else None,
        })
    if ratio is not None:
        out.append({
            "claim": (f"기존 {project.existing_households:,}가구 → 건립 예정 "
                      f"{project.planned_households:,}세대"),
            "source": source_label(project.source),
            "as_of": project.as_of.isoformat() if project.as_of else None,
        })
    return tuple(out)


def _must_verify(project: RedevProject) -> tuple[str, ...]:
    """시스템이 **확인해 주지 않는 것**. 비워 두면 사용자가 확인됐다고 믿는다."""
    return (
        "추가분담금 규모는 조합 사무실·정비사업 정보몽땅(cleanup.seoul.go.kr)에서 "
        "직접 확인하세요 — 공개 데이터에 없습니다.",
        f"'{project.zone_name}' 구역 경계에 이 단지가 실제로 포함되는지 관할 구청 "
        "주거정비과 고시문으로 확인하세요(본 매칭은 대표지번 기준입니다).",
        "조합원 자격·거래 제한(조합설립 후 양도 제한 등) 해당 여부를 확인하세요.",
    )


def _detail(project: RedevProject, purpose: str, base: float | None,
            score: float | None) -> dict[str, Any]:
    """점수가 어떻게 나왔는지 그대로 남긴다 — 검증 가능한 형태로."""
    return {
        "zone_name": project.zone_name,
        "sigungu": project.sigungu,
        "stage": project.stage,
        "stage_label": STAGE_LABELS.get(project.stage, project.stage),
        "raw_stage": project.raw_stage,
        "biz_type": project.biz_type,
        "raw_biz_type": project.raw_biz_type,
        "purpose": purpose,
        "base_score": base,
        "final_score": score,
        "match_method": project.match_method,
        # 기계 키(추적·재현용)와 사람이 읽는 출처명(표시·출처표시 의무)을 **둘 다** 남긴다.
        # 하나만 남기면 둘 중 하나를 못 한다(SR25-3).
        "source": project.source,
        "source_label": source_label(project.source),
        "as_of": project.as_of.isoformat() if project.as_of else None,
        "cost_disclosure": COST_DISCLOSURE,
    }
