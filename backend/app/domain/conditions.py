"""사용자 "내 조건"이 추천까지 **도달하는지**를 선언하는 단일 목록(레지스트리).

왜 이 파일이 있나 — 같은 사고가 세 번 났다
-------------------------------------------
① `budget_override_krw` 가 후보 *조회*에만 닿고 *제외 판정*에는 닿지 않았다.
② `weights`(가중치)가 저장만 되고 순위 계산에 쓰이지 않았다.
③ **평수(전용면적)가 요청 스키마에 아예 없어** 지도는 거르는데 추천은 안 걸렀다.

셋 다 계산 로직의 버그가 아니라 **배선(wiring)이 없던 것**이다. 그리고 셋 다
"조용히" 실패했다 — 조건을 넣었는데 아무 일도 일어나지 않는 형태라, 사용자는
결과가 틀렸다는 사실만 알고 이유는 알 수 없었다.

그래서 조건 항목을 **한 곳에 선언**하고, 각 항목이
  ① 요청 스키마(`RecommendationIn`) 또는 저장된 선호(`user_preference.prefer`)에 있고
  ② 후보 선별·제외·순위 중 **어디에서 실제로 결과를 바꾸는지**
를 여기에 적는다. 회귀 테스트(`tests/test_condition_reach.py`)가 이 목록을 읽어
  · UI(프론트 `Preferences`)에 있는데 여기 없는 키가 생기면 **실패**하고,
  · 여기서 "반영된다"고 주장하는 항목에 **행동 증명(proof)** 이 없으면 **실패**한다.
즉 새 조건을 UI 에 추가하고 배선을 잊으면 테스트가 먼저 넘어진다.

⚠️ 여기 있는 것은 **주장**이다. 주장을 참으로 만드는 것은 테스트다 —
   `effect` 를 바꾸면서 proof 를 안 쓰면 통과하지 못한다.
"""
from __future__ import annotations

from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from typing import Any

# --- 조건이 사는 곳 ---------------------------------------------------------
GROUP_REQUEST = "request"      #: `POST /recommendations` 본문 전용(저장되지 않음)
GROUP_PREFER = "prefer"        #: `user_preference.prefer` (내 조건 화면 · 선호)
GROUP_AVOID = "avoid"          #: `user_preference.avoid` (내 조건 화면 · 기피)
GROUP_WEIGHT = "weights"       #: `user_preference.weights` (무엇을 더 중요하게 볼까)

# --- 조건이 결과를 바꾸는 방식 ----------------------------------------------
#: 후보 조회 범위를 정한다(지역·지도 범위).
EFFECT_SCOPE = "scope"
#: **후보 선별에서 잘라낸다.** 애초에 후보가 아니다(59㎡를 원하는데 84㎡는 후보가 아니다).
EFFECT_CANDIDATE_FILTER = "candidate_filter"
#: 후보는 되지만 **사유와 함께 제외**된다(`excluded[]` 로 보인다).
EFFECT_EXCLUSION = "exclusion"
#: 순위(총점)를 바꾼다.
EFFECT_RANKING = "ranking"
#: 결과의 모양을 바꾼다(개수·목적).
EFFECT_SHAPE = "shape"
#: **아직 추천에 반영되지 않는다.** 있는 척하지 않는다 — 값이 설정돼 있으면
#: 러너가 `notes` 로 "반영되지 않았다"고 말한다(조용한 무시 금지).
EFFECT_NOT_APPLIED = "not_applied"

#: 실제로 결과를 바꾼다고 **주장하는** 효과들. 이 목록에 있으면 증명(proof)이 필요하다.
APPLIED_EFFECTS = frozenset({
    EFFECT_SCOPE, EFFECT_CANDIDATE_FILTER, EFFECT_EXCLUSION,
    EFFECT_RANKING, EFFECT_SHAPE,
})


@dataclass(frozen=True)
class ConditionSpec:
    """조건 한 항목의 계약."""

    key: str
    group: str
    label: str
    effect: str
    #: `RecommendationIn` 필드명. None 이면 요청으로는 못 보낸다(저장된 선호만).
    request_field: str | None = None
    #: `user_preference.prefer` 키. None 이면 저장되지 않는다(요청 전용).
    prefer_key: str | None = None
    #: 이 조건이 **결과를 실제로 바꾼다**는 것을 보이는 회귀 테스트 시나리오 이름.
    #: `effect` 가 APPLIED_EFFECTS 에 있으면 필수다(주장에는 증명이 따른다).
    proof: str | None = None
    #: 반영되지 않는 조건일 때 사용자에게 말할 문장(값이 설정된 경우에만 붙는다).
    gap_note: str | None = None
    why: str = ""


