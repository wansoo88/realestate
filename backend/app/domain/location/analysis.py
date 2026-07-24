"""입지 분석 — 학군·교통·인프라·유해요소·동별 추정.

설계 근거: docs/02-design/agents/04-location-analyst.md,
          docs/02-design/agents/03-valuation-trader.md §D, erd.md §0

이 모듈이 지키는 규칙 (전부 테스트로 고정)
------------------------------------------
1. **학군은 학구도 포함 여부로 판정한다.** 거리로 대체하지 않는다.
2. **교통 호재는 착공 전이면 신뢰도 ≤ 0.4.** 계획을 확정 호재로 쓰지 않으며,
   신뢰도가 낮은 호재는 **점수에 넣지 않고** 리스크로만 남긴다.
3. **기피 조건은 제외다.** 감지되면 가점을 깎는 게 아니라 후보에서 뺀다.
4. **동별 판단은 좌표 기반 추정** → 신뢰도 ≤ 0.6, **금액으로 환산하지 않는다.**
5. 출처·기준연도 없는 수치(학업성취도 등)는 쓰지 않는다.

거리 임계값은 규제값이 아니라 **설계 휴리스틱**이다(출처 불요). 정책·세율과 달리
법적 근거가 필요한 수치가 아니므로 여기 상수로 두되 근거 주석을 남긴다.
"""
from __future__ import annotations

import datetime as dt
from collections.abc import Iterable, Sequence

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

# ---------------------------------------------------------------------------
# 상수 (설계 휴리스틱)
# ---------------------------------------------------------------------------

#: 신설 노선 단계별 신뢰도 상한. 착공 전(계획/미상)은 ≤ 0.4 — 지연이 흔하다.
PLAN_STATUS_CONFIDENCE: dict[str, float] = {
    "계획": 0.4,
    "착공": 0.6,
    "개통": 0.9,
}
#: 알 수 없는 단계는 가장 보수적으로. (착공 전으로 간주)
DEFAULT_PLAN_CONFIDENCE = 0.3

#: 신뢰도가 이 미만인 호재는 점수에 반영하지 않고 리스크로만 남긴다.
HOPE_SCORE_THRESHOLD = 0.5

#: 유해요소 판정 반경(m). 이 안이면 '존재'로 본다.
HAZARD_RADIUS_M: dict[str, float] = {
    "main_road_noise": 50,     # 간선도로 소음
    "railway": 100,            # 선로 인접
    "harmful_facility": 100,   # 유흥·공장·변전소·쓰레기처리
    "power_line": 150,         # 고압선·송전탑
}

HAZARD_LABEL: dict[str, str] = {
    "main_road_noise": "간선도로 소음",
    "railway": "철도 인접",
    "harmful_facility": "유해시설",
    "power_line": "고압선·송전탑",
}

#: 근접 점수 구간 (best_m 이하 100점, worst_m 이상 0점).
PROXIMITY_BANDS: dict[str, tuple[float, float]] = {
    "station": (250, 1500),
    "school": (300, 1500),
    "mart": (400, 2000),
    "park": (200, 1500),
    "hospital_er": (800, 4000),
}

#: 종합 점수 가중치 (있는 항목끼리 정규화).
COMPONENT_WEIGHTS: dict[str, float] = {"transit": 0.40, "school": 0.35, "infra": 0.25}

#: 기피 조건(사용자 자연어/코드) → 유해요소 kind 매핑.
AVOID_SYNONYMS: dict[str, str] = {
    "main_road_noise": "main_road_noise", "대로변": "main_road_noise",
    "간선도로": "main_road_noise", "소음": "main_road_noise",
    "railway": "railway", "철도": "railway", "선로": "railway",
    "harmful_facility": "harmful_facility", "유해시설": "harmful_facility",
    "유흥": "harmful_facility", "변전소": "harmful_facility",
    "power_line": "power_line", "고압선": "power_line", "송전탑": "power_line",
}


# ---------------------------------------------------------------------------
# 소도구
# ---------------------------------------------------------------------------

def _proximity_score(distance_m: float | None, best_m: float, worst_m: float) -> float | None:
    """거리를 0~100 근접 점수로. 가까울수록 높다. 거리 없으면 None(추정 금지)."""
    if distance_m is None:
        return None
    if distance_m <= best_m:
        return 100.0
    if distance_m >= worst_m:
        return 0.0
    return round((worst_m - distance_m) / (worst_m - best_m) * 100, 1)


