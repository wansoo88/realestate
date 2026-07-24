"""입지 분석 테스트 (ORDER 2026-07-25-06-domain).

DoD 를 그대로 테스트로 고정한다:
1. 학군은 **거리가 아니라 학구도 포함 여부**로 판정된다.
2. 미착공 호재의 confidence 가 0.4 이하다.
3. 기피 조건이 **제외**로 처리된다(가점 상쇄 아님).
4. 동별 판단의 confidence 가 0.6 이하이고 **금액 환산이 없다.**
5. 입지 데이터가 있으면 location_finding 이 판단 보류 대신 실제 근거를 낸다.
"""
from __future__ import annotations

import dataclasses
import datetime as dt

from app.agents.base import validate_finding
from app.domain.location.analysis import (
    assess_school,
    estimate_buildings,
    evaluate_location,
    plan_confidence,
    screen_hazards,
)
from app.domain.location.models import (
    BuildingLocationFact,
    HazardFact,
    LocationFacts,
    PoiFact,
    SchoolFact,
    StationFact,
    TransitPlan,
)

TODAY = dt.date(2026, 7, 25)


def _facts(**over) -> LocationFacts:
    base = dict(
        school=SchoolFact(name="○○초", in_district=True, distance_m=340,
                          crosses_main_road=False, district_as_of="2026"),
        stations=(StationFact("○○역", 420, ("2호선", "신분당선")),),
        plans=(),
        pois=(PoiFact("mart", 610), PoiFact("park", 250),
              PoiFact("hospital", 1200, has_emergency_room=True)),
        hazards=(),
    )
    base.update(over)
    return LocationFacts(**base)


# ---------------------------------------------------------------------------
# 1. 학군 — 학구도 포함 여부(거리 아님)
# ---------------------------------------------------------------------------

def test_학군은_학구도_포함이면_배정을_인정한다():
    school, missing = assess_school(
        SchoolFact(name="○○초", in_district=True, distance_m=340, district_as_of="2026"))
    assert school is not None
    assert school["assigned_elementary"] == "○○초"
    assert not missing


def test_학구도_미포함이면_가까워도_배정을_대체하지_않는다():
    """단지 코앞에 학교가 있어도 학구도에 없으면 배정이 아니다 — 거리로 대체 금지."""
    school, missing = assess_school(
        SchoolFact(name="△△초", in_district=False, distance_m=50, district_as_of="2026"))
    assert school is None
    assert any("대체하지 않" in m for m in missing)


def test_학구도_데이터가_없으면_학군을_비운다():
    school, missing = assess_school(
        SchoolFact(district_data_available=False))
    assert school is None
    assert any("학구도 데이터 미확보" in m for m in missing)


def test_학업성취도는_출처_없으면_쓰지_않는다():
    school, missing = assess_school(
        SchoolFact(name="○○초", in_district=True, distance_m=300,
                   district_as_of="2026", achievement_pct=91.2))  # 출처·기준연도 없음
    assert "achievement_pct" not in school
    assert any("학업성취도" in m for m in missing)


def test_학업성취도는_출처가_있으면_쓴다():
    school, _ = assess_school(
        SchoolFact(name="○○초", in_district=True, distance_m=300, district_as_of="2026",
                   achievement_pct=91.2, achievement_source="학교알리미",
                   achievement_as_of="2025"))
    assert school["achievement_pct"] == 91.2
    assert school["achievement_source"] == "학교알리미"


# ---------------------------------------------------------------------------
# 2. 교통 호재 — 착공 전이면 confidence ≤ 0.4
# ---------------------------------------------------------------------------

def test_미착공_호재는_신뢰도가_04이하다():
    assert plan_confidence("계획") <= 0.4
    assert plan_confidence("알수없는단계") <= 0.4        # 미상 → 가장 보수적


def test_착공_이후는_신뢰도를_더_준다():
    assert plan_confidence("착공") > 0.4
    assert plan_confidence("개통") > plan_confidence("착공")


