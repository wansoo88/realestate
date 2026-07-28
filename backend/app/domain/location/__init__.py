"""입지 분석 도메인 — location-analyst 의 순수 계산 계층.

공간쿼리(ST_Contains/ST_Distance)는 리포지토리 소관이고, 이 패키지는 그 결과를
점수·근거로 바꾼다. LLM 은 문장 생성에만 쓴다(숫자는 코드가).
"""
from app.domain.location.analysis import (
    BUILDING_ESTIMATE_BASIS,
    BUILDING_ESTIMATE_CONFIDENCE,
    PLAN_STATUS_CONFIDENCE,
    assess_infra,
    assess_school,
    assess_transit,
    estimate_buildings,
    evaluate_location,
    plan_confidence,
    screen_hazards,
)
from app.domain.location.models import (
    BuildingEstimate,
    BuildingLocationFact,
    HazardFact,
    HazardScreen,
    LocationAssessment,
    LocationFacts,
    PoiFact,
    SchoolFact,
    StationFact,
    TransitHope,
    TransitPlan,
)
from app.domain.location.school_quality import (
    COMPARABLE_ACHIEVEMENT_SOURCES,
    TAG_DEFINITION,
    TOP_PERCENTILE_THRESHOLD,
    AchievementFact,
    SchoolDistrictTag,
    assess_school_district_tag,
)

__all__ = [
    "COMPARABLE_ACHIEVEMENT_SOURCES",
    "BUILDING_ESTIMATE_BASIS",
    "BUILDING_ESTIMATE_CONFIDENCE",
    "PLAN_STATUS_CONFIDENCE",
    "TAG_DEFINITION",
    "TOP_PERCENTILE_THRESHOLD",
    "AchievementFact",
    "BuildingEstimate",
    "BuildingLocationFact",
    "HazardFact",
    "HazardScreen",
    "LocationAssessment",
    "LocationFacts",
    "PoiFact",
    "SchoolDistrictTag",
    "SchoolFact",
    "StationFact",
    "TransitHope",
    "TransitPlan",
    "assess_infra",
    "assess_school_district_tag",
    "assess_school",
    "assess_transit",
    "estimate_buildings",
    "evaluate_location",
    "plan_confidence",
    "screen_hazards",
]