def plan_confidence(status: str) -> float:
    """신설 노선 단계 → 신뢰도. **착공 전은 ≤ 0.4.**"""
    return PLAN_STATUS_CONFIDENCE.get(status, DEFAULT_PLAN_CONFIDENCE)


def _hazard_present(h: HazardFact) -> bool:
    radius = HAZARD_RADIUS_M.get(h.kind)
    if radius is None:                    # 알 수 없는 종류는 존재 자체로 본다
        return True
    return h.distance_m <= radius


def _hazard_severity(kind: str, distance_m: float) -> str:
    radius = HAZARD_RADIUS_M.get(kind, distance_m + 1)
    if distance_m <= radius * 0.5:
        return "high"
    if distance_m <= radius:
        return "medium"
    return "low"


def _canonical_avoids(avoid: Iterable[str] | None) -> set[str]:
    """사용자 기피 토큰을 유해요소 kind 로 정규화. 입지와 무관한 토큰은 버린다.

    (예: '1층'·'재건축리스크'는 각각 매물·리스크 감사 소관 → 여기서 무시)
    """
    out: set[str] = set()
    for token in avoid or ():
        kind = AVOID_SYNONYMS.get(str(token).strip())
        if kind:
            out.add(kind)
    return out


# ---------------------------------------------------------------------------
# A. 학군 — 학구도 포함 여부 (거리 아님)
# ---------------------------------------------------------------------------

def assess_school(fact: SchoolFact | None) -> tuple[dict | None, list[str]]:
    """학군 판정. 학구도 포함일 때만 배정을 인정한다.

    반환: (학군 dict | None, missing 사유들)
    """
    if fact is None or not fact.district_data_available:
        return None, ["학구도 데이터 미확보 — 배정 학교를 거리로 대체하지 않음"]
    if not fact.in_district or not fact.name:
        # 학구도가 있어도 포함되지 않으면 배정을 단정하지 않는다.
        # 최근접 학교 거리로 대체하는 것은 금지(배정과 거리는 다르다).
        return None, ["배정 초등학교 확인 불가(학구도 미포함) — 최근접 학교 거리로 대체하지 않음"]

    result: dict = {
        "assigned_elementary": fact.name,
        "in_district": True,
        "distance_m": fact.distance_m,
        "crosses_main_road": fact.crosses_main_road,
        "as_of": fact.district_as_of,
        "source": "학교알리미 학구도",
    }
    missing: list[str] = []
    if (fact.achievement_pct is not None
            and fact.achievement_source and fact.achievement_as_of):
        result["achievement_pct"] = fact.achievement_pct
        result["achievement_source"] = fact.achievement_source
        result["achievement_as_of"] = fact.achievement_as_of
    elif fact.achievement_pct is not None:
        # 숫자는 있으나 출처·기준연도가 없다 → 쓰지 않는다(원칙 2).
        missing.append("학업성취도 출처·기준연도 없음 — 수치 미사용")
    return result, missing


def _school_score(school: dict | None) -> float | None:
    if not school:
        return None
    base = _proximity_score(school.get("distance_m"), *PROXIMITY_BANDS["school"])
    if base is None:
        base = 60.0                       # 배정은 확인됐으나 거리 미상 → 중립
    if school.get("crosses_main_road"):
        base = max(0.0, base - 15)        # 통학로 대로 횡단은 감점
    ach = school.get("achievement_pct")
    if ach is not None:                   # 출처 검증을 통과한 값만 여기 온다
        base = round(base * 0.5 + float(ach) * 0.5, 1)
    return base


# ---------------------------------------------------------------------------
# B. 교통 — 실측 역세권 + 신설 노선 호재(신뢰도 표기)
# ---------------------------------------------------------------------------