#: ⚠️ 프론트 `Preferences`(frontend/src/api/client.ts)에 키를 추가하면 **여기도** 추가해야 한다.
#:    안 하면 `tests/test_condition_reach.py` 가 실패한다 — 그게 이 목록의 존재 이유다.
REGISTRY: tuple[ConditionSpec, ...] = (
    # --- 요청 전용(화면의 지역 선택·"이 주변") -----------------------------
    ConditionSpec(
        key="region_codes", group=GROUP_REQUEST, label="분석 지역",
        effect=EFFECT_SCOPE, request_field="region_codes",
        proof="region_scope",
        why="법정동코드 접두 매칭으로 후보 조회를 좁힌다."),
    ConditionSpec(
        key="bbox", group=GROUP_REQUEST, label="이 주변에서 검색",
        effect=EFFECT_SCOPE, request_field="bbox",
        proof="bbox_scope",
        why="지도 범위와 교집합. 좌표 없는 단지는 구조적으로 빠지고 그 사실을 notes 로 고지한다."),
    ConditionSpec(
        key="purpose", group=GROUP_REQUEST, label="목적(실거주/투자)",
        effect=EFFECT_SHAPE, request_field="purpose",
        proof="purpose_reaches_affordability",
        why="취득세·자금계획(PropertyFacts.purpose)에 들어간다."),
    ConditionSpec(
        key="top_n", group=GROUP_REQUEST, label="추천 개수",
        effect=EFFECT_SHAPE, request_field="top_n",
        proof="top_n_limits_items",
        why="상위 N건만 남기고 나머지는 '상위 N건 밖' 사유로 남긴다."),

    # --- 내 조건 · 선호 ----------------------------------------------------
    ConditionSpec(
        key="target_price_krw", group=GROUP_PREFER, label="희망 매매가",
        effect=EFFECT_EXCLUSION,
        request_field="budget_override_krw", prefer_key="target_price_krw",
        proof="budget_excludes_over_price",
        why=("예산 **상한**이다. 후보 조회 정렬과 파이프라인 하드 제외 **양쪽**에 닿는다"
             "(AnalysisContext.budget_krw). 한쪽에만 닿았던 것이 1차 사고였다.")),
    ConditionSpec(
        key="area_min_m2", group=GROUP_PREFER, label="전용면적 하한",
        effect=EFFECT_CANDIDATE_FILTER,
        request_field="area_min_m2", prefer_key="area_min_m2",
        proof="area_filters_candidates",
        why=("면적은 후보 선별(hard filter)이다 — 59㎡를 원하는 사람에게 84㎡는 "
             "'제외 사유'가 아니라 애초에 후보가 아니다. 수천 건의 제외 목록을 만들지 않고 "
             "걸러진 건수만 notes 로 말한다.")),
    ConditionSpec(
        key="area_max_m2", group=GROUP_PREFER, label="전용면적 상한",
        effect=EFFECT_CANDIDATE_FILTER,
        request_field="area_max_m2", prefer_key="area_max_m2",
        proof="area_filters_candidates",
        why="위와 같다. min > max 는 조용히 뒤집지 않고 거절한다(400)."),
    ConditionSpec(
        key="built_after", group=GROUP_PREFER, label="준공 연도(이후)",
        effect=EFFECT_CANDIDATE_FILTER,
        request_field="built_after", prefer_key="built_after",
        proof="built_after_filters_candidates",
        why=("지도(`/map/complexes`)가 이미 거르는 조건이다. 추천만 안 거르면 "
             "'지도엔 없는데 추천엔 뜨는' 단지가 생긴다 — 평수와 같은 계열의 결함이다.")),
    ConditionSpec(
        key="min_households", group=GROUP_PREFER, label="최소 세대수",
        effect=EFFECT_CANDIDATE_FILTER,
        request_field="min_households", prefer_key="min_households",
        proof="min_households_filters_candidates",
        why="단지 규모는 환금성·관리비와 직결된다. 세대수 미상은 통과시키지 않고 센다."),
    ConditionSpec(
        key="subway_within_m", group=GROUP_PREFER, label="역세권",
        effect=EFFECT_NOT_APPLIED, prefer_key="subway_within_m",
        gap_note=("역세권 조건(선택한 거리)은 아직 추천 후보 선별에 반영되지 않습니다 — "
                  "역 데이터가 없는 지역에서 '역이 없음'과 '데이터가 없음'을 구분할 수 없어, "
                  "잘못 걸러내는 대신 반영하지 않습니다. 추천 카드에는 최근접 역 거리를 함께 표시합니다."),
        why=("하드 필터로 쓰려면 역 POI 커버리지가 지역별로 보장돼야 한다. 지금은 "
             "미수집 지역이 '역 없음'으로 둔갑해 후보가 통째로 사라진다 — 조용한 실패다. "
             "대신 `nearest_station` 값을 추천 응답에 실어 화면이 표시·정렬할 수 있게 한다.")),
    ConditionSpec(
        key="school_district", group=GROUP_PREFER, label="학군 중요도",
        effect=EFFECT_NOT_APPLIED, prefer_key="school_district",
        gap_note=("학군 중요도는 아직 추천 순위에 반영되지 않습니다 — 순위 비중은 "
                  "'무엇을 더 중요하게 볼까요'의 입지 비중으로 반영됩니다."),
        why="0~5 중요도를 입지 축 가중치와 어떻게 합칠지 미확정(2차). 있는 척하지 않는다."),

    # --- 내 조건 · 기피 ----------------------------------------------------
    ConditionSpec(
        key="main_road_noise", group=GROUP_AVOID, label="대로변 소음",
        effect=EFFECT_EXCLUSION, prefer_key="main_road_noise",
        proof="avoid_excludes_and_off_restores",
        why="유해요소 반경 판정에 해당하면 가점 상쇄가 아니라 **제외**다(F5)."),
    ConditionSpec(
        key="first_floor", group=GROUP_AVOID, label="1층",
        effect=EFFECT_NOT_APPLIED, prefer_key="first_floor",
        gap_note=("'1층 기피'는 아직 추천에서 걸러지지 않습니다 — 후보는 특정 매물이 아니라 "
                  "단지·면적대 단위라 층을 특정할 수 없습니다(호가 수집 후 반영 예정)."),
        why=("공공 API 에는 호가가 없어 후보가 '단지 × 면적대'다. 층은 개별 매물의 속성이라 "
             "지금 구조에서는 판정 대상이 없다 — 없는 판정을 있는 척하면 그게 더 나쁘다.")),
    ConditionSpec(
        key="redevelopment_early_stage", group=GROUP_AVOID, label="재건축 초기 단계",
        effect=EFFECT_NOT_APPLIED, prefer_key="redevelopment_early_stage",
        gap_note=("'재건축 초기 단계 기피'는 아직 추천에서 걸러지지 않습니다 — "
                  "정비사업 단계 데이터가 후보 판정에 연결되기 전입니다."),
        why="risk-auditor·policy-researcher 는 2차 에이전트다(MVP 5종에 없다)."),

    # --- 내 조건 · 가중치 --------------------------------------------------
    ConditionSpec(
        key="price", group=GROUP_WEIGHT, label="가격 비중",
        effect=EFFECT_RANKING, prefer_key="price",
        proof="weights_change_order",
        why="호가 갭 축. 근거가 없으면 총점에서 빼고 재정규화하되 그 사실을 응답에 남긴다."),
    ConditionSpec(
        key="value", group=GROUP_WEIGHT, label="가치 비중",
        effect=EFFECT_RANKING, prefer_key="value",
        proof="weights_change_order",
        why="환금성 축."),
    ConditionSpec(
        key="location", group=GROUP_WEIGHT, label="입지 비중",
        effect=EFFECT_RANKING, prefer_key="location",
        proof="weights_change_order_location",
        why="입지 실측 축. 실측이 없으면 반영되지 않고 그 사실을 notes 로 고지한다."),
    ConditionSpec(
        key="risk", group=GROUP_WEIGHT, label="리스크 비중",
        effect=EFFECT_RANKING, prefer_key="risk",
        proof="weights_change_order_risk",
        why="리스크 신호 축(부분 커버리지)."),
)


