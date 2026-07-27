"""학구도 적재 실증 — "적재했다"로 끝내지 않기 위한 스크립트.

    python scripts/verify_school_district.py --sample 200

무엇을 숫자로 보이는가
----------------------
① **급별 활성화율** — 단지 몇 %에서 초등 통학구역 / 중·고 학교군이 실제로 나오는가.
② **'미확보'와 '미포함'의 구분이 살아 있는가** — 이게 깨지면 거리 대체가 시작된다.
   · 포함     : ST_Contains → `in_district=True`
   · 미포함   : 주변에 학구도는 있는데 어느 구역에도 안 들어감 → **단정하지 않음**
   · 미확보   : 주변 5km 에 그 급의 학구도 자체가 없음 → 학군 항목을 비움
   어느 경우도 최근접 학교 거리로 대체하지 않는다(analysis.assess_school*).
③ **입지 점수 전/후** — 같은 단지를 학구도 있는 그대로 / 없는 셈 치고 각각 평가해
   school 축(가중치 0.35)이 점수를 실제로 얼마나 움직였는지 본다.
④ **급별 문구 검증** — 중·고 근거에 '배정'이라는 단정이 섞이지 않았는가.
   초등 통학구역과 중·고 학교군은 뜻이 다르다(ingest/school_zone.py ⚠️).

왜 '전'을 이렇게 만드나
-----------------------
적재를 되돌려 재보는 건 실데이터에 위험하다. 대신 리포지토리가 돌려준 사실에서
학군만 떼어(`district_data_available=False`) 도메인을 다시 호출한다 —
적재 이전의 입력과 **정확히 같은 상태**다(그때도 school_district 가 0행이었으므로).
"""
from __future__ import annotations

import argparse
import dataclasses
import logging
import sys

import _common  # noqa: F401  (import 부작용: 로깅 억제·마스킹 설치)
from _common import load_env, make_engine

from app.domain.location.analysis import evaluate_location
from app.domain.location.models import LocationFacts, SchoolFact
from app.ingest.school_zone import ELEMENTARY, HIGH, MIDDLE
from app.repositories.postgis import PostgisRepository

logger = logging.getLogger("scripts.verify_school_district")

#: 리포지토리의 `_DISTRICT_DATA_RADIUS_M` 과 같은 값을 도 단위로 (대략 5km).
_DISTRICT_DEG = 0.05

#: ⚠️ 급을 반드시 걸러서 센다. 안 걸면 중·고가 있는 지역이 전부
#:    '초등 학구도 포함'으로 잡혀 활성화율이 부풀려진다.
_CLASSIFY_SQL = """
SELECT CASE
         WHEN c.geom IS NULL THEN 'no_geom'
         WHEN EXISTS (SELECT 1 FROM school_district sd
                       WHERE sd.geom && c.geom AND ST_Contains(sd.geom, c.geom)
                         AND sd.school_level = :level)
              THEN 'in_district'
         WHEN EXISTS (SELECT 1 FROM school_district sd
                       WHERE sd.geom && ST_Expand(c.geom,
                             CAST(:deg AS double precision))
                         AND sd.school_level = :level)
              THEN 'outside_district'
         ELSE 'no_data'
       END AS bucket,
       count(*) AS n
FROM complex c
GROUP BY 1
"""

#: 적재 결과를 원천 행수와 대조하기 위한 집계(조용한 유실 탐지).
_INVENTORY_SQL = """
SELECT COALESCE(sd.school_level, '(급 미상)') AS level,
       COALESCE(sd.zone_kind, '(종류 미상)')  AS kind,
       count(*)                                AS districts,
       count(sd.school_poi_id)                 AS with_single_school,
       COALESCE(sum(m.n), 0)                   AS members
FROM school_district sd
LEFT JOIN LATERAL (
    SELECT count(*) AS n FROM school_district_member x WHERE x.district_id = sd.id
) m ON true
GROUP BY 1, 2
ORDER BY 1, 2
"""

_SAMPLE_SQL = """
SELECT c.id, c.name
FROM complex c
WHERE c.geom IS NOT NULL
ORDER BY c.id
LIMIT CAST(:limit AS int)
"""

#: 학구도 밖에 있는 단지(미포함)를 몇 개 뽑아 실제 판정을 보여 준다.
_OUTSIDE_SQL = """
SELECT c.id, c.name
FROM complex c
WHERE c.geom IS NOT NULL
  AND NOT EXISTS (SELECT 1 FROM school_district sd
                   WHERE sd.geom && c.geom AND ST_Contains(sd.geom, c.geom)
                     AND sd.school_level = :level)
ORDER BY c.id
LIMIT CAST(:limit AS int)
"""

