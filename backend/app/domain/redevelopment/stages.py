"""시도별 원문 단계명 → 공통 enum.

왜 표를 코드에 박아 두는가
--------------------------
시도마다 스키마도 단계 명칭도 다르다(2026-07-27 실측).

    서울(TbSeoulRedevStatus, 472행) 사업추진단계 7종:
        구역지정 · 추진위 · 조합설립 · 건축심의 · 사업시행 · 관리처분 · 착공
    인천(도시 및 주거환경 정비사업 추진현황 CSV, 144행) 진행단계 15종:
        후보지 1차 · 후보지 2차 · 후보지 1차(추진위승인) · 후보지 2차(추진위승인) ·
        정비구역지정 · 정비구역지정(추진위승인) · 추진위원회승인 · 추진위원회 승인 ·
        조합설립인가 · 사업시행계획인가 · 사업시행자지정(신탁사) ·
        관리처분계획인가 · 착공 · 착공(부분준공) · 준공

같은 뜻인데 표기가 다르고(추진위 / 추진위원회승인 / 추진위원회 승인), 인천은 서울에 없는
단계(후보지·준공)를 갖는다. 화면과 점수가 이 차이를 알면 안 되므로 **여기 한 곳**에서
공통 enum 으로 접는다.

⚠️ **원문을 대체하지 않는다.** `redev_project.raw_stage` 에 원문을 그대로 저장하고
   이 표는 그 위에 얹는 해석이다. 표에 없는 값은 `STAGE_UNKNOWN`('미분류')이 되고,
   적재 스크립트가 **건수와 원문을 보고**한다. 버리지 않는다 —
   버리면 새 시도를 붙였을 때 "왜 이 구역만 단계가 없지"에 아무도 답할 수 없다.
"""
from __future__ import annotations

import re

# ---------------------------------------------------------------------------
# 공통 단계 enum
#
# ⚠️ 이 순서는 **법정 절차 순서**일 뿐 점수 순서가 아니다.
#    "뒤에 있을수록 좋다"로 읽으면 도메인적으로 틀린다(analysis.STAGE_PROFILE 참조).
# ---------------------------------------------------------------------------
STAGE_CANDIDATE = "candidate"            # 후보지 — 구역 지정 전. 무산 가능성이 가장 크다
STAGE_ZONE_DESIGNATED = "zone_designated"  # 정비구역 지정(고시)
STAGE_COMMITTEE = "committee"            # 추진위원회 승인
STAGE_ASSOCIATION = "association"        # 조합설립인가 (신탁방식은 사업시행자 지정)
STAGE_DESIGN_REVIEW = "design_review"    # 건축심의 (서울만 별도 단계로 관리)
STAGE_IMPLEMENTATION = "implementation"  # 사업시행인가
STAGE_DISPOSITION = "disposition"        # 관리처분계획인가
STAGE_RELOCATION = "relocation"          # 이주·철거
STAGE_CONSTRUCTION = "construction"      # 착공
STAGE_COMPLETED = "completed"            # 준공 — 정비사업 종료(재건축 프리미엄 소멸)
STAGE_UNKNOWN = "unknown"                # 미분류 — 표에 없는 원문. 버리지 않고 남긴다

#: 절차 순서(표시·정렬용). `STAGE_UNKNOWN` 은 순서가 없으므로 넣지 않는다.
STAGE_ORDER: tuple[str, ...] = (
    STAGE_CANDIDATE, STAGE_ZONE_DESIGNATED, STAGE_COMMITTEE, STAGE_ASSOCIATION,
    STAGE_DESIGN_REVIEW, STAGE_IMPLEMENTATION, STAGE_DISPOSITION, STAGE_RELOCATION,
    STAGE_CONSTRUCTION, STAGE_COMPLETED,
)

#: 화면에 쓰는 말. 원문 대신 이걸 보여줄 때도 **원문을 괄호로 함께** 낸다.
STAGE_LABELS: dict[str, str] = {
    STAGE_CANDIDATE: "후보지(구역지정 전)",
    STAGE_ZONE_DESIGNATED: "정비구역 지정",
    STAGE_COMMITTEE: "추진위원회 승인",
    STAGE_ASSOCIATION: "조합설립인가",
    STAGE_DESIGN_REVIEW: "건축심의",
    STAGE_IMPLEMENTATION: "사업시행인가",
    STAGE_DISPOSITION: "관리처분계획인가",
    STAGE_RELOCATION: "이주·철거",
    STAGE_CONSTRUCTION: "착공",
    STAGE_COMPLETED: "준공",
    STAGE_UNKNOWN: "단계 미분류",
}