def specs(group: str | None = None) -> tuple[ConditionSpec, ...]:
    return tuple(s for s in REGISTRY if group is None or s.group == group)


def spec_keys(group: str) -> frozenset[str]:
    return frozenset(s.key for s in REGISTRY if s.group == group)


def filter_specs() -> tuple[ConditionSpec, ...]:
    """후보 선별(hard filter) 조건들. 러너가 이 목록으로 값을 모은다."""
    return tuple(s for s in REGISTRY if s.effect == EFFECT_CANDIDATE_FILTER)


def request_fields() -> frozenset[str]:
    return frozenset(s.request_field for s in REGISTRY if s.request_field)


# ---------------------------------------------------------------------------
# 값 해석 — 요청 본문 ∪ 저장된 선호
# ---------------------------------------------------------------------------
#
# 왜 둘 다 보나: "내 조건" 화면이 저장한 값(`user_preference.prefer`)이 사용자가 말한
# 조건의 **정본**이고, 요청 본문은 그 자리에서 덮어쓰는 값이다. 요청만 보면 프론트가
# 한 줄 빠뜨리는 순간(이번 사고가 정확히 그것이다) 조건이 통째로 증발한다.
# 반대로 저장본만 보면 "이번만 다르게" 를 할 수 없다. 그래서 **요청 우선 · 저장본 폴백**이다.