def assess_transit(
    stations: Sequence[StationFact],
    plans: Sequence[TransitPlan],
    *,
    as_of: dt.date,
) -> tuple[dict, tuple[TransitHope, ...], list[dict]]:
    """교통 판정. 반환: (transit dict, 호재들, evidence)."""
    transit: dict = {}
    evidence: list[dict] = []

    nearest = min(stations, key=lambda s: s.distance_m) if stations else None
    if nearest is not None:
        transit["nearest_station"] = {
            "name": nearest.name,
            "distance_m": nearest.distance_m,
            "lines": list(nearest.lines),
            "line_count": len(nearest.lines),
        }
        evidence.append({
            "claim": f"최근접 역 {nearest.name} {nearest.distance_m:.0f}m"
                     f"(노선 {len(nearest.lines)}개)",
            "source": "역 좌표 최단거리(PostGIS)",
            "as_of": as_of.isoformat(),
        })

    hopes = tuple(
        TransitHope(
            name=p.name, status=p.status, confidence=plan_confidence(p.status),
            open_expected=p.open_expected, source=p.source, as_of=p.as_of,
        )
        for p in plans
    )
    if hopes:
        # 호재는 status·confidence 를 반드시 함께 낸다. "개통 예정"만 쓰지 않는다.
        transit["planned"] = [{
            "name": h.name, "status": h.status,
            "open_expected": h.open_expected, "confidence": h.confidence,
        } for h in hopes]
    return transit, hopes, evidence


def _transit_score(transit: dict) -> float | None:
    """역세권 점수. **신설 노선 호재는 반영하지 않는다**(착공 지연이 흔하다)."""
    ns = transit.get("nearest_station")
    if not ns:
        return None
    base = _proximity_score(ns["distance_m"], *PROXIMITY_BANDS["station"])
    if base is None:
        return None
    if ns.get("line_count", 0) >= 2:      # 환승역 가치
        base = min(100.0, base + 8)
    return base


# ---------------------------------------------------------------------------
# C. 생활 인프라
# ---------------------------------------------------------------------------

def assess_infra(
    pois: Sequence[PoiFact], *, as_of: dt.date,
) -> tuple[dict, list[dict]]:
    """마트·병원(응급실 구분)·공원 최단거리. 반환: (amenities, evidence)."""
    def nearest(kind: str, *, er: bool = False) -> float | None:
        cands = [p.distance_m for p in pois
                 if p.kind == kind and (not er or p.has_emergency_room)]
        return min(cands) if cands else None

    amenities: dict = {}
    mart = nearest("mart")
    park = nearest("park")
    hospital_er = nearest("hospital", er=True)
    hospital_any = nearest("hospital")
    if mart is not None:
        amenities["mart_m"] = mart
    if park is not None:
        amenities["park_m"] = park
    if hospital_er is not None:
        amenities["hospital_er_m"] = hospital_er
    elif hospital_any is not None:
        # 응급실 없는 병원은 별도 표기 — 응급실 있는 것처럼 쓰지 않는다.
        amenities["hospital_m"] = hospital_any

    evidence: list[dict] = []
    if amenities:
        evidence.append({
            "claim": "; ".join(f"{k}={v:.0f}m" for k, v in amenities.items()),
            "source": "공공 기초자료 POI 최단거리",
            "as_of": as_of.isoformat(),
        })
    return amenities, evidence


def _infra_score(amenities: dict) -> float | None:
    parts: list[float] = []
    if "mart_m" in amenities:
        parts.append(_proximity_score(amenities["mart_m"], *PROXIMITY_BANDS["mart"]))
    if "park_m" in amenities:
        parts.append(_proximity_score(amenities["park_m"], *PROXIMITY_BANDS["park"]))
    if "hospital_er_m" in amenities:
        parts.append(_proximity_score(amenities["hospital_er_m"],
                                      *PROXIMITY_BANDS["hospital_er"]))
    parts = [p for p in parts if p is not None]
    return round(sum(parts) / len(parts), 1) if parts else None


# ---------------------------------------------------------------------------
# D. 유해요소 — 기피는 제외(가점 상쇄 아님)
# ---------------------------------------------------------------------------

def screen_hazards(
    hazards: Sequence[HazardFact], avoid: Iterable[str] | None = None,
) -> HazardScreen:
    """유해요소 스크리닝. 사용자가 기피한 항목이 감지되면 **제외**한다."""
    avoid_kinds = _canonical_avoids(avoid)
    exclusion: list[str] = []
    penalties: list[dict] = []

    for h in hazards:
        if not _hazard_present(h):
            continue
        label = HAZARD_LABEL.get(h.kind, h.kind)
        if h.kind in avoid_kinds:
            # 기피 조건 = 제외. 점수를 깎는 게 아니라 후보에서 뺀다.
            exclusion.append(f"기피 조건 '{label}' 해당(거리 {h.distance_m:.0f}m)")
        else:
            penalties.append({
                "type": h.kind, "label": label, "distance_m": h.distance_m,
                "severity": _hazard_severity(h.kind, h.distance_m),
            })
    return HazardScreen(
        excluded=bool(exclusion),
        exclusion_reasons=tuple(exclusion),
        penalties=tuple(penalties),
    )