def test_평가에_실린_계획호재_신뢰도도_04이하():
    a = evaluate_location(
        _facts(plans=(TransitPlan("GTX-C", "계획", open_expected="2030-12"),)),
        as_of=TODAY)
    assert a.transit["planned"][0]["confidence"] <= 0.4
    # 착공 전 호재는 지연 리스크로 명시된다(확정 호재로 쓰지 않는다).
    assert any("지연" in r["detail"] for r in a.risks)


def test_계획호재는_점수를_올리지_않는다():
    """미착공 노선을 확정 호재처럼 점수에 반영하면 안 된다."""
    without = evaluate_location(_facts(), as_of=TODAY)
    withplan = evaluate_location(
        _facts(plans=(TransitPlan("GTX-C", "계획", open_expected="2030-12"),)),
        as_of=TODAY)
    assert withplan.score == without.score


# ---------------------------------------------------------------------------
# 3. 기피 조건 — 제외(가점 상쇄 아님)
# ---------------------------------------------------------------------------

def test_기피조건에_해당하면_제외된다():
    screen = screen_hazards(
        [HazardFact("main_road_noise", 30)], avoid=["소음"])
    assert screen.excluded is True
    assert screen.exclusion_reasons
    # 제외지 감점이 아니다 — penalties 로 흘려보내지 않는다.
    assert screen.penalties == ()


def test_기피목록에_없는_유해요소는_경고로만_남는다():
    screen = screen_hazards([HazardFact("railway", 60)], avoid=["소음"])
    assert screen.excluded is False
    assert screen.penalties
    assert screen.penalties[0]["type"] == "railway"


def test_반경_밖_유해요소는_무시된다():
    # 간선도로 소음 반경 50m 밖 → 존재로 보지 않는다.
    screen = screen_hazards([HazardFact("main_road_noise", 400)], avoid=["소음"])
    assert screen.excluded is False
    assert screen.penalties == ()


def test_평가_전체에서_기피는_제외로_이어진다():
    a = evaluate_location(
        _facts(hazards=(HazardFact("main_road_noise", 30),)),
        avoid=["대로변"], as_of=TODAY)
    assert a.excluded is True
    assert a.exclusion_reasons


# ---------------------------------------------------------------------------
# 4. 동별 추정 — confidence ≤ 0.6, 금액 환산 없음
# ---------------------------------------------------------------------------

def _bldgs():
    """역 거리만 다르고 나머지는 같은 두 동 — '역 근접 → 상대점수 우위'를 격리 검증."""
    return [
        BuildingLocationFact(building_id=101, label="101동", station_distance_m=640,
                             school_distance_m=320, school_in_district=True,
                             main_road_distance_m=200, park_distance_m=200),
        BuildingLocationFact(building_id=105, label="105동", station_distance_m=420,
                             school_distance_m=320, school_in_district=True,
                             main_road_distance_m=200, park_distance_m=200),
    ]


def test_동별추정_신뢰도는_06이하다():
    ests = estimate_buildings(_bldgs())
    assert ests
    assert all(e.confidence <= 0.6 for e in ests)
    assert all(e.basis == "estimated_from_location" for e in ests)


def test_동별추정은_금액을_환산하지_않는다():
    ests = estimate_buildings(_bldgs())
    # 금액 필드가 아예 없어야 한다.
    field_names = {f.name for f in dataclasses.fields(ests[0])}
    assert not any("krw" in n or "price" in n for n in field_names)
    # 근거 문장에도 금액 표현이 없어야 한다.
    for e in ests:
        for factor in e.factors:
            assert "원" not in factor and "억" not in factor


def test_동별추정은_상대점수만_낸다():
    ests = {e.building_id: e for e in estimate_buildings(_bldgs())}
    assert all(0.0 <= e.relative_score <= 1.0 for e in ests.values())
    # 역이 더 가까운 105동이 101동보다 상대점수가 높아야 한다(도로 감점에도 불구).
    assert ests[105].relative_score >= ests[101].relative_score