_NOT_SET = object()

#: "이번에는 저장된 내 조건을 쓰지 마라" 스위치(`RecommendationIn.use_saved_conditions`).
#: 폴백만 있으면 **조건을 끄는 방법이 없다** — 화면에서 면적 칩을 껐는데 추천은 계속
#: 걸러지는 상태가 되고, 그건 이번 사고의 거울상(끈 조건이 계속 켜져 있음)이다.
USE_SAVED_FIELD = "use_saved_conditions"


def _pick(criteria: Mapping[str, Any], prefer: Mapping[str, Any],
          spec: ConditionSpec, *, use_saved: bool = True) -> Any:
    if spec.request_field:
        value = criteria.get(spec.request_field, _NOT_SET)
        if value is not _NOT_SET and value is not None:
            return value
    if spec.prefer_key and use_saved:
        return prefer.get(spec.prefer_key)
    return None


def _positive_number(value: Any) -> float | None:
    """0·음수·숫자 아님 → None(= 조건 없음). 면적 0㎡ 는 존재하지 않는 값이다.

    ⚠️ 걸러낸 사실은 호출부가 **말해야 한다** — `_rejected_value_note` 참조.
       조용히 None 으로 만들면 조건이 사라진 것을 아무도 모른다(SR24-6).
    """
    if value is None or isinstance(value, bool):
        return None
    try:
        num = float(value)
    except (TypeError, ValueError):
        return None
    if num != num or num in (float("inf"), float("-inf")) or num <= 0:
        return None
    return num


#: 값이 조건이 될 수 없어 무시했다는 고지. **조용히 사라지는 것만은 안 된다.**
VALUE_REJECTED = (
    "'{label}' 에 조건으로 쓸 수 없는 값({value})이 들어와 이 조건을 적용하지 "
    "않았습니다. 내 조건에서 값을 확인해 주세요."
)

#: 사용자에게 보일 조건 이름. 레지스트리 키를 그대로 보여 주면 읽히지 않는다.
_CONDITION_LABELS = {
    "area_min_m2": "전용면적 최소",
    "area_max_m2": "전용면적 최대",
    "built_after": "준공연도",
    "min_households": "최소 세대수",
}


def _rejected_value_note(key: str, raw: Any, parsed: float | None) -> str | None:
    """값이 있었는데 조건이 되지 못했으면 그 사실을 문장으로.

    ⚠️ API 스키마(`RecommendationIn`)는 `Infinity` 를 422 로 막지만, **저장된 내 조건**
       (`user_preference.prefer`)은 `dict[str, Any]` 라 그 검증을 거치지 않는다.
       파이썬 `json.loads` 는 `Infinity` 리터럴을 그대로 받아들이므로 이 경로는 실재한다.
       그래서 도메인에서도 한 번 더 말한다 — 두 방어는 서로를 대신하지 못한다.
    """
    if raw is None or parsed is not None:
        return None
    if isinstance(raw, str) and not raw.strip():
        return None            # 빈 문자열 = "안 보냄"으로 읽는다(늘 뜨는 고지는 소음이다)
    # 원문을 그대로 되비추되 **길이는 자른다** — notes 는 저장돼 화면에 그려지는 문자열이라
    # 임의 길이 입력을 통째로 실어 나르지 않는다(값 자체는 사용자가 보낸 면적·세대수다).
    shown = str(raw)
    if len(shown) > 40:
        shown = shown[:40] + "…"
    return VALUE_REJECTED.format(label=_CONDITION_LABELS.get(key, key), value=shown)