# ---------------------------------------------------------------------------
# 원문 → 공통 enum (실측 문자열 기준 · 정확일치)
#
# 퍼지 매칭을 하지 않는 이유: '사업시행'과 '사업시행자지정'은 글자가 겹치지만
# 뜻이 다르다(전자는 인가, 후자는 신탁방식의 시행자 확정). 부분일치로 접으면
# 한 단계를 통째로 잘못 읽고, 그 오류는 점수까지 그대로 흘러간다.
# ---------------------------------------------------------------------------
_RAW_TO_STAGE: dict[str, str] = {
    # --- 서울 (사업추진단계) -------------------------------------------------
    "구역지정": STAGE_ZONE_DESIGNATED,
    "추진위": STAGE_COMMITTEE,
    "조합설립": STAGE_ASSOCIATION,
    "건축심의": STAGE_DESIGN_REVIEW,
    "사업시행": STAGE_IMPLEMENTATION,
    "관리처분": STAGE_DISPOSITION,
    "착공": STAGE_CONSTRUCTION,
    # --- 인천 (진행단계) ----------------------------------------------------
    # 후보지 계열: 괄호의 '추진위승인'은 후보지 안에서의 진척이지 구역지정이 아니다.
    # 구역 지정 전이라는 **가장 큰 사실**을 우선한다(보수적으로 candidate).
    "후보지 1차": STAGE_CANDIDATE,
    "후보지 2차": STAGE_CANDIDATE,
    "후보지 1차(추진위승인)": STAGE_CANDIDATE,
    "후보지 2차(추진위승인)": STAGE_CANDIDATE,
    "정비구역지정": STAGE_ZONE_DESIGNATED,
    "정비구역지정(추진위승인)": STAGE_COMMITTEE,
    "추진위원회승인": STAGE_COMMITTEE,
    "추진위원회 승인": STAGE_COMMITTEE,
    "조합설립인가": STAGE_ASSOCIATION,
    # 신탁방식에서는 사업시행자 지정이 조합설립인가를 갈음한다(도정법 §27).
    # '사업시행인가'가 아니다 — 여기서 헷갈리면 두 단계를 건너뛴 것으로 읽힌다.
    "사업시행자지정(신탁사)": STAGE_ASSOCIATION,
    "사업시행계획인가": STAGE_IMPLEMENTATION,
    "관리처분계획인가": STAGE_DISPOSITION,
    "착공(부분준공)": STAGE_CONSTRUCTION,
    "준공": STAGE_COMPLETED,
}

#: 정규화 표가 커버하는 원문 수(적재 리포트가 커버리지를 계산할 때 쓴다).
RAW_STAGE_VOCABULARY: tuple[str, ...] = tuple(sorted(_RAW_TO_STAGE))

_WS_RE = re.compile(r"\s+")


def _clean(raw: str | None) -> str:
    """앞뒤 공백 제거 + 내부 연속 공백 1칸. **글자는 바꾸지 않는다.**"""
    if not raw:
        return ""
    return _WS_RE.sub(" ", str(raw).strip())


def normalize_stage(raw: str | None) -> str:
    """원문 단계명 → 공통 enum. 표에 없으면 `STAGE_UNKNOWN`.

    공백만 다른 표기('추진위원회 승인' vs '추진위원회승인')는 같은 값으로 접지만,
    **글자가 다르면 접지 않는다.** 모르는 값을 아는 값으로 만들지 않는 것이
    이 함수의 유일한 목적이다.
    """
    text = _clean(raw)
    if not text:
        return STAGE_UNKNOWN
    if text in _RAW_TO_STAGE:
        return _RAW_TO_STAGE[text]
    # 공백 유무만 다른 표기 한 번 더 시도(‘추진위원회 승인’ ↔ ‘추진위원회승인’).
    squeezed = text.replace(" ", "")
    for key, value in _RAW_TO_STAGE.items():
        if key.replace(" ", "") == squeezed:
            return value
    return STAGE_UNKNOWN


# ---------------------------------------------------------------------------
# 사업 유형
# ---------------------------------------------------------------------------
KIND_REBUILD = "rebuild"        # 재건축 — 기존 아파트를 헐고 다시 짓는다
KIND_REDEVELOP = "redevelop"    # 재개발 — 기반시설까지 정비(주택정비형·도시정비형)
KIND_ENV_IMPROVE = "env_improve"  # 주거환경개선 — 현지개량/전면개량
KIND_UNKNOWN = "unknown"

KIND_LABELS: dict[str, str] = {
    KIND_REBUILD: "재건축",
    KIND_REDEVELOP: "재개발",
    KIND_ENV_IMPROVE: "주거환경개선",
    KIND_UNKNOWN: "유형 미분류",
}

_RAW_TO_KIND: dict[str, str] = {
    # 서울
    "공동주택재건축": KIND_REBUILD,
    "아파트지구재건축": KIND_REBUILD,
    "단독주택재건축": KIND_REBUILD,
    "주택정비형재개발": KIND_REDEVELOP,
    "도시정비형재개발": KIND_REDEVELOP,
    # 인천
    "재건축": KIND_REBUILD,
    "재개발": KIND_REDEVELOP,
    "재정비촉진": KIND_REDEVELOP,
    "주거환경개선(현지개량)": KIND_ENV_IMPROVE,
    "주거환경개선(전면개량)": KIND_ENV_IMPROVE,
    # ⚠️ 인천 CSV 의 '사업유형' 칸에는 단계 문구가 들어온 행이 있다
    #    ('정비구역지정(후보지 1차)' 등 39행). 유형이 아니므로 **유형 미분류**로 둔다 —
    #    단계는 '진행단계' 칸이 정본이고, 여기서 억지로 유형을 만들어내지 않는다.
    "정비구역지정(후보지 1차)": KIND_UNKNOWN,
    "정비구역지정(후보지 2차)": KIND_UNKNOWN,
}


def normalize_biz_type(raw: str | None) -> str:
    """원문 사업유형 → 공통 enum. 표에 없으면 `KIND_UNKNOWN`."""
    text = _clean(raw)
    if not text:
        return KIND_UNKNOWN
    return _RAW_TO_KIND.get(text, KIND_UNKNOWN)
