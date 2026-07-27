"""정비사업(재건축·재개발) 진행 단계 도메인.

이 패키지는 **두 가지만** 한다.
  1. 시도마다 제각각인 원문 단계명을 공통 enum 으로 정규화한다(`stages`).
     ⚠️ 원문(`raw_stage`)은 **항상 보존한다.** 정규화에 실패한 값은 버리지 않고
        '미분류'로 남기고 세어서 보고한다 — 조용히 사라진 값은 나중에 아무도 못 찾는다.
  2. 그 단계를 **리스크-수익 프로파일**로 읽는다(`analysis`).

절대 규칙 (이 패키지를 고치는 사람이 반드시 읽을 것)
---------------------------------------------------
* **추가분담금 금액을 만들어내지 않는다.** 조합 내부 자료라 공개 데이터에 없다.
  용적률·대지지분·세대수 증가율로 *사업성의 방향*은 말할 수 있지만 **금액은 못 말한다.**
  우리 문장은 `assert_no_cost_estimate()`(주제어 + 금액 동시 출현)가 막고,
  **LLM 문장은 주제 자체를 금지**한다 — 재료를 주지 않고(`redact_cost_topic`)
  출력에 주제어가 보이면 폐기한다(`assert_no_cost_topic`).
* **단계가 높다 = 좋다 가 아니다.** 초기는 기대수익이 크지만 무산·장기화 위험이 크고,
  후기는 확실하지만 이미 가격에 반영됐고 이주·멸실 비용이 붙는다. 그래서 점수는
  **목적(실거주/투자)에 따라 다른 모양**이며 투자 프로파일은 사업시행인가 부근에서
  꺾이는 **비단조** 함수다(`analysis.STAGE_PROFILE`).
"""
from app.domain.redevelopment.analysis import (  # noqa: F401
    CostEstimateError,
    CostGuardError,
    CostTopicError,
    RedevAssessment,
    assert_no_cost_estimate,
    assert_no_cost_topic,
    assess_redevelopment,
    contains_cost_topic,
    redact_cost_topic,
)
from app.domain.redevelopment.models import RedevProject  # noqa: F401
from app.domain.redevelopment.stages import (  # noqa: F401
    KIND_ENV_IMPROVE,
    KIND_REBUILD,
    KIND_REDEVELOP,
    KIND_UNKNOWN,
    STAGE_ASSOCIATION,
    STAGE_CANDIDATE,
    STAGE_COMMITTEE,
    STAGE_COMPLETED,
    STAGE_CONSTRUCTION,
    STAGE_DESIGN_REVIEW,
    STAGE_DISPOSITION,
    STAGE_IMPLEMENTATION,
    STAGE_LABELS,
    STAGE_ORDER,
    STAGE_UNKNOWN,
    STAGE_ZONE_DESIGNATED,
    normalize_biz_type,
    normalize_stage,
)

__all__ = [
    "CostEstimateError", "CostGuardError", "CostTopicError", "KIND_ENV_IMPROVE",
    "KIND_REBUILD", "KIND_REDEVELOP",
    "KIND_UNKNOWN", "RedevAssessment", "RedevProject", "STAGE_ASSOCIATION",
    "STAGE_CANDIDATE", "STAGE_COMMITTEE", "STAGE_COMPLETED", "STAGE_CONSTRUCTION",
    "STAGE_DESIGN_REVIEW", "STAGE_DISPOSITION", "STAGE_IMPLEMENTATION", "STAGE_LABELS",
    "STAGE_ORDER", "STAGE_UNKNOWN", "STAGE_ZONE_DESIGNATED", "assert_no_cost_estimate",
    "assert_no_cost_topic", "assess_redevelopment", "contains_cost_topic",
    "normalize_biz_type", "normalize_stage", "redact_cost_topic",
]