#: 급별 라벨. **초등만 '배정'이라는 낱말을 쓴다** — 중·고 학교군은 배정을 말하지 않는다.
_LABEL = {
    ELEMENTARY: {
        "in_district": "통학구역 포함 (배정 또는 공동학구 후보)",
        "outside_district": "통학구역 미포함 (데이터는 있음 · 단정 안 함)",
        "no_data": "통학구역 미확보 (학군 항목 비움)",
        "no_geom": "단지 좌표 없음 (공간판정 불가)",
    },
    "group": {
        "in_district": "학교군 포함 (배정 후보 범위 · 배정 아님)",
        "outside_district": "학교군 미포함 (데이터는 있음 · 단정 안 함)",
        "no_data": "학교군 미확보 (학군 항목 비움)",
        "no_geom": "단지 좌표 없음 (공간판정 불가)",
    },
}


def _labels(level: str) -> dict[str, str]:
    return _LABEL[ELEMENTARY] if level == ELEMENTARY else _LABEL["group"]


def _without_school(facts: LocationFacts) -> LocationFacts:
    """학구도 적재 **이전** 상태의 사실. 학군 3종을 모두 '미확보'로 되돌린다."""
    return dataclasses.replace(
        facts,
        school=SchoolFact(district_data_available=False),
        middle_school=SchoolFact(level=MIDDLE, district_data_available=False),
        high_school=SchoolFact(level=HIGH, district_data_available=False))


def classify(engine, level: str) -> dict[str, int]:
    from sqlalchemy import text

    with engine.connect() as conn:
        rows = conn.execute(text(_CLASSIFY_SQL),
                            {"deg": _DISTRICT_DEG, "level": level}).all()
    return {r.bucket: r.n for r in rows}


def inventory(engine) -> list:
    """적재 재고. **원천 행수와 대조**하기 위한 값이다(조용한 유실 탐지)."""
    from sqlalchemy import text

    with engine.connect() as conn:
        return conn.execute(text(_INVENTORY_SQL)).all()


def show_examples(repo: PostgisRepository, engine, *, limit: int) -> int:
    """급별 판정이 실제로 나오는 단지 예시. **문구까지** 보여 준다."""
    from sqlalchemy import text

    with engine.connect() as conn:
        rows = conn.execute(text(_SAMPLE_SQL), {"limit": limit}).all()

    shown = 0
    for row in rows:
        facts = repo.location_facts(row.id)
        if facts is None or facts.school is None or not facts.school.in_district:
            continue
        school = facts.school
        before = evaluate_location(_without_school(facts))
        after = evaluate_location(facts)
        print(f"  [{row.id}] {row.name}")
        co = (f" · 공동학구 후보 {school.candidate_count}곳"
              if (school.candidate_count or 0) > 1 else " · 단일 배정")
        print(f"      초등 통학구역 : {school.name} · {school.distance_m:.0f}m{co}")
        for fact in (facts.middle_school, facts.high_school):
            if fact is None or not fact.in_district:
                label = "미포함" if (fact and fact.district_data_available) else "미확보"
                print(f"      {(fact.level if fact else '중·고'):>6} 학교군 : {label}")
                continue
            print(f"      {fact.level:>6} 학교군 : {fact.zone_name}"
                  f" · 후보 {fact.candidate_count}곳"
                  f" · 최근접 {fact.name} {fact.distance_m:.0f}m")
        print(f"      입지 점수     : {before.score} -> {after.score} (학군 축 반영)")
        for ev in after.evidence:
            if "학교군" in ev["claim"] or "학구도" in ev["claim"]:
                print(f"      근거          : {ev['claim']}")
        shown += 1
        if shown >= 5:
            break
    return shown


def show_outside(repo: PostgisRepository, engine, *, limit: int = 3) -> None:
    """미포함 단지가 **거리로 대체되지 않는지** 확인한다."""
    from sqlalchemy import text

    with engine.connect() as conn:
        rows = conn.execute(text(_OUTSIDE_SQL),
                            {"limit": limit, "level": ELEMENTARY}).all()
    if not rows:
        print("  (학구도 밖 단지 없음)")
        return
    for row in rows:
        facts = repo.location_facts(row.id)
        if facts is None:
            continue
        school = facts.school
        assessment = evaluate_location(facts)
        print(f"  [{row.id}] {row.name}")
        print(f"      SchoolFact  : in_district={school.in_district} "
              f"data_available={school.district_data_available} name={school.name!r}")
        print(f"      미확보 사유 : {list(assessment.missing)}")
        assert school.name is None, "미포함인데 학교 이름이 붙었다 — 거리 대체 의심"


