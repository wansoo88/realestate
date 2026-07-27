"""입지 분석 입출력 모델. 순수 데이터클래스.

설계 근거: docs/02-design/agents/04-location-analyst.md, docs/02-design/erd.md §0

경계
----
공간쿼리(``ST_Contains`` / ``ST_Distance`` / 학구도 포함 판정)는 **리포지토리가 수행**해
그 결과(포함 여부·거리·좌표)를 이 모델로 넘긴다. 이 계층은 그 사실을 점수·근거로
바꾸는 **순수 함수**만 갖는다. DB 도, PostGIS 도 여기서 만지지 않는다.

절대 규칙(role: re-domain)
--------------------------
* 학군은 **거리가 아니라 학구도 포함 여부**로 판정한다. 학구도가 없으면 최근접 학교
  거리로 대체하지 않는다(배정과 거리는 다른 개념).
* 교통 호재는 착공 전이면 신뢰도 ≤ 0.4. "개통 예정"을 확정 호재로 쓰지 않는다.
* 동(棟)별 판단은 좌표 기반 추정 → 신뢰도 ≤ 0.6, 금액으로 환산하지 않는다.
* 기피 조건은 **가점 상쇄가 아니라 제외**다.
"""
from __future__ import annotations

from dataclasses import dataclass, field


# ---------------------------------------------------------------------------
# 입력 사실 (repository 가 공간쿼리로 채워 넘긴다)
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class SchoolFact:
    """학교급 하나의 학구도 공간판정 결과. **급마다 뜻이 다르다.**

    ``in_district`` 는 ``ST_Contains(school_district.geom, complex.geom)`` 결과다.
    ``distance_m`` 는 통학 거리(직선/네트워크)일 뿐 **도보 시간이 아니며**, 학군 배정의
    근거도 아니다. 배정 근거는 오직 ``in_district`` 다.

    ⚠️ ``in_district`` 가 참이라고 해서 "이 학교에 간다"가 되는 건 아니다.
       그 판단은 ``candidate_count`` 와 ``zone_kind`` 를 함께 봐야 한다:

         통학구역(초등) · 후보 1곳  → 배정이라고 말할 수 있다.
         통학구역(초등) · 후보 N곳  → **공동학구**. 배정 학교를 단정할 수 없다.
         학교군(중·고)             → 후보 N곳. 어떻게 배정되는지는 **원천에 없다**.

       그래서 이 모델은 '배정'을 필드로 갖지 않는다. 가진 것은 셀 수 있는 사실뿐이고,
       그것을 어떤 문장으로 낼지는 ``analysis.assess_school*`` 이 정한다.
    """

    name: str | None = None
    #: 학교급(초등학교|중학교|고등학교). 기본값은 하위호환을 위한 초등이다.
    level: str = "초등학교"
    in_district: bool = False
    distance_m: float | None = None
    crosses_main_road: bool | None = None
    #: 학구도 기준 연도(배정은 바뀔 수 있으므로 함께 표기)
    district_as_of: str | None = None
    #: 해당 지역 학구도 데이터 자체가 확보됐는가. False 면 학군 항목을 비운다.
    district_data_available: bool = True
    #: 구역 이름(원천 HAKGUDO_NM). '서울언주초통학구역' · '강남서초학교군'.
    zone_name: str | None = None
    #: 구역 종류(통학구역|학교군). **원천 데이터셋 제목에서 온 낱말**이지 배정 방식이 아니다.
    zone_kind: str | None = None
    #: 이 단지가 속한 구역(들)에 연계된 학교 수. 1이면 배정, 2 이상이면 후보다.
    candidate_count: int | None = None
    #: 단지를 덮는 구역의 수(자유학구 등으로 겹칠 수 있다).
    zone_count: int | None = None
    #: 교육지원청명(원천 연계정보 CSV). 고등학교 '1학교군'처럼 이름이 겹칠 때 필요하다.
    education_office: str | None = None
    #: 학업성취도(%) — 출처·기준연도가 함께 있을 때만 사용한다.
    achievement_pct: float | None = None
    achievement_source: str | None = None
    achievement_as_of: str | None = None


@dataclass(frozen=True)
class StationFact:
    """지하철/철도역 한 곳까지의 최단거리와 경유 노선."""

    name: str
    distance_m: float
    lines: tuple[str, ...] = ()          # 노선 수 = len(lines) → 환승 가치


@dataclass(frozen=True)
class TransitPlan:
    """신설 노선 계획(GTX·신안산선 등). **확정 호재가 아니다.**

    ``status`` 는 계획 | 착공 | 개통. 신뢰도는 이 단계에서 결정한다.
    """

    name: str
    status: str                          # 계획 | 착공 | 개통
    open_expected: str | None = None
    source: str | None = None
    as_of: str | None = None