def _penalty_deduction(penalties: Sequence[dict]) -> float:
    weight = {"high": 15.0, "medium": 8.0, "low": 4.0}
    return sum(weight.get(p["severity"], 4.0) for p in penalties)


# ---------------------------------------------------------------------------
# 종합
# ---------------------------------------------------------------------------

def _weighted_score(components: dict[str, float | None]) -> float | None:
    """있는 항목끼리만 가중 평균."""
    num = 0.0
    den = 0.0
    for key, val in components.items():
        if val is None:
            continue
        w = COMPONENT_WEIGHTS[key]
        num += val * w
        den += w
    return round(num / den, 1) if den else None


def evaluate_location(
    facts: LocationFacts, *,
    avoid: Iterable[str] | None = None,
    as_of: dt.date | None = None,
) -> LocationAssessment:
    """단지 하나의 입지 종합 판정. 전부 순수 계산."""
    as_of = as_of or dt.date.today()

    school, school_missing = assess_school(facts.school)
    transit, hopes, transit_ev = assess_transit(facts.stations, facts.plans, as_of=as_of)
    amenities, infra_ev = assess_infra(facts.pois, as_of=as_of)
    screen = screen_hazards(facts.hazards, avoid)

    components = {
        "transit": _transit_score(transit),
        "school": _school_score(school),
        "infra": _infra_score(amenities),
    }
    base = _weighted_score(components)
    score = None
    if base is not None:
        score = max(0.0, round(base - _penalty_deduction(screen.penalties), 1))

    evidence: list[dict] = []
    if school:
        ev = {"claim": f"{school['assigned_elementary']} 학구도 내부",
              "source": "학교알리미 학구도",
              "as_of": school.get("as_of") or as_of.isoformat()}
        evidence.append(ev)
    evidence += transit_ev + infra_ev

    # 리스크 — 반대 근거를 반드시 함께 낸다.
    risks: list[dict] = []
    if school:
        risks.append({"severity": "low", "detail": "학군 배정은 변경될 수 있습니다(현재 기준)."})
    for h in hopes:
        # 착공 전 호재는 지연 가능성을 명시. 확정처럼 쓰지 않는다.
        if h.confidence <= 0.4:
            risks.append({
                "severity": "medium",
                "detail": f"{h.name}은(는) '{h.status}' 단계로 개통 시기가 지연될 수 있습니다"
                          f"(신뢰도 {h.confidence}).",
            })
    for p in screen.penalties:
        risks.append({
            "severity": p["severity"],
            "detail": f"{p['label']} {p['distance_m']:.0f}m — 현장 확인 필요.",
        })

    missing = tuple(school_missing)

    # 판정 문구
    if screen.excluded:
        verdict = "기피 조건 해당 — 제외 권고"
        rationale = "; ".join(screen.exclusion_reasons)
        # 제외 대상은 스코어를 신뢰 근거로 쓰지 않는다.
        confidence = 0.6
    elif score is None:
        verdict = "판단 보류"
        rationale = "입지 판단에 쓸 실측 데이터가 부족합니다."
        confidence = 0.0
    else:
        avail = sum(1 for v in components.values() if v is not None)
        confidence = round(0.6 + 0.08 * avail, 2)   # 최대 0.84 — 배정 변경 여지 감안
        bits = []
        if transit.get("nearest_station"):
            ns = transit["nearest_station"]
            bits.append(f"{ns['name']} {ns['distance_m']:.0f}m")
        if school:
            cross = "대로 횡단 있음" if school.get("crosses_main_road") else "대로 횡단 없이"
            dist = school.get("distance_m")
            dtxt = f" {dist:.0f}m" if dist is not None else ""
            bits.append(f"{school['assigned_elementary']} 학구도 내부({cross}{dtxt})")
        if amenities:
            bits.append("생활 인프라 " + ", ".join(
                f"{k.replace('_m','')} {v:.0f}m" for k, v in amenities.items()))
        rationale = "입지 점수 " + f"{score}점 — " + "; ".join(bits) + "." if bits \
            else f"입지 점수 {score}점."
        if screen.penalties:
            rationale += " 감점요소: " + ", ".join(
                f"{p['label']} {p['distance_m']:.0f}m" for p in screen.penalties) + "."
        verdict = "입지 양호" if score >= 70 else ("입지 보통" if score >= 45 else "입지 미흡")

    return LocationAssessment(
        score=score, confidence=confidence, verdict=verdict, rationale=rationale,
        school=school, transit=transit, amenities=amenities,
        penalties=screen.penalties, hopes=hopes,
        evidence=tuple(evidence), risks=tuple(risks),
        excluded=screen.excluded, exclusion_reasons=screen.exclusion_reasons,
        missing=missing,
    )