@dataclass(frozen=True)
class FilterConditions:
    """후보 선별에 실제로 적용되는 값들. **여기 없는 조건은 적용되지 않는다.**"""

    area_min_m2: float | None = None
    area_max_m2: float | None = None
    built_after: int | None = None
    min_households: int | None = None
    #: 적용하지 못한 조건에 대한 고지(형식 오류 등). 조용히 버리지 않는다.
    problems: tuple[str, ...] = ()

    @property
    def area_active(self) -> bool:
        return self.area_min_m2 is not None or self.area_max_m2 is not None

    @property
    def active(self) -> bool:
        return bool(self.area_active or self.built_after is not None
                    or self.min_households is not None)

    def area_ok(self, area_m2: float | None) -> bool:
        """면적 판정. **미상(None·0 이하)은 통과시키지 않는다.**

        조건이 걸렸는데 면적 미상을 통과시키면 "조건에 안 맞는 게 나온다"가 그대로
        재현된다. 반대로 조용히 버리면 유실이므로, 호출부가 **버린 건수를 센다**.
        """
        if not self.area_active:
            return True
        if area_m2 is None or area_m2 <= 0:
            return False
        if self.area_min_m2 is not None and area_m2 < self.area_min_m2:
            return False
        if self.area_max_m2 is not None and area_m2 > self.area_max_m2:
            return False
        return True

    def area_known(self, area_m2: float | None) -> bool:
        return area_m2 is not None and area_m2 > 0

    def built_ok(self, built_year: int | None) -> bool:
        if self.built_after is None:
            return True
        return built_year is not None and built_year >= self.built_after

    def households_ok(self, total_households: int | None) -> bool:
        if self.min_households is None:
            return True
        return total_households is not None and total_households >= self.min_households

    def repo_kwargs(self) -> dict[str, Any]:
        """리포지토리 후보 조회에 넘길 인자. 값이 없으면 키도 없다."""
        out: dict[str, Any] = {}
        if self.area_min_m2 is not None:
            out["area_min_m2"] = self.area_min_m2
        if self.area_max_m2 is not None:
            out["area_max_m2"] = self.area_max_m2
        if self.built_after is not None:
            out["built_after"] = self.built_after
        if self.min_households is not None:
            out["min_households"] = self.min_households
        return out

    def describe(self) -> str:
        """사용자에게 그대로 보여줄 '적용된 조건' 문구."""
        parts: list[str] = []
        if self.area_active:
            if self.area_min_m2 is not None and self.area_max_m2 is not None:
                parts.append(f"전용 {_num(self.area_min_m2)}~{_num(self.area_max_m2)}㎡")
            elif self.area_min_m2 is not None:
                parts.append(f"전용 {_num(self.area_min_m2)}㎡ 이상")
            else:
                parts.append(f"전용 {_num(self.area_max_m2)}㎡ 이하")
        if self.built_after is not None:
            parts.append(f"{self.built_after}년 이후 준공")
        if self.min_households is not None:
            parts.append(f"{self.min_households:,}세대 이상")
        return " · ".join(parts)


def _num(value: float | None) -> str:
    if value is None:
        return "-"
    return str(int(value)) if float(value).is_integer() else f"{value:g}"


#: min > max 로 뒤집힌 면적 조건에 대한 고지. **조용히 뒤집거나 무시하지 않는다.**
AREA_RANGE_INVERTED = (
    "전용면적 조건의 최소값이 최대값보다 커서 면적 조건을 적용하지 않았습니다 "
    "(최소 {min}㎡ > 최대 {max}㎡). 내 조건에서 값을 확인해 주세요."
)