@dataclass(frozen=True)
class PoiFact:
    """생활 인프라 POI 최단거리. ``kind`` = mart | hospital | park | library ..."""

    kind: str
    distance_m: float
    name: str | None = None
    #: 병원일 때만 의미 — 응급실 보유 여부
    has_emergency_room: bool | None = None


@dataclass(frozen=True)
class HazardFact:
    """유해·감점 요소. 이미 반경 안에 있는 것만 repository 가 넘긴다.

    ``kind`` = main_road_noise | railway | harmful_facility | power_line
    """

    kind: str
    distance_m: float
    detail: str | None = None


@dataclass(frozen=True)
class LocationFacts:
    """단지 하나의 입지 사실 묶음. location-analyst 의 입력."""

    #: 초등 통학구역. 이름이 `school` 인 것은 013 이전부터 쓰던 자리라서다.
    school: SchoolFact | None = None
    #: 중학교 학교군. 배정이 아니라 **후보 범위**다(models.SchoolFact ⚠️).
    middle_school: SchoolFact | None = None
    #: 고등학교 학교군. 수도권 학구당 학교 평균 14.4곳 — 사실상 광역이다.
    high_school: SchoolFact | None = None
    stations: tuple[StationFact, ...] = ()
    plans: tuple[TransitPlan, ...] = ()
    pois: tuple[PoiFact, ...] = ()
    hazards: tuple[HazardFact, ...] = ()


@dataclass(frozen=True)
class BuildingLocationFact:
    """동(棟) 하나의 좌표 기반 입지 사실. F4 §D 동별 추정 입력.

    실거래에 동 정보가 없으므로(erd.md §0) 동별 가치는 이 좌표 사실로 **추정**만 한다.
    """

    building_id: int
    label: str | None = None             # "105동"
    station_distance_m: float | None = None
    school_distance_m: float | None = None
    school_in_district: bool | None = None
    main_road_distance_m: float | None = None
    park_distance_m: float | None = None
    position_in_complex: str | None = None   # 중앙 | 외곽
    orientation_deg: float | None = None     # 방위각


# ---------------------------------------------------------------------------
# 출력 모델
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class TransitHope:
    """신설 노선 호재 평가 결과. 신뢰도가 낮으면 점수에 넣지 않고 리스크로만 남긴다."""

    name: str
    status: str
    confidence: float
    open_expected: str | None = None
    source: str | None = None
    as_of: str | None = None


@dataclass(frozen=True)
class HazardScreen:
    """유해요소 스크리닝 결과.

    ``excluded`` 는 사용자가 **기피**한 요소가 감지됐다는 뜻이다(가점 상쇄 아님, 제외).
    ``penalties`` 는 기피 목록엔 없지만 존재하는 요소 → 경고로만 남긴다.
    """

    excluded: bool = False
    exclusion_reasons: tuple[str, ...] = ()
    penalties: tuple[dict, ...] = ()


@dataclass(frozen=True)
class BuildingEstimate:
    """동별 상대 입지 점수(추정). **금액 필드는 없다** — 금액 환산 금지."""

    building_id: int
    label: str | None
    relative_score: float                # 0~1, 같은 단지 내 상대값
    confidence: float                    # ≤ 0.6 강제
    basis: str                           # "estimated_from_location"
    factors: tuple[str, ...] = ()


@dataclass(frozen=True)
class LocationAssessment:
    """location-analyst 종합 판정. orchestrator 가 이걸로 Finding 을 만든다."""

    score: float | None
    confidence: float
    verdict: str
    rationale: str
    #: 초등 통학구역 판정(`assess_school`). 키에 `assigned_elementary` 가 있다.
    school: dict | None = None
    #: 중·고 학교군 판정(`assess_school_group`). **`assigned_*` 키가 없다** —
    #: 학교군은 배정을 말하지 않으므로 그런 키를 만들지 않는 것이 방어선이다.
    middle_school: dict | None = None
    high_school: dict | None = None
    transit: dict = field(default_factory=dict)
    amenities: dict = field(default_factory=dict)
    penalties: tuple[dict, ...] = ()
    hopes: tuple[TransitHope, ...] = ()
    evidence: tuple[dict, ...] = ()      # {claim, source, as_of}
    risks: tuple[dict, ...] = ()         # {severity, detail}
    excluded: bool = False
    exclusion_reasons: tuple[str, ...] = ()
    missing: tuple[str, ...] = ()

    @property
    def has_evidence(self) -> bool:
        return bool(self.evidence)