def test_동이_하나면_상대비교를_하지_않는다():
    ests = estimate_buildings(_bldgs()[:1])
    assert ests == []


def test_간선도로_인접동은_소음_근거가_붙고_상대점수가_낮다():
    """역이 가까워도 간선도로 코앞이면 소음 감점이 근거로 드러나야 한다."""
    bldgs = [
        BuildingLocationFact(building_id=101, label="101동", station_distance_m=640,
                             school_distance_m=320, school_in_district=True,
                             main_road_distance_m=250, park_distance_m=200),
        BuildingLocationFact(building_id=105, label="105동", station_distance_m=420,
                             school_distance_m=320, school_in_district=True,
                             main_road_distance_m=40, park_distance_m=200),
    ]
    ests = {e.building_id: e for e in estimate_buildings(bldgs)}
    assert any("간선도로" in f for f in ests[105].factors)
    assert ests[105].relative_score <= ests[101].relative_score


# ---------------------------------------------------------------------------
# 5. 데이터가 있으면 실제 근거를 낸다 (판단 보류 아님)
# ---------------------------------------------------------------------------

def test_입지데이터가_있으면_실제근거를_낸다():
    a = evaluate_location(_facts(), as_of=TODAY)
    assert a.verdict != "판단 보류"
    assert a.score is not None
    assert a.evidence
    assert 0.0 < a.confidence <= 0.85


def test_location_finding_이_실제_Finding을_낸다():
    from app.agents.orchestrator import Candidate, location_finding
    from app.domain.listings.dedup import group_duplicates
    from app.domain.valuation.models import ListingRow

    listing = ListingRow(id=1, ask_price_krw=800_000_000, area_m2=84.0, floor=10)
    cand = Candidate(complex_id=1, complex_name="○○아파트", unit_type_id=5,
                     area_m2=84.0, group=group_duplicates([listing])[0],
                     location=_facts())
    f = location_finding(cand, TODAY)
    validate_finding(f)                      # 계약 위반이면 여기서 예외
    assert f.verdict != "판단 보류"
    assert f.evidence
    assert f.agent_id == "location-analyst"


def test_학구도_없어도_교통_인프라로_판정한다():
    a = evaluate_location(
        _facts(school=SchoolFact(district_data_available=False)), as_of=TODAY)
    assert a.score is not None                # 학군은 비었어도 다른 축으로 점수
    assert a.school is None
    assert any("학구도" in m for m in a.missing)


# ---------------------------------------------------------------------------
# 파이프라인 — 기피 후보는 excluded 로 빠진다
# ---------------------------------------------------------------------------

def test_파이프라인에서_기피후보는_제외된다():
    from app.agents.orchestrator import AnalysisContext, Candidate, run_mvp_pipeline
    from app.domain.affordability.engine import compute_affordability
    from app.domain.affordability.models import Borrower, PropertyFacts
    from app.domain.listings.dedup import group_duplicates
    from app.domain.rules.loader import load_rules
    from app.domain.valuation.models import ListingRow
    from pathlib import Path

    rules = load_rules(Path(__file__).parent / "fixtures" / "tax_rules_test.yaml")
    afford = compute_affordability(
        Borrower(cash_krw=500_000_000, annual_income_krw=300_000_000), rules,
        prop=PropertyFacts(area_m2=84.0))

    listing = ListingRow(id=1, ask_price_krw=700_000_000, area_m2=84.0, floor=10)
    cand = Candidate(complex_id=7, complex_name="철도변아파트", unit_type_id=5,
                     area_m2=84.0, group=group_duplicates([listing])[0],
                     location=_facts(hazards=(HazardFact("railway", 40),)))
    ctx = AnalysisContext(affordability=afford, candidates=[cand], as_of=TODAY,
                          avoid={"철도": True})
    out = run_mvp_pipeline(ctx, llm=None)

    assert out["items"] == []
    assert out["excluded"]
    assert "철도" in out["excluded"][0]["reason"]