def resolve_filter_conditions(criteria: Mapping[str, Any] | None,
                              prefer: Mapping[str, Any] | None) -> FilterConditions:
    """요청 본문 + 저장된 선호 → 실제 적용할 후보 선별 조건.

    ⚠️ 레지스트리(`filter_specs`)를 돌면서 값을 모은다. 새 필터 조건을 레지스트리에
       추가하면 여기서 `FilterConditions` 필드가 없다는 사실이 바로 드러난다
       (테스트가 그 대응을 강제한다).
    """
    criteria = criteria or {}
    prefer = prefer or {}
    # 명시적으로 False 일 때만 저장본을 무시한다(키가 없으면 예전처럼 폴백).
    use_saved = criteria.get(USE_SAVED_FIELD, True) is not False
    values: dict[str, Any] = {}
    for spec in filter_specs():
        values[spec.key] = _pick(criteria, prefer, spec, use_saved=use_saved)

    area_min = _positive_number(values.get("area_min_m2"))
    area_max = _positive_number(values.get("area_max_m2"))
    built_after = _positive_number(values.get("built_after"))
    min_households_raw = values.get("min_households")
    min_households = _positive_number(min_households_raw)

    problems: list[str] = []
    # 값이 왔는데 조건이 되지 못한 것들을 먼저 말한다(Infinity·문자열·0 등).
    for key, parsed in (("area_min_m2", area_min), ("area_max_m2", area_max),
                        ("built_after", built_after),
                        ("min_households", min_households)):
        note = _rejected_value_note(key, values.get(key), parsed)
        if note:
            problems.append(note)
    if area_min is not None and area_max is not None and area_min > area_max:
        # 뒤집어서 "고쳐 주면" 사용자가 틀린 조건으로 나온 결과를 맞다고 믿는다.
        problems.append(AREA_RANGE_INVERTED.format(min=_num(area_min), max=_num(area_max)))
        area_min = area_max = None

    return FilterConditions(
        area_min_m2=area_min,
        area_max_m2=area_max,
        built_after=int(built_after) if built_after is not None else None,
        min_households=int(min_households) if min_households is not None else None,
        problems=tuple(problems),
    )


def resolve_budget_override(criteria: Mapping[str, Any] | None,
                            prefer: Mapping[str, Any] | None) -> int | None:
    """희망 매매가(예산 상한). **요청 우선 · 저장된 내 조건 폴백**.

    면적과 같은 규칙을 쓴다. 화면은 희망가를 `prefer.target_price_krw` 에 저장하고
    요청에는 `budget_override_krw` 로 싣는데, 요청만 읽으면 클라이언트가 한 줄
    빠뜨리는 순간 사용자가 정한 상한이 조용히 사라지고 **자기 최대 한도**가 쓰인다
    (예산이 늘어난 것처럼 보이는 실패 — 결과가 비는 것보다 알아채기 어렵다).
    0·음수는 조건 없음으로 본다(가격 없는 상한은 상한이 아니다).
    """
    criteria = criteria or {}
    prefer = prefer or {}
    use_saved = criteria.get(USE_SAVED_FIELD, True) is not False
    spec = next(s for s in REGISTRY if s.key == "target_price_krw")
    num = _positive_number(_pick(criteria, prefer, spec, use_saved=use_saved))
    return int(num) if num is not None else None


def unapplied_notes(prefer: Mapping[str, Any] | None,
                    avoid: Mapping[str, Any] | None = None) -> list[str]:
    """설정돼 있지만 **아직 반영되지 않는** 조건을 사용자에게 말한다.

    값을 넣지 않은 조건까지 떠들지 않는다 — 늘 뜨는 경고는 아무도 읽지 않는다.
    """
    prefer = prefer or {}
    avoid = avoid or {}
    out: list[str] = []
    for spec in REGISTRY:
        if spec.effect != EFFECT_NOT_APPLIED or not spec.gap_note:
            continue
        source = avoid if spec.group == GROUP_AVOID else prefer
        if _is_set(source.get(spec.prefer_key or spec.key)):
            out.append(spec.gap_note)
    return out


def _is_set(value: Any) -> bool:
    """사용자가 **실제로 값을 넣었는가**. 0·False·빈 값은 '설정 안 함'이다."""
    if value is None or value is False:
        return False
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        return value > 0
    if isinstance(value, str):
        return bool(value.strip())
    if isinstance(value, Iterable):
        return bool(list(value))
    return bool(value)