def score_delta(repo: PostgisRepository, engine, *, limit: int) -> None:
    """전/후 점수 차이의 분포."""
    from sqlalchemy import text

    with engine.connect() as conn:
        rows = conn.execute(text(_SAMPLE_SQL), {"limit": limit}).all()

    deltas: list[float] = []
    active = {ELEMENTARY: 0, MIDDLE: 0, HIGH: 0}
    for row in rows:
        facts = repo.location_facts(row.id)
        if facts is None:
            continue
        before = evaluate_location(_without_school(facts))
        after = evaluate_location(facts)
        for level, fact in ((ELEMENTARY, facts.school), (MIDDLE, facts.middle_school),
                            (HIGH, facts.high_school)):
            if fact and fact.in_district:
                active[level] += 1
        if before.score is not None and after.score is not None:
            deltas.append(round(after.score - before.score, 1))

    if not deltas:
        print("  비교 가능한 단지가 없습니다")
        return
    changed = [d for d in deltas if d != 0]
    print(f"  표본 {len(deltas)}개 · 학군 축 활성 — "
          + " · ".join(f"{lv} {n}개({n / len(deltas) * 100:.1f}%)"
                       for lv, n in active.items()))
    print(f"  점수 변화 있음 {len(changed)}개 "
          f"· 평균 {sum(deltas) / len(deltas):+.2f}점 "
          f"· 최소 {min(deltas):+.1f} / 최대 {max(deltas):+.1f}")


def check_wording(repo: PostgisRepository, engine, *, limit: int) -> int:
    """★ 급별 문구 검증 — 중·고 근거에 '배정' 단정이 섞이면 **실패로 끝낸다.**

    이건 취향 문제가 아니다. "○○중학교 학구도 내부"는 그 중학교에 간다는 뜻인데
    학교군 데이터는 그걸 말하지 않는다. 리포트에 나가는 문장이 곧 주장이므로
    적재 검증에서 문장까지 본다.
    """
    from sqlalchemy import text

    banned = ("배정 중학교", "배정 고등학교", "배정중학교", "배정고등학교")
    with engine.connect() as conn:
        rows = conn.execute(text(_SAMPLE_SQL), {"limit": limit}).all()

    checked = violations = 0
    for row in rows:
        facts = repo.location_facts(row.id)
        if facts is None:
            continue
        after = evaluate_location(facts)
        for block, level in ((after.middle_school, MIDDLE), (after.high_school, HIGH)):
            if not block:
                continue
            checked += 1
            if any(k.startswith("assigned") for k in block):
                print(f"  ✗ [{row.id}] {level} 판정에 assigned_* 키가 있습니다: {block}")
                violations += 1
        for ev in after.evidence:
            claim = ev["claim"]
            if any(b in claim for b in banned):
                print(f"  ✗ [{row.id}] 근거에 배정 단정: {claim}")
                violations += 1
            if "학교군" in claim and "배정 방식 미확인" not in claim:
                print(f"  ✗ [{row.id}] 학교군 근거에 배정 방식 표기 없음: {claim}")
                violations += 1
    print(f"  학교군 판정 {checked}건 검사 · 위반 {violations}건")
    return violations


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="학구도 적재 실증")
    ap.add_argument("--sample", type=int, default=200, help="점수 비교 표본 수")
    args = ap.parse_args(argv)

    load_env()
    engine = make_engine()
    repo = PostgisRepository(engine)

    print("=== ⓪ 적재 재고 (원천 행수와 대조하라) ===")
    for row in inventory(engine):
        print(f"  {row.level:>8} / {row.kind:>10} — 구역 {row.districts:>6,}"
              f" · 배정학교(단수) {row.with_single_school:>6,}"
              f" · 후보 연결 {row.members:>6,}")

    for level in (ELEMENTARY, MIDDLE, HIGH):
        buckets = classify(engine, level)
        labels = _labels(level)
        total = sum(buckets.values())
        print(f"\n=== ① 단지별 상태 — {level} ===")
        for key in ("in_district", "outside_district", "no_data", "no_geom"):
            n = buckets.get(key, 0)
            print(f"  {labels[key]:44s} {n:6,d}  ({n / total * 100:5.2f}%)")
        active = buckets.get("in_district", 0)
        print(f"  -> 활성화율 {active:,}/{total:,} = {active / total * 100:.2f}%")

    print("\n=== ② 급별 실호출 예시 ===")
    shown = show_examples(repo, engine, limit=args.sample)
    if not shown:
        print("  ⚠️ 판정이 나오는 단지가 하나도 없습니다 — 적재를 확인하세요")
        return 1

    print("\n=== ③ '미포함'은 거리로 대체되지 않는다 (초등) ===")
    show_outside(repo, engine)

    print("\n=== ④ 입지 점수 전/후 ===")
    score_delta(repo, engine, limit=args.sample)

    print("\n=== ⑤ 급별 문구 검증 (중·고에 '배정' 단정 금지) ===")
    if check_wording(repo, engine, limit=args.sample):
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