# ---------------------------------------------------------------------------
# F4 §D — 동별 추정 (좌표 기반, 신뢰도 낮게, 금액 환산 금지)
# ---------------------------------------------------------------------------

#: 동별 추정 신뢰도 — 좌표 기반이므로 절대 상한.
BUILDING_ESTIMATE_CONFIDENCE = 0.5
BUILDING_ESTIMATE_BASIS = "estimated_from_location"


def _building_raw_score(b: BuildingLocationFact) -> float | None:
    parts: list[float] = []
    if b.station_distance_m is not None:
        parts.append(_proximity_score(b.station_distance_m, *PROXIMITY_BANDS["station"]))
    if b.school_distance_m is not None and b.school_in_district:
        parts.append(_proximity_score(b.school_distance_m, *PROXIMITY_BANDS["school"]))
    if b.park_distance_m is not None:
        parts.append(_proximity_score(b.park_distance_m, *PROXIMITY_BANDS["park"]))
    if b.main_road_distance_m is not None:
        # 간선도로는 가까울수록 나쁘다 → 근접 점수를 반전.
        prox = _proximity_score(b.main_road_distance_m, 30, 300)
        if prox is not None:
            parts.append(100.0 - prox)
    parts = [p for p in parts if p is not None]
    return round(sum(parts) / len(parts), 1) if parts else None


def estimate_buildings(
    buildings: Sequence[BuildingLocationFact],
) -> list[BuildingEstimate]:
    """동별 상대 입지 점수. **상대값만** 낸다 — 금액으로 환산하지 않는다.

    "105동은 101동 대비 역까지 220m 가깝습니다" 까지가 허용 범위다.
    (docs/02-design/agents/03-valuation-trader.md §D)
    """
    scored = [(b, _building_raw_score(b)) for b in buildings]
    usable = [(b, s) for b, s in scored if s is not None]
    if len(usable) < 2:
        # 비교 대상이 없으면 상대 점수를 만들지 않는다(단일 동 비교는 무의미).
        return []

    raws = [s for _, s in usable]
    lo, hi = min(raws), max(raws)
    span = hi - lo
    # 비교 근거용 평균 거리
    def _mean(attr: str) -> float | None:
        vals = [getattr(b, attr) for b, _ in usable if getattr(b, attr) is not None]
        return sum(vals) / len(vals) if vals else None

    mean_station = _mean("station_distance_m")
    mean_road = _mean("main_road_distance_m")

    out: list[BuildingEstimate] = []
    for b, s in usable:
        rel = 0.5 if span == 0 else round((s - lo) / span, 3)
        factors: list[str] = []
        if b.station_distance_m is not None and mean_station is not None:
            diff = mean_station - b.station_distance_m
            if diff >= 50:
                factors.append(f"지하철 {abs(diff):.0f}m 근접")
            elif diff <= -50:
                factors.append(f"지하철 {abs(diff):.0f}m 멀음")
        if b.main_road_distance_m is not None and mean_road is not None:
            if b.main_road_distance_m <= HAZARD_RADIUS_M["main_road_noise"]:
                factors.append("간선도로 인접 소음 우려")
        if b.position_in_complex:
            factors.append(f"단지 {b.position_in_complex} 배치")
        out.append(BuildingEstimate(
            building_id=b.building_id, label=b.label, relative_score=rel,
            confidence=BUILDING_ESTIMATE_CONFIDENCE,      # ≤ 0.6 강제
            basis=BUILDING_ESTIMATE_BASIS,
            factors=tuple(factors),
        ))
    return out
